<script setup lang="ts">
/**
 * Die zuletzt eingetragenen Entscheidungen – und der Weg, eine davon
 * richtigzustellen.
 *
 * Der Grund für diese Liste: am Telefon wird der falsche Knopf getroffen, und
 * ohne sie ist der Betrieb weg, sobald der nächste erscheint. Sie steht
 * deshalb unter dem Arbeitsplatz und ist für **jeden** da, der anrufen darf –
 * nicht nur für Administratoren. Wer den Fehlklick macht, merkt ihn in der
 * Sekunde danach; auf jemanden warten zu müssen hieße, dass die falsche Angabe
 * so lange im Nachweis steht.
 *
 * Richtiggestellt wird durch Anhängen, nie durch Überschreiben: das Backend
 * schreibt eine neue Protokollzeile, die auf die falsche zeigt. Die alte bleibt
 * hier sichtbar (durchgestrichen) – ein Eintrag, der bei einer Korrektur
 * stillschweigend verschwindet, wäre genau die Sorte Protokoll, die als
 * Nachweis nichts taugt.
 */
import { ref, watch } from "vue";
import type {
  CallDecision,
  CallDecisionPage,
  OutcomeInfo,
  OutcomePayload,
} from "@/api/call_list.api";
import OutcomeChooser, { type OutcomeChoice } from "./OutcomeChooser.vue";
import { formatMoment } from "./callTime";

const props = defineProps<{
  page: CallDecisionPage | null;
  outcomes: OutcomeInfo[];
  isLoading: boolean;
  isSaving: boolean;
  loadMore: () => void;
}>();

const emit = defineEmits<{
  (event: "correct", eventId: number, payload: OutcomePayload): void;
}>();

/** Welche Zeile gerade geändert wird – immer höchstens eine. */
const editing = ref<number | null>(null);
const note = ref("");
const email = ref("");

/** Die bearbeitete Zeile, wie sie jetzt vom Server kommt. */
function entryOf(eventId: number): CallDecision | undefined {
  return props.page?.entries.find((entry) => entry.event_id === eventId);
}

function open(entry: CallDecision) {
  editing.value = entry.event_id;
  // Vorbelegt mit dem, was in der Zeile steht: korrigiert wird meistens der
  // Knopf, nicht die Adresse – und was hier steht, gilt danach.
  note.value = entry.note;
  email.value = entry.email;
}

function close() {
  editing.value = null;
}

/**
 * Nach einer erfolgreichen Korrektur schließt sich der Kasten von selbst.
 *
 * Die geänderte Zeile ist danach nicht mehr `correctable` (die Korrektur ist
 * jetzt die jüngste), der Kasten bliebe also über einer Zeile stehen, an der
 * nichts mehr geht.
 */
watch(
  () => props.page,
  () => {
    if (editing.value !== null && !entryOf(editing.value)?.correctable) close();
  },
);

function submit(choice: OutcomeChoice) {
  if (editing.value === null || props.isSaving) return;

  emit("correct", editing.value, {
    ...choice,
    note: note.value.trim(),
    // Anders als beim Anruf immer mitschicken: hier steht die Adresse der
    // Zeile im Feld, und wer sie leert, meint „streichen".
    email: email.value.trim(),
  });
}

/** Farbe der Zeile nach dem, was daraus geworden ist. */
function stateClass(entry: CallDecision): string {
  if (entry.corrected) return "text-zinc-500 line-through";
  if (entry.outcome === "zugesagt") return "text-emerald-400";
  if (entry.outcome === "abgelehnt") return "text-red-400";
  return "light-grey-text";
}
</script>

<template>
  <section class="max-w-3xl space-y-2">
    <div class="flex items-baseline justify-between gap-3">
      <h3 class="text-sm font-semibold">Zuletzt eingetragen</h3>
      <p class="text-xs text-zinc-500">
        Falscher Knopf erwischt? Hier lässt sich die jeweils letzte Eintragung eines Betriebs
        ändern.
      </p>
    </div>

    <p v-if="isLoading && !page" class="text-xs light-grey-text">wird geladen …</p>

    <p v-else-if="!page?.entries.length" class="text-xs light-grey-text">
      Noch nichts eingetragen. Was hier angeklickt wird, erscheint gleich darunter.
    </p>

    <ul v-else class="space-y-1">
      <li
        v-for="entry in page.entries"
        :key="entry.event_id"
        class="rounded-md border light-grey-background light-grey-stroke px-3 py-2"
      >
        <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div class="min-w-0 text-xs light-grey-text">
            <span class="white-text font-medium">{{ entry.betrieb }}</span>
            <span :class="['ml-2', stateClass(entry)]">{{ entry.outcome_label }}</span>
            <span v-if="entry.corrects_event_id" class="ml-2 text-blue-400">· Richtigstellung</span>
          </div>
          <div class="flex shrink-0 items-center gap-2 text-xs text-zinc-500">
            <span>{{ formatMoment(entry.occurred_at) }} · {{ entry.username }}</span>
            <button
              v-if="entry.correctable"
              class="rounded-md grey-background light-grey-stroke px-2 py-1 hover:text-white transition-colors"
              :disabled="isSaving"
              @click="editing === entry.event_id ? close() : open(entry)"
            >
              {{ editing === entry.event_id ? "abbrechen" : "ändern" }}
            </button>
            <!-- Warum nicht, statt eines fehlenden Knopfes ohne Erklärung. -->
            <span
              v-else
              class="material-symbols-outlined"
              style="font-size: 16px"
              :title="entry.locked_reason"
            >
              lock
            </span>
          </div>
        </div>

        <p v-if="entry.note" class="mt-0.5 text-xs text-zinc-500 break-words">„{{ entry.note }}“</p>

        <!-- Die Richtigstellung: dieselben Knöpfe wie am Arbeitsplatz -->
        <div
          v-if="editing === entry.event_id"
          class="mt-3 space-y-3 rounded-md grey-background light-grey-stroke p-3"
        >
          <p class="text-xs text-zinc-500">
            Die alte Eintragung bleibt im Protokoll stehen; die Korrektur kommt als eigene Zeile
            daneben und trägt Ihren Namen.
          </p>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div class="flex flex-col gap-1">
              <label class="text-xs text-zinc-500" :for="`fix-email-${entry.event_id}`">
                E-Mail-Adresse
              </label>
              <input
                :id="`fix-email-${entry.event_id}`"
                v-model="email"
                type="email"
                autocomplete="off"
                class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
              />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-xs text-zinc-500" :for="`fix-note-${entry.event_id}`">
                Anmerkung
              </label>
              <input
                :id="`fix-note-${entry.event_id}`"
                v-model="note"
                type="text"
                class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
              />
            </div>
          </div>

          <OutcomeChooser
            :outcomes="outcomes"
            :disabled="isSaving"
            allow-immediate
            @submit="submit"
          />
        </div>
      </li>
    </ul>

    <button
      v-if="page && page.entries.length < page.total"
      class="text-xs light-grey-text hover:text-white transition-colors"
      :disabled="isLoading"
      @click="loadMore()"
    >
      weitere anzeigen ({{ page.entries.length }} von {{ page.total }})
    </button>
  </section>
</template>
