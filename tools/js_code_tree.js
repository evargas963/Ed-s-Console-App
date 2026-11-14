// The syntax tree of one page-code file, comments and positions set aside, as one line of JSON on
// stdout (tools/check_end_to_end.py code_identical). Parsed by Babel, the parser Playwright already
// installs. A file Babel cannot parse exits 1, which code_identical counts as a change.
//   node tools/js_code_tree.js <file>
'use strict';
const fs = require('fs');
const path = require('path');
const { babelParse } = require(path.join(__dirname, '..', 'node_modules', 'playwright', 'lib', 'transform',
  'babelBundleImpl.js'));

// `extra` is how a value was spelled, not what it is: a literal's raw text (its quote marks, a
// number's digits as written) and whether it sat in parentheses the grammar did not need.
const SET_ASIDE = new Set(['start', 'end', 'loc', 'range', 'comments', 'leadingComments', 'trailingComments',
  'innerComments', 'tokens', 'parenStart', 'trailingComma', 'extra']);

// A plain (not computed) object key is a property name, text whichever way it is written:
// `options`, 'options' and "options" name one property, as do 1 and '1' (ECMAScript PropertyName).
const KEYED = new Set(['ObjectProperty', 'ObjectMethod', 'ClassProperty', 'ClassMethod']);

function propertyName(key) {
  return { type: 'PropertyName', name: key.type === 'Identifier' ? key.name : String(key.value) };
}

const file = process.argv[2];
const tree = babelParse(fs.readFileSync(file, 'utf8'), file, file.endsWith('.mjs'));
process.stdout.write(JSON.stringify(tree.program, (key, value) => {
  if (SET_ASIDE.has(key)) return undefined;
  if (value && KEYED.has(value.type) && !value.computed && value.key && value.key.type !== 'PrivateName')
    return { ...value, key: propertyName(value.key) };
  return value;
}));
