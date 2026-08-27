<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type {
  CallContact,
  CallCounters,
  CallOutcome,
  OutcomeInfo,
  OutcomePayload,
} from "@/api/call_list.api";

const props = defineProps<{
  contact: CallContact | null;
  counters: CallCounters | null;
  outcomes: OutcomeInfo[];
  nextDueAt: string | null;
  hasLists: boolean;
  isSaving: boolean;
  isWaiting: boolean;
  isDone: boolean;
}>();

const emit = defineEmits<{
  (event: "answer", contactId: string, payload: OutcomePayload): void;
}>();

/**
 * Symbol pro Ergebnis. Beschriftung und Beschreibung kommen aus der Antwort
 * des Backends – hier steht nur, was reine Darstellung ist.
 */
const ICONS: Record<CallOutcome, string> = {
  zugesagt: "mark_email_read",
  nicht_erreichbar: "phone_missed",
  rueckruf: "event",
  abgelehnt: "block",
  nummer_falsch: "wrong_location",
};

/** Eingaben des Anrufers zum laufenden Gespräch. */
const email = ref("");
const note = ref("");

/** Welches Ergebnis wartet gerade auf einen Zeitpunkt? */
const pending = ref<OutcomeInfo | null>(null);
const customTime = ref("");

const details = ref(false);
const history = ref(false);

/**
 * Beim Wechsel des Kontakts wird das Formular geleert.
 *
 * Ohne das wandert die Anmerkung des vorigen Gesprächs zum nächsten Betrieb –
 * und landet dort im Protokoll.
 */
watch(
  () => props.contact?.id,
  () => {
    email.value = props.contact?.email ?? "";
    note.value = "";
    pending.value = null;
    customTime.value = "";
    details.value = false;
    history.value = false;
  },
  { immediate: true },
);

const emailChanged = computed(() => email.value.trim() !== (props.contact?.email ?? ""));

/** Datum und Uhrzeit für die Anzeige – die Zeitzone kennt der Browser. */
function formatMoment(iso: string | null): string {
  if (!iso) return "";

  const stamp = new Date(iso);
  if (Number.isNaN(stamp.getTime())) return iso;

  return stamp.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatClock(iso: string | null): string {
  if (!iso) return "";

  const stamp = new Date(iso);
  if (Number.isNaN(stamp.getTime())) return iso;

  return stamp.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

/** Wert für ein `datetime-local`-Feld – lokale Zeit, ohne Zeitzone. */
function toLocalInput(stamp: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");

  return (
    `${stamp.getFullYear()}-${pad(stamp.getMonth() + 1)}-${pad(stamp.getDate())}` +
    `T${pad(stamp.getHours())}:${pad(stamp.getMinutes())}`
  );
}

/**
 * Morgen früh um 8 – das häufigste „später" bei Handwerksbetrieben.
 *
 * Wird lokal gerechnet und als ISO-Zeitstempel *mit* Zeitzone geschickt: das
 * Backend hat keine Zeitzonendatenbank und soll auch keine brauchen.
 */
function tomorrowMorning(): Date {
  const stamp = new Date();
  stamp.setDate(stamp.getDate() + 1);
  stamp.setHours(8, 0, 0, 0);
  return stamp;
}

/** Was bei jedem Ergebnis mitgeschickt wird. */
function basePayload(): Pick<OutcomePayload, "note" | "email"> {
  return {
    note: note.value.trim(),
    // Nur mitschicken, wenn wirklich etwas geändert wurde: ein fehlendes Feld
    // heißt im Backend „unverändert" und lässt eine bekannte Adresse in Ruhe.
    ...(emailChanged.value ? { email: email.value.trim() } : {}),
  };
}

function pick(outcome: OutcomeInfo) {
  if (!props.contact || props.isSaving) return;

  if (outcome.time_input === "none") {
    emit("answer", props.contact.id, { outcome: outcome.id, ...basePayload() });
    return;
  }

  // Es fehlt noch ein Zeitpunkt – die Auswahl klappt darunter auf.
  pending.value = outcome;
  customTime.value = toLocalInput(
    outcome.time_input === "appointment"
      ? new Date(Date.now() + 60 * 60 * 1000)
      : tomorrowMorning(),
  );
}

function submitSnooze(minutes: number) {
  if (!props.contact) return;

  emit("answer", props.contact.id, {
    outcome: "nicht_erreichbar",
    snooze_minutes: minutes,
    ...basePayload(),
  });
}

function submitMoment(stamp: Date) {
  if (!props.contact || !pending.value) return;

  const payload: OutcomePayload = { outcome: pending.value.id, ...basePayload() };

  // Beim Rückruf ist der Zeitpunkt der *Termin*; das Backend zieht davon den
  // Vorlauf ab. Bei der Wiedervorlage ist er direkt der Zeitpunkt der Rückkehr.
  if (pending.value.time_input === "appointment") {
    payload.appointment_at = stamp.toISOString();
  } else {
    payload.due_at = stamp.toISOString();
  }

  emit("answer", props.contact.id, payload);
}

function submitCustom() {
  if (!customTime.value) return;

  const stamp = new Date(customTime.value);
  if (Number.isNaN(stamp.getTime())) return;

  submitMoment(stamp);
}

function toneClass(tone: OutcomeInfo["tone"]): string {
  if (tone === "positive") return "outcome outcome--positive";
  if (tone === "negative") return "outcome outcome--negative";
  return "outcome";
}
</script>

<template>
  <div class="space-y-4">
    <!-- Zähler -->
    <div v-if="counters" class="flex flex-wrap items-stretch gap-3">
      <div class="rounded-xl border light-grey-background light-grey-stroke px-5 py-3 min-w-36">
        <p class="eyebrow">Noch anzurufen</p>
        <p class="text-3xl font-semibold leading-tight">{{ counters.offen }}</p>
      </div>
      <div class="rounded-xl border light-grey-background light-grey-stroke px-4 py-3">
        <p class="eyebrow">Wiedervorlage</p>
        <p class="text-xl font-semibold leading-tight">{{ counters.wiedervorlage }}</p>
        <p v-if="nextDueAt" class="text-xs text-zinc-500">ab {{ formatClock(nextDueAt) }}</p>
      </div>
      <div class="rounded-xl border light-grey-background light-grey-stroke px-4 py-3">
        <p class="eyebrow">Zusagen</p>
        <p class="text-xl font-semibold leading-tight text-emerald-400">
          {{ counters.zugesagt }}
        </p>
        <p v-if="counters.zugesagt_ohne_email" class="text-xs text-amber-400">
          {{ counters.zugesagt_ohne_email }} ohne Adresse
        </p>
      </div>
      <div class="rounded-xl border light-grey-background light-grey-stroke px-4 py-3">
        <p class="eyebrow">Abgelehnt</p>
        <p class="text-xl font-semibold leading-tight">{{ counters.abgelehnt }}</p>
      </div>
      <div
        v-if="counters.ungueltig"
        class="rounded-xl border light-grey-background light-grey-stroke px-4 py-3"
      >
        <p class="eyebrow">Nummer falsch</p>
        <p class="text-xl font-semibold leading-tight">{{ counters.ungueltig }}</p>
      </div>
    </div>

    <!-- Kein Kontakt: die Gründe auseinandergehalten -->
    <div
      v-if="!contact"
      class="max-w-2xl rounded-xl border light-grey-background light-grey-stroke p-6 space-y-2"
    >
      <template v-if="!hasLists">
        <h2 class="text-lg font-semibold">Noch keine Anrufliste hinterlegt</h2>
        <p class="text-sm light-grey-text">
          Sobald eine Liste hochgeladen ist, erscheint hier immer genau ein Betrieb zum Anrufen.
          Hochladen kann das ein Administrator.
        </p>
      </template>
      <template v-else-if="isWaiting">
        <h2 class="text-lg font-semibold">Gerade nichts zu tun</h2>
        <p class="text-sm light-grey-text">
          Alle offenen Kontakte liegen auf Wiedervorlage. Der nächste ist ab
          <strong>{{ formatMoment(nextDueAt) }}</strong> wieder dran – die Seite holt ihn von
          selbst.
        </p>
      </template>
      <template v-else-if="isDone">
        <h2 class="text-lg font-semibold">Liste abgearbeitet</h2>
        <p class="text-sm light-grey-text">
          Kein offener Kontakt mehr. {{ counters?.zugesagt ?? 0 }} Zusagen stehen im Export für den
          Mailversand.
        </p>
      </template>
      <template v-else>
        <h2 class="text-lg font-semibold">Nichts zu tun</h2>
        <p class="text-sm light-grey-text">Es ist kein Kontakt offen.</p>
      </template>
    </div>

    <!-- Der Kontakt -->
    <div
      v-else
      class="max-w-3xl rounded-xl border light-grey-background light-grey-stroke p-6 space-y-5"
    >
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="space-y-1">
          <h2 class="text-2xl font-semibold leading-tight">{{ contact.betrieb }}</h2>
          <p class="text-xs text-zinc-500">
            {{ contact.list_name }}
            <template v-if="contact.gewerk"> · {{ contact.gewerk }}</template>
            <template v-if="contact.plz || contact.ort">
              · {{ contact.plz }} {{ contact.ort }}</template
            >
          </p>
        </div>
        <span v-if="contact.prio" class="badge shrink-0">{{ contact.prio }}</span>
      </div>

      <!-- Die Nummer, groß: sie ist der Zweck dieser Seite -->
      <div class="flex flex-wrap items-center gap-4">
        <a
          :href="`tel:${contact.telefon.replace(/\s+/g, '')}`"
          class="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-lg font-semibold hover:bg-blue-500 transition-colors"
        >
          <span class="material-symbols-outlined">call</span>
          {{ contact.telefon }}
        </a>
        <a
          v-if="contact.website"
          :href="contact.website"
          target="_blank"
          rel="noopener noreferrer"
          class="flex items-center gap-1 text-sm light-grey-text hover:text-white transition-colors"
        >
          <span class="material-symbols-outlined nav-icon">open_in_new</span>
          Website ansehen
        </a>
      </div>

      <!-- Vorherige Versuche -->
      <div v-if="contact.history.length" class="space-y-1">
        <button
          class="flex items-center gap-1 text-xs light-grey-text hover:text-white transition-colors"
          @click="history = !history"
        >
          <span class="material-symbols-outlined nav-icon">
            {{ history ? "expand_less" : "expand_more" }}
          </span>
          {{ contact.history.length }} bisherige
          {{ contact.history.length === 1 ? "Eintragung" : "Eintragungen" }}
          <template v-if="contact.appointment_at">
            · Termin {{ formatMoment(contact.appointment_at) }}
          </template>
        </button>
        <ul v-if="history" class="space-y-1 text-xs light-grey-text">
          <li
            v-for="(event, index) in contact.history"
            :key="index"
            class="rounded-md grey-background light-grey-stroke px-3 py-1.5"
          >
            <span class="white-text">{{ event.outcome_label }}</span>
            · {{ formatMoment(event.occurred_at) }} · {{ event.username }}
            <template v-if="event.note"> · „{{ event.note }}“</template>
          </li>
        </ul>
      </div>

      <!-- Gesprächsaufhänger -->
      <div v-if="contact.befunde" class="rounded-md grey-background light-grey-stroke p-3">
        <p class="eyebrow mb-1">Befunde</p>
        <p class="text-sm light-grey-text whitespace-pre-line">{{ contact.befunde }}</p>
      </div>

      <!-- Alles, was in der CSV sonst noch stand -->
      <div v-if="contact.extras.length">
        <button
          class="flex items-center gap-1 text-xs light-grey-text hover:text-white transition-colors"
          @click="details = !details"
        >
          <span class="material-symbols-outlined nav-icon">
            {{ details ? "expand_less" : "expand_more" }}
          </span>
          Details aus der Liste ({{ contact.extras.length }})
        </button>
        <dl v-if="details" class="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-x-6">
          <div
            v-for="entry in contact.extras"
            :key="entry.label"
            class="flex justify-between gap-3 border-b border-zinc-800 py-1 text-xs"
          >
            <dt class="text-zinc-500 shrink-0">{{ entry.label }}</dt>
            <dd class="light-grey-text text-right break-all">{{ entry.value }}</dd>
          </div>
        </dl>
      </div>

      <!-- Was im Gespräch dazukommt -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div class="flex flex-col gap-1">
          <label class="text-sm font-medium" :for="`email-${contact.id}`">E-Mail-Adresse</label>
          <input
            :id="`email-${contact.id}`"
            v-model="email"
            type="email"
            autocomplete="off"
            placeholder="im Gespräch erfragen"
            class="w-full rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
          />
          <p v-if="!email" class="text-xs text-amber-400">
            Ohne Adresse wird aus einer Zusage keine E-Mail.
          </p>
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm font-medium" :for="`note-${contact.id}`">Anmerkungen</label>
          <textarea
            :id="`note-${contact.id}`"
            v-model="note"
            rows="2"
            placeholder="Was im Gespräch gesagt wurde"
            class="w-full rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors resize-y"
          />
        </div>
      </div>

      <!-- Ergebnis -->
      <div class="space-y-2">
        <p class="eyebrow">Ergebnis des Anrufs</p>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <button
            v-for="outcome in outcomes"
            :key="outcome.id"
            :class="[toneClass(outcome.tone), pending?.id === outcome.id ? 'outcome--armed' : '']"
            :disabled="isSaving"
            :title="outcome.description"
            @click="pick(outcome)"
          >
            <span class="material-symbols-outlined">{{ ICONS[outcome.id] }}</span>
            <span class="text-left">{{ outcome.label }}</span>
          </button>
        </div>
      </div>

      <!-- Zeitpunkt, wenn das Ergebnis einen braucht -->
      <div v-if="pending" class="rounded-md grey-background light-grey-stroke p-3 space-y-3">
        <p class="text-sm font-medium">
          {{
            pending.time_input === "appointment"
              ? "Wann ist der Rückruf verabredet?"
              : "Wann erneut anrufen?"
          }}
        </p>
        <p class="text-xs text-zinc-500">{{ pending.description }}</p>

        <div v-if="pending.time_input === 'snooze'" class="flex flex-wrap gap-2">
          <button class="chip" :disabled="isSaving" @click="submitSnooze(60)">in 1 Stunde</button>
          <button class="chip" :disabled="isSaving" @click="submitSnooze(120)">in 2 Stunden</button>
          <button class="chip" :disabled="isSaving" @click="submitMoment(tomorrowMorning())">
            morgen früh
          </button>
        </div>

        <div class="flex flex-wrap items-end gap-2">
          <div class="flex flex-col gap-1">
            <label class="text-xs text-zinc-500" for="call-custom-time">
              {{ pending.time_input === "appointment" ? "Termin" : "eigener Zeitpunkt" }}
            </label>
            <input
              id="call-custom-time"
              v-model="customTime"
              type="datetime-local"
              class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
            />
          </div>
          <button
            class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-40 transition-colors"
            :disabled="isSaving || !customTime"
            @click="submitCustom"
          >
            Übernehmen
          </button>
          <button
            class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm hover:text-white transition-colors"
            :disabled="isSaving"
            @click="pending = null"
          >
            Abbrechen
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
