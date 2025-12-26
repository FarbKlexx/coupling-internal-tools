import csv
from datetime import datetime
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
