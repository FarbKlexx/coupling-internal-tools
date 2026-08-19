<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import axios from "axios";
import {
  convertImagesToWebp,
  DEFAULT_QUALITY,
  estimateWebpSizes,
  interpolateSize,
  MAX_QUALITY,
  MIN_QUALITY,
  type FileEstimate,
} from "@/api/image_convert.api";

/** Vom Backend akzeptierte Eingabeformate (nur fürs Datei-Dialog-Filtering). */
const ACCEPTED_EXTENSIONS = "image/*,.jpg,.jpeg,.jpe,.png,.webp,.gif,.bmp,.tif,.tiff,.heic,.heif";

/** Parallele Schätz-Requests. Das Backend rechnet pro Bild bereits mehrkernig. */
const ESTIMATE_CONCURRENCY = 2;

const selectedFiles = ref<File[]>([]);
const quality = ref(DEFAULT_QUALITY);
const isLoading = ref(false);
const isDragOver = ref(false);
const errorMessage = ref<string | null>(null);
const successMessage = ref<string | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

/** Gemessene Größenkurven, gecacht pro Datei — Key: Name + Größe + Zeitstempel. */
const estimates = ref(new Map<string, FileEstimate>());
/** Keys der Dateien, deren Messung gerade läuft oder eingeplant ist. */
const inFlight = ref(new Set<string>());
const estimateFailed = ref(false);
let estimateController: AbortController | null = null;

const canSubmit = computed(() => selectedFiles.value.length > 0);

const isEstimating = computed(() => inFlight.value.size > 0);

function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function estimateFor(file: File): FileEstimate | undefined {
  return estimates.value.get(fileKey(file));
}

type RowStatus = "ready" | "pending" | "skipped";

interface FileRow {
  file: File;
  key: string;
  status: RowStatus;
  /** Geschätzte WebP-Größe bei der aktuell eingestellten Qualität. */
  estimated: number | null;
  /** Ersparnis in Prozent, positiv = kleiner als das Original. */
  savings: number | null;
}

/**
 * Eine Zeile pro Datei, inklusive der aus den Messpunkten interpolierten
 * Zielgröße. Hängt an `quality`, wird also bei jeder Regler-Bewegung neu
 * berechnet – reine Arithmetik, kein Request.
 */
const rows = computed<FileRow[]>(() =>
  selectedFiles.value.map((file) => {
    const estimate = estimateFor(file);

    if (!estimate) {
      return { file, key: fileKey(file), status: "pending", estimated: null, savings: null };
    }
    if (!estimate.supported) {
      return { file, key: fileKey(file), status: "skipped", estimated: null, savings: null };
    }

    const estimated = interpolateSize(estimate.samples, quality.value);
    const savings =
      estimated === null || file.size === 0 ? null : Math.round((1 - estimated / file.size) * 100);

    return { file, key: fileKey(file), status: "ready", estimated, savings };
  }),
);

const originalTotal = computed(() => selectedFiles.value.reduce((sum, file) => sum + file.size, 0));

const estimatedTotal = computed(() =>
  rows.value.reduce((sum, row) => sum + (row.estimated ?? 0), 0),
);

/** Nur vollständig, wenn für jede Datei eine Messung vorliegt. */
const totalIsComplete = computed(() => rows.value.every((row) => row.status !== "pending"));

const totalSavings = computed(() => {
  if (originalTotal.value === 0 || estimatedTotal.value === 0) return null;
  return Math.round((1 - estimatedTotal.value / originalTotal.value) * 100);
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
 * Holt die Größenkurven für alle noch nicht vermessenen Dateien nach.
 * Jede Datei geht einzeln raus, damit die Liste sich nach und nach füllt.
 */
async function refreshEstimates() {
  const missing = selectedFiles.value.filter(
    (file) => !estimates.value.has(fileKey(file)) && !inFlight.value.has(fileKey(file)),
  );
  if (missing.length === 0) return;

  estimateController ??= new AbortController();
  const { signal } = estimateController;

  estimateFailed.value = false;
  missing.forEach((file) => inFlight.value.add(fileKey(file)));

  const queue = [...missing];
  const worker = async () => {
    while (queue.length > 0) {
      const file = queue.shift();
      if (!file) return;

      try {
        const [estimate] = await estimateWebpSizes([file], signal);
        if (estimate) estimates.value.set(fileKey(file), estimate);
      } catch (e) {
        if (axios.isCancel(e)) return;
        console.error(e);
        estimateFailed.value = true;
      } finally {
        inFlight.value.delete(fileKey(file));
      }
    }
  };

  await Promise.all(Array.from({ length: Math.min(ESTIMATE_CONCURRENCY, missing.length) }, worker));
}

function cancelEstimates() {
  estimateController?.abort();
  estimateController = null;
  inFlight.value.clear();
}

watch(selectedFiles, () => void refreshEstimates());

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
    );

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);

    successMessage.value =
      `${convertedCount} Bild(er) konvertiert und als ${filename} heruntergeladen.` +
      (skippedCount > 0
        ? ` ${skippedCount} Datei(en) wurden übersprungen – Details stehen im ZIP.`
        : "");
  } catch (e) {
    console.error(e);
    errorMessage.value = "Konvertierung fehlgeschlagen. Bitte prüfe die ausgewählten Dateien.";
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
        JPG, JPEG, PNG, HEIC, GIF, TIFF und BMP werden zu WebP konvertiert und als ZIP
        heruntergeladen.
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
        <span class="light-grey-text truncate">{{ row.file.name }}</span>

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
          <span v-else-if="row.status === 'skipped'" class="text-xs text-amber-400">
            wird übersprungen
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

      <p v-if="estimateFailed" class="text-xs text-amber-400">
        Die Größenvorschau konnte nicht für alle Dateien berechnet werden. Die Konvertierung
        funktioniert trotzdem.
      </p>
    </div>
    <p v-else class="text-xs text-zinc-500">Noch keine Dateien ausgewählt.</p>

    <div class="border-t light-grey-stroke" />

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
