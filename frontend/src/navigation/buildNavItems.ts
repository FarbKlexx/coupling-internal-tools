import type { RouteRecordRaw } from "vue-router";
import { isVisible, type Visibility } from "./visiblePages";

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

/**
 * Baut die Sidebar aus den Routen.
 *
 * Frueher war das ein zweites, hartkodiertes Array in `SideBar.vue` – mit
 * eigenen Labels und einem eigenen `enabled`-Flag. Zwei Listen, die
 * uebereinstimmen mussten, obwohl nichts sie zusammenhielt ausser einem Test.
 *
 * Erwartet bewusst das rohe `routes`-Array aus dem Router und nicht
 * `router.getRoutes()`: letzteres gibt die Reihenfolge nicht so zurueck, wie
 * sie deklariert wurde, und die Reihenfolge *ist* hier die Menuestruktur.
 */
export function buildNavItems(
  routes: readonly RouteRecordRaw[],
  visibility?: Visibility,
): NavItem[] {
  return routes
    .filter((route) => route.meta?.sidebar && route.name)
    .filter((route) => isVisible(route, visibility))
    .map((route) => ({
      id: String(route.name),
      label: String(route.meta?.label ?? route.name),
      icon: String(route.meta?.icon),
    }));
}
