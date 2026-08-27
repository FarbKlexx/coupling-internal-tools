"""Was jeder CSV-Import dieser Anwendung braucht, unabhängig vom Werkzeug.

Herausgezogen aus `badge_csv.py`, als der zweite Import dazukam (die
Anrufliste, `call_list_csv.py`). Der schwierige Teil eines CSV-Uploads ist
nicht das Lesen der Zeilen, sondern alles davor: welche Kodierung, welches
Trennzeichen, welche Spalte ist gemeint. Genau dieser Teil steht hier **einmal**
— zweimal geschrieben wäre er zweimal subtil anders, und der Unterschied fiele
erst an einer Datei mit Umlauten auf.

Was hier *nicht* hingehört: Obergrenzen (eine Teilnehmerliste und eine
Anrufliste sind verschieden groß), Spaltensynonyme und alle Meldungen, die von
den Feldern eines bestimmten Werkzeugs sprechen. Die bleiben beim Werkzeug.

**Datenschutz:** nichts hier schreibt Feldinhalte in ein Log, und nichts landet
auf Platte — die Datei existiert nur als `bytes` im Speicher des Requests.
"""

import csv
import io
import re
import unicodedata

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


class CsvImportError(Exception):
    """Die Datei ist als Ganzes unbrauchbar. Meldung ist für den Anwender.

    Die Werkzeuge leiten ihre eigene Fehlerklasse hiervon ab und übersetzen
    diese Ausnahme an ihrer Aussengrenze, damit ein Aufrufer weiter genau eine
    Klasse fangen kann.
    """


class Column:
    """Eine Spalte der Kopfzeile: Position, Originaltext, Vergleichsschlüssel.

    Bewusst kein `NamedTuple` mit Indexzugriff — `column.index` liest sich an
    den Zuordnungsstellen deutlich besser als `entry[0]`.
    """

    __slots__ = ("index", "raw", "key")

    def __init__(self, index: int, raw: str, key: str) -> None:
        self.index = index
        self.raw = raw
        self.key = key

    def __repr__(self) -> str:  # pragma: no cover - Diagnose
        return f"Column({self.index}, {self.raw!r}, {self.key!r})"


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

    raise CsvImportError(
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
    header_line = first_content_line(text)

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


def first_content_line(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip():
            return line
    return None


def drop_sep_hint(rows: list[list[str]]) -> list[list[str]]:
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


def find_header(rows: list[list[str]], *, example: str) -> list[str]:
    """Erste nicht-leere Zeile als Kopfzeile.

    `example` ist die Spaltenaufzählung, die in der Fehlermeldung als Vorbild
    genannt wird — das ist das einzige werkzeugspezifische Stück hier, und es
    ist genau das Stück, das dem Anwender weiterhilft.
    """
    for row in rows:
        if any(cell.strip() for cell in row):
            return row

    raise CsvImportError(
        "Die Datei enthält keine Kopfzeile. Erwartet wird eine erste Zeile mit "
        f"den Spaltennamen, z. B. „{example}“."
    )


def normalised_header(header: list[str]) -> list[Column]:
    """Kopfzeile in vergleichbare Spalten übersetzen, Leerspalten weg.

    Leere Überschriften fallen heraus, nicht weil sie harmlos wären, sondern
    weil Excel sie an jede Datei anhängt, die einmal eine breitere Auswahl
    hatte.
    """
    columns: list[Column] = []

    for index, raw in enumerate(header):
        key = column_key(raw)
        if key:
            columns.append(Column(index, raw.strip(), key))

    return columns


def reject_duplicate_columns(columns: list[Column]) -> None:
    """Doppelte Spaltennamen sind ein Fehler, keine Warnung.

    Zwei Spalten, die auf denselben Schlüssel normalisieren, lassen sich nicht
    zuordnen, ohne zu raten — und die falsche Wahl fällt erst am fertigen
    Ergebnis auf.
    """
    seen: dict[str, str] = {}

    for column in columns:
        if column.key in seen:
            raise CsvImportError(
                f"Die Spalten „{seen[column.key]}“ und „{column.raw}“ sind nicht "
                "unterscheidbar (Groß-/Kleinschreibung, Leer- und Sonderzeichen "
                "zählen nicht). Bitte eine der beiden Spalten umbenennen oder "
                "entfernen."
            )
        seen[column.key] = column.raw


def encoding_label(encoding: str) -> str:
    return ENCODING_LABELS.get(encoding, encoding)


def delimiter_label(delimiter: str) -> str:
    return DELIMITER_LABELS.get(delimiter, delimiter)


def read_rows(text: str, delimiter: str) -> list[list[str]]:
    """Text in Zeilen zerlegen und Excels `sep=`-Vorzeile entfernen."""
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    return drop_sep_hint(rows)


__all__ = [
    "DELIMITERS",
    "DELIMITER_LABELS",
    "ENCODINGS",
    "ENCODING_LABELS",
    "UTF8_BOM",
    "Column",
    "CsvImportError",
    "column_key",
    "decode",
    "delimiter_label",
    "detect_delimiter",
    "drop_sep_hint",
    "encoding_label",
    "find_header",
    "first_content_line",
    "normalise_column",
    "normalised_header",
    "read_rows",
    "reject_duplicate_columns",
]
