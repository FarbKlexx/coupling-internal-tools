/**
 * Anmeldezustand für Tests setzen.
 *
 * `useAuth` hält seinen State auf Modulebene – Tests können ihn deshalb direkt
 * setzen, ohne `/auth/me` zu mocken. Wird nur von Tests importiert und landet
 * dadurch nicht im Bundle.
 */
import type { CurrentUser } from "@/api/auth.api";
import { useAuth } from "@/composables/useAuth";

const ALL_PAGES = [
  "abgleiche",
  "awin-banner",
  "webp-konverter",
  "qr-code",
  "pdf-schutz",
  "namensschilder",
  "kanban",
];

/** Meldet jemanden an. Ohne Argumente: ein Administrator. */
export function signInAs(overrides: Partial<CurrentUser> = {}): CurrentUser {
  const auth = useAuth();

  const user: CurrentUser = {
    id: "test-user",
    username: "testerin",
    is_admin: true,
    must_change_password: false,
    totp_enabled: true,
    pages: [...ALL_PAGES],
    ...overrides,
  };

  auth.user.value = user;
  auth.ready.value = true;

  return user;
}

/** Eingeschränktes Konto: kein Administrator, nur die genannten Seiten. */
export function signInWithPages(pages: string[]): CurrentUser {
  return signInAs({ is_admin: false, pages, username: "eingeschraenkt" });
}

/** Abgemeldet – aber `ready`, damit der Guard nicht auf `/auth/me` wartet. */
export function signOut(): void {
  const auth = useAuth();
  auth.user.value = null;
  auth.ready.value = true;
}
