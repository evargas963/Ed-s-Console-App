---
paths:
  - "tests/**"
---

# Tests (enforced)

- Every test serves the app (AGENTS.md, the goal), in one of four tiers, the test pyramid (Martin
  Fowler, "TestPyramid"; Google Testing Blog, "Just Say No to More End-to-End Tests"): a
  Calculator's logic on captured Schwab data; the wiring, Schwab to program to page; the page
  drawing what it is served (Playwright, `tests/e2e/`); and the rails that guard production and
  the credentials, each such file marked `pytestmark = pytest.mark.rail`. A test file that is not
  a rail runs app code of its own, beyond what half the suite runs. Enforced by: coverage.py's
  per-test record in `linux-pytest` (`.github/workflows/pytest.yml`) and its check there.
- A test exercises behavior through the real code. It never reads source text or pins a private
  helper; a test whose subject is deleted is deleted with it. Enforced by: no machine check — ENF-08.
- A test never patches the code it tests (monkeypatch, mocker or mock.patch). Enforced by:
  `tools/check_locks.py`, whose count of patching lines in tests may not rise (locks); what the
  count does not see — no machine check, TEST-PATCHES.
- A flaky test is fixed in app code with the test unchanged, or in the test with its assertions
  unchanged and evidence the timing can't occur in real use (the code that rules it out);
  loosened expectations, removed checks and
  retries are refused. Its report follows the `flaky-test-fix` skill. Enforced by: no machine check —
  ENF-12.
