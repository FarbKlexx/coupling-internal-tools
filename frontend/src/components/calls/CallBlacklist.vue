<script setup lang="ts">
import { ref, watch } from "vue";
import {
  blacklistExportUrl,
  type BlacklistEntry,
  type BlacklistMutation,
  type BlacklistPage,
} from "@/api/call_list.api";

/**
 * Die Sperrliste – der Grund, dass sich zwei Anruflisten nicht überschneiden.
 *
 * Jede importierte Nummer landet hier von selbst; sichtbar ist sie trotzdem,
 * weil eine Sperre, die man nicht sehen und nicht aufheben kann, aus einem
 * versehentlich importierten Betrieb einen macht, den nie wieder jemand
 * anruft.
 *
 * Die Aktionen kommen als Funktionen herein und nicht als Ereignisse, wie in
 * `CallListManager.vue`: dieses Formular muss wissen, *ob* eine Aktion
 * geklappt hat, und ein Ereignis liefert diese Antwort nicht zurück.
 */
const props = defineProps<{
  page: BlacklistPage | null;
  total: number;
  query: string;
  isLoading: boolean;
  isSaving: boolean;
  load: (options?: { offset?: number }) => Promise<void>;
  add: (numbers: string, note: string) => Promise<BlacklistMutation | null>;
  upload: (file: File) => Promise<BlacklistMutation | null>;
  release: (telefonKey: string) => Promise<boolean>;
}>();

const emit = defineEmits<{ "update:query": [value: string] }>();

const open = ref(false);
const numbers = ref("");
const note = ref("");
const result = ref<BlacklistMutation | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

/** Erst beim Aufklappen laden – die Liste kann zehntausende Zeilen haben. */
async function toggle() {
  open.value = !open.value;
  if (open.value && props.page === null) await props.load();
}

// Die Suche tippt jemand; jeder Anschlag eine Abfrage wäre eine Abfrage zu
// viel. 300 ms sind kurz genug, dass es sich wie Tippen anfühlt.
let searchTimer: ReturnType<typeof setTimeout> | null = null;

watch(
  () => props.query,
  () => {
    if (!open.value) return;
    if (searchTimer !== null) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => void props.load(), 300);
  },
);

async function blockNow() {
  if (!numbers.value.trim() || props.isSaving) return;

  const outcome = await props.add(numbers.value, note.value.trim());

  if (outcome) {
    result.value = outcome;
    numbers.value = "";
    note.value = "";
  }
}

async function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  // Zurücksetzen, damit dieselbe Datei erneut ausgewählt werden kann.
  input.value = "";

  if (!file) return;

  const outcome = await props.upload(file);
  if (outcome) result.value = outcome;
}

function pageStep(direction: number) {
  if (!props.page) return;

  const next = props.page.offset + direction * props.page.limit;
  if (next < 0 || next >= props.page.matched) return;

  void props.load({ offset: next });
}

function label(entry: BlacklistEntry): string {
  return entry.betrieb || entry.telefon || entry.telefon_key;
}

function formatDate(iso: string): string {
  const stamp = new Date(iso);
  if (Number.isNaN(stamp.getTime())) return iso;

  return stamp.toLocaleDateString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}
</script>

<template>
  <div class="space-y-3 border-t border-zinc-800 pt-4">
    <button class="flex w-full items-center justify-between gap-3" @click="toggle">
      <span class="flex items-center gap-2">
        <span class="material-symbols-outlined nav-icon">block</span>
        <span class="text-sm font-semibold">Blacklist</span>
        <span class="text-xs text-zinc-500">{{ total }} gesperrte Nummern</span>
      </span>
      <span class="material-symbols-outlined nav-icon">
        {{ open ? "expand_less" : "expand_more" }}
      </span>
    </button>

    <p class="text-xs text-zinc-500">
      Jede importierte Nummer wird hier gesperrt und bei künftigen Importen übersprungen – auch
      dann, wenn ihre Liste inzwischen archiviert ist. So bringen zwei Auswertungen desselben
      Gebiets die gemeinsamen Betriebe nicht zweimal in den Vorrat. Eine Liste zu
      <strong>löschen</strong> gibt ihre Nummern wieder frei, sie zu archivieren nicht.
    </p>

    <div v-if="open" class="space-y-4">
      <!-- Von Hand sperren -->
      <div class="space-y-2 rounded-md grey-background light-grey-stroke p-4">
        <label class="text-xs text-zinc-500" for="blacklist-numbers">
          Nummern sperren – eine pro Zeile, der Betrieb darf davor oder dahinter stehen
        </label>
        <textarea
          id="blacklist-numbers"
          v-model="numbers"
          rows="3"
          placeholder="05221 111&#10;Zaunbau Müller;05221 222"
          class="w-full rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
        ></textarea>

        <div class="flex flex-wrap items-end gap-2">
          <div class="flex grow flex-col gap-1">
            <label class="text-xs text-zinc-500" for="blacklist-note">
              Grund (optional, steht später beim Eintrag)
            </label>
            <input
              id="blacklist-note"
              v-model="note"
              type="text"
              placeholder="Bestandskunde"
              class="w-full rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
            />
          </div>
          <button
            class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-40 transition-colors"
            :disabled="isSaving || !numbers.trim()"
            @click="blockNow"
          >
            Sperren
          </button>
        </div>

        <div class="flex flex-wrap items-center gap-2 pt-1">
          <button class="chip" :disabled="isSaving" @click="fileInput?.click()">
            CSV mit Nummern einlesen
          </button>
          <a class="chip" :href="blacklistExportUrl()">Blacklist als CSV</a>
          <span class="text-xs text-zinc-500">
            Für den Import genügt eine Spalte „Telefon“; „Betrieb“ wird mitgenommen.
          </span>
        </div>
        <input
          ref="fileInput"
          type="file"
          accept=".csv,text/csv"
          class="hidden"
          @change="onFileChange"
        />

        <p v-if="result" class="text-xs text-emerald-400">
          {{ result.added }} Nummern gesperrt.
          <template v-if="result.already_known">
            {{ result.already_known }} waren schon gesperrt.
          </template>
          <template v-if="result.skipped.length">
            {{ result.skipped.length }} Zeilen ohne Nummer übersprungen ({{
              result.skipped
                .slice(0, 3)
                .map((row) => `Zeile ${row.line}`)
                .join(", ")
            }}).
          </template>
        </p>
      </div>

      <!-- Suchen und blättern -->
      <div class="flex flex-wrap items-center gap-2">
        <input
          type="search"
          :value="query"
          placeholder="Nach Nummer oder Betrieb suchen …"
          class="grow rounded-md light-grey-background light-grey-stroke px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
          @input="emit('update:query', ($event.target as HTMLInputElement).value)"
        />
        <span v-if="page" class="text-xs text-zinc-500">
          {{
            query.trim() ? `${page.matched} Treffer von ${page.total}` : `${page.total} Einträge`
          }}
        </span>
      </div>

      <p v-if="isLoading" class="text-xs light-grey-text">Blacklist wird geladen …</p>

      <p v-else-if="page && page.entries.length === 0" class="text-xs light-grey-text">
        {{ query.trim() ? "Keine Nummer passt zu dieser Suche." : "Noch nichts gesperrt." }}
      </p>

      <ul v-else-if="page" class="space-y-1">
        <li
          v-for="entry in page.entries"
          :key="entry.telefon_key"
          class="flex flex-wrap items-center justify-between gap-2 rounded-md grey-background light-grey-stroke px-3 py-2"
        >
          <div class="min-w-0">
            <p class="truncate text-sm">
              {{ label(entry) }}
              <span class="light-grey-text ml-1 text-xs">{{ entry.telefon }}</span>
            </p>
            <p class="truncate text-xs text-zinc-500">
              {{ entry.source_label }}
              <template v-if="entry.list_name"> · Liste „{{ entry.list_name }}“</template>
              · {{ formatDate(entry.created_at) }}
              <template v-if="entry.created_by"> · {{ entry.created_by }}</template>
              <template v-if="entry.note"> · {{ entry.note }}</template>
            </p>
          </div>
          <button
            class="card-action shrink-0"
            title="Nummer wieder freigeben"
            :disabled="isSaving"
            @click="release(entry.telefon_key)"
          >
            <span class="material-symbols-outlined nav-icon">lock_open</span>
          </button>
        </li>
      </ul>

      <div v-if="page && page.matched > page.limit" class="flex items-center gap-2">
        <button class="chip" :disabled="page.offset === 0" @click="pageStep(-1)">Zurück</button>
        <span class="text-xs text-zinc-500">
          {{ page.offset + 1 }}–{{ Math.min(page.offset + page.limit, page.matched) }} von
          {{ page.matched }}
        </span>
        <button
          class="chip"
          :disabled="page.offset + page.limit >= page.matched"
          @click="pageStep(1)"
        >
          Weiter
        </button>
      </div>
    </div>
  </div>
</template>
