<template>
  <!-- Die Spalten teilen sich die Breite (bei fünf Spalten passen sie damit
       ins Fenster) und scrollen erst, wenn min-w-56 nicht mehr hineingeht. -->
  <section class="kanban-column flex min-w-56 flex-1 flex-col rounded-xl">
    <header class="flex items-center justify-between gap-2 px-3 py-2.5">
      <div class="flex items-center gap-2">
        <span class="white-text font-medium">{{ column.label }}</span>
        <span class="grey-text" style="font-size: 12px">{{ cards.length }}</span>
      </div>
      <button
        type="button"
        class="grey-text hover:text-white"
        title="Karte hinzufügen"
        @click="emit('add', column.id)"
      >
        <span class="material-symbols-outlined" style="font-size: 18px">add</span>
      </button>
    </header>

    <p v-if="!cards.length" class="px-3 pb-2 text-xs text-zinc-600">Keine Karten</p>

    <VueDraggable
      v-model="cards"
      :data-column-id="column.id"
      group="kanban"
      :animation="150"
      :disabled="dragDisabled"
      filter=".card-action"
      :prevent-on-filter="false"
      ghost-class="kanban-ghost"
      drag-class="kanban-drag"
      class="flex min-h-24 flex-1 flex-col gap-2 px-2 pb-3"
      @start="emit('dragStart')"
      @end="emit('dragEnd', $event)"
    >
      <KanbanCard
        v-for="card in cards"
        :key="card.id"
        :card="card"
        :column-labels="columnLabels"
        :is-busy="isBusy"
        @open="emit('open', $event)"
        @advance="emit('advance', $event)"
      />
    </VueDraggable>
  </section>
</template>

<script setup lang="ts">
import { VueDraggable } from "vue-draggable-plus";
import KanbanCard from "./KanbanCard.vue";
import type { KanbanCard as KanbanCardType, KanbanColumnView } from "@/api/kanban.api";
import type { KanbanColumnId } from "@/api/kanban.api";

/**
 * `cards` ist ein eigenes, beschreibbares Array – sortablejs verschiebt die
 * Einträge selbst, ein `computed` aus dem Board wäre nicht schreibbar. Das
 * Board hält die Liste synchron und ersetzt sie nach jeder Antwort des
 * Servers.
 */
const cards = defineModel<KanbanCardType[]>({ required: true });

defineProps<{
  column: KanbanColumnView;
  /** Bei aktivem Filter gesperrt: die Indizes wären dann nicht die echten. */
  dragDisabled?: boolean;
  /** Nur durchgereicht: die Karten beschriften damit ihre Zielspalte. */
  columnLabels?: Partial<Record<KanbanColumnId, string>>;
  isBusy?: boolean;
}>();

const emit = defineEmits<{
  (e: "add", columnId: KanbanColumnId): void;
  (e: "open", card: KanbanCardType): void;
  (e: "advance", payload: { card: KanbanCardType; to: KanbanColumnId }): void;
  (e: "dragStart"): void;
  (
    e: "dragEnd",
    event: {
      from: HTMLElement;
      to: HTMLElement;
      oldIndex?: number;
      newIndex?: number;
      item: HTMLElement;
    },
  ): void;
}>();
</script>
