"""Die Leitplanken um die Seitenberechtigungen.

Der Teil, der still verrottet: ein Router, der ohne Guard eingehängt wird,
bedient einen offenen Endpunkt und sieht dabei kerngesund aus. Diese Tests
machen daraus einen roten Build.
"""

from dataclasses import dataclass

from fastapi.routing import APIRoute

from app.api.deps import current_user
from app.main import FEATURE_MODULES, app
from app.schemas.access import Page

# Endpunkte, die ohne Berechtigung antworten — mit Ansage. `/health` ist die
# Container-Sonde, `/auth/*` beantwortet Fragen über den Zugang selbst.
# Alles andere hier wäre ein Fehler, deshalb eine wörtliche Liste und kein
# Präfixvergleich.
PUBLIC_PATHS = {
    "/health",
    "/auth/login",
    "/auth/logout",
    "/auth/me",
}


@dataclass
class Guards:
    """Wodurch eine Route geschützt ist.

    Drei Stufen, weil es drei gibt: eine Seitenberechtigung (die Werkzeuge),
    das Administratorflag (die Kontenverwaltung) und „irgendeine gültige
    Sitzung" (das eigene Passwort ändern, eigene Sitzungen sehen). Die dritte
    Stufe fehlte hier zuerst — und der Test hielt daraufhin völlig zu Recht
    `/auth/password` für ungeschützt.
    """

    pages: set[Page]
    admin: bool
    session: bool

    def any(self) -> bool:
        return bool(self.pages) or self.admin or self.session


def _guards_of(route: APIRoute) -> Guards:
    """Läuft den aufgelösten Abhängigkeitsbaum ab, nicht die Router-Argumente.

    So sieht der Test auch einen Guard, der an einem einzelnen Handler statt am
    Router hängt.
    """
    guards = Guards(pages=set(), admin=False, session=False)
    pending = list(route.dependant.dependencies)

    while pending:
        dependency = pending.pop()

        page = getattr(dependency.call, "guards_page", None)
        if page is not None:
            guards.pages.add(page)
        if getattr(dependency.call, "requires_admin", False):
            guards.admin = True
        if dependency.call is current_user:
            guards.session = True

        pending.extend(dependency.dependencies)

    return guards


def _api_routes() -> list[APIRoute]:
    return [route for route in app.routes if isinstance(route, APIRoute)]


def test_every_route_is_either_guarded_or_explicitly_public():
    for route in _api_routes():
        guards = _guards_of(route)

        if route.path in PUBLIC_PATHS:
            assert (
                not guards.any()
            ), f"{route.path} steht in PUBLIC_PATHS, hat aber einen Guard"
            continue

        assert guards.any(), f"ungeschützte Route: {route.path}"


def test_every_feature_route_hangs_on_a_page_not_merely_on_a_session():
    """Für die Werkzeuge genügt „angemeldet" nicht.

    Sonst könnte jedes Konto jedes Werkzeug benutzen, sobald es sich anmelden
    kann — die Seitenberechtigungen wären dann Dekoration.
    """
    feature_prefixes = tuple(module.router.prefix or "" for module in FEATURE_MODULES)

    for route in _api_routes():
        if route.path in PUBLIC_PATHS or route.path.startswith("/auth"):
            continue

        guards = _guards_of(route)
        assert guards.pages, (
            f"{route.path} verlangt nur eine Sitzung, keine Berechtigung "
            f"(bekannte Prefixe: {feature_prefixes})"
        )


def test_each_route_is_guarded_by_at_most_one_page():
    """Zwei Berechtigungen an einer Route hiesse, man braucht beide.

    Das ist hier nie gewollt — Seiten sind Bereiche der Anwendung, keine
    stapelbaren Fähigkeiten.
    """
    for route in _api_routes():
        pages = _guards_of(route).pages
        assert len(pages) <= 1, f"{route.path} haengt an mehreren Seiten: {pages}"


def test_nothing_but_api_routes_is_mounted():
    """Ein `app.mount(StaticFiles(...))` wäre für den Walker oben unsichtbar.

    Heute gibt es keinen Mount. Käme einer dazu, soll das hier auffallen und
    nicht dadurch, dass jemand ein Verzeichnis offen im Netz findet.
    """
    from starlette.routing import Route

    for route in app.routes:
        assert isinstance(route, (APIRoute, Route)), f"unerwarteter Mount: {route!r}"


def test_the_api_docs_are_off_by_default():
    """Sie lagen zuvor nur hinter der Basic Auth (ENABLE_API_DOCS=1 holt sie zurück)."""
    paths = {getattr(route, "path", "") for route in app.routes}

    assert "/openapi.json" not in paths
    assert "/docs" not in paths
    assert "/redoc" not in paths


def test_the_catalogue_and_the_routers_match_in_both_directions():
    """Keine Seite ohne Router, kein Router ohne Seite."""
    assert {module.PAGE for module in FEATURE_MODULES} == set(Page)


def test_every_feature_module_declares_its_page():
    for module in FEATURE_MODULES:
        assert isinstance(getattr(module, "PAGE", None), Page), module.__name__


# --------------------------------------------------------------------------
# Durchsetzung
# --------------------------------------------------------------------------


def test_without_a_session_every_feature_route_answers_401(anon_client):
    for path in ("/kanban/board", "/name-badges/formats"):
        assert anon_client.get(path).status_code == 401, path


def test_the_health_probe_needs_no_session(anon_client):
    assert anon_client.get("/health").status_code == 200


def test_a_user_without_the_page_gets_403(make_user):
    user_client, _ = make_user("marie", pages=[Page.QR_CODE])

    response = user_client.get("/kanban/board")

    assert response.status_code == 403
    assert "Berechtigung" in response.json()["detail"]


def test_a_user_with_the_page_gets_through(make_user):
    user_client, _ = make_user("jonas", pages=[Page.KANBAN])

    assert user_client.get("/kanban/board").status_code == 200


def test_an_admin_sees_every_page(client):
    assert client.get("/kanban/board").status_code == 200
    assert client.get("/name-badges/formats").status_code == 200

    body = client.get("/auth/me").json()
    assert body["is_admin"] is True
    assert set(body["pages"]) == {page.value for page in Page}


def test_a_normal_user_cannot_reach_the_user_administration(make_user):
    user_client, _ = make_user("lena", pages=[Page.KANBAN])

    for method, path in (
        ("get", "/auth/users"),
        ("get", "/auth/pages"),
        ("post", "/auth/sessions/revoke-all"),
    ):
        response = getattr(user_client, method)(path)
        assert response.status_code == 403, path
        assert "Administrator" in response.json()["detail"]


def test_a_fresh_account_must_change_its_password_before_using_anything(
    client, make_user
):
    """ASVS 6.4.1 — durchgesetzt im Backend, nicht nur im Frontend."""
    user_client, body = make_user("neuling", pages=[Page.KANBAN], change_password=False)

    response = user_client.get("/kanban/board")
    assert response.status_code == 403
    assert "Passwort ändern" in response.json()["detail"]

    changed = user_client.post(
        "/auth/password",
        json={
            "current_password": body["initial_password"],
            "new_password": "Ganz-Neues-Kennwort-4711",
        },
    )
    assert changed.status_code == 204

    assert user_client.get("/kanban/board").status_code == 200


def test_a_new_card_is_authored_by_the_session_user(client, kanban_db):
    """`created_by` kommt aus der Sitzung, nicht mehr aus einem Header."""
    board = client.post("/kanban/cards", json={"title": "Karte mit Autor"}).json()

    ideen = next(column for column in board["columns"] if column["id"] == "ideen")
    assert ideen["cards"][0]["created_by"] == "chefin"


def test_a_forged_header_cannot_name_the_author(client, kanban_db):
    """Der frühere `X-Remote-User` wird nicht mehr gelesen."""
    board = client.post(
        "/kanban/cards",
        json={"title": "Gefälschter Autor"},
        headers={"X-Remote-User": "eindringling"},
    ).json()

    ideen = next(column for column in board["columns"] if column["id"] == "ideen")
    assert ideen["cards"][0]["created_by"] == "chefin"
