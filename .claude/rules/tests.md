---
paths:
  - "tests/**"
---

# Tests (enforced)

- A test exercises behavior through the real code. It never reads source text or pins a private
  helper; a test whose subject is deleted is deleted with it. Enforced by: no machine check — ENF-08.
- A test, fixture or helper a pull request adds or changes never patches the code it tests
  (monkeypatch, mock.patch, a fixture that does, or a patching autouse fixture in its file); an existing
  one is cleaned when its file is touched. Enforced by: `tools/check_no_new_patches.py` in the required
  `hardening` job (`tests/test_check_no_new_patches_v1.py`); the existing ones — TEST-PATCHES.
- A flaky test is fixed in app code with the test unchanged, or in the test with its assertions
  unchanged and evidence the timing can't occur in real use; loosened expectations, removed checks and
  retries are refused. Its report follows the `flaky-test-fix` skill. Enforced by: no machine check —
  ENF-12.
- A test that stands in a heartbeat, a price or a clock stamps it at the time the code under test
  judges. Enforced by: no machine check — ENF-09.
- An end-to-end spec answers each route it stands in for in the shape the server serves (a
  `/api/watchlist` answer carries `tickers`: `tests/e2e/fixtures/watchlist.js`). Enforced by: no
  machine check — ENF-07.
- The price-history write test keeps its 1.0 s limit; a failure under the flaky hunt's added CPU load
  is that load, not a defect. Enforced by: no machine check — ENF-08.
