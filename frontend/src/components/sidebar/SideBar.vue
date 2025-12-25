<template>
  <aside
    class="w-52 shrink-0 overflow-y-auto light-grey-background grey-stroke p-4 gap-3 flex flex-col"
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
        :isActive="route.name === item.id"
        @select="selectItem(item.id)"
      />
    </nav>
  </aside>
</template>

<script setup lang="ts">
import SidebarItem from "./SidebarItem.vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();

const items = [
  { id: 'dashboard', icon: 'home', label: 'Dashboard' },
  { id: 'abgleiche', icon: 'table', label: 'AWIN Abgleiche' },
];

function selectItem(id: string) {
  router.push({ name: id });
}
</script>

