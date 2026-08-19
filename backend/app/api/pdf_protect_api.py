from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.core.pdf_utils import PdfProtectionError
from app.services.pdf_protect_service import protect_uploaded_pdf

router = APIRouter()


@router.post("/protect-pdf")
async def protect_pdf_upload(
    file: UploadFile = File(...),
    # Not `Form(...)`: an empty form value arrives as "missing" and would turn
    # into a raw 422. Defaulting to "" routes it through the validation below,
    # which answers with a readable message.
    password: str = Form(default=""),
) -> StreamingResponse:
    """Return the uploaded PDF encrypted with the given open password."""
    content = await file.read()

    if not content:
        raise HTTPException(status_code=400, detail="Die hochgeladene Datei ist leer.")

    try:
        # Encrypting every stream of a large PDF is CPU-bound.
        result = await run_in_threadpool(
            protect_uploaded_pdf, content, file.filename or "dokument.pdf", password
        )
    except PdfProtectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StreamingResponse(
        result.buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
        },
    )
