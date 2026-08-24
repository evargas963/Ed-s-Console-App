# Retired enforced checks

RC-468 (operator right-sizing mandate, 2026-08-24). The delta gate refuses SILENT removal
of an enforced check (RC-391: deleting the check that fails is not paying the debt). Before
this manifest existed it also refused DELIBERATE removal, which made the enforced set
append-only forever - governance could only grow, never be right-sized.

A removal is legal when, and only when, the same delta ships a row here naming the check.
The gate reads this file from the CANDIDATE tree, so the declaration travels with the
removal and review sees the name and the reason in one place. An undeclared removal still
blocks exactly as before. Rows are append-only history; never delete one.

| check | retired | rationale |
|---|---|---|
