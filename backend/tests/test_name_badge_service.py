"""Service- und HTTP-Schicht der Namensschilder.

Der wichtigste Test hier ist die Übereinstimmung von Trockenlauf und Druck:
was der Bericht ankündigt, muss das PDF halten — sonst legt jemand zwölf
Blankobögen ein und bekommt dreizehn Seiten.
"""

import logging
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.core.badge_geometry import DEFAULT_FORMAT_ID, get_format
from app.core.badge_pdf import RenderOptions
from app.main import app
from app.services.name_badge_service import (
    NameBadgeError,
    analyse_badge_csv,
    create_badge_pdf,
    create_calibration_pdf,
    list_formats,
)

SHEET = get_format(DEFAULT_FORMAT_ID)

client = TestClient(app)


def _csv(rows: int, header: str = "Vorname;Nachname;Funktion;Firma") -> bytes:
    lines = [header]
    lines += [f"Vorname{index};Nachname{index};Rolle;Firma" for index in range(rows)]
    return ("\n".join(lines) + "\n").encode()


def _pages(pdf: bytes) -> int:
    return len(PdfReader(BytesIO(pdf)).pages)


# ------------------------------
# Trockenlauf und Druck stimmen überein
# ------------------------------


@pytest.mark.parametrize(
    "rows, start_slot",
    [(1, 1), (11, 2), (12, 1), (13, 1), (12, 2), (1, 12), (2, 12), (30, 5)],
)
def test_dry_run_predicts_the_real_page_count(rows, start_slot):
    data = _csv(rows)

    report = analyse_badge_csv(data, DEFAULT_FORMAT_ID, start_slot)
    result = create_badge_pdf(
        data, "liste.csv", DEFAULT_FORMAT_ID, RenderOptions(start_slot=start_slot)
    )

    assert report.records == rows
    assert report.sheets == _pages(result.buffer.getvalue())
    assert report.sheets == result.pages


def test_dry_run_counts_only_printable_rows():
    """Übersprungene Zeilen zählen nicht mit — sonst stimmt die Bogenanzahl nicht."""
    data = "Vorname;Nachname\nAnna;Müller\nOhne;\nBert;Schmidt\n".encode()

    report = analyse_badge_csv(data)
    result = create_badge_pdf(data, "liste.csv")

    assert report.records == 2
    assert report.data_rows == 3
    assert report.sheets == _pages(result.buffer.getvalue()) == 1


def test_dry_run_reports_encoding_delimiter_and_mapping():
    data = "Vorname\tNachname\tTischnummer\nAnna\tMüller\t7\n".encode("utf-8-sig")

    report = analyse_badge_csv(data)

    assert report.encoding == "UTF-8 (mit BOM)"
    assert report.delimiter == "Tabulator"
    assert [entry.column for entry in report.mapping] == ["Vorname", "Nachname"]
    assert report.ignored_columns == ["Tischnummer"]
    assert report.missing_fields == ["Funktion", "Firma"]


def test_dry_run_lists_skipped_rows_with_their_line_numbers():
    data = "Vorname;Nachname\nAnna;Müller\nOhne;\n;\nBert;\n".encode()

    report = analyse_badge_csv(data)

    assert [(row.line, row.reason) for row in report.skipped_rows] == [
        (3, "Kein Nachname in der Zeile."),
        (5, "Kein Nachname in der Zeile."),
    ]


def test_dry_run_counts_empty_fields_per_column():
    data = "Vorname;Nachname;Firma\n;Müller;\nBert;Schmidt;Coupling\n".encode()

    report = analyse_badge_csv(data)
    empty = {entry.field: entry.empty_count for entry in report.mapping}

    assert empty == {"vorname": 1, "nachname": 0, "firma": 1}


def test_dry_run_creates_no_pdf():
    """Der Trockenlauf ist billig — er darf nichts rendern."""
    report = analyse_badge_csv(_csv(5))

    assert not hasattr(report, "buffer")


# ------------------------------
# Dateinamen
# ------------------------------


@pytest.mark.parametrize(
    "uploaded, expected",
    [
        ("Gäste Sommerfest.csv", "gaeste_sommerfest_namensschilder.pdf"),
        ("teilnehmer.CSV", "teilnehmer_namensschilder.pdf"),
        ("2026-05-01_Kunden.csv", "2026_05_01_kunden_namensschilder.pdf"),
        ("", "teilnehmer_namensschilder.pdf"),
        # Bleibt nach dem Übersetzen nichts Verwertbares übrig, greift der
        # Ersatzname — ein Download ohne Namen wäre schlimmer.
        ("🎉🎉.csv", "teilnehmer_namensschilder.pdf"),
    ],
)
def test_download_filename(uploaded, expected):
    assert create_badge_pdf(_csv(1), uploaded).filename == expected


def test_calibration_filename_names_the_format():
    assert create_calibration_pdf().filename == "kalibrierbogen_a4_75x40.pdf"


# ------------------------------
# Fehler, die der Anwender beheben kann
# ------------------------------


def test_missing_surname_column_is_a_user_error():
    with pytest.raises(NameBadgeError, match="keine Spalte für den Nachnamen"):
        create_badge_pdf("Vorname;Firma\nAnna;Coupling\n".encode(), "liste.csv")


def test_unknown_format_is_a_user_error():
    with pytest.raises(NameBadgeError, match="Unbekanntes Bogenformat"):
        analyse_badge_csv(_csv(1), "a4_90x54")


def test_impossible_start_slot_is_a_user_error():
    with pytest.raises(NameBadgeError, match="erste zu bedruckende Karte"):
        analyse_badge_csv(_csv(1), DEFAULT_FORMAT_ID, start_slot=13)


def test_absurd_offset_is_a_user_error():
    with pytest.raises(NameBadgeError, match="Versatz"):
        create_badge_pdf(_csv(1), "liste.csv", options=RenderOptions(offset_x_mm=12.0))


# ------------------------------
# Datenschutz
# ------------------------------


def test_no_field_content_reaches_the_log(caplog):
    """Teilnehmerlisten sind personenbezogene Daten — Logs enthalten nur Zahlen."""
    data = "Vorname;Nachname;Firma\nGeheim;Wichtigtuer;Verschwiegen GmbH\n".encode()

    with caplog.at_level(logging.DEBUG):
        analyse_badge_csv(data)
        create_badge_pdf(data, "vertrauliche_gaesteliste.csv")

    for secret in ("Geheim", "Wichtigtuer", "Verschwiegen", "vertrauliche"):
        assert secret not in caplog.text


# ------------------------------
# Formate für die Oberfläche
# ------------------------------


def test_formats_carry_the_geometry_the_frontend_draws_from():
    response = list_formats()
    a4 = next(entry for entry in response.formats if entry.id == DEFAULT_FORMAT_ID)

    assert response.default_format == DEFAULT_FORMAT_ID
    assert (a4.columns, a4.rows, a4.slots_per_sheet) == (2, 6, 12)
    assert (a4.card_width_mm, a4.card_height_mm) == (75.0, 40.0)
    assert (a4.sheet_width_mm, a4.sheet_height_mm) == (210.0, 297.0)
    assert a4.safety_mm == 4.0
    assert [entry.field for entry in a4.fields] == [
        "vorname",
        "nachname",
        "funktion",
        "firma",
    ]


# ------------------------------
# HTTP
# ------------------------------


def test_endpoint_returns_a_pdf_with_a_filename_and_the_sheet_count():
    response = client.post(
        "/name-badges",
        files={"file": ("gaeste.csv", _csv(13), "text/csv")},
        data={"start_slot": "1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "gaeste_namensschilder.pdf" in response.headers["content-disposition"]
    assert response.headers["x-sheet-count"] == "2"
    assert response.content.startswith(b"%PDF-")
    assert _pages(response.content) == 2


def test_analyse_endpoint_answers_json():
    response = client.post(
        "/name-badges/analyse",
        files={"file": ("gaeste.csv", _csv(13), "text/csv")},
        data={"start_slot": "3"},
    )

    assert response.status_code == 200
    assert response.json()["sheets"] == 2
    assert response.json()["records"] == 13


def test_calibration_endpoint_answers_a_single_page_pdf():
    response = client.post(
        "/name-badges/calibration",
        json={"format": DEFAULT_FORMAT_ID, "offset_x_mm": 0.5, "offset_y_mm": -0.5},
    )

    assert response.status_code == 200
    assert _pages(response.content) == 1


def test_formats_endpoint():
    response = client.get("/name-badges/formats")

    assert response.status_code == 200
    assert response.json()["default_format"] == DEFAULT_FORMAT_ID
    assert response.json()["max_offset_mm"] == 5.0


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"file": ("liste.csv", b"", "text/csv")}, "Datei ist leer"),
        ({"file": ("liste.csv", b"Vorname\nAnna\n", "text/csv")}, "Nachnamen"),
        ({"file": ("liste.csv", b"Vorname;Nachname\n", "text/csv")}, "Kopfzeile"),
    ],
)
def test_broken_uploads_answer_400_with_an_actionable_message(payload, expected):
    response = client.post("/name-badges", files=payload)

    assert response.status_code == 400
    assert expected in response.json()["detail"]


def test_out_of_range_offset_answers_400_not_422():
    """Ein rohes 422 sagt dem Anwender nichts."""
    response = client.post("/name-badges/calibration", json={"offset_x_mm": 42})

    assert response.status_code == 400
    assert "Versatz" in response.json()["detail"]
