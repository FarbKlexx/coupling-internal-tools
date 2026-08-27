"""Page permissions — the vocabulary shared with the frontend.

The one thing both sides of the app have to agree on if a user is to be given
access to some tools and not others. Deliberately kept as small as possible:
opaque ids, nothing else. The German labels, icons and paths that belong to
these pages stay in the frontend route meta
(`frontend/src/router/index.ts`), where they already live — repeating them
here would duplicate UI strings across the language boundary for no gain.

`frontend/src/router/pageIds.test.ts` reads this enum and asserts that both
sides know the same ids, the same way `labelPalette.test.ts` does for the
kanban colours.
"""

from enum import Enum

from pydantic import BaseModel


class Page(str, Enum):
    """Every area of the app a permission can be granted for.

    One member per feature router; `tests/test_access.py` checks that the
    mapping is total in both directions. Unlike `LabelColor` the order here is
    *not* load-bearing — the admin UI sorts the checkboxes by the frontend's
    own navigation order, so a new page can be appended anywhere.

    The `/dashboard` route has no member on purpose: it is a stub with no
    backend behind it. It gets one when it becomes a real page.
    """

    ABGLEICHE = "abgleiche"
    AWIN_BANNER = "awin-banner"
    WEBP_KONVERTER = "webp-konverter"
    QR_CODE = "qr-code"
    PDF_SCHUTZ = "pdf-schutz"
    NAMENSSCHILDER = "namensschilder"
    KANBAN = "kanban"
    TELEFONAKQUISE = "telefonakquise"


class CurrentUserResponse(BaseModel):
    """Answer of `GET /auth/me` — who is calling and what they may open.

    The frontend filters its own route list against `pages`; it never needs
    the full catalogue for that. `GET /auth/pages` serves the catalogue and
    exists only for the admin UI.

    `must_change_password` steers the forced password change after an initial
    or reset password (ASVS 6.4.1): while it is set, the frontend keeps every
    route pointed at the change form.
    """

    id: str
    username: str
    is_admin: bool
    must_change_password: bool
    totp_enabled: bool
    pages: list[Page]
