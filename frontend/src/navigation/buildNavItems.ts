import type { RouteRecordRaw } from "vue-router";
import { isVisible, type Visibility } from "./visiblePages";
import { NAV_GROUP_LABELS } from "./navGroups";

/**
 * Ein Eintrag der Sidebar.
 *
 * `id` ist der Routenname – die Sidebar navigiert per `router.push({ name })`
 * und nicht per Pfad, damit ein umgezogener Pfad hier nichts kaputt macht.
 */
export interface NavItem {
  id: string;
  label: string;
  icon: string;
}

/** Eine einklappbare Gruppe der Sidebar. Ohne `label` wird sie ohne Ueberschrift gerendert. */
export interface NavGroup {
  id: string;
  label?: string;
  items: NavItem[];
}

/**
 * Die Sidebar in ihren zwei Zonen: die Gruppen und der am unteren Rand
 * verankerte Fussbereich (`meta.navFooter`, aktuell die Benutzerverwaltung).
 */
export interface NavSections {
  groups: NavGroup[];
  footer: NavItem[];
}

/**
 * Die sichtbaren Sidebar-Routen in Deklarationsreihenfolge.
 *
 * Erwartet bewusst das rohe `routes`-Array aus dem Router und nicht
 * `router.getRoutes()`: letzteres gibt die Reihenfolge nicht so zurueck, wie
 * sie deklariert wurde, und die Reihenfolge *ist* hier die Menuestruktur.
 */
function visibleRoutes(
  routes: readonly RouteRecordRaw[],
  visibility?: Visibility,
): RouteRecordRaw[] {
  return routes
    .filter((route) => route.meta?.sidebar && route.name)
    .filter((route) => isVisible(route, visibility));
}

function toNavItem(route: RouteRecordRaw): NavItem {
  return {
    id: String(route.name),
    label: String(route.meta?.label ?? route.name),
    icon: String(route.meta?.icon),
  };
}

/**
 * Baut die Sidebar aus den Routen – flach, ohne Gruppierung.
 *
 * Frueher war das ein zweites, hartkodiertes Array in `SideBar.vue` – mit
 * eigenen Labels und einem eigenen `enabled`-Flag. Zwei Listen, die
 * uebereinstimmen mussten, obwohl nichts sie zusammenhielt ausser einem Test.
 */
export function buildNavItems(
  routes: readonly RouteRecordRaw[],
  visibility?: Visibility,
): NavItem[] {
  return visibleRoutes(routes, visibility).map(toNavItem);
}

/**
 * Dieselben Eintraege, aber nach `meta.navGroup` gebuendelt.
 *
 * Die Gruppenreihenfolge ist die ihres ersten Mitglieds, nicht die von
 * `NAV_GROUP_LABELS`: dadurch bleibt die Reihenfolge der Routen die
 * Menuestruktur, so wie vor der Gruppierung. Eine Gruppe, von der ein
 * Benutzer keine einzige Seite oeffnen darf, entsteht gar nicht erst – sie
 * waere eine Ueberschrift ohne Inhalt.
 */
export function buildNavSections(
  routes: readonly RouteRecordRaw[],
  visibility?: Visibility,
): NavSections {
  const groups: NavGroup[] = [];
  const footer: NavItem[] = [];

  for (const route of visibleRoutes(routes, visibility)) {
    const item = toNavItem(route);

    if (route.meta?.navFooter) {
      footer.push(item);
      continue;
    }

    const id = String(route.meta?.navGroup ?? "");
    let group = groups.find((candidate) => candidate.id === id);

    if (!group) {
      group = { id, label: NAV_GROUP_LABELS[id], items: [] };
      groups.push(group);
    }

    group.items.push(item);
  }

  return { groups, footer };
}
