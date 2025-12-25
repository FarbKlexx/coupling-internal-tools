import { http } from "./http";
import type { UploadOption, UploadResponse } from "./types";

export async function uploadCsv(file: File, option: UploadOption): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("option", option);

  const response = await http.post("/upload", formData, {
    responseType: "blob",
  });

  // Filename aus Header extrahieren
  const contentDisposition = response.headers["content-disposition"];
  let filename = "download";

  if (contentDisposition) {
    const match = contentDisposition.match(/filename="(.+)"/);
    if (match?.[1]) {
      filename = match[1];
    }
  }

  return {
    blob: response.data,
    filename,
  };
}
