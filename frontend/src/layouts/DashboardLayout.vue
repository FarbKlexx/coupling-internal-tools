<template>
  <div class="flex min-h-screen flex-col">
    <!-- Topbar -->
    <TopBar />

    <!-- Body -->
    <!-- light-grey-background: liegt hinter <main>, damit dessen
         abgerundete obere linke Ecke die Nav-Farbe durchscheinen laesst. -->
    <div class="flex flex-1 overflow-hidden light-grey-background">
      <!-- Sidebar -->
      <Sidebar />

      <!-- Main Content -->
      <!-- min-w-0: ohne das kann <main> nicht schmaler werden als sein
           Inhalt, und eine breite Seite (Kanban-Board) schiebt Sidebar und
           Topbar aus dem Bild statt selbst zu scrollen. -->
      <main class="min-w-0 flex-1 rounded-tl-xl grey-background p-6">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import TopBar from "../components/topbar/TopBar.vue";
import Sidebar from "../components/sidebar/SideBar.vue";
</script>
