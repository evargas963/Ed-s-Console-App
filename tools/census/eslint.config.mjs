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
  // AGENTS.md rule 4: the page reaches the program only through its transport (ed-core.js: the
  // socket and EdShell.request)
  {
    files: ["**/static/**/*.js"],
    ignores: ["**/static/js/ed-core.js"],
    rules: {
      "no-restricted-globals": [
        "error",
        ...["fetch", "XMLHttpRequest", "EventSource"].map((name) => ({
          name,
          message: "the page's one transport is ed-core.js (EdShell.request)",
        })),
      ],
    },
  },
  {
    files: ["**/*.mjs", "**/tests/**/*.js", "**/scripts/**/*.js", "**/*.config.{js,mjs,cjs}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...globals.node, ...globals.browser },
    },
  },
];
