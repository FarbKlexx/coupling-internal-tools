"""Der Mailversand — was aus einer Zusage geworden ist.

Zwei Dinge sind hier interessant genug für Tests, und beide betreffen den
Übergang zwischen den zwei Werkzeugen:

* Die Liste hat **keine eigenen Kontakte**. Sie zeigt genau die Zusagen der
  Telefonakquise, und sie muss sich mitbewegen, wenn dort eine Zusage
  zurückgenommen wird.
* Der Zustand „keine Antwort" wird **gerechnet**. Es gibt keinen
  Hintergrundjob, der ihn setzt — er folgt aus dem Versanddatum, und genau
  das lässt sich nur prüfen, indem ein Versanddatum von gestern-vor-40-Tagen
  in die Datenbank geschrieben wird.

Die Zusagen entstehen hier über die echte HTTP-Oberfläche (Import → Anruf →
Zusage), nicht durch direktes INSERT: sonst prüft der Test eine Datenlage,
die die Anwendung so nie erzeugt.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.access import Page
from app.schemas.mail_followup import MAIL_TIMEOUT_DAYS, MAIL_TRANSITIONS, MailState

CSV = (
    "Betrieb;Telefon;Ort;E-Mail\r\n"
    "Erster Betrieb;05221 111;Herford;eins@example.de\r\n"
    "Zweiter Betrieb;05221 222;Enger;zwei@example.de\r\n"
    "Dritter Betrieb;05221 333;Bünde;\r\n"
).encode("utf-8")


@pytest.fixture
def zusagen(client, call_db):
    """Drei Betriebe importiert, zwei davon mit Zusage.

    Liefert `(client, ids)` mit den Kontakt-IDs der beiden Zusagen, in der
    Reihenfolge, in der sie zugesagt haben.
    """
    upload = client.post(
        "/telefonakquise/lists",
        files={"file": ("handwerker.csv", CSV, "text/csv")},
        data={"name": "Handwerker Herford"},
    )
    assert upload.status_code == 200, upload.text

    ids = []
    # Der Arbeitsplatz liefert immer genau einen Kontakt; „Erster" und
    # „Dritter" sagen zu, „Zweiter" lehnt ab.
    for outcome in ("zugesagt", "abgelehnt", "zugesagt"):
        contact = client.get("/telefonakquise/state").json()["contact"]
        assert contact is not None
        answer = client.post(
            f"/telefonakquise/contacts/{contact['id']}/outcome",
            json={"outcome": outcome},
        )
        assert answer.status_code == 200, answer.text
        if outcome == "zugesagt":
            ids.append(contact["id"])

    return client, ids


def _board(client, **params):
    response = client.get("/mailversand/board", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _click(client, contact_id, state, expected=200, **params):
    response = client.post(
        f"/mailversand/contacts/{contact_id}",
        json={"state": state},
        params=params,
    )
    assert response.status_code == expected, response.text
    return response.json()


def _backdate(call_db, contact_id, days):
    """Das Versanddatum einer Zeile in die Vergangenheit schieben.

    Der einzige Weg, die Frist zu prüfen, ohne die Uhr zu stellen: der
    Zustand „keine Antwort" hängt allein an diesem Feld.
    """
    moment = datetime.now(timezone.utc) - timedelta(days=days)
    conn = sqlite3.connect(call_db)
    conn.execute(
        "UPDATE mail_status SET sent_at = ? WHERE contact_id = ?",
        (moment.strftime("%Y-%m-%dT%H:%M:%SZ"), contact_id),
    )
    conn.commit()
    conn.close()


# ------------------------------
# Zugang
# ------------------------------


def test_without_a_session_there_is_no_board(anon_client):
    assert anon_client.get("/mailversand/board").status_code == 401


def test_the_page_permission_is_its_own(make_user):
    """Wer telefonieren darf, darf deshalb noch nicht versenden.

    Die beiden Werkzeuge teilen sich die Daten, nicht die Berechtigung — sonst
    wäre die neue Seite für jeden Anrufer sichtbar, was der Punkt der
    Aufteilung gewesen wäre.
    """
    caller, _ = make_user("anruferin", pages=[Page.TELEFONAKQUISE])
    sender, _ = make_user("versenderin", pages=[Page.MAILVERSAND])

    assert caller.get("/mailversand/board").status_code == 403
    assert sender.get("/mailversand/board").status_code == 200
    # Und umgekehrt: die Versandseite öffnet die Anrufliste nicht.
    assert sender.get("/telefonakquise/state").status_code == 403


# ------------------------------
# Die Liste
# ------------------------------


def test_the_board_shows_the_promises_and_nothing_else(zusagen):
    client, ids = zusagen

    board = _board(client)

    assert [entry["contact_id"] for entry in board["entries"]] == ids
    assert board["total"] == 2
    assert board["counters"]["gesamt"] == 2
    assert board["counters"]["offen"] == 2
    # Der abgelehnte Betrieb taucht nirgends auf.
    assert "Zweiter Betrieb" not in {entry["betrieb"] for entry in board["entries"]}


def test_a_promise_without_an_address_stays_visible_but_cannot_be_sent(zusagen):
    """Die Nacharbeit, die sonst niemand sieht.

    Sie aus der Liste zu nehmen wäre die bequeme Variante — und genau die,
    bei der die Zusage stillschweigend verfällt.
    """
    client, _ = zusagen

    board = _board(client)
    without = next(e for e in board["entries"] if e["betrieb"] == "Dritter Betrieb")

    assert without["email"] == ""
    assert board["counters"]["ohne_email"] == 1
    assert "versendet" not in without["actions"]


def test_the_promise_carries_who_took_it_and_when(zusagen):
    """Der Nachweis, auf den sich der Versand stützt, steht in der Zeile."""
    client, _ = zusagen

    entry = _board(client)["entries"][0]

    assert entry["promised_by"] == "chefin"
    assert entry["promised_at"]


def test_a_corrected_promise_leaves_the_board(zusagen):
    """Die Liste hat keine eigenen Kontakte — sie folgt der Telefonakquise.

    Wird eine Zusage richtiggestellt, verschwindet die Zeile von selbst. Eine
    eigene Kopie müsste jemand nachpflegen, und niemand würde daran denken.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    latest = client.get("/telefonakquise/decisions").json()["entries"]
    correction = next(e for e in latest if e["contact_id"] == ids[0])
    fixed = client.post(
        f"/telefonakquise/decisions/{correction['event_id']}/correct",
        json={"outcome": "kein_bedarf"},
    )
    assert fixed.status_code == 200, fixed.text

    board = _board(client)

    assert [entry["contact_id"] for entry in board["entries"]] == ids[1:]


# ------------------------------
# Die Knöpfe
# ------------------------------


def test_sending_records_the_moment_and_the_account(zusagen):
    client, ids = zusagen

    board = _click(client, ids[0], "versendet")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "versendet"
    assert entry["sent_at"]
    assert entry["answered_at"] is None
    assert entry["updated_by"] == "chefin"
    assert entry["days_since_sent"] == 0
    assert board["counters"] == {
        **board["counters"],
        "offen": 1,
        "versendet": 1,
    }


def test_an_answer_keeps_the_send_date(zusagen):
    """„Am 3. geschrieben, am 9. geantwortet" ist die Auskunft, die zählt."""
    client, ids = zusagen
    sent = _click(client, ids[0], "versendet")["entries"]
    sent_at = next(e for e in sent if e["contact_id"] == ids[0])["sent_at"]

    board = _click(client, ids[0], "positiv")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "positiv"
    assert entry["sent_at"] == sent_at
    assert entry["answered_at"]
    assert board["counters"]["positiv"] == 1


def test_a_reset_drops_the_dates_but_keeps_the_author(zusagen):
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    board = _click(client, ids[0], "offen")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "offen"
    assert entry["sent_at"] is None
    assert entry["answered_at"] is None
    # Die Zeile bleibt stehen: der Unterschied zwischen „noch nichts
    # passiert" und „zurückgesetzt von chefin" ist genau das, wonach morgen
    # jemand fragt.
    assert entry["updated_by"] == "chefin"


def test_a_transition_the_row_does_not_offer_is_refused(zusagen):
    """Die Knöpfe der Zeile und die Prüfung beim Schreiben sind dieselbe Tabelle.

    Ohne diese Prüfung stünde eine Zeile auf „Antwort positiv", ohne dass je
    eine Mail heraus war — etwa nach einem zweiten Browserfenster.
    """
    client, ids = zusagen

    body = _click(client, ids[0], "positiv", expected=400)

    assert "nicht machen" in body["detail"]


def test_a_promise_without_an_address_cannot_be_marked_as_sent(zusagen):
    client, _ = zusagen
    without = next(
        e for e in _board(client)["entries"] if e["betrieb"] == "Dritter Betrieb"
    )

    body = _click(client, without["contact_id"], "versendet", expected=400)

    assert "Dritter Betrieb" in body["detail"]


def test_a_note_survives_a_click_that_does_not_mention_it(zusagen):
    client, ids = zusagen
    client.post(
        f"/mailversand/contacts/{ids[0]}",
        json={"state": "versendet", "note": "Angebot mit Preisliste"},
    )

    board = _click(client, ids[0], "positiv")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["mail_note"] == "Angebot mit Preisliste"


def test_a_contact_that_is_gone_answers_404(zusagen):
    client, _ = zusagen

    assert (
        client.post(
            "/mailversand/contacts/gibtsnicht", json={"state": "versendet"}
        ).status_code
        == 404
    )


# ------------------------------
# Die Frist
# ------------------------------


def test_a_send_without_an_answer_becomes_unanswered_after_the_deadline(
    zusagen, call_db
):
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 1)
    board = _board(client)
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "keine_antwort"
    # Angezeigt, nicht angeklickt — sonst sieht es aus, als hätte jemand die
    # Zeile abgeschlossen.
    assert entry["automatic"] is True
    assert entry["days_since_sent"] == MAIL_TIMEOUT_DAYS + 1
    assert board["counters"]["keine_antwort"] == 1
    assert board["counters"]["versendet"] == 0


def test_one_day_short_of_the_deadline_is_still_waiting(zusagen, call_db):
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS - 1)
    entry = next(e for e in _board(client)["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "versendet"
    assert entry["automatic"] is False


def test_a_late_answer_can_still_be_recorded(zusagen, call_db):
    """Gerechnet statt geschrieben heißt: nichts ist zugemauert.

    Am 31. Tag kommt die Antwort doch — und wird eingetragen wie jede andere.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 1)

    board = _click(client, ids[0], "positiv")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "positiv"
    assert entry["automatic"] is False


def test_following_up_restarts_the_deadline(zusagen, call_db):
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 5)

    board = _click(client, ids[0], "versendet")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "versendet"
    assert entry["days_since_sent"] == 0


def test_marking_it_by_hand_needs_no_deadline(zusagen):
    client, ids = zusagen
    _click(client, ids[0], "versendet")

    board = _click(client, ids[0], "keine_antwort")
    entry = next(e for e in board["entries"] if e["contact_id"] == ids[0])

    assert entry["state"] == "keine_antwort"
    assert entry["automatic"] is False
    assert entry["answered_at"] is None


# ------------------------------
# Suche, Filter, Ausgabe
# ------------------------------


def test_the_filter_counts_the_derived_state_too(zusagen, call_db):
    """Sonst zeigte „keine Antwort" nur die von Hand abgeschlossenen Zeilen."""
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 1)

    board = _board(client, state="keine_antwort")

    assert [entry["contact_id"] for entry in board["entries"]] == [ids[0]]
    assert board["matched"] == 1
    # Die Zahlen über der Liste zählen weiter alles — sie beantworten die
    # Frage „wo stehe ich insgesamt", nicht „was ist gerade gefiltert".
    assert board["total"] == 2
    assert board["counters"]["gesamt"] == 2


def test_the_search_finds_by_business_address_and_number(zusagen):
    client, _ = zusagen

    assert _board(client, q="Dritter")["matched"] == 1
    assert _board(client, q="eins@example.de")["matched"] == 1
    assert _board(client, q="+49 5221 111")["matched"] == 1
    assert _board(client, q="Nirgendwo")["matched"] == 0


def test_a_click_answers_with_the_same_view_it_came_from(zusagen):
    """Sonst spränge die Liste nach jedem Klick auf die erste Seite zurück."""
    client, ids = zusagen

    board = _click(client, ids[0], "versendet", q="Erster")

    assert [entry["betrieb"] for entry in board["entries"]] == ["Erster Betrieb"]
    assert board["matched"] == 1


def test_the_export_names_the_state_and_why_it_is_set(zusagen, call_db):
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 2)

    response = client.get("/mailversand/export")
    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")

    assert 'filename="mailversand_' in response.headers["content-disposition"]
    # Mit BOM, weil diese Datei in Excel geöffnet wird.
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert "keine Antwort" in text
    assert "Erster Betrieb" in text
    assert "Dritter Betrieb" in text


def test_every_state_can_be_reached_from_somewhere(zusagen):
    """Ein Zustand, in den kein Übergang führt, wäre toter Code.

    Billig zu prüfen und genau die Sorte Lücke, die beim Nachtragen eines
    sechsten Zustands entsteht.
    """
    reachable = {target for targets in MAIL_TRANSITIONS.values() for target in targets}

    assert reachable == set(MailState)


def test_a_note_can_be_written_without_touching_the_state(zusagen, call_db):
    """Notiert wird, *während* eine Zeile wartet.

    Für „wartet weiter" gibt es keinen Knopf — und die abgelaufene Frist darf
    ein Notizzettel nicht als Entscheidung festschreiben.
    """
    client, ids = zusagen
    _click(client, ids[0], "versendet")
    _backdate(call_db, ids[0], MAIL_TIMEOUT_DAYS + 3)

    response = client.post(
        f"/mailversand/contacts/{ids[0]}",
        json={"note": "zweimal nachgefasst, nichts"},
    )
    assert response.status_code == 200, response.text
    entry = next(e for e in response.json()["entries"] if e["contact_id"] == ids[0])

    assert entry["mail_note"] == "zweimal nachgefasst, nichts"
    # Gespeichert steht dort weiter „versendet", angezeigt „keine Antwort":
    # die Frist bleibt gerechnet, statt durch die Notiz zementiert zu werden.
    assert entry["state"] == "keine_antwort"
    assert entry["automatic"] is True
