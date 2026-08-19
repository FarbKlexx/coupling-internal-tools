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
    """

    filename: str
    original_size: int
    samples: dict[int, int] = field(default_factory=dict)
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
    error: str | None = None


class EstimateResponse(BaseModel):
    """Sampled size curve per uploaded file, in the order they were sent."""

    qualities: list[int]
    files: list[FileEstimateResponse]
