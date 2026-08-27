"""Pure image helpers: format detection, scaling, WebP encoding and estimation.

Kept free of FastAPI/zip concerns so the conversion logic can be reused and
unit-tested on its own (mirrors how `csv_utils` sits under the CSV services).
"""

import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from PIL import Image, ImageOps, ImageSequence

try:  # HEIC/HEIF support is optional at runtime, mandatory in requirements.txt
    import pillow_heif

    pillow_heif.register_heif_opener()
    _HEIF_AVAILABLE = True
except ImportError:  # pragma: no cover - only hit on an incomplete install
    _HEIF_AVAILABLE = False

# Extensions we accept as input. Matching is case-insensitive, so ".JPG" works.
# WebP itself is included on purpose: re-encoding an existing WebP with a lower
# quality is a valid way to shrink it further.
_BASE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".jpe",
        ".png",
        ".webp",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
    }
)

# Only decodable once pillow-heif has registered its opener.
_HEIF_EXTENSIONS: frozenset[str] = frozenset({".heic", ".heif"})

# Formats in which more than one frame means "animation". Deliberately an
# allowlist: see `_is_animated`.
_ANIMATED_FORMATS: frozenset[str] = frozenset({"GIF", "WEBP", "PNG", "APNG", "AVIF"})

SUPPORTED_EXTENSIONS: frozenset[str] = _BASE_EXTENSIONS | (
    _HEIF_EXTENSIONS if _HEIF_AVAILABLE else frozenset()
)

MIN_QUALITY = 1
MAX_QUALITY = 100
DEFAULT_QUALITY = 80

# Resolution in percent of the original edge length. 100 = untouched; the lower
# bound keeps a thumbnail recognisable and bounds the rounding below.
MIN_SCALE = 10
MAX_SCALE = 100
DEFAULT_SCALE = 100

# Pillow's default encoder effort (0 fast … 6 slow).
_ENCODER_METHOD = 4

# Downscaling filter. LANCZOS is the sharpest of the area-averaging filters and
# the one Pillow recommends for shrinking; anything cheaper aliases visibly on
# logos and text, which is most of what goes through this tool.
_RESAMPLING = Image.Resampling.LANCZOS

# Hard limit of the WebP format itself — libwebp refuses anything larger with
# "encoding error 5", which is not a Pillow bug and cannot be worked around.
WEBP_MAX_DIMENSION = 16383

# Quality steps measured for the size estimate. The frontend interpolates
# linearly between them (max. ~7 % off in between, ~1 % on average); the extra
# steps around 75 and 90 pin the kinks in libwebp's size/quality curve.
ESTIMATE_QUALITIES: tuple[int, ...] = (1, 10, 25, 40, 55, 70, 75, 85, 90, 95, 100)

# Coarser grid for larger images: measuring costs ~0.2 s and ~40 MB of peak
# memory per megapixel *per step*, so the full grid stops being affordable long
# before the pixel budget below is reached. Interpolating over these steps is a
# little less precise (~7 % instead of ~3 % between the steps) and still exact
# on them.
ESTIMATE_QUALITIES_COARSE: tuple[int, ...] = (1, 25, 55, 75, 90, 100)
_COARSE_ABOVE_PIXELS = 6_000_000

# Above this *target* resolution no size preview is measured at all. A single
# 60 MP encode takes ~12 s and peaks at ~2.8 GB, and the estimate needs one per
# quality step — that OOM-kills the container instead of previewing anything,
# which used to take the following conversion down with it. Note this is
# measured on the scaled target, so pulling the resolution slider down brings
# the preview back.
ESTIMATE_PIXEL_BUDGET = 12_000_000

# Encoding one image at every step is CPU-bound but Pillow releases the GIL
# during WebP encoding, so the steps run concurrently (~4x on a typical box).
# Every worker holds its own copy of the decoded image *and* libwebp's working
# buffers, so the parallelism is bounded by pixels, not by cores: four workers
# on a 12 MP image peaked at 1.8 GB, four on a 60 MP image at 4.3 GB.
_ESTIMATE_MAX_WORKERS = min(4, os.cpu_count() or 1)
_ESTIMATE_CONCURRENT_PIXELS = 16_000_000


class ImageConversionError(Exception):
    """Raised when a single image cannot be decoded or re-encoded."""


@dataclass(frozen=True)
class SizeEstimate:
    """Measured WebP sizes of one image plus the pixel size behind them.

    `sizes` maps quality → byte size. `source` is the decoded size (after EXIF
    rotation, so it is what the user sees), `target` the size after scaling —
    equal to `source` at 100 %.

    `measured` is False when the target resolution is over `ESTIMATE_PIXEL_BUDGET`:
    the resolutions are reported, `sizes` stays empty, and nothing was encoded.
    That is not an error — such a file converts normally, it just gets no
    preview.
    """

    sizes: dict[int, int]
    source: tuple[int, int]
    target: tuple[int, int]
    measured: bool = True


def is_supported(filename: str) -> bool:
    """True when the filename carries an extension we can decode."""
    return os.path.splitext(filename)[1].lower() in SUPPORTED_EXTENSIONS


def webp_filename(filename: str) -> str:
    """Swap any extension for ".webp", keeping the original stem."""
    stem = os.path.splitext(os.path.basename(filename))[0] or "bild"
    return f"{stem}.webp"


def clamp_quality(quality: int) -> int:
    return max(MIN_QUALITY, min(MAX_QUALITY, quality))


def clamp_scale(scale: int) -> int:
    return max(MIN_SCALE, min(MAX_SCALE, scale))


def scaled_size(size: tuple[int, int], scale: int) -> tuple[int, int]:
    """Pixel size of `size` reduced to `scale` percent.

    Never returns a zero edge — a 1-pixel-wide image stays 1 pixel wide instead
    of becoming undecodable.
    """
    if scale >= MAX_SCALE:
        return size

    width, height = size
    return (
        max(1, round(width * scale / 100)),
        max(1, round(height * scale / 100)),
    )


def max_scale_for_webp(size: tuple[int, int]) -> int:
    """Largest whole-percent scale whose result still fits inside WebP's limit."""
    longest = max(size)
    if longest <= WEBP_MAX_DIMENSION:
        return MAX_SCALE

    # Floor, so the result is guaranteed to fit rather than land on the limit.
    return max(0, int(WEBP_MAX_DIMENSION * 100 / longest))


def _check_encodable(size: tuple[int, int]) -> None:
    """Refuse a target size WebP cannot store, naming the way out.

    Clamping the resolution silently would hand back a file the user did not
    ask for, so this is an error with the scale that would work in the message.
    """
    if max(size) <= WEBP_MAX_DIMENSION:
        return

    usable = max_scale_for_webp(size)
    hint = (
        f" Mit höchstens {usable} % Auflösung passt es."
        if usable >= MIN_SCALE
        else " Das Bild ist auch verkleinert zu groß für WebP."
    )
    raise ImageConversionError(
        f"{size[0]}×{size[1]} px überschreitet die WebP-Grenze von "
        f"{WEBP_MAX_DIMENSION} px pro Kante.{hint}"
    )


def _readable(exc: Exception) -> str:
    """German text for the failure modes that big images actually hit."""
    if isinstance(exc, Image.DecompressionBombError):
        return (
            "Das Bild hat so viele Pixel, dass Pillow es als Speicherfalle "
            "einstuft und nicht dekodiert."
        )
    if isinstance(exc, MemoryError):
        return "Nicht genug Speicher, um das Bild zu verarbeiten."
    return str(exc)


def _estimate_workers(pixels: int) -> int:
    """Parallelism for one image's quality steps, bounded by its pixel count."""
    if pixels <= 0:
        return 1

    affordable = _ESTIMATE_CONCURRENT_PIXELS // pixels
    return max(1, min(_ESTIMATE_MAX_WORKERS, affordable))


def _estimate_steps(pixels: int, qualities: tuple[int, ...]) -> list[int]:
    """Quality steps to measure — thinned out for larger images."""
    grid = qualities
    if pixels > _COARSE_ABOVE_PIXELS and grid == ESTIMATE_QUALITIES:
        grid = ESTIMATE_QUALITIES_COARSE

    return sorted({clamp_quality(quality) for quality in grid})


def _target_mode(image: Image.Image) -> str:
    """WebP only stores RGB/RGBA — pick the one that keeps transparency."""
    has_alpha = image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    )
    return "RGBA" if has_alpha else "RGB"


def _prepare(image: Image.Image) -> Image.Image:
    """Apply EXIF orientation and move the image into a WebP-compatible mode."""
    prepared = ImageOps.exif_transpose(image) or image

    target = _target_mode(prepared)
    if prepared.mode != target:
        prepared = prepared.convert(target)

    return prepared


def _resize(image: Image.Image, scale: int) -> Image.Image:
    """Scale an image down by `scale` percent (no-op at 100 % or below 1 px)."""
    target = scaled_size(image.size, scale)
    return image if target == image.size else image.resize(target, _RESAMPLING)


def _metadata(image: Image.Image) -> dict[str, bytes]:
    """EXIF/ICC payloads worth carrying over into the WebP file."""
    carried: dict[str, bytes] = {}
    for key in ("exif", "icc_profile"):
        value = image.info.get(key)
        if value:
            carried[key] = value
    return carried


def _encode(
    image: Image.Image,
    quality: int,
    *,
    metadata: dict[str, bytes] | None = None,
    save_all: bool = False,
) -> bytes:
    buffer = io.BytesIO()
    image.save(
        buffer,
        format="WEBP",
        quality=quality,
        method=_ENCODER_METHOD,
        save_all=save_all,
        **(metadata or {}),
    )
    return buffer.getvalue()


def _encode_animation(
    image: Image.Image,
    quality: int,
    scale: int,
    metadata: dict[str, bytes] | None = None,
) -> bytes:
    """Re-encode an animation frame by frame, scaled down.

    Only used when the resolution actually changes: Pillow can hand a whole
    animation to the WebP encoder in one go (`save_all`), but not a scaled one —
    resizing has to happen per frame, and then the timing has to be re-attached
    by hand because the resized frames carry no `duration` any more.
    """
    frames: list[Image.Image] = []
    durations: list[int] = []
    fallback_duration = image.info.get("duration", 0)

    for frame in ImageSequence.Iterator(image):
        durations.append(frame.info.get("duration", fallback_duration))
        frames.append(_resize(frame.convert(_target_mode(frame)), scale))

    first, *rest = frames
    buffer = io.BytesIO()
    first.save(
        buffer,
        format="WEBP",
        quality=quality,
        method=_ENCODER_METHOD,
        save_all=True,
        append_images=rest,
        duration=durations,
        loop=image.info.get("loop", 0),
        **(metadata or {}),
    )
    return buffer.getvalue()


def _is_animated(image: Image.Image) -> bool:
    """True only for formats where several frames really mean an animation.

    `n_frames > 1` alone is not that test. An HDR photo from a modern camera or
    phone is an MPO — the JPEG carries a second image (the gain map, or the
    other exposure) next to the main one — and a scanned TIFF carries pages.
    Handing those to the WebP encoder as an animation fails outright, because
    the extra image has its own dimensions: "ERROR adding frame: Invalid frame
    dimensions". Such files are stills; the first image is the picture, the rest
    is baggage WebP has no place for.
    """
    if getattr(image, "n_frames", 1) <= 1:
        return False

    return (image.format or "").upper() in _ANIMATED_FORMATS


def convert_to_webp(
    data: bytes,
    quality: int = DEFAULT_QUALITY,
    scale: int = DEFAULT_SCALE,
) -> bytes:
    """Encode raw image bytes as WebP, optionally at a reduced resolution.

    `scale` is applied first (percent of the original edge length, 100 = keep
    the resolution), `quality` is the lossy WebP quality of the encode that
    follows (1 = strongest compression / most loss, 100 = near-lossless). EXIF
    orientation is applied up front so photos from phones are not rotated, and
    EXIF/ICC metadata is carried over.
    """
    quality = clamp_quality(quality)
    scale = clamp_scale(scale)

    try:
        with Image.open(io.BytesIO(data)) as image:
            if _is_animated(image):
                metadata = _metadata(image)
                _check_encodable(scaled_size(image.size, scale))
                # exif_transpose() drops frames, so an unscaled animation keeps
                # its raw data and goes to the encoder in one piece.
                if scale >= MAX_SCALE:
                    return _encode(image, quality, metadata=metadata, save_all=True)
                return _encode_animation(image, quality, scale, metadata)

            prepared = _prepare(image)
            metadata = _metadata(prepared)
            target = _resize(prepared, scale)
            _check_encodable(target.size)
            return _encode(target, quality, metadata=metadata)
    except ImageConversionError:
        raise
    except Exception as exc:  # Pillow raises a wide range of errors here
        raise ImageConversionError(_readable(exc)) from exc


def estimate_webp_sizes(
    data: bytes,
    qualities: tuple[int, ...] = ESTIMATE_QUALITIES,
    scale: int = DEFAULT_SCALE,
) -> SizeEstimate:
    """Measure the WebP byte size of one image at several quality steps.

    The numbers are exact: every step goes through the same encode path as
    `convert_to_webp`, so the frontend can show what a given quality/resolution
    setting really costs before the user converts anything. Decoding and scaling
    happen once, the encodes run in parallel — with a parallelism and a step
    count that shrink as the image grows.

    Beyond `ESTIMATE_PIXEL_BUDGET` target pixels nothing is encoded at all and
    the result carries `measured=False`: at that size one encode alone costs
    seconds and gigabytes, and measuring a dozen of them killed the process
    that was supposed to do the conversion afterwards.
    """
    scale = clamp_scale(scale)

    try:
        with Image.open(io.BytesIO(data)) as image:
            if _is_animated(image):
                return _estimate_animation(image, qualities, scale)

            prepared = _prepare(image)
            source = prepared.size
            target = scaled_size(source, scale)

            # Checked before the budget below, so a file the conversion would
            # reject is reported as an error either way — the frontend relies on
            # estimate and conversion agreeing on what gets skipped.
            _check_encodable(target)

            pixels = target[0] * target[1]
            if pixels > ESTIMATE_PIXEL_BUDGET:
                return SizeEstimate(
                    sizes={}, source=source, target=target, measured=False
                )

            metadata = _metadata(prepared)
            scaled = _resize(prepared, scale)
            steps = _estimate_steps(pixels, qualities)

            # Pillow stashes the encoder parameters on the image instance, so
            # two threads saving the *same* instance would overwrite each
            # other's quality. Each worker therefore gets its own copy.
            local = threading.local()

            def encoded_size(quality: int) -> int:
                own = getattr(local, "image", None)
                if own is None:
                    own = local.image = scaled.copy()
                return len(_encode(own, quality, metadata=metadata))

            with ThreadPoolExecutor(max_workers=_estimate_workers(pixels)) as pool:
                sizes = list(pool.map(encoded_size, steps))

            return SizeEstimate(
                sizes=dict(zip(steps, sizes, strict=True)),
                source=source,
                target=scaled.size,
            )
    except ImageConversionError:
        raise
    except Exception as exc:
        raise ImageConversionError(_readable(exc)) from exc


def _estimate_animation(
    image: Image.Image, qualities: tuple[int, ...], scale: int
) -> SizeEstimate:
    """Size curve of an animation — sequential, on the shared source image.

    Animations cannot use the copy-per-worker trick above: `Image.copy()` keeps
    only the current frame, which would measure a single-frame file and report a
    fraction of what the conversion produces. Seeking through the frames is not
    thread-safe either, so the steps are encoded one after another. Animations
    are rare here; correctness beats the parallelism.

    The pixel budget counts every frame, because that is what an encode of an
    animation actually costs.
    """
    source = image.size
    target = scaled_size(source, scale)
    _check_encodable(target)

    pixels = target[0] * target[1] * getattr(image, "n_frames", 1)
    if pixels > ESTIMATE_PIXEL_BUDGET:
        return SizeEstimate(sizes={}, source=source, target=target, measured=False)

    metadata = _metadata(image)
    unscaled = scale >= MAX_SCALE

    sizes = {
        quality: len(
            _encode(image, quality, metadata=metadata, save_all=True)
            if unscaled
            else _encode_animation(image, quality, scale, metadata)
        )
        for quality in _estimate_steps(pixels, qualities)
    }

    return SizeEstimate(sizes=sizes, source=source, target=target)
