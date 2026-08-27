import axios from "axios";

export const http = axios.create({
  //baseURL: "http://localhost:8000",
  baseURL: "/api",
  timeout: 60_000,
  // Frontend und API sind über nginx same-origin, das Cookie ginge auch ohne
  // mit. Explizit, damit es beim ersten abweichenden Setup nicht still fehlt.
  withCredentials: true,
});

/**
 * Was bei einem 401 passieren soll.
 *
 * Wird von `main.ts` gesetzt, statt hier `@/router` und `useAuth` zu
 * importieren: beide importieren ihrerseits Module, die `http` brauchen, und
 * der Zirkel führt zu einer halb initialisierten Axios-Instanz.
 */
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

/**
 * Abgelaufene Sitzung → einmal aufräumen und zur Anmeldung.
 *
 * Ohne das wird aus dem 10-Sekunden-Poll des Kanban-Boards nach Ablauf der
 * Sitzung ein 401-Sturm. Der Anmeldeaufruf selbst ist ausgenommen: dort ist
 * ein 401 die reguläre Antwort auf falsche Zugangsdaten und darf nicht als
 * "Sitzung abgelaufen" behandelt werden.
 */
http.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status;
    const url: string = error?.config?.url ?? "";

    if (status === 401 && !url.startsWith("/auth/login") && !url.startsWith("/auth/me")) {
      onUnauthorized?.();
    }

    return Promise.reject(error);
  },
);

/** Liest den Dateinamen aus einem Content-Disposition-Header. */
export function filenameFromDisposition(
  contentDisposition: unknown,
  fallback = "download",
): string {
  if (typeof contentDisposition !== "string") return fallback;

  const match = contentDisposition.match(/filename="(.+)"/);
  return match?.[1] ?? fallback;
}

/**
 * Fehlermeldung aus einer Blob-Antwort lesen.
 *
 * Requests mit `responseType: "blob"` bekommen auch das JSON-Fehlerobjekt als
 * Blob geliefert – es muss also erst ausgepackt werden, bevor die Meldung des
 * Backends im UI landen kann.
 */
export async function readErrorDetail(payload: unknown): Promise<string | null> {
  if (!(payload instanceof Blob)) return null;

  try {
    const parsed: unknown = JSON.parse(await payload.text());
    const detail = (parsed as { detail?: unknown })?.detail;
    return typeof detail === "string" ? detail : null;
  } catch {
    return null;
  }
}
