#!/usr/bin/env bash
#
# Deploy auf dem Server. Wird per SSH aus der GitHub-Action aufgerufen:
#
#     ssh user@host '/opt/coupling-internal-tools/scripts/deploy.sh'
#
# Bricht bei jedem Fehler mit einem Exit-Code != 0 ab, damit der Workflow rot
# wird. Ein halb durchgelaufener Deploy ist immer noch besser als eine gruene
# Action, die nichts deployt hat.
set -euo pipefail

# Warum unten alles in main() steckt und `main "$@"` die letzte Zeile ist:
# Bash liest ein laufendes Skript haeppchenweise nach. Der `git pull` weiter
# unten ersetzt genau diese Datei - danach laese Bash an seinem alten
# Byte-Offset in der neuen Fassung weiter und landete mitten in einer Zeile
# ("command not found", Abbruch an unvorhersehbarer Stelle). Als Funktion ist
# der Rumpf beim Aufruf vollstaendig eingelesen, und nach dem letzten Kommando
# wird nicht mehr nachgelesen.

# Verzeichnis des Repos - aus dem Skriptpfad abgeleitet, damit das Skript nicht
# wissen muss, wo es installiert ist.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Wie lange auf einen gesunden Backend-Container gewartet wird.
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-60}"

# Dateien, die es nur auf dem Server gibt (Secrets, Zertifikate). Fehlen sie,
# startet nginx nicht - und Docker legt an der Stelle des fehlenden
# Datei-Mounts ein Verzeichnis an, was die Fehlersuche unnoetig verwirrend
# macht. Deshalb vorher pruefen.
# .htpasswd steht hier nicht mehr: die Basic Auth ist mit den Benutzerkonten
# entfallen.
REQUIRED_FILES=(
  ".env"
)

# Variablen, die in .env gesetzt sein muessen. Ohne sie verweigert das Backend
# beim allerersten Start den Dienst - es haette sonst kein Konto, mit dem sich
# jemand anmelden koennte. Das soll hier auffallen und nicht drei Minuten
# spaeter als unhealthy-Container.
REQUIRED_VARS=(
  "ADMIN_USERNAME"
  "ADMIN_PASSWORD"
)

# Service-Name, nicht container_name: die Container heissen
# <projekt>-backend-1 und das soll hier keine Rolle spielen.
service_health() {
  local service="$1" id
  id="$(docker compose ps -q "$service")"
  [[ -n "$id" ]] || { echo "missing"; return; }
  # Ohne definierten Healthcheck liefert das Template "none".
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id" 2>/dev/null || echo "missing"
}

# Wartet auf einen Service. Gibt den letzten gesehenen Status zurueck.
wait_for_health() {
  local service="$1" deadline status
  deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
  status=""

  while ((SECONDS < deadline)); do
    status="$(service_health "$service")"

    case "$status" in
      healthy)
        break
        ;;
      none)
        # Kein Healthcheck definiert - das ist ein Konfigurationsfehler und
        # kein Zustand, auf den sich Warten lohnt.
        break
        ;;
      *)
        # starting, unhealthy oder missing: weiter warten. Solange retries
        # offen sind, kann sich das noch drehen; der Timeout ist die Grenze.
        printf '.' >&2
        sleep 3
        ;;
    esac
  done

  echo "$status"
}

log() {
  printf '\n=== %s\n' "$*"
}

fail() {
  printf '\nFEHLER: %s\n' "$*" >&2
  exit 1
}

main() {
  # --------------------------------------------------------------------------
  # 1. Ins Projektverzeichnis
  # --------------------------------------------------------------------------
  cd "$PROJECT_DIR"
  log "Deploy in $PROJECT_DIR"

  for file in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "$file" ]]; then
      fail "$file fehlt. Einmaliges Server-Setup nachholen, siehe README (Abschnitt Deployment)."
    fi
  done

  for var in "${REQUIRED_VARS[@]}"; do
    # Nur auf einen nicht-leeren Wert pruefen. Der Wert selbst wird nirgends
    # ausgegeben und darf auch in keinem Log landen.
    if ! grep -qE "^${var}=.+" .env; then
      fail "$var fehlt in .env oder ist leer. Vorlage: env.example."
    fi
  done

  # --------------------------------------------------------------------------
  # 2. Stand holen
  # --------------------------------------------------------------------------
  log "git pull"
  # --ff-only: lieber abbrechen als auf dem Server einen Merge-Commit erzeugen.
  # Wer hier scheitert, hat lokale Aenderungen auf dem Server - die will man
  # sehen und nicht wegmergen.
  git pull --ff-only

  echo "Jetzt auf: $(git rev-parse --short HEAD) - $(git log -1 --pretty=%s)"

  # --------------------------------------------------------------------------
  # 3. Bauen und starten
  # --------------------------------------------------------------------------
  log "docker compose up -d --build"
  # --remove-orphans raeumt Container von Services auf, die es in der
  # compose-Datei nicht mehr gibt.
  docker compose up -d --build --remove-orphans

  # --------------------------------------------------------------------------
  # 4. Auf die Healthchecks warten
  # --------------------------------------------------------------------------
  # Beide Services, nicht nur das Backend: `docker compose up -d` kehrt auch
  # erfolgreich zurueck, wenn nginx sofort stirbt (fehlendes Zertifikat, kaputte
  # Config). Ohne den frontend-Check waere so ein Deploy gruen und die Seite tot.
  SERVICES=(backend frontend)

  for service in "${SERVICES[@]}"; do
    log "Warte auf den Healthcheck von '$service' (max ${HEALTH_TIMEOUT_SECONDS}s)"
    status="$(wait_for_health "$service")"

    case "$status" in
      healthy)
        echo "'$service' ist healthy."
        ;;
      none)
        fail "Service '$service' hat keinen Healthcheck. docker-compose.yml pruefen."
        ;;
      *)
        # ------------------------------------------------------------------
        # 5. Bei Fehlschlag: Logs zeigen und rot abbrechen
        # ------------------------------------------------------------------
        log "'$service' wurde nicht healthy (Status: ${status:-unbekannt}) - letzte 50 Logzeilen"
        docker compose logs --tail=50 || true
        docker compose ps || true
        fail "Deploy abgebrochen. Der vorherige Stand laeuft NICHT mehr - Rollback siehe README."
        ;;
    esac
  done

  # --------------------------------------------------------------------------
  # 6. Aufraeumen
  # --------------------------------------------------------------------------
  log "Alte Images aufraeumen"
  # Nur unreferenzierte Images. Volumes und die Bind-Mounts bleiben unberuehrt -
  # hier wird nichts geloescht, was Daten enthaelt.
  docker image prune -f

  log "Deploy erfolgreich"
  docker compose ps
}

# `exit` steht in derselben Zeile: Bash liest nach der Rueckkehr aus main
# sonst noch einmal nach - und zwar an altem Offset in der inzwischen
# getauschten Datei. Gemeinsam geparst, endet das Skript ohne weiteren
# Lesezugriff.
main "$@"; exit
