import pytest

from app.services.edit_csv_service import bonus_to_cash, process_csv_jf_to_awin
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
