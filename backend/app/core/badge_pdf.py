"""Druckfertige PDFs für perforierte Einsteckschilder-Bögen.

Der Bogen wird **direkt bedruckt** und danach nicht geschnitten. Alles, was
sonst zu einem Druck-PDF gehört, ist deshalb hier falsch: kein Anschnitt, keine
Beschnittzugabe, keine Schnitt- oder Passermarken, nichts außerhalb der Seite
und keine randabfallenden Farbflächen — an der Perforation entsteht beim
Ausbrechen eine faserige Kante, an der Toner abplatzt.

Drei Eigenschaften des Ergebnisses sind für den Druck entscheidend:

* **Seitenbox exakt A4.** fpdf2 schreibt die MediaBox mit zwei Nachkommastellen
  (595.28 statt 595.276), deshalb setzt `_exact_page_boxes()` sie danach über
  pypdf auf den exakten Wert.
* **PrintScaling = None.** Damit wählen Viewer von sich aus „Tatsächliche
  Größe“. Die stille Skalierung auf ~96 % im Druckdialog ist der häufigste
  Fehler und macht das ganze Raster unbrauchbar.
* **Nur eingebettete Subset-Schriften.** Base-14- oder Systemschriften würden
  vom Druckertreiber mit eigener Metrik gesetzt, der Text liefe aus der
  Sicherheitszone. fpdf2 legt eine Schrift nur an, wenn sie auch benutzt wird —
  eine Seite ohne Text hat gar keine Font-Ressource.

**Datenschutz:** hier wird nichts geloggt. Die Namen stehen im PDF und sonst
nirgends.
"""

import math
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fpdf import FPDF
from fpdf.prefs import ViewerPreferences
from pypdf import PdfReader, PdfWriter
from pypdf.generic import FloatObject, RectangleObject

from app.core.badge_geometry import Rect, SheetFormat, mm_to_pt, pt_to_mm
from app.core.badge_layout import CardLayout, LayoutField

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_FAMILY = "Outfit"
FONT_FILES = {
    "": FONT_DIR / "Outfit-Regular.ttf",
    "B": FONT_DIR / "Outfit-Bold.ttf",
}

# Registerkorrektur: gleicht den systematischen Versatz eines Druckers aus.
# Mehr als ein halber Zentimeter ist kein Versatz mehr, sondern das falsche
# Papierfach oder das falsche Format.
MAX_OFFSET_MM = 5.0

# Schriftgrößen werden auf dieses Raster abgerundet — sonst stehen im PDF
# Größen wie 12.837 pt, die niemand nachvollziehen kann.
SIZE_STEP_PT = 0.1

ELLIPSIS = "…"

# Graustufen (0 = schwarz, 1 = weiß). Hilfslinien bleiben hell genug, um die
# Karte nicht zu dominieren, und dunkel genug, um am Licht sichtbar zu sein.
_TEXT_GRAY = 0
_OUTLINE_GRAY = 0.72
_SAFE_ZONE_GRAY = 0.82
_CALIBRATION_GRAY = 0.45

_HAIRLINE_PT = 0.4

# Fadenkreuze der Kalibrierung: Mittelpunkt 10 mm von jeder Blattecke, Arme
# 5 mm. Sie sind die rasterunabhängige Referenz und werden deshalb **ohne**
# Offset gezeichnet.
CROSSHAIR_INSET_MM = 10.0
CROSSHAIR_ARM_MM = 5.0


class BadgePdfError(Exception):
    """Das PDF konnte nicht erzeugt werden. Meldung ist für den Anwender."""


@dataclass(frozen=True)
class RenderOptions:
    """Alles, was der Anwender am fertigen Bogen einstellen kann."""

    start_slot: int = 1
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    draw_outlines: bool = False


@dataclass(frozen=True)
class FittedText:
    """Ein Text in der Größe, in der er tatsächlich gesetzt wird."""

    text: str
    size_pt: float


def validate_offset(offset_x_mm: float, offset_y_mm: float) -> None:
    """Registerkorrektur auf den sinnvollen Bereich begrenzen."""
    for axis, value in (("X", offset_x_mm), ("Y", offset_y_mm)):
        if not -MAX_OFFSET_MM <= value <= MAX_OFFSET_MM:
            raise BadgePdfError(
                f"Der Versatz in {axis}-Richtung muss zwischen "
                f"-{MAX_OFFSET_MM:g} und {MAX_OFFSET_MM:g} mm liegen. Größere "
                "Abweichungen kommen nicht vom Drucker, sondern vom falschen "
                "Papierfach oder Format."
            )


def page_size_pt(sheet_format: SheetFormat) -> tuple[float, float]:
    """Seitenmaß in Punkt, auf drei Nachkommastellen festgelegt.

    A4 wird damit zu exakt 595.276 × 841.890 pt. Das Dokument wird mit genau
    diesen Werten aufgebaut *und* die MediaBox darauf gesetzt, so dass
    Inhaltskoordinaten und Seitenbox auf dieselbe Blatthöhe bezogen sind.
    """
    return (
        round(mm_to_pt(sheet_format.sheet_width_mm), 3),
        round(mm_to_pt(sheet_format.sheet_height_mm), 3),
    )


def render_badge_sheets(
    records: list[dict[str, str]],
    sheet_format: SheetFormat,
    layout: CardLayout,
    options: RenderOptions,
) -> bytes:
    """Alle Karten auf so viele Bögen setzen, wie nötig sind."""
    validate_offset(options.offset_x_mm, options.offset_y_mm)

    if not records:
        raise BadgePdfError("Es gibt keine Daten, aus denen Karten würden.")

    slots = sheet_format.slots_per_sheet
    if not 1 <= options.start_slot <= slots:
        raise BadgePdfError(
            f"Die erste zu bedruckende Karte muss zwischen 1 und {slots} liegen."
        )

    pdf = _new_document(sheet_format)
    pages = sheet_format.sheets_needed(len(records), options.start_slot)

    # Erst alle Bögen anlegen, dann gezielt zwischen ihnen springen
    # (`pdf.page`): so bestimmt die Slot-Rechnung, wo eine Karte landet, und
    # nicht die Reihenfolge, in der gezeichnet wird. Die Seitenzahl steht damit
    # schon vor dem ersten Text fest — dieselbe Zahl, die der Trockenlauf
    # angekündigt hat.
    for _ in range(pages):
        pdf.add_page()

    if options.draw_outlines:
        # Zum Testen wird das **ganze** Raster gezeichnet, nicht nur die
        # belegten Karten: erst im Vergleich mit der Perforation sieht man, ob
        # der Bogen richtig liegt.
        for page in range(1, pages + 1):
            pdf.page = page
            for slot_index in range(slots):
                _draw_rect(
                    pdf,
                    sheet_format.card_rect(slot_index).moved(
                        options.offset_x_mm, options.offset_y_mm
                    ),
                    gray=_OUTLINE_GRAY,
                )

    for position, record in enumerate(records):
        absolute_slot = position + options.start_slot - 1
        pdf.page = absolute_slot // slots + 1
        slot_index = absolute_slot % slots

        card = sheet_format.card_rect(slot_index).moved(
            options.offset_x_mm, options.offset_y_mm
        )

        for layout_field in layout.fields:
            _draw_field(
                pdf,
                record.get(layout_field.field, ""),
                layout_field,
                card,
                sheet_format.safety_mm,
            )

    return _finish(pdf, sheet_format)


def render_calibration_sheet(
    sheet_format: SheetFormat,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
) -> bytes:
    """Leeres Raster zum Einmessen des Druckerversatzes.

    Wird auf Normalpapier gedruckt, auf einen Blankobogen gelegt und gegen das
    Licht gehalten. Kartenumrisse und Sicherheitszonen wandern mit dem
    eingestellten Offset — die Fadenkreuze in den Blattecken nicht, sie sind
    die Referenz auf das Blatt selbst.
    """
    validate_offset(offset_x_mm, offset_y_mm)

    pdf = _new_document(sheet_format)
    pdf.add_page()

    pdf.set_font(FONT_FAMILY, size=7)
    pdf.set_text_color(_gray(_CALIBRATION_GRAY))

    _draw_crosshairs(pdf, sheet_format)
    _draw_calibration_header(pdf, sheet_format, offset_x_mm, offset_y_mm)

    for slot_index in range(sheet_format.slots_per_sheet):
        card = sheet_format.card_rect(slot_index).moved(offset_x_mm, offset_y_mm)
        safe = card.inset(sheet_format.safety_mm)

        _draw_rect(pdf, card, gray=_OUTLINE_GRAY)
        _draw_rect(pdf, safe, gray=_SAFE_ZONE_GRAY, dashed=True)

        pdf.set_font(FONT_FAMILY, style="B", size=14)
        _draw_centered(pdf, str(slot_index + 1), safe.center_x_mm, card.center_y_mm + 2)

        pdf.set_font(FONT_FAMILY, size=6)
        _draw_centered(
            pdf,
            f"{sheet_format.card_width_mm:g} × {sheet_format.card_height_mm:g} mm",
            safe.center_x_mm,
            safe.bottom_mm - 1,
        )

    return _finish(pdf, sheet_format)


def _new_document(sheet_format: SheetFormat) -> FPDF:
    """Leeres Dokument mit den Druckvorstufen-Einstellungen dieses Werkzeugs."""
    width_pt, height_pt = page_size_pt(sheet_format)

    pdf = FPDF(orientation="P", unit="pt", format=(width_pt, height_pt))
    # Ränder und Umbruch macht die Bogengeometrie, nicht fpdf2: ein
    # automatischer Seitenumbruch würde Karten auf eine Folgeseite schieben.
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)
    pdf.set_title("Namensschilder")
    # Kein Duplex: die Rückseite des Kartons ist unbedruckt und der Bogen darf
    # den Drucker nur einmal durchlaufen.
    pdf.viewer_preferences = ViewerPreferences(
        print_scaling="None",
        duplex="Simplex",
    )

    for style, path in FONT_FILES.items():
        if not path.is_file():
            raise BadgePdfError(
                f"Die Schriftdatei {path.name} fehlt. Ohne eingebettete Schrift "
                "wird kein druckfähiges PDF erzeugt."
            )
        pdf.add_font(FONT_FAMILY, style=style, fname=str(path))

    return pdf


def _finish(pdf: FPDF, sheet_format: SheetFormat) -> bytes:
    try:
        raw = bytes(pdf.output())
    except Exception as exc:  # pragma: no cover - fpdf2 meldet Zeichenprobleme
        raise BadgePdfError(f"Das PDF konnte nicht erzeugt werden ({exc}).") from exc

    return _exact_page_boxes(raw, *page_size_pt(sheet_format))


def _exact_page_boxes(raw: bytes, width_pt: float, height_pt: float) -> bytes:
    """MediaBox jeder Seite auf den exakten Wert setzen.

    fpdf2 rundet die Box beim Schreiben auf zwei Nachkommastellen. Der
    Unterschied ist mit 0,0015 mm praktisch bedeutungslos, aber die Seitenbox
    ist die eine Angabe, an der ein Druckdienstleister das Format prüft — sie
    steht deshalb exakt drin. Der Klon erhält ViewerPreferences und die
    eingebetteten Schriften.
    """
    writer = PdfWriter(clone_from=PdfReader(BytesIO(raw)))

    box = RectangleObject(
        [
            FloatObject(0),
            FloatObject(0),
            FloatObject(round(width_pt, 3)),
            FloatObject(round(height_pt, 3)),
        ]
    )
    for page in writer.pages:
        page.mediabox = box

    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _draw_field(
    pdf: FPDF,
    text: str,
    layout_field: LayoutField,
    card: Rect,
    safety_mm: float,
) -> None:
    """Ein Feld in die Sicherheitszone der Karte setzen."""
    value = text.strip()
    if not value:
        return

    fitted = fit_text(pdf, value, layout_field, card, safety_mm)
    if not fitted.text:
        return

    safe = card.inset(safety_mm)

    pdf.set_font(
        FONT_FAMILY,
        style="B" if layout_field.bold else "",
        size=fitted.size_pt,
    )
    pdf.set_text_color(_gray(_TEXT_GRAY))

    width_mm = pt_to_mm(pdf.get_string_width(fitted.text))
    x_mm = _aligned_x(layout_field.align, safe, width_mm)
    # `baseline_mm` zählt von der Kartenoberkante — dieselbe Grundlinie auf
    # jeder Karte, unabhängig davon, wie stark der Text verkleinert wurde.
    baseline_mm = card.y_mm + layout_field.baseline_mm

    pdf.text(mm_to_pt(x_mm), mm_to_pt(baseline_mm), fitted.text)


def fit_text(
    pdf: FPDF,
    text: str,
    layout_field: LayoutField,
    card: Rect,
    safety_mm: float,
) -> FittedText:
    """Größte Schriftgröße, mit der `text` in die Sicherheitszone passt.

    Verkleinert wird stufenlos (auf 0,1 pt abgerundet) und nur die Größe: die
    Grundlinie bleibt, wo das Layout sie hinlegt, der Zeilenabstand verschiebt
    sich also nicht. Reicht die Mindestgröße nicht, wird gekürzt statt weiter
    geschrumpft.
    """
    pdf.set_font(
        FONT_FAMILY,
        style="B" if layout_field.bold else "",
        size=layout_field.size_pt,
    )

    max_width_mm = card.width_mm - 2 * safety_mm

    size_pt = min(
        layout_field.size_pt,
        _size_limited_by_width(pdf, text, layout_field.size_pt, max_width_mm),
        _size_limited_by_height(pdf, layout_field, card, safety_mm),
    )
    size_pt = max(_floor_to_step(size_pt), layout_field.min_size_pt)

    pdf.set_font_size(size_pt)
    max_width_pt = mm_to_pt(max_width_mm)

    if pdf.get_string_width(text) <= max_width_pt:
        return FittedText(text=text, size_pt=size_pt)

    return FittedText(text=_truncate(pdf, text, max_width_pt), size_pt=size_pt)


def _size_limited_by_width(
    pdf: FPDF, text: str, size_pt: float, max_width_mm: float
) -> float:
    """Textbreite skaliert linear mit der Größe — eine Messung genügt."""
    width_pt = pdf.get_string_width(text)
    if width_pt <= 0:
        return size_pt

    return size_pt * mm_to_pt(max_width_mm) / width_pt


def _size_limited_by_height(
    pdf: FPDF, layout_field: LayoutField, card: Rect, safety_mm: float
) -> float:
    """Größe, bei der Ober- und Unterlängen noch in der Zone bleiben.

    Die Grundlinie ist fix, also begrenzt der Platz über ihr die Oberlänge und
    der Platz darunter die Unterlänge. Gerechnet wird mit den Werten aus der
    Schrift selbst, nicht mit einer Faustformel.
    """
    descriptor = pdf.current_font.desc
    ascent = max(descriptor.ascent, 1) / 1000
    descent = max(-descriptor.descent, 1) / 1000

    above_mm = layout_field.baseline_mm - safety_mm
    below_mm = card.height_mm - safety_mm - layout_field.baseline_mm

    return min(mm_to_pt(above_mm) / ascent, mm_to_pt(below_mm) / descent)


def _truncate(pdf: FPDF, text: str, max_width_pt: float) -> str:
    """Text so weit kürzen, bis er mit Auslassungszeichen hineinpasst."""
    shortened = text
    while shortened:
        shortened = shortened[:-1].rstrip()
        if pdf.get_string_width(shortened + ELLIPSIS) <= max_width_pt:
            return shortened + ELLIPSIS

    return ""


def _aligned_x(align: str, safe: Rect, width_mm: float) -> float:
    if align == "left":
        return safe.x_mm
    if align == "right":
        return safe.right_mm - width_mm
    return safe.center_x_mm - width_mm / 2


def _draw_rect(pdf: FPDF, rect: Rect, *, gray: float, dashed: bool = False) -> None:
    pdf.set_draw_color(_gray(gray))
    pdf.set_line_width(_HAIRLINE_PT)

    if dashed:
        pdf.set_dash_pattern(dash=2, gap=2)

    pdf.rect(
        mm_to_pt(rect.x_mm),
        mm_to_pt(rect.y_mm),
        mm_to_pt(rect.width_mm),
        mm_to_pt(rect.height_mm),
    )

    if dashed:
        pdf.set_dash_pattern()


def _draw_crosshairs(pdf: FPDF, sheet_format: SheetFormat) -> None:
    """Vier Fadenkreuze, je 10 mm von einer Blattecke entfernt."""
    pdf.set_draw_color(_gray(_CALIBRATION_GRAY))
    pdf.set_line_width(_HAIRLINE_PT)

    xs = (CROSSHAIR_INSET_MM, sheet_format.sheet_width_mm - CROSSHAIR_INSET_MM)
    ys = (CROSSHAIR_INSET_MM, sheet_format.sheet_height_mm - CROSSHAIR_INSET_MM)

    for x_mm in xs:
        for y_mm in ys:
            pdf.line(
                mm_to_pt(x_mm - CROSSHAIR_ARM_MM / 2),
                mm_to_pt(y_mm),
                mm_to_pt(x_mm + CROSSHAIR_ARM_MM / 2),
                mm_to_pt(y_mm),
            )
            pdf.line(
                mm_to_pt(x_mm),
                mm_to_pt(y_mm - CROSSHAIR_ARM_MM / 2),
                mm_to_pt(x_mm),
                mm_to_pt(y_mm + CROSSHAIR_ARM_MM / 2),
            )


def _draw_calibration_header(
    pdf: FPDF,
    sheet_format: SheetFormat,
    offset_x_mm: float,
    offset_y_mm: float,
) -> None:
    """Beschriftung über dem Raster — nur, wenn der Rand dafür Platz lässt."""
    if sheet_format.margin_top_mm < CROSSHAIR_INSET_MM + 6:
        return

    pdf.set_font(FONT_FAMILY, style="B", size=8)
    pdf.set_text_color(_gray(_CALIBRATION_GRAY))
    _draw_centered(
        pdf,
        f"Kalibrierbogen · {sheet_format.label}",
        sheet_format.sheet_width_mm / 2,
        sheet_format.margin_top_mm - 8,
    )

    pdf.set_font(FONT_FAMILY, size=7)
    _draw_centered(
        pdf,
        f"Versatz X {offset_x_mm:+.1f} mm · Y {offset_y_mm:+.1f} mm · "
        f"Fadenkreuze {CROSSHAIR_INSET_MM:g} mm von der Blattecke (ohne Versatz)",
        sheet_format.sheet_width_mm / 2,
        sheet_format.margin_top_mm - 4,
    )


def _draw_centered(
    pdf: FPDF, text: str, center_x_mm: float, baseline_mm: float
) -> None:
    width_mm = pt_to_mm(pdf.get_string_width(text))
    pdf.text(mm_to_pt(center_x_mm - width_mm / 2), mm_to_pt(baseline_mm), text)


def _gray(value: float) -> int:
    """Graustufe 0..1 in den 0..255-Wert, den fpdf2 erwartet."""
    return round(value * 255)


def _floor_to_step(size_pt: float) -> float:
    return math.floor(size_pt / SIZE_STEP_PT) * SIZE_STEP_PT
