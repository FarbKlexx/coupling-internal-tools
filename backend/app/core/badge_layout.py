"""Was auf einer Karte steht — als Daten, nicht als Zeichenanweisungen.

Ein Layout ist eine Liste von Feldern mit Grundlinie, Schriftgröße,
Auszeichnung und Ausrichtung. `badge_pdf` liest diese Liste ab; ein anderes
Kartenbild ist damit eine Änderung an der Registry unten.

Die Grundlinie (`baseline_mm`) zählt von der **Kartenoberkante** nach unten und
liegt fest: beim automatischen Verkleinern langer Namen ändert sich nur die
Schriftgröße, nie die Position. Der Zeilenabstand bleibt dadurch über alle
Karten eines Bogens gleich, auch wenn auf einer davon ein langer Name steht.
"""

from dataclasses import dataclass

from app.core.badge_geometry import SHEET_FORMATS, SheetFormat

# Felder, die eine Karte tragen kann. Die Reihenfolge ist die Reihenfolge im
# Trockenlauf-Bericht.
FIELD_NAMES: tuple[str, ...] = ("vorname", "nachname", "funktion", "firma")

# Ohne Nachnamen ist die Karte wertlos — Zeilen ohne ihn werden übersprungen
# und dem Anwender mit Zeilennummer gemeldet (siehe `badge_csv`).
REQUIRED_FIELD = "nachname"

FIELD_LABELS: dict[str, str] = {
    "vorname": "Vorname",
    "nachname": "Nachname",
    "funktion": "Funktion",
    "firma": "Firma",
}

ALIGNMENTS = ("left", "center", "right")


class BadgeLayoutError(ValueError):
    """Ein Kartenlayout passt nicht zu seinem Bogenformat."""


@dataclass(frozen=True)
class LayoutField:
    """Eine Textzeile auf der Karte.

    `min_size_pt` ist die Grenze des automatischen Verkleinerns: darunter wird
    nicht weiter geschrumpft, sondern gekürzt. Sonst schrumpfen einzelne lange
    Namen auf eine Größe, die auf dem gedruckten Schild niemand mehr liest.
    """

    field: str
    baseline_mm: float
    size_pt: float
    min_size_pt: float
    bold: bool = False
    align: str = "center"


@dataclass(frozen=True)
class CardLayout:
    """Alle Zeilen einer Karte, in Zeichenreihenfolge."""

    fields: tuple[LayoutField, ...]

    def validate(self, sheet_format: SheetFormat) -> None:
        """Prüft Feldnamen, Größen und die Lage der Grundlinien."""
        if not self.fields:
            raise BadgeLayoutError(
                f"Layout für '{sheet_format.id}' enthält kein einziges Feld."
            )

        safe_top = sheet_format.safety_mm
        safe_bottom = sheet_format.card_height_mm - sheet_format.safety_mm

        for layout_field in self.fields:
            if layout_field.field not in FIELD_NAMES:
                known = ", ".join(FIELD_NAMES)
                raise BadgeLayoutError(
                    f"Layout für '{sheet_format.id}': unbekanntes Feld "
                    f"'{layout_field.field}'. Bekannt: {known}."
                )

            if layout_field.align not in ALIGNMENTS:
                raise BadgeLayoutError(
                    f"Layout für '{sheet_format.id}': unbekannte Ausrichtung "
                    f"'{layout_field.align}' in Feld '{layout_field.field}'."
                )

            if not 0 < layout_field.min_size_pt <= layout_field.size_pt:
                raise BadgeLayoutError(
                    f"Layout für '{sheet_format.id}': min_size_pt muss zwischen 0 "
                    f"und size_pt liegen (Feld '{layout_field.field}')."
                )

            # Die Grundlinie selbst muss in der Sicherheitszone liegen; dass
            # auch die Oberlängen hineinpassen, sichert `badge_pdf` beim
            # Zeichnen über die tatsächlichen Schriftmetriken ab.
            if not safe_top <= layout_field.baseline_mm <= safe_bottom:
                raise BadgeLayoutError(
                    f"Layout für '{sheet_format.id}': Grundlinie von "
                    f"'{layout_field.field}' liegt bei "
                    f"{layout_field.baseline_mm} mm und damit außerhalb der "
                    f"Sicherheitszone ({safe_top} bis {safe_bottom} mm)."
                )


# Standardlayout für 75 × 40 mm: Vorname klein darüber, Nachname groß und fett,
# darunter Funktion und Firma. Alles zentriert, weil die Karte im Steckrahmen
# mittig sitzt.
CARD_LAYOUTS: dict[str, CardLayout] = {
    "a4_75x40": CardLayout(
        fields=(
            LayoutField(
                field="vorname",
                baseline_mm=14.0,
                size_pt=13.0,
                min_size_pt=9.0,
            ),
            LayoutField(
                field="nachname",
                baseline_mm=22.5,
                size_pt=18.0,
                min_size_pt=11.0,
                bold=True,
            ),
            LayoutField(
                field="funktion",
                baseline_mm=29.0,
                size_pt=9.5,
                min_size_pt=7.0,
            ),
            LayoutField(
                field="firma",
                baseline_mm=34.5,
                size_pt=9.5,
                min_size_pt=7.0,
            ),
        )
    ),
}

for _format_id, _layout in CARD_LAYOUTS.items():
    if _format_id not in SHEET_FORMATS:
        raise BadgeLayoutError(
            f"Layout für unbekanntes Bogenformat '{_format_id}' registriert."
        )
    _layout.validate(SHEET_FORMATS[_format_id])

for _format_id in SHEET_FORMATS:
    if _format_id not in CARD_LAYOUTS:
        raise BadgeLayoutError(f"Bogenformat '{_format_id}' hat kein Kartenlayout.")


def get_layout(format_id: str) -> CardLayout:
    """Kartenlayout eines Bogenformats."""
    try:
        return CARD_LAYOUTS[format_id]
    except KeyError:
        raise BadgeLayoutError(
            f"Für das Bogenformat '{format_id}' ist kein Kartenlayout hinterlegt."
        ) from None
