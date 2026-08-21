<template>
  <article
    :data-card-id="card.id"
    class="kanban-card cursor-pointer rounded-lg p-3 space-y-2 transition-colors"
    @click="emit('open', card)"
  >
    <div v-if="card.labels.length" class="flex flex-wrap gap-1">
      <LabelChip v-for="label in card.labels" :key="label.id" :label="label" />
    </div>

    <p class="white-text leading-snug">{{ card.title }}</p>

    <div class="flex items-center gap-3 grey-text" style="font-size: 11px">
      <span v-if="card.description" class="flex items-center gap-1">
        <span class="material-symbols-outlined" style="font-size: 13px">notes</span>
        Notiz
      </span>
      <span v-if="card.created_by">{{ card.created_by }}</span>
    </div>
  </article>
</template>

<script setup lang="ts">
import LabelChip from "./LabelChip.vue";
import type { KanbanCard } from "@/api/kanban.api";

defineProps<{
  card: KanbanCard;
}>();

const emit = defineEmits<{
  (e: "open", card: KanbanCard): void;
}>();
</script>
