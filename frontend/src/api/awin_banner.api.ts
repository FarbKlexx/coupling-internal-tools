import { http } from "./http";

export interface AwinBannerRequest {
  filenames: string[];
  description: string;
  tag: string;
  target_url: string;
  alt_text: string;
  image_source_stem: string;
}

export async function generateAwinBannerCsv(payload: AwinBannerRequest): Promise<Blob> {
  const response = await http.post("/awin-banner-csv", payload, {
    responseType: "blob",
  });
  return response.data;
}
