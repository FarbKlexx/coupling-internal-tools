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

    <!-- Abkürzung in die nächste Spalte. `@click.stop`, weil ein Klick auf die
         Karte sonst zusätzlich den Dialog öffnet; die Klasse `card-action`
         steht außerdem im `filter` von sortablejs, damit der Button keinen
         Drag startet. -->
    <div v-if="transitions.length" class="flex flex-wrap gap-1">
      <button
        v-for="step in transitions"
        :key="step.to"
        type="button"
        class="card-action flex items-center gap-1 rounded px-1.5 py-0.5"
        style="font-size: 11px"
        :title="`Nach ${step.label} verschieben`"
        :disabled="isBusy"
        @click.stop="emit('advance', { card, to: step.to })"
      >
        <span class="material-symbols-outlined" style="font-size: 13px">{{ step.icon }}</span>
        {{ step.label }}
      </button>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from "vue";
import LabelChip from "./LabelChip.vue";
import { transitionsFor } from "./cardTransitions";
import type { KanbanCard, KanbanColumnId } from "@/api/kanban.api";

const props = withDefaults(
  defineProps<{
    card: KanbanCard;
    /**
     * Spaltenbeschriftungen aus der Board-Antwort – der Button nennt sein Ziel
     * beim Namen, ohne dass das Frontend die Labels doppelt pflegt. Fehlt ein
     * Eintrag, steht der Slug da.
     */
    columnLabels?: Partial<Record<KanbanColumnId, string>>;
    /** Während eines laufenden Schreibvorgangs gesperrt. */
    isBusy?: boolean;
  }>(),
  { columnLabels: () => ({}), isBusy: false },
);

const emit = defineEmits<{
  (e: "open", card: KanbanCard): void;
  (e: "advance", payload: { card: KanbanCard; to: KanbanColumnId }): void;
}>();

const transitions = computed(() =>
  transitionsFor(props.card.column_id).map((step) => ({
    ...step,
    label: props.columnLabels[step.to] ?? step.to,
  })),
);
</script>
