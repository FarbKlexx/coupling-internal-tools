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
    <nav class="flex flex-col gap-3">
      <div v-for="(group, index) in sections.groups" :key="group.id" class="flex flex-col gap-1">
        <button
          v-if="group.label && !collapsed"
          class="sidebar-group flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left"
          :aria-expanded="isGroupOpen(group.id)"
          :aria-controls="`nav-group-${group.id}`"
          @click="toggleGroup(group.id)"
        >
          <span
            class="eyebrow overflow-hidden whitespace-nowrap"
            :class="hasActive(group) ? 'white-text' : 'grey-text'"
          >
            {{ group.label }}
          </span>
          <span
            class="material-symbols-outlined nav-icon shrink-0 transition-transform duration-150"
            :class="isGroupOpen(group.id) ? '' : '-rotate-90'"
          >
            expand_more
          </span>
        </button>

        <!-- Eingeklappt ist kein Platz fuer die Ueberschrift – und eine dort
             zugeklappte Gruppe waere in dieser Breite auch nicht wieder
             aufzuklappen. Statt ihrer traegt ein Strich die Gliederung: er
             steht genau dort, wo ausgeklappt die Ueberschrift steht, also
             ueber der Gruppe und nicht vor der ersten. -->
        <div v-else-if="collapsed && index > 0" class="sidebar-rule mx-2" />

        <div
          v-if="collapsed || isGroupOpen(group.id)"
          :id="`nav-group-${group.id}`"
          class="flex flex-col gap-1"
        >
          <SidebarItem
            v-for="item in group.items"
            :key="item.id"
            :icon="item.icon"
            :label="item.label"
            :isActive="route.name === item.id"
            :collapsed="collapsed"
            @select="selectItem(item.id)"
            data-nav-item
            class="cursor-pointer"
          />
        </div>
      </div>
    </nav>

    <!-- Die Verwaltung sitzt unten und ist abgesetzt: erreichbar, aber nicht
         zwischen den Werkzeugen des Tagesgeschaefts. `mt-auto` schiebt sie an
         den unteren Rand, solange die Navigation kuerzer ist als die Spalte. -->
    <div v-if="sections.footer.length" class="sidebar-rule mt-auto flex flex-col gap-1 pt-3">
      <SidebarItem
        v-for="item in sections.footer"
        :key="item.id"
        :icon="item.icon"
        :label="item.label"
        :isActive="route.name === item.id"
        :collapsed="collapsed"
        @select="selectItem(item.id)"
        data-nav-item
        class="cursor-pointer"
      />
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from "vue";
import SidebarItem from "./SidebarItem.vue";
import { useRoute, useRouter } from "vue-router";
import { routes } from "@/router";
import { buildNavSections, type NavGroup } from "@/navigation/buildNavItems";
import { useAuth } from "@/composables/useAuth";
import { useSidebar } from "@/composables/useSidebar";

const route = useRoute();
const router = useRouter();
const { collapsed, isGroupOpen, toggleGroup } = useSidebar();
const auth = useAuth();

// Abgeleitet, nicht deklariert: Label, Icon, Gruppe und Reihenfolge stehen in
// der Route-Meta (`meta.sidebar`, `meta.navGroup`), damit es nicht zwei Listen
// gibt, die auseinanderlaufen koennen. Einen Eintrag ausblenden heisst dort
// `sidebar: false` – so wie beim Dashboard-Stub.
//
// Zusaetzlich gefiltert nach dem, was dieser Benutzer oeffnen darf. Das ist
// Anzeige, keine Absicherung: die sitzt im Backend. Es verhindert nur, dass
// jemand auf einen Menuepunkt klickt, der ihm ohnehin 403 liefert.
const sections = computed(() =>
  buildNavSections(routes, {
    mayOpen: auth.mayOpen,
    isAdmin: auth.isAdmin.value,
  }),
);

// Eine zugeklappte Gruppe verdeckt sonst, wo man gerade ist: die Ueberschrift
// uebernimmt dann die Markierung, die sonst der Eintrag traegt.
function hasActive(group: NavGroup): boolean {
  return group.items.some((item) => item.id === route.name);
}

function selectItem(id: string) {
  router.push({ name: id });
}
</script>
