import type { RouteRecordRaw } from "vue-router";

/**
 * Ob eine Route in der Navigation auftauchen darf.
 *
 * Ein Helfer für **beide** Oberflächen – Sidebar und Kommandopalette. Zwei
 * getrennte Filter wären zwei Stellen, die auseinanderlaufen können, und man
 * merkt es erst, wenn die Suche eine Seite anbietet, die 403 liefert.
 *
 * `adminOnly`-Routen (die Benutzerverwaltung) hängen nicht an einer
 * Seitenberechtigung, sondern am Administratorflag – deshalb die zweite
 * Bedingung.
 */
export interface Visibility {
  mayOpen: (page: string | undefined) => boolean;
  isAdmin: boolean;
}

export function isVisible(route: RouteRecordRaw, visibility?: Visibility): boolean {
  // Ohne Auskunft über den Benutzer wird nicht gefiltert: die Tests und der
  // erste Frame vor dem `/auth/me` sollen die vollständige Liste sehen.
  if (!visibility) return true;

  if (route.meta?.adminOnly) return visibility.isAdmin;

  return visibility.mayOpen(route.meta?.page);
}
