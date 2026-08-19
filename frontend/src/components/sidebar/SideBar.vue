<template>
  <aside
    class="w-52 shrink-0 overflow-y-auto light-grey-background grey-stroke p-4 gap-3 flex flex-col"
  >
    <span class="grey-text eyebrow"> Hauptkategorie </span>
    <nav class="flex flex-col gap-1">
      <SidebarItem
        v-for="item in visibleItems"
        :key="item.id"
        :icon="item.icon"
        :label="item.label"
        :isActive="route.name === item.id"
        @select="selectItem(item.id)"
        class="cursor-pointer"
      />
    </nav>
  </aside>
</template>

<script setup lang="ts">
import SidebarItem from "./SidebarItem.vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();

// `enabled: false` blendet einen Eintrag aus, ohne ihn zu entfernen.
const items = [
  { id: "dashboard", icon: "home", label: "Dashboard", enabled: false },
  { id: "abgleiche", icon: "table", label: "AWIN Abgleiche" },
  { id: "awin-banner", icon: "image", label: "AWIN Banner CSV" },
  { id: "webp-konverter", icon: "compress", label: "WebP Konverter" },
];

const visibleItems = items.filter((item) => item.enabled !== false);

function selectItem(id: string) {
  router.push({ name: id });
}
</script>
