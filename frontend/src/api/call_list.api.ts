import { http } from "./http";

/**
 * Zustände eines Kontakts. Spiegel von `ContactState` im Backend
 * (`backend/app/schemas/call_list.py`).
 */
export type ContactState =
  | "offen"
  | "wiedervorlage"
  | "rueckruf"
  | "zugesagt"
  | "abgelehnt"
  | "ungueltig";

/**
 * Die Ergebnisse, die der Anrufer anklicken kann.
 *
 * Gespiegelt aus `CallOutcome` im Backend. Beschriftung, Beschreibung und
 * Tonlage kommen dagegen *mit der Antwort* (`CallState.outcomes`) – hier
 * stehen nur die IDs, weil das Frontend jeder ID ein Symbol und eine
 * Tastenkombination zuordnet. `callOutcomes.test.ts` hält beide Seiten
 * zusammen, nach dem Muster von `labelPalette.test.ts`.
 */
export const CALL_OUTCOMES = [
  "zugesagt",
  "nicht_erreichbar",
  "rueckruf",
  "abgelehnt",
  "nummer_falsch",
] as const;

export type CallOutcome = (typeof CALL_OUTCOMES)[number];

/** Welchen Zeitpunkt ein Ergebnis zusätzlich braucht. */
export type TimeInput = "none" | "snooze" | "appointment";

export interface OutcomeInfo {
  id: CallOutcome;
  label: string;
  description: string;
  tone: "positive" | "neutral" | "negative";
  time_input: TimeInput;
  resulting_state: ContactState;
}

export interface ContactField {
  label: string;
  value: string;
}

export interface CallEvent {
  occurred_at: string;
  username: string;
  outcome: CallOutcome;
  outcome_label: string;
  note: string;
  email: string;
  appointment_at: string | null;
  due_at: string | null;
}

export interface CallContact {
  id: string;
  list_id: string;
  list_name: string;
  betrieb: string;
  telefon: string;
  email: string;
  ort: string;
  plz: string;
  website: string;
  gewerk: string;
  prio: string;
  befunde: string;
  /** Die Zusatzspalten der CSV, in der Reihenfolge der Datei. */
  extras: ContactField[];
  state: ContactState;
  state_label: string;
  attempts: number;
  due_at: string | null;
  appointment_at: string | null;
  note: string;
  history: CallEvent[];
}

export interface CallCounters {
  gesamt: number;
  offen: number;
  wiedervorlage: number;
  zugesagt: number;
  abgelehnt: number;
  ungueltig: number;
  zugesagt_ohne_email: number;
}

export interface CallListInfo {
  id: string;
  name: string;
  source_filename: string;
  created_at: string;
  created_by: string;
  archived: boolean;
  counters: CallCounters;
}

export interface CallState {
  /** Zählt jeden Schreibvorgang. Steuert, ob ein Poll den State ersetzt. */
  revision: number;
  counters: CallCounters;
  contact: CallContact | null;
  next_due_at: string | null;
  outcomes: OutcomeInfo[];
  lists: CallListInfo[];
}

export interface OutcomePayload {
  outcome: CallOutcome;
  note?: string;
  /** `undefined` = unverändert, `""` = löschen. */
  email?: string;
  snooze_minutes?: number;
  /** Vollständiger ISO-Zeitstempel *mit* Zeitzone. */
  due_at?: string;
  appointment_at?: string;
}

export interface SkippedRow {
  line: number;
  reason: string;
}

export interface ColumnMapping {
  field: string;
  label: string;
  column: string;
  empty_count: number;
}

export interface ListAnalyse {
  name_suggestion: string;
  encoding: string;
  delimiter: string;
  data_rows: number;
  contacts: number;
  mapping: ColumnMapping[];
  extra_columns: string[];
  skipped_rows: SkippedRow[];
  duplicates: SkippedRow[];
  warnings: string[];
}

export interface ListImport {
  list_id: string;
  imported: number;
  skipped_rows: SkippedRow[];
  duplicates: SkippedRow[];
  warnings: string[];
  state: CallState;
}

/**
 * Jeder schreibende Call antwortet mit dem *ganzen* Arbeitsstand.
 *
 * Wie beim Kanban-Board: das sind ein paar Kilobyte und erspart die
 * Buchhaltung, ob der Zähler im Browser noch zu dem in der Datenbank passt.
 */
export async function fetchState(signal?: AbortSignal): Promise<CallState> {
  const response = await http.get<CallState>("/telefonakquise/state", { signal });
  return response.data;
}

export async function submitOutcome(
  contactId: string,
  payload: OutcomePayload,
): Promise<CallState> {
  const response = await http.post<CallState>(
    `/telefonakquise/contacts/${contactId}/outcome`,
    payload,
  );
  return response.data;
}

/** Trockenlauf – liest die Datei ein, speichert nichts. */
export async function analyseList(file: File): Promise<ListAnalyse> {
  const form = new FormData();
  form.append("file", file);

  const response = await http.post<ListAnalyse>("/telefonakquise/lists/analyse", form);
  return response.data;
}

export async function importList(file: File, name: string): Promise<ListImport> {
  const form = new FormData();
  form.append("file", file);
  form.append("name", name);

  const response = await http.post<ListImport>("/telefonakquise/lists", form);
  return response.data;
}

export async function updateList(
  listId: string,
  payload: { name?: string; archived?: boolean },
): Promise<CallState> {
  const response = await http.patch<CallState>(`/telefonakquise/lists/${listId}`, payload);
  return response.data;
}

/**
 * Löscht eine Liste endgültig.
 *
 * Ohne `force` antwortet das Backend mit 409, solange Anrufe protokolliert
 * sind – archivieren ist der normale Weg, eine Liste zu beenden.
 */
export async function deleteList(listId: string, force = false): Promise<CallState> {
  const response = await http.delete<CallState>(`/telefonakquise/lists/${listId}`, {
    params: { force },
  });
  return response.data;
}

/** Die Zusagen als CSV – die Datei, aus der der Mailversand liest. */
export function promisedExportUrl(): string {
  return "/api/telefonakquise/export/zusagen";
}

/** Das vollständige Anrufprotokoll als CSV – der Nachweis zum Mitnehmen. */
export function protocolExportUrl(): string {
  return "/api/telefonakquise/export/protokoll";
}
