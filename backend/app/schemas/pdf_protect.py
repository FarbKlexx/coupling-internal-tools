from dataclasses import dataclass
from io import BytesIO


@dataclass
class ProtectedPdf:
    """Encrypted PDF, ready for the api layer to stream out."""

    buffer: BytesIO
    filename: str
