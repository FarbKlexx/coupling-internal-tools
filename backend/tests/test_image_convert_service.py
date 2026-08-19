import zipfile
from io import BytesIO

import pytest
from PIL import Image

from app.core.image_utils import (
    ImageConversionError,
    convert_to_webp,
    estimate_webp_sizes,
    webp_filename,
)
from app.services.image_convert_service import (
    SKIP_REPORT_NAME,
    convert_images_to_webp,
    estimate_image_sizes,
)


def _image_bytes(fmt: str = "PNG", mode: str = "RGB", size=(32, 24)) -> bytes:
    buffer = BytesIO()
    Image.new(mode, size, color="red").save(buffer, format=fmt)
    return buffer.getvalue()


def _source(name: str, data: bytes):
    return name, BytesIO(data)


def test_convert_to_webp_produces_webp_of_same_size():
    result = convert_to_webp(_image_bytes(), quality=70)

    with Image.open(BytesIO(result)) as image:
        assert image.format == "WEBP"
        assert image.size == (32, 24)


def test_convert_to_webp_lower_quality_produces_smaller_file():
    # A flat colour compresses to almost nothing, so use noise-ish content.
    buffer = BytesIO()
    source = Image.new("RGB", (200, 200))
    source.putdata(
        [
            (x * 7 % 256, y * 13 % 256, (x + y) % 256)
            for y in range(200)
            for x in range(200)
        ]
    )
    source.save(buffer, format="PNG")
    data = buffer.getvalue()

    assert len(convert_to_webp(data, quality=10)) < len(
        convert_to_webp(data, quality=95)
    )


def test_convert_to_webp_keeps_transparency():
    buffer = BytesIO()
    Image.new("RGBA", (32, 24), (255, 0, 0, 0)).save(buffer, format="PNG")

    result = convert_to_webp(buffer.getvalue())

    with Image.open(BytesIO(result)) as image:
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0


def test_convert_to_webp_rejects_non_image_bytes():
    with pytest.raises(ImageConversionError):
        convert_to_webp(b"definitiv kein bild")


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("foto.JPG", "foto.webp"),
        ("bild.jpeg", "bild.webp"),
        ("pfad/zum/logo.png", "logo.webp"),
        ("ohne-endung", "ohne-endung.webp"),
    ],
)
def test_webp_filename(filename, expected):
    assert webp_filename(filename) == expected


def test_bulk_conversion_zips_every_image():
    result = convert_images_to_webp(
        [
            _source("a.png", _image_bytes()),
            _source("b.jpg", _image_bytes(fmt="JPEG")),
        ]
    )

    assert result.converted == ["a.webp", "b.webp"]
    assert result.skipped == []

    with zipfile.ZipFile(result.archive) as zip_file:
        assert zip_file.namelist() == ["a.webp", "b.webp"]


def test_bulk_conversion_deduplicates_colliding_names():
    result = convert_images_to_webp(
        [
            _source("logo.png", _image_bytes()),
            _source("logo.jpg", _image_bytes(fmt="JPEG")),
            _source("logo.bmp", _image_bytes(fmt="BMP")),
        ]
    )

    assert result.converted == ["logo.webp", "logo_2.webp", "logo_3.webp"]


def test_bulk_conversion_skips_bad_files_but_keeps_the_rest():
    result = convert_images_to_webp(
        [
            _source("gut.png", _image_bytes()),
            _source("notiz.txt", b"kein bild"),
            _source("kaputt.png", b"kein bild"),
        ]
    )

    assert result.converted == ["gut.webp"]
    assert [item.filename for item in result.skipped] == ["notiz.txt", "kaputt.png"]

    with zipfile.ZipFile(result.archive) as zip_file:
        report = zip_file.read(SKIP_REPORT_NAME).decode("utf-8")

    assert "notiz.txt" in report and "kaputt.png" in report


def test_bulk_conversion_of_only_bad_files_yields_no_entries():
    result = convert_images_to_webp([_source("notiz.txt", b"kein bild")])

    assert result.converted == []
    assert len(result.skipped) == 1


def test_estimate_matches_the_real_conversion_size():
    data = _image_bytes()

    samples = estimate_webp_sizes(data, qualities=(20, 60, 100))

    assert set(samples) == {20, 60, 100}
    for quality, size in samples.items():
        assert size == len(convert_to_webp(data, quality))


def test_estimate_shrinks_with_lower_quality():
    buffer = BytesIO()
    noisy = Image.new("RGB", (200, 200))
    noisy.putdata(
        [
            (x * 7 % 256, y * 13 % 256, (x + y) % 256)
            for y in range(200)
            for x in range(200)
        ]
    )
    noisy.save(buffer, format="PNG")

    samples = estimate_webp_sizes(buffer.getvalue())
    qualities = sorted(samples)

    assert all(
        samples[low] <= samples[high]
        for low, high in zip(qualities, qualities[1:], strict=False)
    )


def test_estimate_is_stable_across_runs():
    # The sampled qualities are encoded in parallel; each worker must keep its
    # own encoder state, otherwise sizes bleed between quality steps.
    data = _image_bytes(fmt="JPEG", size=(400, 300))

    assert estimate_webp_sizes(data) == estimate_webp_sizes(data)


def test_estimate_image_sizes_reports_originals_and_errors():
    estimates = estimate_image_sizes(
        [
            _source("foto.jpeg", _image_bytes(fmt="JPEG")),
            _source("notiz.txt", b"kein bild"),
            _source("kaputt.png", b"kein bild"),
        ],
        qualities=(50,),
    )

    assert [e.filename for e in estimates] == ["foto.jpeg", "notiz.txt", "kaputt.png"]
    assert estimates[0].supported and estimates[0].samples[50] > 0
    assert estimates[0].original_size == len(_image_bytes(fmt="JPEG"))
    assert not estimates[1].supported and estimates[1].samples == {}
    assert not estimates[2].supported


def test_estimate_and_conversion_agree_on_which_files_are_skipped():
    files = [
        ("foto.jpeg", _image_bytes(fmt="JPEG")),
        ("notiz.txt", b"kein bild"),
        ("logo.png", _image_bytes()),
    ]

    estimates = estimate_image_sizes(
        [_source(name, data) for name, data in files], qualities=(80,)
    )
    result = convert_images_to_webp([_source(name, data) for name, data in files])

    estimated_as_skipped = {e.filename for e in estimates if not e.supported}
    actually_skipped = {item.filename for item in result.skipped}

    assert estimated_as_skipped == actually_skipped == {"notiz.txt"}
    assert [e.filename for e in estimates if e.supported] == ["foto.jpeg", "logo.png"]
