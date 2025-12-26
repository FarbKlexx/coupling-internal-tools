<script setup lang="ts">
import { ref } from "vue";

const overlay = ref<boolean>(false);
</script>

<template>
  <div class="relative w-sm mx-auto">
    <div
      class="flex items-center gap-3 rounded-xl border light-grey-stroke light-grey-background px-2 py-2"
    >
      <span class="material-symbols-outlined nav-icon"> search </span>

      <input
        type="text"
        placeholder="Type to search"
        class="w-full bg-transparent grey-text focus:outline-none"
        @click="overlay = !overlay"
        autocomplete="off"
      />
    </div>
  </div>
  <v-overlay v-model="overlay"><SearchBar></SearchBar></v-overlay>
</template>

<style scoped></style>
