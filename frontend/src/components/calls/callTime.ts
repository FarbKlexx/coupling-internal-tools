/**
 * Zeitdarstellung der Telefonakquise.
 *
 * Liegt neben den Komponenten und nicht in `api/`, weil hier nichts über die
 * Leitung geht: das Backend speichert ausschließlich UTC, und wie daraus
 * „14:30" wird, weiß nur der Browser – er allein kennt die Zeitzone dessen,
 * der anruft.
 */

/** Datum und Uhrzeit für die Anzeige. */
export function formatMoment(iso: string | null): string {
  if (!iso) return "";

  const stamp = new Date(iso);
  if (Number.isNaN(stamp.getTime())) return iso;

  return stamp.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Nur die Uhrzeit – für „ab 14:30 wieder". */
export function formatClock(iso: string | null): string {
  if (!iso) return "";

  const stamp = new Date(iso);
  if (Number.isNaN(stamp.getTime())) return iso;

  return stamp.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

/** Wert für ein `datetime-local`-Feld – lokale Zeit, ohne Zeitzone. */
export function toLocalInput(stamp: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");

  return (
    `${stamp.getFullYear()}-${pad(stamp.getMonth() + 1)}-${pad(stamp.getDate())}` +
    `T${pad(stamp.getHours())}:${pad(stamp.getMinutes())}`
  );
}

/**
 * Morgen früh um 8 – das häufigste „später" bei Handwerksbetrieben.
 *
 * Wird lokal gerechnet und als ISO-Zeitstempel *mit* Zeitzone geschickt: das
 * Backend hat keine Zeitzonendatenbank und soll auch keine brauchen.
 */
export function tomorrowMorning(): Date {
  const stamp = new Date();
  stamp.setDate(stamp.getDate() + 1);
  stamp.setHours(8, 0, 0, 0);
  return stamp;
}
