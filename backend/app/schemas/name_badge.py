"""Anfrage- und Antwortmodelle des Namensschilder-Werkzeugs.

Die Geometrie geht bewusst vollständig an das Frontend: das klickbare
Kartenraster für die erste zu bedruckende Karte wird daraus gerendert und nicht
im Frontend nachgebaut. Ein weiteres Bogenformat bleibt damit eine reine
Backend-Konfiguration.
"""

from dataclasses import dataclass
from io import BytesIO

from pydantic import BaseModel

from app.core.badge_geometry import DEFAULT_FORMAT_ID
from app.core.badge_pdf import MAX_OFFSET_MM


class LayoutFieldInfo(BaseModel):
    """Eine Zeile des Kartenlayouts, wie sie gedruckt wird."""

    field: str
    label: str
    baseline_mm: float
    size_pt: float
    min_size_pt: float
    bold: bool
    align: str


class SheetFormatInfo(BaseModel):
    """Ein Bogenformat mit allen Maßen in Millimetern."""

    id: str
    label: str
    sheet_width_mm: float
    sheet_height_mm: float
    columns: int
    rows: int
    slots_per_sheet: int
    card_width_mm: float
    card_height_mm: float
    margin_left_mm: float
    margin_right_mm: float
    margin_top_mm: float
    margin_bottom_mm: float
    gap_x_mm: float
    gap_y_mm: float
    safety_mm: float
    fields: list[LayoutFieldInfo]


class FormatsResponse(BaseModel):
    """Alles, was das Frontend braucht, um die Oberfläche zu bauen."""

    formats: list[SheetFormatInfo]
    default_format: str
    max_offset_mm: float = MAX_OFFSET_MM
    max_rows: int
    max_file_bytes: int


class ColumnMappingInfo(BaseModel):
    """Welche Spalte der Datei auf welchem Kartenfeld landet."""

    field: str
    label: str
    column: str
    empty_count: int


class SkippedRowInfo(BaseModel):
    """Eine übersprungene Zeile mit ihrer Nummer in der Datei."""

    line: int
    reason: str


class AnalyseResponse(BaseModel):
    """Trockenlauf: was der Druck ergäbe, ohne ein PDF zu erzeugen."""

    format: str
    start_slot: int
    records: int
    sheets: int
    data_rows: int
    encoding: str
    delimiter: str
    mapping: list[ColumnMappingInfo]
    missing_fields: list[str]
    ignored_columns: list[str]
    skipped_rows: list[SkippedRowInfo]
    warnings: list[str]


class CalibrationRequest(BaseModel):
    """Kalibrierbogen — braucht keine Daten, nur Format und Versatz.

    Die Grenzen des Versatzes prüft absichtlich der Service und nicht Pydantic:
    ein `Field(ge=…)` beantwortet eine Überschreitung mit einem rohen 422, der
    Service dagegen mit einer Meldung, die sagt, was zu tun ist.
    """

    format: str = DEFAULT_FORMAT_ID
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0


@dataclass
class RenderedPdf:
    """Fertiges PDF, bereit zum Ausliefern durch die api-Schicht."""

    buffer: BytesIO
    filename: str
    pages: int
