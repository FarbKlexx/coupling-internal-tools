import axios from "axios";

export const http = axios.create({
  //baseURL: "http://localhost:8000",
  baseURL: "/api",
  timeout: 60_000,
});
