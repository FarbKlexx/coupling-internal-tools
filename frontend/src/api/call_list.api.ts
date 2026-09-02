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
  /** Wie viele Nummern gesperrt sind – die Überschrift der Blacklist. */
  blacklist_count: number;
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

/**
 * Ein Prio-Wert, wie er in der hochgeladenen Datei vorkommt.
 *
 * Die Werte kommen mit der Antwort und stehen bewusst nicht hier: was „Prio"
 * bedeutet, entscheidet die Auswertung – mal A/B/C, mal 1–5.
 */
export interface PrioOption {
  /** Der Wert, der beim Import zurückgeschickt wird. */
  value: string;
  /** Wie er angezeigt wird („A", „(ohne Prio)"). */
  label: string;
  /** Zeilen mit dieser Prio in der Datei. */
  rows: number;
  /** Davon die, die tatsächlich importiert würden (ohne schon bekannte). */
  contacts: number;
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
  /** Überschrift der Prio-Spalte, oder `null` – dann gibt es keine Auswahl. */
  prio_column: string | null;
  prio_values: PrioOption[];
}

export interface ListImport {
  list_id: string;
  imported: number;
  skipped_rows: SkippedRow[];
  duplicates: SkippedRow[];
  warnings: string[];
  state: CallState;
  /** Zeilen, die wegen der Prio-Auswahl draußen blieben. */
  prio_skipped: number;
  /** Nummern, die dieser Import neu gesperrt hat. */
  blacklisted: number;
}

/**
 * Eine bereits eingetragene Entscheidung, wie sie in der Liste unter dem
 * Arbeitsplatz steht.
 *
 * Ob sich daran noch etwas ändern lässt, entscheidet das Backend und kommt als
 * `correctable` mit – dieselbe Prüfung, die die Korrektur gleich noch einmal
 * macht. Die Oberfläche darf sie nicht selbst nachbauen, sonst zeigt sie
 * irgendwann einen Knopf, der 400 antwortet.
 */
export interface CallDecision {
  event_id: number;
  contact_id: string;
  occurred_at: string;
  username: string;
  outcome: CallOutcome;
  outcome_label: string;
  betrieb: string;
  telefon: string;
  list_name: string;
  note: string;
  email: string;
  due_at: string | null;
  appointment_at: string | null;
  /** Zustand, in dem der Betrieb *jetzt* steht. */
  state: ContactState;
  state_label: string;
  /** Diese Zeile stellt eine frühere richtig. */
  corrects_event_id: number | null;
  /** Diese Zeile wurde später selbst richtiggestellt – sie bleibt sichtbar. */
  corrected: boolean;
  correctable: boolean;
  /** Warum nicht – leer, solange `correctable` wahr ist. */
  locked_reason: string;
}

export interface CallDecisionPage {
  entries: CallDecision[];
  total: number;
  offset: number;
  limit: number;
}

/** Woher eine Sperre stammt. Spiegel von `BlacklistSource` im Backend. */
export type BlacklistSource = "import" | "manuell";

export interface BlacklistEntry {
  /** Der Ziffernschlüssel – zugleich die Adresse des Eintrags. */
  telefon_key: string;
  telefon: string;
  betrieb: string;
  source: BlacklistSource;
  source_label: string;
  list_name: string;
  note: string;
  created_at: string;
  created_by: string;
}

export interface BlacklistPage {
  entries: BlacklistEntry[];
  total: number;
  /** Treffer der aktuellen Suche; ohne Suche gleich `total`. */
  matched: number;
  offset: number;
  limit: number;
}

export interface BlacklistMutation {
  added: number;
  already_known: number;
  skipped: SkippedRow[];
  page: BlacklistPage;
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

/**
 * Die zuletzt eingetragenen Entscheidungen, jüngste zuerst.
 *
 * Eigener Aufruf und nicht Teil von `CallState`: die Liste wird geblättert,
 * und der Arbeitsstand wird alle 30 Sekunden geholt.
 */
export async function fetchDecisions(params: {
  offset?: number;
  limit?: number;
}): Promise<CallDecisionPage> {
  const response = await http.get<CallDecisionPage>("/telefonakquise/decisions", { params });
  return response.data;
}

/**
 * Stellt eine eingetragene Entscheidung richtig.
 *
 * Überschreibt nichts: das Backend hängt eine neue Protokollzeile an, die auf
 * die falsche zeigt. Antwortet deshalb mit dem ganzen Arbeitsstand – eine
 * Korrektur kann den Betrieb zurück in den Vorrat holen.
 */
export async function correctDecision(
  eventId: number,
  payload: OutcomePayload,
): Promise<CallState> {
  const response = await http.post<CallState>(
    `/telefonakquise/decisions/${eventId}/correct`,
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

/**
 * Importiert die Liste.
 *
 * `prios` bleibt `undefined`, wenn nicht gefiltert wird – ein *fehlendes* Feld
 * heißt im Backend „alle Prios", eine leere Auswahl dagegen ist eine
 * Fehleingabe und wird abgelehnt.
 */
export async function importList(file: File, name: string, prios?: string[]): Promise<ListImport> {
  const form = new FormData();
  form.append("file", file);
  form.append("name", name);
  if (prios) form.append("prios", JSON.stringify(prios));

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

/** Ein Ausschnitt der Blacklist. Sie wird geblättert, nicht geladen. */
export async function fetchBlacklist(params: {
  q?: string;
  offset?: number;
  limit?: number;
}): Promise<BlacklistPage> {
  const response = await http.get<BlacklistPage>("/telefonakquise/blacklist", { params });
  return response.data;
}

/** Nummern von Hand sperren – eine pro Zeile, Name wahlweise davor/dahinter. */
export async function addBlacklistNumbers(
  numbers: string,
  note: string,
): Promise<BlacklistMutation> {
  const response = await http.post<BlacklistMutation>("/telefonakquise/blacklist", {
    numbers,
    note,
  });
  return response.data;
}

/** Eine CSV als Sperrliste einlesen. Pflicht ist allein die Telefonspalte. */
export async function importBlacklist(file: File): Promise<BlacklistMutation> {
  const form = new FormData();
  form.append("file", file);

  const response = await http.post<BlacklistMutation>("/telefonakquise/blacklist/import", form);
  return response.data;
}

/**
 * Gibt eine Nummer wieder frei.
 *
 * Suche und Versatz reisen mit, damit die Ansicht nach dem Entfernen dort
 * stehen bleibt, wo sie war, statt auf die erste Seite zu springen.
 */
export async function removeBlacklistEntry(
  telefonKey: string,
  params: { q?: string; offset?: number } = {},
): Promise<BlacklistPage> {
  const response = await http.delete<BlacklistPage>(
    `/telefonakquise/blacklist/${encodeURIComponent(telefonKey)}`,
    { params },
  );
  return response.data;
}

/** Die Sperrliste als CSV – lässt sich hier auch wieder einlesen. */
export function blacklistExportUrl(): string {
  return "/api/telefonakquise/export/blacklist";
}
