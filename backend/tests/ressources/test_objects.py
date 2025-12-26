from pathlib import Path
import csv
from io import StringIO

def csv_bytes(filename: str) -> bytes:
    base_path = Path(__file__).parent
    return (base_path / filename).read_bytes()

def csv_bytes_to_rows(content: bytes, delimiter=";"):
    text = content.decode("utf-8-sig")  # BOM sicher entfernen
    reader = csv.reader(StringIO(text), delimiter=delimiter)
    return list(reader)

test_standard_input = csv_bytes("test_standard.csv")

test_standard_accepted = csv_bytes("test_accepted.csv")
test_standard_amended = csv_bytes("test_amended.csv")
test_standard_declined = csv_bytes("test_declined.csv")

test_standard_output = [csv_bytes_to_rows(test_standard_accepted), csv_bytes_to_rows(test_standard_declined), csv_bytes_to_rows(test_standard_amended)]