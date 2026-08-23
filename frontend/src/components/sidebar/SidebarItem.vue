<template>
  <button
    ref="buttonEl"
    v-bind="$attrs"
    @click="$emit('select')"
    @mouseenter="showTooltip"
    @mouseleave="hideTooltip"
    @focus="showTooltip"
    @blur="hideTooltip"
    :aria-label="label"
    :class="[
      'flex w-full items-center gap-3 overflow-hidden rounded-md px-2 py-1 text-left transition sidebar-item',
      isActive && 'sidebar-item--active',
    ]"
  >
    <!-- Feste Iconbreite und konstantes Padding: dadurch liegt das Icon
         eingeklappt genau dort, wo es ausgeklappt liegt, und wandert
         waehrend der Animation nicht. -->
    <span class="material-symbols-outlined nav-icon--active w-5 shrink-0 text-center">
      {{ icon }}
    </span>

    <!-- Bleibt im DOM und wird nur ausgeblendet: die schmaler werdende
         Sidebar schneidet den Text ab, das Ausblenden macht den Uebergang
         weich. Ein v-if wuerde die Beschriftung abrupt verschwinden lassen. -->
    <span
      class="white-text whitespace-nowrap transition-opacity duration-150"
      :class="collapsed ? 'opacity-0' : 'opacity-100'"
    >
      {{ label }}
    </span>
  </button>

  <!-- Eingeklappt fehlt die Beschriftung, also zeigt ein Tooltip sie beim
       Hovern. `position: fixed` per Teleport, weil die Sidebar scrollt
       (`overflow-y-auto`) und ein absolut positionierter Tooltip dort
       abgeschnitten wuerde. -->
  <Teleport to="body">
    <span v-if="tooltip" class="sidebar-tooltip" :style="tooltip" role="tooltip">
      {{ label }}
    </span>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";

// Zwei Wurzelknoten (Button + Teleport) erben Attribute nicht automatisch,
// darum landen `class` & Co. explizit auf dem Button.
defineOptions({ inheritAttrs: false });

const props = defineProps<{
  icon: string;
  label: string;
  isActive?: boolean;
  collapsed?: boolean;
}>();

defineEmits<{
  (e: "select"): void;
}>();

const buttonEl = ref<HTMLButtonElement | null>(null);
const tooltip = ref<{ top: string; left: string } | null>(null);

function showTooltip() {
  if (!props.collapsed || !buttonEl.value) return;

  const rect = buttonEl.value.getBoundingClientRect();
  tooltip.value = {
    top: `${rect.top + rect.height / 2}px`,
    left: `${rect.right + 8}px`,
  };
}

function hideTooltip() {
  tooltip.value = null;
}

// Ausklappen waehrend der Maus auf dem Item steht wuerde den Tooltip sonst
// neben der jetzt sichtbaren Beschriftung stehen lassen.
watch(() => props.collapsed, hideTooltip);
</script>
