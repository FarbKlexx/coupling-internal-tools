/**
 * Angemeldeter Benutzer und seine Berechtigungen.
 *
 * Der State liegt **auf Modulebene**, nicht in der Composable-Funktion – wie
 * bei `useSidebar`. So teilen Router-Guard, Sidebar, Suche und TopBar dieselbe
 * Quelle, ohne dass dafür ein Store nötig wäre.
 *
 * Wichtig zur Einordnung: alles hier ist **Anzeige**. Die Durchsetzung sitzt
 * im Backend (`app/api/deps.py`), das jeden Endpunkt hinter einer Berechtigung
 * hält. Was dieses Modul filtert, ist die Navigation – damit niemand auf einen
 * Menüpunkt klickt, der ihm ohnehin ein 403 liefert.
 */
import { computed, ref } from "vue";
import { fetchMe, login as postLogin, logout as postLogout } from "@/api/auth.api";
import type { CurrentUser, LoginInput, PageId } from "@/api/auth.api";

const user = ref<CurrentUser | null>(null);

/** Ob `/auth/me` schon beantwortet wurde. Der Guard wartet darauf. */
const ready = ref(false);

/** Läuft gerade eine Abfrage? Verhindert, dass der Guard sie mehrfach startet. */
let pending: Promise<void> | null = null;

async function refresh(): Promise<void> {
  if (pending) return pending;

  pending = (async () => {
    try {
      user.value = await fetchMe();
    } catch {
      // Netzwerkfehler heißt nicht "abgemeldet", aber ohne Antwort kann der
      // Guard nichts durchlassen – fail closed, wie im Backend.
      user.value = null;
    } finally {
      ready.value = true;
      pending = null;
    }
  })();

  return pending;
}

async function login(input: LoginInput): Promise<CurrentUser> {
  const result = await postLogin(input);
  user.value = result;
  ready.value = true;
  return result;
}

async function logout(): Promise<void> {
  try {
    await postLogout();
  } finally {
    // Auch wenn der Aufruf scheitert: lokal ist die Sitzung beendet.
    user.value = null;
    ready.value = true;
  }
}

/** Nach einem 401 aus dem Interceptor – ohne erneuten Netzaufruf. */
function forget(): void {
  user.value = null;
  ready.value = true;
}

/**
 * Ob eine Seite geöffnet werden darf.
 *
 * Eine Route ohne `page` braucht keine Berechtigung (der Dashboard-Stub, die
 * Kontoseiten). Administratoren dürfen alles – das Backend sieht es genauso.
 */
function mayOpen(page: PageId | undefined): boolean {
  if (!page) return true;
  if (!user.value) return false;
  if (user.value.is_admin) return true;

  return user.value.pages.includes(page);
}

const isAuthenticated = computed(() => user.value !== null);
const isAdmin = computed(() => user.value?.is_admin === true);
const mustChangePassword = computed(() => user.value?.must_change_password === true);

export function useAuth() {
  return {
    user,
    ready,
    isAuthenticated,
    isAdmin,
    mustChangePassword,
    refresh,
    login,
    logout,
    forget,
    mayOpen,
  };
}
