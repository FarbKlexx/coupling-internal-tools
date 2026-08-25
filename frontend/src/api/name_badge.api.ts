import { filenameFromDisposition, http } from "./http";
import type { UploadResponse } from "./types";

/**
 * Namensschilder: CSV hochladen, Trockenlauf lesen, druckfertiges PDF holen.
 *
 * Die Bogengeometrie kommt vollständig aus dem Backend (`/name-badges/formats`)
 * und wird hier **nicht** nachgebaut: das Kartenraster im UI zeichnet sich aus
 * diesen Daten, ein weiteres Bogenformat ist deshalb reine Backend-Sache.
 */

export interface BadgeLayoutField {
  field: string;
  label: string;
  baseline_mm: number;
  size_pt: number;
  min_size_pt: number;
  bold: boolean;
  align: string;
}

export interface BadgeSheetFormat {
  id: string;
  label: string;
  sheet_width_mm: number;
  sheet_height_mm: number;
  columns: number;
  rows: number;
  slots_per_sheet: number;
  card_width_mm: number;
  card_height_mm: number;
  margin_left_mm: number;
  margin_right_mm: number;
  margin_top_mm: number;
  margin_bottom_mm: number;
  gap_x_mm: number;
  gap_y_mm: number;
  safety_mm: number;
  fields: BadgeLayoutField[];
}

export interface BadgeFormatsResponse {
  formats: BadgeSheetFormat[];
  default_format: string;
  max_offset_mm: number;
  max_rows: number;
  max_file_bytes: number;
}

export interface BadgeColumnMapping {
  field: string;
  label: string;
  column: string;
  empty_count: number;
}

export interface BadgeSkippedRow {
  line: number;
  reason: string;
}

export interface BadgeAnalysis {
  format: string;
  start_slot: number;
  records: number;
  sheets: number;
  data_rows: number;
  encoding: string;
  delimiter: string;
  mapping: BadgeColumnMapping[];
  missing_fields: string[];
  ignored_columns: string[];
  skipped_rows: BadgeSkippedRow[];
  warnings: string[];
}

/** Einstellungen, die Trockenlauf und Druck teilen. */
export interface BadgeOptions {
  format: string;
  start_slot: number;
  offset_x_mm: number;
  offset_y_mm: number;
  draw_outlines: boolean;
}

export interface BadgePdfResponse extends UploadResponse {
  /** Anzahl der Bögen, aus dem Antwort-Header – ohne das PDF zu parsen. */
  sheets: number;
}

/** Bogenformate samt Kartenlayout. Ändert sich zur Laufzeit nicht. */
export async function fetchBadgeFormats(): Promise<BadgeFormatsResponse> {
  const response = await http.get<BadgeFormatsResponse>("/name-badges/formats");
  return response.data;
}

/**
 * Trockenlauf: liest die Datei ein und berichtet, was der Druck ergäbe –
 * ohne ein PDF zu erzeugen.
 */
export async function analyseBadgeCsv(
  file: File,
  options: Pick<BadgeOptions, "format" | "start_slot">,
  signal?: AbortSignal,
): Promise<BadgeAnalysis> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("format", options.format);
  formData.append("start_slot", String(options.start_slot));

  const response = await http.post<BadgeAnalysis>("/name-badges/analyse", formData, { signal });
  return response.data;
}

/** Druckfertiger Bogensatz. Dasselbe Blob dient als Vorschau und als Download. */
export async function createBadgePdf(
  file: File,
  options: BadgeOptions,
  signal?: AbortSignal,
): Promise<BadgePdfResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("format", options.format);
  formData.append("start_slot", String(options.start_slot));
  formData.append("offset_x_mm", String(options.offset_x_mm));
  formData.append("offset_y_mm", String(options.offset_y_mm));
  formData.append("draw_outlines", String(options.draw_outlines));

  const response = await http.post("/name-badges", formData, {
    responseType: "blob",
    signal,
  });

  return {
    blob: response.data,
    filename: filenameFromDisposition(
      response.headers["content-disposition"],
      "namensschilder.pdf",
    ),
    sheets: Number(response.headers["x-sheet-count"] ?? 0),
  };
}

/** Kalibrierbogen zum Einmessen des Druckerversatzes – braucht keine Daten. */
export async function createCalibrationPdf(
  format: string,
  offsetXMm: number,
  offsetYMm: number,
): Promise<UploadResponse> {
  const response = await http.post(
    "/name-badges/calibration",
    { format, offset_x_mm: offsetXMm, offset_y_mm: offsetYMm },
    { responseType: "blob" },
  );

  return {
    blob: response.data,
    filename: filenameFromDisposition(
      response.headers["content-disposition"],
      "kalibrierbogen.pdf",
    ),
  };
}
