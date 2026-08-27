# Authentifizierung nach ASVS — Umsetzungsplan

Umsetzungsplan für Option A (App-Login statt nginx Basic Auth), abgeglichen gegen
**OWASP ASVS 5.0, Kapitel V6 (Authentication) und V7 (Session Management)**.
Zielstufe: **Level 2**. Aufwand: **4–5 Tage**.

Die Anforderungstexte sind gegen die aktuellen Quellen geprüft, nicht aus dem
Gedächtnis zitiert — Quellenliste am Ende.

---

## Vier Korrekturen am bisherigen Plan

Das ist der Teil, der sich gegenüber dem zuvor besprochenen Plan wirklich ändert.
Alles Weitere ist Ergänzung.

### 1. Passwort-Hashing

> ~~bcrypt, Work Factor 12~~ → **argon2-cffi, Argon2id, `m=19456, t=2, p=1`**

OWASP führt Argon2id an erster Stelle, bcrypt nur noch als Legacy-Option für
Altsysteme. Nebeneffekt: der 72-Byte-Deckel von bcrypt entfällt, den man sonst
gegen Anforderung 6.2.9 (mindestens 64 Zeichen erlaubt) explizit abfangen müsste.

### 2. Session-Laufzeit

> ~~30 Tage gleitend~~ → **Inaktivitätsgrenze + absolutes Maximum, beide dokumentiert**

7.3.1 und 7.3.2 verlangen *beide* Grenzen, und 7.1.1 verlangt eine schriftliche
Begründung, wenn man von den Richtwerten abweicht. Ein gleitendes 30-Tage-Fenster
ohne absolute Obergrenze erfüllt keine der beiden. Die konkreten Zahlen sind eine
Entscheidung — siehe „Offene Entscheidungen".

### 3. Vom Admin gesetzte Passwörter

> ~~Dauerpasswort~~ → **Einmal-Credential mit Zwang zur Änderung**

6.4.1: systemseitig erzeugte Startpasswörter müssen zufällig sein, der
Passwortrichtlinie folgen und nach kurzer Zeit oder erster Nutzung verfallen — sie
dürfen nicht zum Dauerpasswort werden. Genau das war im bisherigen Plan der Ablauf:
Admin tippt ein Passwort ein und gibt es weiter.

### 4. Zweiter Faktor

> ~~optional, „nice to have"~~ → **für Level 2 verpflichtend**

6.3.3 verlangt auf Level 2 Mehrfaktor-Authentifizierung. Wenn der Standard das Ziel
ist, ist TOTP kein Extra, sondern Teil der Lieferung. Ohne 2FA landet das Ergebnis
bei Level 1.

---

## Phase 0 — Das Dokument schreiben, bevor Code entsteht

**0,5 Tage.** Fünf Anforderungen sind reine Dokumentationspflichten. Sie stehen
bewusst am Anfang: sie erzwingen Entscheidungen, die sonst beim Coden nebenbei
getroffen und nie wieder hinterfragt werden. Ziel ist `docs/authentifizierung.md`.

| ASVS | Inhalt |
|---|---|
| 6.1.1 | **Abwehr von Credential Stuffing und Brute Force** — ausdrücklich inklusive der Frage, wie *böswilliges Aussperren* verhindert wird. Eine reine Sperre pro Benutzername ist auch eine Waffe: zehnmal falsch raten sperrt eine Kollegin aus. Festhalten: Sperre pro Kombination aus IP und Benutzername, plus `limit_req_zone` in nginx auf den Login-Pfad. |
| 6.1.2, 6.2.11 | **Sperrliste kontextspezifischer Wörter** — Organisations-, Produkt- und Systemnamen dürfen nicht in Passwörtern vorkommen. Konkret: `coupling`, `media`, `awin`, `kanban`, `jeansfritz`, die Toolnamen, die Domain. Als Datei im Repo, nicht als Kommentar. |
| 6.1.3, 6.3.4 | **Alle Authentifizierungswege** — es darf keinen undokumentierten Weg hinein geben. Hier wird schriftlich, dass der `X-Remote-User`-Fallback ersatzlos verschwindet, damit es genau *einen* Weg gibt. |
| 7.1.1, 7.1.2 | **Session-Lebensdauer und parallele Sitzungen** — Inaktivitäts- und Absolutgrenze mit Begründung, plus wie viele parallele Sitzungen ein Konto haben darf und was beim Überschreiten passiert. Der Standard schreibt keine Zahl vor; er schreibt vor, dass eine gewählt und begründet wurde. |

---

## Phase 1 — Speicher und Hashing

**1 Tag.**

### `core/auth_db.py` — zweite SQLite-Datei im selben Mount  · 7.2.1

`AUTH_DB_PATH`, Default `data/auth.db`, **relativ** — exakt wie `KANBAN_DB_PATH` und
aus demselben Grund. Das bestehende `./data/kanban:/app/data`-Mount deckt sie mit ab,
an `docker-compose.yml` ändert sich beim Volume nichts.

`PRAGMA foreign_keys = ON` ist hier nicht Deko: ohne den Cascade überlebt die Session
eines gelöschten Users. `username_key` mit `casefold()` statt `COLLATE NOCASE` —
dieselbe Umlaut-Falle wie bei den Kanban-Labels.

```
users(id, username, username_key UNIQUE, password_hash,
      is_admin, active, must_change_password,
      totp_secret_hash, totp_last_step,
      created_at, password_changed_at)
user_pages(user_id → users ON DELETE CASCADE, page)
sessions(token_hash, user_id → users ON DELETE CASCADE,
         created_at, expires_at, last_seen_at, user_agent, ip)
recovery_codes(user_id → users ON DELETE CASCADE, code_hash, used_at)
login_attempts(ip_key, username_key, failed_count, locked_until)
```

### `core/security.py` — Argon2id  · OWASP Password Storage

`argon2-cffi` in die `requirements.txt` — **die Datei ist UTF-16/LE**, mit einem
UTF-8-Editor bearbeitet ist sie kaputt. Parameter explizit setzen statt Defaults
erben, damit sie im Review sichtbar sind: `m=19456, t=2, p=1`.

`check_needs_rehash()` beim Login mitlaufen lassen: dann lassen sich die Parameter
später anheben und Passwörter wandern beim nächsten Login automatisch mit.

### Passwortregeln — und was ausdrücklich *nicht* hineingehört  · 6.2.1, 6.2.5, 6.2.8, 6.2.9

- Mindestens **15 Zeichen** (8 ist das Minimum, 15 die ausdrückliche Empfehlung),
  mindestens 64 erlaubt.
- **Keine** Regeln zu Groß-/Kleinschreibung, Ziffern oder Sonderzeichen — 6.2.5
  verbietet sie, weil sie Passwörter nachweislich schlechter machen.
- 6.2.8: das Passwort wird exakt so geprüft, wie es ankommt. Kein `.strip()`, kein
  Kürzen, keine Normalisierung.
- Nach oben trotzdem ein Deckel (etwa 256 Zeichen), sonst ist ein 10-MB-Passwort
  ein billiger DoS gegen Argon2.

### Abgleich gegen geleakte und triviale Passwörter  · 6.2.4, 6.2.12

Mindestens die Top 3000 passender Passwörter, dazu ein Satz bekannt geleakter.
Empfehlung: statische Liste ins Repo statt Pwned-Passwords-API — keine
Netzwerkabhängigkeit im Login-Pfad, keine Daten an Dritte, und bei sieben Nutzern
ist die Trefferquote identisch.

### Admin-Bootstrap ohne Standardkonto  · 6.3.2, 6.4.1

6.3.2 verbietet vorhandene Standardkonten. `ADMIN_USERNAME` hat deshalb *keinen*
Default; die Namen `admin`, `root`, `administrator` werden abgelehnt.

Kein User vorhanden und `ADMIN_PASSWORD` nicht gesetzt → **Start verweigern**. Ein
Container, der ohne Zugangsdaten hochkommt, ist eine App, in die niemand mehr
hineinkommt.

> **Folge für die Tests:** `tests/conftest.py` braucht eine Fixture, die
> `AUTH_DB_PATH` *und* `ADMIN_PASSWORD` setzt — sonst brechen `test_health`,
> `test_access` und `test_name_badge_service` gleichzeitig, weil `TestClient(app)`
> den Lifespan mitfährt.

Dazu ein Notausgang für vergessene Admin-Passwörter:
`python -m app.admin_cli reset-password`, aufgerufen per `docker compose exec backend`.

---

## Phase 2 — Login, Session, Sperre

**1 Tag.**

### Session-Token  · 7.2.2, 7.2.3, 7.2.4

Referenztoken aus einem CSPRNG mit mindestens 128 Bit Entropie:
`secrets.token_urlsafe(32)` liefert 256 Bit, also mit Reserve. Gespeichert wird nur
der SHA-256 davon — eine geklaute Datenbank ergibt keine gültigen Sitzungen.

7.2.4: bei jeder Anmeldung ein neuer Token, der bisherige wird beendet.

### Cookie-Attribute  · OWASP Session Management

`HttpOnly`, `Secure`, `Path=/`, kein `Domain` — damit ist das `__Host-`-Präfix
möglich, das der Cheat Sheet empfiehlt. `SameSite=Strict` ist die bevorzugte Wahl
(siehe „Offene Entscheidungen").

Haken beim Präfix: es erzwingt `Secure`, lokal läuft ihr über http. Der Cookie-Name
kommt deshalb aus der Env — in Produktion `__Host-session`, lokal `session`.

### Sperre, Timing und einheitliche Fehlermeldungen  · 6.3.1

- Sperre pro (IP, Benutzername) nach dem in Phase 0 dokumentierten Verfahren.
- Existiert der Benutzer nicht, wird **trotzdem** gegen einen festen Dummy-Hash
  verifiziert — sonst ist die Antwortzeit ein Benutzerverzeichnis.
- „Falsches Passwort" und „Benutzer existiert nicht" ergeben dieselbe Antwort,
  denselben Statuscode und ungefähr dieselbe Laufzeit.

### Passwortwechsel  · 6.2.2, 6.2.3, 7.4.3, 7.5.1

Verlangt das aktuelle *und* das neue Passwort (6.2.3) — das ist gleichzeitig die von
7.5.1 geforderte Re-Authentifizierung vor Änderung eines Authentifizierungsmerkmals.
Danach werden alle *anderen* Sitzungen beendet (7.4.3). **Das fehlte im bisherigen
Plan.**

### Beenden heißt beenden  · 7.4.1, 7.4.2

Logout löscht die Zeile, nicht nur das Cookie. Und: wird ein Konto **deaktiviert**
oder gelöscht, fliegen alle seine Sitzungen sofort mit. Der Cascade deckt nur das
Löschen ab — das Deaktivieren braucht eigenen Code.

### Was nicht gebaut wird  · 6.4.2

Keine Passworthinweise, keine Sicherheitsfragen. Steht hier, damit es niemand später
„als Komfortfunktion" nachrüstet.

---

## Phase 3 — Der Tausch in `current_user`

**0,5 Tage.** Der kurze Teil, und der Grund für die Vorarbeit: kein Router und kein
Handler wird angefasst.

### Cookie → Session → `CurrentUser`  · 7.2.1, 7.3.1, 7.3.2

`deps.py` schlägt die Session nach, prüft Inaktivitäts- und Absolutgrenze und baut
den `CurrentUser`. `is_admin` kommt jetzt dazu — in der Vorarbeit bewusst
weggelassen, weil jeder Wert dafür ohne Usersystem gelogen gewesen wäre.

- **Fail closed:** kein Codepfad darf bei einem Fehler (gesperrte Datenbank, kaputter
  Token) einen Benutzer zurückgeben. Im Zweifel 500, nie durchwinken.
- `last_seen_at` nur schreiben, wenn der Wert älter als ein paar Minuten ist. Sonst
  wird jeder Request ein Schreibvorgang, und der 10-Sekunden-Poll des Kanban-Boards
  hält die Datenbank dauerhaft im Schreiblock.

### `require_admin` — und die Anpassung am bestehenden Test  · 6.3.4

Die Benutzerverwaltung hängt am Admin-Flag, nicht an einer Seite. `test_access.py`
kennt aber nur „Page-Guard oder `PUBLIC_PATHS`" — die Admin-Endpunkte müsste man
sonst in die Allowlist schreiben und würde den Test damit stumpf machen.

Fix: `require_admin` bekommt analog zu `guards_page` ein Attribut `requires_admin`,
und der Walker akzeptiert einen der beiden Guards. Zehn Zeilen, aber ohne sie geht
genau die Sicherung verloren, die gerade gebaut wurde.

### `/docs`, `/redoc`, `/openapi.json` schließen  · 6.3.4

Die drei stehen heute in `PUBLIC_PATHS` und liegen nur deshalb nicht offen, weil die
Basic Auth davor steht. In Produktion per Env abschalten (`docs_url=None`) **und** aus
`PUBLIC_PATHS` entfernen, damit der Test ihre Abwesenheit erzwingt.

---

## Phase 4 — Zweiter Faktor

**0,5–1 Tag.** Für Level 2 verpflichtend (6.3.3). Und unabhängig vom Standard der
wirksamste einzelne Baustein hier, weil er das realistische Risiko abfängt: ein
schwaches Passwort auf einem Login im offenen Netz.

### TOTP mit `pyotp`  · 6.3.3, 6.5.3, 6.5.5

Seed aus einem CSPRNG (`pyotp.random_base32()` nutzt `secrets`), Schrittweite 30
Sekunden, Drift-Fenster ±1 Schritt. Den Enrollment-QR-Code rendert `core/qr_utils.py`
— der Code ist schon da.

### Jeder Code genau einmal  · 6.5.1

Der zuletzt akzeptierte Zeitschritt wird pro Benutzer gespeichert
(`totp_last_step`). Ohne das ist ein abgefangener Code innerhalb seines
30-Sekunden-Fensters beliebig oft einlösbar.

### Wiederherstellungscodes  · 6.5.2, 6.5.4, 6.4.4

Zehn Stück aus einem CSPRNG, deutlich über den geforderten 20 Bit. Gespeichert mit
demselben Argon2id wie Passwörter — 6.5.2 verlangt das für alles unter 112 Bit
Entropie. Jeder Code genau einmal nutzbar.

6.4.4 verlangt bei Verlust des zweiten Faktors eine Identitätsprüfung auf demselben
Niveau wie bei der Einrichtung. Für ein internes Werkzeug heißt das: der Admin setzt
es persönlich zurück. Gehört so in das Dokument aus Phase 0.

---

## Phase 5 — Frontend

**1–1,5 Tage.**

### Das Login-Formular — vor allem, was man weglässt  · 6.2.6, 6.2.7

`type="password"`, optional ein Auge zum Einblenden. Einfügen erlauben,
Passwortmanager erlauben: **kein** `autocomplete="off"`, **kein** `onpaste`-Blocker.
Stattdessen `autocomplete="current-password"` bzw. `"new-password"`, damit Manager
sauber greifen.

### Sichtbares Abmelden auf jeder Seite  · 7.4.4

Der Avatar-Platzhalter in `ProfileArea.vue` hinter `SHOW_PLACEHOLDER_ACTIONS` wird
zum echten Menü: Name, „Benutzer verwalten" (nur Admin), „Passwort ändern", „Aktive
Sitzungen", „Abmelden". Das ist der ursprünglich gesuchte Punkt in der Oberfläche.

### Erzwungener Passwortwechsel beim ersten Login  · 6.4.1

Ist `must_change_password` gesetzt, führt jede Route außer der Wechselseite dorthin
zurück. Das Startpasswort erzeugt die Admin-Oberfläche selbst per CSPRNG und zeigt es
genau einmal an — der Admin tippt keins.

### Navigation filtern, Guard, 401-Interceptor

`buildNavItems` und `buildRouteSearchIndex` bekommen denselben Filter-Helper —
*einen*, damit Sidebar und Suche nicht auseinanderlaufen können. Der Router-Guard
prüft `meta.page` gegen die Rechte des Benutzers.

Der 401-Interceptor in `http.ts` ist wegen des 10-Sekunden-Polls im Kanban-Board
nicht optional — ohne ihn wird aus einer abgelaufenen Session ein 401-Sturm. Auf
`/auth/login` selbst muss er sich zurückhalten, sonst Redirect-Schleife.

> Die Benutzerverwaltung bekommt `meta.adminOnly` und **kein** `meta.page` — damit
> braucht die Regel in `pageIds.test.ts` eine Ausnahme. Zweite und letzte Stelle, an
> der die Vorarbeit nachjustiert wird.

---

## Phase 6 — Sitzungen sichtbar machen

**0,5 Tage.** Zwei Level-2-Anforderungen, die leicht übersehen werden, weil sie nach
Komfort aussehen und keiner sind.

| ASVS | Inhalt |
|---|---|
| 7.5.2 | **Eigene Sitzungen sehen und beenden** — Liste im Profilmenü: Gerät, IP, zuletzt gesehen, die aktuelle markiert. Einzeln beendbar, plus „alle anderen abmelden". |
| 7.4.5 | **Admin kann Sitzungen beenden** — für einen einzelnen Benutzer und für alle. Der Notaus, wenn ein Laptop wegkommt; ohne ihn bleibt nur, das Konto zu löschen. |

---

## Phase 7 — Umschalten

**0,5 Tage.** Zwischen „Basic Auth entfernt" und „Login funktioniert" darf keine
Sekunde liegen. Deshalb: alles ausrollen, *während die Basic Auth noch steht*. Zwei
Abfragen hintereinander sind unschön und für ein paar Stunden richtig.

### Erst verifizieren, dann abschalten

Live einloggen, Testbenutzer anlegen, dessen Einschränkung tatsächlich gegen eine
gesperrte Seite prüfen, 2FA einrichten. Danach erst der letzte Commit:

- `frontend/nginx.conf`: `auth_basic`, `auth_basic_user_file` und
  `proxy_set_header X-Remote-User` raus
- `docker-compose.yml`: `.htpasswd`-Mount raus, `env_file` rein
- `scripts/deploy.sh`: der `.htpasswd`-Preflight wird ein Preflight auf die
  Pflichtvariablen
- README: erster Login, Passwort-Reset per `docker compose exec`

### Der 256-MB-Puffer

nginx puffert den Request-Body bis `client_max_body_size`, *bevor* er ans Backend
geht — das 401 kommt erst danach. Ein Unangemeldeter kann den Server also mit 256 MB
pro Request beschäftigen. Heute lehnt die Basic Auth das ab, bevor ein Byte fließt.

- Sauberer Weg zurück: nginx' `auth_request` gegen eine winzige Backend-Route, dann
  fliegen Unangemeldete wieder auf nginx-Ebene raus.
- Billiger Weg: kleiner Default für `client_max_body_size` und die 256m nur auf
  `location /api/convert-images`.

### Abnahme

`/security-review` über den vollständigen Diff, dazu jeden Endpunkt einmal ohne
Cookie und einmal mit *abgelaufener* statt fehlender Session durchprobieren — die
beiden Fälle laufen erfahrungsgemäß durch unterschiedliche Codepfade.

---

## Offene Entscheidungen

Drei Punkte, die der Standard bewusst überlässt — er verlangt nur, dass sie getroffen
und begründet wurden.

### Inaktivitäts- und Absolutgrenze

Der Session-Cheat-Sheet nennt als Richtwerte 15–30 Minuten Inaktivität für
Anwendungen mit geringem Risiko und 4–8 Stunden absolut für etwas, das jemand einen
Arbeitstag lang benutzt. Streng gelesen: einmal mittags neu anmelden. Für ein
internes Back-Office zu straff — 7.1.1 erlaubt die Abweichung ausdrücklich, mit
schriftlicher Begründung.

> **Vorschlag:** 8 h Inaktivität, 24 h absolut, begründet im Dokument aus Phase 0.

### SameSite: Strict oder Lax

`Strict` ist die bevorzugte Wahl, hat aber eine spürbare Folge: wer einen Link auf das
Tool aus einer Mail oder aus Slack anklickt, bekommt beim ersten Aufruf die
Loginseite, obwohl er angemeldet ist — das Cookie wird bei der ersten Navigation
nicht mitgeschickt.

> **Vorschlag:** Strict, weil intern fast nie über Fremdlinks eingestiegen wird.

### Parallele Sitzungen

7.1.2 verlangt eine dokumentierte Antwort auf „wie viele gleichzeitig, und was
passiert beim Überschreiten". Unbegrenzt ist eine zulässige Antwort, solange sie
bewusst getroffen wurde und die Sitzungsliste aus Phase 6 existiert.

> **Vorschlag:** unbegrenzt, dafür Sitzungsliste plus Admin-Notaus.

---

## Nicht anwendbar

Gehört in ein Konformitätsdokument, damit später niemand nachprüfen muss, ob es
vergessen wurde.

| Kapitel | Thema | Warum nicht |
|---|---|---|
| V6.6 | SMS / PSTN als zweiter Faktor | Wird nicht angeboten. TOTP ist der einzige zweite Faktor. |
| V6.8 | Externer Identity Provider | Kein SSO, keine JWT- oder SAML-Assertions. |
| V7.6 | Föderierte Re-Authentifizierung | Folgt aus V6.8: es gibt keinen IdP, dessen Lebensdauer zu koordinieren wäre. |
| 7.1.3 | Föderierte Session-Dokumentation | Ebenso. |
| 6.4.3 | Passwort-Vergessen-Ablauf | Bewusst nicht gebaut: kein Mailversand im System. Zurücksetzen macht der Admin, was zugleich 6.4.4 erfüllt. |

Level-3-Anforderungen (hardwaregebundene, phishing-resistente Faktoren) sind hier
bewusst nicht enthalten.

---

## Quellen

- [ASVS 5.0 — V6 Authentication](https://github.com/OWASP/ASVS/blob/master/5.0/en/0x15-V6-Authentication.md)
- [ASVS 5.0 — V7 Session Management](https://github.com/OWASP/ASVS/blob/master/5.0/en/0x16-V7-Session-Management.md)
- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)

Bibliotheksstände direkt von PyPI geprüft: `argon2-cffi` 25.1.0 (2025-06-03),
`pyotp` 2.10.0 (2026-06-14), `passlib` 1.7.4 (2020-10-08 — unmaintained, nicht
verwenden), `fastapi-users` 15.0.5 (2026-03-27 — gepflegt, passt aber nicht zum
sync-sqlite3-Ansatz dieses Backends).
