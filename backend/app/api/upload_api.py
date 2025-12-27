import os
from datetime import datetime

from backend.app.services.upload_service import process_upload
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import StreamingResponse

today = datetime.today().date()

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
