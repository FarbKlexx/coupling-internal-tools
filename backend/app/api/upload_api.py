import os
from datetime import datetime

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from fastapi import APIRouter

from app.services.upload_service_manager import match_upload_option

today = datetime.today().date()

router = APIRouter()

OUTPUT_FOLDER = "output"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), option: str = Form(...)):

    content = await file.read()
    filename = file.filename or "upload"

    result = match_upload_option(content, option, filename)

    zip_buffer = match_upload_option(content, option, filename)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="converted_{today:%Y%m%d}.zip"'
        },
    )