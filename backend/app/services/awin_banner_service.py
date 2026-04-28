import csv
import logging
import re
from io import StringIO

from app.schemas.awin_banner import AwinBannerRequest

logger = logging.getLogger(__name__)

# Matches any filename of the form <format>_<width>x<height>.<ext>
_PATTERN_BANNER = re.compile(r"^(.+)_(\d+)x(\d+)\.[^.]+$")

_CSV_HEADERS: list[str] = [
    "ID",
    "Status",
    "Werbemitteltyp",
    "Werbemittel-Titel",
    "Werbemittel-Beschreibung",
    "Werbemittel-Tag",
    "Breite",
    "Höhe",
    "Sichtbarkeit",
    "Link-Text",
    "Ziel-URL",
    "Alt-Text",
    "Bildquelle",
]


def _parse_filename(filename: str) -> tuple[str, str, str] | None:
    """Extract (format_string, width, height) from a banner filename.

    Expects the pattern <format>_<width>x<height>.<ext>, e.g.
    "Mobile-Standardbanner_300x250.jpg" → ("Mobile-Standardbanner", "300", "250").
    The format string is taken verbatim from the filename — no mapping applied.

    Returns None when the filename does not match the pattern.
    """
    m = _PATTERN_BANNER.match(filename)
    if m:
        return m.group(1), m.group(2), m.group(3)

    return None


def _build_image_url(stem: str, filename: str) -> str:
    """Join stem and filename with exactly one forward slash."""
    return f"{stem.rstrip('/')}/{filename.lstrip('/')}"


def generate_awin_banner_csv(request: AwinBannerRequest) -> StringIO:
    """Build a semicolon-delimited CSV for AWIN banner mass upload.

    Unrecognised filenames are skipped rather than added with empty dimension
    fields, because incomplete rows would cause AWIN's import to reject the
    entire file.
    """
    buffer = StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(_CSV_HEADERS)

    for filename in request.filenames:
        parsed = _parse_filename(filename)
        if parsed is None:
            logger.warning("Skipping '%s': filename matches no known banner pattern.", filename)
            continue

        format_string, width, height = parsed

        writer.writerow(
            [
                "",   # ID
                "1",  # Status
                "3",  # Werbemitteltyp
                f"{format_string} {width}x{height}",  # Werbemittel-Titel
                request.description,  # Werbemittel-Beschreibung
                request.tag,  # Werbemittel-Tag
                width,  # Breite
                height,  # Höhe
                "",  # Sichtbarkeit
                "",  # Link-Text
                request.target_url,  # Ziel-URL
                request.alt_text,  # Alt-Text
                _build_image_url(request.image_source_stem, filename),  # Bildquelle
            ]
        )

    buffer.seek(0)
    return buffer
