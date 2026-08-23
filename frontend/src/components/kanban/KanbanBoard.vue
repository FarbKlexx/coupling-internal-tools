<template>
  <!-- min-w-0: ohne das setzt die Mindestbreite der fünf Spalten die Breite
       von <main> und schiebt Sidebar und Kopfzeile aus dem Bild. -->
  <div class="flex h-full min-w-0 flex-col gap-4">
    <div class="space-y-1">
      <h2 class="text-lg font-semibold">Kanban Board</h2>
      <p class="text-xs text-zinc-500">
        Gemeinsames Board – Änderungen sind für alle sichtbar und werden alle 10 Sekunden
        aktualisiert.
      </p>
    </div>

    <BoardFilter
      :labels="labels"
      :selected="activeLabelIds"
      @update:selected="activeLabelIds = $event"
      @manage="openManager"
    />

    <div
      v-if="errorMessage && !dialogOpen && !managerOpen"
      class="flex items-start justify-between gap-3 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200"
    >
      <span>{{ errorMessage }}</span>
      <button type="button" class="shrink-0" @click="errorMessage = null">
        <span class="material-symbols-outlined" style="font-size: 16px">close</span>
      </button>
    </div>

    <p v-if="isLoading && !board" class="light-grey-text">Board wird geladen …</p>

    <div v-else class="flex min-w-0 flex-1 gap-3 overflow-x-auto pb-2">
      <KanbanColumn
        v-for="column in columns"
        :key="column.id"
        v-model="lists[column.id]"
        :column="column"
        :drag-disabled="isFiltered"
        :column-labels="columnLabels"
        :is-busy="isSaving"
        @add="startCreate"
        @open="startEdit"
        @advance="advanceCard"
        @drag-start="isDragging = true"
        @drag-end="onDragEnd"
      />
    </div>

    <CardDialog
      v-if="dialogOpen"
      :card="editingCard"
      :columns="board?.columns ?? []"
      :labels="labels"
      :default-column-id="dialogColumnId"
      :just-created-label-id="justCreatedLabelId"
      :is-busy="isSaving"
      :error-message="errorMessage"
      @submit="saveCard"
      @delete="deleteCard"
      @create-label="createLabelFromDialog"
      @close="closeDialog"
    />

    <LabelManager
      v-if="managerOpen"
      :labels="managedLabels"
      :usage="labelUsage"
      :is-busy="isSaving"
      :error-message="errorMessage"
      @create="addLabel($event)"
      @update="editLabel"
      @delete="removeLabel($event, true)"
      @close="managerOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import BoardFilter from "./BoardFilter.vue";
import CardDialog from "./CardDialog.vue";
import KanbanColumn from "./KanbanColumn.vue";
import LabelManager from "./LabelManager.vue";
import { useKanbanBoard } from "@/composables/useKanbanBoard";
import {
  fetchLabels,
  type KanbanCard,
  type KanbanColumnId,
  type KanbanLabel,
} from "@/api/kanban.api";

const {
  board,
  columns,
  labels,
  isLoading,
  isSaving,
  isDragging,
  errorMessage,
  activeLabelIds,
  isFiltered,
  load,
  startPolling,
  addCard,
  editCard,
  relocateCard,
  assignLabels,
  removeCard,
  addLabel,
  editLabel,
  removeLabel,
} = useKanbanBoard();

/**
 * Beschreibbare Kopie der Spaltenlisten.
 *
 * sortablejs verschiebt die Einträge im gebundenen Array selbst, ein
 * `computed` wäre dafür nicht schreibbar. Nach jeder Serverantwort ersetzt
 * `syncLists` die Listen durch den Stand aus der Datenbank – während eines
 * Drags nicht, sonst reißt es das DOM auseinander.
 */
const lists = ref<Record<KanbanColumnId, KanbanCard[]>>({} as Record<KanbanColumnId, KanbanCard[]>);

function syncLists() {
  const next = {} as Record<KanbanColumnId, KanbanCard[]>;
  // Die Schlüssel kommen aus der Antwort, nicht aus einer Liste im Frontend –
  // eine sechste Spalte wäre damit eine reine Backend-Änderung.
  for (const column of columns.value) next[column.id] = [...column.cards];
  lists.value = next;
}

watch(
  columns,
  () => {
    if (!isDragging.value) syncLists();
  },
  { immediate: true },
);

const dialogOpen = ref(false);
const editingCard = ref<KanbanCard | null>(null);
const dialogColumnId = ref<KanbanColumnId>("ideen");
const justCreatedLabelId = ref<string | null>(null);

const managerOpen = ref(false);
const managedLabels = ref<KanbanLabel[]>([]);

/**
 * Slug -> Beschriftung, aus der Board-Antwort. Die Karten benennen damit das
 * Ziel ihres Weiter-Buttons, ohne die Labels im Frontend zu doppeln.
 */
const columnLabels = computed(() => {
  const map: Partial<Record<KanbanColumnId, string>> = {};
  for (const column of columns.value) map[column.id] = column.label;
  return map;
});

/** Wie viele Karten je Label – das Board liegt komplett im Speicher. */
const labelUsage = computed(() => {
  const counts: Record<string, number> = {};
  for (const column of board.value?.columns ?? []) {
    for (const card of column.cards) {
      for (const label of card.labels) counts[label.id] = (counts[label.id] ?? 0) + 1;
    }
  }
  return counts;
});

function startCreate(columnId: KanbanColumnId) {
  errorMessage.value = null;
  editingCard.value = null;
  dialogColumnId.value = columnId;
  justCreatedLabelId.value = null;
  dialogOpen.value = true;
}

function startEdit(card: KanbanCard) {
  errorMessage.value = null;
  editingCard.value = card;
  dialogColumnId.value = card.column_id;
  justCreatedLabelId.value = null;
  dialogOpen.value = true;
}

function closeDialog() {
  dialogOpen.value = false;
  editingCard.value = null;
  justCreatedLabelId.value = null;
}

function sameLabels(before: string[], after: string[]): boolean {
  return before.length === after.length && before.every((id) => after.includes(id));
}

async function saveCard(payload: {
  title: string;
  description: string;
  columnId: KanbanColumnId;
  labelIds: string[];
}) {
  const card = editingCard.value;

  if (!card) {
    const created = await addCard({
      title: payload.title,
      description: payload.description,
      column_id: payload.columnId,
      label_ids: payload.labelIds,
    });
    if (created) closeDialog();
    return;
  }

  // Getrennte Endpunkte, also nur schicken, was sich wirklich geändert hat.
  let ok = true;

  if (payload.title !== card.title || payload.description !== card.description) {
    ok = await editCard(card.id, {
      title: payload.title,
      description: payload.description,
    });
  }

  const before = card.labels.map((label) => label.id);
  if (ok && !sameLabels(before, payload.labelIds)) {
    ok = await assignLabels(card.id, payload.labelIds);
  }

  if (ok && payload.columnId !== card.column_id) {
    // Über den Dialog verschoben heißt: oben in der Zielspalte.
    ok = await relocateCard(card.id, payload.columnId, 0);
  }

  if (ok) closeDialog();
}

/**
 * Ein Klick auf den Weiter-Button. Die Karte landet oben in der Zielspalte –
 * genauso, wie ein Wechsel über die Spaltenauswahl im Dialog es tut.
 */
async function advanceCard(payload: { card: KanbanCard; to: KanbanColumnId }) {
  await relocateCard(payload.card.id, payload.to, 0);
}

async function deleteCard(cardId: string) {
  if (await removeCard(cardId)) closeDialog();
}

async function createLabelFromDialog(name: string) {
  if (!(await addLabel(name))) return;

  // Der Dialog kennt die neue ID nicht – hier aus dem aktualisierten Board
  // heraussuchen, damit der Kunde sofort ausgewählt ist. Das Backend
  // normalisiert Leerraum, also genauso vergleichen.
  const wanted = name.trim().split(/\s+/).join(" ").toLowerCase();
  justCreatedLabelId.value =
    labels.value.find((label) => label.name.toLowerCase() === wanted)?.id ?? null;
}

async function refreshManagedLabels() {
  try {
    // Der Manager ist die einzige Stelle, die auch archivierte Kunden zeigt –
    // im Board selbst kommen die nicht mit.
    managedLabels.value = await fetchLabels(true);
  } catch (e) {
    console.error(e);
    errorMessage.value = "Die Kundenliste konnte nicht geladen werden.";
  }
}

async function openManager() {
  errorMessage.value = null;
  managerOpen.value = true;
  await refreshManagedLabels();
}

watch(
  () => board.value?.revision,
  () => {
    if (managerOpen.value) void refreshManagedLabels();
  },
);

async function onDragEnd(event: {
  from: HTMLElement;
  to: HTMLElement;
  oldIndex?: number;
  newIndex?: number;
  item: HTMLElement;
}) {
  isDragging.value = false;

  const columnId = event.to.dataset.columnId as KanbanColumnId | undefined;
  const cardId = event.item.dataset.cardId;
  const position = event.newIndex;

  if (!columnId || !cardId || position === undefined) {
    // Ohne die Zielangaben lässt sich nichts speichern – den Serverstand
    // wiederherstellen, damit die Anzeige nicht lügt.
    syncLists();
    return;
  }

  // Innerhalb derselben Spalte auf denselben Platz: nichts zu tun.
  if (event.from === event.to && event.oldIndex === position) return;

  await relocateCard(cardId, columnId, position);
}

onMounted(async () => {
  await load();
  startPolling();
});
</script>
