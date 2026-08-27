# coupling-internal-tools

Internes Back-Office-Werkzeug für Coupling Media: AWIN-Abgleiche, Banner-CSVs,
WebP-Konvertierung, QR-Codes, PDF-Passwortschutz, Namensschilder für
Veranstaltungen und ein Kanban-Board.

Vue-3-SPA (`frontend/`) über einer FastAPI-Anwendung (`backend/`).

## Starten

```bash
# lokale Entwicklung – das -f ist wichtig, ohne wählt Compose die Produktionsdatei
docker compose -f docker-compose.local.yml up --build   # App auf http://localhost

# Produktion
docker compose up --build -d
```

Die beiden Dateien haben getrennte Projektnamen (`coupling-internal-tools` und
`coupling-internal-tools-dev`), liegen also in eigenen Namespaces und fassen
die Container der anderen nicht an. Gleichzeitig laufen können sie trotzdem
nicht — beide wollen Port 80.

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

## Namensschilder: drucken und kalibrieren

Das Werkzeug (`/namensschilder`) macht aus einer Teilnehmerliste ein PDF für
perforierte Einsteckschilder-Bögen. Der Bogen wird **direkt bedruckt und nicht
geschnitten** — deshalb enthält das PDF keinen Anschnitt, keine Schnitt- oder
Passermarken und nichts außerhalb der Seite. Die Liste wird nirgends
gespeichert.

### Beim Drucken

| Einstellung | Wert |
|---|---|
| Größe | **„Tatsächliche Größe“ bzw. 100 %** — niemals „An Seite anpassen“ |
| Einzug | manueller Schacht, Bögen einzeln |
| Medientyp | Karton, 120–160 g/m² |
| Seiten | einseitig, kein Duplex |

Die stille Skalierung auf ~96 % im Druckdialog ist der häufigste Fehler und
macht das ganze Raster unbrauchbar. Das PDF setzt deshalb `PrintScaling` auf
`None`, damit Viewer von sich aus die tatsächliche Größe wählen — der
Druckdialog kann trotzdem übersteuert werden, also im Zweifel nachsehen.

### Kalibrieren (einmal pro Drucker)

Jeder Drucker legt das Blatt ein paar Zehntelmillimeter versetzt an. Die
Registerkorrektur gleicht genau diesen **systematischen** Versatz aus.

1. **Kalibrierbogen herunterladen** (Knopf unter den Einstellungen) und auf
   **Normalpapier** drucken — mit denselben Einstellungen wie oben.
2. Den Ausdruck **deckungsgleich auf einen leeren Einsteckschilder-Bogen
   legen** und beides **gegen das Licht halten**.
3. Ablesen, wie weit die gedruckten Kartenumrisse gegenüber der Perforation
   verschoben sind — in Millimetern, mit Vorzeichen.
   *Beispiel:* Die Umrisse liegen 0,8 mm zu weit links und 0,4 mm zu tief.
4. Die **Gegenwerte** eintragen: X `+0,8`, Y `−0,4`. Positiv heißt nach rechts
   bzw. nach unten.
5. Kalibrierbogen erneut drucken und prüfen. Zwei Durchgänge genügen in aller
   Regel.

Die Fadenkreuze in den Blattecken wandern dabei **nicht** mit: sie sitzen
immer 10 mm von der Blattecke entfernt und sind die Referenz auf das Blatt
selbst — an ihnen ist zu sehen, wie der Drucker das Papier anlegt,
unabhängig vom eingestellten Versatz.

### Was der Versatz nicht kann

Er korrigiert den **festen** Anteil der Abweichung. Die zufällige Streuung des
Papiereinzugs von etwa **±0,5 mm von Blatt zu Blatt** bleibt und lässt sich
nicht wegrechnen. Genau dafür gibt es die **Sicherheitszone von 4 mm** um jede
Karte: solange aller Text darin steht — und dafür verkleinert das Werkzeug
lange Namen automatisch — bleibt auch ein um einen halben Millimeter
verrutschter Bogen brauchbar.

Zum Prüfen im Ernstfall lässt sich „Kartenumrisse mitdrucken“ einschalten und
ein Bogen auf Normalpapier ausgeben.

### Ein weiteres Bogenformat aufnehmen

Format und Kartenlayout sind Konfiguration, kein Code:

| Was | Wo |
|---|---|
| Blattmaß, Raster, Kartenmaß, Ränder, Sicherheitszone | `SHEET_FORMATS` in `backend/app/core/badge_geometry.py` |
| Felder der Karte (Grundlinie, Größe, fett, Ausrichtung) | `CARD_LAYOUTS` in `backend/app/core/badge_layout.py` |

Die Werte werden am tatsächlichen Bogen **ausgemessen**, nicht ausgerechnet.
Beim Start prüft `SheetFormat.validate()`, ob Ränder, Karten und Spalt exakt
auf das Blattmaß aufgehen, und bricht mit der Differenz in Millimetern ab,
wenn nicht — eine unstimmige Konfiguration lässt die Anwendung also gar nicht
erst starten. Sichtbar wird das neue Format ohne jede Frontend-Änderung: das
Kartenraster im UI zeichnet sich aus `GET /api/name-badges/formats`.

Die Schriften liegen als eingebettete Subsets bei
(`backend/app/assets/fonts/`, siehe die README dort). System- oder
Base-14-Schriften kommen bewusst nicht in Frage: der Druckertreiber zöge dafür
eine eigene Metrik, und der Text liefe aus der Sicherheitszone.

## Tests

Beide Test-Suiten laufen ohne Datenbank, ohne Netzwerk und ohne Secrets — der
CI-Runner braucht also nichts weiter als das Repo.

```bash
# Backend (Python 3.11 wie im Produktionsimage)
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest
ruff check .
black --check .

# Frontend (Node 20 wie im Buildimage)
cd frontend
npm ci
npm test              # vitest run
npm run type-check    # vue-tsc -b --noEmit
npm run lint          # eslint .
npm run format:check  # prettier --check .
npm run build         # vue-tsc -b && vite build
```

Alle sechs Kommandos sind grün — sie taugen also unmittelbar als CI-Gate.
`npm run lint:fix` und `npm run format` beheben Verstöße, im Backend
`ruff check --fix .` und `black .`.

Der Frontend-Test `src/api/labelPalette.test.ts` liest `backend/app/schemas/kanban.py`
und hält die Label-Farbpalette über die Sprachgrenze synchron. Er braucht deshalb
das **vollständige** Repo, nicht nur `frontend/`.

## Deployment

Der Deploy läuft über `scripts/deploy.sh`, das per SSH aufgerufen wird:
`git pull --ff-only` → `docker compose up -d --build` → auf den
Backend-Healthcheck warten → alte Images aufräumen. Schlägt der Healthcheck
fehl, gibt das Skript die letzten 50 Logzeilen aus und bricht mit einem
Exit-Code ≠ 0 ab.

```bash
ssh <user>@<host> '/opt/coupling-internal-tools/scripts/deploy.sh'
```

### Einmaliges Server-Setup

Diese Schritte sind **vor dem ersten Deploy** nötig. Alles davon liegt
absichtlich nicht im Repo (Secrets bzw. Laufzeitdaten).

```bash
# 1. Repo klonen. Der Pfad ist frei wählbar; deploy.sh leitet ihn aus seinem
#    eigenen Ort ab und muss nicht angepasst werden.
sudo mkdir -p /opt/coupling-internal-tools
sudo chown "$USER" /opt/coupling-internal-tools
git clone <repo-url> /opt/coupling-internal-tools
cd /opt/coupling-internal-tools

# 2. .env anlegen und ausfüllen. MUSS existieren, bevor der backend-Container
#    startet – ohne ADMIN_USERNAME/ADMIN_PASSWORD verweigert die Anwendung
#    beim allerersten Start den Dienst, weil es sonst kein Konto gäbe, mit dem
#    sich jemand anmelden könnte. deploy.sh prüft beides vorab.
cp env.example .env && chmod 600 .env
$EDITOR .env
#    Eine Basic-Auth-Datei wird nicht mehr gebraucht: authentifiziert wird in
#    der Anwendung. Ein vorhandenes auth/.htpasswd kann gelöscht werden.

# 3. Initiales Zertifikat holen. Das muss von Hand passieren: der certbot-Service
#    in docker-compose.yml macht nur `renew`, und `renew` braucht eine bereits
#    vorhandene Konfiguration unter certbot/conf/renewal/.
#    nginx muss dafür auf Port 80 laufen und /.well-known/acme-challenge/ aus
#    /var/www/certbot ausliefern – genau das tut frontend/nginx.conf.
docker compose up -d frontend
docker compose run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  -d coupling-internal-tools.de -d www.coupling-internal-tools.de \
  --email <adresse> --agree-tos --no-eff-email

# 4. Erster vollständiger Start
docker compose up -d --build
```

### Erster Login

Nach dem ersten Start meldet man sich mit `ADMIN_USERNAME`/`ADMIN_PASSWORD`
aus der `.env` an. Danach:

1. **Zweiten Faktor einrichten** (Profilmenü → Mein Konto). Für ASVS Level 2
   ist er Pflicht, und er ist der wirksamste Einzelschutz — ein Login im
   offenen Netz steht und fällt sonst mit der Passwortqualität.
2. **Weitere Konten anlegen** (Profilmenü → Benutzer verwalten). Das
   Startpasswort erzeugt der Server und zeigt es genau einmal an; die Person
   muss es bei der ersten Anmeldung wechseln.
3. Pro Konto ankreuzen, welche Seiten es öffnen darf. Administratoren sehen
   immer alles.

`ADMIN_PASSWORD` wirkt **nur beim Anlegen**. Ein späterer Neustart
überschreibt ein in der Oberfläche geändertes Passwort nicht.

**Administratorpasswort vergessen?** Es gibt keinen Reset per Mail (das System
versendet keine). Der Notausgang läuft über die Shell:

```bash
docker compose exec backend python -m app.admin_cli reset <benutzername>
```

Das gibt ein neues Startpasswort aus, erzwingt den Wechsel bei der nächsten
Anmeldung und beendet alle laufenden Sitzungen des Kontos.

Wie die Authentifizierung im Einzelnen funktioniert — Passwortrichtlinie,
Sperren, Sitzungsdauern und deren Begründung — steht in
[docs/authentifizierung.md](docs/authentifizierung.md).

### Healthchecks

Beide Services haben einen Healthcheck, und `scripts/deploy.sh` wartet auf
beide (je bis zu 60 s):

| Service | Prüfung | Warum so |
|---|---|---|
| `backend` | Python-Einzeiler gegen `http://127.0.0.1:8000/health` | `python:3.11-slim` hat weder curl noch wget noch nc — Python ist das einzige Werkzeug im Image. `/health` fasst die Datenbank nicht an, damit ein gesperrtes SQLite nicht den Container neu startet |
| `frontend` | `wget --spider http://127.0.0.1/healthz` | `/healthz` liegt im HTTP-Block von `nginx.conf`, also ohne Zertifikat und ohne Anmeldung erreichbar |

Der frontend-Check ist nicht optional: `docker compose up -d` kehrt auch
erfolgreich zurück, wenn nginx sofort stirbt (fehlendes Zertifikat, kaputte
Config). Ohne ihn wäre so ein Deploy grün und die Seite tot.

### Zertifikatserneuerung

Läuft automatisch, sobald der Stack steht — kein Cronjob nötig:

- Der `certbot`-Service versucht alle 12 h ein `certbot renew`. Das ist ein
  No-Op, solange mehr als 30 Tage Restlaufzeit sind.
- Der `frontend`-Container lädt nginx alle 6 h neu (`nginx -s reload`,
  unterbrechungsfrei). Ohne diesen Reload würde nginx nach einer Erneuerung
  bis zum nächsten Neustart mit dem alten Zertifikat weiterlaufen, weil es die
  Zertifikatsdatei beim Start einmal öffnet und dann hält.

Prüfen:

```bash
docker compose run --rm certbot certificates      # Restlaufzeit
docker compose logs certbot --tail=20             # letzte Renewal-Versuche
```

### Rollback

Auf einen bekannten Stand zurück und neu bauen:

```bash
cd /opt/coupling-internal-tools
git log --oneline -10                # Commit aussuchen
git checkout <sha>
docker compose up -d --build --remove-orphans
```

Danach steht das Repo auf einem detached HEAD. Für den nächsten Deploy per
Action wieder auf den Branch:

```bash
git checkout main
```

Ein Rollback des **Codes** rollt die Kanban-Datenbank nicht zurück. Beim
aktuellen Schema (`schema_version = 1`) ist das unkritisch, weil es nur additive
Migrationen gibt; bei einem künftigen zerstörenden Schemawechsel vorher das
Backup ziehen (siehe unten).

### Daten und Backup

| Pfad auf dem Server | Inhalt | Ersetzbar? |
|---|---|---|
| `data/kanban/` | SQLite des Kanban-Boards **und der Benutzerkonten** (`kanban.db`, `auth.db`, je + `-wal`/`-shm`) | **nein** — hier hängt der ganze Zustand der App, inklusive aller Konten |
| `certbot/conf/` | Let's-Encrypt-Zertifikate und Renewal-Konfiguration | ja, neu ausstellbar (Rate-Limits beachten) |
| `.env` | Zugangsdaten des ersten Administrators und Betriebsparameter | ja, aber siehe „Erster Login" |
| `certbot/www/` | ACME-Challenge-Webroot, nur transient | ja |

Backup — ein Verzeichnis-Archiv genügt, der Stack darf dabei laufen:

```bash
tar czf "kanban-$(date +%F).tar.gz" -C /opt/coupling-internal-tools data certbot/conf
```

Zusätzlich holt der Export-Knopf im Board (`GET /api/kanban/export`) jederzeit
ein JSON des kompletten Boards — unabhängig vom Server.

Wiederherstellen: Stack stoppen (`docker compose down`), Archiv über das
Projektverzeichnis entpacken, `docker compose up -d`.
