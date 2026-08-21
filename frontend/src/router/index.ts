// src/router/index.ts
import { createRouter, createWebHistory } from "vue-router";

import DashboardView from "@/views/DashboardView.vue";
import AbgleicheView from "@/views/AbgleicheView.vue";
import AwinBannerView from "@/views/AwinBannerView.vue";
import WebpConverterView from "@/views/WebpConverterView.vue";
import QrCodeView from "@/views/QrCodeView.vue";
import PdfProtectView from "@/views/PdfProtectView.vue";
import KanbanView from "@/views/KanbanView.vue";

const routes = [
  // Die Dashboard-Seite ist noch ein Stub und deshalb weder in der Sidebar
  // noch in der Suche sichtbar. Route bleibt erhalten, /dashboard ist direkt
  // aufrufbar.
  {
    path: "/dashboard",
    name: "dashboard",
    component: DashboardView,
    meta: {
      searchable: false,
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
    path: "/qr-code",
    name: "qr-code",
    component: QrCodeView,
    meta: {
      searchable: true,
      label: "QR-Code Generator",
      icon: "qr_code_2",
      keywords: ["qr", "qr-code", "link", "png", "svg", "generator"],
    },
  },
  {
    path: "/pdf-schutz",
    name: "pdf-schutz",
    component: PdfProtectView,
    meta: {
      searchable: true,
      label: "PDF Passwortschutz",
      icon: "lock",
      keywords: ["pdf", "passwort", "schutz", "verschluesseln", "sichern", "aes"],
    },
  },
  {
    path: "/kanban",
    name: "kanban",
    component: KanbanView,
    meta: {
      searchable: true,
      label: "Kanban Board",
      icon: "view_kanban",
      keywords: ["kanban", "board", "aufgaben", "todo", "tasks", "karten", "kunden"],
    },
  },
  {
    path: "/",
    redirect: "/abgleiche",
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});
