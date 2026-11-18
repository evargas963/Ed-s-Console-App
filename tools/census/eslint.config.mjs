// ESLint's recommended rules over every JavaScript file the repository tracks (run on the commit
// copy in lint/head). The page's scripts are browser scripts; .mjs, tests and tooling are Node modules.
import js from "@eslint/js";
import globals from "globals";

// AGENTS.md rule 4: the page reaches the program only through its transport (ed-core.js: the
// socket and EdShell.request)
const TRANSPORT = ["fetch", "XMLHttpRequest", "EventSource"].map((name) => ({
  name,
  message: "the page's one transport is ed-core.js (EdShell.request)",
}));
// AGENTS.md rule 4: the page reads no clock and formats no time; every time it shows is served
// (time_et.ct_label, ct_ticks), in every page script
const TIME = ["Date", "Intl"].map((name) => ({
  name,
  message: "the page shows the times the program serves (time_et.ct_label, ct_ticks)",
}));
// AGENTS.md rule 4: the page computes no number it shows; its drawing math (where a value is
// placed, how long or dark it is drawn) is the drawing module's (ed-draw.js) and the chart's
// (ed-tv-chart.js), and every other page script draws what is served
const DRAWING = ["**/static/js/ed-draw.js", "**/static/js/ed-tv-chart.js"];
const MATH = [{ name: "Math", message: "drawing math is ed-draw.js's; a shown number is served" }];
const ORDERS = ["sort", "reduce"].map((name) => ({
  selector: `CallExpression[callee.property.name='${name}']`,
  message: `.${name}( on the page: the program serves the rows in order and every total`,
}));

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
    files: ["**/static/**/*.js"],
    ignores: ["**/static/js/ed-core.js", ...DRAWING],
    rules: {
      "no-restricted-globals": ["error", ...TRANSPORT, ...TIME, ...MATH],
      "no-restricted-syntax": ["error", ...ORDERS],
    },
  },
  {
    files: ["**/static/js/ed-core.js"],
    rules: {
      "no-restricted-globals": ["error", ...TIME, ...MATH],
      "no-restricted-syntax": ["error", ...ORDERS],
    },
  },
  {
    files: DRAWING,
    rules: { "no-restricted-globals": ["error", ...TRANSPORT, ...TIME] },
  },
  {
    files: ["**/*.mjs", "**/tests/**/*.js", "**/scripts/**/*.js", "**/*.config.{js,mjs,cjs}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...globals.node, ...globals.browser },
    },
  },
  {
    files: ["**/tools/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "commonjs",
      globals: { ...globals.node },
    },
  },
];
