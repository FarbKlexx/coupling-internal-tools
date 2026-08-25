<template>
  <aside
    :class="[
      'shrink-0 overflow-y-auto overflow-x-hidden light-grey-background grey-stroke gap-3 flex flex-col',
      // Padding bleibt konstant - sonst springt der Inhalt beim Umschalten,
      // waehrend die Breite noch animiert.
      'p-3 transition-[width] duration-200 ease-out',
      collapsed ? 'w-16' : 'w-52',
    ]"
  >
    <!-- Wird ausgeblendet statt entfernt: der Platz bleibt reserviert, sonst
         springen die Icons beim Einklappen nach oben. `overflow-hidden`, weil
         der Text breiter ist als die eingeklappte Sidebar. -->
    <span
      class="grey-text eyebrow overflow-hidden whitespace-nowrap px-2 transition-opacity duration-150"
      :class="collapsed ? 'opacity-0' : 'opacity-100'"
    >
      Hauptkategorie
    </span>
    <nav class="flex flex-col gap-1">
      <SidebarItem
        v-for="item in visibleItems"
        :key="item.id"
        :icon="item.icon"
        :label="item.label"
        :isActive="route.name === item.id"
        :collapsed="collapsed"
        @select="selectItem(item.id)"
        data-nav-item
        class="cursor-pointer"
      />
    </nav>
  </aside>
</template>

<script setup lang="ts">
import SidebarItem from "./SidebarItem.vue";
import { useRoute, useRouter } from "vue-router";
import { useSidebar } from "@/composables/useSidebar";

const route = useRoute();
const router = useRouter();
const { collapsed } = useSidebar();

// `enabled: false` blendet einen Eintrag aus, ohne ihn zu entfernen.
const items = [
  { id: "dashboard", icon: "home", label: "Dashboard", enabled: false },
  { id: "abgleiche", icon: "table", label: "AWIN Abgleiche" },
  { id: "awin-banner", icon: "image", label: "AWIN Banner CSV" },
  { id: "webp-konverter", icon: "compress", label: "WebP Konverter" },
  { id: "qr-code", icon: "qr_code_2", label: "QR-Code Generator" },
  { id: "pdf-schutz", icon: "lock", label: "PDF Passwortschutz" },
  { id: "namensschilder", icon: "badge", label: "Namensschilder" },
  { id: "kanban", icon: "view_kanban", label: "Kanban Board" },
];

const visibleItems = items.filter((item) => item.enabled !== false);

function selectItem(id: string) {
  router.push({ name: id });
}
</script>
