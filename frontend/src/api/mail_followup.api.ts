import { http } from "./http";
import type { ContactField } from "./call_list.api";

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
export const MAIL_STATES = [
  "offen",
  "versendet",
  "nachfassen",
  "nachgefasst",
  "positiv",
  "abgelehnt",
  "keine_antwort",
] as const;

export type MailState = (typeof MAIL_STATES)[number];

/**
 * Die Bau-Einschätzung einer Zusage. Spiegel von `BuildReadiness` im Backend.
 *
 * Zweite, vom Versandstand unabhängige Größe: sie sagt, wo die *Website*
 * steht. Zuerst, ob die bestehende Inhalt hat, den die neue übernehmen kann –
 * hat sie keinen, ist es kein Redesign mehr, dann müssen Texte entstehen, und
 * darüber muss vorher jemand mit dem Kunden sprechen. Und dann, mit
 * `in_development` und `ready_to_mail`, dass die neue Seite gebaut wird bzw.
 * schon steht und nur noch zum Betrieb muss: gebaut, aber noch nicht
 * verschickt.
 *
 * `unbewertet` ist der Ausgangswert *und* der Rückweg: entfernt wird ein
 * Marker, indem man ihn setzt (siehe `MailUpdate.readiness`).
 */
export const BUILD_READINESS = [
  "unbewertet",
  "ready_to_build",
  "in_development",
  "ready_to_mail",
  "missing_content",
] as const;

export type BuildReadiness = (typeof BUILD_READINESS)[number];

/**
 * Ein Marker, wie ihn das Frontend rendert – Beschriftung und Beschreibung
 * kommen mit der Antwort (`MailBoard.readiness_options`).
 *
 * Ohne `tone`, anders als bei den Zustands-Knöpfen: „Missing Content" ist
 * keine schlechte Nachricht, sondern mehr Arbeit. Die Farben der Werte stehen
 * deshalb in der Oberfläche (`READINESS`).
 */
export interface ReadinessOptionInfo {
  id: BuildReadiness;
  label: string;
  description: string;
}

/**
 * Der Umfangs-Marker („Bigger than expected"), wie ihn das Backend mitschickt.
 *
 * Dritte Größe neben Versandstand und Bau-Einschätzung – und die einzige, die
 * mit beiden *kombinierbar* ist: eine Seite kann „In Development" und größer
 * als ein Onepager sein, und genau dafür gibt es sie. Deshalb ein eigenes
 * Feld und kein weiterer `BuildReadiness`-Wert, der beim nächsten Bauschritt
 * wieder verschwände.
 *
 * Ein Eintrag statt eines Katalogs: der Marker ist gesetzt oder nicht.
 * `undo_description` ist der Titel des gesetzten Knopfes – dieselbe Rolle wie
 * „Einschätzung entfernen" im Katalog der Bau-Einschätzung.
 */
export interface ScopeMarkerInfo {
  label: string;
  description: string;
  undo_description: string;
}

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
  /** Die Prio aus der Datei – die Liste zeigt sie nicht, das Kopieren nimmt sie mit. */
  prio: string;
  /** Der Gesprächsaufhänger aus der Datei. */
  befunde: string;
  /**
   * Alle übrigen Spalten der Anrufliste, in der Reihenfolge der Datei.
   *
   * Angezeigt wird davon nichts – sie sind der Grund, warum eine Zeile sich
   * als Text kopieren lässt: was in ihnen steht, weiß nur die Analyse, aus
   * der die Liste kam.
   */
  extras: ContactField[];
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
  /**
   * Die Bau-Einschätzung – unabhängig vom Versandstand, aber nur, solange
   * die Mail nicht heraus ist: danach `unbewertet`, weil die Reihe der Weg
   * *bis* zur Mail ist. Der gesetzte Wert bleibt gespeichert und kommt
   * zurück, wenn der Versand zurückgesetzt wird.
   */
  readiness: BuildReadiness;
  readiness_label: string;
  /**
   * Welche Marker diese Zeile setzen kann – leer, sobald die Mail heraus ist.
   *
   * Dieselbe Rolle wie `actions`: die Oberfläche baut die Regel nicht nach,
   * sonst wächst ihr ein Knopf, der mit 400 antwortet.
   */
  readiness_actions: BuildReadiness[];
  /**
   * „Bigger than expected" – die dritte Größe, kombinierbar mit den beiden
   * anderen. `false` heißt „hat niemand gesagt", nicht „ist ein Onepager".
   */
  oversized: boolean;
  /** Der Zustand folgt aus der Frist und wurde nicht angeklickt. */
  automatic: boolean;
  sent_at: string | null;
  answered_at: string | null;
  /** Wann telefonisch nachgefasst wurde – `null`, solange niemand angerufen hat. */
  followed_up_at: string | null;
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

/**
 * Die Zahlen über der Liste – zwei Aufteilungen derselben Menge.
 *
 * Die Oberfläche hat zwei Filterreihen, und **jede zählt innerhalb der
 * Auswahl der anderen**: mit Reiter „Offen" nennen die Marker die offenen
 * Zusagen, und ihre Zahlen ergeben zusammen die Zahl auf dem Reiter.
 * Ihren eigenen Filter lässt eine Reihe außen vor, sonst gäbe es keinen
 * Rückweg, der eine Zahl nennt. Die Suche bleibt aus beiden heraus.
 *
 * Gerechnet wird das im Backend (`_counters`) – hier ist nur zu wissen, dass
 * die Zahlen zur mitgeschickten Sicht gehören.
 */
export interface MailCounters {
  /** Alle Zusagen der Auswahl – die Zahl hinter dem Reiter „Alle". */
  gesamt: number;
  offen: number;
  versendet: number;
  /** Fällig zum Anrufen – die zweite Zahl, die auf null laufen soll. */
  nachfassen: number;
  /** Angerufen, wartet weiter. */
  nachgefasst: number;
  positiv: number;
  abgelehnt: number;
  keine_antwort: number;
  /** Zusagen ohne Adresse – die Nacharbeit, die sonst niemand sieht. */
  ohne_email: number;
  /**
   * Die Bau-Einschätzung, gezählt innerhalb des Versandstand-Filters.
   *
   * Ohne ihn über alle Zusagen: „wie viele könnten wir sofort bauen?" ist die
   * Frage, für die die Marker gesetzt werden – und die stellt sich vor der
   * Antwort auf die Mail.
   */
  ready_to_build: number;
  /** Wird gerade gebaut. */
  in_development: number;
  /** Gebaut, aber noch nicht beim Betrieb. */
  ready_to_mail: number;
  missing_content: number;
  unbewertet: number;
  /** Zusagen, deren Seite größer als ein Onepager ist. Eine Zahl statt einer
   *  Aufteilung: der Marker ist gesetzt oder nicht. */
  oversized: number;
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
  /** Die Marker samt Beschriftung – wie `actions` Daten und nicht Code. */
  readiness_options: ReadinessOptionInfo[];
  /** Der Umfangs-Marker. Einer statt einer Liste: gesetzt oder nicht. */
  scope_marker: ScopeMarkerInfo;
  /** Die Frist, nach der ohne Antwort „keine Antwort" gilt. */
  timeout_days: number;
  /** Die kürzere Frist, nach der nachtelefoniert werden soll. */
  followup_days: number;
}

/** Die Sicht, aus der ein Klick kam – sie reist mit, damit die Liste steht. */
export interface MailView {
  q?: string;
  state?: MailState | null;
  /** Zweiter, unabhängiger Filter: „was ist verschickt" und „was können wir
   *  bauen" sind zwei Fragen, zusammen ergeben sie die Bauliste. */
  readiness?: BuildReadiness | null;
  /** Dritter Filter: „was ist größer als ein Onepager". `null` heißt „alle";
   *  `false` ist eine echte Auswahl (die Seiten ohne Marker). */
  oversized?: boolean | null;
  offset?: number;
  limit?: number;
}

/**
 * Was ein Klick schickt. Jedes Feld einzeln, jedes Weglassen „unverändert".
 *
 * Ohne `state` ist es eine reine Anmerkung oder ein reiner Marker – der
 * Versandstand bleibt dabei stehen, samt Versand- und Antwortdatum.
 */
export interface MailUpdate {
  state?: MailState;
  /** `undefined` = unverändert, `""` = löschen. */
  note?: string;
  /** `undefined` = unverändert; entfernt wird mit `"unbewertet"`. */
  readiness?: BuildReadiness;
  /** `undefined` = unverändert. Bei zwei Werten ist `false` der Rückweg – ein
   *  „unbewertet" wie bei der Bau-Einschätzung braucht es hier nicht. */
  oversized?: boolean;
}

/** Query-Parameter aus einer Sicht – leere Felder bleiben weg. */
function params(view: MailView): Record<string, string | number> {
  const query: Record<string, string | number> = {};

  if (view.q?.trim()) query.q = view.q.trim();
  if (view.state) query.state = view.state;
  if (view.readiness) query.readiness = view.readiness;
  // Nicht `if (view.oversized)`: `false` ist hier eine Auswahl und kein
  // „nicht gesetzt" – nur `null`/`undefined` heißt „alle".
  if (view.oversized !== null && view.oversized !== undefined) {
    query.oversized = String(view.oversized);
  }
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
