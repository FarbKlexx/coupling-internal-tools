import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    auth_api,
    awin_banner_api,
    health_api,
    image_convert_api,
    kanban_api,
    name_badge_api,
    pdf_protect_api,
    qr_code_api,
    upload_api,
)
from app.api.deps import require_page
from app.core.auth_db import init_schema as init_auth_schema
from app.core.kanban_db import init_schema as init_kanban_schema
from app.services.auth_service import ensure_admin


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Beide Schemata anzulegen ist idempotent und läuft bei jedem Start.
    init_kanban_schema()
    init_auth_schema()
    # Verweigert den Start, wenn noch kein Konto existiert und
    # ADMIN_USERNAME/ADMIN_PASSWORD fehlen — eine Anwendung, in die niemand
    # hineinkommt, soll im Deploy auffallen und nicht später.
    ensure_admin()
    yield


def _docs_enabled() -> bool:
    """FastAPIs eigene Dokumentation.

    In Produktion aus: sie lag zuvor nur deshalb nicht offen, weil die Basic
    Auth davorstand. Ausführen liesse sich darüber nichts — die Endpunkte
    antworten weiter mit 401 —, aber die vollständige API-Oberfläche inklusive
    aller Feldnamen wäre lesbar.
    """
    return os.getenv("ENABLE_API_DOCS", "0") == "1"


_docs = _docs_enabled()

app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)

origins = [
    "http://localhost:4321",
    "http://127.0.0.1:4321",
    "http://localhost:3000",
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    # Standardmäßig leer, also sicher ohne Zutun: in Produktion erreicht das
    # Frontend das Backend über nginx, das ist same-origin und braucht kein
    # CORS. Die Liste oben ist reine Entwicklungsbequemlichkeit und wird
    # ausdrücklich eingeschaltet (docker-compose.local.yml), statt in
    # Produktion ausdrücklich abgeschaltet werden zu müssen.
    allow_origins=origins if os.getenv("ALLOW_DEV_ORIGINS", "0") == "1" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Content-Disposition",
        "X-Converted-Count",
        "X-Skipped-Count",
        "X-Sheet-Count",
    ],
)

# Router ohne eigene Berechtigung. `/health` ist die Container-Sonde und muss
# erreichbar bleiben, während alles andere kaputt ist; `/auth` beantwortet
# Fragen *über* Zugang und kann ohne Henne-Ei-Problem keine verlangen — die
# Endpunkte dort tragen ihre Guards einzeln.
app.include_router(health_api.router)
app.include_router(auth_api.router)

# Jeder Feature-Router hinter der Berechtigung, die sein eigenes Modul
# deklariert. `module.PAGE` hier zu lesen ist das, was „eingehängt, aber
# ungeschützt" unmöglich macht: ein Modul ohne die Konstante wirft beim Import
# einen AttributeError, also in CI, statt still einen offenen Endpunkt zu
# bedienen. Die Reihenfolge ist die der Routen in der OpenAPI-Dokumentation.
FEATURE_MODULES = (
    upload_api,
    awin_banner_api,
    image_convert_api,
    qr_code_api,
    pdf_protect_api,
    name_badge_api,
    kanban_api,
)

for module in FEATURE_MODULES:
    app.include_router(
        module.router,
        dependencies=[Depends(require_page(module.PAGE))],
    )
