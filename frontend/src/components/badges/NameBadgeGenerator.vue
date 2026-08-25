<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import axios from "axios";
import { readErrorDetail } from "@/api/http";
import {
  analyseBadgeCsv,
  createBadgePdf,
  createCalibrationPdf,
  fetchBadgeFormats,
  type BadgeAnalysis,
  type BadgeSheetFormat,
} from "@/api/name_badge.api";
import SlotPicker from "./SlotPicker.vue";

/** Wartezeit nach der letzten Änderung, bevor neu gerechnet wird. */
const DEBOUNCE_MS = 400;

const formats = ref<BadgeSheetFormat[]>([]);
const maxOffsetMm = ref(5);
const maxRows = ref(2000);

const selectedFile = ref<File | null>(null);
const formatId = ref("");
const startSlot = ref(1);
const offsetXMm = ref(0);
const offsetYMm = ref(0);
const drawOutlines = ref(false);

const analysis = ref<BadgeAnalysis | null>(null);
const isWorking = ref(false);
const isDragOver = ref(false);
const errorMessage = ref<string | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

/** Ergebnis des letzten Laufs – die Vorschau ist zugleich der Download. */
const previewUrl = ref<string | null>(null);
let previewBlob: Blob | null = null;
let previewFilename = "";

let debounceTimer: ReturnType<typeof setTimeout> | null = null;
let controller: AbortController | null = null;

const format = computed<BadgeSheetFormat | null>(
  () => formats.value.find((entry) => entry.id === formatId.value) ?? null,
);

const canDownload = computed(() => previewUrl.value !== null && !isWorking.value);

const previewStyle = computed(() => ({
  aspectRatio: format.value
    ? `${format.value.sheet_width_mm} / ${format.value.sheet_height_mm}`
    : "210 / 297",
}));

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function releasePreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
  previewUrl.value = null;
  previewBlob = null;
  previewFilename = "";
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

/** Meldung des Backends auspacken – sie sagt dem Anwender, was zu tun ist. */
async function messageFrom(error: unknown): Promise<string> {
  if (!axios.isAxiosError(error)) return "Die Datei konnte nicht verarbeitet werden.";

  const payload: unknown = error.response?.data;
  const detail =
    (await readErrorDetail(payload)) ??
    (typeof (payload as { detail?: unknown })?.detail === "string"
      ? (payload as { detail: string }).detail
      : null);

  return detail ?? "Die Datei konnte nicht verarbeitet werden.";
}

function selectFile(file: File | null | undefined) {
  if (!file) return;

  selectedFile.value = file;
  errorMessage.value = null;
  analysis.value = null;
  releasePreview();
  void refresh();
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  selectFile(input.files?.[0]);
  // Zurücksetzen, damit dieselbe Datei erneut ausgewählt werden kann.
  input.value = "";
}

function onDrop(event: DragEvent) {
  isDragOver.value = false;
  selectFile(event.dataTransfer?.files?.[0]);
}

function removeFile() {
  selectedFile.value = null;
  analysis.value = null;
  errorMessage.value = null;
  releasePreview();
}

function clampOffset(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.min(maxOffsetMm.value, Math.max(-maxOffsetMm.value, value));
}

/**
 * Trockenlauf und Vorschau in einem Durchgang.
 *
 * Beide Endpunkte lesen dieselbe Datei über denselben Weg ein – der Bericht
 * kann also nichts ankündigen, was das PDF nicht hält.
 */
async function refresh() {
  const file = selectedFile.value;
  if (!file) return;

  // Beim ersten Versuch war das Backend nicht erreichbar: hier ist der
  // natürliche Moment, es noch einmal zu probieren – sonst passiert beim
  // Hochladen scheinbar gar nichts.
  if (!formatId.value && !(await loadFormats())) return;

  controller?.abort();
  controller = new AbortController();
  const signal = controller.signal;

  isWorking.value = true;
  errorMessage.value = null;

  try {
    analysis.value = await analyseBadgeCsv(
      file,
      { format: formatId.value, start_slot: startSlot.value },
      signal,
    );

    const result = await createBadgePdf(
      file,
      {
        format: formatId.value,
        start_slot: startSlot.value,
        offset_x_mm: offsetXMm.value,
        offset_y_mm: offsetYMm.value,
        draw_outlines: drawOutlines.value,
      },
      signal,
    );

    releasePreview();
    previewBlob = result.blob;
    previewFilename = result.filename;
    previewUrl.value = URL.createObjectURL(result.blob);
  } catch (error) {
    if ((error as Error)?.name === "CanceledError") return;

    analysis.value = null;
    releasePreview();
    errorMessage.value = await messageFrom(error);
  } finally {
    if (!signal.aborted) isWorking.value = false;
  }
}

watch([formatId, startSlot, offsetXMm, offsetYMm, drawOutlines], () => {
  if (!selectedFile.value) return;

  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => void refresh(), DEBOUNCE_MS);
});

/**
 * Bogenformate holen. Schlägt das fehl, ist das Backend nicht erreichbar –
 * ohne Format lässt sich weder rechnen noch rendern, deshalb ist es der erste
 * und einzige Zustand, in dem die Seite nicht arbeitsfähig ist.
 */
async function loadFormats(): Promise<boolean> {
  try {
    const response = await fetchBadgeFormats();
    formats.value = response.formats;
    formatId.value = response.default_format;
    maxOffsetMm.value = response.max_offset_mm;
    maxRows.value = response.max_rows;
    return true;
  } catch (error) {
    console.error(error);
    formats.value = [];
    formatId.value = "";
    errorMessage.value =
      "Die Bogenformate konnten nicht geladen werden – das Backend antwortet nicht. " +
      "Bitte erneut versuchen; bleibt es dabei, läuft der Server nicht.";
    return false;
  }
}

onMounted(() => void loadFormats());

onUnmounted(() => {
  if (debounceTimer) clearTimeout(debounceTimer);
  controller?.abort();
  releasePreview();
});

/** Formate nachladen und, wenn schon eine Datei gewählt ist, direkt rechnen. */
async function retry() {
  errorMessage.value = null;

  if (!(await loadFormats())) return;
  if (selectedFile.value) await refresh();
}

function download() {
  if (!previewBlob) return;
  saveBlob(previewBlob, previewFilename);
}

async function downloadCalibrationSheet() {
  if (!formatId.value) return;

  try {
    const { blob, filename } = await createCalibrationPdf(
      formatId.value,
      offsetXMm.value,
      offsetYMm.value,
    );
    saveBlob(blob, filename);
  } catch (error) {
    errorMessage.value = await messageFrom(error);
  }
}
</script>

<template>
  <div class="space-y-5">
    <div class="rounded-xl border light-grey-background light-grey-stroke p-6 space-y-5">
      <div class="space-y-1">
        <h2 class="text-lg font-semibold">Namensschilder drucken</h2>
        <p class="text-xs text-zinc-500">
          Teilnehmerliste als CSV hochladen und als druckfertiges PDF für perforierte
          Einsteckschilder-Bögen herunterladen. Pflichtspalte ist der Nachname; Vorname, Funktion
          und Firma kommen dazu, wenn es sie gibt. Die Liste wird nirgends gespeichert.
        </p>
      </div>

      <!-- Datei -->
      <div class="flex flex-col gap-2">
        <label class="text-sm font-medium">Teilnehmerliste (CSV)</label>
        <div
          :class="[
            'rounded-md border border-dashed px-4 py-6 text-center transition-colors cursor-pointer',
            isDragOver ? 'border-blue-500 bg-blue-500/5' : 'light-grey-stroke grey-background',
          ]"
          @click="fileInput?.click()"
          @dragover.prevent="isDragOver = true"
          @dragleave.prevent="isDragOver = false"
          @drop.prevent="onDrop"
        >
          <span class="material-symbols-outlined nav-icon--active">badge</span>
          <p class="light-grey-text mt-1">Datei hierher ziehen oder klicken zum Auswählen</p>
          <p class="text-xs text-zinc-500">
            Semikolon, Komma oder Tabulator · UTF-8 oder Windows-1252 · max. {{ maxRows }} Zeilen
          </p>
        </div>
        <input
          ref="fileInput"
          type="file"
          accept=".csv,text/csv,text/plain"
          class="hidden"
          @change="onFileChange"
        />

        <div
          v-if="selectedFile"
          class="flex items-center justify-between gap-3 rounded-md px-3 py-1.5 text-sm grey-background light-grey-stroke"
        >
          <span class="light-grey-text truncate">{{ selectedFile.name }}</span>
          <span class="flex items-center gap-3 shrink-0">
            <span class="text-xs text-zinc-500">{{ formatSize(selectedFile.size) }}</span>
            <button
              class="text-zinc-500 hover:text-red-400 transition-colors"
              title="Entfernen"
              @click="removeFile"
            >
              ✕
            </button>
          </span>
        </div>
        <p v-else class="text-xs text-zinc-500">Noch keine Datei ausgewählt.</p>
      </div>

      <!-- Fehler -->
      <div
        v-if="errorMessage"
        class="flex items-start justify-between gap-3 rounded-md bg-red-900/30 border border-red-700 px-3 py-2 text-sm text-red-400"
      >
        <span>{{ errorMessage }}</span>
        <button
          v-if="formats.length === 0"
          type="button"
          class="shrink-0 rounded-md border border-red-700 px-2 py-0.5 text-xs hover:bg-red-900/40 transition-colors"
          @click="retry"
        >
          Erneut versuchen
        </button>
      </div>
    </div>

    <!-- Einstellungen und Vorschau -->
    <div class="grid grid-cols-1 gap-5 xl:grid-cols-2">
      <div class="rounded-xl border light-grey-background light-grey-stroke p-6 space-y-5">
        <h3 class="text-sm font-semibold">Bogen</h3>

        <div v-if="formats.length > 1" class="flex flex-col gap-1">
          <label class="text-sm font-medium" for="badge-format">Format</label>
          <select
            id="badge-format"
            v-model="formatId"
            class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm"
          >
            <option v-for="entry in formats" :key="entry.id" :value="entry.id">
              {{ entry.label }}
            </option>
          </select>
        </div>
        <p v-else-if="format" class="text-xs text-zinc-500">{{ format.label }}</p>

        <!-- Erste Karte -->
        <div v-if="format" class="flex flex-col gap-2">
          <span class="text-sm font-medium">Erste zu bedruckende Karte</span>
          <p class="text-xs text-zinc-500">
            Für angebrochene Bögen: die Karte anklicken, ab der gedruckt werden soll.
          </p>
          <SlotPicker :format="format" v-model="startSlot" />
        </div>

        <!-- Registerkorrektur -->
        <div class="flex flex-col gap-2">
          <span class="text-sm font-medium">Registerkorrektur</span>
          <p class="text-xs text-zinc-500">
            Gleicht den festen Versatz des Druckers aus. Der Kalibrierbogen unten sagt, welche Werte
            hier hingehören – die Seitengröße bleibt unverändert.
          </p>
          <div class="grid grid-cols-2 gap-3">
            <label class="flex flex-col gap-1 text-xs text-zinc-500">
              nach rechts (mm)
              <input
                v-model.number="offsetXMm"
                type="number"
                step="0.1"
                :min="-maxOffsetMm"
                :max="maxOffsetMm"
                class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
                @change="offsetXMm = clampOffset(offsetXMm)"
              />
            </label>
            <label class="flex flex-col gap-1 text-xs text-zinc-500">
              nach unten (mm)
              <input
                v-model.number="offsetYMm"
                type="number"
                step="0.1"
                :min="-maxOffsetMm"
                :max="maxOffsetMm"
                class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
                @change="offsetYMm = clampOffset(offsetYMm)"
              />
            </label>
          </div>
        </div>

        <label
          class="flex items-center gap-2 rounded-md grey-background light-grey-stroke px-3 py-2 text-sm"
        >
          <input v-model="drawOutlines" type="checkbox" class="accent-blue-600" />
          <span class="light-grey-text">Kartenumrisse mitdrucken (nur zum Testen)</span>
        </label>

        <button
          type="button"
          class="w-full rounded-md grey-background light-grey-stroke py-2 text-sm light-grey-text hover:border-blue-500 transition-colors"
          @click="downloadCalibrationSheet"
        >
          Kalibrierbogen herunterladen
        </button>
        <p class="text-xs text-zinc-500">
          Auf Normalpapier drucken, auf einen leeren Bogen legen, gegen das Licht halten und die
          Abweichung oben eintragen.
        </p>
      </div>

      <!-- Trockenlauf -->
      <div class="rounded-xl border light-grey-background light-grey-stroke p-6 space-y-4">
        <h3 class="text-sm font-semibold">Trockenlauf</h3>

        <p v-if="!analysis && !isWorking" class="text-xs text-zinc-500">
          Noch keine Datei ausgewertet.
        </p>
        <p v-else-if="isWorking && !analysis" class="text-xs text-zinc-500">Wird gelesen …</p>

        <template v-if="analysis">
          <div class="grid grid-cols-2 gap-3 text-sm">
            <div class="rounded-md grey-background light-grey-stroke px-3 py-2">
              <span class="block text-xs text-zinc-500">Karten</span>
              {{ analysis.records }}
            </div>
            <div class="rounded-md grey-background light-grey-stroke px-3 py-2">
              <span class="block text-xs text-zinc-500">Bögen</span>
              {{ analysis.sheets }}
            </div>
            <div class="rounded-md grey-background light-grey-stroke px-3 py-2">
              <span class="block text-xs text-zinc-500">Kodierung</span>
              {{ analysis.encoding }}
            </div>
            <div class="rounded-md grey-background light-grey-stroke px-3 py-2">
              <span class="block text-xs text-zinc-500">Trennzeichen</span>
              {{ analysis.delimiter }}
            </div>
          </div>

          <div class="space-y-1">
            <span class="text-xs text-zinc-500">Spaltenzuordnung</span>
            <ul class="space-y-1 text-sm">
              <li
                v-for="entry in analysis.mapping"
                :key="entry.field"
                class="flex items-center justify-between gap-3 rounded-md grey-background light-grey-stroke px-3 py-1.5"
              >
                <span class="light-grey-text truncate">
                  {{ entry.label }} <span class="text-zinc-600">←</span> {{ entry.column }}
                </span>
                <span v-if="entry.empty_count > 0" class="shrink-0 text-xs text-amber-400">
                  {{ entry.empty_count }} × leer
                </span>
              </li>
            </ul>
          </div>

          <p v-if="analysis.missing_fields.length" class="text-xs text-zinc-500">
            Ohne Spalte in der Datei und deshalb leer auf der Karte:
            {{ analysis.missing_fields.join(", ") }}.
          </p>

          <p v-if="analysis.ignored_columns.length" class="text-xs text-zinc-500">
            Nicht verwendete Spalten: {{ analysis.ignored_columns.join(", ") }}.
          </p>

          <p
            v-for="warning in analysis.warnings"
            :key="warning"
            class="rounded-md bg-amber-900/20 border border-amber-800 px-3 py-2 text-xs text-amber-400"
          >
            {{ warning }}
          </p>

          <div v-if="analysis.skipped_rows.length" class="space-y-1">
            <span class="text-xs text-amber-400">
              {{ analysis.skipped_rows.length }} Zeile(n) übersprungen – diese Karten fehlen im PDF:
            </span>
            <ul
              class="max-h-40 overflow-y-auto rounded-md grey-background light-grey-stroke divide-y divide-zinc-800 text-sm"
            >
              <li
                v-for="row in analysis.skipped_rows"
                :key="row.line"
                class="flex gap-3 px-3 py-1.5"
              >
                <span class="shrink-0 text-zinc-500">Zeile {{ row.line }}</span>
                <span class="light-grey-text truncate">{{ row.reason }}</span>
              </li>
            </ul>
          </div>
        </template>
      </div>
    </div>

    <!-- Vorschau -->
    <div class="rounded-xl border light-grey-background light-grey-stroke p-6 space-y-4">
      <div class="flex items-center justify-between gap-3">
        <h3 class="text-sm font-semibold">Vorschau</h3>
        <span v-if="isWorking" class="text-xs text-zinc-500">Wird erzeugt …</span>
      </div>

      <div
        class="mx-auto w-full max-w-md overflow-hidden rounded-md grey-background light-grey-stroke"
        :style="previewStyle"
      >
        <iframe
          v-if="previewUrl"
          :src="`${previewUrl}#toolbar=0&navpanes=0&view=Fit`"
          title="Vorschau des Bogens"
          class="h-full w-full"
        ></iframe>
        <div v-else class="flex h-full items-center justify-center text-xs text-zinc-500">
          Noch keine Vorschau
        </div>
      </div>

      <button
        :disabled="!canDownload"
        class="w-full rounded-md bg-blue-600 py-2 font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        @click="download"
      >
        PDF herunterladen
        <span v-if="analysis">
          ({{ analysis.sheets }} {{ analysis.sheets === 1 ? "Bogen" : "Bögen" }})
        </span>
      </button>

      <!-- Druckhinweis -->
      <div
        class="rounded-md border border-amber-800 bg-amber-900/20 px-3 py-2 text-xs text-amber-300 space-y-1"
      >
        <p class="font-semibold">Beim Drucken unbedingt beachten</p>
        <ul class="list-disc space-y-0.5 pl-4">
          <li>
            Größe: „Tatsächliche Größe“ bzw. 100 % – niemals „An Seite anpassen“ oder „Passend
            skalieren“.
          </li>
          <li>Einzug über den manuellen Schacht, Bögen einzeln einlegen.</li>
          <li>Medientyp: Karton, 120–160 g/m².</li>
          <li>Einseitig drucken, kein Duplex.</li>
        </ul>
      </div>
    </div>
  </div>
</template>
