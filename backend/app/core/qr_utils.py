"""Pure QR helpers: matrix generation plus PNG/SVG rendering.

The `qrcode` package only produces the module matrix here — rendering is done
by hand so the background can be dropped entirely (transparent PNG, no
background rect in the SVG) and the SVG stays a single compact path.
"""

import io
import re

import qrcode
from PIL import Image
from qrcode.exceptions import DataOverflowError

# Quiet zone in modules. The QR spec asks for four, and scanners get less
# reliable below that — but the generated file is meant to be placed in a
# layout that already provides the surrounding whitespace, so the default is a
# flush code with no padding of its own. `QUIET_ZONE_MODULES` is what the spec
# asks for and what a standalone code (one that has to scan on its own) needs.
DEFAULT_BORDER = 0
QUIET_ZONE_MODULES = 4

# Medium recovers ~15 % of a damaged code — the usual default for print.
_ERROR_CORRECTION = qrcode.constants.ERROR_CORRECT_M

# Rendered edge length in pixels. The PNG is scaled by whole modules, so the
# result lands near this value instead of exactly on it — that keeps every
# module the same pixel size and the edges crisp.
TARGET_SIZE = 1024

_BLACK = (0, 0, 0, 255)
_WHITE = (255, 255, 255, 255)
_TRANSPARENT = (255, 255, 255, 0)

_SLUG_STRIP = re.compile(r"^(?:\w+://)?(?:www\.)?", re.IGNORECASE)
_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")


class QrCodeError(Exception):
    """Raised when the payload cannot be encoded as a QR code."""


def build_matrix(data: str, border: int = DEFAULT_BORDER) -> list[list[bool]]:
    """Encode `data` and return the module matrix.

    `border` is the quiet zone in modules, 0 by default — the code ends flush
    with the image edge and the surrounding whitespace comes from wherever it
    is placed.
    """
    if not data.strip():
        raise QrCodeError("Es wurde kein Inhalt übergeben.")

    qr = qrcode.QRCode(error_correction=_ERROR_CORRECTION, border=max(0, border))
    qr.add_data(data)

    try:
        qr.make(fit=True)
    except (DataOverflowError, ValueError) as exc:
        raise QrCodeError(
            "Der Inhalt ist zu lang für einen QR-Code (max. ca. 2300 Zeichen)."
        ) from exc

    return qr.get_matrix()


def _scale_for(modules: int) -> int:
    """Whole-pixel size of one module, so the result has no resampling blur."""
    return max(1, round(TARGET_SIZE / modules))


def matrix_to_png(matrix: list[list[bool]], transparent: bool = False) -> bytes:
    """Render the matrix as a PNG, optionally without a background."""
    modules = len(matrix)
    background = _TRANSPARENT if transparent else _WHITE

    # One pixel per module, then scaled up with NEAREST — every module ends up
    # exactly `scale` pixels wide, no interpolation at the edges.
    source = Image.new("RGBA", (modules, modules))
    source.putdata([_BLACK if cell else background for row in matrix for cell in row])

    scale = _scale_for(modules)
    image = source.resize((modules * scale, modules * scale), Image.Resampling.NEAREST)
    if not transparent:
        image = image.convert("RGB")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _row_runs(row: list[bool]) -> list[tuple[int, int]]:
    """Consecutive dark modules of one row as (start, length) pairs."""
    runs: list[tuple[int, int]] = []
    start: int | None = None

    for x, cell in enumerate(row):
        if cell and start is None:
            start = x
        elif not cell and start is not None:
            runs.append((start, x - start))
            start = None

    if start is not None:
        runs.append((start, len(row) - start))

    return runs


def matrix_to_svg(matrix: list[list[bool]], transparent: bool = False) -> str:
    """Render the matrix as an SVG whose coordinate system is one unit per module.

    Neighbouring dark modules are merged into one horizontal run, which keeps
    the path roughly an order of magnitude shorter than one rect per module.
    """
    modules = len(matrix)
    segments = [
        f"M{x} {y}h{length}v1h-{length}z"
        for y, row in enumerate(matrix)
        for x, length in _row_runs(row)
    ]

    background = (
        "" if transparent else '<rect width="100%" height="100%" fill="#ffffff"/>'
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{TARGET_SIZE}" '
        f'height="{TARGET_SIZE}" viewBox="0 0 {modules} {modules}" '
        'shape-rendering="crispEdges">'
        f"{background}"
        f'<path fill="#000000" d="{"".join(segments)}"/>'
        "</svg>\n"
    )


def filename_stem(data: str) -> str:
    """Readable file stem derived from the payload, e.g. "qr_coupling-media"."""
    slug = _SLUG_CLEAN.sub("-", _SLUG_STRIP.sub("", data.strip()).lower()).strip("-")
    return f"qr_{slug[:40].rstrip('-')}" if slug else "qr-code"
