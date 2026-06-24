import csv
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from io import StringIO

month = datetime.now().month
year = datetime.now().year


def process_csv_jf_to_awin(content: bytes):

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

    accepted = [["Order Reference", "Transaction Date", "Status"]]

    text_data = content.decode("utf-8-sig")
    csv_file = StringIO(text_data)
    reader = csv.reader(csv_file, delimiter=";")

    processed_data = []
    firstRow = True

    for row in reader:
        if firstRow:
            firstRow = False
            continue
        status = row[7]
        if status == "R":
            if row[11] == "":
                declinedRow = [row[0], row[4], "DECLINED", "Storniert"]
            else:
                declinedRow = [row[0], row[4], "DECLINED", row[11]]
            declined.append(declinedRow)
            continue
        elif status == "T":
            if row[11] == "":
                amendedRow = [
                    row[0],
                    row[4],
                    "AMENDED",
                    "Teilstorno",
                    row[5][:-2],
                    "",
                    "EUR",
                ]
            else:
                amendedRow = [
                    row[0],
                    row[4],
                    "AMENDED",
                    row[11],
                    row[5][:-2],
                    "",
                    "EUR",
                ]
            amended.append(amendedRow)
            continue
        elif status == "":
            acceptedRow = [row[0], row[4], "ACCEPTED"]
            accepted.append(acceptedRow)
            continue

    processed_data.append(accepted)
    processed_data.append(declined)
    processed_data.append(amended)

    return processed_data


def process_csv_jf_bonus(content: bytes):
    bonus = [
        [
            "Advertiser_ID",
            "Publisher_ID",
            "Verguetungs_art",
            "Sale_betrag",
            "Bonus/Provisions_betrag",
            "Provisions_status",
            "Klick_Ref",
            "Auftrags_Nr",
        ]
    ]

    bonus_map = {}

    text_data = content.decode("utf-8-sig")
    csv_file = StringIO(text_data)
    reader = csv.reader(csv_file, delimiter=";")

    firstRow = True

    for row in reader:
        if firstRow:
            firstRow = False
            continue
        publisher_id = row[1]
        sale_type = row[8]
        if sale_type == "Sale":
            if publisher_id not in bonus_map:
                bonus_map[publisher_id] = 1
            else:
                bonus_map[publisher_id] += 1

    for map_publisher_id, map_bonus in bonus_map.items():
        if map_bonus >= 10:
            bonus.append(
                [
                    "14899",
                    map_publisher_id,
                    "bonus",
                    "0",
                    str(bonus_to_cash(map_bonus)),
                    "confirmed",
                    "",
                    "BONUS_"
                    + str(month)
                    + "_"
                    + str(year)
                    + "_"
                    + str(map_bonus)
                    + "_"
                    + str(map_publisher_id),
                ]
            )

    return bonus


def bonus_to_cash(bonus):
    if bonus >= 10 and not bonus >= 25:
        return 50
    elif bonus >= 25 and not bonus >= 50:
        return 100
    elif bonus >= 50 and not bonus >= 100:
        return 200
    elif bonus >= 100 and not bonus >= 200:
        return 300
    elif bonus >= 200:
        return 400
    return 0


# ---------------------------------------------------------------------------
# AWIN transaction export -> Jeans-Fritz "Offene Sales"
# ---------------------------------------------------------------------------

OFFENE_SALES_HEADER = [
    "Order_ID",
    "Rate in %",
    "Sale_Betrag",
    "Provision",
    "Datum",
    "Umsatz_Tatsächlich",
    "Status",
    "Bemerkung",
]


def _parse_de_decimal(value: str):
    """Parse a German-formatted number ('1.234,56', '16,80', '60,00 €') to Decimal.

    Returns None for empty/blank/unparseable input.
    """
    cleaned = (value or "").replace("€", "").replace("\xa0", "").strip()
    if not cleaned:
        return None
    # German format: '.' groups thousands, ',' is the decimal separator
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _format_de_decimal(value) -> str:
    """Format a Decimal as a German number string without trailing decimal zeros.

    ('16,80' -> '16,8', '60,00' -> '60'). Empty input stays empty.
    """
    if value is None:
        return ""
    # normalize() drops trailing zeros; the 'f' type keeps fixed-point notation
    # (so e.g. Decimal('60.00') renders as '60', not '6E+1').
    return format(value.normalize(), "f").replace(".", ",")


def _compute_rate(sale, provision) -> str:
    """Provision / Sale * 100, commercially rounded to a whole percent ('8%').

    Empty when the sale amount is missing or zero (avoids #DIV/0!).
    """
    if not sale or provision is None:
        return ""
    rate = (provision / sale * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{rate}%"


def _format_datum(value: str) -> str:
    """'YYYY-MM-DD HH:MM:SS' -> 'DD.MM.YY HH:MM' (seconds dropped, 2-digit year).

    Falls back to the raw value if it does not match the expected format.
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw
    return parsed.strftime("%d.%m.%y %H:%M")


def process_csv_awin_to_jf(content: bytes):
    """Reduce an AWIN transaction export (44 cols, UTF-8) to the 8-column
    Jeans-Fritz "Offene Sales" format. Parses by header name, so column order
    in the source does not matter. Non-sales (Typ != 'Sale') and amended rows
    (Geändert == 'Ja') are filtered out.
    """
    text_data = content.decode("utf-8-sig")
    reader = csv.DictReader(StringIO(text_data), delimiter=";")

    # Map each required column to the source header, tolerating surrounding
    # whitespace in the export's header row.
    field_map = {name.strip(): name for name in (reader.fieldnames or [])}

    def col(record, key: str) -> str:
        source = field_map.get(key)
        if source is None:
            return ""
        value = record.get(source)
        return value if value is not None else ""

    rows = [list(OFFENE_SALES_HEADER)]

    for record in reader:
        typ = col(record, "Typ").strip()
        if typ and typ != "Sale":
            continue
        if col(record, "Geändert").strip() == "Ja":
            continue

        sale = _parse_de_decimal(col(record, "Sale_Betrag"))
        provision = _parse_de_decimal(col(record, "Provision"))

        rows.append(
            [
                col(record, "Extra").strip(),
                _compute_rate(sale, provision),
                _format_de_decimal(sale),
                _format_de_decimal(provision),
                _format_datum(col(record, "Datum")),
                "",  # Umsatz_Tatsächlich (Kunde füllt)
                "",  # Status (Kunde füllt)
                "",  # Bemerkung (Kunde füllt)
            ]
        )

    return rows
