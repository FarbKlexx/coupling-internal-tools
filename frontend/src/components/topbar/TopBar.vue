<template>
  <header class="sticky top-0 z-40 w-full grey-stroke light-grey-background backdrop-blur">
    <div class="mx-4 grid grid-cols-3 items-center h-15">
      <!-- Burger + Logo -->
      <div class="flex items-center gap-3">
        <button
          class="icon-button flex items-center rounded-md p-1 transition"
          :aria-label="collapsed ? 'Navigation ausklappen' : 'Navigation einklappen'"
          :aria-expanded="!collapsed"
          @click="toggle"
        >
          <span class="material-symbols-outlined nav-icon--active">menu</span>
        </button>

        <img src="/coupling-int-tools-logo.svg" alt="Coupling Logo" class="h-8 w-auto" />
      </div>

      <!-- Search -->
      <SearchBarPlaceholder></SearchBarPlaceholder>
      <!-- Actions -->
      <profile-area></profile-area>
    </div>
  </header>
</template>

<script setup lang="ts">
import SearchBarPlaceholder from "./SearchBarPlaceholder.vue";
import ProfileArea from "./ProfileArea.vue";
import { useSidebar } from "@/composables/useSidebar";

const { collapsed, toggle } = useSidebar();
</script>
