import { filenameFromDisposition, http } from "./http";
import type { UploadResponse } from "./types";

/** Grenze des AES-256-Sicherheitshandlers laut PDF-2.0-Spezifikation. */
export const MAX_PASSWORD_BYTES = 127;

/** Lädt ein PDF hoch und erhält es mit Öffnen-Passwort zurück. */
export async function protectPdf(file: File, password: string): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("password", password);

  const response = await http.post("/protect-pdf", formData, {
    responseType: "blob",
    // Große PDFs brauchen mehr als das 60s-Default-Timeout.
    timeout: 300_000,
  });

  return {
    blob: response.data,
    filename: filenameFromDisposition(response.headers["content-disposition"], "geschuetzt.pdf"),
  };
}

// Liegt in der gemeinsamen http-Schicht, weil auch die Namensschilder ihre
// Fehlermeldungen aus Blob-Antworten lesen. Re-Export, damit die bestehenden
// Importe aus diesem Modul unveraendert bleiben.
export { readErrorDetail } from "./http";
