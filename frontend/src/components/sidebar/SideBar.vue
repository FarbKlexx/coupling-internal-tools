<template>
  <aside
    class="w-52 shrink-0 overflow-y-auto grey-background grey-stroke"
  >
    <nav class="flex flex-col gap-1 p-4">
      <SidebarItem
        v-for="item in items"
        :key="item.id"
        :icon="item.icon"
        :label="item.label"
        :isActive="activeItem === item.id"
        @select="activeItem = item.id"
      />
    </nav>
  </aside>
</template>

<script setup lang="ts">
import { ref } from "vue";
import SidebarItem from "./SidebarItem.vue";

const items = [
  { id: 'dashboard', icon: 'dashboard', label: 'Dashboard' },
  { id: 'analytics', icon: 'bar_chart', label: 'Analytics' },
  { id: 'orders', icon: 'shopping_cart', label: 'Orders' },
  { id: 'customers', icon: 'group', label: 'Customers' },
  { id: 'settings', icon: 'settings', label: 'Settings' },
];

const activeItem = ref(items[0].id);
</script>

