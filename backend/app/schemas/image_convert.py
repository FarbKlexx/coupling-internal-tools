from dataclasses import dataclass, field
from io import BytesIO

from pydantic import BaseModel


@dataclass(frozen=True)
class SkippedImage:
    """One input file that never made it into the archive."""

    filename: str
    reason: str


@dataclass
class ImageConversionResult:
    """Outcome of one bulk conversion run.

    `archive` is a seeked zip buffer ready to be streamed; the two lists let the
    api layer report how much actually went through without re-reading the zip.
    """

    archive: BytesIO
    converted: list[str] = field(default_factory=list)
    skipped: list[SkippedImage] = field(default_factory=list)


@dataclass
class ImageEstimate:
    """Measured WebP sizes of one input file at several quality steps.

    `samples` maps quality → byte size; it stays empty when `error` is set,
    which is how the frontend marks a file that the conversion would skip.
    `pixels`/`scaled_pixels` are the decoded and the downscaled resolution, so
    the UI can name the pixel size the numbers belong to; both are `None` for a
    file that could not be decoded.
    """

    filename: str
    original_size: int
    samples: dict[int, int] = field(default_factory=dict)
    pixels: tuple[int, int] | None = None
    scaled_pixels: tuple[int, int] | None = None
    error: str | None = None

    @property
    def supported(self) -> bool:
        return self.error is None


class SizeSample(BaseModel):
    quality: int
    size: int


class FileEstimateResponse(BaseModel):
    filename: str
    original_size: int
    supported: bool
    samples: list[SizeSample]
    width: int | None = None
    height: int | None = None
    scaled_width: int | None = None
    scaled_height: int | None = None
    error: str | None = None


class EstimateResponse(BaseModel):
    """Sampled size curve per uploaded file, in the order they were sent.

    `scale` echoes the resolution the sizes were measured at — the frontend
    caches curves per scale and uses it to tell the answers apart.
    """

    qualities: list[int]
    scale: int
    files: list[FileEstimateResponse]
