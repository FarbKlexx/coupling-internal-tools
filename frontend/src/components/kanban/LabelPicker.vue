<template>
  <div class="flex flex-col gap-2">
    <label class="text-sm font-medium">Kunde</label>

    <div v-if="labels.length" class="flex flex-wrap gap-1.5">
      <button
        v-for="label in labels"
        :key="label.id"
        type="button"
        :class="[
          'label-chip',
          `label-${label.color}`,
          !selected.includes(label.id) && 'opacity-40',
        ]"
        @click="toggle(label.id)"
      >
        {{ label.name }}
      </button>
    </div>
    <p v-else class="text-xs text-zinc-500">Noch kein Kunde angelegt.</p>

    <!-- Direkt hier anlegen, nicht nur im Manager: wer erst einen Dialog
         schließen muss, tippt den Kunden stattdessen in den Titel. -->
    <div class="flex gap-2">
      <input
        v-model="newName"
        type="text"
        placeholder="Neuer Kunde …"
        class="flex-1 rounded-md grey-background light-grey-stroke px-3 py-1.5 text-sm outline-none focus:border-blue-500"
        @keydown.enter.prevent="create"
      />
      <button
        type="button"
        class="rounded-md light-grey-stroke px-3 py-1.5 text-sm disabled:opacity-40"
        :disabled="!newName.trim() || isBusy"
        @click="create"
      >
        Anlegen
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import type { KanbanLabel } from "@/api/kanban.api";

const props = defineProps<{
  labels: KanbanLabel[];
  selected: string[];
  isBusy?: boolean;
}>();

const emit = defineEmits<{
  (e: "update:selected", value: string[]): void;
  (e: "create", name: string): void;
}>();

const newName = ref("");

/**
 * Mehrfachauswahl.
 *
 * Das Schema ist n:m, hier hängt also nur die UI-Entscheidung – auf
 * Einfachauswahl umstellen heißt: statt `toggle` die Auswahl ersetzen.
 */
function toggle(labelId: string) {
  const next = props.selected.includes(labelId)
    ? props.selected.filter((id) => id !== labelId)
    : [...props.selected, labelId];

  emit("update:selected", next);
}

function create() {
  const name = newName.value.trim();
  if (!name || props.isBusy) return;

  emit("create", name);
  newName.value = "";
}
</script>
