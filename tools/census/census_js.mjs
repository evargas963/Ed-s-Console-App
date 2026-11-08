// What the page does with numbers, read by a real parser (acorn), one JSON line per finding.
// Usage: node census_js.mjs <file>...   Each line: {"file","line","kind","text"}.
// kind: value-arithmetic | layout-arithmetic | value-compare | math-call
import { readFileSync } from "node:fs";
import * as acorn from "acorn";
import * as walk from "acorn-walk";

const ARITH = new Set(["-", "*", "/", "%", "**", "+"]);
const COMPARE = new Set(["<", "<=", ">", ">="]);
// names that place things on the screen: pixels, sizes, positions, counts of rows and columns
const LAYOUT =
  /^(x|y|x0|x1|y0|y1|dx|dy|w|h|cx|cy|r|R|px|pad|gap|margin|left|right|top|bottom|width|height|offset\w*|client\w*|page[XY]|scroll\w*|inner\w*|outer\w*|rect|bbox|box|canvas|ctx|row\w*|col\w*|cell\w*|line\w*|i|j|k|n|idx|index|len|length|count|step|frame|tick|zoom|scale|dpr|devicePixelRatio|font\w*|size|half|mid|center|centre|span|lane\w*|bar\w*|strip\w*|callout\w*|CALLOUT_\w*|ROW\w*|PAD\w*|GAP\w*|H|W|stage\w*|depth|level\w*Px|\w*Px|\w*Width|\w*Height|\w*Top|\w*Left|\w*X|\w*Y|\w*Row\w*|\w*Col\w*)$/;

function names(node, out = []) {
  walk.full(node, (n) => {
    if (n.type === "Identifier") out.push(n.name);
    if (n.type === "MemberExpression" && n.property.type === "Identifier")
      out.push(n.property.name);
  });
  return out;
}

function isString(n) {
  if (!n) return false;
  if (n.type === "Literal") return typeof n.value === "string";
  if (n.type === "TemplateLiteral") return true;
  if (n.type === "BinaryExpression" && n.operator === "+")
    return isString(n.left) || isString(n.right);
  if (
    n.type === "CallExpression" &&
    n.callee.type === "MemberExpression" &&
    [
      "join",
      "toFixed",
      "toString",
      "toLocaleString",
      "replace",
      "slice",
      "trim",
      "padStart",
    ].includes(n.callee.property.name)
  )
    return true;
  if (
    n.type === "CallExpression" &&
    n.callee.type === "Identifier" &&
    /^(esc|fmt|num|money|price|pct|label|html|cls|txt|text)/i.test(
      n.callee.name,
    )
  )
    return true;
  return false;
}

for (const file of process.argv.slice(2)) {
  const src = readFileSync(file, "utf8");
  const lines = src.split("\n");
  // a page .js file is a browser script, a .mjs file a module; one that does not parse stops
  // the census with acorn's error
  const ast = acorn.parse(src, {
    ecmaVersion: "latest",
    sourceType: file.endsWith(".mjs") ? "module" : "script",
    locations: true,
  });
  const seen = new Set();
  const emit = (node, kind) => {
    const line = node.loc.start.line;
    const key = `${line}:${kind}`;
    if (seen.has(key)) return;
    seen.add(key);
    console.log(
      JSON.stringify({
        file,
        line,
        kind,
        text: lines[line - 1].trim().slice(0, 150),
      }),
    );
  };
  walk.full(ast, (n) => {
    if (n.type === "BinaryExpression" && ARITH.has(n.operator)) {
      if (n.operator === "+" && (isString(n.left) || isString(n.right))) return;
      const ids = names(n);
      emit(
        n,
        ids.length &&
          ids.every(
            (x) =>
              LAYOUT.test(x) ||
              x === "Math" ||
              /^(min|max|abs|round|floor|ceil)$/.test(x),
          )
          ? "layout-arithmetic"
          : "value-arithmetic",
      );
    } else if (n.type === "BinaryExpression" && COMPARE.has(n.operator)) {
      const ids = names(n);
      if (!(ids.length && ids.every((x) => LAYOUT.test(x))))
        emit(n, "value-compare");
    } else if (
      n.type === "AssignmentExpression" &&
      ["+=", "-=", "*=", "/="].includes(n.operator)
    ) {
      if (isString(n.right)) return;
      const ids = names(n);
      emit(
        n,
        ids.every((x) => LAYOUT.test(x))
          ? "layout-arithmetic"
          : "value-arithmetic",
      );
    } else if (
      n.type === "CallExpression" &&
      n.callee.type === "MemberExpression" &&
      n.callee.object.type === "Identifier" &&
      n.callee.object.name === "Math"
    ) {
      emit(n, "math-call");
    }
  });
}
