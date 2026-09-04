/**
 * Die Beschriftungen der Sidebar-Gruppen.
 *
 * Die *Zugehoerigkeit* steht an der Route (`meta.navGroup`) und die
 * *Reihenfolge* ergibt sich daraus, wo eine Gruppe zum ersten Mal vorkommt –
 * beides bleibt damit im Router, der einzigen Stelle, an der eine Seite
 * deklariert wird. Hier steht nur, wie eine Gruppe heisst; ein Label an jeder
 * Route zu wiederholen waere dieselbe Zeichenkette mehrfach und damit die
 * naechste Liste, die auseinanderlaufen kann.
 *
 * Eine Route ohne `navGroup` erscheint ueber den Gruppen, ohne Ueberschrift.
 * `routes.test.ts` prueft, dass jede benutzte Gruppe hier eine Beschriftung
 * hat – eine neue Gruppe ohne Eintrag waere sonst eine Ueberschrift, die
 * fehlt.
 */
export const NAV_GROUP_LABELS: Record<string, string> = {
  awin: "AWIN",
  tools: "Tools",
  management: "Management",
};
