"""Der CSV-Import der Anruflisten.

Getestet wird an dem, was tatsächlich hochgeladen wird: der Auswertung mit 23
Spalten, von denen neun erkannt werden und vierzehn nur mitfahren — und den
Zeilen, bei denen jemand die Nummer vergessen hat.
"""

import pytest

from app.core.call_list_csv import (
    MAX_ROWS,
    MAX_TEXT_CHARS,
    CallCsvError,
    parse_csv,
)

# Die Kopfzeile der Beispieldatei (Blatt „Redesign-Bedarf"), Semikolon wie aus
# deutschem Excel.
ANALYSE_HEADER = (
    "Punkte;Prio;Gewerk;Betrieb;Ort;Bauhandwerk;E-Mail;PLZ;Telefon;Website;"
    "Bewertung;Anzahl_Bewertungen;Befunde;Handpruefung;CMS;Design-Technik;"
    "Online seit (Archiv);Handy-Layout;Ladezeit ms;Gewicht KB;Screenshot;"
    "Status;Ziel-URL nach Weiterleitung"
)

ANALYSE_ROW = (
    "11;A - dringend;Maler;Azmanlar Tayfun Malermeister;Enger;ja;"
    "info@tayfun-design.de;32130;+49 5224 79473;http://tayfun-design.de/;;;"
    "kein HTTPS +3 | Copyright 2010 +3;keine Media-Queries;WordPress 5.8;"
    "2010 (jQuery 1.4);2004;passt;637;232;screenshots/0008.png;200;"
    "http://www.tayfun-design.de/"
)


def _csv(*lines: str) -> bytes:
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


# ------------------------------
# Die beiden Pflichtspalten
# ------------------------------


def test_two_columns_are_enough():
    """Betrieb und Telefon — mehr verlangt das Format nicht."""
    result = parse_csv(_csv("Betrieb;Telefon", "Zaunbau Müller;05221 12345"))

    assert len(result.records) == 1
    assert result.records[0].get("betrieb") == "Zaunbau Müller"
    assert result.records[0].get("telefon") == "05221 12345"
    assert result.records[0].extras == {}


def test_a_missing_phone_column_names_what_the_file_needs():
    with pytest.raises(CallCsvError) as error:
        parse_csv(_csv("Betrieb;Ort", "Zaunbau Müller;Herford"))

    message = str(error.value)
    assert "Telefon" in message
    # Die Meldung soll beides sagen: was fehlt und was gefunden wurde.
    assert "„Betrieb“" in message and "„Ort“" in message


def test_a_missing_company_column_is_an_error_too():
    with pytest.raises(CallCsvError, match="Betrieb"):
        parse_csv(_csv("Telefon;Ort", "05221 12345;Herford"))


# ------------------------------
# Spaltenzuordnung
# ------------------------------


def test_synonyms_are_recognised():
    result = parse_csv(_csv("Firma;Tel;Mailadresse", "Dachbau GmbH;0521 1;a@b.de"))

    assert result.mapping["betrieb"] == "Firma"
    assert result.mapping["telefon"] == "Tel"
    assert result.mapping["email"] == "Mailadresse"
    assert result.records[0].get("email") == "a@b.de"


def test_an_explicit_company_column_wins_over_the_generic_name_column():
    """Sonst landet in „Betrieb" der Name des Inhabers."""
    result = parse_csv(_csv("Name;Betrieb;Telefon", "Meier;Dachbau GmbH;0521 1"))

    assert result.mapping["betrieb"] == "Betrieb"
    assert result.records[0].get("betrieb") == "Dachbau GmbH"
    # „Name" bleibt übrig und fährt als Zusatzspalte mit, statt zu verschwinden.
    assert result.records[0].extras == {"Name": "Meier"}


def test_the_full_analysis_sheet_maps_nine_fields_and_carries_the_rest():
    result = parse_csv(_csv(ANALYSE_HEADER, ANALYSE_ROW))

    assert set(result.mapping) == {
        "betrieb",
        "telefon",
        "email",
        "ort",
        "plz",
        "website",
        "gewerk",
        "prio",
        "befunde",
    }

    record = result.records[0]
    assert record.get("gewerk") == "Maler"
    assert record.get("prio") == "A - dringend"
    assert record.get("befunde").startswith("kein HTTPS")

    # Die Zusatzspalten behalten die Reihenfolge der Datei — sie werden in
    # dieser Reihenfolge unter „Details" angezeigt.
    assert list(record.extras) == [
        "Punkte",
        "Bauhandwerk",
        "Handpruefung",
        "CMS",
        "Design-Technik",
        "Online seit (Archiv)",
        "Handy-Layout",
        "Ladezeit ms",
        "Gewicht KB",
        "Screenshot",
        "Status",
        "Ziel-URL nach Weiterleitung",
    ]
    # Leere Zusatzspalten fallen weg: „Bewertung" und „Anzahl_Bewertungen"
    # stehen in dieser Zeile nicht drin.
    assert "Bewertung" not in record.extras


def test_only_the_required_columns_recognised_is_a_warning_not_an_error():
    result = parse_csv(_csv("Betrieb;Telefon;Postfach", "Bau AG;0521 1;irgendwas"))

    assert len(result.records) == 1
    assert any("E-Mail" in warning for warning in result.warnings)


def test_duplicate_columns_are_an_error():
    """„Telefon" und „tele fon" normalisieren auf denselben Schlüssel."""
    with pytest.raises(CallCsvError, match="nicht unterscheidbar"):
        parse_csv(_csv("Betrieb;Telefon;tele fon", "Bau AG;0521 1;0521 2"))


# ------------------------------
# Zeilen, die nicht taugen
# ------------------------------


def test_a_row_without_a_phone_number_is_skipped_with_its_line_number():
    result = parse_csv(
        _csv(
            "Betrieb;Telefon",
            "Mit Nummer;0521 1",
            "Ohne Nummer;",
            "Auch mit;0521 2",
        )
    )

    assert [record.get("betrieb") for record in result.records] == [
        "Mit Nummer",
        "Auch mit",
    ]
    assert len(result.skipped) == 1
    # Zeile 3 in Excel: Kopfzeile ist Zeile 1.
    assert result.skipped[0].line == 3
    assert "Ohne Nummer" in result.skipped[0].reason


def test_a_row_without_a_company_is_skipped():
    result = parse_csv(_csv("Betrieb;Telefon", ";0521 1", "Bau AG;0521 2"))

    assert len(result.records) == 1
    assert "Kein Betrieb" in result.skipped[0].reason


def test_a_phone_number_without_digits_is_no_phone_number():
    result = parse_csv(_csv("Betrieb;Telefon", "Bau AG;auf Anfrage", "Ok;0521 2"))

    assert len(result.records) == 1
    assert "keine Ziffern" in result.skipped[0].reason


def test_trailing_empty_lines_are_not_skipped_rows():
    """Excel hängt sie an jede Datei — das ist kein Fehler des Anwenders."""
    result = parse_csv(_csv("Betrieb;Telefon", "Bau AG;0521 1", ";", ";"))

    assert len(result.records) == 1
    assert result.skipped == []
    assert result.data_rows == 1


def test_an_oversized_extra_column_skips_the_row_instead_of_truncating():
    """Gekürzt sähe die Zeile im Kontakt aus wie ein saubererer Datensatz."""
    result = parse_csv(
        _csv(
            "Betrieb;Telefon;Notiz",
            f"Bau AG;0521 1;{'x' * (MAX_TEXT_CHARS + 1)}",
            "Ok;0521 2;kurz",
        )
    )

    assert len(result.records) == 1
    assert "Notiz" in result.skipped[0].reason


def test_a_file_with_no_usable_row_at_all_is_an_error():
    with pytest.raises(CallCsvError, match="Betrieb \\*und\\* Telefon"):
        parse_csv(_csv("Betrieb;Telefon", "Ohne Nummer;", "Auch ohne;"))


def test_only_a_header_is_an_error():
    with pytest.raises(CallCsvError, match="nur die Kopfzeile"):
        parse_csv(_csv("Betrieb;Telefon"))


def test_an_empty_file_is_an_error():
    with pytest.raises(CallCsvError, match="Datei ist leer"):
        parse_csv(b"")


def test_too_many_rows_is_an_error():
    rows = [f"Betrieb {index};0521 {index}" for index in range(MAX_ROWS + 1)]

    with pytest.raises(CallCsvError, match=str(MAX_ROWS)):
        parse_csv(_csv("Betrieb;Telefon", *rows))


def test_an_xlsx_upload_says_what_to_do():
    """Die wahrscheinlichste Fehlbedienung: die Excel-Datei selbst hochladen."""
    # Ein ZIP-Kopf, dahinter Müll — genau das, was eine .xlsx ist.
    data = b"PK\x03\x04" + bytes(range(128, 256)) * 4

    with pytest.raises(CallCsvError, match="CSV UTF-8"):
        parse_csv(data)


# ------------------------------
# Kodierung
# ------------------------------


def test_a_windows_file_is_read_and_reported():
    result = parse_csv("Betrieb;Telefon\nZaunbau Müller;0521 1\n".encode("cp1252"))

    assert result.records[0].get("betrieb") == "Zaunbau Müller"
    assert result.encoding == "cp1252"
    assert any("cp1252" in warning for warning in result.warnings)


def test_comma_separated_files_work_too():
    result = parse_csv(b"Betrieb,Telefon\nBau AG,0521 1\n")

    assert result.delimiter == ","
    assert result.records[0].get("telefon") == "0521 1"
