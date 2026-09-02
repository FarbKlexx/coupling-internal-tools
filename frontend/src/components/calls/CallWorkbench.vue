<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { CallContact, CallCounters, OutcomeInfo, OutcomePayload } from "@/api/call_list.api";
import OutcomeChooser, { type OutcomeChoice } from "./OutcomeChooser.vue";
import { formatClock, formatMoment } from "./callTime";

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

/** Eingaben des Anrufers zum laufenden Gespräch. */
const email = ref("");
const note = ref("");

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
    details.value = false;
    history.value = false;
  },
  { immediate: true },
);

const emailChanged = computed(() => email.value.trim() !== (props.contact?.email ?? ""));

/** Was bei jedem Ergebnis mitgeschickt wird. */
function basePayload(): Pick<OutcomePayload, "note" | "email"> {
  return {
    note: note.value.trim(),
    // Nur mitschicken, wenn wirklich etwas geändert wurde: ein fehlendes Feld
    // heißt im Backend „unverändert" und lässt eine bekannte Adresse in Ruhe.
    ...(emailChanged.value ? { email: email.value.trim() } : {}),
  };
}

/**
 * Der Wähler liefert Ergebnis und Zeitpunkt, hier kommen Adresse und
 * Anmerkung dazu – beides gehört in dieselbe Protokollzeile wie die Zusage
 * selbst.
 */
function answer(choice: OutcomeChoice) {
  if (!props.contact || props.isSaving) return;

  emit("answer", props.contact.id, { ...choice, ...basePayload() });
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
        <!-- `:key` setzt den Wähler beim Wechsel des Betriebs zurück: eine
             halb aufgeklappte Zeitauswahl gehörte zum vorigen Gespräch. -->
        <OutcomeChooser
          :key="contact.id"
          :outcomes="outcomes"
          :disabled="isSaving"
          @submit="answer"
        />
      </div>
    </div>
  </div>
</template>
