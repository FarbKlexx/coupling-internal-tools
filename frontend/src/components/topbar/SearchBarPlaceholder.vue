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
    <div class="search-field flex items-center gap-3 px-2 py-2">
      <span class="material-symbols-outlined nav-icon"> search </span>

      <input
        placeholder="Click to search"
        readonly
        class="w-full cursor-pointer bg-transparent grey-text focus:outline-none"
        @click="openSearch"
        autocomplete="off"
      />
    </div>
  </div>
  <!-- `transition` statt einer Animation in der Palette selbst: eine
       Animation laeuft nur beim Einhaengen, das Zumachen saehe man nicht.
       Vuetify haengt die Uebergangsklassen an seinen Inhalt, definiert
       sind sie in `style.css`. -->
  <v-overlay
    v-model="overlay"
    transition="search-palette"
    class="mt-40 flex justify-center content-center"
  >
    <SearchBar @close="overlay = false" ref="searchBarRef"></SearchBar>
  </v-overlay>
</template>

<style scoped></style>
