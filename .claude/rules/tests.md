---
paths:
  - "tests/**"
---

# Tests (enforced)

- A test exercises behavior through the real code. It never reads source text or pins a private
  helper; a test whose subject is deleted is deleted with it. Enforced by: no machine check — ENF-08.
- A test whose code a pull request adds or changes never runs with a patch of the code it tests
  applied (monkeypatch, mocker or mock.patch, its own or a fixture's, helper's, setup's, conftest's or
  statement's) and runs in CI to its end (until the operator decides TEST-PATCHES (a)), and no code
  a pull request adds or changes applies one; a patching test may change only in its docstrings and
  comments, or by a standard tool's safe fix, until its patch is removed. Enforced by: `tools/check_no_new_patches.py` on the suite's
  run as `tools/patch_record.py` records it, in the required `pytest-full` job
  (`tests/test_check_no_new_patches_v1.py`); a patch in a branch CI does not take, a patch another
  file's test leaves applied, a `unittest.TestCase` class not named `Test*` in a file pytest
  collects nothing from (skipped whole, ignored, or in a package that skips), a test set onto a class
  with `setattr`, a fixture changed only to request a patching fixture without calling it, a conftest hook that adds
  fixtures to items,
  direct assignment over product code, and the existing ones — no machine check, TEST-PATCHES.
- A flaky test is fixed in app code with the test unchanged, or in the test with its assertions
  unchanged and evidence the timing can't occur in real use (the code that rules it out); loosened expectations, removed checks and
  retries are refused. Its report follows the `flaky-test-fix` skill. Enforced by: no machine check —
  ENF-12.
