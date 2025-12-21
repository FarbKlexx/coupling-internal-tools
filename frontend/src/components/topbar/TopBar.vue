<template>
  <header
      class="sticky top-0 z-40 w-full grey-stroke grey-background backdrop-blur"
  >
    <div class="mx-auto flex h-15 max-w-350 items-center justify-between px-6 gap-20">
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
