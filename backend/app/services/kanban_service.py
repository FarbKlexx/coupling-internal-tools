"""Business rules of the kanban board.

Every mutating call answers with the *whole* board. That is a few kilobytes,
and it removes a whole class of bugs where the client's idea of the card order
drifts from the database after a drag.
"""

import json
import sqlite3
from dataclasses import dataclass
from io import BytesIO
from typing import Sequence

from app.core import kanban_db as db
from app.schemas.kanban import (
    COLUMN_LABELS,
    CardCreateRequest,
    CardLabelsRequest,
    CardMoveRequest,
    CardUpdateRequest,
    KanbanBoard,
    KanbanCard,
    KanbanColumn,
    KanbanColumnView,
    KanbanLabel,
    LabelColor,
    LabelCreateRequest,
    LabelUpdateRequest,
)


class KanbanError(Exception):
    """Anything the user can fix. The api layer turns this into a 400."""


class KanbanNotFoundError(KanbanError):
    """Card or label does not exist -> 404."""


class KanbanConflictError(KanbanError):
    """Duplicate customer name, or a label that is still in use -> 409."""


@dataclass
class KanbanExport:
    """The whole board as a JSON download — the manual backup."""

    buffer: BytesIO
    filename: str


def _label_from_row(row: sqlite3.Row) -> KanbanLabel:
    return KanbanLabel(
        id=row["id"],
        name=row["name"],
        color=row["color"],
        archived=bool(row["archived"]),
    )


def _card_from_row(row: sqlite3.Row, labels: Sequence[sqlite3.Row]) -> KanbanCard:
    return KanbanCard(
        id=row["id"],
        column_id=row["column_id"],
        position=row["position"],
        title=row["title"],
        description=row["description"],
        labels=[_label_from_row(label) for label in labels],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        created_by=row["created_by"],
    )


def _build_board(conn: sqlite3.Connection) -> KanbanBoard:
    assignments = db.labels_by_card(conn)

    cards: dict[str, list[KanbanCard]] = {column.value: [] for column in KanbanColumn}
    for row in db.all_cards(conn):
        # A column slug that is no longer in the enum would otherwise take the
        # whole board down; drop the card from the view instead.
        if row["column_id"] in cards:
            cards[row["column_id"]].append(
                _card_from_row(row, assignments.get(row["id"], []))
            )

    return KanbanBoard(
        revision=db.revision(conn),
        columns=[
            KanbanColumnView(
                id=column,
                label=COLUMN_LABELS[column],
                cards=cards[column.value],
            )
            for column in KanbanColumn
        ],
        labels=[_label_from_row(row) for row in db.all_labels(conn)],
    )


def get_board() -> KanbanBoard:
    with db.connect() as conn:
        return _build_board(conn)


def _validated_label_ids(
    conn: sqlite3.Connection, label_ids: Sequence[str]
) -> list[str]:
    """Keep the order, drop duplicates, reject ids that do not exist."""
    unique = list(dict.fromkeys(label_ids))
    known = db.existing_label_ids(conn, unique)

    missing = [label_id for label_id in unique if label_id not in known]
    if missing:
        raise KanbanNotFoundError("Mindestens ein ausgewähltes Label existiert nicht.")

    return unique


# --------------------------------------------------------------------------
# cards
# --------------------------------------------------------------------------


def create_card(request: CardCreateRequest, created_by: str = "") -> KanbanBoard:
    title = request.title.strip()
    if not title:
        raise KanbanError("Der Titel darf nicht leer sein.")

    with db.connect() as conn:
        with db.transaction(conn):
            label_ids = _validated_label_ids(conn, request.label_ids)
            card_id = db.new_id()

            db.insert_card(
                conn,
                card_id=card_id,
                column_id=request.column_id.value,
                title=title,
                description=request.description.strip(),
                created_by=created_by,
            )
            db.set_card_labels(conn, card_id, label_ids)
            db.bump_revision(conn)

        return _build_board(conn)


def edit_card(card_id: str, request: CardUpdateRequest) -> KanbanBoard:
    title = request.title.strip() if request.title is not None else None
    if title is not None and not title:
        raise KanbanError("Der Titel darf nicht leer sein.")

    with db.connect() as conn:
        with db.transaction(conn):
            if not db.card_exists(conn, card_id):
                raise KanbanNotFoundError("Die Karte existiert nicht (mehr).")

            db.update_card(
                conn,
                card_id,
                title=title,
                description=(
                    request.description.strip()
                    if request.description is not None
                    else None
                ),
            )
            db.bump_revision(conn)

        return _build_board(conn)


def move_card(card_id: str, request: CardMoveRequest) -> KanbanBoard:
    with db.connect() as conn:
        with db.transaction(conn):
            moved = db.move_card(
                conn, card_id, request.column_id.value, request.position
            )
            if not moved:
                raise KanbanNotFoundError("Die Karte existiert nicht (mehr).")

            db.bump_revision(conn)

        return _build_board(conn)


def remove_card(card_id: str) -> KanbanBoard:
    with db.connect() as conn:
        with db.transaction(conn):
            if not db.delete_card(conn, card_id):
                raise KanbanNotFoundError("Die Karte existiert nicht (mehr).")

            db.bump_revision(conn)

        return _build_board(conn)


def set_card_labels(card_id: str, request: CardLabelsRequest) -> KanbanBoard:
    with db.connect() as conn:
        with db.transaction(conn):
            if not db.card_exists(conn, card_id):
                raise KanbanNotFoundError("Die Karte existiert nicht (mehr).")

            db.set_card_labels(
                conn, card_id, _validated_label_ids(conn, request.label_ids)
            )
            db.bump_revision(conn)

        return _build_board(conn)


# --------------------------------------------------------------------------
# labels
# --------------------------------------------------------------------------


def list_labels(include_archived: bool = False) -> list[KanbanLabel]:
    with db.connect() as conn:
        return [
            _label_from_row(row)
            for row in db.all_labels(conn, include_archived=include_archived)
        ]


def _next_color(conn: sqlite3.Connection) -> LabelColor:
    """Least-used colour of the palette, ties broken by palette order.

    So creating a customer needs a name and nothing else.
    """
    usage = db.color_usage(conn)
    return min(LabelColor, key=lambda color: usage.get(color.value, 0))


def create_label(request: LabelCreateRequest) -> KanbanBoard:
    name = " ".join(request.name.split())
    if not name:
        raise KanbanError("Der Name darf nicht leer sein.")

    with db.connect() as conn:
        with db.transaction(conn):
            existing = db.find_label_by_name(conn, name)
            if existing is not None:
                raise KanbanConflictError(f"„{existing['name']}“ existiert bereits.")

            color = request.color or _next_color(conn)
            db.insert_label(conn, label_id=db.new_id(), name=name, color=color.value)
            db.bump_revision(conn)

        return _build_board(conn)


def edit_label(label_id: str, request: LabelUpdateRequest) -> KanbanBoard:
    name = " ".join(request.name.split()) if request.name is not None else None
    if name is not None and not name:
        raise KanbanError("Der Name darf nicht leer sein.")

    with db.connect() as conn:
        with db.transaction(conn):
            if db.find_label(conn, label_id) is None:
                raise KanbanNotFoundError("Das Label existiert nicht (mehr).")

            if name is not None:
                clash = db.find_label_by_name(conn, name)
                if clash is not None and clash["id"] != label_id:
                    raise KanbanConflictError(f"„{clash['name']}“ existiert bereits.")

            db.update_label(
                conn,
                label_id,
                name=name,
                color=request.color.value if request.color is not None else None,
                archived=request.archived,
            )
            db.bump_revision(conn)

        return _build_board(conn)


def remove_label(label_id: str, force: bool = False) -> KanbanBoard:
    """Delete a label for good.

    Refused while it is still on cards unless `force` is set — archiving is the
    normal way to retire a customer, because deleting one strips it from every
    card it was ever on.
    """
    with db.connect() as conn:
        with db.transaction(conn):
            if db.find_label(conn, label_id) is None:
                raise KanbanNotFoundError("Das Label existiert nicht (mehr).")

            used_by = db.label_usage_count(conn, label_id)
            if used_by and not force:
                raise KanbanConflictError(
                    f"Das Label liegt noch auf {used_by} Karte(n)."
                )

            db.delete_label(conn, label_id)
            db.bump_revision(conn)

        return _build_board(conn)


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------


def export_board() -> KanbanExport:
    """Dump the board as JSON, archived labels included.

    Deliberately the full state and not the board view: this is the backup
    users can take themselves, independent of the server volume.
    """
    with db.connect() as conn:
        payload = {
            "schema_version": db.SCHEMA_VERSION,
            "revision": db.revision(conn),
            "exported_at": db.now(),
            "labels": [dict(row) for row in db.all_labels(conn, include_archived=True)],
            "cards": [dict(row) for row in db.all_cards(conn)],
            "card_labels": [
                {"card_id": card_id, "label_id": label["id"]}
                for card_id, labels in db.labels_by_card(conn).items()
                for label in labels
            ],
        }

    buffer = BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    stamp = payload["exported_at"][:10].replace("-", "")

    return KanbanExport(buffer=buffer, filename=f"kanban_{stamp}.json")


__all__ = [
    "KanbanConflictError",
    "KanbanError",
    "KanbanExport",
    "KanbanNotFoundError",
    "create_card",
    "create_label",
    "edit_card",
    "edit_label",
    "export_board",
    "get_board",
    "list_labels",
    "move_card",
    "remove_card",
    "remove_label",
    "set_card_labels",
]
