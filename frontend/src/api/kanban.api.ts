import { http } from "./http";

/** Spalten-Slugs. Müssen zum `KanbanColumn`-Enum im Backend passen. */
export type KanbanColumnId = "ideen" | "todo" | "in_progress" | "done" | "on_hold";

/**
 * Farbpalette für Labels.
 *
 * Gespiegelt aus `LabelColor` in `backend/app/schemas/kanban.py`. Die echten
 * Farbwerte stehen als `.label-<slug>`-Klassen in `src/style.css` – eine
 * elfte Farbe muss also an drei Stellen nachgetragen werden.
 */
export const LABEL_COLORS = [
  "blue",
  "orange",
  "green",
  "violet",
  "red",
  "teal",
  "pink",
  "amber",
  "lime",
  "slate",
] as const;

export type LabelColor = (typeof LABEL_COLORS)[number];

export interface KanbanLabel {
  id: string;
  name: string;
  color: LabelColor;
  archived: boolean;
}

export interface KanbanCard {
  id: string;
  column_id: KanbanColumnId;
  position: number;
  title: string;
  description: string;
  labels: KanbanLabel[];
  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface KanbanColumnView {
  id: KanbanColumnId;
  label: string;
  cards: KanbanCard[];
}

export interface KanbanBoard {
  /** Zählt jeden Schreibvorgang. Steuert, ob ein Poll den State ersetzt. */
  revision: number;
  columns: KanbanColumnView[];
  /** Alle nicht-archivierten Labels – für Picker und Filter. */
  labels: KanbanLabel[];
}

/**
 * Jeder schreibende Call antwortet mit dem *ganzen* Board.
 *
 * Das sind ein paar Kilobyte und erspart die Buchhaltung, ob die Positionen im
 * Client noch zu denen in der Datenbank passen.
 */
export async function fetchBoard(signal?: AbortSignal): Promise<KanbanBoard> {
  const response = await http.get<KanbanBoard>("/kanban/board", { signal });
  return response.data;
}

export interface CardCreatePayload {
  title: string;
  description?: string;
  column_id?: KanbanColumnId;
  label_ids?: string[];
}

export async function createCard(payload: CardCreatePayload): Promise<KanbanBoard> {
  const response = await http.post<KanbanBoard>("/kanban/cards", payload);
  return response.data;
}

export async function updateCard(
  cardId: string,
  payload: { title?: string; description?: string },
): Promise<KanbanBoard> {
  const response = await http.patch<KanbanBoard>(`/kanban/cards/${cardId}`, payload);
  return response.data;
}

export async function moveCard(
  cardId: string,
  columnId: KanbanColumnId,
  position: number,
): Promise<KanbanBoard> {
  const response = await http.post<KanbanBoard>(`/kanban/cards/${cardId}/move`, {
    column_id: columnId,
    position,
  });
  return response.data;
}

/** Setzt die komplette Label-Menge einer Karte, kein Delta. Idempotent. */
export async function setCardLabels(cardId: string, labelIds: string[]): Promise<KanbanBoard> {
  const response = await http.put<KanbanBoard>(`/kanban/cards/${cardId}/labels`, {
    label_ids: labelIds,
  });
  return response.data;
}

export async function deleteCard(cardId: string): Promise<KanbanBoard> {
  const response = await http.delete<KanbanBoard>(`/kanban/cards/${cardId}`);
  return response.data;
}

/** Nur die Label-Liste – der Manager braucht auch die archivierten. */
export async function fetchLabels(includeArchived = false): Promise<KanbanLabel[]> {
  const response = await http.get<KanbanLabel[]>("/kanban/labels", {
    params: { include_archived: includeArchived },
  });
  return response.data;
}

/** Farbe weglassen: das Backend nimmt die am wenigsten benutzte. */
export async function createLabel(name: string, color?: LabelColor): Promise<KanbanBoard> {
  const response = await http.post<KanbanBoard>("/kanban/labels", { name, color });
  return response.data;
}

export async function updateLabel(
  labelId: string,
  payload: { name?: string; color?: LabelColor; archived?: boolean },
): Promise<KanbanBoard> {
  const response = await http.patch<KanbanBoard>(`/kanban/labels/${labelId}`, payload);
  return response.data;
}

/**
 * Löscht ein Label endgültig.
 *
 * Ohne `force` antwortet das Backend mit 409, solange das Label auf Karten
 * liegt – archivieren ist der normale Weg, einen Kunden stillzulegen.
 */
export async function deleteLabel(labelId: string, force = false): Promise<KanbanBoard> {
  const response = await http.delete<KanbanBoard>(`/kanban/labels/${labelId}`, {
    params: { force },
  });
  return response.data;
}

/** Board als JSON-Download – das Backup, das sich jeder selbst ziehen kann. */
export function boardExportUrl(): string {
  return "/api/kanban/export";
}
