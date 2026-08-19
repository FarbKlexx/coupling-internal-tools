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
