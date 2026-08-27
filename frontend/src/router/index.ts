// src/router/index.ts
import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import { useAuth } from "@/composables/useAuth";

import DashboardView from "@/views/DashboardView.vue";
import AbgleicheView from "@/views/AbgleicheView.vue";
import AwinBannerView from "@/views/AwinBannerView.vue";
import WebpConverterView from "@/views/WebpConverterView.vue";
import QrCodeView from "@/views/QrCodeView.vue";
import PdfProtectView from "@/views/PdfProtectView.vue";
import NameBadgeView from "@/views/NameBadgeView.vue";
import KanbanView from "@/views/KanbanView.vue";
import TelefonakquiseView from "@/views/TelefonakquiseView.vue";
import LoginView from "@/views/LoginView.vue";
import PasswordChangeView from "@/views/PasswordChangeView.vue";
import AccountView from "@/views/AccountView.vue";
import UserAdminView from "@/views/UserAdminView.vue";

/**
 * Die Feature-Routen – und damit die einzige Stelle, an der eine Seite
 * deklariert wird.
 *
 * Sidebar (`navigation/buildNavItems.ts`) und Kommandopalette
 * (`search/buildRouteSearchIndex.ts`) leiten sich beide aus dieser Liste ab.
 * Eine neue Seite ist deshalb ein Eintrag hier, sonst nichts.
 *
 * `meta.page` ist der Berechtigungsschluessel und muss im `Page`-Enum des
 * Backends existieren (`backend/app/schemas/access.py`), siehe
 * `pageIds.test.ts`. Eine Route ohne `page` braucht keine Berechtigung.
 *
 * Wird zusaetzlich exportiert, weil `router.getRoutes()` die
 * Deklarationsreihenfolge nicht garantiert – vue-router sortiert dort nach
 * Match-Spezifitaet. Fuer die Sidebar ist die Reihenfolge aber bedeutungs-
 * tragend, also liest sie dieses Array.
 */
export const routes: RouteRecordRaw[] = [
  // Ohne Anmeldung erreichbar und ohne Dashboard-Layout gerendert.
  {
    path: "/login",
    name: "login",
    component: LoginView,
    meta: { public: true, searchable: false, sidebar: false, label: "Anmelden" },
  },
  // Erzwungener Passwortwechsel nach einem Start- oder zurueckgesetzten
  // Passwort. Erreichbar, solange `must_change_password` gesetzt ist – und
  // dann fuehrt der Guard jede andere Route hierher zurueck.
  {
    path: "/passwort-aendern",
    name: "passwort-aendern",
    component: PasswordChangeView,
    meta: { searchable: false, sidebar: false, label: "Passwort ändern", icon: "key" },
  },
  // Eigenes Konto: Passwort, zweiter Faktor, aktive Sitzungen. Braucht keine
  // Seitenberechtigung – wer angemeldet ist, darf sein eigenes Konto sehen.
  {
    path: "/konto",
    name: "konto",
    component: AccountView,
    meta: { searchable: false, sidebar: false, label: "Mein Konto", icon: "account_circle" },
  },
  // Die Dashboard-Seite ist noch ein Stub und deshalb weder in der Sidebar
  // noch in der Suche sichtbar. Route bleibt erhalten, /dashboard ist direkt
  // aufrufbar. Ohne Backend dahinter gibt es auch nichts zu berechtigen –
  // `page` kommt dazu, wenn die Seite echt wird.
  {
    path: "/dashboard",
    name: "dashboard",
    component: DashboardView,
    meta: {
      searchable: false,
      sidebar: false,
      label: "Dashboard",
      icon: "home",
      keywords: ["home", "overview"],
    },
  },
  {
    path: "/abgleiche",
    name: "abgleiche",
    component: AbgleicheView,
    meta: {
      searchable: true,
      sidebar: true,
      page: "abgleiche",
      label: "AWIN Abgleiche",
      icon: "table",
      keywords: ["awin", "vergleich", "csv", "abgleich"],
    },
  },
  {
    path: "/awin-banner",
    name: "awin-banner",
    component: AwinBannerView,
    meta: {
      searchable: true,
      sidebar: true,
      page: "awin-banner",
      label: "AWIN Banner CSV",
      icon: "image",
      keywords: ["awin", "banner", "csv", "mass upload"],
    },
  },
  {
    path: "/webp-konverter",
    name: "webp-konverter",
    component: WebpConverterView,
    meta: {
      searchable: true,
      sidebar: true,
      page: "webp-konverter",
      label: "WebP Konverter",
      icon: "compress",
      keywords: [
        "bild",
        "bilder",
        "image",
        "webp",
        "konvertieren",
        "jpg",
        "png",
        "heic",
        "komprimieren",
      ],
    },
  },
  {
    path: "/qr-code",
    name: "qr-code",
    component: QrCodeView,
    meta: {
      searchable: true,
      sidebar: true,
      page: "qr-code",
      label: "QR-Code Generator",
      icon: "qr_code_2",
      keywords: ["qr", "qr-code", "link", "png", "svg", "generator"],
    },
  },
  {
    path: "/pdf-schutz",
    name: "pdf-schutz",
    component: PdfProtectView,
    meta: {
      searchable: true,
      sidebar: true,
      page: "pdf-schutz",
      label: "PDF Passwortschutz",
      icon: "lock",
      keywords: ["pdf", "passwort", "schutz", "verschluesseln", "sichern", "aes"],
    },
  },
  {
    path: "/namensschilder",
    name: "namensschilder",
    component: NameBadgeView,
    meta: {
      searchable: true,
      sidebar: true,
      page: "namensschilder",
      label: "Namensschilder",
      icon: "badge",
      keywords: [
        "namensschild",
        "namensschilder",
        "einsteckschilder",
        "schilder",
        "veranstaltung",
        "event",
        "teilnehmer",
        "csv",
        "pdf",
        "drucken",
      ],
    },
  },
  {
    path: "/kanban",
    name: "kanban",
    component: KanbanView,
    meta: {
      searchable: true,
      sidebar: true,
      page: "kanban",
      label: "Kanban Board",
      icon: "view_kanban",
      keywords: ["kanban", "board", "aufgaben", "todo", "tasks", "karten", "kunden"],
    },
  },
  {
    path: "/telefonakquise",
    name: "telefonakquise",
    component: TelefonakquiseView,
    meta: {
      searchable: true,
      sidebar: true,
      page: "telefonakquise",
      label: "Telefonakquise",
      icon: "phone_in_talk",
      keywords: [
        "telefon",
        "anrufen",
        "anrufliste",
        "akquise",
        "kaltakquise",
        "kunden",
        "leads",
        "einwilligung",
        "csv",
      ],
    },
  },
  // Benutzerverwaltung: `adminOnly` statt `page`, siehe meta.d.ts.
  //
  // Steht bewusst *hinter* den Werkzeugen: die Reihenfolge hier ist zugleich
  // die der Sidebar und bestimmt, wo ein Administrator nach der Anmeldung
  // landet. Weiter oben waere die Kontenverwaltung die Startseite.
  {
    path: "/benutzer",
    name: "benutzer",
    component: UserAdminView,
    meta: {
      searchable: true,
      sidebar: true,
      adminOnly: true,
      label: "Benutzer",
      icon: "group",
      keywords: ["benutzer", "user", "konten", "rechte", "berechtigungen", "admin", "zugang"],
    },
  },
  {
    path: "/",
    // Nicht mehr fest auf /abgleiche: wer diese Seite nicht sehen darf, landet
    // sonst auf einem 403 statt auf seiner ersten erlaubten Seite. Der Guard
    // unten loest das auf.
    redirect: { name: "start" },
  },
  {
    path: "/start",
    name: "start",
    // Wird nie gerendert – der Guard leitet vorher weiter. Existiert nur, damit
    // "/" ein benanntes Ziel hat.
    component: { render: () => null },
    meta: { searchable: false, sidebar: false, label: "Start" },
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});

/** Die erste Seite, die dieser Benutzer öffnen darf. */
function firstAllowedRoute(auth: ReturnType<typeof useAuth>): string {
  const candidate = routes.find(
    (route) =>
      route.meta?.sidebar &&
      route.name &&
      (route.meta?.adminOnly ? auth.isAdmin.value : auth.mayOpen(route.meta?.page)),
  );

  return String(candidate?.name ?? "konto");
}

/**
 * Der Zugangs-Guard.
 *
 * Reine Navigation – die Durchsetzung sitzt im Backend. Was hier passiert, ist
 * dem Anwender ein 403 zu ersparen, das er nicht beeinflussen kann.
 */
router.beforeEach(async (to) => {
  const auth = useAuth();

  // Einmal pro Seitenaufruf klaeren, wer da ist. `refresh` buendelt parallele
  // Aufrufe selbst, ein zweiter Guard-Durchlauf loest also keinen zweiten
  // Request aus.
  if (!auth.ready.value) await auth.refresh();

  if (to.meta.public) {
    // Angemeldet auf der Anmeldeseite: weiter zur Anwendung.
    return auth.isAuthenticated.value ? { name: firstAllowedRoute(auth) } : true;
  }

  if (!auth.isAuthenticated.value) {
    return { name: "login", query: to.fullPath === "/" ? {} : { weiter: to.fullPath } };
  }

  // Startpasswort noch nicht gewechselt: alles fuehrt dorthin zurueck. Das
  // Backend antwortet auf die Werkzeuge ohnehin mit 403 (ASVS 6.4.1); hier
  // wird daraus ein sinnvoller Weg statt einer Fehlermeldung.
  if (auth.mustChangePassword.value && to.name !== "passwort-aendern") {
    return { name: "passwort-aendern" };
  }

  if (to.name === "start") return { name: firstAllowedRoute(auth) };

  if (to.meta.adminOnly && !auth.isAdmin.value) return { name: firstAllowedRoute(auth) };

  if (!auth.mayOpen(to.meta.page)) return { name: firstAllowedRoute(auth) };

  return true;
});
