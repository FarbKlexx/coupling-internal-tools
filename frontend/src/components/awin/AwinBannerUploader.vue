<script setup lang="ts">
import { ref, computed } from "vue";
import { generateAwinBannerCsv } from "@/api/awin_banner.api";

const selectedFiles = ref<string[]>([]);
const description = ref("");
const tag = ref("");
const targetUrl = ref("");
const altText = ref("");
const imageSourceStem = ref("");
const isLoading = ref(false);
const errorMessage = ref<string | null>(null);

const canSubmit = computed(
  () =>
    selectedFiles.value.length > 0 &&
    description.value.trim() !== "" &&
    tag.value.trim() !== "" &&
    targetUrl.value.trim() !== "" &&
    altText.value.trim() !== "" &&
    imageSourceStem.value.trim() !== "",
);

function onFilesChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = input.files;
  if (!files || files.length === 0) {
    selectedFiles.value = [];
    return;
  }
  selectedFiles.value = Array.from(files).map((f) => f.name);
}

function removeFile(index: number) {
  selectedFiles.value = selectedFiles.value.filter((_, i) => i !== index);
}

async function generateCsv() {
  if (!canSubmit.value) return;

  errorMessage.value = null;
  isLoading.value = true;

  try {
    const blob = await generateAwinBannerCsv({
      filenames: selectedFiles.value,
      description: description.value.trim(),
      tag: tag.value.trim(),
      target_url: targetUrl.value.trim(),
      alt_text: altText.value.trim(),
      image_source_stem: imageSourceStem.value.trim(),
    });

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "awin_banners.csv";
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    console.error(e);
    errorMessage.value = "Fehler beim Generieren der CSV. Bitte prüfe die Eingaben.";
  } finally {
    isLoading.value = false;
  }
}
</script>

<template>
  <div class="max-w-2xl rounded-xl border light-grey-background light-grey-stroke p-6 space-y-5">
    <h2 class="text-lg font-semibold">AWIN Banner CSV generieren</h2>

    <!-- File Input -->
    <div class="flex flex-col gap-2">
      <label class="text-sm font-medium">Banner-Dateien auswählen</label>
      <input
        type="file"
        multiple
        @change="onFilesChange"
        class="block w-full text-sm light-grey-text file:mr-4 file:rounded-md file:border-0 file:bg-zinc-700 file:px-4 file:py-2 file:text-sm file:font-semibold hover:file:bg-zinc-600 cursor-pointer"
      />
      <div v-if="selectedFiles.length > 0" class="mt-1 flex flex-col gap-1">
        <div
          v-for="(name, i) in selectedFiles"
          :key="i"
          class="flex items-center justify-between rounded-md px-3 py-1.5 text-sm grey-background light-grey-stroke"
        >
          <span class="light-grey-text truncate mr-2">{{ name }}</span>
          <button
            @click="removeFile(i)"
            class="text-zinc-500 hover:text-red-400 shrink-0 transition-colors"
            title="Entfernen"
          >
            ✕
          </button>
        </div>
      </div>
      <p v-else class="text-xs text-zinc-500">Noch keine Dateien ausgewählt.</p>
    </div>

    <div class="border-t light-grey-stroke" />

    <!-- Common Attributes -->
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium">Description <span class="text-red-400">*</span></label>
        <input
          v-model="description"
          type="text"
          placeholder="z.B. Sommer Sale Banner"
          class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
        />
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium">Tag <span class="text-red-400">*</span></label>
        <input
          v-model="tag"
          type="text"
          placeholder="z.B. sommer-2024"
          class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
        />
      </div>

      <div class="flex flex-col gap-1 sm:col-span-2">
        <label class="text-sm font-medium">Target URL <span class="text-red-400">*</span></label>
        <input
          v-model="targetUrl"
          type="url"
          placeholder="https://www.example.com/landing-page"
          class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
        />
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium">Alt Text <span class="text-red-400">*</span></label>
        <input
          v-model="altText"
          type="text"
          placeholder="z.B. Sommer Sale – Jetzt shoppen"
          class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
        />
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium"
          >Image Source Stem <span class="text-red-400">*</span></label
        >
        <input
          v-model="imageSourceStem"
          type="text"
          placeholder="z.B. https://cdn.example.com/banners/"
          class="rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
        />
      </div>
    </div>

    <!-- Error -->
    <p v-if="errorMessage" class="rounded-md bg-red-900/30 border border-red-700 px-3 py-2 text-sm text-red-400">
      {{ errorMessage }}
    </p>

    <!-- Submit -->
    <button
      @click="generateCsv"
      :disabled="!canSubmit || isLoading"
      class="w-full rounded-md bg-blue-600 py-2 font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
    >
      <span v-if="!isLoading">CSV generieren & herunterladen</span>
      <span v-else class="flex items-center justify-center gap-2">
        <svg class="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
        </svg>
        Verarbeite...
      </span>
    </button>

    <p v-if="!canSubmit && selectedFiles.length > 0" class="text-xs text-zinc-500 text-center">
      Bitte alle Pflichtfelder ausfüllen.
    </p>
  </div>
</template>
