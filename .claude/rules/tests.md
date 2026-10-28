---
paths:
  - "tests/**"
---

# Tests (enforced)

- A test exercises behavior through the real code. It never reads source text or pins a private
  helper; a test whose subject is deleted is deleted with it. Enforced by: no machine check — ENF-08.
- A pull request adds no patch to a test, fixture or helper (monkeypatch, mock.patch, a fixture that
  does, or a patching autouse fixture over a test it adds); a patch already there is TEST-PATCHES'
  work, not a bar to editing its test elsewhere. Enforced by: `tools/check_no_new_patches.py` in the required
  `hardening` job (`tests/test_check_no_new_patches_v1.py`); the existing ones — TEST-PATCHES.
- A flaky test is fixed in app code with the test unchanged, or in the test with its assertions
  unchanged and evidence the timing can't occur in real use (the code that rules it out); loosened expectations, removed checks and
  retries are refused. Its report follows the `flaky-test-fix` skill. Enforced by: no machine check —
  ENF-12.
