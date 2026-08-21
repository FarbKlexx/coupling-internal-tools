import json

import pytest

from app.schemas.kanban import (
    CardCreateRequest,
    CardMoveRequest,
    CardUpdateRequest,
    KanbanColumn,
)
from app.services.kanban_service import (
    KanbanError,
    KanbanNotFoundError,
    create_card,
    edit_card,
    export_board,
    get_board,
    move_card,
    remove_card,
)


def _column(board, column: KanbanColumn):
    return next(view for view in board.columns if view.id is column)


def _titles(board, column: KanbanColumn) -> list[str]:
    return [card.title for card in _column(board, column).cards]


def _positions(board, column: KanbanColumn) -> list[int]:
    return [card.position for card in _column(board, column).cards]


def _add(title: str, column: KanbanColumn = KanbanColumn.IDEEN):
    return create_card(CardCreateRequest(title=title, column_id=column))


def _card_id(board, title: str) -> str:
    for view in board.columns:
        for card in view.cards:
            if card.title == title:
                return card.id
    raise AssertionError(f"card {title!r} not on the board")


def test_empty_board_has_all_five_columns_in_order(kanban_db):
    board = get_board()

    assert [view.id.value for view in board.columns] == [
        "ideen",
        "todo",
        "in_progress",
        "done",
        "on_hold",
    ]
    assert [view.label for view in board.columns] == [
        "Ideen",
        "TODO",
        "In Progress",
        "Done",
        "On hold",
    ]
    # Empty columns are part of the response so the frontend never has to know
    # which columns exist.
    assert all(view.cards == [] for view in board.columns)
    assert board.labels == []
    assert board.revision == 0


def test_new_card_lands_on_top_and_pushes_the_rest_down(kanban_db):
    _add("erste")
    board = _add("zweite")

    assert _titles(board, KanbanColumn.IDEEN) == ["zweite", "erste"]
    assert _positions(board, KanbanColumn.IDEEN) == [0, 1]


def test_card_defaults_to_ideen(kanban_db):
    board = create_card(CardCreateRequest(title="ohne Spalte"))

    assert _titles(board, KanbanColumn.IDEEN) == ["ohne Spalte"]


def test_every_write_bumps_the_revision(kanban_db):
    first = _add("a").revision
    second = _add("b").revision
    card_id = _card_id(get_board(), "a")
    third = edit_card(card_id, CardUpdateRequest(title="a2")).revision

    assert first < second < third
    # A pure read does not.
    assert get_board().revision == third


def test_moving_a_card_down_by_one_is_not_a_no_op(kanban_db):
    # Created top-first, so the column reads c, b, a.
    _add("a")
    _add("b")
    board = _add("c")
    assert _titles(board, KanbanColumn.IDEEN) == ["c", "b", "a"]

    board = move_card(
        _card_id(board, "c"),
        CardMoveRequest(column_id=KanbanColumn.IDEEN, position=1),
    )

    assert _titles(board, KanbanColumn.IDEEN) == ["b", "c", "a"]
    assert _positions(board, KanbanColumn.IDEEN) == [0, 1, 2]


def test_moving_within_a_column_to_the_end(kanban_db):
    _add("a")
    _add("b")
    board = _add("c")

    board = move_card(
        _card_id(board, "c"),
        CardMoveRequest(column_id=KanbanColumn.IDEEN, position=2),
    )

    assert _titles(board, KanbanColumn.IDEEN) == ["b", "a", "c"]


def test_moving_across_columns_renumbers_both_sides(kanban_db):
    _add("a")
    _add("b")
    board = _add("c")

    board = move_card(
        _card_id(board, "b"),
        CardMoveRequest(column_id=KanbanColumn.IN_PROGRESS, position=0),
    )

    assert _titles(board, KanbanColumn.IDEEN) == ["c", "a"]
    assert _positions(board, KanbanColumn.IDEEN) == [0, 1]
    assert _titles(board, KanbanColumn.IN_PROGRESS) == ["b"]
    assert _positions(board, KanbanColumn.IN_PROGRESS) == [0]


def test_out_of_range_position_is_clamped_not_rejected(kanban_db):
    board = _add("a")

    # sortablejs can report an index that no longer exists once the card has
    # been taken out of its old column.
    board = move_card(
        _card_id(board, "a"),
        CardMoveRequest(column_id=KanbanColumn.DONE, position=99),
    )

    assert _positions(board, KanbanColumn.DONE) == [0]


def test_deleting_closes_the_gap(kanban_db):
    _add("a")
    _add("b")
    board = _add("c")

    board = remove_card(_card_id(board, "b"))

    assert _titles(board, KanbanColumn.IDEEN) == ["c", "a"]
    assert _positions(board, KanbanColumn.IDEEN) == [0, 1]


def test_edit_writes_only_the_given_fields(kanban_db):
    board = _add("titel")
    card_id = _card_id(board, "titel")

    board = edit_card(card_id, CardUpdateRequest(description="  Notiz  "))
    card = _column(board, KanbanColumn.IDEEN).cards[0]

    assert card.title == "titel"
    assert card.description == "Notiz"


def test_blank_title_is_rejected(kanban_db):
    with pytest.raises(KanbanError):
        create_card(CardCreateRequest(title="   "))


def test_unknown_card_raises_not_found(kanban_db):
    with pytest.raises(KanbanNotFoundError):
        move_card(
            "gibt-es-nicht", CardMoveRequest(column_id=KanbanColumn.DONE, position=0)
        )

    with pytest.raises(KanbanNotFoundError):
        remove_card("gibt-es-nicht")

    with pytest.raises(KanbanNotFoundError):
        edit_card("gibt-es-nicht", CardUpdateRequest(title="x"))


def test_created_by_is_stored(kanban_db):
    board = create_card(CardCreateRequest(title="mit Autor"), created_by="au")

    assert _column(board, KanbanColumn.IDEEN).cards[0].created_by == "au"


def test_export_contains_the_full_state(kanban_db):
    _add("a")

    result = export_board()
    payload = json.loads(result.buffer.getvalue().decode("utf-8"))

    assert result.filename.startswith("kanban_")
    assert result.filename.endswith(".json")
    assert payload["schema_version"] == "1"
    assert [card["title"] for card in payload["cards"]] == ["a"]
    assert payload["labels"] == []
    assert payload["card_labels"] == []
