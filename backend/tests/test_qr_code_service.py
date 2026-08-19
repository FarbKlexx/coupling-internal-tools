import re
from io import BytesIO

import pytest
from PIL import Image

from app.core.qr_utils import (
    DEFAULT_BORDER,
    TARGET_SIZE,
    QrCodeError,
    build_matrix,
    filename_stem,
    matrix_to_png,
    matrix_to_svg,
)
from app.schemas.qr_code import QrCodeFormat, QrCodeRequest
from app.services.qr_code_service import generate_qr_code

LINK = "https://www.coupling.media/sommer-sale"


def _matrix_from_svg(svg: str, modules: int) -> list[list[bool]]:
    """Rebuild the module matrix from the runs in the SVG path."""
    rebuilt = [[False] * modules for _ in range(modules)]

    for raw_x, raw_y, raw_length in re.findall(r"M(\d+) (\d+)h(\d+)", svg):
        x, y, length = int(raw_x), int(raw_y), int(raw_length)
        for offset in range(length):
            rebuilt[y][x + offset] = True

    return rebuilt


def test_matrix_is_square_and_starts_flush_by_default():
    matrix = build_matrix(LINK)

    assert DEFAULT_BORDER == 0
    assert len(matrix) == len(matrix[0])
    # No quiet zone: the top-left finder pattern touches the very first module.
    assert matrix[0][0]
    assert matrix[0][6] and not matrix[0][7]


def test_border_adds_a_quiet_zone_on_every_side():
    flush = build_matrix(LINK)
    bordered = build_matrix(LINK, border=4)

    assert len(bordered) == len(flush) + 8
    assert not any(bordered[y][x] for y in range(4) for x in range(len(bordered)))
    assert not any(bordered[y][x] for y in range(len(bordered)) for x in range(4))
    assert not any(bordered[-y - 1][x] for y in range(4) for x in range(len(bordered)))
    assert not any(bordered[y][-x - 1] for y in range(len(bordered)) for x in range(4))


def test_empty_payload_is_rejected():
    with pytest.raises(QrCodeError):
        build_matrix("   ")


def test_overlong_payload_is_rejected_with_a_readable_message():
    with pytest.raises(QrCodeError, match="zu lang"):
        build_matrix("x" * 4000)


def test_png_is_scaled_by_whole_modules():
    matrix = build_matrix(LINK)

    with Image.open(BytesIO(matrix_to_png(matrix))) as image:
        assert image.width == image.height
        assert image.width % len(matrix) == 0
        assert abs(image.width - TARGET_SIZE) < len(matrix)


def test_png_background_follows_the_transparency_flag():
    matrix = build_matrix(LINK)

    # Without a quiet zone the corner is a dark module, so probe a light one:
    # the gap right of the top-left finder pattern.
    scale = len(matrix)
    light = (int(TARGET_SIZE / scale * 7.5), int(TARGET_SIZE / scale * 0.5))

    with Image.open(BytesIO(matrix_to_png(matrix))) as opaque:
        assert opaque.mode == "RGB"
        assert opaque.getpixel((0, 0)) == (0, 0, 0)
        assert opaque.getpixel(light) == (255, 255, 255)

    with Image.open(BytesIO(matrix_to_png(matrix, transparent=True))) as clear:
        assert clear.mode == "RGBA"
        # Dark modules stay fully opaque, light ones vanish completely.
        assert clear.getpixel((0, 0)) == (0, 0, 0, 255)
        assert clear.getpixel(light)[3] == 0


def test_svg_encodes_the_same_matrix_as_the_png():
    matrix = build_matrix(LINK)

    svg = matrix_to_svg(matrix)

    assert _matrix_from_svg(svg, len(matrix)) == matrix
    assert f'viewBox="0 0 {len(matrix)} {len(matrix)}"' in svg


def test_svg_drops_the_background_rect_when_transparent():
    matrix = build_matrix(LINK)

    assert "<rect" in matrix_to_svg(matrix)
    assert "<rect" not in matrix_to_svg(matrix, transparent=True)


@pytest.mark.parametrize(
    "payload,expected",
    [
        ("https://www.coupling.media/sommer-sale", "qr_coupling-media-sommer-sale"),
        ("http://example.com", "qr_example-com"),
        ("Hallo Welt", "qr_hallo-welt"),
        ("äöü", "qr-code"),
    ],
)
def test_filename_stem(payload, expected):
    assert filename_stem(payload) == expected


def test_service_returns_png_by_default():
    result = generate_qr_code(QrCodeRequest(data=LINK))

    assert result.media_type == "image/png"
    assert result.filename == "qr_coupling-media-sommer-sale.png"
    assert result.buffer.getvalue().startswith(b"\x89PNG")


def test_service_returns_svg_when_asked():
    result = generate_qr_code(
        QrCodeRequest(data=LINK, format=QrCodeFormat.SVG, transparent=True)
    )

    assert result.media_type == "image/svg+xml"
    assert result.filename.endswith(".svg")
    assert result.buffer.getvalue().decode("utf-8").lstrip().startswith("<?xml")


def test_service_renders_flush_by_default_and_pads_on_request():
    flush = generate_qr_code(QrCodeRequest(data=LINK))
    padded = generate_qr_code(QrCodeRequest(data=LINK, quiet_zone=True))

    with Image.open(BytesIO(flush.buffer.getvalue())) as image:
        # First pixel is part of the finder pattern, so no padding at all.
        assert image.getpixel((0, 0)) == (0, 0, 0)

    with Image.open(BytesIO(padded.buffer.getvalue())) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_quiet_zone_option_reaches_the_svg():
    flush = generate_qr_code(QrCodeRequest(data=LINK, format=QrCodeFormat.SVG))
    padded = generate_qr_code(
        QrCodeRequest(data=LINK, format=QrCodeFormat.SVG, quiet_zone=True)
    )

    flush_modules = len(build_matrix(LINK))
    assert (
        f'viewBox="0 0 {flush_modules} {flush_modules}"'
        in flush.buffer.getvalue().decode()
    )
    assert (
        f'viewBox="0 0 {flush_modules + 8} {flush_modules + 8}"'
        in padded.buffer.getvalue().decode()
    )
