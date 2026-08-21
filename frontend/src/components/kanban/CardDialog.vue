<template>
  <v-overlay
    :model-value="true"
    class="flex items-center justify-center"
    scrim="#000000"
    opacity="0.6"
    @click:outside="emit('close')"
    @keydown.esc="emit('close')"
  >
    <div
      class="w-[32rem] max-w-[90vw] rounded-xl border light-grey-background light-grey-stroke p-6 space-y-4"
    >
      <div class="flex items-start justify-between gap-4">
        <h2 class="text-lg font-semibold">
          {{ card ? "Karte bearbeiten" : "Neue Karte" }}
        </h2>
        <button type="button" class="grey-text" @click="emit('close')">
          <span class="material-symbols-outlined">close</span>
        </button>
      </div>

      <p
        v-if="errorMessage"
        class="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200"
      >
        {{ errorMessage }}
      </p>

      <div class="flex flex-col gap-2">
        <label class="text-sm font-medium">Titel</label>
        <input
          ref="titleInput"
          v-model="title"
          type="text"
          :maxlength="MAX_TITLE"
          class="rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500"
          @keydown.enter.prevent="submit"
        />
      </div>

      <div class="flex flex-col gap-2">
        <label class="text-sm font-medium">Notiz</label>
        <textarea
          v-model="description"
          rows="4"
          :maxlength="MAX_DESCRIPTION"
          class="rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 resize-y"
        />
      </div>

      <!-- Auch der Weg ohne Maus: die Spalte hier zu wechseln ersetzt das
           Ziehen und funktioniert per Tastatur. -->
      <div class="flex flex-col gap-2">
        <label class="text-sm font-medium">Spalte</label>
        <select
          v-model="columnId"
          class="rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500"
        >
          <option v-for="column in columns" :key="column.id" :value="column.id">
            {{ column.label }}
          </option>
        </select>
      </div>

      <LabelPicker
        :labels="labels"
        :selected="labelIds"
        :is-busy="isBusy"
        @update:selected="labelIds = $event"
        @create="emit('createLabel', $event)"
      />

      <p v-if="card" class="text-xs text-zinc-500">
        Angelegt von {{ card.created_by || "unbekannt" }} am {{ formatDate(card.created_at) }} ·
        zuletzt geändert {{ formatDate(card.updated_at) }}
      </p>

      <div class="flex items-center justify-between gap-3 pt-1">
        <button
          v-if="card"
          type="button"
          class="rounded-md px-3 py-2 text-sm text-red-400 hover:bg-red-500/10"
          @click="emit('delete', card.id)"
        >
          Löschen
        </button>
        <span v-else></span>

        <div class="flex gap-2">
          <button
            type="button"
            class="rounded-md light-grey-stroke px-4 py-2 text-sm"
            @click="emit('close')"
          >
            Abbrechen
          </button>
          <button
            type="button"
            class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-40"
            :disabled="!title.trim() || isBusy"
            @click="submit"
          >
            {{ card ? "Speichern" : "Anlegen" }}
          </button>
        </div>
      </div>
    </div>
  </v-overlay>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";
import LabelPicker from "./LabelPicker.vue";
import type { KanbanCard, KanbanColumnId, KanbanColumnView, KanbanLabel } from "@/api/kanban.api";

/** Gespiegelt aus backend/app/schemas/kanban.py. */
const MAX_TITLE = 200;
const MAX_DESCRIPTION = 5000;

const props = defineProps<{
  /** `null` = neue Karte. */
  card: KanbanCard | null;
  columns: KanbanColumnView[];
  labels: KanbanLabel[];
  /** Vorbelegte Spalte beim Anlegen. */
  defaultColumnId: KanbanColumnId;
  /**
   * Zuletzt im Picker angelegter Kunde.
   *
   * Der Dialog kennt die neue ID nicht selbst – das Anlegen läuft über das
   * Board. Kommt sie hier an, wird sie sofort mitausgewählt, damit "neuer
   * Kunde" nicht noch einen zweiten Klick braucht.
   */
  justCreatedLabelId?: string | null;
  isBusy?: boolean;
  /**
   * Fehler aus dem letzten Call. Muss *im* Dialog stehen – das Overlay deckt
   * das Banner auf dem Board ab, ein 409 wäre sonst unsichtbar.
   */
  errorMessage?: string | null;
}>();

const emit = defineEmits<{
  (
    e: "submit",
    value: {
      title: string;
      description: string;
      columnId: KanbanColumnId;
      labelIds: string[];
    },
  ): void;
  (e: "delete", cardId: string): void;
  (e: "createLabel", name: string): void;
  (e: "close"): void;
}>();

const title = ref(props.card?.title ?? "");
const description = ref(props.card?.description ?? "");
const columnId = ref<KanbanColumnId>(props.card?.column_id ?? props.defaultColumnId);
const labelIds = ref<string[]>(props.card?.labels.map((label) => label.id) ?? []);
const titleInput = ref<HTMLInputElement | null>(null);

onMounted(() => {
  void nextTick(() => titleInput.value?.focus());
});

watch(
  () => props.justCreatedLabelId,
  (labelId) => {
    if (labelId && !labelIds.value.includes(labelId)) {
      labelIds.value = [...labelIds.value, labelId];
    }
  },
);

function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("de-DE");
}

function submit() {
  const trimmed = title.value.trim();
  if (!trimmed || props.isBusy) return;

  emit("submit", {
    title: trimmed,
    description: description.value.trim(),
    columnId: columnId.value,
    labelIds: labelIds.value,
  });
}
</script>
