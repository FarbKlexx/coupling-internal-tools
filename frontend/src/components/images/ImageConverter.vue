<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import axios from "axios";
import { readErrorDetail } from "@/api/http";
import {
  convertImagesToWebp,
  DEFAULT_QUALITY,
  DEFAULT_SCALE,
  estimateWebpSizes,
  interpolateSize,
  MAX_QUALITY,
  MAX_SCALE,
  MIN_QUALITY,
  MIN_SCALE,
  SCALE_STEP,
  type FileEstimate,
} from "@/api/image_convert.api";

/** Vom Backend akzeptierte Eingabeformate (nur fürs Datei-Dialog-Filtering). */
const ACCEPTED_EXTENSIONS = "image/*,.jpg,.jpeg,.jpe,.png,.webp,.gif,.bmp,.tif,.tiff,.heic,.heif";

/** Parallele Schätz-Requests. Das Backend rechnet pro Bild bereits mehrkernig. */
const ESTIMATE_CONCURRENCY = 2;

/**
 * Ab dieser Dateigröße wird nur noch eine Datei zur Zeit vermessen. Große
 * Bilder kosten im Backend hunderte MB pro Messung; zwei davon gleichzeitig
 * summieren sich, und der Container stirbt am Speicher statt eine Vorschau zu
 * liefern. Die Bytezahl ist nur ein Anhaltspunkt für „viele Pixel" — die echte
 * Grenze zieht das Backend anhand der Auflösung.
 */
const SEQUENTIAL_ABOVE_BYTES = 8 * 1024 * 1024;

/**
 * Wartezeit, bevor eine neue Auflösung vermessen wird. Der Qualitätsregler
 * rechnet lokal, der Auflösungsregler braucht pro Stufe einen Request — ohne
 * Verzögerung würde ein Zug über die Skala ein Dutzend Messungen auslösen.
 */
const SCALE_DEBOUNCE_MS = 400;

const selectedFiles = ref<File[]>([]);
const quality = ref(DEFAULT_QUALITY);
const scale = ref(DEFAULT_SCALE);
const isLoading = ref(false);
const isDragOver = ref(false);
const errorMessage = ref<string | null>(null);
const successMessage = ref<string | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

/**
 * Gemessene Größenkurven, gecacht pro Datei *und* Auflösung — eine Kurve gilt
 * nur für die Auflösung, bei der sie gemessen wurde. Dadurch ist ein Zurück auf
 * eine bereits vermessene Stufe sofort da.
 */
const estimates = ref(new Map<string, FileEstimate>());
/** Keys der Messungen, die gerade laufen oder eingeplant sind. */
const inFlight = ref(new Set<string>());
const estimateFailed = ref(false);
let estimateController: AbortController | null = null;
let estimateTimer: ReturnType<typeof setTimeout> | null = null;

const canSubmit = computed(() => selectedFiles.value.length > 0);

const isEstimating = computed(() => inFlight.value.size > 0);

/** Identität einer Datei — auch für das Filtern von Duplikaten. */
function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

/** Cache-Key einer Messung: dieselbe Datei bei dieser Auflösung. */
function cacheKey(file: File, atScale: number): string {
  return `${fileKey(file)}@${atScale}`;
}

function estimateFor(file: File): FileEstimate | undefined {
  return estimates.value.get(cacheKey(file, scale.value));
}

type RowStatus = "ready" | "pending" | "unmeasured" | "skipped";

interface FileRow {
  file: File;
  key: string;
  status: RowStatus;
  /** Geschätzte WebP-Größe bei der aktuell eingestellten Qualität. */
  estimated: number | null;
  /** Ersparnis in Prozent, positiv = kleiner als das Original. */
  savings: number | null;
  /** Auflösung nach dem Verkleinern, z. B. "1920×1080 → 960×540". */
  resolution: string | null;
  /** Begründung des Backends: warum keine Vorschau bzw. warum übersprungen. */
  hint: string | null;
}

function resolutionLabel(estimate: FileEstimate): string | null {
  const { width, height, scaled_width: targetWidth, scaled_height: targetHeight } = estimate;
  if (width === null || height === null) return null;

  const source = `${width}×${height}`;
  if (targetWidth === null || targetHeight === null) return source;
  if (targetWidth === width && targetHeight === height) return source;

  return `${source} → ${targetWidth}×${targetHeight}`;
}

/**
 * Eine Zeile pro Datei, inklusive der aus den Messpunkten interpolierten
 * Zielgröße. Hängt an `quality`, wird also bei jeder Regler-Bewegung neu
 * berechnet – reine Arithmetik, kein Request. Eine neue Auflösung dagegen
 * wechselt die Messkurve, weshalb die Zeilen dort kurz auf "pending" fallen.
 */
const rows = computed<FileRow[]>(() =>
  selectedFiles.value.map((file) => {
    const estimate = estimateFor(file);
    // Die Zeilen-Identität ist die Datei, nicht die Messung — sonst würde jede
    // Reglerstufe die DOM-Zeilen neu aufbauen statt sie zu aktualisieren.
    const blank = {
      file,
      key: fileKey(file),
      estimated: null,
      savings: null,
      resolution: null,
      hint: null,
    };

    if (!estimate) return { ...blank, status: "pending" };

    const resolution = resolutionLabel(estimate);

    if (!estimate.supported) {
      return { ...blank, status: "skipped", resolution, hint: estimate.error };
    }
    // Zu groß für eine Vorschau, aber kein Fehler: die Datei wird konvertiert.
    if (!estimate.measurable) {
      return { ...blank, status: "unmeasured", resolution, hint: estimate.note };
    }

    const estimated = interpolateSize(estimate.samples, quality.value);
    const savings =
      estimated === null || file.size === 0 ? null : Math.round((1 - estimated / file.size) * 100);

    return { ...blank, status: "ready", estimated, savings, resolution };
  }),
);

const originalTotal = computed(() => selectedFiles.value.reduce((sum, file) => sum + file.size, 0));

const estimatedTotal = computed(() =>
  rows.value.reduce((sum, row) => sum + (row.estimated ?? 0), 0),
);

/**
 * Nur vollständig, wenn für jede Datei eine Messung vorliegt. Dateien ohne
 * Vorschau steuern 0 B bei, die Summe ist dann eine Untergrenze.
 */
const totalIsComplete = computed(() =>
  rows.value.every((row) => row.status === "ready" || row.status === "skipped"),
);

/** Dateien, die konvertiert werden, für die es aber keine Vorschau gibt. */
const unmeasuredRows = computed(() => rows.value.filter((row) => row.status === "unmeasured"));

const totalSavings = computed(() => {
  if (originalTotal.value === 0 || estimatedTotal.value === 0) return null;
  return Math.round((1 - estimatedTotal.value / originalTotal.value) * 100);
});

const scaleHint = computed(() => {
  if (scale.value >= MAX_SCALE) return "Originalauflösung, es wird nur komprimiert.";
  if (scale.value >= 75) return "Leicht verkleinert, für Druck und Retina noch ausreichend.";
  if (scale.value >= 50) return "Halbe Kantenlänge: passend für normale Web-Darstellung.";
  if (scale.value >= 25) return "Stark verkleinert, geeignet für Thumbnails und Vorschauen.";
  return "Minimale Auflösung, nur noch als Miniatur brauchbar.";
});

const qualityHint = computed(() => {
  if (quality.value >= 90) return "Kaum sichtbarer Qualitätsverlust, größere Dateien.";
  if (quality.value >= 70) return "Empfohlen: guter Kompromiss aus Qualität und Größe.";
  if (quality.value >= 40) return "Deutlich kleinere Dateien, sichtbarer Qualitätsverlust.";
  return "Maximale Kompression, starker Qualitätsverlust.";
});

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Holt die Größenkurven für alle bei der aktuellen Auflösung noch nicht
 * vermessenen Dateien nach. Jede Datei geht einzeln raus, damit die Liste sich
 * nach und nach füllt. Die Auflösung wird beim Start festgehalten: bewegt der
 * Nutzer den Regler weiter, landet das Ergebnis unter der Stufe, für die es
 * gemessen wurde – nicht unter der gerade sichtbaren.
 */
async function refreshEstimates() {
  const atScale = scale.value;
  const missing = selectedFiles.value.filter((file) => {
    const key = cacheKey(file, atScale);
    return !estimates.value.has(key) && !inFlight.value.has(key);
  });
  if (missing.length === 0) return;

  estimateController ??= new AbortController();
  const { signal } = estimateController;

  estimateFailed.value = false;
  missing.forEach((file) => inFlight.value.add(cacheKey(file, atScale)));

  const queue = [...missing];
  const worker = async () => {
    while (queue.length > 0) {
      const file = queue.shift();
      if (!file) return;

      try {
        const [estimate] = await estimateWebpSizes([file], atScale, signal);
        if (estimate) estimates.value.set(cacheKey(file, atScale), estimate);
      } catch (e) {
        if (axios.isCancel(e)) return;
        console.error(e);
        estimateFailed.value = true;
      } finally {
        inFlight.value.delete(cacheKey(file, atScale));
      }
    }
  };

  // Große Dateien nacheinander: siehe SEQUENTIAL_ABOVE_BYTES.
  const concurrency = missing.some((file) => file.size > SEQUENTIAL_ABOVE_BYTES)
    ? 1
    : ESTIMATE_CONCURRENCY;

  await Promise.all(Array.from({ length: Math.min(concurrency, missing.length) }, worker));
}

/** Messung einplanen; ein bereits geplanter Lauf wird dabei verworfen. */
function scheduleEstimates(delay = 0) {
  if (estimateTimer) clearTimeout(estimateTimer);
  estimateTimer = setTimeout(() => {
    estimateTimer = null;
    void refreshEstimates();
  }, delay);
}

function cancelEstimates() {
  if (estimateTimer) clearTimeout(estimateTimer);
  estimateTimer = null;
  estimateController?.abort();
  estimateController = null;
  inFlight.value.clear();
}

watch(selectedFiles, () => scheduleEstimates());
// Laufende Messungen bleiben stehen: sie gehören zu ihrer eigenen Stufe und
// füllen den Cache, in den der Regler zurückkehren kann.
watch(scale, () => scheduleEstimates(SCALE_DEBOUNCE_MS));

onUnmounted(cancelEstimates);

function addFiles(files: FileList | null) {
  if (!files || files.length === 0) return;

  successMessage.value = null;
  errorMessage.value = null;

  // Mehrfachauswahl soll ergänzen, nicht ersetzen – Duplikate werden gefiltert.
  const known = new Set(selectedFiles.value.map(fileKey));
  const added = Array.from(files).filter((file) => !known.has(fileKey(file)));

  selectedFiles.value = [...selectedFiles.value, ...added];
}

function onFilesChange(event: Event) {
  const input = event.target as HTMLInputElement;
  addFiles(input.files);
  // Zurücksetzen, damit dieselbe Datei erneut ausgewählt werden kann.
  input.value = "";
}

function onDrop(event: DragEvent) {
  isDragOver.value = false;
  addFiles(event.dataTransfer?.files ?? null);
}

function removeFile(index: number) {
  selectedFiles.value = selectedFiles.value.filter((_, i) => i !== index);
}

function clearFiles() {
  cancelEstimates();
  selectedFiles.value = [];
  estimates.value = new Map();
  successMessage.value = null;
  errorMessage.value = null;
}

async function convert() {
  if (!canSubmit.value || isLoading.value) return;

  errorMessage.value = null;
  successMessage.value = null;
  isLoading.value = true;

  try {
    const { blob, filename, convertedCount, skippedCount } = await convertImagesToWebp(
      selectedFiles.value,
      quality.value,
      scale.value,
    );

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);

    const settings =
      scale.value < MAX_SCALE
        ? `${scale.value} % Auflösung, Qualität ${quality.value}`
        : `Qualität ${quality.value}`;

    successMessage.value =
      `${convertedCount} Bild(er) mit ${settings} konvertiert und als ${filename} heruntergeladen.` +
      (skippedCount > 0
        ? ` ${skippedCount} Datei(en) wurden übersprungen – Details stehen im ZIP.`
        : "");
  } catch (e) {
    console.error(e);
    // Das Backend begründet die Ablehnung pro Datei ("… überschreitet die
    // WebP-Grenze von 16383 px, mit höchstens 96 % Auflösung passt es") — nur
    // damit weiß der Nutzer, welchen Regler er anfassen muss. Bei
    // `responseType: "blob"` steckt das JSON in einem Blob.
    const detail = axios.isAxiosError(e) ? await readErrorDetail(e.response?.data) : null;
    errorMessage.value =
      detail ?? "Konvertierung fehlgeschlagen. Bitte prüfe die ausgewählten Dateien.";
  } finally {
    isLoading.value = false;
  }
}
</script>

<template>
  <div class="max-w-2xl rounded-xl border light-grey-background light-grey-stroke p-6 space-y-5">
    <div class="space-y-1">
      <h2 class="text-lg font-semibold">Bilder zu WebP konvertieren</h2>
      <p class="text-xs text-zinc-500">
        JPG, JPEG, PNG, HEIC, GIF, TIFF und BMP werden zuerst auf die gewählte Auflösung
        verkleinert, dann als WebP kodiert und als ZIP heruntergeladen.
      </p>
    </div>

    <!-- Dropzone / File Input -->
    <div class="flex flex-col gap-2">
      <label class="text-sm font-medium">Bilder auswählen</label>
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
        <span class="material-symbols-outlined nav-icon--active">add_photo_alternate</span>
        <p class="light-grey-text mt-1">Dateien hierher ziehen oder klicken zum Auswählen</p>
        <p class="text-xs text-zinc-500">Mehrfachauswahl möglich</p>
      </div>
      <input
        ref="fileInput"
        type="file"
        multiple
        :accept="ACCEPTED_EXTENSIONS"
        class="hidden"
        @change="onFilesChange"
      />
    </div>

    <!-- Dateiliste mit Größenvorschau -->
    <div v-if="selectedFiles.length > 0" class="flex flex-col gap-1">
      <div class="flex items-center justify-between">
        <span class="text-xs text-zinc-500">
          {{ selectedFiles.length }} Datei(en)
          <span v-if="isEstimating"> · Größen werden berechnet …</span>
        </span>
        <button
          class="text-xs text-zinc-500 hover:text-red-400 transition-colors"
          @click="clearFiles"
        >
          Alle entfernen
        </button>
      </div>

      <div
        v-for="(row, i) in rows"
        :key="row.key"
        class="flex items-center justify-between gap-3 rounded-md px-3 py-1.5 text-sm grey-background light-grey-stroke"
      >
        <span class="min-w-0 flex flex-col">
          <span class="light-grey-text truncate">{{ row.file.name }}</span>
          <span v-if="row.resolution" class="text-xs text-zinc-500 tabular-nums">
            {{ row.resolution }} px
          </span>
        </span>

        <span class="flex items-center gap-2 shrink-0 tabular-nums">
          <span class="text-xs text-zinc-500">{{ formatSize(row.file.size) }}</span>

          <template v-if="row.status === 'ready' && row.estimated !== null">
            <span class="text-xs text-zinc-600">→</span>
            <span class="text-xs white-text">≈ {{ formatSize(row.estimated) }}</span>
            <span
              v-if="row.savings !== null"
              :class="[
                'rounded px-1.5 py-0.5 text-xs',
                row.savings > 0
                  ? 'bg-emerald-900/40 text-emerald-400'
                  : 'bg-amber-900/40 text-amber-400',
              ]"
            >
              {{ row.savings > 0 ? "−" : "+" }}{{ Math.abs(row.savings) }} %
            </span>
          </template>
          <span
            v-else-if="row.status === 'skipped'"
            class="text-xs text-amber-400"
            :title="row.hint ?? undefined"
          >
            wird übersprungen
          </span>
          <span
            v-else-if="row.status === 'unmeasured'"
            class="text-xs text-zinc-500"
            :title="row.hint ?? undefined"
          >
            keine Vorschau
          </span>
          <span v-else class="text-xs text-zinc-600">wird berechnet …</span>

          <button
            class="text-zinc-500 hover:text-red-400 transition-colors"
            title="Entfernen"
            @click="removeFile(i)"
          >
            ✕
          </button>
        </span>
      </div>

      <!-- Summe -->
      <div
        class="mt-1 flex items-center justify-between rounded-md px-3 py-2 text-sm light-grey-background light-grey-stroke"
      >
        <span class="white-text font-medium">Gesamt</span>
        <span class="flex items-center gap-2 tabular-nums">
          <span class="text-xs light-grey-text">{{ formatSize(originalTotal) }}</span>
          <span class="text-xs text-zinc-600">→</span>
          <span class="text-xs white-text">
            {{ totalIsComplete ? "≈" : "mind." }} {{ formatSize(estimatedTotal) }}
          </span>
          <span
            v-if="totalSavings !== null"
            class="rounded px-1.5 py-0.5 text-xs bg-emerald-900/40 text-emerald-400"
          >
            −{{ totalSavings }} %
          </span>
        </span>
      </div>

      <p v-if="unmeasuredRows.length > 0" class="text-xs text-zinc-500">
        {{ unmeasuredRows[0]?.hint }}
      </p>

      <p v-if="estimateFailed" class="text-xs text-amber-400">
        Die Größenvorschau konnte nicht für alle Dateien berechnet werden. Die Konvertierung
        funktioniert trotzdem.
      </p>
    </div>
    <p v-else class="text-xs text-zinc-500">Noch keine Dateien ausgewählt.</p>

    <div class="border-t light-grey-stroke" />

    <!-- Auflösung -->
    <div class="flex flex-col gap-2">
      <div class="flex items-center justify-between">
        <label class="text-sm font-medium" for="scale">Auflösung</label>
        <span class="white-text tabular-nums">{{ scale }} %</span>
      </div>
      <input
        id="scale"
        v-model.number="scale"
        type="range"
        :min="MIN_SCALE"
        :max="MAX_SCALE"
        :step="SCALE_STEP"
        class="w-full accent-blue-600 cursor-pointer"
      />
      <div class="flex justify-between text-xs text-zinc-500">
        <span>{{ MIN_SCALE }} % · kleinste Auflösung</span>
        <span>{{ MAX_SCALE }} % · Original</span>
      </div>
      <p class="text-xs text-zinc-500">{{ scaleHint }}</p>
    </div>

    <!-- Qualität -->
    <div class="flex flex-col gap-2">
      <div class="flex items-center justify-between">
        <label class="text-sm font-medium" for="quality">Qualität</label>
        <span class="white-text tabular-nums">{{ quality }}</span>
      </div>
      <input
        id="quality"
        v-model.number="quality"
        type="range"
        :min="MIN_QUALITY"
        :max="MAX_QUALITY"
        step="1"
        class="w-full accent-blue-600 cursor-pointer"
      />
      <div class="flex justify-between text-xs text-zinc-500">
        <span>{{ MIN_QUALITY }} · kleinste Datei</span>
        <span>{{ MAX_QUALITY }} · beste Qualität</span>
      </div>
      <p class="text-xs text-zinc-500">{{ qualityHint }}</p>
    </div>

    <!-- Meldungen -->
    <p
      v-if="errorMessage"
      class="rounded-md bg-red-900/30 border border-red-700 px-3 py-2 text-sm text-red-400"
    >
      {{ errorMessage }}
    </p>
    <p
      v-if="successMessage"
      class="rounded-md bg-emerald-900/30 border border-emerald-700 px-3 py-2 text-sm text-emerald-400"
    >
      {{ successMessage }}
    </p>

    <!-- Submit -->
    <button
      :disabled="!canSubmit || isLoading"
      class="w-full rounded-md bg-blue-600 py-2 font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      @click="convert"
    >
      <span v-if="!isLoading">Konvertieren &amp; als ZIP herunterladen</span>
      <span v-else class="flex items-center justify-center gap-2">
        <svg class="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
          <circle
            class="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            stroke-width="4"
          />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
        </svg>
        Konvertiere...
      </span>
    </button>
  </div>
</template>
