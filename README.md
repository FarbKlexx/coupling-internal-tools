# coupling-internal-tools

Internes Back-Office-Werkzeug für Coupling Media: AWIN-Abgleiche, Banner-CSVs,
WebP-Konvertierung, QR-Codes, PDF-Passwortschutz und ein Kanban-Board.

Vue-3-SPA (`frontend/`) über einer FastAPI-Anwendung (`backend/`).

## Starten

```bash
# lokale Entwicklung – das -f ist wichtig, ohne wählt Compose die Produktionsdatei
docker compose -f docker-compose.local.yml up --build   # App auf http://localhost

# Produktion
docker compose up --build -d
```

## Betrieb: das Kanban-Board ist der einzige persistente Zustand

Alle Werkzeuge außer dem Kanban-Board sind zustandslos – sie wandeln eine
Eingabe um und geben eine Datei zurück. Das Board dagegen liegt in einer
SQLite-Datei:

| | |
|---|---|
| Im Container | `/app/data/kanban.db` |
| Auf dem Host (Produktion) | `./data/kanban/` – gemountet in `docker-compose.yml` |
| Konfigurierbar über | `KANBAN_DB_PATH` (Default: relativ `data/kanban.db`) |

**Zwei Dinge daran sind wichtig:**

1. **Das Mount in `docker-compose.yml` nicht entfernen.** Ohne
   `./data/kanban:/app/data` liegt die Datenbank im Container und ist beim
   nächsten `docker compose up --build` verloren.
2. **`./data/kanban/` ins Backup aufnehmen.** Ein Verzeichnis-Archiv genügt.
   Zusätzlich kann sich jeder über den Export-Knopf im Board (bzw.
   `GET /api/kanban/export`) jederzeit ein JSON des kompletten Boards ziehen.

Das Board schreibt außerdem `kanban.db-wal` und `kanban.db-shm` daneben (WAL-Modus);
die gehören zur Datenbank und werden beim Backup mitgenommen.
