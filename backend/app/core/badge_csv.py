"""CSV-Import der Teilnehmerlisten.

Die Dateien kommen aus deutschem Excel und aus allem, was die Anwender sonst
exportieren. Der Import kommt deshalb ohne Rückfrage mit Semikolon, Komma und
Tabulator zurecht, mit UTF-8 (mit und ohne BOM) und cp1252, mit Umlauten in den
Spaltenüberschriften und mit angehängten Leerzeilen.

**Datenschutz:** Teilnehmerlisten sind personenbezogene Daten. Nichts hier
schreibt Feldinhalte in ein Log, und nichts wird auf Platte geschrieben — die
Datei existiert nur als `bytes` im Speicher dieses Requests.
"""

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field

from app.core.badge_layout import FIELD_NAMES, REQUIRED_FIELD

# Obergrenzen. Eine Teilnehmerliste ist ein paar hundert Zeilen Text; alles
# darüber ist entweder die falsche Datei oder ein Export, der auseinanderfällt.
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
MAX_FIELD_CHARS = 120

# Reihenfolge ist entscheidend: cp1252 akzeptiert fast jedes Byte und würde
# UTF-8-Dateien klaglos als Mojibake einlesen ("Müller"). Deshalb steht es
# hinten und kommt nur zum Zug, wenn UTF-8 die Datei wirklich nicht dekodiert.
ENCODINGS = ("utf-8-sig", "utf-8", "cp1252")

UTF8_BOM = b"\xef\xbb\xbf"

# Semikolon zuerst: deutsches Excel schreibt es, und es kommt in Namen und
# Firmenbezeichnungen praktisch nie vor.
DELIMITERS = (";", ",", "\t")

DELIMITER_LABELS = {";": "Semikolon", ",": "Komma", "\t": "Tabulator"}

ENCODING_LABELS = {
    "utf-8-sig": "UTF-8 (mit BOM)",
    "utf-8": "UTF-8",
    "cp1252": "cp1252 (Windows-1252)",
}

# Excel schreibt manchen Exporten eine Zeile "sep=;" voran, damit es sie selbst
# wieder öffnen kann. Sie ist keine Kopfzeile.
_SEP_HINT = re.compile(r"^sep=(.)\s*$", re.IGNORECASE)

# Umlaute werden **ausgeschrieben**, nicht verworfen: "Größe" und "Grose" wären
# sonst dieselbe normalisierte Spalte, und aus zwei verschiedenen Spalten würde
# ein Duplikat-Fehler oder — schlimmer — eine stille Zuordnung zur falschen.
_UMLAUTS = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
    "æ": "ae",
    "ø": "oe",
    "å": "aa",
}

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


class BadgeCsvError(Exception):
    """Der Import kann nicht fortgesetzt werden. Meldung ist für den Anwender.

    Jede Meldung sagt, was zu tun ist — nicht nur, dass etwas fehlgeschlagen
    ist. Zeilenbezogene Probleme sind *kein* Fehler dieser Klasse: sie landen
    als `SkippedRow` im Ergebnis, damit der Rest der Liste trotzdem gedruckt
    werden kann.
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
        return ENCODING_LABELS.get(self.encoding, self.encoding)

    @property
    def delimiter_label(self) -> str:
        return DELIMITER_LABELS.get(self.delimiter, self.delimiter)

    def empty_field_counts(self) -> dict[str, int]:
        """Wie oft ein zugeordnetes Feld leer bleibt — pro Feld.

        Das ist die Zahl, die im Trockenlauf davor warnt, dass auf 40 Karten
        die Funktion fehlt, obwohl die Spalte existiert.
        """
        return {
            name: sum(1 for record in self.records if not record.get(name))
            for name in self.mapping
        }


def normalise_column(name: str) -> str:
    """Spaltenüberschrift auf einen Vergleichsschlüssel bringen.

    "Nach­name (lt. Ausweis)" → "nachname_lt_ausweis". Umlaute werden
    ausgeschrieben, übrige Akzente auf den Grundbuchstaben reduziert, alles
    andere zu Unterstrichen.
    """
    text = name.strip().lower()
    text = "".join(_UMLAUTS.get(character, character) for character in text)
    # Erst nach dem Ausschreiben: sonst würde "ü" hier zu "u" und die
    # Unterscheidung zwischen "Buero" und "Büro" ginge verloren.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def column_key(name: str) -> str:
    """Vergleichsschlüssel einer Spalte — Normalisierung ohne Trennzeichen.

    "Nach-Name!", "Nach Name" und "nachname" sind dieselbe Spalte. Genau
    deshalb sind sie auch untereinander Duplikate: nebeneinander in einer Datei
    ließen sie sich nicht auseinanderhalten.
    """
    return normalise_column(name).replace("_", "")


def decode(data: bytes) -> tuple[str, str]:
    """Dateiinhalt dekodieren, Ergebnis plus erkannte Kodierung.

    Reihenfolge siehe `ENCODINGS`.
    """
    if data.startswith(UTF8_BOM):
        candidates: tuple[str, ...] = ("utf-8-sig",)
    else:
        candidates = tuple(name for name in ENCODINGS if name != "utf-8-sig")

    for encoding in candidates:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue

    raise BadgeCsvError(
        "Die Datei ist weder UTF-8 noch Windows-1252 (cp1252). Bitte in Excel "
        "über „Speichern unter“ als „CSV UTF-8 (durch Trennzeichen getrennt)“ "
        "exportieren."
    )


def detect_delimiter(text: str) -> str:
    """Trennzeichen aus der Kopfzeile bestimmen.

    Bewusst kein `csv.Sniffer`: der wirft bei einspaltigen Dateien eine
    Ausnahme, und genau die kommen vor (eine Spalte "Nachname"). Hier gewinnt
    das Zeichen, das die meisten Spalten ergibt; ergibt keines mehr als eine
    Spalte, ist die Datei einspaltig und das Trennzeichen egal.
    """
    header_line = _first_content_line(text)

    if header_line is None:
        return DELIMITERS[0]

    hint = _SEP_HINT.match(header_line)
    if hint and hint.group(1) in DELIMITERS:
        return hint.group(1)

    best = DELIMITERS[0]
    best_columns = 1

    for delimiter in DELIMITERS:
        columns = len(next(csv.reader([header_line], delimiter=delimiter), []))
        if columns > best_columns:
            best, best_columns = delimiter, columns

    return best


def _first_content_line(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip():
            return line
    return None


def parse_csv(data: bytes) -> CsvParseResult:
    """Rohe Uploaddaten in Datensätze für die Karten umwandeln.

    Wirft `BadgeCsvError`, wenn die Datei als Ganzes unbrauchbar ist (leer, nur
    Kopfzeile, Nachname-Spalte fehlt, doppelte Spaltennamen, zu groß). Einzelne
    unbrauchbare Zeilen führen dagegen nur zu einem Eintrag in `skipped`.
    """
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

    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    rows = _drop_sep_hint(rows)

    header = _find_header(rows)
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


def _drop_sep_hint(rows: list[list[str]]) -> list[list[str]]:
    """Excels "sep=;"-Vorzeile entfernen, falls vorhanden.

    Sie wird mit genau dem Trennzeichen gelesen, das sie ankündigt, und
    zerfällt dabei selbst in mehrere Zellen ("sep=" + leer). Erkannt wird sie
    deshalb an der ersten Zelle, nicht an der Länge der Zeile.
    """
    if not rows:
        return rows

    first = rows[0][0].strip() if rows[0] else ""
    rest_is_empty = all(not cell.strip() for cell in rows[0][1:])

    if rest_is_empty and (first.lower() == "sep=" or _SEP_HINT.match(first)):
        return rows[1:]

    return rows


def _find_header(rows: list[list[str]]) -> list[str]:
    """Erste nicht-leere Zeile als Kopfzeile."""
    for row in rows:
        if any(cell.strip() for cell in row):
            return row

    raise BadgeCsvError(
        "Die Datei enthält keine Kopfzeile. Erwartet wird eine erste Zeile mit "
        "den Spaltennamen, z. B. „Vorname;Nachname;Funktion;Firma“."
    )


def _map_columns(
    header: list[str],
) -> tuple[dict[str, str], dict[str, int], list[str]]:
    """Kopfzeile auf die Kartenfelder abbilden.

    Liefert (Feld → Originalüberschrift), (Feld → Spaltenindex) und die
    Überschriften, die zu keinem Kartenfeld gehören.
    """
    normalised: list[tuple[int, str, str]] = []
    for index, raw in enumerate(header):
        key = column_key(raw)
        if key:
            normalised.append((index, raw.strip(), key))

    _reject_duplicates(normalised)

    mapping: dict[str, str] = {}
    columns: dict[str, int] = {}
    used_indexes: set[int] = set()

    for field_name in FIELD_NAMES:
        for synonym in COLUMN_SYNONYMS[field_name]:
            match = next(
                (
                    entry
                    for entry in normalised
                    if entry[2] == synonym and entry[0] not in used_indexes
                ),
                None,
            )
            if match is not None:
                index, raw, _ = match
                mapping[field_name] = raw
                columns[field_name] = index
                used_indexes.add(index)
                break

    if REQUIRED_FIELD not in columns:
        found = ", ".join(f"„{entry[1]}“" for entry in normalised) or "keine"
        expected = ", ".join(
            f"„{synonym}“" for synonym in COLUMN_SYNONYMS[REQUIRED_FIELD][:4]
        )
        raise BadgeCsvError(
            "Die Datei hat keine Spalte für den Nachnamen. Erwartet wird eine "
            f"Spalte mit einer dieser Überschriften: {expected}. "
            f"Gefunden wurden: {found}."
        )

    ignored = [entry[1] for entry in normalised if entry[0] not in used_indexes]

    return mapping, columns, ignored


def _reject_duplicates(normalised: list[tuple[int, str, str]]) -> None:
    """Doppelte Spaltennamen sind ein Fehler, keine Warnung.

    Zwei Spalten, die auf denselben Schlüssel normalisieren, lassen sich nicht
    zuordnen, ohne zu raten — und die falsche Wahl fällt erst auf dem
    fertigen Bogen auf.
    """
    seen: dict[str, str] = {}
    for _, raw, key in normalised:
        if key in seen:
            raise BadgeCsvError(
                f"Die Spalten „{seen[key]}“ und „{raw}“ sind nicht "
                "unterscheidbar (Groß-/Kleinschreibung, Leer- und Sonderzeichen "
                "zählen nicht). Bitte eine der beiden Spalten umbenennen oder "
                "entfernen."
            )
        seen[key] = raw


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
