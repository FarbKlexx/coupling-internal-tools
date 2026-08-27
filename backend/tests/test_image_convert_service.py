import zipfile
from io import BytesIO

import pytest
from PIL import Image

from app.core.image_utils import (
    MAX_SCALE,
    MIN_SCALE,
    ImageConversionError,
    clamp_scale,
    convert_to_webp,
    estimate_webp_sizes,
    scaled_size,
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

    samples = estimate_webp_sizes(data, qualities=(20, 60, 100)).sizes

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

    samples = estimate_webp_sizes(buffer.getvalue()).sizes
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


def _noisy_png_bytes(size=(200, 200)) -> bytes:
    """A PNG that does not compress to nothing — needed to compare sizes."""
    width, height = size
    image = Image.new("RGB", size)
    image.putdata(
        [
            (x * 7 % 256, y * 13 % 256, (x + y) % 256)
            for y in range(height)
            for x in range(width)
        ]
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _animated_gif_bytes(frames: int = 3, size=(40, 30)) -> bytes:
    """A multi-frame GIF, so the animation paths get exercised."""
    images = [
        Image.new("RGB", size, color=(index * 60 % 256, 40, 200))
        for index in range(frames)
    ]

    buffer = BytesIO()
    images[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=120,
        loop=0,
    )
    return buffer.getvalue()


@pytest.mark.parametrize(
    "size,scale,expected",
    [
        ((1000, 500), 100, (1000, 500)),
        ((1000, 500), 50, (500, 250)),
        ((1000, 500), 25, (250, 125)),
        ((3, 3), 10, (1, 1)),  # rounds to 0 without the floor
        ((1, 1), 10, (1, 1)),
        ((101, 101), 33, (33, 33)),
    ],
)
def test_scaled_size(size, scale, expected):
    assert scaled_size(size, scale) == expected


@pytest.mark.parametrize(
    "scale,expected", [(0, MIN_SCALE), (5, MIN_SCALE), (50, 50), (400, MAX_SCALE)]
)
def test_clamp_scale(scale, expected):
    assert clamp_scale(scale) == expected


def test_convert_to_webp_scales_the_resolution_down():
    result = convert_to_webp(_image_bytes(size=(400, 300)), quality=80, scale=50)

    with Image.open(BytesIO(result)) as image:
        assert image.format == "WEBP"
        assert image.size == (200, 150)


def test_convert_to_webp_at_full_scale_keeps_the_resolution():
    data = _image_bytes(size=(400, 300))

    assert convert_to_webp(data, 80, 100) == convert_to_webp(data, 80)


def test_convert_to_webp_clamps_an_out_of_range_scale():
    with Image.open(
        BytesIO(convert_to_webp(_image_bytes(size=(400, 300)), 80, 0))
    ) as i:
        assert i.size == scaled_size((400, 300), MIN_SCALE)


def test_scaling_shrinks_the_file_at_the_same_quality():
    data = _noisy_png_bytes()

    assert len(convert_to_webp(data, 80, 50)) < len(convert_to_webp(data, 80, 100))


def test_scaling_and_quality_compose():
    # Both steps have to bite: halving the edges and dropping the quality must
    # beat either one on its own.
    data = _noisy_png_bytes()

    both = len(convert_to_webp(data, 20, 50))
    assert both < len(convert_to_webp(data, 20, 100))
    assert both < len(convert_to_webp(data, 80, 50))


def test_scaling_keeps_transparency():
    buffer = BytesIO()
    Image.new("RGBA", (80, 60), (255, 0, 0, 0)).save(buffer, format="PNG")

    with Image.open(BytesIO(convert_to_webp(buffer.getvalue(), 80, 50))) as image:
        assert image.mode == "RGBA"
        assert image.size == (40, 30)
        assert image.getpixel((0, 0))[3] == 0


def test_scaling_an_animation_keeps_every_frame():
    result = convert_to_webp(_animated_gif_bytes(frames=3), quality=80, scale=50)

    with Image.open(BytesIO(result)) as image:
        assert image.format == "WEBP"
        assert image.n_frames == 3
        assert image.size == (20, 15)


def test_bulk_conversion_applies_the_scale_to_every_image():
    result = convert_images_to_webp(
        [
            _source("a.png", _image_bytes(size=(400, 300))),
            _source("b.jpg", _image_bytes(fmt="JPEG", size=(200, 200))),
        ],
        quality=80,
        scale=25,
    )

    with zipfile.ZipFile(result.archive) as zip_file:
        sizes = []
        for name in result.converted:
            with Image.open(BytesIO(zip_file.read(name))) as image:
                sizes.append(image.size)

    assert sizes == [(100, 75), (50, 50)]


def test_estimate_reports_source_and_target_resolution():
    estimate = estimate_webp_sizes(
        _image_bytes(size=(400, 300)), qualities=(80,), scale=50
    )

    assert estimate.source == (400, 300)
    assert estimate.target == (200, 150)


def test_estimate_matches_the_real_conversion_size_at_a_reduced_scale():
    data = _noisy_png_bytes()

    estimate = estimate_webp_sizes(data, qualities=(20, 60, 100), scale=40)

    for quality, size in estimate.sizes.items():
        assert size == len(convert_to_webp(data, quality, 40))


def test_estimate_of_an_animation_matches_the_real_conversion_size():
    # Animations cannot be estimated on per-thread image copies: a copy holds
    # only the current frame and would report a fraction of the real size.
    data = _animated_gif_bytes(frames=4)

    for scale in (100, 50):
        estimate = estimate_webp_sizes(data, qualities=(30, 90), scale=scale)
        for quality, size in estimate.sizes.items():
            assert size == len(convert_to_webp(data, quality, scale))


def test_estimate_shrinks_with_a_lower_resolution():
    data = _noisy_png_bytes()

    full = estimate_webp_sizes(data, qualities=(80,), scale=100)
    half = estimate_webp_sizes(data, qualities=(80,), scale=50)

    assert half.sizes[80] < full.sizes[80]


def test_estimate_image_sizes_carries_the_resolutions_through():
    estimates = estimate_image_sizes(
        [
            _source("foto.jpeg", _image_bytes(fmt="JPEG", size=(400, 300))),
            _source("notiz.txt", b"kein bild"),
        ],
        qualities=(50,),
        scale=50,
    )

    assert estimates[0].pixels == (400, 300)
    assert estimates[0].scaled_pixels == (200, 150)
    # A file that cannot be decoded has no resolution to report.
    assert estimates[1].pixels is None and estimates[1].scaled_pixels is None
