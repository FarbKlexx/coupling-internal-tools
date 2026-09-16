"""HTTP-Schicht des Mailversands.

Fünf Endpunkte: die Ansicht lesen, einen Zustand setzen, einen Betrieb von
Hand anlegen, dessen Stammdaten ändern, alles als CSV herausholen. Der schreibende Aufruf antwortet mit der ganzen Ansicht, wie
überall in dieser Anwendung — und nimmt dafür Suche, Filter und Seite als
Query-Parameter entgegen, damit die Liste nach dem Klick dort stehen bleibt,
wo sie war (dasselbe Verfahren wie beim Freigeben einer gesperrten Nummer).

Der Zugang hängt an der eigenen Seitenberechtigung `mailversand` und
ausdrücklich **nicht** zusätzlich an `require_admin`: wer Mails versendet,
muss dafür kein Administrator sein — und wem die Seite nicht zugeteilt ist,
für den existiert sie nicht. Die Seitenberechtigungen sind das Mittel dieser
Anwendung für genau diese Frage; ein zweiter Riegel darüber machte sie zur
Attrappe.

Die Handler sind einfaches `def`: SQLite blockiert, und FastAPI führt
synchrone Handler in seinem Threadpool aus.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, current_user
from app.schemas.access import Page
from app.schemas.mail_followup import (
    MAIL_PAGE_SIZE,
    MAX_MAIL_PAGE_SIZE,
    BuildReadiness,
    MailBoard,
    MailState,
    MailUpdateRequest,
    ManualEntryRequest,
)
from app.services.mail_followup_service import (
    MailFollowupConflictError,
    MailFollowupError,
    MailFollowupNotFoundError,
    create_entry,
    export_board,
    get_board,
    set_state,
    update_entry,
)

# Berechtigung, hinter der dieser Router hängt. `main.py` liest die Konstante
# beim Einhängen — ein Feature-Modul ohne sie lässt sich gar nicht erst
# mounten.
PAGE = Page.MAILVERSAND

router = APIRouter(prefix="/mailversand", tags=["mailversand"])


def _fail(exc: MailFollowupError) -> HTTPException:
    if isinstance(exc, MailFollowupNotFoundError):
        status = 404
    elif isinstance(exc, MailFollowupConflictError):
        status = 409
    else:
        status = 400

    return HTTPException(status_code=status, detail=str(exc))


@router.get("/board", response_model=MailBoard)
def read_board(
    q: str = Query(default="", max_length=200),
    state: MailState | None = Query(default=None),
    readiness: BuildReadiness | None = Query(default=None),
    oversized: bool | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=MAIL_PAGE_SIZE, ge=1, le=MAX_MAIL_PAGE_SIZE),
    _: CurrentUser = Depends(current_user),
) -> MailBoard:
    """Die Versandliste: Zähler, eine Seite Zusagen, die Knöpfe.

    `state`, `readiness` und `oversized` sind drei unabhängige Filter, weil
    sie drei Fragen beantworten: was ist verschickt, was lässt sich bauen,
    und was ist größer als ein Onepager.
    """
    return get_board(
        query=q,
        state=state,
        readiness=readiness,
        oversized=oversized,
        offset=offset,
        limit=limit,
    )


@router.post("/contacts/{contact_id}", response_model=MailBoard)
def change_state(
    contact_id: str,
    request: MailUpdateRequest,
    q: str = Query(default="", max_length=200),
    state: MailState | None = Query(default=None),
    readiness: BuildReadiness | None = Query(default=None),
    oversized: bool | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=MAIL_PAGE_SIZE, ge=1, le=MAX_MAIL_PAGE_SIZE),
    user: CurrentUser = Depends(current_user),
) -> MailBoard:
    """Einen Versandzustand, eine Anmerkung oder einen Marker setzen.

    Wer geklickt hat, kommt aus der Sitzung und nie aus dem Anfragekörper —
    dieselbe Regel wie im Anrufprotokoll, auch wenn hier kein Nachweis
    entsteht, sondern Arbeitsstand.

    `state`/`readiness`/`oversized` sind hier zweimal da und meinen
    zweierlei: in der Query die Sicht, die zurückkommen soll, im Körper das,
    was gesetzt wird.
    """
    try:
        return set_state(
            contact_id,
            request,
            username=user.username,
            query=q,
            state=state,
            readiness=readiness,
            oversized=oversized,
            offset=offset,
            limit=limit,
        )
    except MailFollowupError as exc:
        raise _fail(exc) from exc


@router.post("/contacts", response_model=MailBoard, status_code=201)
def create_contact(
    request: ManualEntryRequest,
    q: str = Query(default="", max_length=200),
    state: MailState | None = Query(default=None),
    readiness: BuildReadiness | None = Query(default=None),
    oversized: bool | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=MAIL_PAGE_SIZE, ge=1, le=MAX_MAIL_PAGE_SIZE),
    user: CurrentUser = Depends(current_user),
) -> MailBoard:
    """Einen Betrieb von Hand anlegen — für die, die niemand angerufen hat.

    Antwortet mit der ganzen Ansicht, wie jeder Schreibzugriff hier. 409, wenn
    die Nummer schon bekannt ist: die Meldung nennt, wo sie steht, und
    `force` im Körper übergeht den Befund danach ausdrücklich.
    """
    try:
        return create_entry(
            request,
            user_id=user.id,
            username=user.username,
            query=q,
            state=state,
            readiness=readiness,
            oversized=oversized,
            offset=offset,
            limit=limit,
        )
    except MailFollowupError as exc:
        raise _fail(exc) from exc


@router.patch("/contacts/{contact_id}", response_model=MailBoard)
def edit_contact(
    contact_id: str,
    request: ManualEntryRequest,
    q: str = Query(default="", max_length=200),
    state: MailState | None = Query(default=None),
    readiness: BuildReadiness | None = Query(default=None),
    oversized: bool | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=MAIL_PAGE_SIZE, ge=1, le=MAX_MAIL_PAGE_SIZE),
    user: CurrentUser = Depends(current_user),
) -> MailBoard:
    """Die Stammdaten eines von Hand erfassten Betriebs ändern.

    PATCH statt POST, weil unter derselben Adresse schon der Versandstand
    geschrieben wird: die Methode trennt „was ist aus der Zusage geworden" von
    „wer ist dieser Betrieb". Importierte Zeilen lehnt der Service ab — die
    gehören der Telefonakquise.
    """
    try:
        return update_entry(
            contact_id,
            request,
            user_id=user.id,
            username=user.username,
            query=q,
            state=state,
            readiness=readiness,
            oversized=oversized,
            offset=offset,
            limit=limit,
        )
    except MailFollowupError as exc:
        raise _fail(exc) from exc


@router.get("/export")
def download_board(_: CurrentUser = Depends(current_user)) -> StreamingResponse:
    """Die ganze Versandliste als CSV."""
    result = export_board()

    return StreamingResponse(
        result.buffer,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )
