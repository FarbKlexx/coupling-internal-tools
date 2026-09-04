import { http } from "./http";

/**
 * Der Mailversand – was aus einer Zusage der Telefonakquise geworden ist.
 *
 * Die Zeilen sind die Kontakte der Telefonakquise im Zustand „zugesagt"; neu
 * ist allein der Versandzustand. Die Seite hat deshalb eine eigene
 * Berechtigung, aber keine eigenen Kontakte: wird eine Zusage drüben
 * richtiggestellt, verschwindet die Zeile hier von selbst.
 */

/**
 * Die Zustände einer Zusage im Versand. Spiegel von `MailState` im Backend
 * (`backend/app/schemas/mail_followup.py`).
 *
 * Beschriftung, Beschreibung und Tonlage der Knöpfe kommen dagegen *mit der
 * Antwort* (`MailBoard.actions`) – hier stehen nur die IDs, weil das Frontend
 * jeder ID ein Symbol zuordnet. `mailStates.test.ts` hält beide Seiten
 * zusammen, nach dem Muster von `callOutcomes.test.ts`.
 */
export const MAIL_STATES = ["offen", "versendet", "positiv", "abgelehnt", "keine_antwort"] as const;

export type MailState = (typeof MAIL_STATES)[number];

export interface MailActionInfo {
  /** Der Zustand, in dem die Zeile danach steht – die Aktion *ist* ihr Ziel. */
  id: MailState;
  label: string;
  description: string;
  tone: "positive" | "neutral" | "negative";
}

export interface MailEntry {
  contact_id: string;
  betrieb: string;
  telefon: string;
  email: string;
  ort: string;
  plz: string;
  website: string;
  gewerk: string;
  list_id: string;
  list_name: string;
  /** Archivierte Listen bleiben sichtbar – die Zusage gilt weiter. */
  list_archived: boolean;
  promised_at: string | null;
  promised_by: string;
  /** Anmerkung aus dem Telefonat. */
  note: string;
  state: MailState;
  state_label: string;
  /** Der Zustand folgt aus der Frist und wurde nicht angeklickt. */
  automatic: boolean;
  sent_at: string | null;
  answered_at: string | null;
  days_since_sent: number | null;
  /** Anmerkung zum Versand – getrennt von der aus dem Telefonat. */
  mail_note: string;
  updated_at: string | null;
  updated_by: string;
  /**
   * Welche Knöpfe diese Zeile zeigt.
   *
   * Kommt aus derselben Übergangstabelle, gegen die das Backend beim
   * Schreiben prüft. Die Oberfläche darf sie nicht selbst nachbauen, sonst
   * wächst ihr ein Knopf, der mit 400 antwortet.
   */
  actions: MailState[];
}

export interface MailCounters {
  gesamt: number;
  offen: number;
  versendet: number;
  positiv: number;
  abgelehnt: number;
  keine_antwort: number;
  /** Zusagen ohne Adresse – die Nacharbeit, die sonst niemand sieht. */
  ohne_email: number;
}

export interface MailBoard {
  /** Zählt jede Änderung an der Anrufdatenbank – steuert den Poll. */
  revision: number;
  counters: MailCounters;
  entries: MailEntry[];
  /** Zusagen insgesamt … */
  total: number;
  /** … und die, die Suche und Filter übrig lassen. */
  matched: number;
  offset: number;
  limit: number;
  actions: MailActionInfo[];
  /** Die Frist, nach der ohne Antwort „keine Antwort" gilt. */
  timeout_days: number;
}

/** Die Sicht, aus der ein Klick kam – sie reist mit, damit die Liste steht. */
export interface MailView {
  q?: string;
  state?: MailState | null;
  offset?: number;
  limit?: number;
}

/** Was ein Klick schickt. Ohne `state` ist es eine reine Anmerkung. */
export interface MailUpdate {
  state?: MailState;
  /** `undefined` = unverändert, `""` = löschen. */
  note?: string;
}

/** Query-Parameter aus einer Sicht – leere Felder bleiben weg. */
function params(view: MailView): Record<string, string | number> {
  const query: Record<string, string | number> = {};

  if (view.q?.trim()) query.q = view.q.trim();
  if (view.state) query.state = view.state;
  if (view.offset) query.offset = view.offset;
  if (view.limit) query.limit = view.limit;

  return query;
}

export async function fetchBoard(view: MailView = {}, signal?: AbortSignal): Promise<MailBoard> {
  const response = await http.get<MailBoard>("/mailversand/board", {
    params: params(view),
    signal,
  });
  return response.data;
}

/**
 * Setzt den Versandzustand einer Zusage – oder nur ihre Anmerkung.
 *
 * Antwortet mit der ganzen Ansicht für dieselbe Sicht, aus der der Klick kam;
 * deshalb reisen Suche, Filter und Seite als Query-Parameter mit. Ohne das
 * spränge die Liste nach jedem Klick auf die erste Seite zurück.
 */
export async function updateEntry(
  contactId: string,
  update: MailUpdate,
  view: MailView = {},
): Promise<MailBoard> {
  const response = await http.post<MailBoard>(`/mailversand/contacts/${contactId}`, update, {
    params: params(view),
  });
  return response.data;
}

/** Die ganze Versandliste als CSV. */
export function exportUrl(): string {
  return "/api/mailversand/export";
}
