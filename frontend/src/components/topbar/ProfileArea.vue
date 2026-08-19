<script setup lang="ts">
// Mail, Notifications und Avatar sind reine Platzhalter ohne Backend (feste
// Badge-Zahlen, kein Ziel beim Klick). Sie bleiben im Code, werden aber erst
// eingeblendet, wenn es echte Funktionen dahinter gibt.
const SHOW_PLACEHOLDER_ACTIONS = false;
</script>

<template>
  <!-- Container bleibt bestehen: TopBar ist ein 3-Spalten-Grid, sonst rutscht die Suche aus der Mitte. -->
  <div v-if="SHOW_PLACEHOLDER_ACTIONS" class="ml-auto flex items-center gap-4">
    <!-- Inbox -->
    <button class="relative items-center p-0 m-0 w-8 h-8 rounded-full nav-item cursor-pointer">
      <span class="material-symbols-outlined text-lg nav-icon"> mail </span>

      <span class="badge"> 2 </span>
    </button>

    <!-- Notifications -->
    <button class="relative items-center p-0 m-0 w-8 h-8 rounded-full nav-item cursor-pointer">
      <span class="material-symbols-outlined text-lg nav-icon"> notifications </span>

      <span class="badge"> 2 </span>
    </button>

    <!-- Avatar -->
    <button class="flex items-center gap-2 rounded-xl cursor-pointer">
      <div class="h-8 w-8 rounded-full light-grey-background" />
    </button>
  </div>
</template>

<style scoped></style>
