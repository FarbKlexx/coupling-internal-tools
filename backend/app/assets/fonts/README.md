# Schriften für die Namensschilder-PDFs

`badge_pdf.py` bettet ausschließlich diese Dateien ein — als Subset, mit
`/FontFile2`. Systemschriften und die Base-14-Schriften sind bewusst außen vor:
der Druckertreiber würde dafür eine eigene Metrik ziehen, der Text hätte im
Druck andere Breiten als beim Ausmessen und liefe aus der Sicherheitszone.

| Datei | Schnitt | Herkunft |
|---|---|---|
| `Outfit-Regular.ttf` | wght 400 | Outfit (Google Fonts, OFL 1.1) |
| `Outfit-Bold.ttf` | wght 700 | Outfit (Google Fonts, OFL 1.1) |

Outfit ist auch die Schrift der Oberfläche (`index.html`), Bildschirm und Druck
sehen also gleich aus.

## Woher die beiden Dateien kommen

Google Fonts liefert Outfit nur noch als Variable Font. Die beiden statischen
Schnitte sind daraus instanziert — reproduzierbar mit:

```bash
curl -sSL -o 'Outfit[wght].ttf' \
  'https://github.com/google/fonts/raw/main/ofl/outfit/Outfit%5Bwght%5D.ttf'

python - <<'PY'
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

for weight, name in ((400, "Regular"), (700, "Bold")):
    font = TTFont("Outfit[wght].ttf")
    instancer.instantiateVariableFont(
        font, {"wght": weight}, updateFontNames=True, inplace=True
    )
    font.save(f"Outfit-{name}.ttf")
PY
```

`fontTools` kommt mit `fpdf2` ohnehin mit; für den Schritt oben wird es nur
einmalig gebraucht, nicht zur Laufzeit.

**Die Variable-Font-Datei selbst darf nicht eingebettet werden**: ihre
Default-Instanz ist Thin (wght 100), und einen fetten Schnitt gäbe es daraus
im PDF nicht.

## Lizenz

SIL Open Font License 1.1, siehe `OFL.txt`. Einbetten in PDFs ist ausdrücklich
erlaubt.
