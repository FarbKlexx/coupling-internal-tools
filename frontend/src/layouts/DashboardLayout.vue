<template>
  <div class="flex min-h-screen flex-col">
    <!-- Topbar -->
    <TopBar />

    <!-- Body -->
    <div class="flex flex-1 overflow-hidden">
      <!-- Sidebar -->
      <Sidebar />

      <!-- Main Content -->
      <main class="flex-1 p-6">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import TopBar from "../components/topbar/TopBar.vue";
import Sidebar from "../components/sidebar/SideBar.vue";
</script>
