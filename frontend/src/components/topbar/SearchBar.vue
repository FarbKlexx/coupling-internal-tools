<script setup lang="ts">
import { ref, computed, nextTick } from "vue";
import { useRouter } from "vue-router";
import { allRoutes, searchRoutes } from "@/search/useRouteSearch";
import type { RouteSearchItem } from "@/search/buildRouteSearchIndex";

const emit = defineEmits<{
  (e: "close"): void;
}>();

const router = useRouter();

const inputRef = ref<HTMLInputElement | null>(null);

const query = ref<string>("");
const isOpen = ref<boolean>(false);

function focus() {
  nextTick(() => {
    inputRef.value?.focus();
    isOpen.value = true;
  });
}

/**
 * Ohne Suchbegriff steht hier alles, was man oeffnen darf — in der
 * Reihenfolge der Routen, nicht nach Treffergenauigkeit, denn ohne Begriff
 * gibt es keine. Erst ein eingetippter Begriff laesst Fuse sortieren.
 *
 * `FuseResult` wird gleich hier ausgepackt, damit die Vorlage nur eine Form
 * kennt und nicht zwei.
 */
const results = computed<RouteSearchItem[]>(() => {
  const term = query.value.trim();

  if (!term) return allRoutes();

  return searchRoutes(term).map((treffer) => treffer.item);
});

function selectResult(item: RouteSearchItem) {
  query.value = "";
  isOpen.value = false;
  emit("close");
  router.push(item.path);
}

defineExpose({ focus });
</script>

<template>
  <div class="w-2xl">
    <div class="search-field flex items-center gap-3 px-2 py-2">
      <span class="material-symbols-outlined nav-icon"> search </span>

      <input
        ref="inputRef"
        v-model="query"
        type="text"
        placeholder="Type to search"
        class="w-full bg-transparent grey-text focus:outline-none"
        @focus="isOpen = true"
        @blur="isOpen = false"
        autocomplete="off"
      />
    </div>

    <!-- Ergebnisse -->
    <div
      v-if="isOpen && results.length > 0"
      class="absolute z-50 mt-2 max-h-[60vh] w-full overflow-y-auto rounded-xl border light-grey-stroke light-grey-background"
    >
      <button
        v-for="result in results"
        :key="result.id"
        type="button"
        class="search-result flex w-full items-center gap-3 px-4 py-2 text-left"
        @mousedown.prevent="selectResult(result)"
      >
        <!-- optional: Icon aus route.meta.icon -->
        <span v-if="result.icon" class="material-symbols-outlined nav-icon">
          {{ result.icon }}
        </span>

        <div class="min-w-0">
          <div class="truncate text-sm font-medium grey-text">
            {{ result.label }}
          </div>
          <div class="truncate text-xs opacity-60 grey-text">
            {{ result.path }}
          </div>
        </div>
      </button>
    </div>
  </div>
</template>

<style scoped></style>
