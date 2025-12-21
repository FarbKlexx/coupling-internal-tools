<template>
  <aside
    class="w-64 shrink-0 overflow-y-auto grey-background grey-stroke"
  >
    <nav class="flex flex-col gap-1 p-4">
      <SidebarItem icon="dashboard" label="Dashboard" />
      <SidebarItem icon="bar_chart" label="Analytics" />
      <SidebarItem icon="shopping_cart" label="Orders" />
      <SidebarItem icon="group" label="Customers" />
      <SidebarItem icon="settings" label="Settings" />

      <!-- Spacer -->
      <div class="flex-1" />

      <SidebarItem icon="logout" label="Logout" />
    </nav>
  </aside>
</template>

<script setup lang="ts">
import SidebarItem from "./SidebarItem.vue";
</script>
