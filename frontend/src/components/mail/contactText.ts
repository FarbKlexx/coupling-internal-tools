/**
 * Eine Zeile der Versandliste als Text.
 *
 * Gedacht zum Weiterreichen: in einen Prompt, in eine Notiz, in die Mail
 * selbst. Deshalb keine Tabelle und kein JSON, sondern „Feld: Wert" und
 * darunter die längeren Blöcke — beides liest ein Mensch wie ein Modell.
 *
 * Zwei Regeln halten den Text brauchbar:
 *
 * * **Leeres steht nicht drin.** Eine Zeile „Website: " ist keine Auskunft,
 *   sondern Füllmaterial, das im Prompt als Behauptung ankommt.
 * * **Die Reihenfolge ist die der Datei.** Die freien Spalten (`extras`)
 *   kommen so, wie die Analyse sie geliefert hat — was sie bedeuten, weiß
 *   diese Anwendung nicht, und sie umzusortieren hieße, ihnen eine Ordnung zu
 *   unterstellen.
 *
 * Die Zeitangaben werden hier *mit* Jahr geschrieben, anders als in der Liste
 * (`formatMoment`): dort steht der Text neben seiner Zeile, hier steht er
 * irgendwann irgendwo ohne diesen Zusammenhang.
 */
import type { MailEntry } from "@/api/mail_followup.api";

/** Datum und Uhrzeit, ausgeschrieben – der Text verlässt die Anwendung. */
function moment(iso: string | null): string {
  if (!iso) return "";

  const stamp = new Date(iso);
  if (Number.isNaN(stamp.getTime())) return iso;

  return stamp.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** „seit 12 Tagen" – dieselbe Formulierung wie an der Zeile. */
function waiting(days: number | null): string {
  if (days === null) return "";
  if (days === 0) return "heute";

  return `seit ${days} ${days === 1 ? "Tag" : "Tagen"}`;
}

/** Eine „Feld: Wert"-Zeile, oder nichts, wenn der Wert leer ist. */
function line(label: string, value: string): string[] {
  const text = value.trim();

  return text ? [`${label}: ${text}`] : [];
}

/** Ein mehrzeiliger Block unter seiner Überschrift. */
function block(label: string, value: string): string[] {
  const text = value.trim();

  return text ? ["", `${label}:`, text] : [];
}

/**
 * Alles, was diese Anwendung über den Betrieb einer Zusage weiß.
 *
 * `scopeLabel` kommt mit der Antwort des Backends (`scope_marker.label`) –
 * wie an der Zeile selbst wird der Umfangs-Marker nur genannt, wenn er
 * gesetzt ist, denn sein Fehlen ist keine Aussage.
 */
export function contactText(entry: MailEntry, scopeLabel = "Bigger than expected"): string {
  const parts: string[] = [
    ...line("Betrieb", entry.betrieb),
    ...line("Gewerk", entry.gewerk),
    ...line("Adresse", `${entry.plz} ${entry.ort}`),
    ...line("Telefon", entry.telefon),
    ...line("E-Mail", entry.email),
    ...line("Website", entry.website),
    ...line("Prio", entry.prio),
    ...line("Liste", entry.list_name + (entry.list_archived ? " (archiviert)" : "")),

    "",
    // Der Versandstand mit dem Hinweis, wenn er aus der Frist folgt und nicht
    // angeklickt wurde – sonst liest sich „keine Antwort" wie eine
    // Entscheidung.
    ...line("Versandstand", entry.state_label + (entry.automatic ? " (automatisch)" : "")),
    ...line("Bau-Einschätzung", entry.readiness === "unbewertet" ? "" : entry.readiness_label),
    ...line("Umfang", entry.oversized ? scopeLabel : ""),
    ...line(
      "Zusage am",
      entry.promised_at
        ? moment(entry.promised_at) + (entry.promised_by ? ` (${entry.promised_by})` : "")
        : "",
    ),
    ...line(
      "Mail versendet am",
      entry.sent_at ? `${moment(entry.sent_at)} (${waiting(entry.days_since_sent)})` : "",
    ),
    ...line("Nachgefasst am", moment(entry.followed_up_at)),
    ...line("Antwort am", moment(entry.answered_at)),

    ...block("Befunde", entry.befunde),
    ...block("Anmerkung aus dem Telefonat", entry.note),
    ...block("Anmerkung zum Versand", entry.mail_note),
  ];

  if (entry.extras.length) {
    parts.push("", "Details aus der Liste:");
    for (const field of entry.extras) parts.push(`- ${field.label}: ${field.value}`);
  }

  // Die Leerzeilen stehen fest zwischen den Gruppen, die Gruppen selbst
  // können leer sein – ohne das Zusammenziehen klaffte im Text eine Lücke,
  // wo eine ganze Gruppe fehlt.
  return (
    parts
      .join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim() + "\n"
  );
}
