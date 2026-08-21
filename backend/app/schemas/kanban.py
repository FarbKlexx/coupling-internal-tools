"""Kanban board DTOs.

This is the first stateful feature of the app: the board lives in a SQLite
file, see `core/kanban_db.py`. Everything else here transforms a request and
throws the result away.
"""

from enum import Enum

from pydantic import BaseModel, Field

MAX_TITLE = 200
MAX_DESCRIPTION = 5000
MAX_LABEL_NAME = 80


class KanbanColumn(str, Enum):
    """The five fixed columns. Slugs are stored, labels are display-only."""

    IDEEN = "ideen"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    ON_HOLD = "on_hold"


# Order here is the order of the columns in the board response, and therefore
# on screen. Renaming a column is a change to this dict only — the slug that
# is stored in the database stays as it is.
COLUMN_LABELS: dict[KanbanColumn, str] = {
    KanbanColumn.IDEEN: "Ideen",
    KanbanColumn.TODO: "TODO",
    KanbanColumn.IN_PROGRESS: "In Progress",
    KanbanColumn.DONE: "Done",
    KanbanColumn.ON_HOLD: "On hold",
}


class LabelColor(str, Enum):
    """Closed palette.

    Only the slug is stored; the actual colour values are CSS classes in
    `frontend/src/style.css` (`.label-<slug>`), because they are design tokens
    and the UI is a hand-rolled dark theme that free colour input would break.
    An eleventh colour has to be added in both places.
    """

    # Order matters: the automatic colour picks the least-used one and breaks
    # ties by this order, so the first customers get colours that are easy to
    # tell apart. Grey is last on purpose.
    BLUE = "blue"
    ORANGE = "orange"
    GREEN = "green"
    VIOLET = "violet"
    RED = "red"
    TEAL = "teal"
    PINK = "pink"
    AMBER = "amber"
    LIME = "lime"
    SLATE = "slate"


class KanbanLabel(BaseModel):
    """A label — used for customers, but deliberately not named `customer`.

    The generic name keeps non-customer labels ("intern", "dringend") a pure
    frontend change later on.
    """

    id: str
    name: str
    color: LabelColor
    archived: bool


class KanbanCard(BaseModel):
    id: str
    column_id: KanbanColumn
    position: int
    title: str
    description: str
    # Embedded in full, not just as ids: the frontend should never have to
    # join, and a board is a few kilobytes either way.
    labels: list[KanbanLabel]
    created_at: str
    updated_at: str
    created_by: str


class KanbanColumnView(BaseModel):
    id: KanbanColumn
    label: str
    cards: list[KanbanCard]


class KanbanBoard(BaseModel):
    """The whole board in one response — the frontend keeps no other state."""

    # Bumped on every write, label edits included (renaming a customer changes
    # how every card carrying it renders). The frontend polls and skips
    # re-patching its state while this is unchanged, so a poll cannot tear a
    # drag that is in progress.
    revision: int
    columns: list[KanbanColumnView]
    # All non-archived labels, for the picker and the filter.
    labels: list[KanbanLabel]


class CardCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    description: str = Field(default="", max_length=MAX_DESCRIPTION)
    column_id: KanbanColumn = KanbanColumn.IDEEN
    label_ids: list[str] = Field(default_factory=list)


class CardUpdateRequest(BaseModel):
    """Only the fields that are present get written."""

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)


class CardMoveRequest(BaseModel):
    column_id: KanbanColumn
    position: int = Field(ge=0)


class CardLabelsRequest(BaseModel):
    """The complete set of labels for a card, not a delta.

    A multi-select hands over the end state anyway, and setting the whole set
    is idempotent — a double click cannot break anything.
    """

    label_ids: list[str]


class LabelCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_LABEL_NAME)
    # Left out on purpose in the normal flow: the backend picks the least-used
    # colour so nobody has to make a colour decision while typing a name.
    color: LabelColor | None = None


class LabelUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=MAX_LABEL_NAME)
    color: LabelColor | None = None
    archived: bool | None = None
