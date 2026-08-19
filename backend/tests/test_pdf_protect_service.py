from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfReader

from app.core.pdf_utils import (
    MAX_PASSWORD_BYTES,
    PdfProtectionError,
    is_pdf,
    protect_pdf,
    protected_filename,
)
from app.services.pdf_protect_service import protect_uploaded_pdf

PASSWORD = "geheim123"


def _pdf_bytes(pages: int = 2, **metadata: str) -> bytes:
    images = [Image.new("RGB", (200, 280), "white") for _ in range(pages)]
    buffer = BytesIO()
    images[0].save(
        buffer,
        format="PDF",
        save_all=True,
        append_images=images[1:],
        **metadata,
    )
    return buffer.getvalue()


def test_is_pdf_accepts_a_pdf_and_rejects_other_bytes():
    assert is_pdf(_pdf_bytes())
    assert not is_pdf(b"kein pdf")
    assert not is_pdf(b"")


def test_protected_pdf_needs_the_password():
    protected = protect_pdf(_pdf_bytes(), PASSWORD)
    reader = PdfReader(BytesIO(protected))

    assert reader.is_encrypted
    # 0 = wrong password, anything above = access granted
    assert reader.decrypt("falsches-passwort") == 0
    assert reader.decrypt(PASSWORD) > 0


def test_pages_and_metadata_survive_the_encryption():
    original = _pdf_bytes(pages=3, title="Testdokument", author="Coupling")

    reader = PdfReader(BytesIO(protect_pdf(original, PASSWORD)))
    reader.decrypt(PASSWORD)

    assert len(reader.pages) == 3
    assert reader.metadata is not None
    assert reader.metadata.title == "Testdokument"
    assert reader.metadata.author == "Coupling"


def test_non_pdf_upload_is_rejected():
    with pytest.raises(PdfProtectionError, match="kein PDF"):
        protect_pdf(b"nur text", PASSWORD)


def test_already_protected_pdf_is_rejected():
    protected = protect_pdf(_pdf_bytes(), PASSWORD)

    with pytest.raises(PdfProtectionError, match="bereits passwortgeschützt"):
        protect_pdf(protected, "anderes-passwort")


def test_empty_password_is_rejected():
    with pytest.raises(PdfProtectionError, match="nicht leer"):
        protect_pdf(_pdf_bytes(), "")


def test_overlong_password_is_rejected():
    with pytest.raises(PdfProtectionError, match="zu lang"):
        protect_pdf(_pdf_bytes(), "x" * (MAX_PASSWORD_BYTES + 1))


def test_password_length_is_counted_in_bytes_not_characters():
    # Umlauts take two bytes in UTF-8, so this is over the limit despite being
    # only 64 characters long.
    with pytest.raises(PdfProtectionError, match="zu lang"):
        protect_pdf(_pdf_bytes(), "ä" * 64)


def test_corrupt_pdf_reports_a_readable_error():
    with pytest.raises(PdfProtectionError):
        protect_pdf(b"%PDF-1.7\nkaputt", PASSWORD)


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("rechnung.pdf", "rechnung_geschuetzt.pdf"),
        ("Rechnung 2026.PDF", "Rechnung 2026_geschuetzt.pdf"),
        ("pfad/zum/vertrag.pdf", "vertrag_geschuetzt.pdf"),
        ("", "dokument_geschuetzt.pdf"),
    ],
)
def test_protected_filename(filename, expected):
    assert protected_filename(filename) == expected


def test_service_returns_a_seeked_buffer_and_a_filename():
    result = protect_uploaded_pdf(_pdf_bytes(), "vertrag.pdf", PASSWORD)

    assert result.filename == "vertrag_geschuetzt.pdf"
    assert result.buffer.tell() == 0
    assert result.buffer.getvalue().startswith(b"%PDF-")
