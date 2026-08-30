"""Die HTTP-Oberfläche der Telefonakquise.

Interessant sind hier zwei Dinge, die der Service nicht prüfen kann: dass die
Trennung zwischen „darf anrufen" und „darf Listen pflegen" wirklich greift, und
dass im Protokoll das Konto aus der Sitzung landet — ein Nachweis, bei dem der
Aufrufer den Namen mitschicken könnte, wäre keiner.
"""

from app.schemas.access import Page

CSV = (
    "Betrieb;Telefon;Ort;E-Mail\r\n"
    "Erster Betrieb;05221 111;Herford;eins@example.de\r\n"
    "Zweiter Betrieb;05221 222;Enger;\r\n"
).encode("utf-8")

#: Endpunkte, die nur Administratoren beantworten dürfen.
ADMIN_ROUTES = (
    ("post", "/telefonakquise/lists"),
    ("post", "/telefonakquise/lists/analyse"),
    ("patch", "/telefonakquise/lists/egal"),
    ("delete", "/telefonakquise/lists/egal"),
    ("get", "/telefonakquise/export/zusagen"),
    ("get", "/telefonakquise/export/protokoll"),
    ("get", "/telefonakquise/export/blacklist"),
    ("get", "/telefonakquise/blacklist"),
    ("post", "/telefonakquise/blacklist"),
    ("post", "/telefonakquise/blacklist/import"),
    ("delete", "/telefonakquise/blacklist/05221111"),
)


def _upload(client, name="Handwerker Herford", data=CSV):
    return client.post(
        "/telefonakquise/lists",
        files={"file": ("handwerker-herford.csv", data, "text/csv")},
        data={"name": name},
    )


# ------------------------------
# Zugang
# ------------------------------


def test_without_a_session_there_is_no_state(anon_client):
    assert anon_client.get("/telefonakquise/state").status_code == 401


def test_a_user_without_the_page_gets_403(make_user):
    user_client, _ = make_user("ohne", pages=[Page.KANBAN])

    assert user_client.get("/telefonakquise/state").status_code == 403


def test_a_caller_with_the_page_may_work_but_not_manage(client, make_user):
    """Der Anrufer braucht die Seite — die Listenpflege bleibt beim Administrator."""
    _upload(client)

    user_client, _ = make_user("anruferin", pages=[Page.TELEFONAKQUISE])

    state = user_client.get("/telefonakquise/state")
    assert state.status_code == 200
    assert state.json()["contact"]["betrieb"] == "Erster Betrieb"

    for method, path in ADMIN_ROUTES:
        response = getattr(user_client, method)(path)
        assert response.status_code == 403, path
        assert "Administrator" in response.json()["detail"], path


def test_a_caller_may_record_an_outcome(client, make_user):
    _upload(client)
    user_client, _ = make_user("anruferin", pages=[Page.TELEFONAKQUISE])

    contact = user_client.get("/telefonakquise/state").json()["contact"]

    response = user_client.post(
        f"/telefonakquise/contacts/{contact['id']}/outcome",
        json={"outcome": "zugesagt", "note": "darf Mail bekommen"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["counters"]["zugesagt"] == 1
    # Die Antwort bringt den nächsten Kontakt gleich mit.
    assert body["contact"]["betrieb"] == "Zweiter Betrieb"


def test_the_protocol_names_the_session_user_and_not_a_claim_in_the_request(
    client, make_user
):
    _upload(client)
    user_client, _ = make_user("anruferin", pages=[Page.TELEFONAKQUISE])
    contact = user_client.get("/telefonakquise/state").json()["contact"]

    user_client.post(
        f"/telefonakquise/contacts/{contact['id']}/outcome",
        json={"outcome": "abgelehnt", "username": "jemand anderes"},
        headers={"X-Remote-User": "eindringling"},
    )

    protocol = client.get("/telefonakquise/export/protokoll").text

    assert "anruferin" in protocol
    assert "eindringling" not in protocol
    assert "jemand anderes" not in protocol


# ------------------------------
# Listen pflegen
# ------------------------------


def test_an_admin_can_analyse_before_importing(client):
    response = client.post(
        "/telefonakquise/lists/analyse",
        files={"file": ("handwerker-herford-v2-analyse.csv", CSV, "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["contacts"] == 2
    assert body["name_suggestion"] == "handwerker herford v2 analyse"
    assert [entry["field"] for entry in body["mapping"]] == [
        "betrieb",
        "telefon",
        "email",
        "ort",
    ]
    # Trockenlauf heisst Trockenlauf.
    assert client.get("/telefonakquise/state").json()["counters"]["gesamt"] == 0


def test_an_admin_can_import_and_sees_the_new_state(client):
    response = _upload(client)

    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 2
    assert body["state"]["counters"]["offen"] == 2
    assert body["state"]["lists"][0]["created_by"] == "chefin"


def test_an_import_without_a_name_falls_back_to_the_filename(client):
    """Ein leeres Formularfeld kommt als *fehlend* an — das darf kein 422 sein."""
    response = client.post(
        "/telefonakquise/lists",
        files={"file": ("handwerker-herford.csv", CSV, "text/csv")},
    )

    assert response.status_code == 200
    assert response.json()["state"]["lists"][0]["name"] == "handwerker herford"


def test_a_broken_file_answers_with_a_readable_message(client):
    response = client.post(
        "/telefonakquise/lists",
        files={"file": ("liste.csv", b"Betrieb;Ort\nBau AG;Herford\n", "text/csv")},
        data={"name": "Kaputt"},
    )

    assert response.status_code == 400
    assert "Telefon" in response.json()["detail"]


def test_the_same_list_name_twice_is_a_409(client):
    _upload(client)

    response = _upload(client, data=b"Betrieb;Telefon\nNeu;05221 999\n")

    assert response.status_code == 409


def test_deleting_a_list_with_protocol_needs_force(client):
    list_id = _upload(client).json()["list_id"]
    contact = client.get("/telefonakquise/state").json()["contact"]
    client.post(
        f"/telefonakquise/contacts/{contact['id']}/outcome",
        json={"outcome": "abgelehnt"},
    )

    refused = client.delete(f"/telefonakquise/lists/{list_id}")
    assert refused.status_code == 409

    forced = client.delete(f"/telefonakquise/lists/{list_id}?force=true")
    assert forced.status_code == 200
    assert forced.json()["lists"] == []


def test_an_unknown_list_is_a_404(client):
    assert (
        client.patch(
            "/telefonakquise/lists/gibt-es-nicht", json={"archived": True}
        ).status_code
        == 404
    )


def test_an_unknown_contact_is_a_404(client):
    assert (
        client.post(
            "/telefonakquise/contacts/gibt-es-nicht/outcome",
            json={"outcome": "zugesagt"},
        ).status_code
        == 404
    )


# ------------------------------
# Ausgaben
# ------------------------------


def test_the_exports_come_as_named_csv_downloads(client):
    _upload(client)

    for path, prefix in (
        ("/telefonakquise/export/zusagen", "zusagen_"),
        ("/telefonakquise/export/protokoll", "telefonprotokoll_"),
    ):
        response = client.get(path)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert prefix in response.headers["content-disposition"]
        assert response.headers["content-disposition"].endswith('.csv"')


# ------------------------------
# Prio-Auswahl und Blacklist
# ------------------------------

PRIO_CSV = (
    "Betrieb;Telefon;Prio\r\n"
    "Alpha;05221 111;A\r\n"
    "Beta;05221 222;B\r\n"
    "Gamma;05221 333;A\r\n"
).encode("utf-8")


def test_the_dry_run_hands_the_prio_values_to_the_form(client):
    response = client.post(
        "/telefonakquise/lists/analyse",
        files={"file": ("auswertung.csv", PRIO_CSV, "text/csv")},
    )

    body = response.json()
    assert body["prio_column"] == "Prio"
    assert [(entry["value"], entry["rows"]) for entry in body["prio_values"]] == [
        ("a", 2),
        ("b", 1),
    ]


def test_the_import_takes_the_prio_selection_as_a_json_field(client):
    response = client.post(
        "/telefonakquise/lists",
        files={"file": ("auswertung.csv", PRIO_CSV, "text/csv")},
        data={"name": "Nur A", "prios": '["a"]'},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 2
    assert body["prio_skipped"] == 1


def test_an_absent_prio_field_means_all_prios(client):
    """Ein leeres Formularfeld kommt als *fehlend* an — das darf nicht filtern."""
    response = _upload(client, data=PRIO_CSV)

    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 3


def test_an_unreadable_prio_selection_is_a_400_and_not_a_422(client):
    response = client.post(
        "/telefonakquise/lists",
        files={"file": ("auswertung.csv", PRIO_CSV, "text/csv")},
        data={"name": "Kaputt", "prios": "A,B"},
    )

    assert response.status_code == 400
    assert "Prio-Auswahl" in response.json()["detail"]


def test_the_state_carries_the_size_of_the_blacklist(client):
    assert client.get("/telefonakquise/state").json()["blacklist_count"] == 0

    _upload(client)

    assert client.get("/telefonakquise/state").json()["blacklist_count"] == 2


def test_the_blacklist_is_paged_and_searchable(client):
    _upload(client)

    page = client.get(
        "/telefonakquise/blacklist", params={"q": "Zweiter", "limit": 1}
    ).json()

    assert page["total"] == 2
    assert page["matched"] == 1
    assert page["entries"][0]["betrieb"] == "Zweiter Betrieb"


def test_a_number_can_be_blocked_by_hand_and_released_again(client):
    added = client.post(
        "/telefonakquise/blacklist",
        json={"numbers": "05221 111", "note": "Bestandskunde"},
    )
    assert added.status_code == 200, added.text
    assert added.json()["added"] == 1

    # Die gesperrte Nummer kommt nicht mehr in eine Liste.
    imported = _upload(client)
    assert imported.json()["imported"] == 1

    released = client.delete("/telefonakquise/blacklist/05221111")
    assert released.status_code == 200
    assert released.json()["total"] == 1


def test_releasing_an_unknown_number_is_a_404(client):
    assert client.delete("/telefonakquise/blacklist/05221999").status_code == 404


def test_a_blacklist_csv_can_be_uploaded(client):
    response = client.post(
        "/telefonakquise/blacklist/import",
        files={
            "file": (
                "sperrliste.csv",
                "Telefon;Betrieb\r\n05221 111;Alpha\r\n".encode("utf-8"),
                "text/csv",
            )
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["added"] == 1
    assert response.json()["page"]["entries"][0]["betrieb"] == "Alpha"


def test_the_blacklist_export_is_a_csv_download(client):
    _upload(client)

    response = client.get("/telefonakquise/export/blacklist")

    assert response.status_code == 200
    assert "blacklist_" in response.headers["content-disposition"]
    assert "Erster Betrieb" in response.content.decode("utf-8-sig")
