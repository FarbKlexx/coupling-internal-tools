import { AxiosError } from "axios";
import { http } from "./http";

/**
 * Berechtigungs-IDs.
 *
 * Absichtlich `string` und keine Aufzählung: die gültigen Werte stehen im
 * `Page`-Enum des Backends, hier stehen sie ein zweites Mal in der Route-Meta.
 * Eine dritte Deklaration als TS-Union wäre eine dritte Stelle, die driften
 * kann – `pageIds.test.ts` hält die beiden vorhandenen zusammen.
 */
export type PageId = string;

export interface CurrentUser {
  id: string;
  username: string;
  is_admin: boolean;
  must_change_password: boolean;
  totp_enabled: boolean;
  pages: PageId[];
}

export interface SessionInfo {
  id: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  user_agent: string;
  ip: string;
  current: boolean;
}

export interface UserSummary {
  id: string;
  username: string;
  is_admin: boolean;
  active: boolean;
  must_change_password: boolean;
  totp_enabled: boolean;
  pages: PageId[];
  created_at: string;
  password_changed_at: string;
  session_count: number;
}

export interface CreatedUser {
  user: UserSummary;
  initial_password: string;
}

export interface TotpSetup {
  secret: string;
  provisioning_uri: string;
  qr_code_data_uri: string;
}

/** Der Server verlangt den zweiten Faktor – nicht: die Anmeldung ist gescheitert. */
export class TotpRequired extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TotpRequired";
  }
}

/**
 * Liest die Fehlermeldung des Backends aus einer Axios-Ausnahme.
 *
 * Das Backend liefert Meldungen, die für Anwender geschrieben sind – die will
 * man zeigen und nicht durch ein generisches "Etwas ist schiefgelaufen"
 * ersetzen. Nur wenn keine da ist, greift der Rückfalltext.
 */
export function errorMessage(error: unknown, fallback: string): string {
  const detail = (error as AxiosError<{ detail?: unknown }>)?.response?.data?.detail;

  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }

  return fallback;
}

function isTotpChallenge(error: unknown): boolean {
  const detail = (error as AxiosError<{ detail?: unknown }>)?.response?.data?.detail;

  return Boolean(
    detail && typeof detail === "object" && (detail as { totp_required?: boolean }).totp_required,
  );
}

// --------------------------------------------------------------------------
// Anmeldung
// --------------------------------------------------------------------------

export interface LoginInput {
  username: string;
  password: string;
  totp_code?: string;
  recovery_code?: string;
}

export async function login(input: LoginInput): Promise<CurrentUser> {
  try {
    const { data } = await http.post<CurrentUser>("/auth/login", input);
    return data;
  } catch (error) {
    if (isTotpChallenge(error)) {
      throw new TotpRequired(errorMessage(error, "Bitte den Code aus der App eingeben."));
    }
    throw error;
  }
}

export async function logout(): Promise<void> {
  await http.post("/auth/logout");
}

/** `null`, wenn niemand angemeldet ist – 401 ist hier eine Antwort, kein Fehler. */
export async function fetchMe(): Promise<CurrentUser | null> {
  try {
    const { data } = await http.get<CurrentUser>("/auth/me");
    return data;
  } catch (error) {
    if ((error as AxiosError)?.response?.status === 401) return null;
    throw error;
  }
}

// --------------------------------------------------------------------------
// Eigenes Konto
// --------------------------------------------------------------------------

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await http.post("/auth/password", {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export async function fetchSessions(): Promise<SessionInfo[]> {
  const { data } = await http.get<SessionInfo[]>("/auth/sessions");
  return data;
}

export async function revokeSession(id: string): Promise<SessionInfo[]> {
  const { data } = await http.delete<SessionInfo[]>(`/auth/sessions/${id}`);
  return data;
}

export async function revokeOtherSessions(): Promise<SessionInfo[]> {
  const { data } = await http.post<SessionInfo[]>("/auth/sessions/revoke-others");
  return data;
}

// --------------------------------------------------------------------------
// Zweiter Faktor
// --------------------------------------------------------------------------

export async function startTotpSetup(): Promise<TotpSetup> {
  const { data } = await http.post<TotpSetup>("/auth/totp/setup");
  return data;
}

export async function confirmTotpSetup(
  secret: string,
  code: string,
  currentPassword: string,
): Promise<string[]> {
  const { data } = await http.post<{ recovery_codes: string[] }>("/auth/totp/confirm", {
    secret,
    code,
    current_password: currentPassword,
  });
  return data.recovery_codes;
}

export async function disableTotp(currentPassword: string): Promise<void> {
  // Das Backend nimmt hier `PasswordChangeRequest` entgegen und liest nur das
  // aktuelle Passwort; `new_password` ist Pflichtfeld des Schemas.
  await http.post("/auth/totp/disable", {
    current_password: currentPassword,
    new_password: "",
  });
}

// --------------------------------------------------------------------------
// Kontenverwaltung (nur Administratoren)
// --------------------------------------------------------------------------

export async function fetchPageCatalogue(): Promise<PageId[]> {
  const { data } = await http.get<PageId[]>("/auth/pages");
  return data;
}

export async function fetchUsers(): Promise<UserSummary[]> {
  const { data } = await http.get<UserSummary[]>("/auth/users");
  return data;
}

export async function createUser(
  username: string,
  isAdmin: boolean,
  pages: PageId[],
): Promise<CreatedUser> {
  const { data } = await http.post<CreatedUser>("/auth/users", {
    username,
    is_admin: isAdmin,
    pages,
  });
  return data;
}

export async function updateUser(
  id: string,
  changes: { username?: string; is_admin?: boolean; active?: boolean },
): Promise<UserSummary> {
  const { data } = await http.patch<UserSummary>(`/auth/users/${id}`, changes);
  return data;
}

export async function setUserPages(id: string, pages: PageId[]): Promise<UserSummary> {
  const { data } = await http.put<UserSummary>(`/auth/users/${id}/pages`, { pages });
  return data;
}

export async function resetUserPassword(
  id: string,
): Promise<{ user: UserSummary; initial_password: string }> {
  const { data } = await http.post<{ user: UserSummary; initial_password: string }>(
    `/auth/users/${id}/password`,
  );
  return data;
}

export async function resetUserTotp(id: string): Promise<UserSummary> {
  const { data } = await http.post<UserSummary>(`/auth/users/${id}/totp/reset`);
  return data;
}

export async function revokeUserSessions(id: string): Promise<UserSummary> {
  const { data } = await http.post<UserSummary>(`/auth/users/${id}/sessions/revoke`);
  return data;
}

export async function deleteUser(id: string): Promise<void> {
  await http.delete(`/auth/users/${id}`);
}
