import "vue-router";

declare module "vue-router" {
  interface RouteMeta {
    /** Taucht in der Kommandopalette auf. */
    searchable?: boolean;
    /** Taucht in der Sidebar auf – siehe `navigation/buildNavItems.ts`. */
    sidebar?: boolean;
    label?: string;
    icon?: string;
    keywords?: string[];
    /**
     * Berechtigungsschluessel dieser Seite.
     *
     * Bewusst nicht der Routenname: mehrere Routen duerfen spaeter auf
     * dieselbe Berechtigung zeigen (`/kanban` und ein spaeteres
     * `/kanban/archiv`), und eine Route ganz ohne `page` ist eine, die keine
     * Berechtigung braucht. Die gueltigen Werte sind das `Page`-Enum in
     * `backend/app/schemas/access.py`; `pageIds.test.ts` haelt beide Seiten
     * zusammen.
     */
    page?: string;
    /**
     * Ohne Anmeldung erreichbar (die Anmeldeseite selbst). Solche Routen
     * werden ausserdem ohne das Dashboard-Layout gerendert.
     */
    public?: boolean;
    /**
     * Nur fuer Administratoren. Bewusst getrennt von `page`: die
     * Benutzerverwaltung haengt am Administratorflag und nicht an einer
     * Seitenberechtigung, hat also keinen Eintrag im `Page`-Enum.
     */
    adminOnly?: boolean;
  }
}
