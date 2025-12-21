<template>
  <header
      class="sticky top-0 z-40 w-full grey-stroke grey-background backdrop-blur"
  >
    <div class="mx-auto flex h-15 max-w-350 items-center gap-4 px-6">
      <!-- Logo -->
      <div class="flex items-center gap-2">
        <img
          src="/coupling-int-tools-logo.svg"
          alt="Coupling Logo"
          class="h-8 w-auto"
        />
      </div>

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
