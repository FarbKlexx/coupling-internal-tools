"""Notausgang für ein vergessenes Administratorpasswort.

    docker compose exec backend python -m app.admin_cli reset <benutzername>

Setzt ein neues zufälliges Startpasswort, erzwingt den Wechsel bei der
nächsten Anmeldung und beendet alle laufenden Sitzungen des Kontos. Ohne
diesen Weg wäre die einzige Rettung, die Datenbank zu löschen.

Bewusst kein Endpunkt: wer das hier ausführen kann, hat ohnehin Zugriff auf
den Server.
"""

import sys

from app.core.auth_db import init_schema
from app.services.auth_service import AuthError, reset_password_from_cli


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "reset":
        print(__doc__)
        return 2

    init_schema()

    try:
        password = reset_password_from_cli(argv[2])
    except AuthError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    print(f"Neues Startpasswort für „{argv[2]}“:\n\n    {password}\n")
    print("Es muss bei der nächsten Anmeldung geändert werden.")
    print("Alle bisherigen Sitzungen dieses Kontos wurden beendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
