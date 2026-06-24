import pytest

from app.services.edit_csv_service import (
    bonus_to_cash,
    process_csv_awin_to_jf,
    process_csv_jf_to_awin,
)
from tests.ressources.test_objects import test_standard_input, test_standard_output

# ------------------------------
# test_bonus_to_cash_thresholds
# ------------------------------


@pytest.mark.parametrize(
    "bonus, expected",
    [
        (0, 0),
        (1, 0),
        (9, 0),
        (10, 50),
        (24, 50),
        (25, 100),
        (49, 100),
        (50, 200),
        (99, 200),
        (100, 300),
        (199, 300),
        (200, 400),
        (500, 400),
    ],
)
def test_bonus_to_cash_thresholds(bonus, expected):
    assert bonus_to_cash(bonus) == expected


# ------------------------------
# test_process_csv_jf_to_awin
# ------------------------------

# ------ Global Variables ------

accepted = [["Order Reference", "Transaction Date", "Status"]]

declined = [["Order Reference", "Transaction Date", "Status", "Status Note"]]

amended = [
    [
        "Order Reference",
        "Transaction Date",
        "Status",
        "Status Note",
        "New Sale Price",
        "Commission Breakdown",
        "Currency",
    ]
]

# ---------- Test-Cases -----------

process_csv_jf_to_awin_empty_input = (
    b"",
    [
        accepted,
        declined,
        amended,
    ],
)

process_csv_jf_to_awin_standard = (test_standard_input, test_standard_output)


@pytest.mark.parametrize(
    "input, expected",
    [process_csv_jf_to_awin_empty_input, process_csv_jf_to_awin_standard],
)
def test_process_csv_jf_to_awin(input, expected):
    assert process_csv_jf_to_awin(input) == expected


# ------------------------------
# test_process_csv_awin_to_jf
# ------------------------------

awin_to_jf_header = [
    "Order_ID",
    "Rate in %",
    "Sale_Betrag",
    "Provision",
    "Datum",
    "Umsatz_Tatsächlich",
    "Status",
    "Bemerkung",
]

# Source export: header order is deliberately not the target order, and extra
# columns are present, to prove parsing happens by header name.
process_csv_awin_to_jf_standard = (
    (
        "Extra;Sale_Betrag;Provision;Datum;Typ;Geändert;Sonstiges\r\n"
        "12345;16,80;1,34;2025-10-12 16:54:03;Sale;Nein;x\r\n"  # rate 7,98 -> 8%
        "60000;60,00;6,00;2025-01-05 09:00:00;Sale;Nein;y\r\n"  # trailing zeros dropped
        "77;0,00;0,00;2025-03-15 12:30:45;Sale;Nein;z\r\n"  # div/0 -> empty rate
        "88;10,00;1,00;2025-04-01 10:00:00;Lead;Nein;a\r\n"  # filtered: Typ != Sale
        "99;20,00;2,00;2025-05-01 11:00:00;Sale;Ja;b\r\n"  # filtered: Geändert == Ja
    ).encode("utf-8"),
    [
        awin_to_jf_header,
        ["12345", "8%", "16,8", "1,34", "12.10.25 16:54", "", "", ""],
        ["60000", "10%", "60", "6", "05.01.25 09:00", "", "", ""],
        ["77", "", "0", "0", "15.03.25 12:30", "", "", ""],
    ],
)

process_csv_awin_to_jf_empty_input = (b"", [awin_to_jf_header])


@pytest.mark.parametrize(
    "input, expected",
    [process_csv_awin_to_jf_empty_input, process_csv_awin_to_jf_standard],
)
def test_process_csv_awin_to_jf(input, expected):
    assert process_csv_awin_to_jf(input) == expected
