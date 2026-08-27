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
    CallOutcome,
    ContactState,
    ListUpdateRequest,
    OutcomeRequest,
)
from app.services.call_list_service import (
    CallListConflictError,
    CallListError,
    CallListNotFoundError,
    analyse_list,
    delete_list,
    export_promised,
    export_protocol,
    get_state,
    import_list,
    record_outcome,
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


def test_a_number_already_in_an_archived_list_may_be_imported_again():
    """Eine abgeschlossene Runde darf die nächste nicht blockieren."""
    first = _import()
    update_list(first.list_id, ListUpdateRequest(archived=True))

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
