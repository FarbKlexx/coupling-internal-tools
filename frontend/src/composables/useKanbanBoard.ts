import { computed, onScopeDispose, ref, shallowRef } from "vue";
import axios from "axios";
import {
  createCard,
  createLabel,
  deleteCard,
  deleteLabel,
  fetchBoard,
  moveCard,
  setCardLabels,
  updateCard,
  updateLabel,
  type CardCreatePayload,
  type KanbanBoard,
  type KanbanCard,
  type KanbanColumnId,
  type KanbanLabel,
  type LabelColor,
} from "@/api/kanban.api";

/** Abstand der Hintergrund-Abfragen, solange der Tab sichtbar ist. */
const POLL_INTERVAL_MS = 10_000;

/** Fehlermeldung aus einer JSON-Fehlerantwort des Backends lesen. */
function readDetail(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

/**
 * Zustand des Kanban-Boards.
 *
 * Kein Store: das Board lebt nur in dieser einen View, und das Projekt hat
 * kein Pinia. Jeder schreibende Call liefert das komplette Board zurück, das
 * hier den alten Stand ersetzt – deshalb gibt es keine optimistische
 * Buchführung, die auseinanderlaufen könnte.
 */
export function useKanbanBoard() {
  const board = shallowRef<KanbanBoard | null>(null);
  const isLoading = ref(false);
  const isSaving = ref(false);
  const errorMessage = ref<string | null>(null);

  /**
   * Während eines Drags darf kein Poll den State ersetzen – sortablejs hat das
   * DOM dann schon angefasst und ein Austausch der Liste zerreißt es.
   */
  const isDragging = ref(false);

  /** Leere Auswahl = kein Filter. Enthält Label-IDs. */
  const activeLabelIds = ref<string[]>([]);
  const isFiltered = computed(() => activeLabelIds.value.length > 0);

  const labels = computed<KanbanLabel[]>(() => board.value?.labels ?? []);

  function matchesFilter(card: KanbanCard): boolean {
    if (!isFiltered.value) return true;
    return card.labels.some((label) => activeLabelIds.value.includes(label.id));
  }

  /** Spalten mit angewendetem Filter – die Ansicht, nicht der Wahrheitsstand. */
  const columns = computed(() =>
    (board.value?.columns ?? []).map((column) => ({
      ...column,
      cards: column.cards.filter(matchesFilter),
    })),
  );

  function apply(next: KanbanBoard) {
    board.value = next;
  }

  /**
   * Board neu laden.
   *
   * `keepError` behält eine bereits gesetzte Meldung: nach einer
   * fehlgeschlagenen Mutation wird neu geladen, um den DOM-Stand von
   * sortablejs aufzuräumen – der Grund des Fehlschlags muss dabei aber stehen
   * bleiben, sonst scheitert die Aktion für den Nutzer lautlos.
   */
  async function load(options: { keepError?: boolean } = {}) {
    isLoading.value = true;
    if (!options.keepError) errorMessage.value = null;
    try {
      apply(await fetchBoard());
    } catch (e) {
      console.error(e);
      errorMessage.value = readDetail(e, "Das Board konnte nicht geladen werden.");
    } finally {
      isLoading.value = false;
    }
  }

  /**
   * Hintergrund-Abfrage.
   *
   * Ersetzt den State nur bei geänderter `revision`. Ohne diesen Vergleich
   * würde jeder Tick die Karten-Arrays neu erzeugen und laufende Interaktionen
   * (Drag, offener Dialog) unnötig durchrütteln.
   */
  async function poll() {
    if (isDragging.value || isSaving.value || isLoading.value) return;

    try {
      const next = await fetchBoard();
      if (next.revision !== board.value?.revision) apply(next);
    } catch (e) {
      // Ein fehlgeschlagener Poll ist kein Fehler, den der Nutzer sehen muss –
      // der nächste Tick versucht es erneut.
      console.debug("Kanban-Poll fehlgeschlagen", e);
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

  /** Führt eine Mutation aus und übernimmt das zurückgegebene Board. */
  async function mutate(
    action: () => Promise<KanbanBoard>,
    fallbackMessage: string,
  ): Promise<boolean> {
    isSaving.value = true;
    errorMessage.value = null;
    try {
      apply(await action());
      return true;
    } catch (e) {
      console.error(e);
      errorMessage.value = readDetail(e, fallbackMessage);
      // Bei einem Fehler ist der DOM-Stand von sortablejs womöglich schon
      // verschoben – das Board neu laden räumt das auf.
      await load({ keepError: true });
      return false;
    } finally {
      isSaving.value = false;
    }
  }

  return {
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
    stopPolling,

    addCard: (payload: CardCreatePayload) =>
      mutate(() => createCard(payload), "Die Karte konnte nicht angelegt werden."),

    editCard: (cardId: string, payload: { title?: string; description?: string }) =>
      mutate(() => updateCard(cardId, payload), "Die Änderung wurde nicht gespeichert."),

    relocateCard: (cardId: string, columnId: KanbanColumnId, position: number) =>
      mutate(
        () => moveCard(cardId, columnId, position),
        "Die Karte konnte nicht verschoben werden.",
      ),

    assignLabels: (cardId: string, labelIds: string[]) =>
      mutate(() => setCardLabels(cardId, labelIds), "Die Labels konnten nicht gespeichert werden."),

    removeCard: (cardId: string) =>
      mutate(() => deleteCard(cardId), "Die Karte konnte nicht gelöscht werden."),

    addLabel: (name: string, color?: LabelColor) =>
      mutate(() => createLabel(name, color), "Der Kunde konnte nicht angelegt werden."),

    editLabel: (
      labelId: string,
      payload: { name?: string; color?: LabelColor; archived?: boolean },
    ) => mutate(() => updateLabel(labelId, payload), "Die Änderung wurde nicht gespeichert."),

    removeLabel: (labelId: string, force = false) =>
      mutate(() => deleteLabel(labelId, force), "Der Kunde konnte nicht gelöscht werden."),
  };
}
