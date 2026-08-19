from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.awin_banner_api import router as awin_banner_router
from app.api.image_convert_api import router as image_convert_router
from app.api.qr_code_api import router as qr_code_router
from app.api.upload_api import router

app = FastAPI()

origins = [
    "http://localhost:4321",
    "http://127.0.0.1:4321",
    "http://localhost:3000",
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Converted-Count", "X-Skipped-Count"],
)

app.include_router(router)
app.include_router(awin_banner_router)
app.include_router(image_convert_router)
app.include_router(qr_code_router)
