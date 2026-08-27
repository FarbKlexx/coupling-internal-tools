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

# Quality steps measured for the size estimate. The frontend interpolates
# linearly between them (max. ~7 % off in between, ~1 % on average); the extra
# steps around 75 and 90 pin the kinks in libwebp's size/quality curve.
ESTIMATE_QUALITIES: tuple[int, ...] = (1, 10, 25, 40, 55, 70, 75, 85, 90, 95, 100)

# Encoding one image at every step is CPU-bound but Pillow releases the GIL
# during WebP encoding, so the steps run concurrently (~4x on a typical box).
# Kept small on purpose: every worker holds its own copy of the decoded image,
# and several estimate requests may be in flight at once.
_ESTIMATE_WORKERS = min(4, os.cpu_count() or 1)


class ImageConversionError(Exception):
    """Raised when a single image cannot be decoded or re-encoded."""


@dataclass(frozen=True)
class SizeEstimate:
    """Measured WebP sizes of one image plus the pixel size behind them.

    `sizes` maps quality → byte size. `source` is the decoded size (after EXIF
    rotation, so it is what the user sees), `target` the size after scaling —
    equal to `source` at 100 %.
    """

    sizes: dict[int, int]
    source: tuple[int, int]
    target: tuple[int, int]


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
    return getattr(image, "n_frames", 1) > 1


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
                # exif_transpose() drops frames, so an unscaled animation keeps
                # its raw data and goes to the encoder in one piece.
                if scale >= MAX_SCALE:
                    return _encode(image, quality, metadata=metadata, save_all=True)
                return _encode_animation(image, quality, scale, metadata)

            prepared = _prepare(image)
            metadata = _metadata(prepared)
            return _encode(_resize(prepared, scale), quality, metadata=metadata)
    except ImageConversionError:
        raise
    except Exception as exc:  # Pillow raises a wide range of errors here
        raise ImageConversionError(str(exc)) from exc


def estimate_webp_sizes(
    data: bytes,
    qualities: tuple[int, ...] = ESTIMATE_QUALITIES,
    scale: int = DEFAULT_SCALE,
) -> SizeEstimate:
    """Measure the WebP byte size of one image at several quality steps.

    The numbers are exact: every step goes through the same encode path as
    `convert_to_webp`, so the frontend can show what a given quality/resolution
    setting really costs before the user converts anything. Decoding and scaling
    happen once, the encodes run in parallel.
    """
    steps = sorted({clamp_quality(q) for q in qualities})
    scale = clamp_scale(scale)

    try:
        with Image.open(io.BytesIO(data)) as image:
            if _is_animated(image):
                return _estimate_animation(image, steps, scale)

            prepared = _prepare(image)
            source = prepared.size
            metadata = _metadata(prepared)
            scaled = _resize(prepared, scale)

            # Pillow stashes the encoder parameters on the image instance, so
            # two threads saving the *same* instance would overwrite each
            # other's quality. Each worker therefore gets its own copy.
            local = threading.local()

            def encoded_size(quality: int) -> int:
                own = getattr(local, "image", None)
                if own is None:
                    own = local.image = scaled.copy()
                return len(_encode(own, quality, metadata=metadata))

            with ThreadPoolExecutor(max_workers=_ESTIMATE_WORKERS) as pool:
                sizes = list(pool.map(encoded_size, steps))

            return SizeEstimate(
                sizes=dict(zip(steps, sizes, strict=True)),
                source=source,
                target=scaled.size,
            )
    except ImageConversionError:
        raise
    except Exception as exc:
        raise ImageConversionError(str(exc)) from exc


def _estimate_animation(
    image: Image.Image, steps: list[int], scale: int
) -> SizeEstimate:
    """Size curve of an animation — sequential, on the shared source image.

    Animations cannot use the copy-per-worker trick above: `Image.copy()` keeps
    only the current frame, which would measure a single-frame file and report a
    fraction of what the conversion produces. Seeking through the frames is not
    thread-safe either, so the steps are encoded one after another. Animations
    are rare here; correctness beats the parallelism.
    """
    metadata = _metadata(image)
    unscaled = scale >= MAX_SCALE

    sizes = {
        quality: len(
            _encode(image, quality, metadata=metadata, save_all=True)
            if unscaled
            else _encode_animation(image, quality, scale, metadata)
        )
        for quality in steps
    }

    return SizeEstimate(
        sizes=sizes,
        source=image.size,
        target=scaled_size(image.size, scale),
    )
