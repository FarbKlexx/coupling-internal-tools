import { filenameFromDisposition, http } from "./http";
import type { UploadOption, UploadResponse } from "./types";

export async function uploadCsv(file: File, option: UploadOption): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("option", option);

  const response = await http.post("/upload", formData, {
    responseType: "blob",
  });

  return {
    blob: response.data,
    // Filename aus Header extrahieren
    filename: filenameFromDisposition(response.headers["content-disposition"]),
  };
}
