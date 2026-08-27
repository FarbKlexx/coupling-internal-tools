from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.core.image_utils import (
    DEFAULT_QUALITY,
    ESTIMATE_QUALITIES,
    MAX_QUALITY,
    MIN_QUALITY,
)
from app.schemas.access import Page
from app.schemas.image_convert import (
    EstimateResponse,
    FileEstimateResponse,
    SizeSample,
)
from app.services.image_convert_service import (
    convert_images_to_webp,
    estimate_image_sizes,
)

# Permission this router lives behind. `main.py` reads it when including
# the router, so a feature module without it cannot be mounted at all.
PAGE = Page.WEBP_KONVERTER

router = APIRouter()


@router.post("/convert-images")
async def convert_images(
    files: list[UploadFile] = File(...),
    quality: int = Form(DEFAULT_QUALITY),
) -> StreamingResponse:
    """Convert a batch of uploaded images to WebP and return them as one zip."""
    if not MIN_QUALITY <= quality <= MAX_QUALITY:
        raise HTTPException(
            status_code=400,
            detail=f"quality muss zwischen {MIN_QUALITY} und {MAX_QUALITY} liegen.",
        )

    if not files:
        raise HTTPException(status_code=400, detail="Keine Dateien hochgeladen.")

    # Pillow is CPU-bound and UploadFile.file is a sync stream, so the whole
    # batch runs off the event loop.
    sources = [(file.filename or "bild", file.file) for file in files]
    result = await run_in_threadpool(convert_images_to_webp, sources, quality)

    if not result.converted:
        raise HTTPException(
            status_code=400,
            detail="Keine der hochgeladenen Dateien konnte konvertiert werden.",
        )

    # Stamped per request — a module-level date would go stale in a long-running
    # process (see the existing upload endpoints).
    today = datetime.today().date()

    return StreamingResponse(
        result.archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="webp_{today:%Y%m%d}.zip"',
            "X-Converted-Count": str(len(result.converted)),
            "X-Skipped-Count": str(len(result.skipped)),
        },
    )


@router.post("/convert-images/estimate", response_model=EstimateResponse)
async def estimate_image_conversion(
    files: list[UploadFile] = File(...),
) -> EstimateResponse:
    """Report the WebP size of each uploaded image at every sampled quality.

    The frontend interpolates between the returned steps so the quality slider
    can show a live size preview without another round trip. Since this encodes
    the images for real, callers should send small batches and cache the result
    per file.
    """
    if not files:
        raise HTTPException(status_code=400, detail="Keine Dateien hochgeladen.")

    sources = [(file.filename or "bild", file.file) for file in files]
    estimates = await run_in_threadpool(estimate_image_sizes, sources)

    return EstimateResponse(
        qualities=list(ESTIMATE_QUALITIES),
        files=[
            FileEstimateResponse(
                filename=estimate.filename,
                original_size=estimate.original_size,
                supported=estimate.supported,
                samples=[
                    SizeSample(quality=quality, size=size)
                    for quality, size in sorted(estimate.samples.items())
                ],
                error=estimate.error,
            )
            for estimate in estimates
        ],
    )
