"""HTTP layer of the kanban board.

The first JSON CRUD router of the app — every other endpoint answers with a
`StreamingResponse` of a generated file. Only `/kanban/export` still does.

The handlers are plain `def`, not `async def`: SQLite is blocking, and FastAPI
runs sync handlers in its threadpool, which is exactly what is wanted here.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, current_user
from app.schemas.access import Page
from app.schemas.kanban import (
    CardCreateRequest,
    CardLabelsRequest,
    CardMoveRequest,
    CardUpdateRequest,
    KanbanBoard,
    KanbanLabel,
    LabelCreateRequest,
    LabelUpdateRequest,
)
from app.services.kanban_service import (
    KanbanConflictError,
    KanbanError,
    KanbanNotFoundError,
    create_card,
    create_label,
    edit_card,
    edit_label,
    export_board,
    get_board,
    list_labels,
    move_card,
    remove_card,
    remove_label,
    set_card_labels,
)

# Permission this router lives behind. `main.py` reads it when including
# the router, so a feature module without it cannot be mounted at all.
PAGE = Page.KANBAN

router = APIRouter(prefix="/kanban", tags=["kanban"])


def _fail(exc: KanbanError) -> HTTPException:
    """Map a service error onto its status code.

    Order matters — both specific errors are subclasses of `KanbanError`.
    """
    if isinstance(exc, KanbanNotFoundError):
        status = 404
    elif isinstance(exc, KanbanConflictError):
        status = 409
    else:
        status = 400

    return HTTPException(status_code=status, detail=str(exc))


@router.get("/board", response_model=KanbanBoard)
def read_board() -> KanbanBoard:
    """The whole board. Polled by the frontend, guarded by `revision`."""
    return get_board()


@router.post("/cards", response_model=KanbanBoard)
def add_card(
    request: CardCreateRequest,
    user: CurrentUser = Depends(current_user),
) -> KanbanBoard:
    """The author label comes from the caller, never from the request body."""
    try:
        return create_card(request, created_by=user.username)
    except KanbanError as exc:
        raise _fail(exc) from exc


@router.patch("/cards/{card_id}", response_model=KanbanBoard)
def change_card(card_id: str, request: CardUpdateRequest) -> KanbanBoard:
    try:
        return edit_card(card_id, request)
    except KanbanError as exc:
        raise _fail(exc) from exc


@router.post("/cards/{card_id}/move", response_model=KanbanBoard)
def relocate_card(card_id: str, request: CardMoveRequest) -> KanbanBoard:
    try:
        return move_card(card_id, request)
    except KanbanError as exc:
        raise _fail(exc) from exc


@router.put("/cards/{card_id}/labels", response_model=KanbanBoard)
def replace_card_labels(card_id: str, request: CardLabelsRequest) -> KanbanBoard:
    """Set the complete label set of a card — idempotent, not a delta."""
    try:
        return set_card_labels(card_id, request)
    except KanbanError as exc:
        raise _fail(exc) from exc


@router.delete("/cards/{card_id}", response_model=KanbanBoard)
def drop_card(card_id: str) -> KanbanBoard:
    try:
        return remove_card(card_id)
    except KanbanError as exc:
        raise _fail(exc) from exc


@router.get("/labels", response_model=list[KanbanLabel])
def read_labels(include_archived: bool = Query(default=False)) -> list[KanbanLabel]:
    """Only the label list — the manager needs the archived ones too."""
    return list_labels(include_archived=include_archived)


@router.post("/labels", response_model=KanbanBoard)
def add_label(request: LabelCreateRequest) -> KanbanBoard:
    try:
        return create_label(request)
    except KanbanError as exc:
        raise _fail(exc) from exc


@router.patch("/labels/{label_id}", response_model=KanbanBoard)
def change_label(label_id: str, request: LabelUpdateRequest) -> KanbanBoard:
    try:
        return edit_label(label_id, request)
    except KanbanError as exc:
        raise _fail(exc) from exc


@router.delete("/labels/{label_id}", response_model=KanbanBoard)
def drop_label(label_id: str, force: bool = Query(default=False)) -> KanbanBoard:
    """Delete for good. Answers 409 while the label is still on cards.

    `force=true` is the confirmed variant ("remove from 30 cards?").
    """
    try:
        return remove_label(label_id, force=force)
    except KanbanError as exc:
        raise _fail(exc) from exc


@router.get("/export")
def download_board() -> StreamingResponse:
    """The board as a JSON download — a backup users can take themselves."""
    result = export_board()

    return StreamingResponse(
        result.buffer,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
        },
    )
