"""Bogengeometrie der perforierten Einsteckschilder-Bögen.

Alle Maße sind **gemessene** Werte in Millimetern, keine abgeleiteten: die
Ränder eines perforierten Bogens ergeben sich nicht rechnerisch aus Blatt- und
Kartengröße, sie stehen so auf dem Karton. Deshalb liegt jedes Format als
vollständiger Datensatz in `SHEET_FORMATS` — ein weiteres Format ist eine
Konfigurationszeile, kein Code.

Damit ein Tippfehler in dieser Konfiguration nicht erst auf dem Karton
auffällt, prüft `SheetFormat.validate()` beim Import, ob Ränder, Karten und
Spalte exakt auf das Blattmaß aufgehen.

Der Ursprung ist die **linke obere Blattecke**, y wächst nach unten — dieselbe
Richtung wie in fpdf2, so dass `badge_pdf` nichts umrechnen muss.
"""

from dataclasses import dataclass

MM_PER_INCH = 25.4
POINTS_PER_INCH = 72.0

# Toleranz der Konsistenzprüfung. 0,01 mm ist eine Größenordnung unter allem,
# was ein Drucker treffen kann, fängt aber Fließkomma-Reste ab.
GEOMETRY_TOLERANCE_MM = 0.01


class SheetGeometryError(ValueError):
    """Ein Format geht nicht auf. Fehlermeldung nennt die Differenz in mm."""


def mm_to_pt(millimetres: float) -> float:
    """Millimeter in PDF-Punkte (1 pt = 1/72 Zoll)."""
    return millimetres * POINTS_PER_INCH / MM_PER_INCH


def pt_to_mm(points: float) -> float:
    """PDF-Punkte in Millimeter."""
    return points * MM_PER_INCH / POINTS_PER_INCH


@dataclass(frozen=True)
class Rect:
    """Rechteck in mm, gemessen von der linken oberen Blattecke."""

    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float

    @property
    def right_mm(self) -> float:
        return self.x_mm + self.width_mm

    @property
    def bottom_mm(self) -> float:
        return self.y_mm + self.height_mm

    @property
    def center_x_mm(self) -> float:
        return self.x_mm + self.width_mm / 2

    @property
    def center_y_mm(self) -> float:
        return self.y_mm + self.height_mm / 2

    def inset(self, amount_mm: float) -> "Rect":
        """Dasselbe Rechteck, allseitig um `amount_mm` verkleinert."""
        return Rect(
            x_mm=self.x_mm + amount_mm,
            y_mm=self.y_mm + amount_mm,
            width_mm=self.width_mm - 2 * amount_mm,
            height_mm=self.height_mm - 2 * amount_mm,
        )

    def moved(self, dx_mm: float, dy_mm: float) -> "Rect":
        """Verschobene Kopie — die Registerkorrektur läuft hierüber."""
        return Rect(self.x_mm + dx_mm, self.y_mm + dy_mm, self.width_mm, self.height_mm)


@dataclass(frozen=True)
class SheetFormat:
    """Ein perforierter Bogen: Blattmaß, Raster, Kartenmaß, Ränder.

    `safety_mm` ist der Abstand, den Inhalte von jeder Kartenkante halten. Er
    fängt die Streuung des Druckers (~±0,5 mm) und die ausgefranste Kante an
    der Perforation ab.
    """

    id: str
    label: str
    sheet_width_mm: float
    sheet_height_mm: float
    columns: int
    rows: int
    card_width_mm: float
    card_height_mm: float
    margin_left_mm: float
    margin_right_mm: float
    margin_top_mm: float
    margin_bottom_mm: float
    # Mikroperforierte Bögen stoßen direkt aneinander, hier also 0. Formate mit
    # Stanzabstand tragen ihn ein.
    gap_x_mm: float
    gap_y_mm: float
    safety_mm: float

    @property
    def slots_per_sheet(self) -> int:
        return self.columns * self.rows

    def validate(self) -> None:
        """Bricht ab, wenn die Maße nicht auf das Blatt aufgehen.

        Läuft beim Import über jedes registrierte Format: eine unstimmige
        Konfiguration lässt die Anwendung gar nicht erst starten, statt Bögen
        zu drucken, deren Karten neben der Perforation liegen.
        """
        if self.columns < 1 or self.rows < 1:
            raise SheetGeometryError(
                f"Format '{self.id}': columns und rows müssen mindestens 1 sein."
            )

        for name, value in (
            ("sheet_width_mm", self.sheet_width_mm),
            ("sheet_height_mm", self.sheet_height_mm),
            ("card_width_mm", self.card_width_mm),
            ("card_height_mm", self.card_height_mm),
        ):
            if value <= 0:
                raise SheetGeometryError(
                    f"Format '{self.id}': {name} muss größer als 0 sein."
                )

        for name, value in (
            ("margin_left_mm", self.margin_left_mm),
            ("margin_right_mm", self.margin_right_mm),
            ("margin_top_mm", self.margin_top_mm),
            ("margin_bottom_mm", self.margin_bottom_mm),
            ("gap_x_mm", self.gap_x_mm),
            ("gap_y_mm", self.gap_y_mm),
            ("safety_mm", self.safety_mm),
        ):
            if value < 0:
                raise SheetGeometryError(
                    f"Format '{self.id}': {name} darf nicht negativ sein."
                )

        if 2 * self.safety_mm >= min(self.card_width_mm, self.card_height_mm):
            raise SheetGeometryError(
                f"Format '{self.id}': safety_mm ({self.safety_mm} mm) lässt von der "
                f"Karte ({self.card_width_mm} × {self.card_height_mm} mm) nichts übrig."
            )

        self._check_axis(
            axis="Breite",
            sheet_mm=self.sheet_width_mm,
            leading_margin_mm=self.margin_left_mm,
            trailing_margin_mm=self.margin_right_mm,
            count=self.columns,
            card_mm=self.card_width_mm,
            gap_mm=self.gap_x_mm,
        )
        self._check_axis(
            axis="Höhe",
            sheet_mm=self.sheet_height_mm,
            leading_margin_mm=self.margin_top_mm,
            trailing_margin_mm=self.margin_bottom_mm,
            count=self.rows,
            card_mm=self.card_height_mm,
            gap_mm=self.gap_y_mm,
        )

    def _check_axis(
        self,
        *,
        axis: str,
        sheet_mm: float,
        leading_margin_mm: float,
        trailing_margin_mm: float,
        count: int,
        card_mm: float,
        gap_mm: float,
    ) -> None:
        used = (
            leading_margin_mm
            + count * card_mm
            + (count - 1) * gap_mm
            + trailing_margin_mm
        )
        difference = used - sheet_mm

        if abs(difference) > GEOMETRY_TOLERANCE_MM:
            raise SheetGeometryError(
                f"Format '{self.id}': die {axis} geht nicht auf. "
                f"{leading_margin_mm} + {count} × {card_mm} + {count - 1} × {gap_mm} "
                f"+ {trailing_margin_mm} = {used:g} mm, das Blatt misst "
                f"{sheet_mm:g} mm ({difference:+.2f} mm Differenz)."
            )

    def card_rect(self, slot_index: int) -> Rect:
        """Kartenrechteck des Slots (0-basiert, zeilenweise von links oben)."""
        if not 0 <= slot_index < self.slots_per_sheet:
            raise SheetGeometryError(
                f"Format '{self.id}': Slot {slot_index + 1} gibt es nicht "
                f"(1 bis {self.slots_per_sheet})."
            )

        column = slot_index % self.columns
        row = slot_index // self.columns

        return Rect(
            x_mm=self.margin_left_mm + column * (self.card_width_mm + self.gap_x_mm),
            y_mm=self.margin_top_mm + row * (self.card_height_mm + self.gap_y_mm),
            width_mm=self.card_width_mm,
            height_mm=self.card_height_mm,
        )

    def safe_rect(self, slot_index: int) -> Rect:
        """Sicherheitszone des Slots — hier darf Inhalt stehen, sonst nirgends."""
        return self.card_rect(slot_index).inset(self.safety_mm)

    def sheets_needed(self, card_count: int, start_slot: int = 1) -> int:
        """Bogenanzahl für `card_count` Karten ab `start_slot` (1-basiert).

        Dieselbe Funktion beantwortet den Trockenlauf und steuert das Rendern —
        vorhergesagte und tatsächliche Seitenzahl können deshalb nicht
        auseinanderlaufen.
        """
        if card_count <= 0:
            return 0

        if not 1 <= start_slot <= self.slots_per_sheet:
            raise SheetGeometryError(
                f"Format '{self.id}': Startkarte {start_slot} gibt es nicht "
                f"(1 bis {self.slots_per_sheet})."
            )

        occupied = card_count + (start_slot - 1)
        return -(-occupied // self.slots_per_sheet)


DEFAULT_FORMAT_ID = "a4_75x40"

# Gemessen am tatsächlichen Bogen. Wer ein Format ergänzt, misst Ränder und
# Kartenmaß nach und rechnet sie nicht aus — die Prüfung oben fängt nur
# Widersprüche ab, keine gemeinsam verschobenen Werte.
SHEET_FORMATS: dict[str, SheetFormat] = {
    DEFAULT_FORMAT_ID: SheetFormat(
        id=DEFAULT_FORMAT_ID,
        label="A4 · 12 Einsteckschilder 75 × 40 mm",
        sheet_width_mm=210.0,
        sheet_height_mm=297.0,
        columns=2,
        rows=6,
        card_width_mm=75.0,
        card_height_mm=40.0,
        margin_left_mm=30.0,
        margin_right_mm=30.0,
        margin_top_mm=28.5,
        margin_bottom_mm=28.5,
        gap_x_mm=0.0,
        gap_y_mm=0.0,
        safety_mm=4.0,
    ),
}

for _sheet_format in SHEET_FORMATS.values():
    _sheet_format.validate()


def get_format(format_id: str) -> SheetFormat:
    """Format nach Id, oder `SheetGeometryError` mit der Liste der bekannten."""
    try:
        return SHEET_FORMATS[format_id]
    except KeyError:
        known = ", ".join(sorted(SHEET_FORMATS))
        raise SheetGeometryError(
            f"Unbekanntes Bogenformat '{format_id}'. Verfügbar: {known}."
        ) from None
