import csv
from io import StringIO


def csv_rows_to_str(rows: list[list[str]]) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerows(rows)
    return buffer.getvalue()
