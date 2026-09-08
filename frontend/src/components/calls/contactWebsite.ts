/**
 * Die Website eines Kontakts als anklickbarer Link.
 *
 * Liegt neben `callTime.ts` und aus demselben Grund: beide Ansichten über
 * `calls.db` – Telefonakquise und Mailversand – zeigen dieselbe Adresse
 * desselben Betriebs, und ob daraus ein Link wird, entscheidet nicht das
 * Backend, sondern der Browser.
 *
 * Der Grund für das Modul ist der Wert selbst. `website` kommt wortwörtlich
 * aus der CSV – `core/call_list_csv.py` normalisiert dieses Feld nicht –, und
 * die Analysen schreiben dort „www.beispiel.de“ genauso wie
 * „https://beispiel.de/“. Ein `href="www.beispiel.de"` ist aber **relativ**:
 * der Klick landet in der eigenen SPA unter `/mailversand/www.beispiel.de`
 * statt beim Betrieb. Ein fehlendes Schema wird deshalb hier ergänzt.
 *
 * Was sich nicht in eine http(s)-Adresse übersetzen lässt, wird zu Text und
 * verschwindet nicht: in diesen Spalten stehen auch „keine“, eine Telefon-
 * nummer oder eine E-Mail-Adresse, und beim Telefonieren ist ein sichtbarer
 * falscher Eintrag mehr wert als ein stillschweigend weggelassener.
 */

/** Nur diese beiden Schemata dürfen in ein `href`. */
const ALLOWED_PROTOCOLS = new Set(["http:", "https:"]);

/**
 * Ein vorangestelltes Schema – mit oder ohne „//“.
 *
 * Der Punkt fehlt in der Zeichenklasse absichtlich, anders als in echten
 * Schema-Grammatiken: sonst gälte „beispiel.de:8080“ als Schema „beispiel.de“
 * und bekäme kein „https://“ davor.
 */
const HAS_SCHEME = /^[a-z][a-z0-9+-]*:/i;

export type ContactWebsite = {
  /** Absolute URL fürs `href`, oder `null`, wenn daraus keine wird. */
  href: string | null;
  /** Was angezeigt wird: Hostname ohne „www.“, sonst der Wert wie er kam. */
  label: string;
};

/** `null`, wenn das Feld leer ist – dann gibt es nichts anzuzeigen. */
export function contactWebsite(value: string): ContactWebsite | null {
  const raw = value.trim();
  if (!raw) return null;

  const candidate = HAS_SCHEME.test(raw) ? raw : `https://${raw}`;

  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return { href: null, label: raw };
  }

  // `mailto:`/`javascript:` und alles andere bleiben Text. Und ein Hostname
  // ohne Punkt ist keine Website, sondern ein Wort aus der Tabelle („keine“) –
  // ein Link darauf führte ins Leere.
  if (!ALLOWED_PROTOCOLS.has(url.protocol) || !url.hostname.includes(".")) {
    return { href: null, label: raw };
  }

  return { href: url.href, label: displayLabel(url) };
}

/**
 * Kurzform für die Anzeige.
 *
 * Die Zeile im Mailversand trägt schon Adresse, Nummer, Ort und Gewerk; eine
 * volle URL mit Schema und Schrägstrich wäre dort der längste Teil, ohne mehr
 * zu sagen. Der Pfad bleibt aber stehen – er unterscheidet zwei Einträge
 * derselben Domain.
 */
function displayLabel(url: URL): string {
  const host = url.hostname.replace(/^www\./i, "");
  const path = url.pathname === "/" ? "" : url.pathname.replace(/\/$/, "");

  return `${host}${path}`;
}
