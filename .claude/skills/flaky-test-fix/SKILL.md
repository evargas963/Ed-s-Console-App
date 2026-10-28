---
name: flaky-test-fix
description: Use when a test both passes and fails on the same commit. Finds every such test under load, then takes one per session: forces its failure on demand, fixes it at its cause, and reports the four checks with their output.
---

1. Find them all. Run the full suite repeatedly under load on one commit and list every test that both
   passed and failed: `npx playwright test` and
   `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider -n 8 --dist loadfile --junitxml=<run>.xml`,
   10 runs, with 4 CPU-bound processes beside each (`.venv/Scripts/python.exe tools/cpu_load.py 4 <seconds>`). Show the per-test pass/fail counts, and beside each
   test the operator's ruling on it in `ACTIVE_PROGRAM.md`, if one is recorded.
2. Show Ed the list, then take one test per session (CLAUDE.md item 3): a short plan for it, then Ed's
   yes. For that test, report four things, each with its command and output:
   1. The failure forced on demand before the fix: a command anyone can re-run that makes the timing
      happen every time (a pytest plugin passed with `-p`, a held port, Playwright's `page.clock`).
   2. The cause, as a sequence of events, down to the line of code or data (AGENTS.md First gate 4).
   3. The same forced command passing after the fix, and the test passing in many runs under load.
   4. What changed, judged by the flaky-test rule in `.claude/rules/tests.md`.
3. The fix is its own pull request; run the `before-done` skill on it.
