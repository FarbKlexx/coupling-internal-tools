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
 *
 * **Die Suche der Seite sitzt hier.** „Was war eigentlich bei Klappschmidt?"
 * ist dieselbe Frage wie „welche Eintragungen hat er?", und die Antwort soll
 * nicht nur zu lesen, sondern gleich zu korrigieren sein – die jüngste Zeile
 * eines Treffers trägt denselben Knopf wie die von vorhin. Vorher stand die
 * Suche als eigene Sektion darunter und lieferte Betriebe: derselbe Weg, nur
 * am falschen Platz und ohne den Knopf, um den es meistens geht.
 *
 * Im Suchbetrieb fällt „weitere anzeigen" weg. Es zieht das Fenster der
 * *Standardliste* auf; gesucht wird dagegen im ganzen Protokoll, und was ein
 * sinnvoller Begriff trifft, passt auf eine Seite. Steht doch mehr an, sagt
 * die Liste es und bittet um einen engeren Begriff.
 */
import { ref, watch } from "vue";
import type {
  CallDecision,
  CallDecisionPage,
  ContactState,
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
  /** Sucht nach kurzer Pause – die Verzögerung liegt im Composable. */
  search: (term: string) => void;
}>();

const emit = defineEmits<{
  (event: "correct", eventId: number, payload: OutcomePayload): void;
}>();

const query = ref("");

// Jede Eingabe geht an die Suche des Composables, die selbst wartet, bevor sie
// einen Request stellt. Ein Watcher und kein `@input`, weil neben `v-model` am
// selben Feld sonst die Reihenfolge zweier Listener entscheidet, ob `query`
// beim Aufruf schon den neuen Wert trägt.
watch(query, (term) => props.search(term));

/**
 * Farbe des *jetzigen* Zustands eines Betriebs – dieselbe Sprache wie in der
 * Versandliste: grün heißt Zusage, rot Widerspruch, bernstein „hier ist noch
 * etwas zu tun". Steht nur an einem Suchtreffer: in der Standardliste ist der
 * Zustand von eben gerade das, was die Zeile ohnehin sagt.
 */
const STATE_CLASSES: Record<ContactState, string> = {
  offen: "light-grey-text",
  wiedervorlage: "text-amber-400",
  rueckruf: "text-blue-300",
  zugesagt: "text-emerald-400",
  kein_bedarf: "text-zinc-500",
  abgelehnt: "text-red-400",
  ungueltig: "text-zinc-500",
};

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
    <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <h3 class="text-sm font-semibold">Zuletzt eingetragen</h3>
      <p class="text-xs text-zinc-500">
        Falscher Knopf erwischt? Hier lässt sich die jeweils letzte Eintragung eines Betriebs
        ändern.
      </p>
    </div>

    <!-- Die Suche gehört über diese Liste, weil sie in ihr sucht: ein Begriff
         zeigt die Eintragungen des Betriebs statt der letzten überhaupt –
         auch aus beendeten Listen. -->
    <div class="relative">
      <span
        class="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500"
        style="font-size: 18px"
      >
        search
      </span>
      <input
        v-model="query"
        type="search"
        placeholder="Betrieb, Adresse oder Nummer suchen"
        aria-label="Eintragungen durchsuchen"
        class="w-full rounded-md light-grey-background light-grey-stroke py-2 pl-10 pr-3 text-sm outline-none focus:border-blue-500 transition-colors"
      />
    </div>

    <p v-if="isLoading && !page" class="text-xs light-grey-text">wird geladen …</p>

    <!-- Zwei leere Listen mit zwei Gründen: nichts eingetragen ist der
         Anfangszustand der Seite, kein Treffer die Auskunft zu einer Suche. -->
    <p v-else-if="page?.query && !page.entries.length" class="text-xs light-grey-text">
      Keine Eintragung passt zu „{{ page.query }}“. Gesucht wird über Betrieb, Adresse und Nummer.
    </p>

    <p v-else-if="!page?.entries.length" class="text-xs light-grey-text">
      Noch nichts eingetragen. Was hier angeklickt wird, erscheint gleich darunter.
    </p>

    <p v-else-if="page.query" class="text-xs text-zinc-500">
      {{ page.total }} {{ page.total === 1 ? "Eintragung" : "Eintragungen" }} für „{{ page.query }}“
      <!-- Statt eines „weitere anzeigen": im Suchbetrieb ist eine zu weite
           Suche der Grund, nicht ein zu kleines Fenster. -->
      <template v-if="page.total > page.entries.length">
        – die ersten {{ page.entries.length }} stehen hier, bitte den Begriff verengen.
      </template>
    </p>

    <ul v-if="page?.entries.length" class="space-y-1">
      <li
        v-for="entry in page.entries"
        :key="entry.event_id"
        class="rounded-md light-grey-background px-3 py-2"
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
              class="rounded-md grey-background light-grey-stroke px-2 py-1 hover:text-strong transition-colors"
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

        <!-- Nur am Suchtreffer: wer nachsieht, hat den Betrieb nicht mehr im
             Kopf und braucht Nummer, Liste und den Stand von *jetzt*. In der
             Standardliste ist das die Zeile, die man gerade selbst
             eingetragen hat – dort wäre es Rauschen. -->
        <p v-if="page.query" class="mt-0.5 text-xs light-grey-text">
          <a
            :href="`tel:${entry.telefon.replace(/\s+/g, '')}`"
            class="hover:text-strong transition-colors"
          >
            {{ entry.telefon }}
          </a>
          <template v-if="entry.email">
            ·
            <a :href="`mailto:${entry.email}`" class="hover:text-strong transition-colors">
              {{ entry.email }}
            </a>
          </template>
          <template v-if="entry.list_name"> · {{ entry.list_name }}</template>
          · steht jetzt auf
          <span :class="STATE_CLASSES[entry.state]">{{ entry.state_label }}</span>
        </p>

        <p v-if="entry.note" class="mt-0.5 text-xs text-zinc-500 break-words whitespace-pre-line">
          „{{ entry.note }}“
        </p>

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
              <!-- Textfeld wie am Arbeitsplatz: eine Richtigstellung muss
                   dieselbe Notiz aufnehmen können wie das Gespräch selbst. -->
              <textarea
                :id="`fix-note-${entry.event_id}`"
                v-model="note"
                rows="4"
                class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors resize-y"
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

    <!-- Zieht das Fenster der Standardliste auf. Im Suchbetrieb gibt es
         nichts aufzuziehen: gesucht wird im ganzen Protokoll. -->
    <button
      v-if="page && !page.query && page.entries.length < page.total"
      class="text-xs light-grey-text hover:text-strong transition-colors"
      :disabled="isLoading"
      @click="loadMore()"
    >
      weitere anzeigen ({{ page.entries.length }} von {{ page.total }})
    </button>
  </section>
</template>
