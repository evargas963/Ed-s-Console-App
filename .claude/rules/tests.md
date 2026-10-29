---
paths:
  - "tests/**"
---

# Tests (enforced)

- A test exercises behavior through the real code. It never reads source text or pins a private
  helper; a test whose subject is deleted is deleted with it. Enforced by: no machine check — ENF-08.
- A test, fixture or helper whose code a pull request adds or changes never patches the code it tests
  (monkeypatch, mocker, mock.patch in any spelling, a fixture that does by parameter, usefixtures or
  its class's decorator, or a patching autouse fixture, setup function or other statement in its
  file or a conftest.py above it); code outside the functions never adds or changes a patch; a patching
  test may change only in its docstrings and comments until its patch is removed. Enforced by: `tools/check_no_new_patches.py` in the required
  `hardening` job (`tests/test_check_no_new_patches_v1.py`); the existing ones — TEST-PATCHES.
- A flaky test is fixed in app code with the test unchanged, or in the test with its assertions
  unchanged and evidence the timing can't occur in real use (the code that rules it out); loosened expectations, removed checks and
  retries are refused. Its report follows the `flaky-test-fix` skill. Enforced by: no machine check —
  ENF-12.
