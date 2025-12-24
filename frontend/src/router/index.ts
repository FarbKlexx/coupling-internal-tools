// src/router/index.ts
import { createRouter, createWebHistory } from "vue-router";

import DashboardView from "@/views/DashboardView.vue";
import AbgleicheView from "@/views/AbgleicheView.vue";

const routes = [
  {
    path: "/dashboard",
    name: "dashboard",
    component: DashboardView,
  },
  {
    path: "/abgleiche",
    name: "abgleiche",
    component: AbgleicheView,
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
