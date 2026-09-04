import { computed, ref, shallowRef, watch } from "vue";
import axios from "axios";
import {
  fetchBoard,
  updateEntry,
  type MailBoard,
  type MailState,
  type MailUpdate,
  type MailView,
} from "@/api/mail_followup.api";

/**
 * Die Versandliste.
 *
 * Kein Store, wie bei der Telefonakquise: der Stand lebt in dieser einen View,
 * und jeder schreibende Aufruf liefert ihn vollständig zurück – es gibt also
 * keine optimistische Buchführung, die auseinanderlaufen könnte.
 *
 * Anders als der Arbeitsstand der Telefonakquise wird hier **nicht gepollt**.
 * Diese Liste ändert sich nicht von selbst: es gibt keine Frist, die im
 * Minutentakt etwas fällig macht, und die 30 Tage sind am nächsten Tag noch
 * rechtzeitig zu sehen. Ein Hintergrundabruf würde nur die Zeile umsortieren,
 * an der gerade jemand arbeitet.
 */
export function useMailFollowup() {
  const board = shallowRef<MailBoard | null>(null);
  // Startet auf `true`: `onMounted` feuert nach dem ersten Rendern, und mit
  // `false` zeigte die Seite in diesem einen Tick „keine Zusagen".
  const isLoading = ref(true);
  const isSaving = ref(false);
  const errorMessage = ref<string | null>(null);

  /** Die aktuelle Sicht – sie reist mit jedem Schreibzugriff mit. */
  const query = ref("");
  const stateFilter = ref<MailState | null>(null);
  const offset = ref(0);

  const counters = computed(() => board.value?.counters ?? null);
  const entries = computed(() => board.value?.entries ?? []);
  const actions = computed(() => board.value?.actions ?? []);
  const timeoutDays = computed(() => board.value?.timeout_days ?? 30);

  function view(): MailView {
    return { q: query.value, state: stateFilter.value, offset: offset.value };
  }

  function readDetail(error: unknown, fallback: string): string {
    if (axios.isAxiosError(error)) {
      const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
      if (typeof detail === "string") return detail;
    }
    return fallback;
  }

  async function load(options: { keepError?: boolean } = {}) {
    isLoading.value = true;
    if (!options.keepError) errorMessage.value = null;
    try {
      board.value = await fetchBoard(view());
    } catch (e) {
      console.error(e);
      errorMessage.value = readDetail(e, "Die Versandliste konnte nicht geladen werden.");
    } finally {
      isLoading.value = false;
    }
  }

  // Suche und Filter laden neu und fangen dabei vorne an: eine Seite 3, die es
  // nach dem Filtern nicht mehr gibt, wäre eine leere Liste ohne Erklärung.
  let searchTimer: ReturnType<typeof setTimeout> | null = null;

  watch(query, () => {
    if (searchTimer !== null) clearTimeout(searchTimer);
    // 300 ms wie bei der Blacklist: kurz genug, dass es sich wie Tippen
    // anfühlt, lang genug für einen Request statt zehn.
    searchTimer = setTimeout(() => {
      offset.value = 0;
      void load();
    }, 300);
  });

  function filterBy(state: MailState | null) {
    stateFilter.value = stateFilter.value === state ? null : state;
    offset.value = 0;
    void load();
  }

  function goToPage(next: number) {
    if (!board.value) return;
    if (next < 0 || next >= board.value.matched) return;

    offset.value = next;
    void load();
  }

  /**
   * Einen Zustand setzen oder eine Anmerkung schreiben.
   *
   * Die Sicht reist mit, damit die Antwort dieselbe Seite zeigt wie vorher –
   * sonst spränge die Liste nach jedem Klick zurück an den Anfang.
   */
  async function save(contactId: string, update: MailUpdate): Promise<boolean> {
    isSaving.value = true;
    errorMessage.value = null;
    try {
      board.value = await updateEntry(contactId, update, view());
      return true;
    } catch (e) {
      console.error(e);
      errorMessage.value = readDetail(e, "Die Änderung wurde nicht gespeichert.");
      // Die Liste kann veraltet sein – etwa wenn die Zusage inzwischen
      // richtiggestellt wurde. Dann ist der neue Stand die Antwort auf den
      // Fehler, aber die Meldung dazu muss stehen bleiben.
      await load({ keepError: true });
      return false;
    } finally {
      isSaving.value = false;
    }
  }

  return {
    board,
    counters,
    entries,
    actions,
    timeoutDays,
    query,
    stateFilter,
    isLoading,
    isSaving,
    errorMessage,

    load,
    filterBy,
    goToPage,
    save,
  };
}
