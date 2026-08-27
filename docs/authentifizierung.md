# Authentifizierung — Sicherheitsdokumentation

Dieses Dokument erfüllt die Dokumentationspflichten aus OWASP ASVS 5.0:
**6.1.1**, **6.1.2**, **6.1.3**, **6.3.4**, **6.2.11**, **7.1.1**, **7.1.2**.

Es beschreibt den Ist-Zustand, nicht die Absicht. Wer eine der hier genannten
Zahlen im Code ändert, ändert sie auch hier.

Umsetzungsplan und Herleitung: [auth-umsetzungsplan.md](auth-umsetzungsplan.md).

---

## 1. Authentifizierungswege — 6.1.3, 6.3.4

Es gibt **genau einen** Weg in die Anwendung:

1. `POST /auth/login` mit Benutzername und Passwort
2. bei aktiviertem zweitem Faktor zusätzlich ein TOTP-Code oder ein
   Wiederherstellungscode
3. daraufhin ein Session-Cookie, das jeder weitere Request mitführt

**Es existiert kein zweiter Weg.** Insbesondere:

- Der frühere `X-Remote-User`-Header aus der nginx-Basic-Auth wird **nicht** mehr
  gelesen. Er war ein Anzeigename, nie eine Berechtigung, und ist mit dem Wegfall
  der Basic Auth ersatzlos entfallen.
- Es gibt keinen API-Key, kein statisches Token, keinen Service-Account.
- Es gibt kein SSO und keinen externen Identity Provider.
- Es gibt keine Passwort-vergessen-Funktion per E-Mail (das System versendet
  keine Mail). Zurücksetzen macht ein Administrator, siehe Abschnitt 5.

Die Durchsetzung sitzt vollständig im Backend, in einer einzigen Dependency
(`app/api/deps.py::current_user`). Jeder Feature-Router ist über
`require_page(...)` eingehängt, die Benutzerverwaltung über `require_admin`.
`backend/tests/test_access.py` läuft die Routentabelle ab und lässt eine Route
nur durch, wenn sie einen der beiden Guards trägt oder namentlich in
`PUBLIC_PATHS` steht. Eine ungeschützte Route ist damit ein fehlschlagender Test,
keine stille Lücke.

Öffentlich erreichbar sind ausschließlich:

| Pfad | Warum |
|---|---|
| `GET /health` | Container-Healthcheck. Antwortet ohne Datenbankzugriff und gibt nichts preis, was ein Verbindungsversuch nicht auch zeigt. |
| `POST /auth/login` | Der Einstiegspunkt selbst. |
| `POST /auth/logout` | Muss auch mit bereits ungültiger Session funktionieren. |
| `GET /auth/me` | Antwortet selbst mit 401, wenn keine Session vorliegt. Das Frontend fragt hier, ob überhaupt jemand angemeldet ist. |

Die FastAPI-Dokumentation (`/docs`, `/redoc`, `/openapi.json`) ist in Produktion
**abgeschaltet** (`ENABLE_API_DOCS=0`, Standard). Sie war zuvor nur deshalb nicht
öffentlich, weil die Basic Auth davorstand.

---

## 2. Passwortrichtlinie — 6.2.x

| Regel | Wert | ASVS |
|---|---|---|
| Mindestlänge | 15 Zeichen | 6.2.1 (8 gefordert, 15 empfohlen) |
| Maximallänge | 256 Zeichen | 6.2.9 (mindestens 64 gefordert) |
| Zeichenklassen-Regeln | **keine** | 6.2.5 (verboten) |
| Verarbeitung vor dem Hashen | **keine** | 6.2.8 |
| Turnusmäßiger Wechsel | **nicht erzwungen** | 6.2.10 |
| Passworthinweise, Sicherheitsfragen | **nicht vorhanden** | 6.4.2 |

Die Obergrenze von 256 Zeichen ist keine Sicherheits-, sondern eine
Verfügbarkeitsmaßnahme: Argon2 hasht die Eingabe vollständig, ein Megabyte-Passwort
wäre ein billiger Denial of Service.

„Keine Verarbeitung" heißt wörtlich: kein `strip()`, kein Kürzen, keine
Unicode-Normalisierung, keine Änderung der Groß-/Kleinschreibung. Das Passwort
wird exakt so geprüft, wie es ankommt.

### Abgelehnte Passwörter — 6.2.4, 6.2.12

Ein Passwort wird abgelehnt, wenn es

- in `backend/app/assets/wordlists/common_passwords.txt` steht (häufige und bekannt
  geleakte Passwörter, gefiltert auf solche, die die Längenregel überhaupt erfüllen
  könnten), oder
- ein Wort aus `backend/app/assets/wordlists/context_words.txt` enthält (Abschnitt 3), oder
- den Benutzernamen enthält.

Der Abgleich läuft vollständig lokal. Die Pwned-Passwords-API wird bewusst **nicht**
aufgerufen: sie brächte eine Netzwerkabhängigkeit in den Anmeldepfad und einen
Datenabfluss an Dritte, ohne bei dieser Nutzerzahl die Trefferquote zu verbessern.

### Kontextspezifische Wörter — 6.1.2, 6.2.11

`context_words.txt` enthält Organisations-, Produkt- und Systemnamen aus dem Umfeld
dieser Anwendung. Sie sind als Passwortbestandteil verboten, weil sie für jeden
Angreifer, der weiß, worum es geht, die ersten Rateversuche sind.

Wird ein neues Werkzeug oder ein neuer Kunde prominent, gehört das Wort in diese
Datei.

### Startpasswörter — 6.4.1

Ein Administrator **tippt kein Passwort ein**. Beim Anlegen eines Kontos erzeugt der
Server ein zufälliges Startpasswort (CSPRNG, erfüllt die Richtlinie oben) und zeigt es
genau einmal an. Das Konto wird mit `must_change_password` markiert: die erste
Anmeldung führt zwingend auf die Seite zum Ändern, jede andere Route leitet dorthin
zurück. Ein Startpasswort kann also nie zum Dauerpasswort werden.

Dasselbe gilt für ein vom Administrator zurückgesetztes Passwort.

---

## 3. Schutz gegen Credential Stuffing und Brute Force — 6.1.1, 6.3.1

### Zählung und Sperre

Fehlversuche werden **pro Kombination aus IP-Adresse und Benutzername** gezählt.

| Parameter | Wert |
|---|---|
| Fehlversuche bis zur Sperre | 10 |
| Beobachtungsfenster | 15 Minuten |
| Sperrdauer | 15 Minuten |

**Warum nicht pro Benutzername allein:** eine reine Benutzersperre ist selbst eine
Waffe. Wer den Anmeldenamen einer Kollegin kennt, sperrt sie mit zehn falschen
Versuchen aus dem System aus. ASVS 6.1.1 verlangt ausdrücklich, dass die
Dokumentation böswilliges Aussperren adressiert — die Bindung an die IP ist die
Antwort darauf. Ein verteilter Angriff umgeht sie, wird aber von der zweiten Stufe
erfasst:

### Zweite Stufe: Rate Limit in nginx

`frontend/nginx.conf` begrenzt `POST /api/auth/login` unabhängig vom Benutzernamen
auf **10 Anfragen pro Minute und IP** (`limit_req_zone`, `burst=5 nodelay`). Das
greift auch dann, wenn ein Angreifer viele verschiedene Benutzernamen durchprobiert,
und es hält die Last vom Argon2-Hashing fern.

### Keine Informationspreisgabe

- „Benutzer existiert nicht" und „Passwort falsch" liefern dieselbe Antwort,
  denselben Statuscode (401) und dieselbe Meldung.
- Existiert der Benutzer nicht, wird trotzdem gegen einen festen Dummy-Hash
  verifiziert. Ohne das wäre die Antwortzeit ein Benutzerverzeichnis.
- Eine bestehende Sperre wird dem Aufrufer als solche mitgeteilt (sonst rät er
  weiter und hält die Sperre offen), aber ohne Aussage darüber, ob das Konto
  existiert.

### Keine Standardkonten — 6.3.2

Es gibt kein ausgeliefertes Konto. Der erste Administrator entsteht beim ersten Start
aus den Umgebungsvariablen `ADMIN_USERNAME` und `ADMIN_PASSWORD`; beide haben
**keinen Standardwert**. Die Namen `admin`, `root`, `administrator`, `sa` und `test`
werden abgelehnt. Fehlen die Variablen und existiert noch kein Konto, **verweigert die
Anwendung den Start**, statt ohne Zugang hochzukommen.

`ADMIN_PASSWORD` wirkt ausschließlich beim Anlegen. Ein späterer Neustart überschreibt
kein geändertes Passwort.

---

## 4. Sitzungen — 7.1.1, 7.1.2, 7.3.x

### Token

Referenztoken (kein JWT): 32 Byte aus `secrets.token_urlsafe`, also 256 Bit Entropie
gegenüber den von 7.2.3 geforderten 128. Gespeichert wird ausschließlich der
SHA-256-Hash. Eine kopierte Datenbankdatei liefert damit keine nutzbaren Sitzungen.

Bei jeder Anmeldung entsteht ein neuer Token, ein etwa mitgeschicktes altes Cookie
wird entwertet (7.2.4).

### Cookie

| Attribut | Wert |
|---|---|
| Name | `__Host-session` in Produktion, `session` lokal |
| `HttpOnly` | ja |
| `Secure` | ja (in Produktion; lokal aus, da http) |
| `SameSite` | `Strict` |
| `Path` | `/` |
| `Domain` | nicht gesetzt (Voraussetzung für `__Host-`) |

**Zu `SameSite=Strict`:** wer das Werkzeug über einen Link aus einer Mail oder aus
Slack heraus öffnet, sieht beim ersten Aufruf die Anmeldeseite, obwohl er angemeldet
ist — das Cookie wird bei der ersten Fremdnavigation nicht mitgeschickt, ein Klick auf
„Anmelden" oder ein Reload genügt. Das ist bewusst in Kauf genommen: intern wird das
Werkzeug fast immer direkt aufgerufen, und `Strict` schließt CSRF vollständig aus,
statt sich auf die Methodenwahl zu verlassen.

**Zum `__Host-`-Präfix:** es erzwingt `Secure` und verbietet ein `Domain`-Attribut,
wodurch ein Cookie nicht von einer Subdomain gesetzt werden kann. Lokal läuft die
Anwendung über http, wo `Secure` das Cookie unbrauchbar machen würde — deshalb kommt
der Name aus `SESSION_COOKIE_NAME`.

### Lebensdauer — 7.1.1, 7.3.1, 7.3.2

| Grenze | Wert |
|---|---|
| Inaktivität | 8 Stunden |
| Absolut | 24 Stunden |

**Begründung der Abweichung.** Der OWASP Session Management Cheat Sheet nennt als
Richtwerte 15–30 Minuten Inaktivität und 4–8 Stunden absolut. Diese Anwendung ist ein
internes Back-Office ohne personenbezogene Massendaten, ohne Zahlungsfunktion und
ohne Zugriff auf Kundensysteme; sie ist ausschließlich über die Firmen-Anmeldung
erreichbar und durch einen zweiten Faktor geschützt. Der Schaden einer übernommenen
Sitzung ist auf die Inhalte dieser Anwendung begrenzt.

Dem gegenüber steht, dass eine 30-Minuten-Grenze bei einem Werkzeug, das über den Tag
verteilt in kurzen Einheiten benutzt wird, zu mehreren Anmeldungen täglich führt — mit
dem bekannten Nebeneffekt, dass Passwörter dann kürzer und Passwortmanager seltener
werden. 8 Stunden decken einen Arbeitstag, 24 Stunden begrenzen den Schaden eines
liegengebliebenen Geräts auf höchstens einen Tag.

ASVS 7.1.1 lässt diese Abweichung ausdrücklich zu, sofern sie dokumentiert und
begründet ist. Das ist hiermit geschehen.

### Parallele Sitzungen — 7.1.2

**Unbegrenzt.** Eine Person darf gleichzeitig an Arbeitsplatzrechner, Notebook und
Telefon angemeldet sein; ein Limit brächte hier keinen Sicherheitsgewinn, sondern
würde die zuletzt benutzte Sitzung willkürlich beenden.

Ausgeglichen wird das durch Sichtbarkeit und Widerruf:

- Jede Person sieht unter „Aktive Sitzungen" alle eigenen Sitzungen mit Gerät,
  IP-Adresse und letztem Zugriff und kann jede einzelne oder alle übrigen beenden
  (7.5.2).
- Ein Administrator kann alle Sitzungen einer Person oder aller Personen beenden
  (7.4.5).
- Ein Passwortwechsel beendet automatisch alle übrigen Sitzungen (7.4.3).
- Deaktivieren oder Löschen eines Kontos beendet dessen Sitzungen sofort (7.4.2).

---

## 5. Zweiter Faktor — 6.3.3, 6.5.x

TOTP nach RFC 6238, 30-Sekunden-Schritte, Toleranz ±1 Schritt gegen Uhrendrift. Der
Seed stammt aus einem CSPRNG. Der Einrichtungs-QR-Code wird lokal erzeugt
(`app/core/qr_utils.py`); der Seed verlässt den Server nur in diesem einen Bild.

Das **Einrichten und das Umhängen** des zweiten Faktors verlangen zusätzlich das
eigene Passwort (6.5.1 zusammen mit 7.5.1). Ohne diese Prüfung könnte jemand mit
einer übernommenen Sitzung den zweiten Faktor auf sein eigenes Gerät umhängen,
ohne das Passwort zu kennen — und wäre danach schwerer aus dem Konto zu bekommen
als der rechtmäßige Besitzer.

Ein Code ist **genau einmal** verwendbar (6.5.1): der zuletzt akzeptierte Zeitschritt
wird pro Konto gespeichert, ein erneutes Einreichen desselben Codes innerhalb seines
30-Sekunden-Fensters wird abgewiesen.

**Wiederherstellungscodes:** zehn Stück aus einem CSPRNG, je 20 Zeichen Base32
(deutlich über den in 6.5.4 geforderten 20 Bit). Sie werden mit demselben Argon2id
gehasht wie Passwörter, wie es 6.5.2 für Geheimnisse unter 112 Bit verlangt, und sind
je einmal verwendbar.

**Verlust des zweiten Faktors — 6.4.4:** ein Administrator setzt ihn zurück. Da diese
Anwendung ausschließlich intern und in einem Büro mit persönlich bekannten Personen
benutzt wird, ist die Identitätsprüfung dieselbe wie bei der Einrichtung: persönlich
oder über einen etablierten Kanal, in dem die Person zweifelsfrei bekannt ist. Ein
Zurücksetzen über E-Mail oder Telefon findet nicht statt.

**Verpflichtend?** Die Anwendung erzwingt die Einrichtung nicht technisch für jedes
Konto — sie bietet sie an und ein Administrator kann sie pro Konto verlangen. Für die
Einstufung nach ASVS Level 2 muss sie für alle Konten aktiv sein; der Stand ist in der
Benutzerverwaltung pro Konto sichtbar.

---

## 6. Speicherung von Geheimnissen

| Geheimnis | Verfahren |
|---|---|
| Passwörter | Argon2id, `m=19456 KiB, t=2, p=1` (OWASP-Minimum), Salt je Eintrag |
| Wiederherstellungscodes | Argon2id, gleiche Parameter |
| Session-Token | SHA-256 (volle Entropie, kein Wörterbuchangriff möglich) |
| TOTP-Seed | im Klartext, da er zur Prüfung rekonstruierbar sein muss |

Die Argon2-Parameter werden beim Anmelden über `check_needs_rehash()` geprüft. Werden
sie später angehoben, wandern bestehende Passwörter bei der nächsten Anmeldung
automatisch mit.

Der TOTP-Seed ist das einzige Geheimnis, das im Klartext liegt — das ist bei TOTP
verfahrensbedingt so. Wer Lesezugriff auf die Datenbankdatei hat, kann damit Codes
erzeugen; er hätte dann allerdings ohnehin Zugriff auf den Server.

**In keinem Codepfad der Anmeldung wird geloggt.** Weder Passwörter noch Token noch
TOTP-Codes dürfen in einer Logzeile erscheinen.

---

## 7. Wo was liegt

| Datei | Inhalt |
|---|---|
| `backend/app/core/auth_db.py` | Einziges Modul mit SQL für Konten und Sitzungen |
| `backend/app/core/security.py` | Hashing, Token, Passwortrichtlinie, TOTP |
| `backend/app/services/auth_service.py` | Anmeldung, Sperre, Kontenverwaltung |
| `backend/app/api/auth_api.py` | HTTP-Schicht, Cookie-Behandlung |
| `backend/app/api/deps.py` | `current_user`, `require_page`, `require_admin` |
| `backend/tests/test_access.py` | Prüft, dass keine Route ungeschützt ist |
| `docs/auth-umsetzungsplan.md` | Herleitung und ASVS-Zuordnung |

Die Datenbank liegt unter `AUTH_DB_PATH` (Standard `data/auth.db`), im Container also
unter `/app/data/auth.db` und damit im selben gemounteten Verzeichnis wie das
Kanban-Board. **Ohne dieses Mount sind alle Konten beim nächsten Image-Rebuild weg.**
Sicherung = dieses Verzeichnis sichern.
