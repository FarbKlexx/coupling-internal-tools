import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import pluginVue from "eslint-plugin-vue";
import { defineConfig } from "eslint/config";

export default defineConfig([
  {
    // Der Build-Output ist minifiziertes Fremdmaterial - ohne dieses Ignore
    // meldet `eslint .` rund 2000 Fehler aus dist/ und ist als CI-Gate
    // unbrauchbar. node_modules ist in der Flat-Config schon per Default aus.
    ignores: ["dist/**", "coverage/**"],
  },
  {
    files: ["**/*.{js,mjs,cjs,ts,mts,cts,vue}"],
    plugins: { js },
    extends: ["js/recommended"],
    languageOptions: { globals: globals.browser },
  },
  tseslint.configs.recommended,
  pluginVue.configs["flat/essential"],
  { files: ["**/*.vue"], languageOptions: { parserOptions: { parser: tseslint.parser } } },
]);
