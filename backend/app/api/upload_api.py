import os
from datetime import datetime

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from app.schemas.access import Page
from app.services.upload_service import process_upload

today = datetime.today().date()

# Permission this router lives behind. `main.py` reads it when including
# the router, so a feature module without it cannot be mounted at all.
PAGE = Page.ABGLEICHE

router = APIRouter()

OUTPUT_FOLDER = "output"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), option: str = Form(...)):

    content = await file.read()
    filename = file.filename or "upload"

    zip_buffer = process_upload(content, option, filename)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="converted_{today:%Y%m%d}.zip"'
        },
    )
