// ESLint's recommended rules over every JavaScript file the repository tracks (run on the commit
// copy in lint/head). The page's scripts are browser scripts; .mjs, tests and tooling are Node modules.
import js from "@eslint/js";
import globals from "globals";

export default [
  { ignores: ["**/static/vendor/**", "**/node_modules/**"] },
  js.configs.recommended,
  {
    files: ["**/static/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "script",
      globals: { ...globals.browser },
    },
  },
  {
    files: [
      "**/*.mjs",
      "**/tests/**/*.js",
      "**/scripts/**/*.js",
      "**/*.config.{js,mjs,cjs}",
    ],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...globals.node, ...globals.browser },
    },
  },
];
