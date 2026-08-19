<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { generateQrCode, type QrCodeFormat } from "@/api/qr_code.api";

/** Wartezeit nach der letzten Eingabe, bevor die Vorschau neu geholt wird. */
const PREVIEW_DEBOUNCE_MS = 400;

const data = ref("");
const format = ref<QrCodeFormat>("png");
const transparent = ref(false);
const quietZone = ref(false);
const isLoading = ref(false);
const errorMessage = ref<string | null>(null);

/** Ergebnis der letzten Vorschau – wird beim Download direkt gespeichert. */
const previewUrl = ref<string | null>(null);
let previewBlob: Blob | null = null;
let previewFilename = "";

let debounceTimer: ReturnType<typeof setTimeout> | null = null;
let controller: AbortController | null = null;

const hasInput = computed(() => data.value.trim() !== "");
const canDownload = computed(() => previewUrl.value !== null && !isLoading.value);

function releasePreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
  previewUrl.value = null;
  previewBlob = null;
  previewFilename = "";
}

/** Holt den QR-Code für die aktuellen Einstellungen und zeigt ihn als Vorschau. */
async function loadPreview() {
  if (!hasInput.value) {
    releasePreview();
    errorMessage.value = null;
    return;
  }

  controller?.abort();
  controller = new AbortController();

  isLoading.value = true;
  errorMessage.value = null;

  try {
    const { blob, filename } = await generateQrCode({
      data: data.value.trim(),
      format: format.value,
      transparent: transparent.value,
      quiet_zone: quietZone.value,
    });

    releasePreview();
    previewBlob = blob;
    previewFilename = filename;
    previewUrl.value = URL.createObjectURL(blob);
  } catch (e) {
    if ((e as Error)?.name === "CanceledError") return;
    console.error(e);
    releasePreview();
    errorMessage.value = "QR-Code konnte nicht erzeugt werden. Bitte Eingabe prüfen.";
  } finally {
    isLoading.value = false;
  }
}

// Jede Änderung an Inhalt oder Optionen erzeugt eine neue Vorschau; der
// Download benutzt danach genau diese Datei, ohne weiteren Request.
watch([data, format, transparent, quietZone], () => {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => void loadPreview(), PREVIEW_DEBOUNCE_MS);
});

onUnmounted(() => {
  if (debounceTimer) clearTimeout(debounceTimer);
  controller?.abort();
  releasePreview();
});

function download() {
  if (!previewBlob) return;

  const url = URL.createObjectURL(previewBlob);
  const a = document.createElement("a");
  a.href = url;
  a.download = previewFilename;
  a.click();
  URL.revokeObjectURL(url);
}
</script>

<template>
  <div class="max-w-2xl rounded-xl border light-grey-background light-grey-stroke p-6 space-y-5">
    <div class="space-y-1">
      <h2 class="text-lg font-semibold">QR-Code erstellen</h2>
      <p class="text-xs text-zinc-500">
        Link oder Text eingeben und als PNG oder SVG herunterladen. Die Vorschau aktualisiert sich
        automatisch.
      </p>
    </div>

    <!-- Inhalt -->
    <div class="flex flex-col gap-1">
      <label class="text-sm font-medium" for="qr-data">
        Link oder Text <span class="text-red-400">*</span>
      </label>
      <input
        id="qr-data"
        v-model="data"
        type="text"
        placeholder="https://www.example.com/landing-page"
        class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
      />
    </div>

    <!-- Optionen -->
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div class="flex flex-col gap-1">
        <span class="text-sm font-medium">Format</span>
        <div class="flex gap-2">
          <button
            v-for="option in ['png', 'svg'] as QrCodeFormat[]"
            :key="option"
            type="button"
            :class="[
              'flex-1 rounded-md px-3 py-2 text-sm uppercase transition-colors',
              format === option
                ? 'bg-blue-600 text-white'
                : 'grey-background light-grey-stroke light-grey-text hover:border-blue-500',
            ]"
            @click="format = option"
          >
            {{ option }}
          </button>
        </div>
      </div>

      <div class="flex flex-col gap-1">
        <span class="text-sm font-medium">Optionen</span>
        <label
          class="flex items-center gap-2 rounded-md grey-background light-grey-stroke px-3 py-2 text-sm cursor-pointer"
        >
          <input v-model="transparent" type="checkbox" class="accent-blue-600 cursor-pointer" />
          <span class="light-grey-text">Hintergrund transparent</span>
        </label>
        <label
          class="flex items-center gap-2 rounded-md grey-background light-grey-stroke px-3 py-2 text-sm cursor-pointer"
        >
          <input v-model="quietZone" type="checkbox" class="accent-blue-600 cursor-pointer" />
          <span class="light-grey-text">Rand</span>
        </label>
      </div>
    </div>

    <!-- Vorschau -->
    <div class="flex flex-col items-center gap-2">
      <div
        class="flex h-64 w-64 items-center justify-center rounded-md light-grey-stroke overflow-hidden"
        :class="transparent ? 'checkerboard' : 'grey-background'"
      >
        <img
          v-if="previewUrl"
          :src="previewUrl"
          alt="QR-Code Vorschau"
          class="h-full w-full object-contain"
        />
        <span v-else-if="isLoading" class="text-xs text-zinc-500">Wird erzeugt …</span>
        <span v-else class="text-xs text-zinc-500">Noch keine Vorschau</span>
      </div>
      <p v-if="isLoading && previewUrl" class="text-xs text-zinc-500">Wird aktualisiert …</p>
    </div>

    <!-- Fehler -->
    <p
      v-if="errorMessage"
      class="rounded-md bg-red-900/30 border border-red-700 px-3 py-2 text-sm text-red-400"
    >
      {{ errorMessage }}
    </p>

    <!-- Download -->
    <button
      :disabled="!canDownload"
      class="w-full rounded-md bg-blue-600 py-2 font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      @click="download"
    >
      QR-Code als {{ format.toUpperCase() }} herunterladen
    </button>
  </div>
</template>

<style scoped>
/* Schachbrett, damit ein transparenter Hintergrund in der Vorschau sichtbar ist. */
.checkerboard {
  background-color: #2a2a2b;
  background-image:
    linear-gradient(45deg, #1e1e1e 25%, transparent 25%),
    linear-gradient(-45deg, #1e1e1e 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #1e1e1e 75%),
    linear-gradient(-45deg, transparent 75%, #1e1e1e 75%);
  background-size: 16px 16px;
  background-position:
    0 0,
    0 8px,
    8px -8px,
    -8px 0;
}
</style>
