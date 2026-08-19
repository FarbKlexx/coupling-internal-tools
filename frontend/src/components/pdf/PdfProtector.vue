<script setup lang="ts">
import { computed, ref } from "vue";
import { MAX_PASSWORD_BYTES, protectPdf, readErrorDetail } from "@/api/pdf_protect.api";
import axios from "axios";

const selectedFile = ref<File | null>(null);
const password = ref("");
const showPassword = ref(false);
const isLoading = ref(false);
const isDragOver = ref(false);
const errorMessage = ref<string | null>(null);
const successMessage = ref<string | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

/** Die PDF-Spezifikation zählt Bytes, nicht Zeichen – Umlaute zählen doppelt. */
const passwordBytes = computed(() => new TextEncoder().encode(password.value).length);

const passwordTooLong = computed(() => passwordBytes.value > MAX_PASSWORD_BYTES);

const canSubmit = computed(
  () => selectedFile.value !== null && password.value !== "" && !passwordTooLong.value,
);

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function selectFile(file: File | null | undefined) {
  if (!file) return;

  selectedFile.value = file;
  errorMessage.value = null;
  successMessage.value = null;
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
  successMessage.value = null;
  errorMessage.value = null;
}

async function protect() {
  if (!canSubmit.value || !selectedFile.value || isLoading.value) return;

  errorMessage.value = null;
  successMessage.value = null;
  isLoading.value = true;

  try {
    const { blob, filename } = await protectPdf(selectedFile.value, password.value);

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);

    successMessage.value = `${filename} wurde erstellt und heruntergeladen.`;
  } catch (e) {
    console.error(e);
    // Das Backend liefert eine verständliche Meldung (kein PDF, bereits
    // geschützt, …) – die kommt wegen responseType "blob" als Blob an.
    const detail = axios.isAxiosError(e) ? await readErrorDetail(e.response?.data) : null;
    errorMessage.value = detail ?? "Das PDF konnte nicht gesichert werden.";
  } finally {
    isLoading.value = false;
  }
}
</script>

<template>
  <div class="max-w-2xl rounded-xl border light-grey-background light-grey-stroke p-6 space-y-5">
    <div class="space-y-1">
      <h2 class="text-lg font-semibold">PDF mit Passwort sichern</h2>
      <p class="text-xs text-zinc-500">
        Das PDF lässt sich danach nur noch mit dem Passwort öffnen (AES-256). Das Passwort wird
        nirgends gespeichert – geht es verloren, ist die Datei nicht mehr zu öffnen.
      </p>
    </div>

    <!-- Dropzone / File Input -->
    <div class="flex flex-col gap-2">
      <label class="text-sm font-medium">PDF auswählen</label>
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
        <span class="material-symbols-outlined nav-icon--active">picture_as_pdf</span>
        <p class="light-grey-text mt-1">Datei hierher ziehen oder klicken zum Auswählen</p>
        <p class="text-xs text-zinc-500">Eine PDF-Datei</p>
      </div>
      <input
        ref="fileInput"
        type="file"
        accept=".pdf,application/pdf"
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

    <!-- Passwort -->
    <div class="flex flex-col gap-1">
      <label class="text-sm font-medium" for="pdf-password">
        Passwort <span class="text-red-400">*</span>
      </label>
      <div class="relative">
        <input
          id="pdf-password"
          v-model="password"
          :type="showPassword ? 'text' : 'password'"
          autocomplete="new-password"
          placeholder="Passwort zum Öffnen des PDFs"
          class="w-full rounded-md light-grey-background light-grey-stroke py-2 pl-3 pr-11 text-sm outline-none focus:border-blue-500 transition-colors"
          @keyup.enter="protect"
        />
        <button
          type="button"
          class="absolute inset-y-0 right-0 flex items-center px-3 hover:text-white transition-colors"
          :title="showPassword ? 'Passwort verbergen' : 'Passwort anzeigen'"
          @click="showPassword = !showPassword"
        >
          <span class="material-symbols-outlined nav-icon">
            {{ showPassword ? "visibility_off" : "visibility" }}
          </span>
        </button>
      </div>
      <p v-if="passwordTooLong" class="text-xs text-amber-400">
        Zu lang: {{ passwordBytes }} von maximal {{ MAX_PASSWORD_BYTES }} Bytes (Umlaute zählen
        doppelt).
      </p>
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
      @click="protect"
    >
      <span v-if="!isLoading">PDF sichern &amp; herunterladen</span>
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
        Verarbeite...
      </span>
    </button>
  </div>
</template>
