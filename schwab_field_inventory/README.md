> **Classification:** Policy Specification | **Scope:** Schwab field inventory reference; refresh on CHANGELOG or quarterly.

# Schwab Field Inventory

**Capture date:** 2026-05-05  
**Capture source:** live Schwab Trader API market-data probes after local OAuth re-authentication  
**Canonical field count:** 2,393  
**Raw field paths observed:** 468,039

---

## Tracked Files

This directory intentionally tracks only the curated, diffable Schwab field references:

```text
schwab_canonical_fields.txt
schwab_field_dictionary.csv
schwab_field_dictionary_grouped.csv
README.md
```

These files are the versioned data-plane reference cited by:

```text
docs/SCHWAB_FIELD_REFERENCE.md
docs/FIELD_SOURCE_AUDIT.md
docs/SCHWAB_FIELD_NORMALIZATION_AUDIT.md
(retired under ED CONSOLE SLIMMING)
```

---

## Ignored Generated Files

The raw endpoint payloads, per-endpoint field dumps, `schwab_all_fields_master.txt`, and `schwab_field_inventory_summary.csv` are generated build-stage artifacts. They are intentionally gitignored to avoid committing large raw captures while keeping the canonical field dictionary versioned.

---

## Regenerate Procedure

1. Re-authenticate Schwab and refresh `schwab_token.json`.
2. Run:

```text
python schwab_full_field_inventory.py
```

3. Build the canonical dictionary:

```text
python schwab_field_dictionary_builder.py
```

4. Review diffs in the tracked canonical files. Any Schwab field addition, removal, or semantic change should be treated as a data-governance event under the v2.0 data-plane contract.

**Quarterly / CHANGELOG refresh (Phase 2):** Re-run steps 1–4 when Schwab publishes API CHANGELOG updates or at least once per quarter; record the refresh date in this README header.

