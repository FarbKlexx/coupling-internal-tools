"""Renders a QR code for a link or text in the format the UI asked for."""

from io import BytesIO

from app.core.qr_utils import (
    QUIET_ZONE_MODULES,
    QrCodeError,
    build_matrix,
    filename_stem,
    matrix_to_png,
    matrix_to_svg,
)
from app.schemas.qr_code import QrCodeFormat, QrCodeRequest, QrCodeResult

_MEDIA_TYPES = {
    QrCodeFormat.PNG: "image/png",
    QrCodeFormat.SVG: "image/svg+xml",
}


def generate_qr_code(request: QrCodeRequest) -> QrCodeResult:
    """Encode `request.data` and render it as PNG or SVG.

    Raises `QrCodeError` when the payload is empty or too long for a QR code;
    the api layer turns that into a 400.
    """
    matrix = build_matrix(
        request.data,
        border=QUIET_ZONE_MODULES if request.quiet_zone else 0,
    )

    if request.format is QrCodeFormat.SVG:
        payload = matrix_to_svg(matrix, transparent=request.transparent).encode("utf-8")
    else:
        payload = matrix_to_png(matrix, transparent=request.transparent)

    return QrCodeResult(
        buffer=BytesIO(payload),
        media_type=_MEDIA_TYPES[request.format],
        filename=f"{filename_stem(request.data)}.{request.format.value}",
    )


__all__ = ["QrCodeError", "generate_qr_code"]
