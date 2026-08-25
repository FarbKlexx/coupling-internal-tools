"""Druckvorstufen-Eigenschaften der erzeugten Bögen.

Geprüft wird jeweils am **fertigen PDF**, nicht an den Absichten des Codes:
Seitenbox, PrintScaling und Schrifteinbettung werden aus der Datei
zurückgelesen, und wo es um die Lage von Text geht, kommen Position, Größe und
Breite aus dem Content-Stream selbst.
"""

from io import BytesIO

import pytest
from pypdf import PdfReader
from pypdf.generic import ContentStream

from app.core.badge_geometry import (
    DEFAULT_FORMAT_ID,
    SheetFormat,
    get_format,
    mm_to_pt,
    pt_to_mm,
)
from app.core.badge_layout import get_layout
from app.core.badge_pdf import (
    MAX_OFFSET_MM,
    BadgePdfError,
    RenderOptions,
    render_badge_sheets,
    render_calibration_sheet,
)

A4_WIDTH_PT = 595.276
A4_HEIGHT_PT = 841.890

SHEET = get_format(DEFAULT_FORMAT_ID)
LAYOUT = get_layout(DEFAULT_FORMAT_ID)


def _render(records, **options) -> bytes:
    return render_badge_sheets(records, SHEET, LAYOUT, RenderOptions(**options))


def _person(nachname: str, **extra) -> dict[str, str]:
    return {"nachname": nachname, **extra}


def _reader(raw: bytes) -> PdfReader:
    return PdfReader(BytesIO(raw))


# ---------------------------------------------------------------------------
# Auslesen des Content-Streams
#
# Alles unterhalb dieser Grenze arbeitet mit dem, was wirklich im PDF steht:
# `Tf` sagt, welche Schrift in welcher Größe *selektiert* ist, `Td` wo die
# Grundlinie liegt, und die Glyphenbreiten aus dem Font-Objekt ergeben die
# tatsächliche Breite des gesetzten Textes.
# ---------------------------------------------------------------------------


class DrawnText:
    """Ein gesetzter Text, rekonstruiert aus dem Content-Stream."""

    def __init__(
        self, font_name: str, size_pt: float, x_pt: float, y_pt: float, glyphs
    ):
        self.font_name = font_name
        self.size_pt = size_pt
        self.x_pt = x_pt
        self.y_pt = y_pt
        self.glyphs = glyphs

    def width_pt(self, widths: dict[int, float], default_width: float) -> float:
        return (
            sum(widths.get(glyph, default_width) for glyph in self.glyphs)
            * self.size_pt
            / 1000
        )

    @property
    def x_mm(self) -> float:
        return pt_to_mm(self.x_pt)

    def baseline_mm(self, page_height_pt: float) -> float:
        """PDF zählt y von unten, die Bogengeometrie von oben."""
        return pt_to_mm(page_height_pt - self.y_pt)


def _glyph_ids(operand) -> list[int]:
    """Die Glyphen-Ids eines Tj-Operanden (Identity-H, also 2 Byte je Glyphe)."""
    if isinstance(operand, bytes):
        return [
            int.from_bytes(operand[index : index + 2], "big")
            for index in range(0, len(operand), 2)
        ]
    return [ord(character) for character in str(operand)]


def _drawn_texts(reader: PdfReader, page) -> list[DrawnText]:
    stream = ContentStream(page.get_contents(), reader)

    font_name = ""
    size_pt = 0.0
    position = (0.0, 0.0)
    drawn: list[DrawnText] = []

    for operands, operator in stream.operations:
        if operator == b"Tf":
            font_name, size_pt = str(operands[0]), float(operands[1])
        elif operator == b"Td":
            position = (float(operands[0]), float(operands[1]))
        elif operator == b"Tj":
            drawn.append(
                DrawnText(
                    font_name,
                    size_pt,
                    position[0],
                    position[1],
                    _glyph_ids(operands[0]),
                )
            )

    return drawn


def _font_objects(page) -> dict[str, object]:
    fonts = page["/Resources"].get("/Font")
    return {str(name): obj.get_object() for name, obj in (fonts or {}).items()}


def _descendant(font) -> dict:
    return font["/DescendantFonts"][0].get_object()


def _glyph_widths(font) -> tuple[dict[int, float], float]:
    """Das /W-Array eines Type0-Fonts in {Glyphen-Id: Breite} übersetzen."""
    descendant = _descendant(font)
    widths: dict[int, float] = {}

    entries = list(descendant.get("/W", []))
    index = 0
    while index < len(entries):
        start = int(entries[index])
        following = entries[index + 1]

        if isinstance(following, list):
            for offset, width in enumerate(following):
                widths[start + offset] = float(width)
            index += 2
        else:
            end, width = int(following), float(entries[index + 2])
            for glyph in range(start, end + 1):
                widths[glyph] = width
            index += 3

    return widths, float(descendant.get("/DW", 1000))


def _embedded_font_file(font) -> object | None:
    """Die eingebettete Schriftdatei eines Fonts, falls es eine gibt."""
    if font.get("/Subtype") == "/Type0":
        descriptor = _descendant(font)["/FontDescriptor"].get_object()
    else:
        descriptor_ref = font.get("/FontDescriptor")
        if descriptor_ref is None:
            return None
        descriptor = descriptor_ref.get_object()

    for key in ("/FontFile", "/FontFile2", "/FontFile3"):
        if key in descriptor:
            return descriptor[key]

    return None


# ------------------------------
# Seitenbox
# ------------------------------


def test_page_box_is_exactly_a4():
    """Kein Anschnitt, keine Zugabe — die Seite ist das Blatt."""
    page = _reader(_render([_person("Müller")])).pages[0]

    assert float(page.mediabox.width) == pytest.approx(A4_WIDTH_PT, abs=1e-9)
    assert float(page.mediabox.height) == pytest.approx(A4_HEIGHT_PT, abs=1e-9)
    assert [float(value) for value in page.mediabox.lower_left] == [0.0, 0.0]


def test_page_box_is_a4_on_every_page():
    raw = _render([_person(f"Nummer{index}") for index in range(20)])

    for page in _reader(raw).pages:
        assert float(page.mediabox.width) == pytest.approx(A4_WIDTH_PT, abs=1e-9)
        assert float(page.mediabox.height) == pytest.approx(A4_HEIGHT_PT, abs=1e-9)


def test_page_box_matches_210_by_297_millimetres():
    page = _reader(_render([_person("Müller")])).pages[0]

    assert pt_to_mm(float(page.mediabox.width)) == pytest.approx(210.0, abs=0.001)
    assert pt_to_mm(float(page.mediabox.height)) == pytest.approx(297.0, abs=0.001)


def test_no_crop_box_deviates_from_the_media_box():
    page = _reader(_render([_person("Müller")])).pages[0]

    assert [float(value) for value in page.cropbox] == [
        float(value) for value in page.mediabox
    ]


def test_calibration_sheet_has_the_same_page_box():
    page = _reader(render_calibration_sheet(SHEET)).pages[0]

    assert float(page.mediabox.width) == pytest.approx(A4_WIDTH_PT, abs=1e-9)
    assert float(page.mediabox.height) == pytest.approx(A4_HEIGHT_PT, abs=1e-9)


# ------------------------------
# Viewer-Einstellungen
# ------------------------------


def test_print_scaling_is_none():
    """Ohne diesen Eintrag skalieren Viewer still auf ~96 % und das Raster ist hin."""
    catalog = _reader(_render([_person("Müller")])).trailer["/Root"]

    assert catalog["/ViewerPreferences"]["/PrintScaling"] == "/None"


def test_print_scaling_is_set_on_the_calibration_sheet_too():
    catalog = _reader(render_calibration_sheet(SHEET)).trailer["/Root"]

    assert catalog["/ViewerPreferences"]["/PrintScaling"] == "/None"


def test_duplex_is_simplex():
    catalog = _reader(_render([_person("Müller")])).trailer["/Root"]

    assert catalog["/ViewerPreferences"]["/Duplex"] == "/Simplex"


# ------------------------------
# Schrifteinbettung
# ------------------------------


def test_every_font_selected_in_the_content_stream_is_embedded():
    """Geprüft wird, was benutzt wird — nicht, was in den Ressourcen liegt.

    In den Page-Resources kann eine ungenutzte Default-Schrift stehen; die
    entscheidende Frage ist, welche Schrift ein `Tf`-Operator selektiert.
    """
    reader = _reader(
        _render(
            [
                _person("Müller", vorname="Anna", funktion="CEO", firma="Coupling"),
                _person("Schmidt", vorname="Bert"),
            ]
        )
    )

    selected_anywhere = 0

    for page in reader.pages:
        fonts = _font_objects(page)
        used = {text.font_name for text in _drawn_texts(reader, page)}

        assert used, "Auf der Seite wird Text gesetzt, aber keine Schrift selektiert."

        for name in used:
            assert name in fonts, f"{name} wird selektiert, steht aber nicht in /Font."
            font = fonts[name]

            assert (
                _embedded_font_file(font) is not None
            ), f"{name} ({font.get('/BaseFont')}) ist nicht eingebettet."
            # Ein Subset-Präfix wie "MPDFAA+Outfit" belegt zusätzlich, dass nur
            # die benutzten Glyphen mitgehen.
            assert "+" in str(font["/BaseFont"])

            selected_anywhere += 1

    assert selected_anywhere > 0


def test_no_base14_font_is_referenced_at_all():
    """Auch nicht ungenutzt in den Ressourcen — es gibt schlicht keine."""
    base14 = ("Helvetica", "Courier", "Times", "Symbol", "ZapfDingbats", "Arial")
    reader = _reader(_render([_person("Müller", vorname="Anna")]))

    for page in reader.pages:
        for name, font in _font_objects(page).items():
            base_font = str(font.get("/BaseFont", ""))
            assert not any(
                candidate in base_font for candidate in base14
            ), f"{name} verweist auf die nicht eingebettete Schrift {base_font}."


def test_calibration_sheet_uses_only_embedded_fonts():
    reader = _reader(render_calibration_sheet(SHEET))
    page = reader.pages[0]
    fonts = _font_objects(page)

    for text in _drawn_texts(reader, page):
        assert _embedded_font_file(fonts[text.font_name]) is not None


def test_a_page_without_text_carries_no_font_resource_at_all():
    """Ein Bogen ohne einen einzigen Text darf keine Schrift referenzieren.

    Manche PDF-Bibliotheken schreiben von sich aus eine Default-Schrift in den
    Content-Stream jeder Seite, auch wenn nichts damit gesetzt wird. Genau das
    darf hier nicht passieren: dieser Bogen enthält nur Linien.
    """
    raw = _render([{"nachname": " "}], draw_outlines=True)
    reader = _reader(raw)
    page = reader.pages[0]

    assert _drawn_texts(reader, page) == []
    assert _font_objects(page) == {}


def test_only_the_used_fonts_end_up_in_the_page_resources():
    raw = _render([_person("Müller", vorname="Anna")])
    reader = _reader(raw)
    page = reader.pages[0]

    assert set(_font_objects(page)) == {
        text.font_name for text in _drawn_texts(reader, page)
    }


# ------------------------------
# Seitenzahl
# ------------------------------


@pytest.mark.parametrize(
    "cards, start_slot",
    [(1, 1), (12, 1), (13, 1), (25, 1), (1, 12), (2, 12), (11, 2), (12, 2), (24, 7)],
)
def test_predicted_sheet_count_matches_the_real_page_count(cards, start_slot):
    records = [_person(f"Person{index}") for index in range(cards)]

    predicted = SHEET.sheets_needed(cards, start_slot)
    raw = _render(records, start_slot=start_slot)

    assert len(_reader(raw).pages) == predicted


def test_cards_land_on_the_slot_they_were_promised():
    """Ab Slot 12: die erste Karte steht rechts unten, die zweite oben links."""
    raw = _render([_person("Erste"), _person("Zweite")], start_slot=12)
    reader = _reader(raw)
    height_pt = float(reader.pages[0].mediabox.height)

    first = _drawn_texts(reader, reader.pages[0])[0]
    second = _drawn_texts(reader, reader.pages[1])[0]

    assert first.baseline_mm(height_pt) == pytest.approx(
        SHEET.card_rect(11).y_mm + _baseline_of("nachname"), abs=0.01
    )
    assert second.baseline_mm(height_pt) == pytest.approx(
        SHEET.card_rect(0).y_mm + _baseline_of("nachname"), abs=0.01
    )


def _baseline_of(field: str) -> float:
    return next(f.baseline_mm for f in LAYOUT.fields if f.field == field)


# ------------------------------
# Text in der Sicherheitszone
# ------------------------------


def _texts_with_geometry(raw: bytes):
    reader = _reader(raw)
    page = reader.pages[0]
    fonts = _font_objects(page)
    height_pt = float(page.mediabox.height)

    for text in _drawn_texts(reader, page):
        widths, default_width = _glyph_widths(fonts[text.font_name])
        yield text, pt_to_mm(text.width_pt(widths, default_width)), height_pt


def test_a_long_name_fits_into_the_safety_zone_after_shrinking():
    """Der Ernstfall: ein Name, der die Karte sprengen würde."""
    long_name = "Schmidt-Wolkenkuckucksheim-Hohenzollern"
    safe = SHEET.safe_rect(0)

    for text, width_mm, _ in _texts_with_geometry(_render([_person(long_name)])):
        assert text.x_mm >= safe.x_mm - 0.01
        assert text.x_mm + width_mm <= safe.right_mm + 0.01
        # Die Karte ist 75 mm breit, die Zone 67 mm — der Text muss deutlich
        # schmaler geworden sein als die Karte.
        assert width_mm <= safe.width_mm


def test_every_field_of_a_full_card_stays_inside_the_safety_zone():
    record = _person(
        "Schmidt-Wolkenkuckucksheim-Hohenzollern",
        vorname="Maximilian-Alexander",
        funktion="Senior Account Manager Nord und Ost",
        firma="Sehr Lange Firmenbezeichnung GmbH & Co. KG",
    )
    safe = SHEET.safe_rect(0)

    drawn = list(_texts_with_geometry(_render([record])))
    assert len(drawn) == 4

    for text, width_mm, height_pt in drawn:
        baseline_mm = text.baseline_mm(height_pt)

        assert text.x_mm >= safe.x_mm - 0.01
        assert text.x_mm + width_mm <= safe.right_mm + 0.01
        assert safe.y_mm <= baseline_mm <= safe.bottom_mm


def test_ascenders_and_descenders_stay_inside_the_safety_zone():
    """Nicht nur die Grundlinie: die Ober- und Unterlängen zählen mit."""
    record = _person("Müller", vorname="Anna", funktion="Typografin", firma="Coupling")
    raw = _render([record])
    reader = _reader(raw)
    page = reader.pages[0]
    fonts = _font_objects(page)
    height_pt = float(page.mediabox.height)
    safe = SHEET.safe_rect(0)

    for text in _drawn_texts(reader, page):
        descriptor = _descendant(fonts[text.font_name])["/FontDescriptor"].get_object()
        ascent_mm = pt_to_mm(float(descriptor["/Ascent"]) / 1000 * text.size_pt)
        descent_mm = pt_to_mm(abs(float(descriptor["/Descent"])) / 1000 * text.size_pt)
        baseline_mm = text.baseline_mm(height_pt)

        assert baseline_mm - ascent_mm >= safe.y_mm - 0.01
        assert baseline_mm + descent_mm <= safe.bottom_mm + 0.01


def test_shrinking_does_not_move_the_baselines():
    """Der Zeilenabstand ist über alle Karten gleich, egal wie lang der Name ist."""
    short = _render([_person("Ott", vorname="Ida")])
    long = _render([_person("Schmidt-Wolkenkuckucksheim-Hohenzollern", vorname="Ida")])

    short_baselines = [
        text.y_pt for text in _drawn_texts(_reader(short), _reader(short).pages[0])
    ]
    long_baselines = [
        text.y_pt for text in _drawn_texts(_reader(long), _reader(long).pages[0])
    ]

    assert short_baselines == long_baselines


def test_a_long_name_is_actually_set_smaller():
    short = list(_texts_with_geometry(_render([_person("Ott")])))
    long = list(_texts_with_geometry(_render([_person("Schmidt-Wolkenkuckucksheim")])))

    assert long[0][0].size_pt < short[0][0].size_pt


def test_an_absurd_name_is_truncated_at_the_minimum_size():
    minimum = next(f.min_size_pt for f in LAYOUT.fields if f.field == "nachname")
    safe = SHEET.safe_rect(0)

    drawn = list(_texts_with_geometry(_render([_person("Do" + "nau" * 40)])))
    text, width_mm, _ = drawn[0]

    assert text.size_pt == pytest.approx(minimum, abs=0.001)
    assert width_mm <= safe.width_mm + 0.01


def test_empty_fields_draw_nothing():
    drawn = list(
        _texts_with_geometry(_render([_person("Müller", vorname="", firma="   ")]))
    )

    assert len(drawn) == 1


# ------------------------------
# Registerkorrektur
# ------------------------------


def test_offset_moves_the_content_but_not_the_page_box():
    plain = _reader(_render([_person("Müller")]))
    shifted = _reader(_render([_person("Müller")], offset_x_mm=1.5, offset_y_mm=-0.75))

    assert [float(value) for value in shifted.pages[0].mediabox] == [
        float(value) for value in plain.pages[0].mediabox
    ]

    before = _drawn_texts(plain, plain.pages[0])[0]
    after = _drawn_texts(shifted, shifted.pages[0])[0]

    assert after.x_pt - before.x_pt == pytest.approx(mm_to_pt(1.5), abs=0.02)
    # y wächst im PDF nach oben, ein negativer Versatz nach oben hebt den Text.
    assert after.y_pt - before.y_pt == pytest.approx(mm_to_pt(0.75), abs=0.02)


@pytest.mark.parametrize("offset", [MAX_OFFSET_MM + 0.1, -MAX_OFFSET_MM - 0.1, 50.0])
def test_absurd_offsets_are_rejected(offset):
    with pytest.raises(BadgePdfError, match="Versatz"):
        _render([_person("Müller")], offset_x_mm=offset)

    with pytest.raises(BadgePdfError, match="Versatz"):
        _render([_person("Müller")], offset_y_mm=offset)


def test_the_maximum_offset_is_still_allowed():
    _render([_person("Müller")], offset_x_mm=MAX_OFFSET_MM, offset_y_mm=-MAX_OFFSET_MM)


# ------------------------------
# Kalibrierbogen
# ------------------------------


def test_calibration_sheet_is_a_single_page_with_every_slot_numbered():
    reader = _reader(render_calibration_sheet(SHEET))

    assert len(reader.pages) == 1

    numbers = [
        text
        for text in _drawn_texts(reader, reader.pages[0])
        if len(text.glyphs) <= 2 and text.size_pt >= 10
    ]
    assert len(numbers) == SHEET.slots_per_sheet


def test_calibration_crosshairs_ignore_the_offset():
    """Die Fadenkreuze sind die Referenz auf das Blatt, nicht auf das Raster."""
    plain = render_calibration_sheet(SHEET)
    shifted = render_calibration_sheet(SHEET, offset_x_mm=2.0, offset_y_mm=2.0)

    assert _line_operations(plain) == _line_operations(shifted)


def _line_operations(raw: bytes) -> list[tuple[float, float]]:
    reader = _reader(raw)
    stream = ContentStream(reader.pages[0].get_contents(), reader)

    return [
        (round(float(operands[0]), 3), round(float(operands[1]), 3))
        for operands, operator in stream.operations
        if operator in (b"m", b"l")
    ]


# ------------------------------
# Grenzfälle
# ------------------------------


def test_rendering_without_records_is_refused():
    with pytest.raises(BadgePdfError, match="keine Daten"):
        _render([])


def test_impossible_start_slot_is_refused():
    with pytest.raises(BadgePdfError, match="erste zu bedruckende Karte"):
        _render([_person("Müller")], start_slot=13)


def test_special_characters_survive_the_font_subset():
    """Namen mit Umlauten, Akzenten und Bindestrichen dürfen nicht scheitern."""
    raw = _render(
        [
            _person("Müller-Lüdenscheidt", vorname="Jürgen"),
            _person("Šarović", vorname="Željko"),
            _person("Łukasiewicz", vorname="Agnieszka"),
            _person("Öztürk", vorname="Ayşe"),
        ]
    )

    assert len(_reader(raw).pages) == 1


def test_a_format_the_renderer_has_never_seen_works_the_same():
    """Ein anderes Format ist Konfiguration — der Renderer kennt keine Sonderfälle."""
    square = SheetFormat(
        id="test_square",
        label="Testbogen",
        sheet_width_mm=200.0,
        sheet_height_mm=200.0,
        columns=2,
        rows=2,
        card_width_mm=80.0,
        card_height_mm=80.0,
        margin_left_mm=20.0,
        margin_right_mm=20.0,
        margin_top_mm=20.0,
        margin_bottom_mm=20.0,
        gap_x_mm=0.0,
        gap_y_mm=0.0,
        safety_mm=5.0,
    )
    square.validate()

    raw = render_badge_sheets([_person("Müller")], square, LAYOUT, RenderOptions())
    page = _reader(raw).pages[0]

    assert pt_to_mm(float(page.mediabox.width)) == pytest.approx(200.0, abs=0.001)
