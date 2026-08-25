"""Robustheit des CSV-Imports.

Die Dateien kommen aus deutschem Excel, aus Google Sheets, aus einem
Veranstaltungsportal — und manchmal aus einem Texteditor. Getestet wird
deshalb nicht der glückliche Pfad, sondern das, was tatsächlich hochgeladen
wird.
"""

import pytest

from app.core.badge_csv import (
    MAX_FIELD_CHARS,
    MAX_FILE_BYTES,
    MAX_ROWS,
    BadgeCsvError,
    column_key,
    decode,
    detect_delimiter,
    normalise_column,
    parse_csv,
)

GERMAN_EXCEL = (
    "Vorname;Nachname;Funktion;Firma\r\n"
    "Anna;Müller;Geschäftsführerin;Coupling Media\r\n"
)


def _names(result) -> list[str]:
    return [record.get("nachname") for record in result.records]


# ------------------------------
# Kodierung
# ------------------------------


def test_german_excel_export_cp1252():
    """Der Normalfall: Semikolon, CRLF, cp1252."""
    result = parse_csv(GERMAN_EXCEL.encode("cp1252"))

    assert result.encoding == "cp1252"
    assert result.delimiter == ";"
    assert _names(result) == ["Müller"]
    assert result.records[0].get("funktion") == "Geschäftsführerin"


def test_utf8_with_bom():
    result = parse_csv(GERMAN_EXCEL.encode("utf-8-sig"))

    assert result.encoding == "utf-8-sig"
    assert result.encoding_label == "UTF-8 (mit BOM)"
    # Das BOM darf nicht im ersten Spaltennamen landen.
    assert result.mapping["vorname"] == "Vorname"
    assert _names(result) == ["Müller"]


def test_utf8_without_bom():
    result = parse_csv(GERMAN_EXCEL.encode("utf-8"))

    assert result.encoding == "utf-8"
    assert _names(result) == ["Müller"]


def test_utf8_is_tried_before_cp1252():
    """Sonst liest cp1252 jede UTF-8-Datei klaglos als Mojibake ein.

    cp1252 hat für fast jedes Byte ein Zeichen — stünde es vorn, käme aus
    "Müller" ein "MÃ¼ller", und niemand würde es vor dem Druck merken.
    """
    text, encoding = decode("Nachname\nMüller\n".encode("utf-8"))

    assert encoding == "utf-8"
    assert "Müller" in text
    assert "Ã" not in text


def test_undecodable_file_explains_the_way_out():
    with pytest.raises(BadgeCsvError, match="CSV UTF-8"):
        parse_csv(b"Nachname\n\x81\x8d\x90ung\xfcltig\n")


# ------------------------------
# Trennzeichen
# ------------------------------


@pytest.mark.parametrize("delimiter", [";", ",", "\t"])
def test_all_three_delimiters(delimiter):
    header = delimiter.join(["Vorname", "Nachname", "Funktion"])
    row = delimiter.join(["Anna", "Müller", "CEO"])
    result = parse_csv(f"{header}\n{row}\n".encode())

    assert result.delimiter == delimiter
    assert result.records[0].get("funktion") == "CEO"


def test_single_column_file():
    """Einspaltige Dateien lassen `csv.Sniffer` scheitern — hier nicht."""
    result = parse_csv("Nachname\nMüller\nSchmidt\n".encode())

    assert _names(result) == ["Müller", "Schmidt"]
    assert result.mapping == {"nachname": "Nachname"}


def test_semicolon_wins_over_a_comma_inside_a_field():
    result = parse_csv("Nachname;Firma\nMüller;Meier, Schulz & Partner\n".encode())

    assert result.delimiter == ";"
    assert result.records[0].get("firma") == "Meier, Schulz & Partner"


def test_excel_sep_hint_line_is_not_a_header():
    result = parse_csv("sep=;\nVorname;Nachname\nAnna;Müller\n".encode())

    assert result.delimiter == ";"
    assert result.mapping["nachname"] == "Nachname"
    assert _names(result) == ["Müller"]


def test_detect_delimiter_falls_back_for_empty_text():
    assert detect_delimiter("") == ";"


# ------------------------------
# Spaltennamen
# ------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Nachname", "nachname"),
        ("  NACHNAME  ", "nachname"),
        ("Nachname (lt. Ausweis)", "nachname_lt_ausweis"),
        ("Funktion / Rolle", "funktion_rolle"),
        ("Größe", "groesse"),
        ("Straße", "strasse"),
        ("Café", "cafe"),
    ],
)
def test_column_normalisation(raw, expected):
    assert normalise_column(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Nachname", "nachname"),
        ("Nach-Name!", "nachname"),
        ("Nach Name", "nachname"),
        ("NACH_NAME", "nachname"),
    ],
)
def test_column_key_ignores_separators(raw, expected):
    assert column_key(raw) == expected


def test_umlauts_are_written_out_not_dropped():
    """Sonst kollidieren verschiedene Spalten miteinander.

    Würde "ü" einfach entfallen oder zu "u" werden, hätten "Büro" und "Buro"
    denselben Schlüssel — und zwei verschiedene Spalten wären nicht mehr
    unterscheidbar.
    """
    assert normalise_column("Büro") == "buero"
    assert normalise_column("Büro") != normalise_column("Buro")
    assert normalise_column("Fußball") == "fussball"


def test_columns_with_spaces_and_special_characters_still_map():
    result = parse_csv("  Vor Name ;Nach-Name!;Tätigkeit\nAnna;Müller;CEO\n".encode())

    assert result.mapping["nachname"] == "Nach-Name!"
    assert result.records[0].get("funktion") == "CEO"


def test_duplicate_columns_are_an_error_not_a_warning():
    """ "Nachname" und "nach name" normalisieren auf denselben Schlüssel."""
    with pytest.raises(BadgeCsvError, match="nicht unterscheidbar"):
        parse_csv("Nachname;nach name\nMüller;Schmidt\n".encode())


def test_duplicate_error_names_both_columns():
    with pytest.raises(BadgeCsvError) as error:
        parse_csv("Nachname;NACHNAME\nMüller;Schmidt\n".encode())

    assert "„Nachname“" in str(error.value)
    assert "„NACHNAME“" in str(error.value)


def test_explicit_surname_column_wins_over_the_generic_name_column():
    result = parse_csv("Name;Nachname\nEgal;Müller\n".encode())

    assert result.mapping["nachname"] == "Nachname"
    assert "Name" in result.ignored_columns


def test_generic_name_column_is_used_when_there_is_nothing_better():
    result = parse_csv("Name\nMüller\n".encode())

    assert result.mapping["nachname"] == "Name"


def test_unknown_columns_are_ignored_and_reported():
    result = parse_csv("Nachname;E-Mail;Tischnummer\nMüller;a@b.de;7\n".encode())

    assert result.ignored_columns == ["E-Mail", "Tischnummer"]
    assert result.records[0].values == {"nachname": "Müller"}


def test_missing_surname_column_says_what_is_expected():
    with pytest.raises(BadgeCsvError, match="keine Spalte für den Nachnamen"):
        parse_csv("Vorname;Firma\nAnna;Coupling\n".encode())


# ------------------------------
# Zeilen
# ------------------------------


def test_trailing_empty_lines_are_ignored():
    result = parse_csv("Nachname\nMüller\n\n\n;\n\n".encode())

    assert _names(result) == ["Müller"]
    assert result.data_rows == 1
    assert result.skipped == []


def test_rows_without_a_surname_are_skipped_and_listed_with_their_line_number():
    data = "Vorname;Nachname\nAnna;Müller\nOhne;\nBert;Schmidt\n".encode()

    result = parse_csv(data)

    assert _names(result) == ["Müller", "Schmidt"]
    assert [(row.line, row.reason) for row in result.skipped] == [
        (3, "Kein Nachname in der Zeile.")
    ]


def test_line_numbers_match_the_file_including_the_header():
    data = "Nachname\n\nMüller\n\nSchmidt\n".encode()

    result = parse_csv(data)

    assert [record.line for record in result.records] == [3, 5]


def test_short_rows_leave_the_missing_fields_empty():
    """Excel schneidet leere Felder am Zeilenende gerne ab."""
    result = parse_csv("Vorname;Nachname;Funktion\nAnna;Müller\n".encode())

    assert result.records[0].get("funktion") == ""


def test_values_are_trimmed():
    result = parse_csv("Nachname\n  Müller  \n".encode())

    assert _names(result) == ["Müller"]


def test_empty_field_counts_feed_the_dry_run():
    data = "Vorname;Nachname\n;Müller\nBert;Schmidt\n".encode()

    assert parse_csv(data).empty_field_counts() == {"vorname": 1, "nachname": 0}


def test_cp1252_produces_a_warning_about_the_preview():
    result = parse_csv(GERMAN_EXCEL.encode("cp1252"))

    assert any("Windows-1252" in warning for warning in result.warnings)


# ------------------------------
# Leere und unbrauchbare Dateien
# ------------------------------


def test_empty_file():
    with pytest.raises(BadgeCsvError, match="Datei ist leer"):
        parse_csv(b"")


def test_header_only():
    with pytest.raises(BadgeCsvError, match="nur die Kopfzeile"):
        parse_csv("Vorname;Nachname;Funktion\n".encode())


def test_header_only_with_trailing_empty_lines():
    with pytest.raises(BadgeCsvError, match="nur die Kopfzeile"):
        parse_csv("Vorname;Nachname\n\n\n\n".encode())


def test_file_without_a_single_surname():
    with pytest.raises(BadgeCsvError, match="Keine einzige Zeile"):
        parse_csv("Vorname;Nachname\nAnna;\nBert;\n".encode())


# ------------------------------
# Obergrenzen
# ------------------------------


def test_file_size_limit():
    oversized = b"Nachname\n" + b"M" * (MAX_FILE_BYTES + 1)

    with pytest.raises(BadgeCsvError, match="MB"):
        parse_csv(oversized)


def test_row_limit():
    data = "Nachname\n" + "Müller\n" * (MAX_ROWS + 1)

    with pytest.raises(BadgeCsvError, match=str(MAX_ROWS)):
        parse_csv(data.encode())


def test_row_limit_is_not_hit_one_row_early():
    data = "Nachname\n" + "Müller\n" * MAX_ROWS

    assert len(parse_csv(data.encode()).records) == MAX_ROWS


def test_overlong_field_skips_the_row_instead_of_the_file():
    data = f"Nachname;Firma\nMüller;{'X' * (MAX_FIELD_CHARS + 1)}\nSchmidt;Kurz\n"

    result = parse_csv(data.encode())

    assert _names(result) == ["Schmidt"]
    assert result.skipped[0].line == 2
    assert "länger als" in result.skipped[0].reason
