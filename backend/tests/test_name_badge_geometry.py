"""Rastermathematik der Einsteckschilder-Bögen.

Der Bogen wird direkt bedruckt und nicht geschnitten: eine Karte, die einen
Millimeter daneben liegt, ist Ausschuss. Diese Tests prüfen deshalb die
absoluten mm-Werte einzelner Slots und nicht nur, dass irgendetwas gerechnet
wird.
"""

import dataclasses

import pytest

from app.core.badge_geometry import (
    DEFAULT_FORMAT_ID,
    SHEET_FORMATS,
    Rect,
    SheetFormat,
    SheetGeometryError,
    get_format,
    mm_to_pt,
    pt_to_mm,
)
from app.core.badge_layout import (
    CARD_LAYOUTS,
    BadgeLayoutError,
    LayoutField,
    get_layout,
)

A4 = get_format(DEFAULT_FORMAT_ID)


def _variant(**changes) -> SheetFormat:
    return dataclasses.replace(A4, **changes)


# ------------------------------
# Aufgehen des Rasters
# ------------------------------


def test_registered_formats_are_consistent():
    """Jedes ausgelieferte Format geht exakt auf sein Blattmaß auf."""
    for sheet_format in SHEET_FORMATS.values():
        sheet_format.validate()


def test_columns_add_up_to_the_sheet_width():
    used = (
        A4.margin_left_mm
        + A4.columns * A4.card_width_mm
        + (A4.columns - 1) * A4.gap_x_mm
        + A4.margin_right_mm
    )
    assert used == pytest.approx(A4.sheet_width_mm, abs=1e-9)
    assert used == pytest.approx(210.0, abs=1e-9)


def test_rows_add_up_to_the_sheet_height():
    used = (
        A4.margin_top_mm
        + A4.rows * A4.card_height_mm
        + (A4.rows - 1) * A4.gap_y_mm
        + A4.margin_bottom_mm
    )
    assert used == pytest.approx(A4.sheet_height_mm, abs=1e-9)
    assert used == pytest.approx(297.0, abs=1e-9)


def test_twelve_slots_per_sheet():
    assert A4.slots_per_sheet == 12


# ------------------------------
# Absolute Kartenpositionen
# ------------------------------


@pytest.mark.parametrize(
    "slot, expected",
    [
        # Zeilenweise von links oben, Ränder 30 mm links, 28,5 mm oben.
        (1, Rect(30.0, 28.5, 75.0, 40.0)),
        (2, Rect(105.0, 28.5, 75.0, 40.0)),
        (3, Rect(30.0, 68.5, 75.0, 40.0)),
        (12, Rect(105.0, 228.5, 75.0, 40.0)),
    ],
)
def test_card_positions_in_millimetres(slot, expected):
    assert A4.card_rect(slot - 1) == expected


def test_last_card_ends_exactly_at_the_bottom_margin():
    last = A4.card_rect(A4.slots_per_sheet - 1)

    assert last.right_mm == pytest.approx(A4.sheet_width_mm - A4.margin_right_mm)
    assert last.bottom_mm == pytest.approx(A4.sheet_height_mm - A4.margin_bottom_mm)


def test_cards_touch_because_the_sheet_is_microperforated():
    """Spalt 0 mm: die rechte Kante von Slot 1 ist die linke von Slot 2."""
    assert A4.card_rect(0).right_mm == A4.card_rect(1).x_mm
    assert A4.card_rect(0).bottom_mm == A4.card_rect(2).y_mm


def test_safety_zone_is_four_millimetres_inside_the_card():
    assert A4.safe_rect(0) == Rect(34.0, 32.5, 67.0, 32.0)


def test_unknown_slot_is_rejected():
    with pytest.raises(SheetGeometryError, match="Slot 13"):
        A4.card_rect(12)

    with pytest.raises(SheetGeometryError):
        A4.card_rect(-1)


# ------------------------------
# Konsistenzprüfung
# ------------------------------


def test_three_columns_of_75_mm_do_not_fit():
    """Der Fall aus der Aufgabenstellung: 30 + 3 × 75 + 30 = 285 ≠ 210."""
    with pytest.raises(SheetGeometryError, match="Breite geht nicht auf"):
        _variant(columns=3).validate()


def test_wrong_margins_are_rejected():
    with pytest.raises(SheetGeometryError, match="Breite geht nicht auf"):
        _variant(margin_left_mm=25.0).validate()

    with pytest.raises(SheetGeometryError, match="Höhe geht nicht auf"):
        _variant(margin_top_mm=25.0).validate()


def test_error_message_names_the_difference():
    with pytest.raises(SheetGeometryError) as error:
        _variant(card_width_mm=76.0).validate()

    assert "+2.00 mm" in str(error.value)


def test_a_gap_that_is_not_there_is_rejected():
    """Ein Spalt zwischen den Karten sprengt die Blattbreite."""
    with pytest.raises(SheetGeometryError):
        _variant(gap_x_mm=2.0).validate()


def test_tolerance_accepts_rounding_noise_but_not_a_tenth_of_a_millimetre():
    _variant(card_width_mm=75.0 + 1e-9).validate()

    with pytest.raises(SheetGeometryError):
        _variant(card_width_mm=75.05).validate()


def test_safety_zone_larger_than_the_card_is_rejected():
    with pytest.raises(SheetGeometryError, match="safety_mm"):
        _variant(safety_mm=25.0).validate()


def test_negative_values_are_rejected():
    with pytest.raises(SheetGeometryError, match="margin_left_mm"):
        _variant(margin_left_mm=-1.0, margin_right_mm=61.0).validate()


def test_unknown_format_lists_the_known_ones():
    with pytest.raises(SheetGeometryError, match="a4_75x40"):
        get_format("a4_90x54")


# ------------------------------
# Bogenanzahl
# ------------------------------


@pytest.mark.parametrize(
    "cards, start_slot, expected",
    [
        (0, 1, 0),
        (1, 1, 1),
        (12, 1, 1),
        (13, 1, 2),
        (24, 1, 2),
        (25, 1, 3),
        # Ein angebrochener Bogen verschiebt alles nach hinten.
        (1, 12, 1),
        (2, 12, 2),
        (12, 2, 2),
        (11, 2, 1),
    ],
)
def test_sheets_needed(cards, start_slot, expected):
    assert A4.sheets_needed(cards, start_slot) == expected


def test_impossible_start_slot_is_rejected():
    with pytest.raises(SheetGeometryError, match="Startkarte 13"):
        A4.sheets_needed(1, start_slot=13)


# ------------------------------
# Einheiten
# ------------------------------


def test_millimetre_to_point_conversion_is_exact_for_a4():
    assert mm_to_pt(210.0) == pytest.approx(595.2755905511812)
    assert mm_to_pt(297.0) == pytest.approx(841.8897637795277)
    assert pt_to_mm(mm_to_pt(75.0)) == pytest.approx(75.0)


# ------------------------------
# Kartenlayout
# ------------------------------


def test_every_format_has_a_layout_that_fits_it():
    for format_id, sheet_format in SHEET_FORMATS.items():
        get_layout(format_id).validate(sheet_format)


def test_default_layout_has_the_four_expected_fields():
    fields = [
        layout_field.field for layout_field in get_layout(DEFAULT_FORMAT_ID).fields
    ]

    assert fields == ["vorname", "nachname", "funktion", "firma"]


def test_surname_is_the_largest_and_the_only_bold_field():
    layout = get_layout(DEFAULT_FORMAT_ID)
    surname = next(f for f in layout.fields if f.field == "nachname")

    assert surname.bold
    assert all(f.size_pt <= surname.size_pt for f in layout.fields)
    assert [f.field for f in layout.fields if f.bold] == ["nachname"]


def test_baselines_keep_their_order_from_top_to_bottom():
    baselines = [f.baseline_mm for f in get_layout(DEFAULT_FORMAT_ID).fields]

    assert baselines == sorted(baselines)


def test_baseline_outside_the_safety_zone_is_rejected():
    layout = dataclasses.replace(
        CARD_LAYOUTS[DEFAULT_FORMAT_ID],
        fields=(
            LayoutField(
                field="nachname", baseline_mm=38.0, size_pt=18.0, min_size_pt=9.0
            ),
        ),
    )

    with pytest.raises(BadgeLayoutError, match="Sicherheitszone"):
        layout.validate(A4)


def test_unknown_field_in_a_layout_is_rejected():
    layout = dataclasses.replace(
        CARD_LAYOUTS[DEFAULT_FORMAT_ID],
        fields=(
            LayoutField(
                field="abteilung", baseline_mm=20.0, size_pt=12.0, min_size_pt=9.0
            ),
        ),
    )

    with pytest.raises(BadgeLayoutError, match="abteilung"):
        layout.validate(A4)
