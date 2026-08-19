"""Pure PDF helpers: format check and password protection."""

import os
from io import BytesIO

from pypdf import PdfReader, PdfWriter

# The header may sit behind a few junk bytes, so look at the start of the file
# rather than requiring position 0.
_HEADER = b"%PDF-"
_HEADER_SEARCH_WINDOW = 1024

# PDF 2.0 caps the password of the AES-256 security handler at 127 bytes.
MAX_PASSWORD_BYTES = 127

# AES-256 is what every current reader supports; the weaker RC4 handlers are
# only needed for pre-2010 software.
_ALGORITHM = "AES-256"

PROTECTED_SUFFIX = "_geschuetzt"


class PdfProtectionError(Exception):
    """Raised when a PDF cannot be read or protected. Message is user-facing."""


def is_pdf(data: bytes) -> bool:
    """True when the bytes look like a PDF file."""
    return _HEADER in data[:_HEADER_SEARCH_WINDOW]


def protected_filename(filename: str) -> str:
    """ "rechnung.pdf" → "rechnung_geschuetzt.pdf"."""
    stem = os.path.splitext(os.path.basename(filename))[0] or "dokument"
    return f"{stem}{PROTECTED_SUFFIX}.pdf"


def protect_pdf(data: bytes, password: str) -> bytes:
    """Return the PDF encrypted with `password` as the open password.

    The document is cloned so pages, metadata and outlines survive; the owner
    password is left equal to the user password, so there is exactly one
    password to remember.
    """
    if not password:
        raise PdfProtectionError("Das Passwort darf nicht leer sein.")

    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise PdfProtectionError(
            f"Das Passwort ist zu lang (max. {MAX_PASSWORD_BYTES} Zeichen)."
        )

    if not is_pdf(data):
        raise PdfProtectionError("Die hochgeladene Datei ist kein PDF.")

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise PdfProtectionError(
            f"Das PDF konnte nicht gelesen werden ({exc})."
        ) from exc

    if reader.is_encrypted:
        raise PdfProtectionError(
            "Das PDF ist bereits passwortgeschützt und kann nicht erneut gesichert werden."
        )

    try:
        writer = PdfWriter(clone_from=reader)
        writer.encrypt(user_password=password, algorithm=_ALGORITHM)

        buffer = BytesIO()
        writer.write(buffer)
    except Exception as exc:
        raise PdfProtectionError(
            f"Das PDF konnte nicht gesichert werden ({exc})."
        ) from exc

    return buffer.getvalue()
