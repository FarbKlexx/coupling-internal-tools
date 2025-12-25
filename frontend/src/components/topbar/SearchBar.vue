<script setup lang="ts">
import { ref, computed } from "vue";
import { useRouter } from "vue-router";
import { searchRoutes } from "@/search/useRouteSearch";
import type { FuseResult } from "fuse.js";
import type { RouteSearchItem } from "@/search/buildRouteSearchIndex";

const router = useRouter();

const query = ref<string>("");
const isOpen = ref<boolean>(false);

const results = computed<FuseResult<RouteSearchItem>[]>(() => {
  if (!query.value.trim()) return [];
  return searchRoutes(query.value);
});

function selectResult(item: RouteSearchItem) {
  query.value = "";
  isOpen.value = false;
  router.push(item.path);
}
</script>


<template>
  <div class="relative w-sm mx-auto">
    <div
      class="flex items-center gap-3 rounded-xl border light-grey-stroke light-grey-background px-2 py-2"
    >
      <span class="material-symbols-outlined nav-icon">
        search
      </span>

      <input
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
      v-if="isOpen && results.length"
      class="absolute z-50 mt-2 w-full rounded-xl border light-grey-stroke light-grey-background overflow-hidden"
    >
      <button
        v-for="result in results"
        :key="result.item.id"
        type="button"
        class="flex w-full items-center gap-3 px-4 py-2 text-left hover:bg-zinc-800/40"
        @mousedown.prevent="selectResult(result.item)"
      >
        <!-- optional: Icon aus route.meta.icon -->
        <span
          v-if="result.item.icon"
          class="material-symbols-outlined nav-icon"
        >
          {{ result.item.icon }}
        </span>

        <div class="min-w-0">
          <div class="truncate text-sm font-medium grey-text">
            {{ result.item.label }}
          </div>
          <div class="truncate text-xs opacity-60 grey-text">
            {{ result.item.path }}
          </div>
        </div>
      </button>
    </div>
  </div>
</template>

<style scoped>

</style>