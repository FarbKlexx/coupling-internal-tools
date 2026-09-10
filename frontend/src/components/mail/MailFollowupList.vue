<script setup lang="ts">
/**
 * Die Versandliste: jede Zusage mit dem, was daraus geworden ist.
 *
 * Oben ein Reiter je Versandstand mit seiner Anzahl, darunter die Zeilen mit
 * ihren Knöpfen. Reiter und nicht anklickbare Zähler-Kacheln: eine Kachel
 * sieht aus wie eine Zahl, und dass sie zugleich der Filter ist, sieht man
 * ihr nicht an. Die Knöpfe einer
 * Zeile kommen als `entry.actions` aus dem Backend; welche Übergänge es gibt,
 * entscheidet dort eine Tabelle, gegen die auch das Schreiben prüft. Diese
 * Regel hier nachzubauen hieße, sich früher oder später einen Knopf zu
 * bauen, der mit 400 antwortet.
 *
 * Beschriftung, Beschreibung und Tonlage der Knöpfe reisen ebenfalls als
 * Daten mit (`actions`). Was hier steht, ist reine Darstellung.
 *
 * Quer zu den Reitern liegt die **Bau-Einschätzung**: drei Marker je Zeile,
 * die sagen, wo die Website steht — ob aus der bestehenden eine neue werden
 * kann, und ob sie es schon ist und nur noch zum Betrieb muss. Sie ist kein
 * Versandstand und steht deshalb nicht in der Reiterzeile, sondern als eigene
 * Filterzeile darunter — zwei Fragen, zwei Filter, und beide gleichzeitig
 * ergibt die Liste, mit der jemand zu bauen anfängt.
 */
import { ref } from "vue";
import {
  exportUrl,
  type BuildReadiness,
  type MailActionInfo,
  type MailBoard,
  type MailEntry,
  type MailState,
  type ReadinessOptionInfo,
} from "@/api/mail_followup.api";
import { formatMoment } from "@/components/calls/callTime";
import ContactWebsiteLink from "@/components/calls/ContactWebsiteLink.vue";

const props = defineProps<{
  board: MailBoard | null;
  actions: MailActionInfo[];
  readinessOptions: ReadinessOptionInfo[];
  timeoutDays: number;
  isLoading: boolean;
  isSaving: boolean;
  filterBy: (state: MailState | null) => void;
  filterByReadiness: (readiness: BuildReadiness | null) => void;
  goToPage: (offset: number) => void;
  save: (
    contactId: string,
    update: { state?: MailState; note?: string; readiness?: BuildReadiness },
  ) => Promise<boolean>;
}>();

const query = defineModel<string>("query", { required: true });
const stateFilter = defineModel<MailState | null>("stateFilter", { required: true });
const readinessFilter = defineModel<BuildReadiness | null>("readinessFilter", {
  required: true,
});

/**
 * Symbol pro Zustand.
 *
 * `mailStates.test.ts` hält diese Zuordnung mit dem `MailState`-Enum des
 * Backends zusammen: eine ID ohne Symbol ist im Knopf ein leeres Kästchen,
 * und das fällt sonst erst dem auf, der die Liste abarbeitet.
 */
const ICONS: Record<MailState, string> = {
  offen: "drafts",
  versendet: "send",
  positiv: "mark_email_read",
  abgelehnt: "do_not_disturb_on",
  keine_antwort: "hourglass_disabled",
};

/**
 * Symbol, Farbe und Filter-Beschriftung je Einschätzung.
 *
 * Anders als bei den Zustands-Knöpfen kommt hier **keine** Tonlage aus dem
 * Backend: „Missing Content" ist keine Ablehnung, sondern mehr Arbeit, und
 * Bernstein heißt in dieser Anwendung durchgehend „hier ist noch etwas zu
 * tun". „Ready to Mail" ist aus demselben Grund blau: dieselbe Farbe wie der
 * Versandstand „verschickt", weil es dieselbe Aussage über die Website ist –
 * fertig und auf dem Weg. Die Beschriftung an der Zeile kommt dagegen mit der
 * Antwort – nur die kurze Form für die Filterzeile steht hier, wie bei
 * `TABS`.
 *
 * `mailStates.test.ts` hält diese Zuordnung mit `BuildReadiness` im Backend
 * zusammen: ein Wert ohne Symbol wäre ein leeres Kästchen in einem Knopf.
 */
const READINESS: Record<
  BuildReadiness,
  { icon: string; text: string; chip: string; filter: string }
> = {
  unbewertet: {
    icon: "help",
    text: "text-zinc-500",
    chip: "chip--on",
    filter: "Nicht eingeschätzt",
  },
  ready_to_build: {
    icon: "construction",
    text: "text-emerald-400",
    chip: "chip--ready",
    filter: "Ready to Build",
  },
  ready_to_mail: {
    icon: "schedule_send",
    text: "text-blue-300",
    chip: "chip--built",
    filter: "Ready to Mail",
  },
  missing_content: {
    icon: "edit_document",
    text: "text-amber-400",
    chip: "chip--missing",
    filter: "Missing Content",
  },
};

/** Die Werte in der Reihenfolge der Filterzeile: erst der Weg durch den Bau
 *  („lässt sich bauen" → „ist gebaut"), dann der Umweg, dann die offene
 *  Frage. */
const READINESS_FILTERS: BuildReadiness[] = [
  "ready_to_build",
  "ready_to_mail",
  "missing_content",
  "unbewertet",
];

/** Die Marker, die an einer Zeile stehen. `unbewertet` ist kein Knopf,
 *  sondern das Ausschalten des gesetzten – siehe `toggleReadiness`. */
const READINESS_MARKERS: BuildReadiness[] = ["ready_to_build", "ready_to_mail", "missing_content"];

function readinessOption(id: BuildReadiness): ReadinessOptionInfo | undefined {
  return props.readinessOptions.find((option) => option.id === id);
}

/**
 * Die Zahl auf einem Marker – gezählt innerhalb des Reiters, der oben aktiv
 * ist (`countOf` erklärt die Regel). Sie ergeben damit zusammen die Zahl des
 * Reiters; vorher zählten sie immer über alle Zusagen und passten zur Liste
 * nur, solange „Alle" ausgewählt war.
 */
function readinessCount(id: BuildReadiness): number {
  return props.board?.counters[id] ?? 0;
}

/**
 * Einen Marker setzen – oder den gesetzten wieder entfernen.
 *
 * Ein zweiter Klick auf denselben Marker schickt `unbewertet`: der Fehlklick
 * gehört zum Werkzeug, und ein Marker, den man nur setzen kann, wäre für die
 * Zeile eine Einbahnstraße. Der Titel des aktiven Knopfes sagt das auch –
 * mit der Beschreibung, die das Backend für den Rückweg mitschickt.
 */
function toggleReadiness(entry: MailEntry, id: BuildReadiness) {
  void props.save(entry.contact_id, {
    readiness: entry.readiness === id ? "unbewertet" : id,
  });
}

function markerTitle(entry: MailEntry, id: BuildReadiness): string {
  const option = readinessOption(entry.readiness === id ? "unbewertet" : id);

  return option?.description ?? "";
}

/**
 * Die Reiter über der Liste – Filter und Zähler in einem.
 *
 * `id: null` ist „Alle" und hebt den Filter auf. Die Beschriftungen sind
 * kürzer als die Zustandsnamen aus dem Backend (`state_label`), weil sie in
 * eine Reiterzeile müssen; welcher Zustand gemeint ist, steht ausführlich an
 * der Zeile selbst.
 */
const TABS: { id: MailState | null; label: string }[] = [
  { id: null, label: "Alle" },
  { id: "offen", label: "Offen" },
  { id: "versendet", label: "Verschickt" },
  { id: "positiv", label: "Antwort positiv" },
  { id: "abgelehnt", label: "Abgelehnt" },
  { id: "keine_antwort", label: "Keine Antwort" },
];

/**
 * Die Zahl auf einem Reiter.
 *
 * Kommt immer aus `counters` und nie aus `matched`: eine laufende **Suche**
 * lässt die Zähler unberührt, sonst zeigte jeder Reiter die Zahl der gerade
 * sichtbaren Zeilen und beantwortete die Frage nicht mehr, für die er da ist
 * („wo stehe ich?").
 *
 * Der Filter der *anderen* Reihe steckt dagegen im Wert, denn er kommt
 * gerechnet aus dem Backend: bei aktivem Marker-Filter teilen die Reiter
 * dessen Auswahl auf, und „Alle" ist deren Summe. Hier ist dafür nichts zu
 * tun – die Sicht reist mit der Anfrage, und die Antwort bringt die Zahlen,
 * die zu ihr passen.
 */
function countOf(state: MailState | null): number {
  if (!props.board) return 0;

  return state === null ? props.board.counters.gesamt : props.board.counters[state];
}

/** Welche Zeile gerade eine Anmerkung bekommt – immer höchstens eine. */
const editing = ref<string | null>(null);
const note = ref("");

function openNote(entry: MailEntry) {
  editing.value = entry.contact_id;
  note.value = entry.mail_note;
}

async function saveNote(entry: MailEntry) {
  if (props.isSaving) return;

  // Ohne `state`: eine Anmerkung soll den Zustand nicht anfassen – und schon
  // gar nicht eine abgelaufene Frist als Entscheidung festschreiben.
  if (await props.save(entry.contact_id, { note: note.value.trim() })) editing.value = null;
}

function toneClass(tone: MailActionInfo["tone"]): string {
  if (tone === "positive") return "outcome outcome--positive";
  if (tone === "negative") return "outcome outcome--negative";
  return "outcome";
}

/** Farbe des Zustands in der Zeile. */
function stateClass(state: MailState): string {
  if (state === "positiv") return "text-emerald-400";
  if (state === "abgelehnt") return "text-red-400";
  if (state === "keine_antwort") return "text-amber-400";
  if (state === "versendet") return "text-blue-300";
  return "light-grey-text";
}

function actionOf(id: MailState): MailActionInfo | undefined {
  return props.actions.find((action) => action.id === id);
}

/** „seit 12 Tagen" – die Zahl kommt gerechnet aus dem Backend. */
function waiting(entry: MailEntry): string {
  if (entry.days_since_sent === null) return "";
  if (entry.days_since_sent === 0) return "heute";

  return `seit ${entry.days_since_sent} ${entry.days_since_sent === 1 ? "Tag" : "Tagen"}`;
}
</script>

<template>
  <div class="space-y-4">
    <!-- Die Reiter: Filter und Zähler in einem -->
    <div
      v-if="board"
      role="tablist"
      aria-label="Nach Versandstand filtern"
      class="flex flex-wrap items-center gap-x-1 border-b border-zinc-800"
    >
      <button
        v-for="tab in TABS"
        :key="tab.id ?? 'alle'"
        type="button"
        role="tab"
        class="tab"
        :class="stateFilter === tab.id ? 'tab--active' : ''"
        :aria-selected="stateFilter === tab.id"
        :data-tab="tab.id ?? 'alle'"
        @click="filterBy(tab.id)"
      >
        <span v-if="tab.id" class="material-symbols-outlined" style="font-size: 16px">
          {{ ICONS[tab.id] }}
        </span>
        {{ tab.label }}
        <span class="tab-count">{{ countOf(tab.id) }}</span>
      </button>
    </div>

    <!-- Die Bau-Einschätzung als zweiter, unabhängiger Filter. Bewusst
         keine zweite Reiterzeile: zwei Reiterzeilen übereinander sähen aus
         wie eine Hierarchie, und die beiden Größen liegen nebeneinander. -->
    <div
      v-if="board"
      role="group"
      aria-label="Nach Bau-Einschätzung filtern"
      class="flex flex-wrap items-center gap-2"
    >
      <span class="text-xs text-zinc-500">Website:</span>
      <button
        v-for="id in READINESS_FILTERS"
        :key="id"
        type="button"
        class="chip"
        :class="readinessFilter === id ? READINESS[id].chip : ''"
        :aria-pressed="readinessFilter === id"
        :data-readiness-filter="id"
        @click="filterByReadiness(id)"
      >
        <span class="material-symbols-outlined" style="font-size: 16px">
          {{ READINESS[id].icon }}
        </span>
        {{ READINESS[id].filter }}
        <span class="tab-count">{{ readinessCount(id) }}</span>
      </button>
    </div>

    <!-- Suche und Ausgabe -->
    <div class="flex flex-wrap items-center gap-3">
      <div class="relative min-w-64 flex-1 max-w-md">
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
          aria-label="Versandliste durchsuchen"
          class="w-full rounded-md light-grey-background light-grey-stroke py-2 pl-10 pr-3 text-sm outline-none focus:border-blue-500 transition-colors"
        />
      </div>

      <!-- Die Zusagen ohne Adresse: keine eigene Spalte im Zustandsmodell,
           aber die Nacharbeit, die sonst niemand sieht. -->
      <p v-if="board?.counters.ohne_email" class="text-xs text-amber-400">
        {{ board.counters.ohne_email }} ohne E-Mail-Adresse
      </p>

      <a :href="exportUrl()" class="chip ml-auto" download>
        <span class="material-symbols-outlined" style="font-size: 16px">download</span>
        Als CSV
      </a>
    </div>

    <p v-if="isLoading && !board" class="text-sm light-grey-text">Versandliste wird geladen …</p>

    <p
      v-else-if="!board?.total"
      class="rounded-xl border light-grey-background light-grey-stroke p-6 text-sm light-grey-text"
    >
      Noch keine Zusage. Sobald in der Telefonakquise jemand zusagt, eine E-Mail zu bekommen,
      erscheint der Betrieb hier.
    </p>

    <p v-else-if="!board.entries.length" class="text-sm light-grey-text">
      Keine Zeile passt zu dieser Auswahl.
    </p>

    <!-- Die Zeilen -->
    <ul v-else class="space-y-2">
      <li
        v-for="entry in board.entries"
        :key="entry.contact_id"
        class="rounded-xl border light-grey-background light-grey-stroke p-4 space-y-3"
      >
        <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div class="min-w-0 space-y-1">
            <p class="flex flex-wrap items-baseline gap-2">
              <span class="font-semibold">{{ entry.betrieb }}</span>
              <span class="flex items-center gap-1 text-xs" :class="stateClass(entry.state)">
                <span class="material-symbols-outlined" style="font-size: 15px">
                  {{ ICONS[entry.state] }}
                </span>
                {{ entry.state_label }}
              </span>
              <!-- Nicht angeklickt, sondern abgelaufen: ohne diesen Hinweis
                   sähe die Zeile aus, als hätte jemand sie abgeschlossen. -->
              <span
                v-if="entry.automatic"
                class="text-xs text-zinc-500"
                :title="`Automatisch, weil seit ${timeoutDays} Tagen keine Antwort kam.`"
              >
                automatisch
              </span>
              <!-- Die Einschätzung, wenn eine gemacht wurde: der Marker soll
                   beim Überfliegen der Liste ins Auge fallen, sonst ist er
                   keiner. `unbewertet` steht hier nicht — eine Zeile ohne
                   Marker ist die Auskunft „noch nicht angesehen". -->
              <span
                v-if="entry.readiness !== 'unbewertet'"
                class="flex items-center gap-1 text-xs"
                :class="READINESS[entry.readiness].text"
                :data-readiness="entry.readiness"
                :title="readinessOption(entry.readiness)?.description"
              >
                <span class="material-symbols-outlined" style="font-size: 15px">
                  {{ READINESS[entry.readiness].icon }}
                </span>
                {{ entry.readiness_label }}
              </span>
            </p>

            <p class="text-xs light-grey-text">
              <a
                v-if="entry.email"
                :href="`mailto:${entry.email}`"
                class="hover:text-white transition-colors"
              >
                {{ entry.email }}
              </a>
              <span v-else class="text-amber-400">
                keine E-Mail-Adresse – erst nachtragen (Telefonakquise)
              </span>
              <template v-if="entry.telefon"> · {{ entry.telefon }}</template>
              <template v-if="entry.plz || entry.ort"> · {{ entry.plz }} {{ entry.ort }}</template>
              <template v-if="entry.gewerk"> · {{ entry.gewerk }}</template>
              <!-- Die Website: beim Nachfassen die Frage „mit wem rede ich
                   hier eigentlich?“, ohne den Betrieb erst googeln zu müssen.
                   Ob daraus ein Link wird, entscheidet die Komponente – der
                   Wert kommt unverändert aus der CSV. -->
              <template v-if="entry.website">
                · <ContactWebsiteLink :website="entry.website" />
              </template>
            </p>

            <p class="text-xs text-zinc-500">
              Zusage {{ formatMoment(entry.promised_at) }}
              <template v-if="entry.promised_by"> · {{ entry.promised_by }}</template>
              · {{ entry.list_name }}
              <template v-if="entry.list_archived"> (archiviert)</template>
            </p>
          </div>

          <div class="shrink-0 space-y-1 text-right text-xs text-zinc-500">
            <p v-if="entry.sent_at">
              versendet {{ formatMoment(entry.sent_at) }}
              <span :class="entry.state === 'keine_antwort' ? 'text-amber-400' : ''">
                · {{ waiting(entry) }}
              </span>
            </p>
            <p v-if="entry.answered_at">Antwort {{ formatMoment(entry.answered_at) }}</p>
            <p v-if="entry.updated_by">zuletzt {{ entry.updated_by }}</p>
          </div>
        </div>

        <p v-if="entry.note" class="text-xs text-zinc-500 break-words whitespace-pre-line">
          Telefonat: „{{ entry.note }}“
        </p>

        <!-- Die Knöpfe dieser Zeile – aus `entry.actions`, nicht aus einer
             Regel hier. -->
        <div class="flex flex-wrap items-center gap-2">
          <button
            v-for="id in entry.actions"
            :key="id"
            type="button"
            class="text-xs"
            :class="toneClass(actionOf(id)?.tone ?? 'neutral')"
            :disabled="isSaving"
            :title="actionOf(id)?.description"
            @click="save(entry.contact_id, { state: id })"
          >
            <span class="material-symbols-outlined" style="font-size: 16px">{{ ICONS[id] }}</span>
            {{ actionOf(id)?.label ?? id }}
          </button>

          <button
            type="button"
            class="chip"
            :disabled="isSaving"
            @click="editing === entry.contact_id ? (editing = null) : openNote(entry)"
          >
            <span class="material-symbols-outlined" style="font-size: 16px">edit_note</span>
            {{ entry.mail_note ? "Anmerkung ändern" : "Anmerkung" }}
          </button>

          <!-- Die Einschätzung: Umschalter, keine Übergänge. Sie ändert den
               Versandstand nicht und ist deshalb von den Ergebnis-Knöpfen
               abgesetzt (`ml-auto`) — und ein zweiter Klick auf den gesetzten
               nimmt ihn zurück. -->
          <span class="ml-auto flex flex-wrap items-center gap-2">
            <button
              v-for="id in READINESS_MARKERS"
              :key="id"
              type="button"
              class="chip"
              :class="entry.readiness === id ? READINESS[id].chip : ''"
              :aria-pressed="entry.readiness === id"
              :data-marker="id"
              :disabled="isSaving"
              :title="markerTitle(entry, id)"
              @click="toggleReadiness(entry, id)"
            >
              <span class="material-symbols-outlined" style="font-size: 16px">
                {{ READINESS[id].icon }}
              </span>
              {{ readinessOption(id)?.label ?? id }}
            </button>
          </span>
        </div>

        <p
          v-if="entry.mail_note && editing !== entry.contact_id"
          class="text-xs light-grey-text break-words whitespace-pre-line"
        >
          Versand: „{{ entry.mail_note }}“
        </p>

        <div
          v-if="editing === entry.contact_id"
          class="flex flex-wrap items-end gap-2 rounded-md grey-background light-grey-stroke p-3"
        >
          <div class="flex min-w-64 flex-1 flex-col gap-1">
            <label class="text-xs text-zinc-500" :for="`mail-note-${entry.contact_id}`">
              Anmerkung zum Versand – ändert den Zustand nicht
            </label>
            <!-- Mehrzeilig: hier steht, was in der Antwort stand, und das ist
                 selten ein Satz. Enter macht deshalb eine neue Zeile;
                 gespeichert wird mit dem Knopf oder Strg/⌘+Enter. -->
            <textarea
              :id="`mail-note-${entry.contact_id}`"
              v-model="note"
              rows="4"
              class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors resize-y"
              @keydown.enter.ctrl.prevent="saveNote(entry)"
              @keydown.enter.meta.prevent="saveNote(entry)"
            />
          </div>
          <button
            type="button"
            class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-40 transition-colors"
            :disabled="isSaving"
            @click="saveNote(entry)"
          >
            Speichern
          </button>
          <button
            type="button"
            class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm hover:text-white transition-colors"
            :disabled="isSaving"
            @click="editing = null"
          >
            Abbrechen
          </button>
        </div>
      </li>
    </ul>

    <!-- Blättern -->
    <div v-if="board && board.matched > board.limit" class="flex items-center gap-3 text-xs">
      <button
        class="chip"
        type="button"
        :disabled="board.offset === 0 || isLoading"
        @click="goToPage(board.offset - board.limit)"
      >
        zurück
      </button>
      <span class="light-grey-text">
        {{ board.offset + 1 }}–{{ Math.min(board.offset + board.limit, board.matched) }} von
        {{ board.matched }}
      </span>
      <button
        class="chip"
        type="button"
        :disabled="board.offset + board.limit >= board.matched || isLoading"
        @click="goToPage(board.offset + board.limit)"
      >
        weiter
      </button>
    </div>
  </div>
</template>
