import axios from "axios";

export const http = axios.create({
  //baseURL: "http://localhost:8000",
  baseURL: "/api",
  timeout: 60_000,
});

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
