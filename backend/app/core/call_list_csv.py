"""CSV-Import der Anruflisten.

Das Format ist absichtlich schwach festgelegt: verlangt werden **zwei**
Spalten, „Betrieb" und „Telefon". Ohne die beiden ist eine Zeile für jemanden,
der anrufen soll, wertlos. Sieben weitere Spalten werden erkannt und bekommen
in der Oberfläche eine eigene Rolle (E-Mail, Ort, PLZ, Website, Gewerk, Prio,
Befunde), und **alles Übrige wird unverändert mitgeführt** und beim Kontakt
unter „Details" angezeigt.

Der Grund für diese Bauform steht in der Praxis: die Listen entstehen aus
Auswertungen, die sich ändern — eine Analyse mit Ladezeit und CMS-Version
heute, eine mit Umsatzklassen morgen. Eine feste Spaltenliste wäre bei jeder
neuen Auswertung eine Codeänderung, und die Spalten, die niemand vorhergesehen
hat, sind genau die, über die am Telefon geredet wird.

Kodierung, Trennzeichen und Spaltennormalisierung kommen aus `csv_import.py`,
geteilt mit dem Import der Namensschilder.

**Datenschutz:** Anruflisten sind personenbezogene Daten. Nichts hier schreibt
Feldinhalte in ein Log; auf Platte landen sie erst durch den Service, und dort
nur in der Datenbank.
"""

from dataclasses import dataclass, field

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

# Obergrenzen. Eine Anrufliste ist ein Auszug aus einer Auswertung, ein paar
# hundert Zeilen — alles darüber ist die falsche Datei.
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_ROWS = 5000
# Kurzfelder (Betrieb, Nummer, Ort …). Längeres bedeutet fast immer eine
# verrutschte Zeile.
MAX_NAME_CHARS = 200
# Freitextfelder (Befunde, Zusatzspalten). Die Befunde einer Auswertung sind
# gern zwei Sätze lang.
MAX_TEXT_CHARS = 2000

#: Erkannte Felder in der Reihenfolge, in der sie zugeordnet werden.
FIELD_NAMES = (
    "betrieb",
    "telefon",
    "email",
    "ort",
    "plz",
    "website",
    "gewerk",
    "prio",
    "befunde",
)

#: Ohne diese beiden entsteht kein Kontakt.
REQUIRED_FIELDS = ("betrieb", "telefon")

FIELD_LABELS: dict[str, str] = {
    "betrieb": "Betrieb",
    "telefon": "Telefon",
    "email": "E-Mail",
    "ort": "Ort",
    "plz": "PLZ",
    "website": "Website",
    "gewerk": "Gewerk",
    "prio": "Prio",
    "befunde": "Befunde",
}

#: Felder, für die die kurze Längengrenze gilt.
_SHORT_FIELDS = ("betrieb", "telefon", "email", "ort", "plz", "gewerk", "prio")

# Erste Übereinstimmung gewinnt, deshalb steht der eindeutige Name jeweils
# vorn: „name" ganz hinten bei `betrieb`, damit eine Datei mit „Betrieb" *und*
# „Name" das Richtige zuordnet und nicht umgekehrt.
COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "betrieb": (
        "betrieb",
        "firma",
        "firmenname",
        "unternehmen",
        "organisation",
        "organization",
        "company",
        "kunde",
        "name",
    ),
    "telefon": (
        "telefon",
        "telefonnummer",
        "telefonnr",
        "telnr",
        "tel",
        "rufnummer",
        "festnetz",
        "phone",
        "nummer",
    ),
    "email": (
        "email",
        "emailadresse",
        "mailadresse",
        "mail",
    ),
    "ort": (
        "ort",
        "stadt",
        "gemeinde",
        "city",
    ),
    "plz": (
        "plz",
        "postleitzahl",
        "postcode",
        "zip",
    ),
    "website": (
        "website",
        "webseite",
        "homepage",
        "internetseite",
        "url",
        "domain",
    ),
    "gewerk": (
        "gewerk",
        "branche",
        "gewerbe",
        "kategorie",
        "sparte",
    ),
    "prio": (
        "prio",
        "prioritaet",
        "dringlichkeit",
        "rang",
    ),
    "befunde": (
        "befunde",
        "befund",
        "aufhaenger",
        "gesprsaufhaenger",
        "argumente",
        "hinweise",
        "hinweis",
        "bemerkung",
    ),
}

#: Beispielkopfzeile für die Fehlermeldung, wenn keine Kopfzeile gefunden wird.
HEADER_EXAMPLE = "Betrieb;Telefon;Ort;E-Mail"


class CallCsvError(CsvImportError):
    """Die Datei ist als Ganzes unbrauchbar. Meldung ist für den Anwender.

    Einzelne unbrauchbare Zeilen sind *kein* Fehler dieser Klasse: sie landen
    als `SkippedRow` im Ergebnis, damit der Rest der Liste trotzdem
    abgearbeitet werden kann. Eine Liste, die wegen einer Zeile ohne Nummer
    komplett abgelehnt wird, wird von Hand nachgebessert — und dann ist sie
    nicht mehr die Datei, die in der Auswertung steht.
    """


@dataclass(frozen=True)
class CallRecord:
    """Ein Kontakt in spe.

    `line` ist die Zeilennummer in der Datei (1-basiert, Kopfzeile
    eingerechnet), damit eine Meldung auf genau die Zeile zeigen kann, die der
    Anwender in Excel vor sich hat.
    """

    line: int
    values: dict[str, str]
    #: Zusatzspalten: Originalüberschrift → Wert, in der Reihenfolge der Datei.
    extras: dict[str, str]

    def get(self, name: str) -> str:
        return self.values.get(name, "")


@dataclass(frozen=True)
class SkippedRow:
    """Eine Zeile, aus der kein Kontakt wurde — mit Grund und Zeilennummer."""

    line: int
    reason: str


@dataclass
class CallCsvResult:
    """Ergebnis des Imports, Grundlage für Trockenlauf **und** Import.

    Beide Endpunkte lesen dieselbe Datei über denselben Weg ein — der
    Trockenlauf kann also nichts melden, was der Import anders sieht.
    """

    encoding: str
    delimiter: str
    records: list[CallRecord]
    mapping: dict[str, str]
    #: Überschriften der mitgeführten Zusatzspalten, in Dateireihenfolge.
    extra_columns: list[str] = field(default_factory=list)
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

        Das ist die Zahl, die im Trockenlauf davor warnt, dass die Spalte
        „E-Mail" existiert, aber bei 80 von 104 Betrieben leer ist.
        """
        return {
            name: sum(1 for record in self.records if not record.get(name))
            for name in self.mapping
        }


def parse_csv(data: bytes) -> CallCsvResult:
    """Rohe Uploaddaten in Kontakte umwandeln.

    Wirft `CallCsvError`, wenn die Datei als Ganzes unbrauchbar ist (leer, nur
    Kopfzeile, „Betrieb" oder „Telefon" fehlt, doppelte Spaltennamen, zu groß).

    Die Übersetzung der geteilten Ausnahme passiert hier, an einer Stelle: die
    Primitiven in `csv_import` kennen die Anrufliste nicht und werfen
    `CsvImportError`, nach außen bleibt der Import eine `CallCsvError`.
    """
    try:
        return _parse_csv(data)
    except CallCsvError:
        raise
    except CsvImportError as exc:
        raise CallCsvError(str(exc)) from exc


def _parse_csv(data: bytes) -> CallCsvResult:
    if not data:
        raise CallCsvError("Die Datei ist leer. Bitte die CSV mit Daten hochladen.")

    if len(data) > MAX_FILE_BYTES:
        raise CallCsvError(
            f"Die Datei ist größer als {MAX_FILE_BYTES // (1024 * 1024)} MB. Eine "
            "Anrufliste ist reiner Text — vermutlich wurde die falsche Datei "
            "ausgewählt (eine .xlsx zum Beispiel muss in Excel erst über "
            "„Speichern unter“ als „CSV UTF-8“ exportiert werden)."
        )

    text, encoding = decode(data)
    delimiter = detect_delimiter(text)

    rows = read_rows(text, delimiter)
    header = find_header(rows, example=HEADER_EXAMPLE)
    mapping, columns, extras = _map_columns(header)

    warnings: list[str] = []
    if encoding == "cp1252":
        # Kein Fehler, aber der einzige Fall, in dem Umlaute stillschweigend
        # falsch werden können — deshalb ein Hinweis auf die Vorschau.
        warnings.append(
            "Die Datei ist nicht UTF-8, sondern Windows-1252 (cp1252). Bitte in "
            "der Vorschau prüfen, ob Umlaute richtig dargestellt sind."
        )

    records, skipped, data_rows = _read_records(rows[1:], columns, extras, start_line=2)

    if data_rows == 0:
        raise CallCsvError(
            "Die Datei enthält nur die Kopfzeile und keine Daten. Bitte eine "
            "Liste mit mindestens einem Betrieb hochladen."
        )

    if not records:
        raise CallCsvError(
            "Keine einzige Zeile hat Betrieb *und* Telefonnummer. Bitte prüfen, "
            "ob die richtigen Spalten gefüllt sind."
        )

    if len(mapping) == len(REQUIRED_FIELDS) and extras:
        # Kein Fehler: die Datei ist brauchbar. Aber wenn nur die beiden
        # Pflichtspalten erkannt wurden, ist meistens eine Überschrift
        # ungewöhnlich benannt — und dann steht die E-Mail unter „Details"
        # statt im Feld, aus dem später der Versand liest.
        warnings.append(
            "Außer „Betrieb“ und „Telefon“ wurde keine Spalte erkannt. Die "
            "übrigen Spalten werden mitgeführt und angezeigt, aber zum Beispiel "
            "eine E-Mail-Adresse landet dann nicht im E-Mail-Feld. Zuordnung "
            "unten prüfen."
        )

    return CallCsvResult(
        encoding=encoding,
        delimiter=delimiter,
        records=records,
        mapping=mapping,
        extra_columns=list(extras.keys()),
        skipped=skipped,
        warnings=warnings,
        data_rows=data_rows,
    )


def _map_columns(
    header: list[str],
) -> tuple[dict[str, str], dict[str, int], dict[str, int]]:
    """Kopfzeile auf die Felder abbilden.

    Liefert (Feld → Originalüberschrift), (Feld → Spaltenindex) und
    (Überschrift → Spaltenindex) für alles, was zu keinem Feld gehört.
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

    missing = [name for name in REQUIRED_FIELDS if name not in columns]
    if missing:
        _raise_missing(missing, normalised)

    extras = {
        entry.raw: entry.index
        for entry in normalised
        if entry.index not in used_indexes
    }

    return mapping, columns, extras


def _raise_missing(missing: list[str], normalised: list) -> None:
    """Eine Meldung, die sagt, welche Überschrift die Datei bräuchte."""
    found = ", ".join(f"„{entry.raw}“" for entry in normalised) or "keine"
    wanted = "; ".join(
        f"{FIELD_LABELS[name]} (z. B. "
        + ", ".join(f"„{synonym}“" for synonym in COLUMN_SYNONYMS[name][:3])
        + ")"
        for name in missing
    )

    raise CallCsvError(
        f"In der Datei fehlt: {wanted}. Gefunden wurden diese Spalten: {found}."
    )


def _read_records(
    rows: list[list[str]],
    columns: dict[str, int],
    extras: dict[str, int],
    start_line: int,
) -> tuple[list[CallRecord], list[SkippedRow], int]:
    """Datenzeilen einlesen; leere überspringen, unbrauchbare protokollieren."""
    records: list[CallRecord] = []
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
            raise CallCsvError(
                f"Die Datei enthält mehr als {MAX_ROWS} Zeilen. Bitte die Liste "
                "aufteilen und in mehreren Durchgängen hochladen."
            )

        values = {name: _cell(row, index).strip() for name, index in columns.items()}

        too_long = _too_long(values)
        if too_long is not None:
            skipped.append(SkippedRow(line=line, reason=too_long))
            continue

        if not values["betrieb"]:
            skipped.append(
                SkippedRow(line=line, reason="Kein Betrieb in dieser Zeile.")
            )
            continue

        if not values["telefon"]:
            skipped.append(
                SkippedRow(
                    line=line,
                    reason=f"Keine Telefonnummer bei „{values['betrieb']}“.",
                )
            )
            continue

        if not any(character.isdigit() for character in values["telefon"]):
            skipped.append(
                SkippedRow(
                    line=line,
                    reason=(
                        f"„{values['telefon']}“ enthält keine Ziffern und ist "
                        f"keine Telefonnummer ({values['betrieb']})."
                    ),
                )
            )
            continue

        # Leere Zusatzspalten werden weggelassen, nicht als leere Zeile
        # angezeigt: bei 14 Zusatzspalten wäre der Kontakt sonst zur Hälfte
        # Leerzeilen.
        record_extras = {
            label: value
            for label, index in extras.items()
            if (value := _cell(row, index).strip())
        }

        oversized = next(
            (
                label
                for label, value in record_extras.items()
                if len(value) > MAX_TEXT_CHARS
            ),
            None,
        )
        if oversized is not None:
            # Nicht stillschweigend abschneiden: eine Zelle mit 5000 Zeichen
            # ist keine Zusatzinformation, sondern eine verrutschte Zeile — und
            # gekürzt sieht sie im Kontakt aus wie ein sauberer Datensatz.
            skipped.append(
                SkippedRow(
                    line=line,
                    reason=(
                        f"Spalte „{oversized}“ ist länger als {MAX_TEXT_CHARS} "
                        f"Zeichen ({values['betrieb']}) — vermutlich ist die "
                        "Zeile verrutscht."
                    ),
                )
            )
            continue

        records.append(CallRecord(line=line, values=values, extras=record_extras))

    return records, skipped, data_rows


def _cell(row: list[str], index: int) -> str:
    return row[index] if index < len(row) else ""


def _too_long(values: dict[str, str]) -> str | None:
    """Prüft die Längengrenzen und liefert die Meldung, falls überschritten."""
    for name, value in values.items():
        limit = MAX_NAME_CHARS if name in _SHORT_FIELDS else MAX_TEXT_CHARS
        if len(value) > limit:
            return (
                f"Feld „{FIELD_LABELS[name]}“ ist länger als {limit} Zeichen — "
                "vermutlich ist die Zeile verrutscht."
            )

    return None


# --------------------------------------------------------------------------
# Blacklist-Import
# --------------------------------------------------------------------------

#: Für die Blacklist reicht die Nummer. „Betrieb" wird mitgenommen, wenn die
#: Datei ihn hat, denn eine Sperrliste aus reinen Ziffern kann später niemand
#: mehr einordnen — Pflicht ist er aber nicht: die typische Quelle ist ein
#: Auszug aus dem CRM mit einer einzigen Spalte.
BLACKLIST_REQUIRED_FIELDS = ("telefon",)

BLACKLIST_HEADER_EXAMPLE = "Telefon;Betrieb"

#: Eine Sperrliste darf deutlich länger sein als eine Anrufliste: sie wird nie
#: abtelefoniert, sondern nur nachgeschlagen.
MAX_BLACKLIST_ROWS = 50_000


@dataclass(frozen=True)
class BlacklistRecord:
    """Eine zu sperrende Nummer aus einer Datei."""

    line: int
    telefon: str
    betrieb: str


@dataclass
class BlacklistCsvResult:
    encoding: str
    delimiter: str
    records: list[BlacklistRecord]
    skipped: list[SkippedRow] = field(default_factory=list)
    data_rows: int = 0

    @property
    def encoding_label(self) -> str:
        return encoding_label(self.encoding)

    @property
    def delimiter_label(self) -> str:
        return delimiter_label(self.delimiter)


def parse_blacklist_csv(data: bytes) -> BlacklistCsvResult:
    """Eine Sperrliste einlesen — dieselben Primitiven, weniger Pflichtspalten.

    Bewusst nicht `parse_csv` mit einer Ausnahme: dort ist „Betrieb" Pflicht,
    weil ein Kontakt ohne Namen für den Anrufer wertlos ist. Für eine Sperre
    ist er es nicht.
    """
    try:
        return _parse_blacklist_csv(data)
    except CallCsvError:
        raise
    except CsvImportError as exc:
        raise CallCsvError(str(exc)) from exc


def _parse_blacklist_csv(data: bytes) -> BlacklistCsvResult:
    if not data:
        raise CallCsvError("Die Datei ist leer. Bitte die CSV mit Daten hochladen.")

    if len(data) > MAX_FILE_BYTES:
        raise CallCsvError(
            f"Die Datei ist größer als {MAX_FILE_BYTES // (1024 * 1024)} MB."
        )

    text, encoding = decode(data)
    delimiter = detect_delimiter(text)

    rows = read_rows(text, delimiter)
    header = find_header(rows, example=BLACKLIST_HEADER_EXAMPLE)
    normalised = normalised_header(header)
    reject_duplicate_columns(normalised)

    columns: dict[str, int] = {}
    used: set[int] = set()

    for field_name in ("telefon", "betrieb"):
        for synonym in COLUMN_SYNONYMS[field_name]:
            match = next(
                (
                    entry
                    for entry in normalised
                    if entry.key == synonym and entry.index not in used
                ),
                None,
            )
            if match is not None:
                columns[field_name] = match.index
                used.add(match.index)
                break

    if "telefon" not in columns:
        found = ", ".join(f"„{entry.raw}“" for entry in normalised) or "keine"
        raise CallCsvError(
            "In der Datei fehlt die Spalte mit den Telefonnummern (z. B. "
            f"„Telefon“, „Telefonnummer“, „Nummer“). Gefunden wurden: {found}."
        )

    records: list[BlacklistRecord] = []
    skipped: list[SkippedRow] = []
    data_rows = 0

    for offset, row in enumerate(rows[1:]):
        line = offset + 2

        if not any(cell.strip() for cell in row):
            continue

        data_rows += 1

        if data_rows > MAX_BLACKLIST_ROWS:
            raise CallCsvError(
                f"Die Datei enthält mehr als {MAX_BLACKLIST_ROWS} Zeilen."
            )

        telefon = _cell(row, columns["telefon"]).strip()[:MAX_NAME_CHARS]
        betrieb = (
            _cell(row, columns["betrieb"]).strip()[:MAX_NAME_CHARS]
            if "betrieb" in columns
            else ""
        )

        if not any(character.isdigit() for character in telefon):
            skipped.append(
                SkippedRow(
                    line=line,
                    reason=(
                        f"„{telefon}“ enthält keine Ziffern und ist keine "
                        "Telefonnummer."
                        if telefon
                        else "Keine Telefonnummer in dieser Zeile."
                    ),
                )
            )
            continue

        records.append(BlacklistRecord(line=line, telefon=telefon, betrieb=betrieb))

    if data_rows == 0:
        raise CallCsvError("Die Datei enthält nur die Kopfzeile und keine Nummern.")

    if not records:
        raise CallCsvError(
            "Keine einzige Zeile enthält eine Telefonnummer. Bitte prüfen, ob "
            "die richtige Spalte gefüllt ist."
        )

    return BlacklistCsvResult(
        encoding=encoding,
        delimiter=delimiter,
        records=records,
        skipped=skipped,
        data_rows=data_rows,
    )
