// src/router/index.ts
import { createRouter, createWebHistory } from "vue-router";

import DashboardView from "@/views/DashboardView.vue";
import AbgleicheView from "@/views/AbgleicheView.vue";
import AwinBannerView from "@/views/AwinBannerView.vue";
import WebpConverterView from "@/views/WebpConverterView.vue";

const routes = [
  {
    path: "/dashboard",
    name: "dashboard",
    component: DashboardView,
    meta: {
      searchable: true,
      label: "Dashboard",
      icon: "home",
      keywords: ["home", "overview"],
    },
  },
  {
    path: "/abgleiche",
    name: "abgleiche",
    component: AbgleicheView,
    meta: {
      searchable: true,
      label: "Abgleiche",
      icon: "table",
      keywords: ["awin", "vergleich", "csv"],
    },
  },
  {
    path: "/awin-banner",
    name: "awin-banner",
    component: AwinBannerView,
    meta: {
      searchable: true,
      label: "AWIN Banner CSV",
      icon: "image",
      keywords: ["awin", "banner", "csv", "mass upload"],
    },
  },
  {
    path: "/webp-konverter",
    name: "webp-konverter",
    component: WebpConverterView,
    meta: {
      searchable: true,
      label: "WebP Konverter",
      icon: "compress",
      keywords: [
        "bild",
        "bilder",
        "image",
        "webp",
        "konvertieren",
        "jpg",
        "png",
        "heic",
        "komprimieren",
      ],
    },
  },
  {
    path: "/",
    redirect: "/dashboard",
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});
