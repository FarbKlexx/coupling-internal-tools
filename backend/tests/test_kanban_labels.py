import json

import pytest

from app.schemas.kanban import (
    CardCreateRequest,
    CardLabelsRequest,
    KanbanColumn,
    LabelColor,
    LabelCreateRequest,
    LabelUpdateRequest,
)
from app.services.kanban_service import (
    KanbanConflictError,
    KanbanNotFoundError,
    create_card,
    create_label,
    edit_label,
    export_board,
    get_board,
    list_labels,
    remove_card,
    remove_label,
    set_card_labels,
)


def _label_id(board, name: str) -> str:
    return next(label.id for label in board.labels if label.name == name)


def _first_card(board):
    return next(view for view in board.columns if view.id is KanbanColumn.IDEEN).cards[
        0
    ]


def test_creating_a_label_needs_nothing_but_a_name(kanban_db):
    board = create_label(LabelCreateRequest(name="Jeans Fritz"))

    assert [label.name for label in board.labels] == ["Jeans Fritz"]
    assert board.labels[0].color in set(LabelColor)
    assert board.labels[0].archived is False


def test_auto_colour_spreads_across_the_palette(kanban_db):
    for index in range(len(LabelColor)):
        create_label(LabelCreateRequest(name=f"Kunde {index}"))

    colors = [label.color for label in get_board().labels]

    # Least-used colour wins, so the first pass hands out every colour once.
    assert sorted(colors) == sorted(LabelColor)


def test_duplicate_name_is_refused_case_insensitively_with_umlauts(kanban_db):
    create_label(LabelCreateRequest(name="Ärzte am Ring"))

    # SQLite's built-in NOCASE only folds ASCII A-Z, which is why the service
    # normalises with casefold() into name_key.
    with pytest.raises(KanbanConflictError):
        create_label(LabelCreateRequest(name="ärzte am ring"))


def test_duplicate_name_ignores_surrounding_and_inner_whitespace(kanban_db):
    create_label(LabelCreateRequest(name="Jeans Fritz"))

    with pytest.raises(KanbanConflictError):
        create_label(LabelCreateRequest(name="  Jeans   Fritz  "))


def test_renaming_onto_another_name_is_refused_but_onto_itself_is_fine(kanban_db):
    board = create_label(LabelCreateRequest(name="Kunde A"))
    board = create_label(LabelCreateRequest(name="Kunde B"))
    a, b = _label_id(board, "Kunde A"), _label_id(board, "Kunde B")

    with pytest.raises(KanbanConflictError):
        edit_label(b, LabelUpdateRequest(name="kunde a"))

    # Same label, only the spelling changes.
    board = edit_label(a, LabelUpdateRequest(name="KUNDE A"))
    assert "KUNDE A" in [label.name for label in board.labels]
    assert b == _label_id(board, "Kunde B")


def test_labels_are_embedded_in_the_card(kanban_db):
    board = create_label(LabelCreateRequest(name="Jeans Fritz"))
    label_id = _label_id(board, "Jeans Fritz")

    board = create_card(CardCreateRequest(title="Sommerkampagne", label_ids=[label_id]))

    assert [label.name for label in _first_card(board).labels] == ["Jeans Fritz"]


def test_setting_labels_replaces_the_set_and_deduplicates(kanban_db):
    board = create_label(LabelCreateRequest(name="A"))
    board = create_label(LabelCreateRequest(name="B"))
    a, b = _label_id(board, "A"), _label_id(board, "B")

    board = create_card(CardCreateRequest(title="Karte", label_ids=[a]))
    card_id = _first_card(board).id

    board = set_card_labels(card_id, CardLabelsRequest(label_ids=[b, b]))
    assert [label.name for label in _first_card(board).labels] == ["B"]

    # Idempotent — the same call twice changes nothing.
    board = set_card_labels(card_id, CardLabelsRequest(label_ids=[b]))
    assert [label.name for label in _first_card(board).labels] == ["B"]

    board = set_card_labels(card_id, CardLabelsRequest(label_ids=[]))
    assert _first_card(board).labels == []


def test_unknown_label_id_is_refused(kanban_db):
    with pytest.raises(KanbanNotFoundError):
        create_card(CardCreateRequest(title="Karte", label_ids=["gibt-es-nicht"]))


def test_archived_label_leaves_the_picker_but_stays_on_its_cards(kanban_db):
    board = create_label(LabelCreateRequest(name="Alter Kunde"))
    label_id = _label_id(board, "Alter Kunde")
    board = create_card(CardCreateRequest(title="Altlast", label_ids=[label_id]))

    board = edit_label(label_id, LabelUpdateRequest(archived=True))

    # Gone from the picker/filter list...
    assert board.labels == []
    # ...but the card still shows which customer it belonged to.
    assert [label.name for label in _first_card(board).labels] == ["Alter Kunde"]
    assert [label.name for label in list_labels(include_archived=True)] == [
        "Alter Kunde"
    ]


def test_deleting_a_label_in_use_is_refused_until_forced(kanban_db):
    board = create_label(LabelCreateRequest(name="Kunde"))
    label_id = _label_id(board, "Kunde")
    create_card(CardCreateRequest(title="Karte", label_ids=[label_id]))

    with pytest.raises(KanbanConflictError) as excinfo:
        remove_label(label_id)
    assert "1" in str(excinfo.value)

    board = remove_label(label_id, force=True)

    assert board.labels == []
    assert _first_card(board).labels == []


def test_unused_label_deletes_without_force(kanban_db):
    board = create_label(LabelCreateRequest(name="Kunde"))

    board = remove_label(_label_id(board, "Kunde"))

    assert board.labels == []


def test_deleting_a_card_takes_its_assignments_with_it(kanban_db):
    board = create_label(LabelCreateRequest(name="Kunde"))
    label_id = _label_id(board, "Kunde")
    board = create_card(CardCreateRequest(title="Karte", label_ids=[label_id]))
    card_id = _first_card(board).id

    remove_card(card_id)

    # Cascade only fires because connect() sets PRAGMA foreign_keys = ON.
    payload = json.loads(export_board().buffer.getvalue().decode("utf-8"))
    assert payload["card_labels"] == []
    # The label itself survives.
    assert [label["name"] for label in payload["labels"]] == ["Kunde"]


def test_label_edits_bump_the_revision(kanban_db):
    board = create_label(LabelCreateRequest(name="Kunde"))
    label_id = _label_id(board, "Kunde")

    # Renaming a customer changes how every card carrying it renders, so the
    # poll has to notice.
    after = edit_label(label_id, LabelUpdateRequest(color=LabelColor.RED))

    assert after.revision > board.revision


def test_unknown_label_raises_not_found(kanban_db):
    with pytest.raises(KanbanNotFoundError):
        edit_label("gibt-es-nicht", LabelUpdateRequest(name="x"))

    with pytest.raises(KanbanNotFoundError):
        remove_label("gibt-es-nicht")
