> **Classification:** Policy Specification | **Scope:** Repository documentation `tools/schwab_universal_coverage_scanner_v3/V3_DYNAMIC_PATTERNS.md`.

# V3-D dynamic-pattern enumeration (normative)

**Authority:** `SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V3.md` § V3-D. **Edits require gatekeeper review** (same bar as contract changes). Each removal or modification triggers re-disposition of affected register rows.

| pattern_kind | Runtime-resolution risk (one line) | Clause |
|--------------|-----------------------------------|--------|
| DYNAMIC_DISPATCH | `__getattr__` / `__setattr__` may resolve arbitrary attribute names at runtime. | V3-D |
| PYTHON_GETATTR_SETATTR | `getattr` / `setattr` with dynamic name argument. | V3-D |
| DYNAMIC_EVAL | `eval` executes arbitrary code; field access is opaque to static analysis. | V3-D |
| COMPUTED_PROPERTY | JS/TS `obj[expr]` where property key is not a compile-time literal. | V3-D |
| PROXY_TRAP | `Proxy` traps can intercept and remap property access dynamically. | V3-D |
| REFLECT_API | `Reflect.get` / `set` / `has` / `ownKeys` use runtime property keys. | V3-D |
| COMPUTED_DEFINE_PROPERTY | `Object.defineProperty(ies)` with non-literal property key. | V3-D |
| DYNAMIC_IMPORT | `import(expr)` resolves module path at runtime. | V3-D |
| REGISTRY_DISPATCH | String-keyed object / registry may route to handlers by dynamic key. | V3-D |
| DYNAMIC_SQL_BUILD | SQL built with concatenation/format; column names may be runtime-derived. | V3-D |
| pattern_kind_miss | Cross-validator found vocabulary on a line not covered by primary AST/parser. | V3-D |

**Note:** Rows with other `pattern_kind` values are not V3-D dynamic-site rows unless this table is amended.
