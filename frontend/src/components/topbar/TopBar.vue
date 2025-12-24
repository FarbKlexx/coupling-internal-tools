<template>
  <header
      class="sticky top-0 z-40 w-full grey-stroke grey-background backdrop-blur"
  >
    <div class="mx-4 grid grid-cols-3 items-center h-15">
    <!-- Logo -->
        <img
          src="/coupling-int-tools-logo.svg"
          alt="Coupling Logo"
          class="h-8 w-auto"
        />

      <!-- Search -->
      <SearchBar></SearchBar>

      <!-- Actions -->
      <profile-area></profile-area>
    </div>
  </header>
</template>

<script setup lang="ts">
import SearchBar from "./SearchBar.vue";
import ProfileArea from "./ProfileArea.vue";
</script>
