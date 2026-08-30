"""Fachregeln der Telefonakquise.

Der Kern ist die Frage „wer ist als nächstes dran" — und die hat mehr Fälle,
als sie aussieht: ein vereinbarter Rückruf schlägt einen noch nie angerufenen
Betrieb, eine Wiedervorlage nicht. Dazu das Protokoll, das nur wachsen darf,
und die Zähler, an denen der Anrufer sieht, wie weit er ist.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core import call_list_db as db
from app.schemas.call_list import (
    CALLBACK_LEAD_MINUTES,
    POOL_STATES,
    BlacklistAddRequest,
    BlacklistSource,
    CallOutcome,
    ContactState,
    ListUpdateRequest,
    OutcomeRequest,
)
from app.services.call_list_service import (
    CallListConflictError,
    CallListError,
    CallListNotFoundError,
    add_blacklist_numbers,
    analyse_list,
    delete_list,
    export_blacklist,
    export_promised,
    export_protocol,
    get_blacklist,
    get_state,
    import_blacklist,
    import_list,
    record_outcome,
    remove_blacklist_entry,
    update_list,
)

pytestmark = pytest.mark.usefixtures("call_db")

HEADER = "Betrieb;Telefon;Ort;E-Mail;Befunde"


def _csv(*rows: str) -> bytes:
    return ("\r\n".join([HEADER, *rows]) + "\r\n").encode("utf-8")


def _three() -> bytes:
    return _csv(
        "Erster Betrieb;05221 111;Herford;;kein HTTPS",
        "Zweiter Betrieb;05221 222;Enger;zwei@example.de;Copyright 2010",
        "Dritter Betrieb;05221 333;Bünde;;am Handy unlesbar",
    )


def _import(data: bytes | None = None, name: str = "Handwerker Herford"):
    return import_list(
        data if data is not None else _three(),
        "handwerker-herford.csv",
        name,
        created_by="chefin",
    )


def _answer(contact_id: str, outcome: CallOutcome, **kwargs):
    return record_outcome(
        contact_id,
        OutcomeRequest(outcome=outcome, **kwargs),
        user_id="u1",
        username="anruferin",
    )


def _in(minutes: int) -> str:
    """Ein Zeitpunkt mit Zeitzone, so wie ihn der Browser schickt."""
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


# ------------------------------
# Import
# ------------------------------


def test_an_import_makes_contacts_in_file_order():
    result = _import()

    assert result.imported == 3

    state = result.state
    assert state.counters.gesamt == 3
    assert state.counters.offen == 3
    assert state.contact is not None
    # Reihenfolge der Datei, nicht der Zufall der UUIDs.
    assert state.contact.betrieb == "Erster Betrieb"
    assert state.contact.ort == "Herford"
    assert state.contact.list_name == "Handwerker Herford"
    assert state.contact.state is ContactState.OFFEN


def test_extra_columns_travel_with_the_contact():
    result = import_list(
        (
            "Betrieb;Telefon;Punkte;CMS\r\n" "Bau AG;05221 111;11;WordPress 5.8\r\n"
        ).encode("utf-8"),
        "liste.csv",
        "Mit Zusatzspalten",
        created_by="chefin",
    )

    extras = {field.label: field.value for field in result.state.contact.extras}

    assert extras == {"Punkte": "11", "CMS": "WordPress 5.8"}


def test_a_second_list_with_the_same_name_is_a_conflict():
    _import()

    with pytest.raises(CallListConflictError, match="bereits eine Liste"):
        _import(_csv("Anderer Betrieb;05221 999;Löhne;;egal"))


def test_the_same_number_in_a_second_list_is_skipped_with_the_first_list_named():
    _import()

    result = _import(
        _csv(
            "Erster Betrieb noch mal;05221 111;Herford;;egal",
            "Wirklich neu;05221 444;Vlotho;;egal",
        ),
        name="Zweite Runde",
    )

    assert result.imported == 1
    assert len(result.duplicates) == 1
    assert "Handwerker Herford" in result.duplicates[0].reason


def test_the_same_number_twice_in_one_file_is_imported_once():
    result = _import(
        _csv(
            "Bau AG;+49 5221 111;Herford;;egal",
            "Bau AG Zweigstelle;05221 111;Herford;;egal",
        )
    )

    assert result.imported == 1
    # Dieselbe Nummer in zwei Schreibweisen — der Vergleichsschlüssel fängt das.
    assert "Zeile 2" in result.duplicates[0].reason


def test_an_archived_list_still_blocks_its_numbers_via_the_blacklist():
    """Archivieren beendet die Runde, hebt die Sperre aber nicht auf.

    Genau der Fall, für den es die Blacklist gibt: zwei Auswertungen desselben
    Gebiets überschneiden sich, und der zweite Import darf die Betriebe aus
    dem ersten nicht noch einmal in den Vorrat legen — auch dann nicht, wenn
    die erste Liste längst stillgelegt ist.
    """
    first = _import()
    update_list(first.list_id, ListUpdateRequest(archived=True))

    with pytest.raises(CallListError, match="schon bekannt"):
        _import(name="Zweite Runde")


def test_deleting_a_list_releases_its_numbers_again():
    """Löschen heißt „hat nicht stattgefunden" — Archivieren heißt „beendet".

    Ohne diesen Unterschied wäre eine versehentlich importierte Datei nicht
    mehr zu korrigieren: die Liste ließe sich löschen, ihre Nummern blieben
    aber für immer gesperrt.
    """
    first = _import()
    delete_list(first.list_id, force=True)

    again = _import(name="Zweite Runde")

    assert again.imported == 3
    assert again.duplicates == []


def test_a_file_that_is_entirely_duplicate_is_rejected():
    _import()

    with pytest.raises(CallListError, match="nichts zu importieren"):
        _import(name="Zweite Runde")


def test_the_dry_run_sees_what_the_import_would_do():
    _import()

    report = analyse_list(
        _csv(
            "Erster Betrieb;05221 111;Herford;;egal",
            "Neu;05221 999;Löhne;neu@example.de;egal",
        ),
        "handwerker-herford-v2-analyse.csv",
    )

    assert report.data_rows == 2
    assert report.contacts == 1
    assert len(report.duplicates) == 1
    assert report.name_suggestion == "handwerker herford v2 analyse"
    assert report.delimiter == "Semikolon"
    # Nichts gespeichert: es gibt weiter nur die eine Liste.
    assert len(get_state().lists) == 1


# ------------------------------
# Ergebnis eintragen
# ------------------------------


def test_a_promise_leaves_the_pool_and_lands_in_the_protocol():
    state = _import().state
    contact_id = state.contact.id

    after = _answer(
        contact_id,
        CallOutcome.ZUGESAGT,
        email="chef@erster-betrieb.de",
        note="Will das Angebot per Mail.",
    )

    assert after.counters.offen == 2
    assert after.counters.zugesagt == 1
    assert after.counters.zugesagt_ohne_email == 0
    # Der nächste Kontakt kommt gleich mit.
    assert after.contact.betrieb == "Zweiter Betrieb"

    with db.connect() as conn:
        events = db.events_of_contact(conn, contact_id)

    assert len(events) == 1
    assert events[0]["outcome"] == "zugesagt"
    assert events[0]["username"] == "anruferin"
    # Die Adresse, für die zugestimmt wurde, steht in der Protokollzeile selbst.
    assert events[0]["email"] == "chef@erster-betrieb.de"
    assert events[0]["betrieb"] == "Erster Betrieb"


def test_a_promise_without_an_address_is_counted_separately():
    state = _import().state

    after = _answer(state.contact.id, CallOutcome.ZUGESAGT)

    assert after.counters.zugesagt == 1
    assert after.counters.zugesagt_ohne_email == 1


def test_an_email_asked_for_during_the_call_is_written_to_the_contact():
    state = _import().state
    contact_id = state.contact.id

    _answer(contact_id, CallOutcome.ZUGESAGT, email=" info@erster.de ")

    with db.connect() as conn:
        row = db.find_contact(conn, contact_id)

    assert row["email"] == "info@erster.de"


def test_a_known_address_survives_an_outcome_that_does_not_mention_it():
    """`email=None` heisst unverändert — nicht „löschen"."""
    state = _import().state
    # Der zweite Betrieb hat eine Adresse aus der Datei.
    second = _answer(state.contact.id, CallOutcome.NUMMER_FALSCH).contact

    assert second.email == "zwei@example.de"

    _answer(second.id, CallOutcome.ZUGESAGT, note="nur eine Notiz")

    with db.connect() as conn:
        row = db.find_contact(conn, second.id)

    assert row["email"] == "zwei@example.de"


@pytest.mark.parametrize("email", ["keinatzeichen.de", "zwei@@example.de", "a b@c.de"])
def test_an_address_that_is_no_address_is_refused(email):
    state = _import().state

    with pytest.raises(CallListError, match="E-Mail-Adresse"):
        _answer(state.contact.id, CallOutcome.ZUGESAGT, email=email)


def test_a_refusal_is_final_and_counted():
    state = _import().state

    after = _answer(state.contact.id, CallOutcome.ABGELEHNT, note="kein Interesse")

    assert after.counters.abgelehnt == 1
    assert after.counters.offen == 2


def test_a_wrong_number_does_not_count_as_an_attempt():
    """Das war kein Anrufversuch beim Betrieb, sondern ein Fund über die Liste."""
    state = _import().state
    contact_id = state.contact.id

    _answer(contact_id, CallOutcome.NUMMER_FALSCH)

    with db.connect() as conn:
        row = db.find_contact(conn, contact_id)

    assert row["attempts"] == 0
    assert row["state"] == ContactState.UNGUELTIG.value


def test_an_unreachable_contact_leaves_the_counter_and_comes_back_later():
    state = _import().state
    contact_id = state.contact.id

    after = _answer(contact_id, CallOutcome.NICHT_ERREICHBAR, snooze_minutes=120)

    assert after.counters.offen == 2
    assert after.counters.wiedervorlage == 1
    assert after.next_due_at is not None
    # Nicht mehr vorne: der nächste noch nie angerufene Betrieb ist dran.
    assert after.contact.betrieb == "Zweiter Betrieb"

    with db.connect() as conn:
        row = db.find_contact(conn, contact_id)

    assert row["attempts"] == 1


def test_a_due_deferral_is_back_in_the_pool_but_behind_the_untried_ones():
    """„Nach hinten in die Liste" heisst: hinter alles, was noch nie dran war."""
    state = _import().state
    first = state.contact.id

    # Ein Zeitpunkt in der Vergangenheit wird auf „jetzt" gezogen, ist also
    # sofort wieder fällig.
    after = _answer(first, CallOutcome.NICHT_ERREICHBAR, due_at=_in(-30))

    assert after.counters.offen == 3
    assert after.counters.wiedervorlage == 0
    assert after.contact.betrieb == "Zweiter Betrieb"

    # Nach den beiden anderen kommt der aufgeschobene wieder.
    second = _answer(after.contact.id, CallOutcome.ABGELEHNT)
    third = _answer(second.contact.id, CallOutcome.ABGELEHNT)

    assert third.contact.id == first
    assert third.contact.state is ContactState.WIEDERVORLAGE


def test_unreachable_without_a_time_is_refused():
    state = _import().state

    with pytest.raises(CallListError, match="fehlt der Zeitpunkt"):
        _answer(state.contact.id, CallOutcome.NICHT_ERREICHBAR)


def test_a_deferral_beyond_the_horizon_is_refused():
    state = _import().state

    with pytest.raises(CallListError, match="Zukunft"):
        _answer(state.contact.id, CallOutcome.NICHT_ERREICHBAR, due_at=_in(200 * 1440))


def test_a_timestamp_without_a_timezone_is_refused():
    """Sonst liegt jeder Rückruf im Sommer zwei Stunden daneben."""
    state = _import().state

    with pytest.raises(CallListError, match="ohne Zeitzone"):
        _answer(
            state.contact.id,
            CallOutcome.NICHT_ERREICHBAR,
            due_at="2026-09-01T09:00:00",
        )


# ------------------------------
# Rückrufe
# ------------------------------


def test_a_callback_appears_before_the_agreed_time():
    state = _import().state
    contact_id = state.contact.id
    appointment = datetime.now(timezone.utc) + timedelta(minutes=120)

    after = _answer(
        contact_id, CallOutcome.RUECKRUF, appointment_at=appointment.isoformat()
    )

    assert after.counters.wiedervorlage == 1

    with db.connect() as conn:
        row = db.find_contact(conn, contact_id)

    assert row["state"] == ContactState.RUECKRUF.value

    due = datetime.strptime(row["due_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    lead = (appointment - due).total_seconds() / 60

    assert CALLBACK_LEAD_MINUTES - 1 <= lead <= CALLBACK_LEAD_MINUTES + 1


def test_a_due_callback_beats_every_contact_that_was_never_called():
    """Ein zugesagter Termin ist eine Verpflichtung, ein offener Kontakt nicht."""
    state = _import().state
    first = state.contact.id

    # Termin in 10 Minuten: mit 15 Minuten Vorlauf ist der Kontakt sofort fällig.
    after = _answer(first, CallOutcome.RUECKRUF, appointment_at=_in(10))

    assert after.contact.id == first
    assert after.contact.state is ContactState.RUECKRUF
    assert after.contact.appointment_at is not None


def test_a_callback_without_an_appointment_is_refused():
    state = _import().state

    with pytest.raises(CallListError, match="fehlt der Termin"):
        _answer(state.contact.id, CallOutcome.RUECKRUF)


# ------------------------------
# Protokoll
# ------------------------------


def test_the_protocol_only_grows():
    state = _import().state
    contact_id = state.contact.id

    _answer(contact_id, CallOutcome.NICHT_ERREICHBAR, due_at=_in(-5))
    _answer(contact_id, CallOutcome.ZUGESAGT, email="a@b.de")

    with db.connect() as conn:
        events = db.events_of_contact(conn, contact_id)

    # Beide Versuche stehen drin, jüngster zuerst.
    assert [event["outcome"] for event in events] == ["zugesagt", "nicht_erreichbar"]


def test_the_contact_carries_its_own_history():
    """Die Antwort auf „habe ich hier schon mal angerufen?" steht am Kontakt."""
    # Einzeiler, damit der aufgeschobene Kontakt sofort wieder der nächste ist
    # und nicht hinter zwei noch nie versuchten steht.
    state = _import(_csv("Einziger;05221 111;Herford;;egal")).state
    contact_id = state.contact.id

    after = _answer(contact_id, CallOutcome.NICHT_ERREICHBAR, due_at=_in(-5))

    assert after.contact.id == contact_id
    assert len(after.contact.history) == 1
    assert after.contact.history[0].outcome is CallOutcome.NICHT_ERREICHBAR
    assert after.contact.history[0].username == "anruferin"


def test_an_unknown_contact_is_a_404():
    _import()

    with pytest.raises(CallListNotFoundError):
        _answer("gibt-es-nicht", CallOutcome.ZUGESAGT)


# ------------------------------
# Listen verwalten
# ------------------------------


def test_archiving_empties_the_pool_but_keeps_the_protocol():
    result = _import()
    _answer(result.state.contact.id, CallOutcome.ZUGESAGT, email="a@b.de")

    after = update_list(result.list_id, ListUpdateRequest(archived=True))

    assert after.contact is None
    assert after.counters.gesamt == 0
    assert after.lists[0].archived is True
    # Die Zusage bleibt in der Ausgabe, obwohl die Liste still ist.
    assert b"a@b.de" in export_promised().buffer.getvalue()


def test_a_list_can_be_renamed():
    result = _import()

    after = update_list(result.list_id, ListUpdateRequest(name="Handwerker Herford II"))

    assert after.lists[0].name == "Handwerker Herford II"
    assert after.contact.list_name == "Handwerker Herford II"


def test_renaming_onto_an_existing_name_is_a_conflict():
    first = _import()
    _import(_csv("Neu;05221 999;Löhne;;egal"), name="Zweite Runde")

    with pytest.raises(CallListConflictError):
        update_list(first.list_id, ListUpdateRequest(name="zweite   runde"))


def test_deleting_a_list_with_documented_calls_needs_confirmation():
    result = _import()
    _answer(result.state.contact.id, CallOutcome.ZUGESAGT, email="a@b.de")

    with pytest.raises(CallListConflictError, match="protokolliert"):
        delete_list(result.list_id)

    after = delete_list(result.list_id, force=True)

    assert after.lists == []
    assert after.counters.gesamt == 0


def test_deleting_an_untouched_list_needs_no_confirmation():
    result = _import()

    after = delete_list(result.list_id)

    assert after.lists == []


def test_a_contact_of_an_archived_list_cannot_be_answered():
    result = _import()
    contact_id = result.state.contact.id
    update_list(result.list_id, ListUpdateRequest(archived=True))

    with pytest.raises(CallListError, match="archiviert"):
        _answer(contact_id, CallOutcome.ZUGESAGT)


def test_per_list_counters_count_that_list():
    first = _import()
    _answer(first.state.contact.id, CallOutcome.ABGELEHNT)
    second = _import(_csv("Neu;05221 999;Löhne;;egal"), name="Zweite Runde")

    by_id = {entry.id: entry for entry in second.state.lists}

    assert by_id[first.list_id].counters.abgelehnt == 1
    assert by_id[first.list_id].counters.offen == 2
    assert by_id[second.list_id].counters.offen == 1


# ------------------------------
# Ausgaben
# ------------------------------


def test_the_promise_export_carries_who_agreed_and_when():
    result = _import()
    _answer(
        result.state.contact.id,
        CallOutcome.ZUGESAGT,
        email="chef@erster.de",
        note="Angebot bis Freitag",
    )

    text = export_promised().buffer.getvalue().decode("utf-8-sig")
    lines = text.splitlines()

    assert lines[0].startswith("Betrieb;E-Mail")
    assert "Erster Betrieb;chef@erster.de" in lines[1]
    assert "anruferin" in lines[1]
    assert "Angebot bis Freitag" in lines[1]
    # Nur Zusagen, nicht die ganze Liste.
    assert len(lines) == 2


def test_the_protocol_export_has_one_line_per_call():
    result = _import()
    contact_id = result.state.contact.id
    _answer(contact_id, CallOutcome.NICHT_ERREICHBAR, snooze_minutes=60)
    _answer(contact_id, CallOutcome.ABGELEHNT, note="ausdrücklich nein")

    lines = export_protocol().buffer.getvalue().decode("utf-8-sig").splitlines()

    assert len(lines) == 3
    assert "Nicht erreichbar" in lines[1]
    assert "ausdrücklich nein" in lines[2]
    assert "Handwerker Herford" in lines[2]


def test_the_export_starts_with_a_bom_so_excel_reads_umlauts():
    _import()

    assert export_protocol().buffer.getvalue().startswith(b"\xef\xbb\xbf")


# ------------------------------
# Leerlauf
# ------------------------------


def test_without_any_list_there_is_nothing_to_do_and_that_is_not_an_error():
    state = get_state()

    assert state.contact is None
    assert state.counters.offen == 0
    assert state.next_due_at is None
    # Die Knöpfe kommen trotzdem mit — das Frontend baut seine Oberfläche daraus.
    assert len(state.outcomes) == 5


def test_when_everything_is_deferred_the_state_says_when_it_comes_back():
    result = _import(_csv("Einziger;05221 111;Herford;;egal"))

    after = _answer(
        result.state.contact.id, CallOutcome.NICHT_ERREICHBAR, snooze_minutes=90
    )

    assert after.contact is None
    assert after.counters.offen == 0
    assert after.counters.wiedervorlage == 1
    assert after.next_due_at is not None


def test_every_write_bumps_the_revision():
    """Darauf entscheidet der Poll im Frontend, ob er den Stand ersetzt."""
    before = get_state().revision
    result = _import()

    assert result.state.revision > before

    after = _answer(result.state.contact.id, CallOutcome.ZUGESAGT)

    assert after.revision > result.state.revision


def test_the_pool_states_of_the_schema_and_the_database_module_agree():
    """Die Rangfolge in `next_contact` nennt sie als Text — hier gegengeprüft."""
    assert {state.value for state in POOL_STATES} == {
        "offen",
        "wiedervorlage",
        "rueckruf",
    }
    assert "'rueckruf', 'offen', 'wiedervorlage'" in db._POOL_FILTER


# --------------------------------------------------------------------------
# Prio-Auswahl beim Import
# --------------------------------------------------------------------------

PRIO_HEADER = "Betrieb;Telefon;Prio"


def _prio_csv(*rows: str) -> bytes:
    return ("\r\n".join([PRIO_HEADER, *rows]) + "\r\n").encode("utf-8")


def _mixed_prios() -> bytes:
    return _prio_csv(
        "Alpha;05221 111;A",
        "Beta;05221 222;B",
        "Gamma;05221 333;a",
        "Delta;05221 444;",
        "Epsilon;05221 555;C",
    )


def test_the_dry_run_reports_the_prio_values_of_the_file():
    """Die Werte kommen aus der Datei, nicht aus einer Aufzählung im Code."""
    report = analyse_list(_mixed_prios(), "auswertung.csv")

    assert report.prio_column == "Prio"
    assert [
        (option.value, option.label, option.rows) for option in report.prio_values
    ] == [
        ("a", "A", 2),
        ("b", "B", 1),
        ("__ohne__", "(ohne Prio)", 1),
        ("c", "C", 1),
    ]
    # Ohne Bestand ist jede Zeile auch ein Kontakt.
    assert [option.contacts for option in report.prio_values] == [2, 1, 1, 1]


def test_a_file_without_a_prio_column_offers_no_selection():
    report = analyse_list(_three(), "handwerker.csv")

    assert report.prio_column is None
    assert report.prio_values == []


def test_only_the_selected_prios_are_imported():
    result = import_list(
        _mixed_prios(), "auswertung.csv", "Nur A", created_by="chefin", prios=["a"]
    )

    assert result.imported == 2
    assert result.prio_skipped == 3

    state = get_state()
    assert state.counters.gesamt == 2
    assert state.contact.betrieb == "Alpha"


def test_the_prio_selection_ignores_case_and_spacing():
    """„A" und „a" sind dieselbe Prio — sonst steht sie zweimal in der Auswahl."""
    result = import_list(
        _mixed_prios(), "auswertung.csv", "Nur A", created_by="chefin", prios=["  A "]
    )

    assert result.imported == 2


def test_rows_without_a_prio_are_selectable_on_their_own():
    result = import_list(
        _mixed_prios(),
        "auswertung.csv",
        "Ohne Prio",
        created_by="chefin",
        prios=["__ohne__"],
    )

    assert result.imported == 1
    assert get_state().contact.betrieb == "Delta"


def test_an_empty_prio_selection_is_a_mistake_and_not_an_empty_list():
    with pytest.raises(CallListError, match="keine Prio ausgewählt"):
        import_list(
            _mixed_prios(), "auswertung.csv", "Nichts", created_by="chefin", prios=[]
        )


def test_filtering_by_prio_needs_a_prio_column():
    with pytest.raises(CallListError, match="keine Prio-Spalte"):
        import_list(
            _three(), "handwerker.csv", "Egal", created_by="chefin", prios=["a"]
        )


def test_the_prio_filter_runs_before_the_duplicate_check():
    """Sonst zeigt eine Duplikatmeldung auf eine Zeile, die gar nicht kommt.

    Zeile 2 (Prio B) und Zeile 3 (Prio A) haben dieselbe Nummer. Wird nur A
    importiert, ist Zeile 3 kein Duplikat von Zeile 2 — Zeile 2 wird nicht
    importiert.
    """
    data = _prio_csv("Alt;05221 111;B", "Neu;05221 111;A")

    result = import_list(
        data, "auswertung.csv", "Nur A", created_by="chefin", prios=["a"]
    )

    assert result.imported == 1
    assert result.duplicates == []
    assert get_state().contact.betrieb == "Neu"


def test_the_preview_count_per_prio_subtracts_what_is_already_known():
    _import(_prio_csv("Alpha;05221 111;A"), name="Erste Runde")

    report = analyse_list(_mixed_prios(), "auswertung.csv")
    by_value = {option.value: option for option in report.prio_values}

    assert by_value["a"].rows == 2
    # Alpha ist schon bekannt, Gamma nicht.
    assert by_value["a"].contacts == 1


# --------------------------------------------------------------------------
# Blacklist
# --------------------------------------------------------------------------


def test_every_imported_number_lands_on_the_blacklist():
    result = _import()

    assert result.blacklisted == 3

    page = get_blacklist()
    assert page.total == 3
    assert {entry.betrieb for entry in page.entries} == {
        "Erster Betrieb",
        "Zweiter Betrieb",
        "Dritter Betrieb",
    }
    assert all(entry.source is BlacklistSource.IMPORT for entry in page.entries)
    assert all(entry.list_name == "Handwerker Herford" for entry in page.entries)


def test_two_overlapping_lists_import_only_the_difference():
    """Der Fall, um den es geht: zwei Auswertungen mit gemeinsamen Betrieben."""
    _import()

    second = _import(
        _csv(
            "Erster Betrieb;05221 111;Herford;;doppelt",
            "Vierter Betrieb;05221 444;Löhne;;neu",
        ),
        name="Zweite Runde",
    )

    assert second.imported == 1
    assert len(second.duplicates) == 1
    assert "Erster Betrieb" in second.duplicates[0].reason


def test_the_duplicate_reason_names_the_blacklist_when_the_list_is_gone():
    """Eine Duplikatmeldung ohne den Ort des Originals ist nicht handlungsfähig."""
    first = _import()
    update_list(first.list_id, ListUpdateRequest(archived=True))

    report = analyse_list(
        _csv("Erster Betrieb;05221 111;Herford;;egal"), "zweite-runde.csv"
    )

    assert len(report.duplicates) == 1
    assert "Handwerker Herford" in report.duplicates[0].reason


def test_a_number_blocked_by_hand_never_enters_a_list():
    add_blacklist_numbers(
        BlacklistAddRequest(numbers="05221 222", note="Bestandskunde"),
        created_by="chefin",
    )

    result = _import()

    assert result.imported == 2
    assert "von Hand gesperrt" in result.duplicates[0].reason
    assert "Bestandskunde" in result.duplicates[0].reason


def test_pasted_lines_may_carry_the_name_on_either_side():
    """Eingefügt wird, was zur Hand ist — nicht eine feste Spaltenreihenfolge."""
    result = add_blacklist_numbers(
        BlacklistAddRequest(
            numbers="05221 111\nZaunbau Müller;05221 222\n05221 333;Dachdecker Klein",
            note="",
        ),
        created_by="chefin",
    )

    assert result.added == 3
    by_key = {entry.telefon_key: entry.betrieb for entry in result.page.entries}
    assert by_key["05221222"] == "Zaunbau Müller"
    assert by_key["05221333"] == "Dachdecker Klein"
    assert by_key["05221111"] == ""


def test_pasted_lines_without_a_number_are_reported_not_swallowed():
    result = add_blacklist_numbers(
        BlacklistAddRequest(numbers="05221 111\nkeine Nummer", note=""),
        created_by="chefin",
    )

    assert result.added == 1
    assert len(result.skipped) == 1
    assert result.skipped[0].line == 2


def test_adding_a_number_twice_says_so_instead_of_counting_it():
    add_blacklist_numbers(BlacklistAddRequest(numbers="05221 111"), created_by="chefin")

    again = add_blacklist_numbers(
        BlacklistAddRequest(numbers="+49 5221 111"), created_by="chefin"
    )

    assert again.added == 0
    assert again.already_known == 1
    assert again.page.total == 1


def test_a_blacklist_csv_needs_only_the_phone_column():
    result = import_blacklist(
        "Telefon\r\n05221 111\r\n05221 222\r\n".encode("utf-8"),
        created_by="chefin",
    )

    assert result.added == 2
    assert get_blacklist().total == 2


def test_a_blacklist_csv_without_a_phone_column_is_rejected():
    with pytest.raises(CallListError, match="Telefonnummern"):
        import_blacklist(
            "Betrieb;Ort\r\nAlpha;Herford\r\n".encode("utf-8"), created_by="chefin"
        )


def test_releasing_a_number_lets_it_in_again():
    first = _import()
    update_list(first.list_id, ListUpdateRequest(archived=True))

    remove_blacklist_entry(db.phone_key("05221 111"))

    again = _import(_csv("Erster Betrieb;05221 111;Herford;;wieder"), name="Neu")
    assert again.imported == 1


def test_releasing_a_number_that_is_not_blocked_is_a_404():
    with pytest.raises(CallListNotFoundError):
        remove_blacklist_entry("05221999")


def test_the_blacklist_search_finds_a_number_in_any_spelling():
    _import()

    assert get_blacklist(query="+49 5221 111").matched == 1
    assert get_blacklist(query="Zweiter").matched == 1
    assert get_blacklist(query="gibtsnicht").matched == 0
    # `total` bleibt die Gesamtzahl, damit die Ansicht „3 von 3" zeigen kann.
    assert get_blacklist(query="gibtsnicht").total == 3


def test_the_blacklist_export_can_be_read_back_in():
    _import()
    exported = export_blacklist().buffer.getvalue()

    delete_list(get_state().lists[0].id, force=True)
    assert get_blacklist().total == 0

    result = import_blacklist(exported, created_by="chefin")
    assert result.added == 3
