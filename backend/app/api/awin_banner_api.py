from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.access import Page
from app.schemas.awin_banner import AwinBannerRequest
from app.services.awin_banner_service import generate_awin_banner_csv

# Permission this router lives behind. `main.py` reads it when including
# the router, so a feature module without it cannot be mounted at all.
PAGE = Page.AWIN_BANNER

router = APIRouter()


@router.post("/awin-banner-csv")
async def create_awin_banner_csv(request: AwinBannerRequest) -> StreamingResponse:
    csv_buffer = generate_awin_banner_csv(request)
    return StreamingResponse(
        csv_buffer,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="awin_banners.csv"'},
    )
