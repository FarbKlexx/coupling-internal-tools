// src/router/index.ts
import { createRouter, createWebHistory } from "vue-router";

import DashboardView from "@/views/DashboardView.vue";
import AbgleicheView from "@/views/AbgleicheView.vue";

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
    path: "/",
    redirect: "/dashboard",
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});
