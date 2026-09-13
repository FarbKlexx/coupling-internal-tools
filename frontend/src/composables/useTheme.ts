/**
 * Hell- und Dunkelmodus.
 *
 * Der State liegt **auf Modulebene** wie bei `useSidebar`: Topbar und jede
 * andere Stelle, die den Modus lesen will, teilen dieselbe Quelle, ohne dass
 * ein Store dafuer noetig waere.
 *
 * Umgeschaltet wird ein einziges Attribut am <html>-Element; alle Farben
 * haengen als CSS-Variablen daran (siehe `style.css`). Deshalb gibt es hier
 * keine Liste von Komponenten, die etwas mitbekommen muessten.
 *
 * Gesetzt wird das Attribut zusaetzlich schon im Inline-Skript in
 * `index.html`, also vor dem ersten Bild. Ohne das blitzt bei jedem Laden
 * der jeweils andere Modus auf, weil Vue erst nach dem Parsen laeuft — und
 * die Reihenfolge ist dort dieselbe wie hier, damit beide zum selben
 * Ergebnis kommen.
 */
import { computed, ref, watch } from "vue";

export type Theme = "dark" | "light";

const STORAGE_KEY = "theme";

/** Was gespeichert wurde — oder nichts, wenn noch nie umgeschaltet wurde. */
function readStored(): Theme | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);

    return stored === "dark" || stored === "light" ? stored : null;
  } catch {
    // Privater Modus / blockierter Storage: dann eben nicht persistent.
    return null;
  }
}

/**
 * Die Voreinstellung des Betriebssystems. Nur relevant, solange niemand
 * selbst gewaehlt hat — eine eigene Wahl schlaegt sie danach.
 */
function preferred(): Theme {
  try {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  } catch {
    // jsdom kennt matchMedia nicht immer.
    return "dark";
  }
}

const theme = ref<Theme>(readStored() ?? preferred());

/**
 * Den Modus setzen — und dabei jeden Uebergang kurz stilllegen.
 *
 * Ohne das laufen beim Umschalten *alle* Uebergaenge gleichzeitig los: jeder
 * Nav-Eintrag, jeder Knopf, jede Karte faehrt 150 ms lang von seiner alten in
 * seine neue Farbe, und weil sie unterschiedliche Eigenschaften und Dauern
 * haben, sieht das nicht aus wie ein Wechsel, sondern wie ein Flackern.
 *
 * Zwei Frames, nicht einer: der erste laesst den Browser mit der neuen Farbe
 * zeichnen, erst danach darf wieder ueberblendet werden. Waere die Klasse
 * schon im ersten Frame weg, haette sie nie gegolten.
 */
function apply(value: Theme) {
  const root = document.documentElement;

  root.classList.add("theme-switching");
  root.dataset.theme = value;

  requestAnimationFrame(() => {
    requestAnimationFrame(() => root.classList.remove("theme-switching"));
  });
}

apply(theme.value);

watch(theme, (value) => {
  apply(value);

  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Persistenz ist Komfort, kein Muss.
  }
});

export function useTheme() {
  const isLight = computed(() => theme.value === "light");

  function toggle() {
    theme.value = theme.value === "light" ? "dark" : "light";
  }

  return { theme, isLight, toggle };
}
