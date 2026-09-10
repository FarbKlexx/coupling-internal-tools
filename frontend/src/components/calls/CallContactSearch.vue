<script setup lang="ts">
/**
 * Die Kontaktsuche – der Weg zurück zu einem Betrieb.
 *
 * Der Arbeitsplatz darüber zeigt immer nur den *nächsten* Betrieb, und die
 * Entscheidungsliste reicht absichtlich nur ein Stück zurück. Ohne diese Suche
 * ist ein Betrieb, der einmal durchgelaufen ist, nicht mehr auffindbar – „was
 * war eigentlich bei Klappschmidt?" war bis hierher nicht beantwortbar.
 *
 * **Lesend, mit Absicht.** Eingetragen wird ein Ergebnis am Arbeitsplatz,
 * richtiggestellt in der Entscheidungsliste; ein dritter Schreibweg auf
 * denselben Nachweis hieße, dieselbe Regel an drei Stellen zu prüfen. Was hier
 * steht, ist die Auskunft: Zustand, Nummer, Adresse und das ganze Protokoll.
 *
 * Archivierte Listen sind eingeschlossen (das Backend entscheidet das) und
 * werden als solche gekennzeichnet – nachgesehen wird gerade dann, wenn eine
 * Runde schon vorbei ist.
 */
import { ref, watch } from "vue";
import type { CallContact, CallContactPage, ContactState } from "@/api/call_list.api";
import ContactWebsiteLink from "./ContactWebsiteLink.vue";
import { formatMoment } from "./callTime";

const props = defineProps<{
  page: CallContactPage | null;
  isSearching: boolean;
  /** Sucht nach kurzer Pause – die Verzögerung liegt im Composable. */
  search: (term: string) => void;
  goToPage: (offset: number) => void;
}>();

const query = ref("");

// Jede Eingabe geht an die Suche des Composables, die selbst wartet, bevor sie
// einen Request stellt. Ein Watcher und kein `@input`, weil neben `v-model` am
// selben Feld sonst die Reihenfolge zweier Listener entscheidet, ob `query`
// beim Aufruf schon den neuen Wert trägt.
watch(query, (term) => props.search(term));

/** Welche Treffer ihr Protokoll aufgeklappt zeigen. */
const opened = ref<Set<string>>(new Set());

function toggle(contactId: string) {
  const next = new Set(opened.value);
  if (!next.delete(contactId)) next.add(contactId);
  opened.value = next;
}

// Eine neue Trefferseite klappt alles wieder zu: die aufgeklappten IDs gehören
// zur vorigen Suche, und ein Kasten, der sich beim Weitertippen von selbst
// öffnet, verwirrt mehr, als er zeigt.
watch(
  () => props.page,
  () => {
    opened.value = new Set();
  },
);

/**
 * Farbe des Zustands – dieselbe Sprache wie in der Versandliste: grün heißt
 * Zusage, rot Widerspruch, bernstein „hier ist noch etwas zu tun".
 */
const STATE_CLASSES: Record<ContactState, string> = {
  offen: "light-grey-text",
  wiedervorlage: "text-amber-400",
  rueckruf: "text-blue-300",
  zugesagt: "text-emerald-400",
  kein_bedarf: "text-zinc-500",
  abgelehnt: "text-red-400",
  ungueltig: "text-zinc-500",
};

/** Was in der Zeile unter dem Namen steht, ohne die leeren Felder. */
function details(hit: CallContact): string[] {
  const ort = [hit.plz, hit.ort].filter(Boolean).join(" ");

  return [ort, hit.gewerk, hit.prio ? `Prio ${hit.prio}` : ""].filter(Boolean);
}

function attempts(hit: CallContact): string {
  if (hit.attempts === 0) return "noch nicht angerufen";

  return hit.attempts === 1 ? "1 Versuch" : `${hit.attempts} Versuche`;
}
</script>

<template>
  <section class="max-w-3xl space-y-2">
    <div class="flex items-baseline justify-between gap-3">
      <h3 class="text-sm font-semibold">Betrieb suchen</h3>
      <p class="text-xs text-zinc-500">
        Nachsehen, was bei einem Betrieb schon war – auch in beendeten Listen.
      </p>
    </div>

    <div class="relative">
      <span
        class="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500"
        style="font-size: 18px"
      >
        search
      </span>
      <input
        v-model="query"
        type="search"
        placeholder="Betrieb, Adresse oder Nummer suchen"
        aria-label="Kontakte durchsuchen"
        class="w-full rounded-md light-grey-background light-grey-stroke py-2 pl-10 pr-3 text-sm outline-none focus:border-blue-500 transition-colors"
      />
    </div>

    <p v-if="isSearching && !page" class="text-xs light-grey-text">wird gesucht …</p>

    <p v-else-if="page && !page.matched" class="text-xs light-grey-text">
      Kein Betrieb passt zu „{{ page.query }}“. Gesucht wird über Name, Adresse und Nummer.
    </p>

    <template v-else-if="page">
      <p class="text-xs text-zinc-500">{{ page.matched }} Treffer für „{{ page.query }}“</p>

      <ul class="space-y-1">
        <li
          v-for="hit in page.entries"
          :key="hit.id"
          class="rounded-md border light-grey-background light-grey-stroke px-3 py-2"
        >
          <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <div class="min-w-0 text-xs light-grey-text">
              <span class="white-text font-medium">{{ hit.betrieb }}</span>
              <span :class="['ml-2', STATE_CLASSES[hit.state]]">{{ hit.state_label }}</span>
              <!-- Ein vereinbarter Rückruf ist der einzige Zeitpunkt, den man
                   beim Nachsehen sofort braucht. -->
              <span v-if="hit.appointment_at" class="ml-2 text-blue-300">
                · {{ formatMoment(hit.appointment_at) }}
              </span>
            </div>
            <div class="shrink-0 text-xs text-zinc-500">
              {{ hit.list_name }}
              <template v-if="hit.list_archived"> (archiviert)</template>
              · {{ attempts(hit) }}
            </div>
          </div>

          <p class="mt-0.5 text-xs light-grey-text">
            <a
              :href="`tel:${hit.telefon.replace(/\s+/g, '')}`"
              class="hover:text-white transition-colors"
            >
              {{ hit.telefon }}
            </a>
            <template v-if="hit.email">
              ·
              <a :href="`mailto:${hit.email}`" class="hover:text-white transition-colors">
                {{ hit.email }}
              </a>
            </template>
            <template v-for="part in details(hit)" :key="part"> · {{ part }}</template>
            <template v-if="hit.website">
              · <ContactWebsiteLink :website="hit.website" />
            </template>
          </p>

          <p v-if="hit.note" class="mt-0.5 text-xs text-zinc-500 break-words whitespace-pre-line">
            „{{ hit.note }}“
          </p>

          <!-- Das Protokoll: die eigentliche Antwort auf „was war da?“ -->
          <div v-if="hit.history.length" class="mt-1">
            <button
              class="flex items-center gap-1 text-xs light-grey-text hover:text-white transition-colors"
              type="button"
              :aria-expanded="opened.has(hit.id)"
              @click="toggle(hit.id)"
            >
              <span class="material-symbols-outlined nav-icon">
                {{ opened.has(hit.id) ? "expand_less" : "expand_more" }}
              </span>
              {{ hit.history.length }}
              {{ hit.history.length === 1 ? "Eintragung" : "Eintragungen" }}
            </button>

            <ul v-if="opened.has(hit.id)" class="mt-1 space-y-1 text-xs light-grey-text">
              <li
                v-for="(event, index) in hit.history"
                :key="index"
                class="rounded-md grey-background light-grey-stroke px-3 py-1.5"
              >
                <span class="white-text">{{ event.outcome_label }}</span>
                · {{ formatMoment(event.occurred_at) }} · {{ event.username }}
                <span v-if="event.note" class="mt-0.5 block break-words whitespace-pre-line">
                  „{{ event.note }}“
                </span>
              </li>
            </ul>
          </div>
        </li>
      </ul>

      <!-- Blättern, wie in der Versandliste -->
      <div v-if="page.matched > page.limit" class="flex items-center gap-3 text-xs">
        <button
          class="chip"
          type="button"
          :disabled="page.offset === 0 || isSearching"
          @click="goToPage(page.offset - page.limit)"
        >
          zurück
        </button>
        <span class="light-grey-text">
          {{ page.offset + 1 }}–{{ Math.min(page.offset + page.limit, page.matched) }} von
          {{ page.matched }}
        </span>
        <button
          class="chip"
          type="button"
          :disabled="page.offset + page.limit >= page.matched || isSearching"
          @click="goToPage(page.offset + page.limit)"
        >
          weiter
        </button>
      </div>
    </template>
  </section>
</template>
