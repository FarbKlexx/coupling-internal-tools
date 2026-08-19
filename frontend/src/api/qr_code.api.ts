import { filenameFromDisposition, http } from "./http";
import type { UploadResponse } from "./types";

export type QrCodeFormat = "png" | "svg";

export interface QrCodeRequest {
  data: string;
  format: QrCodeFormat;
  transparent: boolean;
  /** Ruhezone von 4 Modulen rund um den Code. Aus = randlos. */
  quiet_zone: boolean;
}

/**
 * Erzeugt den QR-Code zu einem Link (oder beliebigem Text).
 * Dieselbe Antwort wird sowohl für die Vorschau als auch für den Download benutzt.
 */
export async function generateQrCode(payload: QrCodeRequest): Promise<UploadResponse> {
  const response = await http.post("/qr-code", payload, {
    responseType: "blob",
  });

  return {
    blob: response.data,
    filename: filenameFromDisposition(
      response.headers["content-disposition"],
      `qr-code.${payload.format}`,
    ),
  };
}
