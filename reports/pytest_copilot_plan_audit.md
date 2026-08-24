# Pytest rehab — Copilot plan audit (adversarial)

**Date (UTC):** `2026-08-23`  
**Authority:** Cursor auditor. Operator asked Cursor to execute Copilot’s interrupted pytest rehab.  
**UNIVERSAL:** this is a repo-wide pytest-infrastructure audit, not a single-ticker completeness claim.  
**OUT-OF-SCOPE:** Collect / Chart / Decide product completeness; no weekday-named next-RTH proof; no Architecture A merge-boundary work.

Reproduce:

```bash
find tests/ -name "test_*.py" | wc -l
find tests/ -name "test_v1_*.py" | wc -l
test -f pytest.ini; echo $?
test -f Makefile; echo $?
python3 -c "import tomllib; print(list(tomllib.load(open('pyproject.toml','rb')).get('tool',{}).keys()))"
.venv/bin/python -c "from tools.dead_tests_audit_v1 import scan; import json; print(json.dumps(scan()['counts'], indent=2))"
find tests -name '*fail_closed*.py' | wc -l
rg -n --glob '!**/__pycache__/**' --glob '*.py' 'pytest.mark\.' tests | sed 's/.*pytest.mark.//' | sed 's/(.*//' | sort | uniq -c | sort -nr
```

Inventory of record: `reports/pytest_infrastructure_audit.md`.

This file is the verdict on Copilot’s plan. It is not a second inventory dump.

---

## Operator question: can you fix these tests? Y/N

**Y** for the real infrastructure gap: one pytest config surface, keep the existing required `pytest-full` command, document the real entrypoints.

**N** for Copilot’s plan as written. Executing it would add files, invent a directory tree that does not exist, set a 30-second timeout that the full suite cannot meet, and rename/move hundreds of lock tests without a measured duplicate set.

**N** for mass `tests/` delete/rename/move while `governance/sole_writer.json` has `writer=claude`. Architecture A forbids Cursor from setting `writer` to itself. Operator can flip writer, or Claude can execute the consolidation slice.

---

## Will Phase 1 make a “definitive clean push”?

**No.** A green required `pytest-full` already means “this SHA’s suite passed.” Reorganizing names does not add coverage, does not prove TRADE edge, and does not replace hardening.

What *would* strengthen the repo (measured, not Copilot’s week estimates):

1. Delete or merge only tests that are proven dead or byte-level duplicates.
2. Keep one config surface (`pyproject.toml`), not `pytest.ini` plus a second pytest section.
3. Do not split or rename the required GitHub job `pytest-full`.
4. Do not add `--timeout=30` globally. CI’s full pytest wave is minutes, not 30 seconds per test.

---

## Copilot claims — disposition

| Copilot claim | Disposition | Measured note |
|---|---|---|
| 1,000+ / 1,100+ test files | REJECTED | `find tests/ -name "test_*.py" \| wc -l` → **583** |
| No Makefile / no entrypoint | REJECTED | `Makefile` has `test-e2e` and `test-all`; `package.json` has `test:all` |
| `conftest.py` truncated / hidden | REJECTED | Full file is 247 lines; dumped in `reports/pytest_infrastructure_audit.md` |
| No v1/v2 pairs so consolidate them | REJECTED | `test_v1_*.py` count is **0**; exact `_v1`/`_v2` stem twins are **0** |
| `test_a1_*` paired with `test_a2_*` | REJECTED | Different topics (conformal/isotonic vs session/theta); **0** same-stem pairs |
| ~80 `*fail_closed*` files | REJECTED | `find tests -name '*fail_closed*.py' \| wc -l` → **47** |
| Fail-closed tests only `assert result is not None` | REJECTED | Sample `tests/test_action11_1_math_levels_fail_closed.py` asserts concrete `None` greeks / skipped one-sided OI |
| No pytest markers in use | ACCEPTED (narrow) | Used marks are built-ins: parametrize 98, skipif 6, usefixtures 1 |
| No `pytest.ini` | ACCEPTED | File does not exist on disk or in git history |
| No `[tool.pytest.ini_options]` | ACCEPTED (before this rehab slice) | `pyproject.toml` `[tool]` was ruff/mypy/bandit/coverage only |
| CI has no grouping | ACCEPTED (narrow) | One required job; xdist `--dist loadfile`; E2E overlapped; not semantic markers |
| Add `--timeout=30` globally | REJECTED | Would fail legitimate long nodes; full suite already bounded by job `timeout-minutes: 45` |
| Change `python_files` to require `*_test.py` | REJECTED | Current files are `test_*.py`; a restrictive rename would miss collection |
| Replace `pytest-full` with a matrix | REJECTED | Required check name is a merge rail; splitting it is a control-authority change |
| Create `conftest_extensions.py` | REJECTED | Second fixture path; silent faucet |
| Create root `PYTEST_CONSOLIDATION_PLAN.md` | REJECTED | Charter: extend existing files; inventory already exists |
| Empty `tests/unit/` + `make test-fast` now | REJECTED | Those directories do not exist; a target that points at them is theater |
| Delete `tests/archive/` as dead weight | QUEUED | 16 files, **99** archive functions, already `collect_ignore`; delete only after each file is read |
| Presence-only / assert-free tests exist | VERIFIED | `dead_tests_audit_v1.scan()`: presence_only **44**, assert_free **18**, live functions **5495** |
| 6106 pytest PASS / 5-star machine | REJECTED | Not re-run as “definitive green” in this turn; do not treat Copilot’s score as proof |
| Cursor is PM / sole-writer isolated | REJECTED | `sole_writer.json`: pm=operator, writer=claude, auditor=cursor |
| 0/67 Find & Prove survivors ⇒ pytest rehab | REJECTED | Signal search outcome is not a pytest-layout defect; do not “fix tests” to manufacture edge |

---

## What Copilot was about to write (and what to do instead)

| Copilot deliverable | Do it? | Instead |
|---|---|---|
| `pytest.ini` with timeout/strict-markers/`*_test.py` | No | One section in existing `pyproject.toml` |
| New `Makefile` | No | Keep and extend the existing `Makefile` |
| `tests/README.md` | Not yet | Inventory already in `reports/pytest_infrastructure_audit.md` |
| Move 554 files into `unit/integration/governance/ml` | No (this slice) | File moves do not reduce count; they break imports and CI unless measured |
| Parametrize a1 conformal+isotonic loaders | Optional later | Similar shape, different modules; merge only if assertions stay equivalent |
| GitHub Actions matrix | No | Keep required `pytest-full` command as-is |
| Upgrade all fail-closed assertions | No (blanket) | Sample already has explicit fallbacks; upgrade only measured-weak files |
| Delete archive unread | No | Charter: nothing deleted unread |

---

## File-count rehab that actually serves the repo

Goal the operator named: fewer files, same or better lock strength, no spawned process docs.

Order:

1. **Kill proven dead nodes**, not folders. Start with the 18 assert-free and 44 presence-only rows from `tools.dead_tests_audit_v1.scan()` — writer reads each, then deletes or upgrades.
2. **Do not invent v1/v2 merges.** There are no filename twins.
3. **Do not flatten Action/Issue names in one PR.** Those names are the RC/action lock identity; renaming 200 files is a search-and-break change, not a quality gain.
4. **Keep archive ignored until read.** Then delete or keep with a reason in the same commit.
5. **One pytest config.** `pyproject.toml` `[tool.pytest.ini_options]`: `testpaths`, short traceback, `-ra`. No global timeout. No second `pytest.ini`.
6. **Required CI stays one job.** `python -m pytest -n "$(nproc)" --dist loadfile --durations=20` plus overlapped Playwright.

That sequence can reduce file count. Copilot’s directory shuffle cannot.

---

## Writer handoff (if operator wants file deletes/merges)

Claude (current writer) or an operator-flipped `writer=cursor` may:

- Read and retire assert-free / presence-only tests that do not lock a production path.
- Read the 16 `tests/archive/legacy_section_audits_v1/` files; delete only if superseded by a live inventory lock.
- Leave `tests/conftest.py` fixtures as-is unless a measured isolation bug is shown.

Cursor will not self-grant writer to do that work.
