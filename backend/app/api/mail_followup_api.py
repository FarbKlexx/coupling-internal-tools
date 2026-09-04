"""HTTP-Schicht des Mailversands.

Drei Endpunkte: die Ansicht lesen, einen Zustand setzen, alles als CSV
herausholen. Der schreibende Aufruf antwortet mit der ganzen Ansicht, wie
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
    MailBoard,
    MailState,
    MailUpdateRequest,
)
from app.services.mail_followup_service import (
    MailFollowupError,
    MailFollowupNotFoundError,
    export_board,
    get_board,
    set_state,
)

# Berechtigung, hinter der dieser Router hängt. `main.py` liest die Konstante
# beim Einhängen — ein Feature-Modul ohne sie lässt sich gar nicht erst
# mounten.
PAGE = Page.MAILVERSAND

router = APIRouter(prefix="/mailversand", tags=["mailversand"])


def _fail(exc: MailFollowupError) -> HTTPException:
    status = 404 if isinstance(exc, MailFollowupNotFoundError) else 400

    return HTTPException(status_code=status, detail=str(exc))


@router.get("/board", response_model=MailBoard)
def read_board(
    q: str = Query(default="", max_length=200),
    state: MailState | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=MAIL_PAGE_SIZE, ge=1, le=MAX_MAIL_PAGE_SIZE),
    _: CurrentUser = Depends(current_user),
) -> MailBoard:
    """Die Versandliste: Zähler, eine Seite Zusagen, die Knöpfe."""
    return get_board(query=q, state=state, offset=offset, limit=limit)


@router.post("/contacts/{contact_id}", response_model=MailBoard)
def change_state(
    contact_id: str,
    request: MailUpdateRequest,
    q: str = Query(default="", max_length=200),
    state: MailState | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=MAIL_PAGE_SIZE, ge=1, le=MAX_MAIL_PAGE_SIZE),
    user: CurrentUser = Depends(current_user),
) -> MailBoard:
    """Einen Versandzustand setzen.

    Wer geklickt hat, kommt aus der Sitzung und nie aus dem Anfragekörper —
    dieselbe Regel wie im Anrufprotokoll, auch wenn hier kein Nachweis
    entsteht, sondern Arbeitsstand.
    """
    try:
        return set_state(
            contact_id,
            request,
            username=user.username,
            query=q,
            state=state,
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
