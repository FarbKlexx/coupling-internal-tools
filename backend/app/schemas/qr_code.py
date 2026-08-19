from dataclasses import dataclass
from enum import Enum
from io import BytesIO

from pydantic import BaseModel, Field

# Generous upper bound — the real limit depends on the encoding and is enforced
# by the encoder, which reports it with a readable message.
_MAX_PAYLOAD = 4000


class QrCodeFormat(str, Enum):
    PNG = "png"
    SVG = "svg"


class QrCodeRequest(BaseModel):
    """Link (or any text) plus the output options offered in the UI."""

    data: str = Field(min_length=1, max_length=_MAX_PAYLOAD)
    format: QrCodeFormat = QrCodeFormat.PNG
    transparent: bool = False
    # Off by default: the code ends flush with the image edge and the layout it
    # is placed in supplies the whitespace. Turn on for a standalone code.
    quiet_zone: bool = False


@dataclass
class QrCodeResult:
    """Rendered QR code, ready for the api layer to stream out."""

    buffer: BytesIO
    media_type: str
    filename: str
