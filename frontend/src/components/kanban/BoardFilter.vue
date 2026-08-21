<template>
  <div class="flex flex-wrap items-center gap-2">
    <span class="grey-text eyebrow" style="font-size: 11px">Kunde</span>

    <button
      v-for="label in labels"
      :key="label.id"
      type="button"
      :class="['label-chip', `label-${label.color}`, !selected.includes(label.id) && 'opacity-40']"
      @click="toggle(label.id)"
    >
      {{ label.name }}
    </button>

    <span v-if="!labels.length" class="text-xs text-zinc-500">Noch kein Kunde angelegt.</span>

    <button
      v-if="selected.length"
      type="button"
      class="grey-text hover:text-white"
      style="font-size: 12px"
      @click="emit('update:selected', [])"
    >
      Filter aufheben
    </button>

    <div class="ml-auto flex items-center gap-2">
      <!-- Der Filter verschiebt die sichtbaren Indizes, deshalb ist Ziehen
           währenddessen gesperrt. -->
      <span v-if="selected.length" class="text-xs text-amber-400/80">
        Ziehen ist bei aktivem Filter gesperrt
      </span>
      <button
        type="button"
        class="flex items-center gap-1 rounded-md light-grey-stroke px-3 py-1.5 text-sm"
        @click="emit('manage')"
      >
        <span class="material-symbols-outlined" style="font-size: 16px">sell</span>
        Kunden verwalten
      </button>
      <a
        :href="exportUrl"
        class="flex items-center gap-1 rounded-md light-grey-stroke px-3 py-1.5 text-sm"
        title="Board als JSON sichern"
      >
        <span class="material-symbols-outlined" style="font-size: 16px">download</span>
        Export
      </a>
    </div>
  </div>
</template>

<script setup lang="ts">
import { boardExportUrl, type KanbanLabel } from "@/api/kanban.api";

const props = defineProps<{
  labels: KanbanLabel[];
  selected: string[];
}>();

const emit = defineEmits<{
  (e: "update:selected", value: string[]): void;
  (e: "manage"): void;
}>();

const exportUrl = boardExportUrl();

function toggle(labelId: string) {
  const next = props.selected.includes(labelId)
    ? props.selected.filter((id) => id !== labelId)
    : [...props.selected, labelId];

  emit("update:selected", next);
}
</script>
