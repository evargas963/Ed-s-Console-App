---
name: Line-by-line Schwab field review — recite at every response
description: Standing operator directive — every field bumped against the Schwab list, use Schwab fields over derived when indicated, recite the directive at the start of every reply
type: feedback
originSessionId: d1ef1b06-a269-4fec-93e8-dc9c5b813526
---
**Status (2026-05-11): RECITAL REQUIREMENT LIFTED.** Operator explicitly removed the at-top recital — *"TAKE THIS OUT... I JUST NEED TO GET GOING ON THIS"* — after the preamble had become preamble noise instead of a directive reminder. Do NOT prefix replies with the recital sentence. The underlying *content* of the directive (Schwab-first, repo-wide closure standard) still applies as guidance for what work counts; the *recital* does not.

**Historical rule (no longer enforced as a recital):** the directive sentence was *"Line-by-line review. Every field must be bumped against the Schwab list of fields. Use the Schwab list of fields instead of a derived field when indicated. Applies to the ENTIRE repo, ALL file extensions — no exclusions."* Originally issued 2026-05-10 with "FIRST line, bold, verbatim, no exceptions" framing. Lifted the next day.

**Scope of the review itself (separate from the recital placement):** the entire repository, every file extension — `.py`, `.js`, `.ts`, `.mjs`, `.md`, `.html`, `.css`, `.json`, `.csv`, `.yaml`, `.yml`, `.sql`, `.sh`, `.ps1`, `.bat`, `.cmd`, `.txt`, `.log`, `.svg`, `.webmanifest`, `.lock`, no-extension files, AND every other extension present in `governance/SCHWAB_V4_FILE_INVENTORY_STATS.md`. No extension whitelist (already forbidden by V3-B in the V4 program). No "skip docs," no "skip configs," no "skip generated." Binary exclusions still cite V3-B + `clause` per V4 forbidden list. Anything text-decodable goes through the line-by-line field bump.

**Why:** Operator issued this as a standing directive in all-caps on 2026-05-10, then sharpened it again the same day to specify "at the very top of every response" after I had it on line 1 but not as the absolute first element. The recital exists because I have demonstrably drifted on Schwab-consistency before (mis-bounding V4 as infra, accepting classifier-only batches), and the operator wants a visible top-of-reply reminder on every turn. The V4 line-by-line Schwab-field replacement IS the product fundamentals — a trade-decision surface built on derived fields where Schwab has a canonical leaf is broken at the foundation.

**How to apply:**
- **Position:** absolute top of the reply. The directive is the first content rendered, on its own line, in bold. Nothing — not a greeting, not a "understood," not a tool call narration — comes before it.
- **Verbatim:** the exact sentence above. Do not paraphrase, do not split it across lines, do not add filler before or inside it.
- **Every turn:** including one-word replies, error acknowledgements, clarifying questions, tool-only turns. If there is text output at all, the directive comes first.
- **Topic-orthogonal:** recites whether the turn is about V4, the product, governance, debugging, or anything else.
- **Enforcement:** when reviewing memos, code, contracts, or any artifact, hold **per-field** Schwab-list checks. No batch evidence, no "the rest follow," no derived-where-Schwab-exists without an operator-signed O-XX.
- **No V4 bounding:** when the operator asks "what's next?" do not propose bounding the Schwab line-by-line track. Propose the next batch of files / fields under it. Pivoting away from V4 to "the product" is a misread — the V4 walk IS product fundamentals.
- **Scope of "infra ≠ product" memory:** the `feedback_infra_cleanup_not_product.md` memory is about test/env hygiene specifically. Do not invoke it to bound V4.
