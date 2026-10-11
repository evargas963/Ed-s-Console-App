---
name: flaky-test-fix
description: Use when a test both passes and fails on the same commit. Finds every such test under load, forces each failure on demand, fixes it at its cause, and reports the four checks with their output.
---

1. Find them all. Run the full suite repeatedly under load on one commit and list every test that both
   passed and failed: `npx playwright test` and
   `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider -n 8 --dist loadfile --junitxml=<run>.xml`,
   10 runs, with 4 CPU-bound processes beside each. Show the per-test pass/fail counts. The operator's
   ruling on the price-history write test is in `ACTIVE_PROGRAM.md` P1-8.
2. For each test, report four things, each with its command and output:
   1. The failure forced on demand before the fix: a command anyone can re-run that makes the timing
      happen every time (a pytest plugin passed with `-p`, a held port, Playwright's `page.clock`).
   2. The cause, as a sequence of events, down to the line of code or data (AGENTS.md First gate 4).
   3. The same forced command passing after the fix, and the test passing in many runs under load.
   4. What changed. App code with the test unchanged is a real fix. A test-only change keeps its
      assertions and shows why the timing can't occur in real use (the code that rules it out).
      Loosened expectations, removed checks and retries are refused.
3. Each fix is its own pull request; run the `before-done` skill on it.
