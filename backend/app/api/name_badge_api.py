"""HTTP-Schicht der Namensschilder.

Vier Endpunkte, drei davon liefern eine Datei:

* `GET /name-badges/formats` — Bogenformate und Kartenlayout als Daten. Das
  Frontend baut daraus das klickbare Kartenraster.
* `POST /name-badges/analyse` — Trockenlauf, JSON, erzeugt kein PDF.
* `POST /name-badges` — der druckfertige Bogensatz.
* `POST /name-badges/calibration` — Kalibrierbogen, ohne Daten.

Die Optionen des Druckendpunkts kommen als Formularfelder neben der Datei und
werden im Service geprüft, nicht über `Form(..., ge=…)`: das ergäbe ein rohes
422 statt einer Meldung, mit der ein Anwender etwas anfangen kann.
"""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.core.badge_geometry import DEFAULT_FORMAT_ID
from app.schemas.access import Page
from app.schemas.name_badge import (
    AnalyseResponse,
    CalibrationRequest,
    FormatsResponse,
    RenderedPdf,
)
from app.services.name_badge_service import (
    NameBadgeError,
    RenderOptions,
    analyse_badge_csv,
    create_badge_pdf,
    create_calibration_pdf,
    list_formats,
)

# Permission this router lives behind. `main.py` reads it when including
# the router, so a feature module without it cannot be mounted at all.
PAGE = Page.NAMENSSCHILDER

router = APIRouter(prefix="/name-badges", tags=["name-badges"])


@router.get("/formats", response_model=FormatsResponse)
def get_formats() -> FormatsResponse:
    """Verfügbare Bogenformate samt Geometrie und Kartenlayout."""
    return list_formats()


@router.post("/analyse", response_model=AnalyseResponse)
async def analyse_upload(
    file: UploadFile = File(...),
    format: str = Form(DEFAULT_FORMAT_ID),
    start_slot: int = Form(1),
) -> AnalyseResponse:
    """Trockenlauf über die hochgeladene Liste, ohne ein PDF zu erzeugen."""
    content = await file.read()

    try:
        return await run_in_threadpool(analyse_badge_csv, content, format, start_slot)
    except NameBadgeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("")
async def create_badges(
    file: UploadFile = File(...),
    format: str = Form(DEFAULT_FORMAT_ID),
    start_slot: int = Form(1),
    offset_x_mm: float = Form(0.0),
    offset_y_mm: float = Form(0.0),
    draw_outlines: bool = Form(False),
) -> StreamingResponse:
    """Die hochgeladene Liste als druckfertigen Bogensatz zurückgeben."""
    content = await file.read()

    options = RenderOptions(
        start_slot=start_slot,
        offset_x_mm=offset_x_mm,
        offset_y_mm=offset_y_mm,
        draw_outlines=draw_outlines,
    )

    try:
        # Einlesen und Setzen sind CPU-gebunden und laufen deshalb neben der
        # Ereignisschleife.
        result = await run_in_threadpool(
            create_badge_pdf, content, file.filename or "", format, options
        )
    except NameBadgeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _pdf_response(result)


@router.post("/calibration")
async def create_calibration(request: CalibrationRequest) -> StreamingResponse:
    """Kalibrierbogen für das gewählte Format und den eingestellten Versatz."""
    try:
        result = await run_in_threadpool(
            create_calibration_pdf,
            request.format,
            request.offset_x_mm,
            request.offset_y_mm,
        )
    except NameBadgeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _pdf_response(result)


def _pdf_response(result: RenderedPdf) -> StreamingResponse:
    return StreamingResponse(
        result.buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            # Die Vorschau zeigt die Bogenanzahl an, ohne das PDF zu parsen.
            "X-Sheet-Count": str(result.pages),
        },
    )
