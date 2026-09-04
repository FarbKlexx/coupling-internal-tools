/**
 * Ein-/ausklappbare Navigation.
 *
 * Der State liegt **auf Modulebene**, nicht in der Composable-Funktion: so
 * teilen Sidebar und (spaeter) TopBar dieselbe Quelle, ohne dass ein Store
 * dafuer noetig ist. Gespeichert wird in `localStorage`, damit die Wahl einen
 * Reload ueberlebt.
 */
import { ref, watch } from "vue";

const STORAGE_KEY = "sidebar:collapsed";
const GROUPS_KEY = "sidebar:closed-groups";

function readStored(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    // Privater Modus / blockierter Storage: eingeklappt ist dann eben nicht persistent.
    return false;
  }
}

/**
 * Gespeichert werden die **zugeklappten** Gruppen, nicht die offenen: eine
 * spaeter hinzukommende Gruppe ist damit von selbst offen und nicht
 * versehentlich unsichtbar fuer jeden, der die Anwendung schon benutzt hat.
 */
function readClosedGroups(): string[] {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(GROUPS_KEY) ?? "[]");

    return Array.isArray(stored) ? stored.filter((id) => typeof id === "string") : [];
  } catch {
    // Kaputter oder blockierter Storage: dann eben alles aufgeklappt.
    return [];
  }
}

const collapsed = ref(readStored());
const closedGroups = ref<string[]>(readClosedGroups());

watch(collapsed, (value) => {
  try {
    localStorage.setItem(STORAGE_KEY, String(value));
  } catch {
    // Persistenz ist Komfort, kein Muss.
  }
});

watch(
  closedGroups,
  (value) => {
    try {
      localStorage.setItem(GROUPS_KEY, JSON.stringify(value));
    } catch {
      // Persistenz ist Komfort, kein Muss.
    }
  },
  { deep: true },
);

export function useSidebar() {
  function toggle() {
    collapsed.value = !collapsed.value;
  }

  function isGroupOpen(id: string) {
    return !closedGroups.value.includes(id);
  }

  function toggleGroup(id: string) {
    closedGroups.value = isGroupOpen(id)
      ? [...closedGroups.value, id]
      : closedGroups.value.filter((entry) => entry !== id);
  }

  return { collapsed, toggle, isGroupOpen, toggleGroup };
}
