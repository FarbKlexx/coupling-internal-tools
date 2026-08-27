from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.qr_utils import QrCodeError
from app.schemas.access import Page
from app.schemas.qr_code import QrCodeRequest
from app.services.qr_code_service import generate_qr_code

# Permission this router lives behind. `main.py` reads it when including
# the router, so a feature module without it cannot be mounted at all.
PAGE = Page.QR_CODE

router = APIRouter()


@router.post("/qr-code")
async def create_qr_code(request: QrCodeRequest) -> StreamingResponse:
    """Return the QR code for a link or text as a PNG or SVG download."""
    try:
        result = generate_qr_code(request)
    except QrCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StreamingResponse(
        result.buffer,
        media_type=result.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
        },
    )
