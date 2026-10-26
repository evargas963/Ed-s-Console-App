// The syntax tree of one page-code file, comments and positions set aside, as one line of JSON on
// stdout (tools/check_end_to_end.py code_identical). Parsed by Babel, the parser Playwright already
// installs. A file Babel cannot parse exits 1, which code_identical counts as a change.
//   node tools/js_code_tree.js <file>
'use strict';
const fs = require('fs');
const path = require('path');
const { babelParse } = require(path.join(__dirname, '..', 'node_modules', 'playwright', 'lib', 'transform',
  'babelBundleImpl.js'));

const SET_ASIDE = new Set(['start', 'end', 'loc', 'range', 'comments', 'leadingComments', 'trailingComments',
  'innerComments', 'tokens', 'parenStart', 'trailingComma']);

const file = process.argv[2];
const tree = babelParse(fs.readFileSync(file, 'utf8'), file, file.endsWith('.mjs'));
process.stdout.write(JSON.stringify(tree.program, (key, value) => (SET_ASIDE.has(key) ? undefined : value)));
