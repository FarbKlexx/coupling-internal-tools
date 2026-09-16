<template>
  <v-overlay
    :model-value="true"
    class="flex items-center justify-center"
    scrim="#000000"
    opacity="0.6"
    @click:outside="emit('close')"
    @keydown.esc="emit('close')"
  >
    <div class="w-[34rem] max-w-[90vw] content-box p-6 space-y-4">
      <div class="flex items-start justify-between gap-4">
        <div class="space-y-1">
          <h2 class="text-lg font-semibold">
            {{ entry ? "Betrieb bearbeiten" : "Betrieb von Hand anlegen" }}
          </h2>
          <p class="text-xs text-zinc-500">
            <template v-if="entry">
              Geändert wird der Kontakt in der Telefonakquise. Eine neue Adresse schreibt dort eine
              Richtigstellung ins Protokoll – der Nachweis muss nennen, für welche Adresse die
              Zusage gilt.
            </template>
            <template v-else>
              Für die, die niemand angerufen hat. Der Betrieb wird als Zusage angelegt und steht ab
              sofort hier in der Liste – mit Protokolleintrag in der Telefonakquise, wie jede andere
              Zusage auch.
            </template>
          </p>
        </div>
        <button
          type="button"
          class="shrink-0 light-grey-text hover:text-strong transition-colors"
          aria-label="Schließen"
          @click="emit('close')"
        >
          <span class="material-symbols-outlined">close</span>
        </button>
      </div>

      <!-- Der Befund zur schon bekannten Nummer steht mit seinem eigenen
           Knopf da: erst die Auskunft, wo sie steht, dann die ausdrückliche
           Bestätigung. Dasselbe Verfahren wie beim Löschen einer Liste. -->
      <div
        v-if="conflict"
        class="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200"
      >
        <p>{{ conflict }}</p>
        <button type="button" class="chip" data-force :disabled="isBusy" @click="submit(true)">
          <span class="material-symbols-outlined" style="font-size: 16px">warning</span>
          Trotzdem anlegen
        </button>
      </div>

      <p
        v-else-if="errorMessage"
        class="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200"
      >
        {{ errorMessage }}
      </p>

      <div class="grid grid-cols-2 gap-3">
        <div class="col-span-2 flex flex-col gap-1">
          <label class="text-xs text-zinc-500" :for="`${id}-betrieb`">Betrieb *</label>
          <input
            :id="`${id}-betrieb`"
            ref="firstField"
            v-model="form.betrieb"
            type="text"
            :maxlength="MAX_NAME"
            class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
            @keydown.enter.prevent="submit(false)"
          />
        </div>

        <div class="col-span-2 flex flex-col gap-1">
          <label class="text-xs text-zinc-500" :for="`${id}-email`">E-Mail *</label>
          <input
            :id="`${id}-email`"
            v-model="form.email"
            type="email"
            :maxlength="MAX_EMAIL"
            class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
            @keydown.enter.prevent="submit(false)"
          />
        </div>

        <!-- Freiwillig, aber die einzige Angabe, mit der die Doppelprüfung
             gegen Listen und Blacklist arbeiten kann – und die, die man im
             Reiter „Nachfassen" braucht. -->
        <div class="col-span-2 flex flex-col gap-1">
          <label class="text-xs text-zinc-500" :for="`${id}-telefon`">
            Telefon – empfohlen: hält den Betrieb aus der nächsten Anrufliste heraus
          </label>
          <input
            :id="`${id}-telefon`"
            v-model="form.telefon"
            type="tel"
            :maxlength="MAX_NAME"
            class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
            @keydown.enter.prevent="submit(false)"
          />
        </div>

        <div class="flex flex-col gap-1">
          <label class="text-xs text-zinc-500" :for="`${id}-plz`">PLZ</label>
          <input
            :id="`${id}-plz`"
            v-model="form.plz"
            type="text"
            :maxlength="MAX_NAME"
            class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        <div class="flex flex-col gap-1">
          <label class="text-xs text-zinc-500" :for="`${id}-ort`">Ort</label>
          <input
            :id="`${id}-ort`"
            v-model="form.ort"
            type="text"
            :maxlength="MAX_NAME"
            class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        <div class="flex flex-col gap-1">
          <label class="text-xs text-zinc-500" :for="`${id}-website`">Website</label>
          <input
            :id="`${id}-website`"
            v-model="form.website"
            type="text"
            :maxlength="MAX_NAME"
            class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        <div class="flex flex-col gap-1">
          <label class="text-xs text-zinc-500" :for="`${id}-gewerk`">Gewerk</label>
          <input
            :id="`${id}-gewerk`"
            v-model="form.gewerk"
            type="text"
            :maxlength="MAX_NAME"
            class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        <!-- Mehrzeilig wie jede Anmerkung in dieser Anwendung: woher der
             Kontakt kommt, ist selten ein Satz. -->
        <div class="col-span-2 flex flex-col gap-1">
          <label class="text-xs text-zinc-500" :for="`${id}-note`">
            Anmerkung – woher kommt der Kontakt, was wurde besprochen
          </label>
          <textarea
            :id="`${id}-note`"
            v-model="form.note"
            rows="3"
            :maxlength="MAX_NOTE"
            class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors resize-y"
          />
        </div>
      </div>

      <div class="flex items-center justify-end gap-2 pt-1">
        <button
          type="button"
          class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm hover:text-strong transition-colors"
          :disabled="isBusy"
          @click="emit('close')"
        >
          Abbrechen
        </button>
        <button
          type="button"
          class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-40 transition-colors"
          data-submit
          :disabled="!isComplete || isBusy"
          @click="submit(false)"
        >
          {{ entry ? "Speichern" : "Anlegen" }}
        </button>
      </div>
    </div>
  </v-overlay>
</template>

<script setup lang="ts">
/**
 * Das Formular für einen von Hand erfassten Betrieb – anlegen wie ändern.
 *
 * Beides dasselbe Formular, weil es dieselben Felder sind; was sich
 * unterscheidet, ist die Überschrift, der Knopf und was das Backend daraus
 * macht. Ein zweites Formular für das Ändern wäre eine zweite Stelle, an der
 * ein neues Feld nachgetragen werden müsste.
 *
 * Pflicht sind Betrieb und E-Mail: die Zeile existiert, damit eine Mail
 * hinausgeht. Die Nummer ist freiwillig, aber die einzige Angabe, mit der
 * die Doppelprüfung gegen Listen und Blacklist arbeiten kann – steht sie
 * schon irgendwo, antwortet das Backend mit 409, und der Befund erscheint
 * hier mitsamt dem Knopf, der ihn übergeht.
 *
 * Die Prüfung selbst steht im Backend. Hier wird nur so viel geprüft, dass
 * der Knopf nicht klickbar ist, solange offensichtlich etwas fehlt.
 */
import { computed, onMounted, ref, useId } from "vue";
import { emptyManualEntry, type MailEntry, type ManualEntry } from "@/api/mail_followup.api";

/** Gespiegelt aus backend/app/schemas/mail_followup.py. */
const MAX_NAME = 200;
const MAX_EMAIL = 254;
const MAX_NOTE = 2000;

const props = defineProps<{
  /** `null` = neuer Betrieb; sonst die Zeile, die geändert wird. */
  entry: MailEntry | null;
  isBusy: boolean;
  /** Die Meldung zur schon bekannten Nummer (409), oder `null`. */
  conflict: string | null;
  /** Jede andere Fehlermeldung des Backends. */
  errorMessage: string | null;
}>();

const emit = defineEmits<{
  (event: "close"): void;
  (event: "submit", value: ManualEntry): void;
}>();

/** Eigene ID je Instanz: Label und Feld müssen zusammenfinden. */
const id = useId();

const form = ref<ManualEntry>(
  props.entry
    ? {
        betrieb: props.entry.betrieb,
        email: props.entry.email,
        telefon: props.entry.telefon,
        plz: props.entry.plz,
        ort: props.entry.ort,
        website: props.entry.website,
        gewerk: props.entry.gewerk,
        // Die Anmerkung aus dem Telefonat – beim erfassten Betrieb ist es
        // die, die beim Anlegen geschrieben wurde. Die Versand-Anmerkung
        // daneben gehört der Zeile und nicht dem Betrieb.
        note: props.entry.note,
      }
    : emptyManualEntry(),
);

const firstField = ref<HTMLInputElement | null>(null);

onMounted(() => firstField.value?.focus());

const isComplete = computed(
  () => form.value.betrieb.trim().length > 0 && form.value.email.trim().length > 0,
);

function submit(force: boolean) {
  if (!isComplete.value || props.isBusy) return;

  emit("submit", { ...form.value, force });
}
</script>
