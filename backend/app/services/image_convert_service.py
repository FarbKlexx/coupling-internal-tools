"""Bulk conversion of uploaded images into a downloadable WebP zip."""

import logging
import zipfile
from collections.abc import Iterable
from io import BytesIO
from typing import BinaryIO

from app.core.image_utils import (
    DEFAULT_QUALITY,
    ESTIMATE_QUALITIES,
    ImageConversionError,
    convert_to_webp,
    estimate_webp_sizes,
    is_supported,
    webp_filename,
)
from app.schemas.image_convert import (
    ImageConversionResult,
    ImageEstimate,
    SkippedImage,
)

logger = logging.getLogger(__name__)

SKIP_REPORT_NAME = "_uebersprungene_dateien.txt"


def _unique_name(name: str, taken: set[str]) -> str:
    """Avoid overwriting entries when two uploads share a stem ("logo.png"/"logo.jpg")."""
    if name not in taken:
        taken.add(name)
        return name

    stem, _, suffix = name.rpartition(".")
    counter = 2
    while f"{stem}_{counter}.{suffix}" in taken:
        counter += 1

    unique = f"{stem}_{counter}.{suffix}"
    taken.add(unique)
    return unique


def convert_images_to_webp(
    sources: Iterable[tuple[str, BinaryIO]],
    quality: int = DEFAULT_QUALITY,
) -> ImageConversionResult:
    """Convert every source image to WebP and pack the results into one zip.

    `sources` is consumed lazily as `(filename, stream)` pairs, so only one
    original is held in memory at a time — the batch size is bounded by the
    resulting archive, not by the uploaded originals.

    Files with an unsupported extension or broken content are skipped instead of
    failing the whole batch; they are listed in `result.skipped` and in a plain
    text report inside the archive.
    """
    archive = BytesIO()
    result = ImageConversionResult(archive=archive)
    taken: set[str] = set()

    # WebP payloads are already compressed — deflating them again only costs CPU.
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_STORED) as zip_file:
        for filename, stream in sources:
            if not is_supported(filename):
                logger.warning("Skipping '%s': unsupported image format.", filename)
                result.skipped.append(
                    SkippedImage(filename, "Nicht unterstütztes Dateiformat")
                )
                continue

            try:
                webp_bytes = convert_to_webp(stream.read(), quality)
            except ImageConversionError as exc:
                logger.warning("Skipping '%s': %s", filename, exc)
                result.skipped.append(
                    SkippedImage(filename, f"Datei konnte nicht gelesen werden ({exc})")
                )
                continue

            entry_name = _unique_name(webp_filename(filename), taken)
            zip_file.writestr(entry_name, webp_bytes)
            result.converted.append(entry_name)

        if result.skipped:
            report = "\n".join(
                f"{item.filename}: {item.reason}" for item in result.skipped
            )
            zip_file.writestr(SKIP_REPORT_NAME, f"Übersprungene Dateien\n\n{report}\n")

    archive.seek(0)
    return result


def estimate_image_sizes(
    sources: Iterable[tuple[str, BinaryIO]],
    qualities: tuple[int, ...] = ESTIMATE_QUALITIES,
) -> list[ImageEstimate]:
    """Measure what each source image would weigh at every sampled quality.

    Mirrors `convert_images_to_webp`: the same files are accepted, the same ones
    are rejected, and the sizes come from the same encode path — so the numbers
    shown in the UI match what the download actually contains. Results are
    returned in input order; callers match them positionally, since filenames
    are not unique.
    """
    estimates: list[ImageEstimate] = []

    for filename, stream in sources:
        data = stream.read()

        if not is_supported(filename):
            estimates.append(
                ImageEstimate(
                    filename=filename,
                    original_size=len(data),
                    error="Nicht unterstütztes Dateiformat",
                )
            )
            continue

        try:
            samples = estimate_webp_sizes(data, qualities)
        except ImageConversionError as exc:
            logger.warning("No estimate for '%s': %s", filename, exc)
            estimates.append(
                ImageEstimate(
                    filename=filename,
                    original_size=len(data),
                    error=f"Datei konnte nicht gelesen werden ({exc})",
                )
            )
            continue

        estimates.append(
            ImageEstimate(filename=filename, original_size=len(data), samples=samples)
        )

    return estimates
