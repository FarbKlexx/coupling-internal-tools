import Fuse from "fuse.js";
import { buildRouteSearchIndex } from "./buildRouteSearchIndex";
import { router } from "@/router";

const routeSearchIndex = buildRouteSearchIndex(router.getRoutes());

const fuse = new Fuse(routeSearchIndex, {
  includeScore: true,
  threshold: 0.4,
  ignoreLocation: true,
  keys: [
    { name: "label", weight: 0.6 },
    { name: "path", weight: 0.2 },
    { name: "keywords", weight: 0.2 },
  ],
});

export function searchRoutes(query: string) {
  if (!query.trim()) return [];
  return fuse.search(query);
}
