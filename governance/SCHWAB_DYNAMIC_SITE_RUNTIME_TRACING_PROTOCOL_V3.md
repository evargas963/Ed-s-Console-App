> **Classification:** Policy Specification | **Scope:** Governance documentation `SCHWAB_DYNAMIC_SITE_RUNTIME_TRACING_PROTOCOL_V3.md`.

# Schwab dynamic-site runtime tracing protocol (V3-D / Deliverable 15)

**Status:** Protocol definition — instrumentation may ship after scanner; disposition may use static allow-list or refactor instead.  
**Contract:** `SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md` (active program, LOCKED 2026-05-08); the V3-D dynamic-site resolution semantics described here are **inherited by V4 unchanged**. The historical pointer was `SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V3.md` § V3-D resolution path 2.

## Purpose

For register rows whose `pattern_kind` appears in `tools/schwab_universal_coverage_scanner_v3/V3_DYNAMIC_PATTERNS.md`, when static allow-list disposition is insufficient, operators may **prove** which canonical fields flow through the site using **runtime evidence**.

## What gets logged

1. **Register pointer:** `register_id` of the row under review.  
2. **Resolved key / name:** string value observed at the dynamic boundary (e.g. attribute name, `Reflect` key, SQL fragment token).  
3. **UTC timestamp** and **process / service identifier** (e.g. `server`, `worker`, `replay_job`).  
4. **Source frame** (optional): one-line caller location if available from stack or structured logging.

## Where it is stored

- **Primary:** append-only **JSONL** or **structured log** file under a path recorded in the closure audit (e.g. `logs/schwab_v3_dynamic_trace.jsonl`), **or**  
- **Linked artifact:** same schema exported from APM (Datadog, etc.) with **stable query** cited in the register row `notes` / `governed_ref`.

## How it links to the register

1. Tracing run produces lines keyed by `register_id`.  
2. During disposition, operator attaches **evidence digest** (file hash or log query ID) to the row.  
3. Closure audit lists **every** V3-D row using path 2 with **evidence citation**.

## Privacy / safety

- Log **only** field names / keys that are already in the Schwab dictionary vocabulary or explicitly allow-listed; redact unrelated PII.  
- Retention and access control match production log policy; gatekeeper may reject traces that broaden scope beyond the cited register row.

## Revision

Changes to this protocol require operator + gatekeeper acknowledgment (same bar as `V3_DYNAMIC_PATTERNS.md` edits for tracing semantics).
