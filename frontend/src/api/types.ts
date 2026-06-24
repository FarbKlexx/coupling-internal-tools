export type UploadOption = "jf_to_awin" | "jf_bonus" | "awin_to_jf";

export interface UploadResponse {
  blob: Blob;
  filename: string;
}
