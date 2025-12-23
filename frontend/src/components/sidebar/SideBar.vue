<template>
  <aside
    class="w-52 shrink-0 overflow-y-auto grey-background grey-stroke p-4 gap-3 flex flex-col"
  >
  <span class="grey-text eyebrow"> 
    Hauptkategorie
  </span>
    <nav class="flex flex-col gap-1">
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
  { id: 'abgleiche', icon: 'table', label: 'AWIN Abgleiche' },
];

const activeItem = ref(items[0]!.id);
</script>

