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

function readStored(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    // Privater Modus / blockierter Storage: eingeklappt ist dann eben nicht persistent.
    return false;
  }
}

const collapsed = ref(readStored());

watch(collapsed, (value) => {
  try {
    localStorage.setItem(STORAGE_KEY, String(value));
  } catch {
    // Persistenz ist Komfort, kein Muss.
  }
});

export function useSidebar() {
  function toggle() {
    collapsed.value = !collapsed.value;
  }

  return { collapsed, toggle };
}
