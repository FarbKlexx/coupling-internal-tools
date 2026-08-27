"""CSV-Import der Teilnehmerlisten.

Die Dateien kommen aus deutschem Excel und aus allem, was die Anwender sonst
exportieren. Der Import kommt deshalb ohne Rückfrage mit Semikolon, Komma und
Tabulator zurecht, mit UTF-8 (mit und ohne BOM) und cp1252, mit Umlauten in den
Spaltenüberschriften und mit angehängten Leerzeilen.

Die Primitiven dahinter — Kodierung, Trennzeichen, Spaltennormalisierung —
stehen in `csv_import.py` und werden mit der Anrufliste geteilt. Hier bleibt,
was die Teilnehmerliste eigen hat: die Spaltensynonyme, die Obergrenzen und
jede Meldung, die von Vor- und Nachnamen spricht.

**Datenschutz:** Teilnehmerlisten sind personenbezogene Daten. Nichts hier
schreibt Feldinhalte in ein Log, und nichts wird auf Platte geschrieben — die
Datei existiert nur als `bytes` im Speicher dieses Requests.
"""

from dataclasses import dataclass, field

from app.core.badge_layout import FIELD_NAMES, REQUIRED_FIELD
from app.core.csv_import import (
    CsvImportError,
    decode,
    delimiter_label,
    detect_delimiter,
    encoding_label,
    find_header,
    normalised_header,
    read_rows,
    reject_duplicate_columns,
)

# Obergrenzen. Eine Teilnehmerliste ist ein paar hundert Zeilen Text; alles
# darüber ist entweder die falsche Datei oder ein Export, der auseinanderfällt.
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
MAX_FIELD_CHARS = 120

# Erste Übereinstimmung gewinnt, deshalb steht der eindeutige Name jeweils
# vorn: eine Datei mit "Nachname" und "Name" ordnet "Nachname" zu und lässt
# "Name" unbenutzt, nicht umgekehrt.
COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "nachname": (
        "nachname",
        "familienname",
        "zuname",
        "last_name",
        "lastname",
        "surname",
        "name",
    ),
    "vorname": (
        "vorname",
        "rufname",
        "first_name",
        "firstname",
        "given_name",
        "givenname",
    ),
    "funktion": (
        "funktion",
        "position",
        "rolle",
        "jobtitel",
        "job_title",
        "jobtitle",
        "taetigkeit",
        "role",
        "function",
        "titel",
    ),
    "firma": (
        "firma",
        "unternehmen",
        "organisation",
        "organization",
        "company",
        "betrieb",
        "institution",
    ),
}


class BadgeCsvError(CsvImportError):
    """Der Import kann nicht fortgesetzt werden. Meldung ist für den Anwender.

    Jede Meldung sagt, was zu tun ist — nicht nur, dass etwas fehlgeschlagen
    ist. Zeilenbezogene Probleme sind *kein* Fehler dieser Klasse: sie landen
    als `SkippedRow` im Ergebnis, damit der Rest der Liste trotzdem gedruckt
    werden kann.

    Erbt von `CsvImportError`, weil die geteilten Primitiven jene Klasse
    werfen; `parse_csv` übersetzt sie an der Aussengrenze, damit ein Aufrufer
    weiter genau `BadgeCsvError` fangen kann.
    """


@dataclass(frozen=True)
class BadgeRecord:
    """Eine Karte in spe: die Feldwerte einer CSV-Zeile.

    `line` ist die Zeilennummer in der Datei (1-basiert, Kopfzeile
    eingerechnet), damit das Frontend auf genau die Zeile zeigen kann, die der
    Anwender in Excel vor sich hat.
    """

    line: int
    values: dict[str, str]

    def get(self, name: str) -> str:
        return self.values.get(name, "")


@dataclass(frozen=True)
class SkippedRow:
    """Eine Zeile, aus der keine Karte wurde — mit Grund und Zeilennummer."""

    line: int
    reason: str


@dataclass
class CsvParseResult:
    """Ergebnis des Imports, Grundlage für Trockenlauf **und** Druck.

    Beide Endpunkte lesen dieselbe Datei über denselben Weg ein — der
    Trockenlauf kann also nichts melden, was der Druck anders sieht.
    """

    encoding: str
    delimiter: str
    records: list[BadgeRecord]
    mapping: dict[str, str]
    ignored_columns: list[str] = field(default_factory=list)
    skipped: list[SkippedRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data_rows: int = 0

    @property
    def encoding_label(self) -> str:
        return encoding_label(self.encoding)

    @property
    def delimiter_label(self) -> str:
        return delimiter_label(self.delimiter)

    def empty_field_counts(self) -> dict[str, int]:
        """Wie oft ein zugeordnetes Feld leer bleibt — pro Feld.

        Das ist die Zahl, die im Trockenlauf davor warnt, dass auf 40 Karten
        die Funktion fehlt, obwohl die Spalte existiert.
        """
        return {
            name: sum(1 for record in self.records if not record.get(name))
            for name in self.mapping
        }


def parse_csv(data: bytes) -> CsvParseResult:
    """Rohe Uploaddaten in Datensätze für die Karten umwandeln.

    Wirft `BadgeCsvError`, wenn die Datei als Ganzes unbrauchbar ist (leer, nur
    Kopfzeile, Nachname-Spalte fehlt, doppelte Spaltennamen, zu groß). Einzelne
    unbrauchbare Zeilen führen dagegen nur zu einem Eintrag in `skipped`.

    Die Übersetzung der geteilten Ausnahme passiert hier, an einer Stelle: die
    Primitiven in `csv_import` kennen die Teilnehmerliste nicht und werfen
    `CsvImportError`, nach außen bleibt der Import aber eine `BadgeCsvError`.
    """
    try:
        return _parse_csv(data)
    except BadgeCsvError:
        raise
    except CsvImportError as exc:
        raise BadgeCsvError(str(exc)) from exc


def _parse_csv(data: bytes) -> CsvParseResult:
    if not data:
        raise BadgeCsvError("Die Datei ist leer. Bitte die CSV mit Daten hochladen.")

    if len(data) > MAX_FILE_BYTES:
        raise BadgeCsvError(
            f"Die Datei ist größer als "
            f"{MAX_FILE_BYTES // (1024 * 1024)} MB. Eine Teilnehmerliste ist "
            "reiner Text — vermutlich wurde die falsche Datei ausgewählt."
        )

    text, encoding = decode(data)
    delimiter = detect_delimiter(text)

    rows = read_rows(text, delimiter)

    header = find_header(rows, example="Vorname;Nachname;Funktion;Firma")
    mapping, columns, ignored = _map_columns(header)

    warnings: list[str] = []
    if encoding == "cp1252":
        # Kein Fehler, aber der einzige Fall, in dem Umlaute stillschweigend
        # falsch werden können — deshalb ein Hinweis auf die Vorschau.
        warnings.append(
            "Die Datei ist nicht UTF-8, sondern Windows-1252 (cp1252). Bitte in "
            "der Vorschau prüfen, ob Umlaute richtig dargestellt sind."
        )

    records, skipped, data_rows = _read_records(rows[1:], columns, start_line=2)

    if data_rows == 0:
        raise BadgeCsvError(
            "Die Datei enthält nur die Kopfzeile und keine Daten. Bitte eine "
            "Liste mit mindestens einer Person hochladen."
        )

    result = CsvParseResult(
        encoding=encoding,
        delimiter=delimiter,
        records=records,
        mapping=mapping,
        ignored_columns=ignored,
        skipped=skipped,
        warnings=warnings,
        data_rows=data_rows,
    )

    if not records:
        raise BadgeCsvError(
            "Keine einzige Zeile hat einen Nachnamen. Bitte prüfen, ob die "
            "richtige Spalte gefüllt ist."
        )

    return result


def _map_columns(
    header: list[str],
) -> tuple[dict[str, str], dict[str, int], list[str]]:
    """Kopfzeile auf die Kartenfelder abbilden.

    Liefert (Feld → Originalüberschrift), (Feld → Spaltenindex) und die
    Überschriften, die zu keinem Kartenfeld gehören.
    """
    normalised = normalised_header(header)
    reject_duplicate_columns(normalised)

    mapping: dict[str, str] = {}
    columns: dict[str, int] = {}
    used_indexes: set[int] = set()

    for field_name in FIELD_NAMES:
        for synonym in COLUMN_SYNONYMS[field_name]:
            match = next(
                (
                    entry
                    for entry in normalised
                    if entry.key == synonym and entry.index not in used_indexes
                ),
                None,
            )
            if match is not None:
                mapping[field_name] = match.raw
                columns[field_name] = match.index
                used_indexes.add(match.index)
                break

    if REQUIRED_FIELD not in columns:
        found = ", ".join(f"„{entry.raw}“" for entry in normalised) or "keine"
        expected = ", ".join(
            f"„{synonym}“" for synonym in COLUMN_SYNONYMS[REQUIRED_FIELD][:4]
        )
        raise BadgeCsvError(
            "Die Datei hat keine Spalte für den Nachnamen. Erwartet wird eine "
            f"Spalte mit einer dieser Überschriften: {expected}. "
            f"Gefunden wurden: {found}."
        )

    ignored = [entry.raw for entry in normalised if entry.index not in used_indexes]

    return mapping, columns, ignored


def _read_records(
    rows: list[list[str]],
    columns: dict[str, int],
    start_line: int,
) -> tuple[list[BadgeRecord], list[SkippedRow], int]:
    """Datenzeilen einlesen; leere überspringen, fehlerhafte protokollieren."""
    records: list[BadgeRecord] = []
    skipped: list[SkippedRow] = []
    data_rows = 0

    for offset, row in enumerate(rows):
        line = start_line + offset

        # Angehängte Leerzeilen sind der Normalfall bei Excel-Exporten und
        # werden still übergangen — sie sind kein Fehler des Anwenders.
        if not any(cell.strip() for cell in row):
            continue

        data_rows += 1

        if data_rows > MAX_ROWS:
            raise BadgeCsvError(
                f"Die Datei enthält mehr als {MAX_ROWS} Zeilen. Bitte die Liste "
                "aufteilen und die Bögen in mehreren Durchgängen drucken."
            )

        values = {
            name: row[index].strip() if index < len(row) else ""
            for name, index in columns.items()
        }

        too_long = next(
            (name for name, value in values.items() if len(value) > MAX_FIELD_CHARS),
            None,
        )
        if too_long is not None:
            skipped.append(
                SkippedRow(
                    line=line,
                    reason=(
                        f"Feld „{too_long}“ ist länger als {MAX_FIELD_CHARS} "
                        "Zeichen — vermutlich ist die Zeile verrutscht."
                    ),
                )
            )
            continue

        if not values.get(REQUIRED_FIELD):
            skipped.append(SkippedRow(line=line, reason="Kein Nachname in der Zeile."))
            continue

        records.append(BadgeRecord(line=line, values=values))

    return records, skipped, data_rows
