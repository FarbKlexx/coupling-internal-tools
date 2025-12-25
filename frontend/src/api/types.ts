export type UploadOption = "jf_to_awin" | "jf_bonus";

export interface UploadResponse {
  blob: Blob;
  filename: string;
}
