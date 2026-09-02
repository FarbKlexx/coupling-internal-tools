<script setup lang="ts">
import axios from "axios";
import { computed, ref } from "vue";
import CallBlacklist from "@/components/calls/CallBlacklist.vue";
import {
  analyseList,
  promisedExportUrl,
  protocolExportUrl,
  type BlacklistMutation,
  type BlacklistPage,
  type CallListInfo,
  type ListAnalyse,
  type ListImport,
} from "@/api/call_list.api";

/**
 * Die Listenpflege – nur für Administratoren, das Backend setzt es durch.
 *
 * Die schreibenden Aktionen kommen als Funktionen aus `useCallList` herein und
 * werden nicht als Ereignisse gemeldet: dieses Formular muss wissen, *ob* eine
 * Aktion geklappt hat (ein abgelehntes Löschen bietet „trotzdem löschen" an),
 * und ein Ereignis liefert diese Antwort nicht zurück.
 */
const props = defineProps<{
  lists: CallListInfo[];
  isSaving: boolean;
  upload: (file: File, name: string, prios?: string[]) => Promise<ListImport | null>;
  edit: (listId: string, payload: { name?: string; archived?: boolean }) => Promise<boolean>;
  remove: (listId: string, force?: boolean) => Promise<boolean>;
  blacklist: BlacklistPage | null;
  blacklistCount: number;
  blacklistQuery: string;
  isBlacklistLoading: boolean;
  loadBlacklist: (options?: { offset?: number }) => Promise<void>;
  addToBlacklist: (numbers: string, note: string) => Promise<BlacklistMutation | null>;
  uploadBlacklist: (file: File) => Promise<BlacklistMutation | null>;
  releaseNumber: (telefonKey: string) => Promise<boolean>;
}>();

const emit = defineEmits<{ "update:blacklistQuery": [value: string] }>();

const open = ref(props.lists.length === 0);

const file = ref<File | null>(null);
const listName = ref("");
const analysis = ref<ListAnalyse | null>(null);
const analysisError = ref<string | null>(null);
const isAnalysing = ref(false);
const result = ref<ListImport | null>(null);
const isDragOver = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);

/**
 * Die angehakten Prio-Werte.
 *
 * Nach dem Trockenlauf sind alle angehakt: der Filter ist ein Angebot, keine
 * Pflicht, und wer ihn nicht braucht, soll die Datei nicht erst freischalten
 * müssen.
 */
const selectedPrios = ref<string[]>([]);

/** Filtert die Auswahl wirklich, oder sind ohnehin alle Prios dabei? */
const isPrioFiltered = computed(
  () =>
    analysis.value !== null &&
    analysis.value.prio_values.length > 0 &&
    selectedPrios.value.length < analysis.value.prio_values.length,
);

/**
 * Wie viele Kontakte der Import brächte – aus den Zahlen des Trockenlaufs.
 *
 * Lokal gerechnet und nicht bei jedem Häkchen neu erfragt: das Backend liefert
 * pro Prio schon die Zahl der *neuen* Kontakte, und die 4-MB-Datei bei jedem
 * Klick erneut hochzuladen wäre der teuerste Weg zu derselben Zahl.
 */
const plannedContacts = computed(() => {
  if (analysis.value === null) return 0;
  if (!isPrioFiltered.value) return analysis.value.contacts;

  return analysis.value.prio_values
    .filter((entry) => selectedPrios.value.includes(entry.value))
    .reduce((sum, entry) => sum + entry.contacts, 0);
});

function togglePrio(value: string) {
  selectedPrios.value = selectedPrios.value.includes(value)
    ? selectedPrios.value.filter((entry) => entry !== value)
    : [...selectedPrios.value, value];
}

/** Umbenennen läuft direkt in der Zeile. */
const renaming = ref<string | null>(null);
const draftName = ref("");

/** Löschen wird bestätigt; nach einem 409 mit „trotzdem". */
const deleting = ref<string | null>(null);
const deleteRefused = ref(false);

function reset() {
  file.value = null;
  listName.value = "";
  analysis.value = null;
  analysisError.value = null;
  result.value = null;
  selectedPrios.value = [];
}

async function selectFile(selected: File | null | undefined) {
  if (!selected) return;

  file.value = selected;
  analysis.value = null;
  analysisError.value = null;
  result.value = null;
  isAnalysing.value = true;

  try {
    // Trockenlauf sofort: der Anwender soll die Zuordnung sehen, *bevor* 86
    // Kontakte in der Datenbank stehen.
    const report = await analyseList(selected);
    analysis.value = report;
    listName.value = report.name_suggestion;
    selectedPrios.value = report.prio_values.map((entry) => entry.value);
  } catch (e) {
    console.error(e);
    analysisError.value = axios.isAxiosError(e)
      ? ((e.response?.data as { detail?: string } | undefined)?.detail ??
        "Die Datei konnte nicht gelesen werden.")
      : "Die Datei konnte nicht gelesen werden.";
  } finally {
    isAnalysing.value = false;
  }
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  void selectFile(input.files?.[0]);
  // Zurücksetzen, damit dieselbe Datei erneut ausgewählt werden kann.
  input.value = "";
}

function onDrop(event: DragEvent) {
  isDragOver.value = false;
  void selectFile(event.dataTransfer?.files?.[0]);
}

async function importNow() {
  if (!file.value || props.isSaving) return;

  const imported = await props.upload(
    file.value,
    listName.value,
    // Nur mitschicken, wenn wirklich eingeschränkt wird: ein fehlendes Feld
    // heißt im Backend „alle Prios", und das ist genau dieser Fall.
    isPrioFiltered.value ? selectedPrios.value : undefined,
  );

  if (imported) {
    result.value = imported;
    file.value = null;
    analysis.value = null;
    selectedPrios.value = [];
  }
}

function startRename(list: CallListInfo) {
  renaming.value = list.id;
  draftName.value = list.name;
}

async function saveRename() {
  if (!renaming.value || !draftName.value.trim()) return;

  const ok = await props.edit(renaming.value, { name: draftName.value.trim() });
  if (ok) renaming.value = null;
}

function askDelete(list: CallListInfo) {
  deleting.value = list.id;
  deleteRefused.value = false;
}

async function confirmDelete(force: boolean) {
  if (!deleting.value) return;

  const ok = await props.remove(deleting.value, force);

  if (ok) {
    deleting.value = null;
    deleteRefused.value = false;
  } else {
    // Das Backend verweigert, solange Anrufe protokolliert sind, und sagt in
    // der Meldung oben, wie viele. Erst danach gibt es „trotzdem".
    deleteRefused.value = true;
  }
}

function formatDate(iso: string): string {
  const stamp = new Date(iso);
  if (Number.isNaN(stamp.getTime())) return iso;

  return stamp.toLocaleDateString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}
</script>

<template>
  <div class="max-w-4xl rounded-xl border light-grey-background light-grey-stroke">
    <button class="flex w-full items-center justify-between gap-3 px-6 py-4" @click="open = !open">
      <span class="flex items-center gap-2">
        <span class="material-symbols-outlined nav-icon">list_alt</span>
        <span class="font-semibold">Listen verwalten</span>
        <span class="text-xs text-zinc-500">nur für Administratoren</span>
      </span>
      <span class="material-symbols-outlined nav-icon">
        {{ open ? "expand_less" : "expand_more" }}
      </span>
    </button>

    <div v-if="open" class="space-y-6 border-t border-zinc-800 px-6 py-5">
      <!-- Import -->
      <div class="space-y-3">
        <div class="space-y-1">
          <h3 class="text-sm font-semibold">Liste hochladen</h3>
          <p class="text-xs text-zinc-500">
            CSV mit den Spalten <strong>Betrieb</strong> und <strong>Telefon</strong>; E-Mail, Ort,
            PLZ, Website, Gewerk, Prio und Befunde werden erkannt, alle weiteren Spalten fahren mit
            und erscheinen beim Kontakt unter „Details". Aus Excel über „Speichern unter" als „CSV
            UTF-8" exportieren. Nummern, die schon einmal importiert wurden oder auf der Blacklist
            stehen, werden übersprungen. Gibt es eine Prio-Spalte, lässt sich unten auswählen,
            welche Prio hochgeladen wird.
          </p>
        </div>

        <div
          :class="[
            'rounded-md border border-dashed px-4 py-5 text-center transition-colors cursor-pointer',
            isDragOver ? 'border-blue-500 bg-blue-500/5' : 'light-grey-stroke grey-background',
          ]"
          @click="fileInput?.click()"
          @dragover.prevent="isDragOver = true"
          @dragleave.prevent="isDragOver = false"
          @drop.prevent="onDrop"
        >
          <span class="material-symbols-outlined nav-icon--active">upload_file</span>
          <p class="light-grey-text mt-1 text-sm">CSV hierher ziehen oder klicken zum Auswählen</p>
        </div>
        <input
          ref="fileInput"
          type="file"
          accept=".csv,text/csv"
          class="hidden"
          @change="onFileChange"
        />

        <p v-if="isAnalysing" class="text-xs light-grey-text">Datei wird gelesen …</p>
        <p
          v-if="analysisError"
          class="rounded-md bg-red-900/30 border border-red-700 px-3 py-2 text-sm text-red-400"
        >
          {{ analysisError }}
        </p>

        <!-- Trockenlauf -->
        <div v-if="analysis" class="space-y-3 rounded-md grey-background light-grey-stroke p-4">
          <p class="text-sm">
            <strong>{{ analysis.data_rows }}</strong> Zeilen gelesen →
            <strong>{{ analysis.contacts }}</strong> Kontakte
            <span class="text-xs text-zinc-500">
              ({{ analysis.encoding }}, {{ analysis.delimiter }})
            </span>
          </p>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
            <div
              v-for="entry in analysis.mapping"
              :key="entry.field"
              class="flex justify-between gap-2 border-b border-zinc-800 py-1 text-xs"
            >
              <span class="text-zinc-500">{{ entry.label }}</span>
              <span class="light-grey-text text-right">
                {{ entry.column }}
                <span v-if="entry.empty_count" class="text-amber-400">
                  ({{ entry.empty_count }}× leer)
                </span>
              </span>
            </div>
          </div>

          <p v-if="analysis.extra_columns.length" class="text-xs light-grey-text">
            <span class="text-zinc-500">Fahren mit:</span>
            {{ analysis.extra_columns.join(", ") }}
          </p>

          <p
            v-for="(warning, index) in analysis.warnings"
            :key="index"
            class="text-xs text-amber-400"
          >
            {{ warning }}
          </p>

          <details v-if="analysis.skipped_rows.length" class="text-xs">
            <summary class="cursor-pointer text-amber-400">
              {{ analysis.skipped_rows.length }} Zeilen werden übersprungen
            </summary>
            <ul class="mt-1 space-y-0.5 light-grey-text">
              <li v-for="row in analysis.skipped_rows" :key="row.line">
                Zeile {{ row.line }}: {{ row.reason }}
              </li>
            </ul>
          </details>

          <details v-if="analysis.duplicates.length" class="text-xs">
            <summary class="cursor-pointer text-amber-400">
              {{ analysis.duplicates.length }} Nummern sind schon bekannt
            </summary>
            <ul class="mt-1 space-y-0.5 light-grey-text">
              <li v-for="row in analysis.duplicates" :key="row.line">
                Zeile {{ row.line }}: {{ row.reason }}
              </li>
            </ul>
          </details>

          <!-- Prio-Auswahl: nur, wenn die Datei überhaupt eine Prio-Spalte hat -->
          <div v-if="analysis.prio_values.length" class="space-y-2 border-t border-zinc-800 pt-3">
            <p class="text-xs text-zinc-500">
              Spalte „{{ analysis.prio_column }}“ – welche Prio soll importiert werden?
            </p>
            <div class="flex flex-wrap gap-2">
              <label
                v-for="entry in analysis.prio_values"
                :key="entry.value"
                :class="[
                  'flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs transition-colors cursor-pointer',
                  selectedPrios.includes(entry.value)
                    ? 'border-blue-500 bg-blue-500/10'
                    : 'light-grey-stroke light-grey-background',
                ]"
              >
                <input
                  type="checkbox"
                  :checked="selectedPrios.includes(entry.value)"
                  @change="togglePrio(entry.value)"
                />
                <span class="font-medium">{{ entry.label }}</span>
                <span class="text-zinc-500">
                  {{ entry.rows }} Zeilen<template v-if="entry.contacts !== entry.rows">
                    , {{ entry.contacts }} neu</template
                  >
                </span>
              </label>
            </div>
            <p v-if="selectedPrios.length === 0" class="text-xs text-amber-400">
              Ohne angehakte Prio gibt es nichts zu importieren.
            </p>
          </div>

          <div class="flex flex-wrap items-end gap-2">
            <div class="flex flex-col gap-1 grow">
              <label class="text-xs text-zinc-500" for="call-list-name">Name der Liste</label>
              <input
                id="call-list-name"
                v-model="listName"
                type="text"
                class="w-full rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
              />
            </div>
            <button
              class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-40 transition-colors"
              :disabled="isSaving || plannedContacts === 0"
              @click="importNow"
            >
              {{ plannedContacts }} Kontakte importieren
            </button>
            <button
              class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm"
              @click="reset"
            >
              Abbrechen
            </button>
          </div>
        </div>

        <p
          v-if="result"
          class="rounded-md bg-emerald-900/30 border border-emerald-700 px-3 py-2 text-sm text-emerald-400"
        >
          {{ result.imported }} Kontakte importiert.
          <template v-if="result.skipped_rows.length || result.duplicates.length">
            {{ result.skipped_rows.length }} Zeilen übersprungen,
            {{ result.duplicates.length }} Nummern waren schon bekannt.
          </template>
          <template v-if="result.prio_skipped">
            {{ result.prio_skipped }} Zeilen hatten eine andere Prio.
          </template>
        </p>
      </div>

      <!-- Vorhandene Listen -->
      <div v-if="lists.length" class="space-y-2">
        <h3 class="text-sm font-semibold">Vorhandene Listen</h3>

        <div
          v-for="list in lists"
          :key="list.id"
          class="rounded-md grey-background light-grey-stroke px-4 py-3 space-y-2"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="min-w-0">
              <div v-if="renaming === list.id" class="flex items-center gap-2">
                <input
                  v-model="draftName"
                  type="text"
                  class="rounded-md light-grey-background light-grey-stroke px-2 py-1 text-sm outline-none focus:border-blue-500"
                  @keyup.enter="saveRename"
                />
                <button class="chip" :disabled="isSaving" @click="saveRename">Speichern</button>
                <button class="chip" @click="renaming = null">Abbrechen</button>
              </div>
              <p v-else class="font-medium truncate">
                {{ list.name }}
                <span v-if="list.archived" class="badge ml-1">archiviert</span>
              </p>
              <p class="text-xs text-zinc-500 truncate">
                {{ formatDate(list.created_at) }} · {{ list.created_by }} ·
                {{ list.source_filename }}
              </p>
            </div>

            <div class="flex items-center gap-1 shrink-0">
              <button
                class="card-action"
                title="Umbenennen"
                :disabled="isSaving"
                @click="startRename(list)"
              >
                <span class="material-symbols-outlined nav-icon">edit</span>
              </button>
              <button
                class="card-action"
                :title="list.archived ? 'Wieder aufnehmen' : 'Stilllegen (Protokoll bleibt)'"
                :disabled="isSaving"
                @click="edit(list.id, { archived: !list.archived })"
              >
                <span class="material-symbols-outlined nav-icon">
                  {{ list.archived ? "unarchive" : "archive" }}
                </span>
              </button>
              <button
                class="card-action"
                title="Endgültig löschen"
                :disabled="isSaving"
                @click="askDelete(list)"
              >
                <span class="material-symbols-outlined nav-icon">delete</span>
              </button>
            </div>
          </div>

          <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs light-grey-text">
            <span>{{ list.counters.gesamt }} Kontakte</span>
            <span>{{ list.counters.offen }} offen</span>
            <span v-if="list.counters.wiedervorlage">
              {{ list.counters.wiedervorlage }} Wiedervorlage
            </span>
            <span class="text-emerald-400">{{ list.counters.zugesagt }} Zusagen</span>
            <span v-if="list.counters.kein_bedarf">
              {{ list.counters.kein_bedarf }} kein Bedarf
            </span>
            <span v-if="list.counters.abgelehnt">{{ list.counters.abgelehnt }} abgelehnt</span>
            <span v-if="list.counters.ungueltig">
              {{ list.counters.ungueltig }} Nummer falsch
            </span>
          </div>

          <div
            v-if="deleting === list.id"
            class="space-y-2 rounded-md border border-red-700 bg-red-900/20 px-3 py-2"
          >
            <p class="text-xs text-red-300">
              Löschen entfernt die Kontakte <strong>und</strong> ihre Protokollzeilen – damit den
              Nachweis der Einwilligungen. Die Nummern dieser Liste werden dabei wieder freigegeben
              und sind erneut importierbar. Stilllegen behält beides und die Sperre.
            </p>
            <div class="flex flex-wrap gap-2">
              <button class="chip" :disabled="isSaving" @click="confirmDelete(false)">
                Löschen
              </button>
              <button
                v-if="deleteRefused"
                class="chip chip--danger"
                :disabled="isSaving"
                @click="confirmDelete(true)"
              >
                Trotzdem löschen
              </button>
              <button class="chip" @click="deleting = null">Abbrechen</button>
            </div>
          </div>
        </div>
      </div>

      <CallBlacklist
        :page="blacklist"
        :total="blacklistCount"
        :query="blacklistQuery"
        :is-loading="isBlacklistLoading"
        :is-saving="isSaving"
        :load="loadBlacklist"
        :add="addToBlacklist"
        :upload="uploadBlacklist"
        :release="releaseNumber"
        @update:query="emit('update:blacklistQuery', $event)"
      />

      <!-- Ausgaben -->
      <div class="space-y-2 border-t border-zinc-800 pt-4">
        <h3 class="text-sm font-semibold">Ausgaben</h3>
        <div class="flex flex-wrap gap-2">
          <a class="chip" :href="promisedExportUrl()">Zusagen als CSV</a>
          <a class="chip" :href="protocolExportUrl()">Anrufprotokoll als CSV</a>
        </div>
        <p class="text-xs text-zinc-500">
          Die Zusagen sind die Grundlage für den Mailversand. Das Protokoll ist der Nachweis, dass
          die Zustimmung am Telefon vorlag – mit Zeitpunkt und Konto.
        </p>
      </div>
    </div>
  </div>
</template>
