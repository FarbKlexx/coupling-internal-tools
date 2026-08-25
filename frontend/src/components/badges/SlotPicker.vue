<script setup lang="ts">
import { computed } from "vue";
import type { BadgeSheetFormat } from "@/api/name_badge.api";

/**
 * Klickbares Kartenraster: welche Karte des Bogens zuerst bedruckt wird.
 *
 * Das Raster ist ein maßstäbliches Abbild des Bogens – Seitenverhältnis,
 * Ränder und Kartengröße kommen aus der Backend-Geometrie und sind hier
 * nirgends fest verdrahtet. Ein Bogenformat mit anderem Raster zeichnet sich
 * ohne Änderung an dieser Komponente.
 */
const props = defineProps<{
  format: BadgeSheetFormat;
  modelValue: number;
}>();

const emit = defineEmits<{
  "update:modelValue": [slot: number];
}>();

const slots = computed(() =>
  Array.from({ length: props.format.slots_per_sheet }, (_, index) => index + 1),
);

/** Prozentangaben, damit das Raster mit dem Container skaliert. */
const percent = (value: number, total: number) => `${(value / total) * 100}%`;

const gridStyle = computed(() => {
  const format = props.format;
  const width = format.columns * format.card_width_mm + (format.columns - 1) * format.gap_x_mm;
  const height = format.rows * format.card_height_mm + (format.rows - 1) * format.gap_y_mm;

  return {
    left: percent(format.margin_left_mm, format.sheet_width_mm),
    top: percent(format.margin_top_mm, format.sheet_height_mm),
    width: percent(width, format.sheet_width_mm),
    height: percent(height, format.sheet_height_mm),
    gridTemplateColumns: `repeat(${format.columns}, 1fr)`,
    gridTemplateRows: `repeat(${format.rows}, 1fr)`,
    columnGap: percent(format.gap_x_mm, format.sheet_width_mm),
    rowGap: percent(format.gap_y_mm, format.sheet_height_mm),
  };
});

const sheetStyle = computed(() => ({
  aspectRatio: `${props.format.sheet_width_mm} / ${props.format.sheet_height_mm}`,
}));
</script>

<template>
  <div class="flex flex-col gap-2">
    <div
      class="relative w-full max-w-[15rem] rounded-md grey-background light-grey-stroke"
      :style="sheetStyle"
    >
      <div class="absolute grid" :style="gridStyle">
        <button
          v-for="slot in slots"
          :key="slot"
          type="button"
          data-slot
          :aria-pressed="slot === modelValue"
          :aria-label="`Ab Karte ${slot} drucken`"
          :title="`Ab Karte ${slot} drucken`"
          :class="[
            'flex items-center justify-center rounded-[2px] border text-[10px] transition-colors',
            slot === modelValue
              ? 'border-blue-500 bg-blue-600 text-white'
              : slot < modelValue
                ? 'border-zinc-700 bg-zinc-800/60 text-zinc-600'
                : 'border-zinc-700 light-grey-background text-zinc-400 hover:border-blue-500',
          ]"
          @click="emit('update:modelValue', slot)"
        >
          {{ slot }}
        </button>
      </div>
    </div>
    <p class="text-xs text-zinc-500">
      Ab Karte {{ modelValue }}
      <span v-if="modelValue > 1">
        · die {{ modelValue - 1 }} Karten davor bleiben auf dem ersten Bogen frei
      </span>
    </p>
  </div>
</template>
