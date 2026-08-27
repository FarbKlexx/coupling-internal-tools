import { filenameFromDisposition, http } from "./http";
import type { UploadResponse } from "./types";

export const MIN_QUALITY = 1;
export const MAX_QUALITY = 100;
export const DEFAULT_QUALITY = 80;

/** Auflösung in Prozent der Originalkantenlänge (Spiegel von `image_utils.py`). */
export const MIN_SCALE = 10;
export const MAX_SCALE = 100;
export const DEFAULT_SCALE = 100;
/** Rasterung des Auflösungsreglers — jede Stufe kostet einen Mess-Request. */
export const SCALE_STEP = 5;

/** Bulk-Uploads brauchen deutlich mehr als das 60s-Default-Timeout. */
const LONG_TIMEOUT = 300_000;

export interface ImageConvertResponse extends UploadResponse {
  /** Anzahl der Bilder im ZIP. */
  convertedCount: number;
  /** Anzahl der Dateien, die das Backend nicht konvertieren konnte. */
  skippedCount: number;
}

export interface SizeSample {
  quality: number;
  size: number;
}

export interface FileEstimate {
  filename: string;
  original_size: number;
  supported: boolean;
  samples: SizeSample[];
  /** Auflösung des dekodierten Originals (null, wenn nicht lesbar). */
  width: number | null;
  height: number | null;
  /** Auflösung nach dem Verkleinern — bei 100 % identisch zum Original. */
  scaled_width: number | null;
  scaled_height: number | null;
  error: string | null;
}

interface EstimateResponse {
  qualities: number[];
  /** Auflösung, bei der gemessen wurde. */
  scale: number;
  files: FileEstimate[];
}

/**
 * Lädt beliebig viele Bilder hoch und erhält sie als WebP-ZIP zurück.
 *
 * `scale` verkleinert die Auflösung (Prozent der Kantenlänge, 100 = unverändert)
 * und wird vom Backend *vor* der WebP-Kodierung angewendet; `quality` steuert
 * anschließend den Qualitätsverlust (1 = stark komprimiert, 100 = kaum Verlust).
 */
export async function convertImagesToWebp(
  files: File[],
  quality: number,
  scale: number = DEFAULT_SCALE,
): Promise<ImageConvertResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  formData.append("quality", String(quality));
  formData.append("scale", String(scale));

  const response = await http.post("/convert-images", formData, {
    responseType: "blob",
    timeout: LONG_TIMEOUT,
  });

  return {
    blob: response.data,
    filename: filenameFromDisposition(response.headers["content-disposition"], "webp.zip"),
    convertedCount: Number(response.headers["x-converted-count"] ?? files.length),
    skippedCount: Number(response.headers["x-skipped-count"] ?? 0),
  };
}

/**
 * Misst für jede Datei die WebP-Größe an mehreren Qualitätsstufen — gemessen bei
 * der Auflösung `scale`, denn die Kurve gilt nur für diese eine Auflösung.
 *
 * Die Antwort kommt in derselben Reihenfolge wie die gesendeten Dateien —
 * Dateinamen sind nicht eindeutig, deshalb wird über den Index zugeordnet.
 */
export async function estimateWebpSizes(
  files: File[],
  scale: number = DEFAULT_SCALE,
  signal?: AbortSignal,
): Promise<FileEstimate[]> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  formData.append("scale", String(scale));

  const response = await http.post<EstimateResponse>("/convert-images/estimate", formData, {
    timeout: LONG_TIMEOUT,
    signal,
  });

  return response.data.files;
}

/**
 * Größe für eine beliebige Qualität aus den gemessenen Stützstellen ableiten.
 *
 * Zwischen zwei Stufen wird linear interpoliert (in der Praxis wenige Prozent
 * daneben, auf den Stufen selbst exakt), außerhalb wird der Randwert gehalten.
 * Gilt nur innerhalb einer Auflösung — für eine andere `scale` muss neu
 * gemessen werden.
 */
export function interpolateSize(samples: SizeSample[], quality: number): number | null {
  const sorted = [...samples].sort((a, b) => a.quality - b.quality);
  const first = sorted[0];
  const last = sorted[sorted.length - 1];

  if (!first || !last) return null;
  if (quality <= first.quality) return first.size;
  if (quality >= last.quality) return last.size;

  for (let i = 0; i < sorted.length - 1; i++) {
    const low = sorted[i];
    const high = sorted[i + 1];
    if (!low || !high) continue;

    if (quality >= low.quality && quality <= high.quality) {
      const span = high.quality - low.quality;
      const ratio = span === 0 ? 0 : (quality - low.quality) / span;
      return Math.round(low.size + (high.size - low.size) * ratio);
    }
  }

  return last.size;
}
