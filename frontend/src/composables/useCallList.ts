import { computed, onScopeDispose, ref, shallowRef } from "vue";
import axios from "axios";
import {
  deleteList,
  fetchState,
  importList,
  submitOutcome,
  updateList,
  type CallState,
  type OutcomePayload,
} from "@/api/call_list.api";

/**
 * Abstand der Hintergrund-Abfragen, solange der Tab sichtbar ist.
 *
 * Länger als die 10 Sekunden des Kanban-Boards: hier arbeitet in der Regel
 * eine Person allein, und der eine Fall, in dem sich der Stand von selbst
 * ändert, ist eine ablaufende Wiedervorlage. Eine halbe Minute Verzug ist
 * dabei ohne Bedeutung.
 */
const POLL_INTERVAL_MS = 30_000;

/** Fehlermeldung aus einer JSON-Fehlerantwort des Backends lesen. */
function readDetail(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

/**
 * Arbeitsstand der Telefonakquise.
 *
 * Kein Store: der Stand lebt nur in dieser einen View, und das Projekt hat
 * kein Pinia. Jeder schreibende Aufruf liefert den kompletten Stand zurück,
 * der hier den alten ersetzt – es gibt also keine optimistische Buchführung,
 * die auseinanderlaufen könnte.
 */
export function useCallList() {
  const state = shallowRef<CallState | null>(null);
  // Startet auf `true`, obwohl noch nichts läuft: `onMounted` feuert *nach*
  // dem ersten Rendern, und mit `false` zeigt die Seite in diesem einen Tick
  // „noch keine Anrufliste hinterlegt" — und dem Administrator eine
  // Listenverwaltung, die sich für leer hält und aufklappt.
  const isLoading = ref(true);
  const isSaving = ref(false);
  const errorMessage = ref<string | null>(null);

  const contact = computed(() => state.value?.contact ?? null);
  const counters = computed(() => state.value?.counters ?? null);
  const outcomes = computed(() => state.value?.outcomes ?? []);
  const lists = computed(() => state.value?.lists ?? []);
  const activeLists = computed(() => lists.value.filter((entry) => !entry.archived));

  /** Nichts fällig, aber etwas kommt zurück – der Unterschied zu „fertig". */
  const isWaiting = computed(
    () => contact.value === null && (counters.value?.wiedervorlage ?? 0) > 0,
  );

  /** Wirklich abgearbeitet: nichts offen, nichts auf Wiedervorlage. */
  const isDone = computed(
    () =>
      contact.value === null &&
      (counters.value?.gesamt ?? 0) > 0 &&
      (counters.value?.wiedervorlage ?? 0) === 0,
  );

  async function load(options: { keepError?: boolean } = {}) {
    isLoading.value = true;
    if (!options.keepError) errorMessage.value = null;
    try {
      state.value = await fetchState();
    } catch (e) {
      console.error(e);
      errorMessage.value = readDetail(e, "Der Arbeitsstand konnte nicht geladen werden.");
    } finally {
      isLoading.value = false;
    }
  }

  /**
   * Hintergrund-Abfrage.
   *
   * Ersetzt den Stand nur bei geänderter `revision`. Ohne diesen Vergleich
   * würde jeder Tick den angezeigten Kontakt neu erzeugen – und damit die
   * Notiz, die gerade jemand tippt, aus dem Formular werfen.
   */
  async function poll() {
    if (isSaving.value || isLoading.value) return;

    try {
      const next = await fetchState();
      if (next.revision !== state.value?.revision) state.value = next;
    } catch (e) {
      // Ein fehlgeschlagener Poll ist kein Fehler, den der Nutzer sehen muss –
      // der nächste Tick versucht es erneut.
      console.debug("Telefonakquise-Poll fehlgeschlagen", e);
    }
  }

  let timer: ReturnType<typeof setInterval> | null = null;

  function onVisibilityChange() {
    if (document.visibilityState === "visible") void poll();
  }

  function startPolling() {
    if (timer !== null) return;
    timer = setInterval(() => {
      if (document.visibilityState === "visible") void poll();
    }, POLL_INTERVAL_MS);
    document.addEventListener("visibilitychange", onVisibilityChange);
  }

  function stopPolling() {
    if (timer !== null) clearInterval(timer);
    timer = null;
    document.removeEventListener("visibilitychange", onVisibilityChange);
  }

  onScopeDispose(stopPolling);

  /** Führt eine Mutation aus und übernimmt den zurückgegebenen Stand. */
  async function mutate(
    action: () => Promise<CallState>,
    fallbackMessage: string,
  ): Promise<boolean> {
    isSaving.value = true;
    errorMessage.value = null;
    try {
      state.value = await action();
      return true;
    } catch (e) {
      console.error(e);
      errorMessage.value = readDetail(e, fallbackMessage);
      return false;
    } finally {
      isSaving.value = false;
    }
  }

  return {
    state,
    contact,
    counters,
    outcomes,
    lists,
    activeLists,
    isLoading,
    isSaving,
    isWaiting,
    isDone,
    errorMessage,

    load,
    startPolling,
    stopPolling,

    recordOutcome: (contactId: string, payload: OutcomePayload) =>
      mutate(() => submitOutcome(contactId, payload), "Das Ergebnis wurde nicht gespeichert."),

    /**
     * Import läuft nicht über `mutate`: der Aufrufer braucht die
     * übersprungenen Zeilen aus der Antwort und nicht nur den neuen Stand.
     */
    async uploadList(file: File, name: string) {
      isSaving.value = true;
      errorMessage.value = null;
      try {
        const result = await importList(file, name);
        state.value = result.state;
        return result;
      } catch (e) {
        console.error(e);
        errorMessage.value = readDetail(e, "Die Liste konnte nicht importiert werden.");
        return null;
      } finally {
        isSaving.value = false;
      }
    },

    editList: (listId: string, payload: { name?: string; archived?: boolean }) =>
      mutate(() => updateList(listId, payload), "Die Änderung wurde nicht gespeichert."),

    removeList: (listId: string, force = false) =>
      mutate(() => deleteList(listId, force), "Die Liste konnte nicht gelöscht werden."),
  };
}
