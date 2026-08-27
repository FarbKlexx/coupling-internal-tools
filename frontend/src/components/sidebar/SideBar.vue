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
        v-for="item in items"
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
import { computed } from "vue";
import SidebarItem from "./SidebarItem.vue";
import { useRoute, useRouter } from "vue-router";
import { routes } from "@/router";
import { buildNavItems } from "@/navigation/buildNavItems";
import { useAuth } from "@/composables/useAuth";
import { useSidebar } from "@/composables/useSidebar";

const route = useRoute();
const router = useRouter();
const { collapsed } = useSidebar();
const auth = useAuth();

// Abgeleitet, nicht deklariert: Label, Icon und Reihenfolge stehen in der
// Route-Meta (`meta.sidebar`), damit es nicht zwei Listen gibt, die
// auseinanderlaufen koennen. Einen Eintrag ausblenden heisst dort
// `sidebar: false` – so wie beim Dashboard-Stub.
//
// Zusaetzlich gefiltert nach dem, was dieser Benutzer oeffnen darf. Das ist
// Anzeige, keine Absicherung: die sitzt im Backend. Es verhindert nur, dass
// jemand auf einen Menuepunkt klickt, der ihm ohnehin 403 liefert.
const items = computed(() =>
  buildNavItems(routes, {
    mayOpen: auth.mayOpen,
    isAdmin: auth.isAdmin.value,
  }),
);

function selectItem(id: string) {
  router.push({ name: id });
}
</script>
