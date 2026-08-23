import type { KanbanColumnId } from "@/api/kanban.api";

export interface CardTransition {
  to: KanbanColumnId;
  /** Material-Symbols-Ligatur. */
  icon: string;
}

/**
 * Ein-Klick-Wege aus einer Spalte heraus.
 *
 * Reine Anzeige-Politik: das Backend erlaubt jede Spalte als Ziel, das hier
 * ist nur die Abkuerzung fuer den ueblichen Weg. Eine Spalte ohne Eintrag
 * bekommt keinen Button – Ziehen und der Dialog verschieben sie weiterhin.
 * `Done` und `On hold` sind Endpunkte und stehen deshalb nicht drin.
 */
export const CARD_TRANSITIONS: Partial<Record<KanbanColumnId, CardTransition[]>> = {
  ideen: [{ to: "todo", icon: "arrow_forward" }],
  todo: [{ to: "in_progress", icon: "arrow_forward" }],
  in_progress: [
    { to: "done", icon: "check" },
    { to: "on_hold", icon: "pause" },
  ],
};

export function transitionsFor(columnId: KanbanColumnId): CardTransition[] {
  return CARD_TRANSITIONS[columnId] ?? [];
}
