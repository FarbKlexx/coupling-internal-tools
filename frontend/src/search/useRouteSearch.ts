import Fuse from "fuse.js";
import { buildRouteSearchIndex } from "./buildRouteSearchIndex";
import { useAuth } from "@/composables/useAuth";
import { router } from "@/router";

/**
 * Der Index wird pro Suche gebaut, nicht einmal beim Laden des Moduls.
 *
 * Er haengt jetzt davon ab, wer angemeldet ist – ein zur Ladezeit erzeugter
 * Index waere der eines noch unbekannten Benutzers und wuerde Seiten
 * anbieten, die ein 403 liefern.
 */
function currentIndex() {
  const auth = useAuth();

  return buildRouteSearchIndex(router.getRoutes(), {
    mayOpen: auth.mayOpen,
    isAdmin: auth.isAdmin.value,
  });
}

/**
 * Alles, was dieser Benutzer oeffnen darf, in der Reihenfolge der Routen —
 * also derselben, in der auch die Navigation die Eintraege zeigt.
 *
 * Das ist die Liste, die die Palette ohne Suchbegriff anzeigt: ein leeres
 * Feld hiess vorher „keine Treffer", obwohl niemand etwas gesucht hatte, und
 * wer die Suche oeffnet, um zu sehen *was* es gibt, bekam ein leeres Fenster.
 */
export function allRoutes() {
  return currentIndex();
}

export function searchRoutes(query: string) {
  if (!query.trim()) return [];

  const fuse = new Fuse(currentIndex(), {
    includeScore: true,
    threshold: 0.4,
    ignoreLocation: true,
    keys: [
      { name: "label", weight: 0.6 },
      { name: "path", weight: 0.2 },
      { name: "keywords", weight: 0.2 },
    ],
  });

  return fuse.search(query);
}
