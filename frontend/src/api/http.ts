import axios from "axios";

export const http = axios.create({
  baseURL: "http://localhost:8000",
  timeout: 60_000,
});
