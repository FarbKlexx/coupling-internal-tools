from app.schemas.awin_banner import AwinBannerRequest
from app.services.awin_banner_service import generate_awin_banner_csv
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()


@router.post("/awin-banner-csv")
async def create_awin_banner_csv(request: AwinBannerRequest) -> StreamingResponse:
    csv_buffer = generate_awin_banner_csv(request)
    return StreamingResponse(
        csv_buffer,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="awin_banners.csv"'},
    )
