"""Namensschilder: CSV einlesen, Trockenlauf berichten, Bogen-PDF erzeugen.

Trockenlauf und Druck laufen durch denselben Import und dieselbe
Bogenrechnung — die angekündigte Bogenanzahl kann deshalb nicht von der
tatsächlichen Seitenzahl abweichen.

**Datenschutz:** Teilnehmerlisten sind personenbezogene Daten. Nichts wird
gespeichert, alles läuft im Speicher dieses Requests, und die Logzeilen unten
enthalten ausschließlich Zahlen — keine Namen, keine Firmen, keine Dateinamen.
"""

import logging
import os
import re
from contextlib import contextmanager
from io import BytesIO
from typing import Iterator

from app.core.badge_csv import (
    MAX_FILE_BYTES,
    MAX_ROWS,
    BadgeCsvError,
    CsvParseResult,
    parse_csv,
)
from app.core.badge_geometry import (
    DEFAULT_FORMAT_ID,
    SHEET_FORMATS,
    SheetFormat,
    SheetGeometryError,
    get_format,
)
from app.core.badge_layout import (
    FIELD_LABELS,
    FIELD_NAMES,
    BadgeLayoutError,
    get_layout,
)
from app.core.badge_pdf import (
    BadgePdfError,
    RenderOptions,
    render_badge_sheets,
    render_calibration_sheet,
)
from app.schemas.name_badge import (
    AnalyseResponse,
    ColumnMappingInfo,
    FormatsResponse,
    LayoutFieldInfo,
    RenderedPdf,
    SheetFormatInfo,
    SkippedRowInfo,
)

logger = logging.getLogger(__name__)

_FALLBACK_STEM = "teilnehmer"
_FILENAME_SUFFIX = "_namensschilder"


class NameBadgeError(Exception):
    """Alles, was der Anwender selbst beheben kann -> HTTP 400.

    Die Fehler der einzelnen Schichten (Import, Geometrie, Layout, PDF) tragen
    bereits anwendbare deutsche Meldungen; hier werden sie nur auf einen Typ
    gebracht, damit die api-Schicht genau eine Ausnahme kennen muss.
    """


_SOURCE_ERRORS = (BadgeCsvError, BadgePdfError, SheetGeometryError, BadgeLayoutError)


@contextmanager
def _user_facing() -> Iterator[None]:
    try:
        yield
    except _SOURCE_ERRORS as exc:
        raise NameBadgeError(str(exc)) from exc


def list_formats() -> FormatsResponse:
    """Bogenformate samt Kartenlayout — die Datenquelle der Oberfläche."""
    return FormatsResponse(
        formats=[_format_info(sheet_format) for sheet_format in SHEET_FORMATS.values()],
        default_format=DEFAULT_FORMAT_ID,
        max_rows=MAX_ROWS,
        max_file_bytes=MAX_FILE_BYTES,
    )


def analyse_badge_csv(
    content: bytes,
    format_id: str = DEFAULT_FORMAT_ID,
    start_slot: int = 1,
) -> AnalyseResponse:
    """Trockenlauf: Datei einlesen und berichten, ohne ein PDF zu erzeugen."""
    with _user_facing():
        sheet_format = get_format(format_id)
        _check_start_slot(sheet_format, start_slot)
        parsed = parse_csv(content)

    logger.info(
        "Namensschilder-Trockenlauf: %s Datensätze, %s übersprungen.",
        len(parsed.records),
        len(parsed.skipped),
    )

    empty_counts = parsed.empty_field_counts()

    return AnalyseResponse(
        format=sheet_format.id,
        start_slot=start_slot,
        records=len(parsed.records),
        sheets=sheet_format.sheets_needed(len(parsed.records), start_slot),
        data_rows=parsed.data_rows,
        encoding=parsed.encoding_label,
        delimiter=parsed.delimiter_label,
        mapping=[
            ColumnMappingInfo(
                field=name,
                label=FIELD_LABELS[name],
                column=column,
                empty_count=empty_counts.get(name, 0),
            )
            for name, column in parsed.mapping.items()
        ],
        missing_fields=[
            FIELD_LABELS[name] for name in FIELD_NAMES if name not in parsed.mapping
        ],
        ignored_columns=list(parsed.ignored_columns),
        skipped_rows=[
            SkippedRowInfo(line=row.line, reason=row.reason) for row in parsed.skipped
        ],
        warnings=list(parsed.warnings),
    )


def create_badge_pdf(
    content: bytes,
    filename: str,
    format_id: str = DEFAULT_FORMAT_ID,
    options: RenderOptions | None = None,
) -> RenderedPdf:
    """Aus der hochgeladenen Liste den druckfertigen Bogensatz erzeugen."""
    render_options = options or RenderOptions()

    with _user_facing():
        sheet_format = get_format(format_id)
        layout = get_layout(format_id)
        _check_start_slot(sheet_format, render_options.start_slot)

        parsed: CsvParseResult = parse_csv(content)
        pdf_bytes = render_badge_sheets(
            [record.values for record in parsed.records],
            sheet_format,
            layout,
            render_options,
        )

    pages = sheet_format.sheets_needed(len(parsed.records), render_options.start_slot)

    logger.info(
        "Namensschilder erzeugt: %s Karten auf %s Bögen (Format %s, ab Karte %s).",
        len(parsed.records),
        pages,
        sheet_format.id,
        render_options.start_slot,
    )

    return RenderedPdf(
        buffer=BytesIO(pdf_bytes),
        filename=_badge_filename(filename),
        pages=pages,
    )


def create_calibration_pdf(
    format_id: str = DEFAULT_FORMAT_ID,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
) -> RenderedPdf:
    """Kalibrierbogen zum Einmessen des Druckerversatzes."""
    with _user_facing():
        sheet_format = get_format(format_id)
        pdf_bytes = render_calibration_sheet(sheet_format, offset_x_mm, offset_y_mm)

    return RenderedPdf(
        buffer=BytesIO(pdf_bytes),
        filename=f"kalibrierbogen_{sheet_format.id}.pdf",
        pages=1,
    )


def _check_start_slot(sheet_format: SheetFormat, start_slot: int) -> None:
    if not 1 <= start_slot <= sheet_format.slots_per_sheet:
        raise BadgePdfError(
            f"Die erste zu bedruckende Karte muss zwischen 1 und "
            f"{sheet_format.slots_per_sheet} liegen."
        )


def _format_info(sheet_format: SheetFormat) -> SheetFormatInfo:
    layout = get_layout(sheet_format.id)

    return SheetFormatInfo(
        id=sheet_format.id,
        label=sheet_format.label,
        sheet_width_mm=sheet_format.sheet_width_mm,
        sheet_height_mm=sheet_format.sheet_height_mm,
        columns=sheet_format.columns,
        rows=sheet_format.rows,
        slots_per_sheet=sheet_format.slots_per_sheet,
        card_width_mm=sheet_format.card_width_mm,
        card_height_mm=sheet_format.card_height_mm,
        margin_left_mm=sheet_format.margin_left_mm,
        margin_right_mm=sheet_format.margin_right_mm,
        margin_top_mm=sheet_format.margin_top_mm,
        margin_bottom_mm=sheet_format.margin_bottom_mm,
        gap_x_mm=sheet_format.gap_x_mm,
        gap_y_mm=sheet_format.gap_y_mm,
        safety_mm=sheet_format.safety_mm,
        fields=[
            LayoutFieldInfo(
                field=layout_field.field,
                label=FIELD_LABELS[layout_field.field],
                baseline_mm=layout_field.baseline_mm,
                size_pt=layout_field.size_pt,
                min_size_pt=layout_field.min_size_pt,
                bold=layout_field.bold,
                align=layout_field.align,
            )
            for layout_field in layout.fields
        ],
    )


def _badge_filename(filename: str) -> str:
    """ "Gäste Sommerfest.csv" -> "gaeste_sommerfest_namensschilder.pdf"."""
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    slug = re.sub(r"[^a-z0-9]+", "_", _transliterate(stem.lower())).strip("_")
    return f"{slug or _FALLBACK_STEM}{_FILENAME_SUFFIX}.pdf"


def _transliterate(text: str) -> str:
    for character, replacement in (
        ("ä", "ae"),
        ("ö", "oe"),
        ("ü", "ue"),
        ("ß", "ss"),
    ):
        text = text.replace(character, replacement)
    return text


__all__ = [
    "NameBadgeError",
    "RenderOptions",
    "analyse_badge_csv",
    "create_badge_pdf",
    "create_calibration_pdf",
    "list_formats",
]
