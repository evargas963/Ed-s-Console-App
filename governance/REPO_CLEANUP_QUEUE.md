# Repo Cleanup Queue

**Status:** Open cleanup queue  
**Created:** 2026-05-06  
**Policy reference:** `governance/ENGINEERING_GATEKEEPING_POLICY.md`

---

## Purpose

This queue tracks dead-code, stale-doc, temporary-artifact, and bloat candidates that should not be removed blindly during unrelated work. Entries here require disposition: remove, archive, retain with rationale, or defer with owner/trigger.

Queue entries should be added when cleanup is identified but not safely in scope for the current commit.

---

## Entry Schema

```text
file_path
why_flagged
date_flagged
recommended_resolution
status
notes
```

Valid statuses:

```text
open
needs_operator_disposition
resolved
retained_with_rationale
archived
```

---

## Open Items

| File path | Why flagged | Date flagged | Recommended resolution | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `governance/INSTITUTIONAL_STANDARD_WISHLIST.md` | V1 institutional standard wishlist appears superseded by later institutional standard governance. | 2026-05-06 | Move to `governance/archive/` if no live references or operator retention need exists. | open | Verify references before moving. |
| `governance/INSTITUTIONAL_STANDARD_V2.md` | Superseded by `governance/INSTITUTIONAL_STANDARD_V3.md` / V3.1-era governance. | 2026-05-06 | Move to `governance/archive/` if no live references or operator retention need exists. | open | Verify references before moving. |
| `governance/V3_CONFORMANCE_AUDIT_TEMPLATE.md` | Template appears redundant with completed `governance/V3_CONFORMANCE_AUDIT.md`. | 2026-05-06 | Move to `governance/archive/` or retain with explicit template reuse rationale. | open | Verify whether future audits still use the template. |
| Dirty working tree files | Current working tree contains many modified and untracked files outside the v2 calibration commits. | 2026-05-06 | Separate operator disposition pass: keep, commit by topic, archive, or discard only with explicit approval. | needs_operator_disposition | Not a cleanup queue deletion item. Do not revert or remove without operator approval. |

---

## Resolution Log

No entries resolved yet.
