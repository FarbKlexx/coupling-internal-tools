import "vue-router";

declare module "vue-router" {
  interface RouteMeta {
    searchable?: boolean;
    label?: string;
    icon?: string;
    keywords?: string[];
  }
}
