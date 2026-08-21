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
      class="w-[34rem] max-w-[90vw] rounded-xl border light-grey-background light-grey-stroke p-6 space-y-4"
    >
      <div class="flex items-start justify-between gap-4">
        <div class="space-y-1">
          <h2 class="text-lg font-semibold">Kunden verwalten</h2>
          <p class="text-xs text-zinc-500">
            Archivierte Kunden verschwinden aus Auswahl und Filter, bleiben aber auf den Karten
            sichtbar, auf denen sie schon liegen.
          </p>
        </div>
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

      <div class="flex gap-2">
        <input
          v-model="newName"
          type="text"
          placeholder="Neuer Kunde …"
          class="flex-1 rounded-md grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500"
          @keydown.enter.prevent="create"
        />
        <button
          type="button"
          class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-40"
          :disabled="!newName.trim() || isBusy"
          @click="create"
        >
          Anlegen
        </button>
      </div>

      <div class="max-h-80 space-y-1 overflow-y-auto pr-1">
        <p v-if="!labels.length" class="text-sm text-zinc-500">Noch kein Kunde angelegt.</p>

        <div
          v-for="label in labels"
          :key="label.id"
          class="rounded-md grey-background light-grey-stroke px-3 py-2"
        >
          <div class="flex items-center gap-2">
            <button
              type="button"
              :class="['label-swatch', `label-${label.color}`, 'shrink-0']"
              title="Farbe ändern"
              @click="expandedId = expandedId === label.id ? null : label.id"
            />

            <input
              :value="label.name"
              type="text"
              :class="[
                'min-w-0 flex-1 bg-transparent text-sm outline-none',
                label.archived && 'text-zinc-500 line-through',
              ]"
              @change="rename(label, ($event.target as HTMLInputElement).value)"
            />

            <span class="grey-text shrink-0" style="font-size: 11px">
              {{ usage[label.id] ?? 0 }} {{ (usage[label.id] ?? 0) === 1 ? "Karte" : "Karten" }}
            </span>

            <button
              type="button"
              class="grey-text shrink-0 hover:text-white"
              :title="label.archived ? 'Wieder aktivieren' : 'Archivieren'"
              @click="emit('update', label.id, { archived: !label.archived })"
            >
              <span class="material-symbols-outlined" style="font-size: 16px">
                {{ label.archived ? "unarchive" : "archive" }}
              </span>
            </button>

            <button
              type="button"
              class="shrink-0 text-red-400/80 hover:text-red-400"
              title="Endgültig löschen"
              @click="pendingDeleteId = label.id"
            >
              <span class="material-symbols-outlined" style="font-size: 16px">delete</span>
            </button>
          </div>

          <!-- Palette nur für die gerade angeklickte Zeile, das erspart ein
               positioniertes Popover. -->
          <div v-if="expandedId === label.id" class="mt-2 flex flex-wrap gap-1.5">
            <button
              v-for="color in LABEL_COLORS"
              :key="color"
              type="button"
              :class="[
                'label-swatch',
                `label-${color}`,
                color === label.color ? 'ring-2 ring-white' : 'opacity-60',
              ]"
              @click="pickColor(label.id, color)"
            />
          </div>

          <div v-if="pendingDeleteId === label.id" class="mt-2 space-y-2">
            <p class="text-xs text-red-300">
              {{
                (usage[label.id] ?? 0) > 0
                  ? `„${label.name}“ wird von ${usage[label.id]} Karte(n) entfernt. Das lässt sich nicht rückgängig machen.`
                  : `„${label.name}“ endgültig löschen?`
              }}
            </p>
            <div class="flex gap-2">
              <button
                type="button"
                class="rounded-md bg-red-600/90 px-3 py-1.5 text-xs font-medium hover:bg-red-600"
                @click="confirmDelete(label.id)"
              >
                Ja, löschen
              </button>
              <button
                type="button"
                class="rounded-md light-grey-stroke px-3 py-1.5 text-xs"
                @click="pendingDeleteId = null"
              >
                Abbrechen
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </v-overlay>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { LABEL_COLORS, type KanbanLabel, type LabelColor } from "@/api/kanban.api";

const props = defineProps<{
  /** Inklusive der archivierten – der Manager ist die einzige Stelle dafür. */
  labels: KanbanLabel[];
  /** Anzahl Karten pro Label, aus dem Board gezählt. */
  usage: Record<string, number>;
  isBusy?: boolean;
  /** Siehe CardDialog: das Overlay verdeckt das Banner auf dem Board. */
  errorMessage?: string | null;
}>();

const emit = defineEmits<{
  (e: "create", name: string): void;
  (
    e: "update",
    labelId: string,
    payload: { name?: string; color?: LabelColor; archived?: boolean },
  ): void;
  (e: "delete", labelId: string): void;
  (e: "close"): void;
}>();

const newName = ref("");
const expandedId = ref<string | null>(null);
const pendingDeleteId = ref<string | null>(null);

function create() {
  const name = newName.value.trim();
  if (!name || props.isBusy) return;

  emit("create", name);
  newName.value = "";
}

function rename(label: KanbanLabel, value: string) {
  const name = value.trim();
  if (!name || name === label.name) return;

  emit("update", label.id, { name });
}

function pickColor(labelId: string, color: LabelColor) {
  expandedId.value = null;
  emit("update", labelId, { color });
}

function confirmDelete(labelId: string) {
  pendingDeleteId.value = null;
  emit("delete", labelId);
}
</script>
