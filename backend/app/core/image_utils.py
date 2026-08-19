"""Pure image helpers: format detection, WebP encoding and size estimation.

Kept free of FastAPI/zip concerns so the conversion logic can be reused and
unit-tested on its own (mirrors how `csv_utils` sits under the CSV services).
"""

import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageOps

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

# Pillow's default encoder effort (0 fast … 6 slow).
_ENCODER_METHOD = 4

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


def is_supported(filename: str) -> bool:
    """True when the filename carries an extension we can decode."""
    return os.path.splitext(filename)[1].lower() in SUPPORTED_EXTENSIONS


def webp_filename(filename: str) -> str:
    """Swap any extension for ".webp", keeping the original stem."""
    stem = os.path.splitext(os.path.basename(filename))[0] or "bild"
    return f"{stem}.webp"


def clamp_quality(quality: int) -> int:
    return max(MIN_QUALITY, min(MAX_QUALITY, quality))


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


def _is_animated(image: Image.Image) -> bool:
    return getattr(image, "n_frames", 1) > 1


def convert_to_webp(data: bytes, quality: int = DEFAULT_QUALITY) -> bytes:
    """Encode raw image bytes as WebP.

    `quality` is the lossy quality (1 = strongest compression / most loss,
    100 = near-lossless). EXIF orientation is applied up front so photos from
    phones are not rotated, and EXIF/ICC metadata is carried over.
    """
    quality = clamp_quality(quality)

    try:
        with Image.open(io.BytesIO(data)) as image:
            # exif_transpose() drops frames, so animations keep their raw data.
            if _is_animated(image):
                return _encode(image, quality, metadata=_metadata(image), save_all=True)

            prepared = _prepare(image)
            return _encode(prepared, quality, metadata=_metadata(prepared))
    except ImageConversionError:
        raise
    except Exception as exc:  # Pillow raises a wide range of errors here
        raise ImageConversionError(str(exc)) from exc


def estimate_webp_sizes(
    data: bytes, qualities: tuple[int, ...] = ESTIMATE_QUALITIES
) -> dict[int, int]:
    """Measure the WebP byte size of one image at several quality steps.

    The numbers are exact: every step goes through the same encode path as
    `convert_to_webp`, so the frontend can show what a given quality setting
    really costs before the user converts anything. Decoding happens once, the
    encodes run in parallel.
    """
    steps = sorted({clamp_quality(q) for q in qualities})

    try:
        with Image.open(io.BytesIO(data)) as image:
            animated = _is_animated(image)
            # exif_transpose() drops frames, so animations keep their raw data.
            prepared = image if animated else _prepare(image)
            metadata = _metadata(prepared)

            # Pillow stashes the encoder parameters on the image instance, so
            # two threads saving the *same* instance would overwrite each
            # other's quality. Each worker therefore gets its own copy.
            local = threading.local()

            def encoded_size(quality: int) -> int:
                own = getattr(local, "image", None)
                if own is None:
                    own = local.image = prepared.copy()
                return len(_encode(own, quality, metadata=metadata, save_all=animated))

            with ThreadPoolExecutor(max_workers=_ESTIMATE_WORKERS) as pool:
                sizes = list(pool.map(encoded_size, steps))

            return dict(zip(steps, sizes, strict=True))
    except ImageConversionError:
        raise
    except Exception as exc:
        raise ImageConversionError(str(exc)) from exc
