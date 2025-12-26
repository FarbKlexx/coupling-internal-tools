<script setup lang="ts">
import { ref, nextTick } from "vue";
import SearchBar from "@/components/topbar/SearchBar.vue";

const overlay = ref<boolean>(false);

const searchBarRef = ref<InstanceType<typeof SearchBar> | null>(null);

function openSearch() {
  overlay.value = !overlay.value;

  nextTick(() => {
    searchBarRef.value?.focus();
  });
}
</script>

<template>
  <div class="relative w-sm mx-auto">
    <div
      class="flex items-center gap-3 rounded-xl border light-grey-stroke light-grey-background px-2 py-2"
    >
      <span class="material-symbols-outlined nav-icon"> search </span>

      <input
        placeholder="Click to search"
        readonly
        class="w-full bg-transparent grey-text focus:outline-none"
        @click="openSearch"
        autocomplete="off"
      />
    </div>
  </div>
  <v-overlay v-model="overlay" class="mt-40 flex justify-center content-center">
    <SearchBar @close="overlay = false" ref="searchBarRef"></SearchBar>
  </v-overlay>
</template>

<style scoped></style>
