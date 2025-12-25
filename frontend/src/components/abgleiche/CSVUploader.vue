<script setup lang="ts">
import { ref } from "vue";
import { uploadCsv } from "@/api/upload.api";
import type { UploadOption } from "@/api/types";

const selectedFile = ref<File | null>(null);
const option = ref<UploadOption>("jf_to_awin");
const isLoading = ref(false);
const error = ref<string | null>(null);

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];

  if (!file) {
    selectedFile.value = null;
    return;
  }

  selectedFile.value = file;
}

async function upload() {
  if (!selectedFile.value) return;

  try {
    isLoading.value = true;

    const { blob, filename } = await uploadCsv(selectedFile.value, option.value);

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    error.value = "Upload fehlgeschlagen";
  } finally {
    isLoading.value = false;
  }
}
</script>

<template>
  <div class="max-w-md rounded-xl border light-grey-background light-grey-stroke p-6 space-y-4">
    <h2 class="text-lg font-semibold">CSV konvertieren</h2>

    <!-- Option -->
    <div class="flex flex-col gap-1">
      <label class="text-sm">Konvertierungsoption</label>
      <select v-model="option" class="rounded-md light-grey-background light-grey-stroke px-3 py-2">
        <option value="jf_to_awin">JeansFritz zu AWIN</option>
        <option value="jf_bonus">JeansFritz Bonus</option>
      </select>
    </div>

    <!-- File Input -->
    <div class="flex flex-col gap-1">
      <label class="text-sm">CSV Datei (UTF-8)</label>
      <input
        type="file"
        accept=".csv,text/csv"
        @change="onFileChange"
        class="block w-full text-sm light-grey-text file:mr-4 file:rounded-md file:border-0 file:bg-zinc-700 file:px-4 file:py-2 file:text-sm file:font-semibold hover:file:bg-zinc-600"
      />
    </div>

    <!-- Error -->
    <p v-if="error" class="text-sm text-red-400">
      {{ error }}
    </p>

    <!-- Button -->
    <button
      @click="upload"
      :disabled="isLoading"
      class="w-full rounded-md bg-blue-600 py-2 font-medium hover:bg-blue-500 disabled:opacity-50"
    >
      <span v-if="!isLoading">Konvertieren & herunterladen</span>
      <span v-else>Verarbeite...</span>
    </button>
  </div>
</template>
