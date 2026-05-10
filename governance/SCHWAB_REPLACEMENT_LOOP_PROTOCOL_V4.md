# Schwab replacement loop protocol (V4-B) — Deliverable 19

**Authority:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md` § V4-B — **mandatory** between human disposition (sequencing step 4) and stability sweeps (step 6).

---

## Triage — identifying bare `GOVERNED_EXCEPTION` work

1. Run **`python -m tools.schwab_coverage_v4_metrics --register governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv`** and inspect **`bare_governed_exception_count`** and **`v4_a_violations`**.
2. A row is **bare** when **`disposition`** is **`GOVERNED_EXCEPTION`** without the mandated shape **`GOVERNED_EXCEPTION (O-NN)`**, or **`governed_ref`** does not cite **`O-NN`**, or the cited **`O-NN`** lacks a valid **`### O-NN`** narrative in `governance/OPERATOR_DECISION_REGISTER.md` with **`Why:`**, **`Constraint:`**, and **`Permanent or interim:`** (see Deliverable **18**).
3. For each bare row where the **Schwab CSV clearly supplies an equivalent** and **no** documented operator constraint blocks substitution, the **default** action is **refactor to canonical Schwab reference** (not a new **`O-XX`**).

---

## Edit — code-change discipline

- Work in **small slices** (one logical module or concern per pass).
- Run **unit tests** and **scanner tests** (`pytest`) before marking the slice done.
- **Commit messages** should reference affected **`register_id`** values when rows are re-dispositioned or eliminated by refactor.

---

## Rescan

```bash
python -m tools.schwab_universal_coverage_scanner_v3 --output governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv
```

(Use **`--root`** if scanning a non-default tree; default output path is the **V4** register per program Deliverable 4.)

Re-import or merge mechanical scanner output with **human disposition** columns as required by the register schema.

---

## Re-disposition

- Rows whose sites **disappear** after refactor: **drop** or mark **superseded** per closure-audit practice.
- Rows that now reference canonical Schwab fields correctly: **`REPLACED`**.
- Rows that **still** require a non-canonical shape: **`GOVERNED_EXCEPTION (O-NN)`** with matching **`governed_ref`**, and add **`### O-NN`** narrative to **`OPERATOR_DECISION_REGISTER.md`** with the **three mandatory lines**.

---

## When an `O-XX` is acceptable

Use **`GOVERNED_EXCEPTION (O-NN)`** only when **all** hold:

1. **Why:** derived / alternate representation is retained despite a Schwab field existing.  
2. **Constraint:** a concrete trade-off (units, consumer API, latency, precision, etc.).  
3. **Permanent or interim:** if interim, include a **target date** or successor milestone.

The gatekeeper **rejects** boilerplate operator entries missing any of the three elements.

---

## When refactor is required

If a **Schwab equivalent fits** the site and **no** operator-cited **constraint** in a valid **`O-XX`** blocks substitution, the row **must not** close as **`GOVERNED_EXCEPTION`** — **edit code** toward **`REPLACED`** or remove the emission.

---

## Exit

Loop until **`bare_governed_exception_count == 0`** and **`python -m tools.schwab_oxx_validator`** passes on the **V4** register.
