import type { RouteRecordRaw } from "vue-router";

export interface RouteSearchItem {
  id: string;
  label: string;
  icon: string;
  path: string;
  keywords?: string[];
}

export function buildRouteSearchIndex(
  routes: RouteRecordRaw[]
): RouteSearchItem[] {
  return routes
    .filter(
      (r) =>
        r.meta?.searchable &&
        typeof r.path === "string" &&
        !r.redirect
    )
    .map((r) => ({
      id: String(r.name ?? r.path),
      label: String(r.meta?.label ?? r.name),
      icon: String(r.meta?.icon),
      path: r.path,
      keywords: r.meta?.keywords,
    }));
}
