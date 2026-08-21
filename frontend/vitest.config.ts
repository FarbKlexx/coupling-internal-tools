import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config";

// Eigene Datei statt eines `test`-Blocks in vite.config.ts: die Build-Config
// bleibt damit unangetastet und braucht keinen Import aus vitest.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      // Fuer das Mounten von Komponenten. Die Tests brauchen weder Netzwerk
      // noch Backend - der CI-Runner hat beides nicht.
      environment: "jsdom",
      include: ["src/**/*.test.ts"],
      restoreMocks: true,
    },
  }),
);
