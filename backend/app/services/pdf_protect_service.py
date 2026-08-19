"""Puts an open password on an uploaded PDF."""

from io import BytesIO

from app.core.pdf_utils import PdfProtectionError, protect_pdf, protected_filename
from app.schemas.pdf_protect import ProtectedPdf


def protect_uploaded_pdf(content: bytes, filename: str, password: str) -> ProtectedPdf:
    """Encrypt `content` with `password` and name the result after the upload.

    Raises `PdfProtectionError` for anything the user can fix (not a PDF,
    already protected, empty password); the api layer turns that into a 400.
    Nothing here is logged — the password must not end up in any log line.
    """
    protected = protect_pdf(content, password)

    return ProtectedPdf(
        buffer=BytesIO(protected),
        filename=protected_filename(filename),
    )


__all__ = ["PdfProtectionError", "protect_uploaded_pdf"]
