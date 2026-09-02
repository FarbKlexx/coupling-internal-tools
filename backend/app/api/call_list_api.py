"""HTTP-Schicht der Telefonakquise.

Zwei Gruppen von Endpunkten an einem Router:

* **Anrufen** — `GET /telefonakquise/state`,
  `POST /telefonakquise/contacts/{id}/outcome` sowie die Entscheidungsliste
  (`GET /telefonakquise/decisions`) und ihre Richtigstellung
  (`POST /telefonakquise/decisions/{event_id}/correct`). Alle drei
  schreibenden Wege antworten mit dem ganzen Arbeitsstand, so wie das
  Kanban-Board mit dem ganzen Board antwortet. Die Richtigstellung hängt
  bewusst **nicht** an `require_admin`: der Fehlklick passiert dem, der
  telefoniert.
* **Verwalten** — Import, Übersicht, Archivieren, Löschen, Ausgaben. Diese
  Endpunkte tragen zusätzlich `Depends(require_admin)`.

Warum beide Gruppen an *einem* Router hängen: die Seitenberechtigung hängt in
`main.py` am Router, und `tests/test_access.py` verlangt für jede
Feature-Route eine Seite (nicht bloß eine Sitzung). Ein zweiter, nur
administrativer Router wäre entweder ungeschützt im Sinne dieses Tests oder
eine Ausnahme in seiner Liste. Administratoren haben ohnehin jede
Seitenberechtigung, also kostet die Kombination nichts.

Die Handler sind einfaches `def`, nicht `async def`: SQLite blockiert, und
FastAPI führt synchrone Handler in seinem Threadpool aus — genau das ist hier
gewollt. Der CSV-Import ist die Ausnahme, weil er die Datei aus dem Request
lesen muss.
"""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, current_user, require_admin
from app.schemas.access import Page
from app.schemas.call_list import (
    BLACKLIST_PAGE_SIZE,
    DECISION_PAGE_SIZE,
    MAX_BLACKLIST_PAGE_SIZE,
    MAX_DECISION_PAGE_SIZE,
    BlacklistAddRequest,
    BlacklistMutationResponse,
    BlacklistPage,
    CallDecisionPage,
    CallState,
    ListAnalyseResponse,
    ListImportResponse,
    ListUpdateRequest,
    OutcomeRequest,
)
from app.services.call_list_service import (
    CallListConflictError,
    CallListError,
    CallListExport,
    CallListNotFoundError,
    add_blacklist_numbers,
    analyse_list,
    correct_outcome,
    delete_list,
    export_blacklist,
    export_promised,
    export_protocol,
    get_blacklist,
    get_decisions,
    get_state,
    import_blacklist,
    import_list,
    record_outcome,
    remove_blacklist_entry,
    update_list,
)

# Permission this router lives behind. `main.py` reads it when including
# the router, so a feature module without it cannot be mounted at all.
PAGE = Page.TELEFONAKQUISE

router = APIRouter(prefix="/telefonakquise", tags=["telefonakquise"])


def _fail(exc: CallListError) -> HTTPException:
    """Fehlerklasse auf ihren Statuscode abbilden.

    Reihenfolge ist wichtig — beide besonderen Fehler erben von `CallListError`.
    """
    if isinstance(exc, CallListNotFoundError):
        status = 404
    elif isinstance(exc, CallListConflictError):
        status = 409
    else:
        status = 400

    return HTTPException(status_code=status, detail=str(exc))


# --------------------------------------------------------------------------
# Anrufen
# --------------------------------------------------------------------------


@router.get("/state", response_model=CallState)
def read_state() -> CallState:
    """Der ganze Arbeitsstand: Zähler, der nächste Kontakt, die Listen."""
    return get_state()


@router.post("/contacts/{contact_id}/outcome", response_model=CallState)
def submit_outcome(
    contact_id: str,
    request: OutcomeRequest,
    user: CurrentUser = Depends(current_user),
) -> CallState:
    """Ergebnis eines Anrufs festschreiben und den nächsten Kontakt liefern.

    Wer das Ergebnis eingetragen hat, kommt aus der Sitzung und nie aus dem
    Anfragekörper — das Protokoll ist ein Nachweis und darf nicht behaupten
    können, wer angerufen hat.
    """
    try:
        return record_outcome(
            contact_id, request, user_id=user.id, username=user.username
        )
    except CallListError as exc:
        raise _fail(exc) from exc


@router.get("/decisions", response_model=CallDecisionPage)
def read_decisions(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=DECISION_PAGE_SIZE, ge=1, le=MAX_DECISION_PAGE_SIZE),
    _: CurrentUser = Depends(current_user),
) -> CallDecisionPage:
    """Die zuletzt eingetragenen Entscheidungen, jüngste zuerst.

    Geblättert und deshalb nicht Teil von `CallState`: der Arbeitsstand wird
    alle 30 Sekunden geholt.
    """
    return get_decisions(offset=offset, limit=limit)


@router.post("/decisions/{event_id}/correct", response_model=CallState)
def correct_decision(
    event_id: int,
    request: OutcomeRequest,
    user: CurrentUser = Depends(current_user),
) -> CallState:
    """Eine eingetragene Entscheidung richtigstellen.

    Kein `require_admin`: wer anrufen darf, darf seinen Fehlklick auch wieder
    geradeziehen. Überschrieben wird dabei nichts — die Korrektur ist eine
    neue Protokollzeile, und wer sie eingetragen hat, kommt wie beim Anruf
    selbst aus der Sitzung.

    Antwortet mit dem ganzen Arbeitsstand, nicht mit der Entscheidungsliste:
    eine Korrektur kann den Betrieb zurück in den Vorrat holen, und *das* ist
    das Ergebnis, das sofort stimmen muss.
    """
    try:
        return correct_outcome(
            event_id, request, user_id=user.id, username=user.username
        )
    except CallListError as exc:
        raise _fail(exc) from exc


# --------------------------------------------------------------------------
# Verwalten (nur Administratoren)
# --------------------------------------------------------------------------


@router.post("/lists/analyse", response_model=ListAnalyseResponse)
async def analyse_upload(
    file: UploadFile = File(...),
    _: CurrentUser = Depends(require_admin),
) -> ListAnalyseResponse:
    """Trockenlauf über die hochgeladene Datei, ohne etwas zu speichern."""
    content = await file.read()

    try:
        return await run_in_threadpool(analyse_list, content, file.filename or "")
    except CallListError as exc:
        raise _fail(exc) from exc


def _parse_prios(raw: str) -> list[str] | None:
    """Die Prio-Auswahl aus dem Formularfeld lesen.

    Ein leeres Feld heißt „alle Prios" und nicht „keine": ein leerer
    Formularwert kommt ohnehin als *fehlend* an, und eine Datei ohne
    Prio-Spalte schickt nichts. `"[]"` dagegen ist eine ausdrücklich leere
    Auswahl — die lehnt der Service ab, statt kommentarlos alles zu nehmen.
    """
    if not raw.strip():
        return None

    try:
        values = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Die Prio-Auswahl kam unlesbar an."
        ) from exc

    if not isinstance(values, list) or not all(
        isinstance(value, str) for value in values
    ):
        raise HTTPException(status_code=400, detail="Die Prio-Auswahl kam unlesbar an.")

    return values


@router.post("/lists", response_model=ListImportResponse)
async def create_list(
    file: UploadFile = File(...),
    # `Form(default="")` statt `Form(...)`: ein leeres Formularfeld kommt als
    # *fehlend* an und ergäbe sonst ein rohes 422 statt einer Meldung. Ein
    # leerer Name wird aus dem Dateinamen abgeleitet.
    name: str = Form(default=""),
    #: JSON-Liste der zu importierenden Prio-Werte, oder leer für „alle".
    prios: str = Form(default=""),
    user: CurrentUser = Depends(require_admin),
) -> ListImportResponse:
    """Die hochgeladene Liste speichern."""
    content = await file.read()
    selection = _parse_prios(prios)

    try:
        return await run_in_threadpool(
            import_list,
            content,
            file.filename or "",
            name,
            created_by=user.username,
            prios=selection,
        )
    except CallListError as exc:
        raise _fail(exc) from exc


@router.patch("/lists/{list_id}", response_model=CallState)
def change_list(
    list_id: str,
    request: ListUpdateRequest,
    _: CurrentUser = Depends(require_admin),
) -> CallState:
    """Umbenennen oder archivieren."""
    try:
        return update_list(list_id, request)
    except CallListError as exc:
        raise _fail(exc) from exc


@router.delete("/lists/{list_id}", response_model=CallState)
def drop_list(
    list_id: str,
    force: bool = Query(default=False),
    _: CurrentUser = Depends(require_admin),
) -> CallState:
    """Endgültig löschen. Antwortet 409, solange Anrufe protokolliert sind.

    `force=true` ist die bestätigte Variante („nimmt 43 Protokollzeilen mit").
    """
    try:
        return delete_list(list_id, force=force)
    except CallListError as exc:
        raise _fail(exc) from exc


# --------------------------------------------------------------------------
# Blacklist (nur Administratoren)
# --------------------------------------------------------------------------


@router.get("/blacklist", response_model=BlacklistPage)
def read_blacklist(
    q: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=BLACKLIST_PAGE_SIZE, ge=1, le=MAX_BLACKLIST_PAGE_SIZE),
    _: CurrentUser = Depends(require_admin),
) -> BlacklistPage:
    """Ein Ausschnitt der Sperrliste. Sie wird geblättert, nicht geladen."""
    return get_blacklist(query=q, offset=offset, limit=limit)


@router.post("/blacklist", response_model=BlacklistMutationResponse)
def add_blacklist(
    request: BlacklistAddRequest,
    user: CurrentUser = Depends(require_admin),
) -> BlacklistMutationResponse:
    """Nummern von Hand sperren — eine pro Zeile."""
    try:
        return add_blacklist_numbers(request, created_by=user.username)
    except CallListError as exc:
        raise _fail(exc) from exc


@router.post("/blacklist/import", response_model=BlacklistMutationResponse)
async def upload_blacklist(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_admin),
) -> BlacklistMutationResponse:
    """Eine CSV als Sperrliste einlesen. Pflicht ist allein die Telefonspalte."""
    content = await file.read()

    try:
        return await run_in_threadpool(
            import_blacklist, content, created_by=user.username
        )
    except CallListError as exc:
        raise _fail(exc) from exc


@router.delete("/blacklist/{telefon_key}", response_model=BlacklistPage)
def drop_blacklist_entry(
    telefon_key: str,
    q: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_admin),
) -> BlacklistPage:
    """Eine Nummer wieder freigeben.

    `q` und `offset` reisen mit, damit die Ansicht nach dem Entfernen dort
    stehen bleibt, wo sie war.
    """
    try:
        return remove_blacklist_entry(telefon_key, query=q, offset=offset)
    except CallListError as exc:
        raise _fail(exc) from exc


@router.get("/export/blacklist")
def download_blacklist(_: CurrentUser = Depends(require_admin)) -> StreamingResponse:
    """Die Sperrliste als CSV — lässt sich hier auch wieder einlesen."""
    return _csv_response(export_blacklist())


@router.get("/export/zusagen")
def download_promised(_: CurrentUser = Depends(require_admin)) -> StreamingResponse:
    """Die Zusagen als CSV — Grundlage für den Mailversand."""
    return _csv_response(export_promised())


@router.get("/export/protokoll")
def download_protocol(_: CurrentUser = Depends(require_admin)) -> StreamingResponse:
    """Das vollständige Anrufprotokoll als CSV — der Nachweis zum Mitnehmen."""
    return _csv_response(export_protocol())


def _csv_response(result: CallListExport) -> StreamingResponse:
    return StreamingResponse(
        result.buffer,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
        },
    )
