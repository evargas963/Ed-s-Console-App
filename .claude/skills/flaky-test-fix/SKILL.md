---
name: flaky-test-fix
description:
  Use when a test both passes and fails on the same commit. Finds every such test under load, then
  for each one forces its failure on demand, fixes it at its cause, and reports the four checks with
  their output; the fixes go in one pull request.
---

# Flaky test fix

1. Find them all. Run the full suite repeatedly under load on one commit and list every test that
   both passed and failed: `npx playwright test`, and pytest as CI runs it
   (`.github/workflows/pytest.yml`), the workers, then each test marked `alone` (a limit on the wall
   clock) with none beside it:
   `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider -n logical --dist loadfile -m "not alone" --junitxml=<run>.xml`
   and
   `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider -m alone --junitxml=<run>-alone.xml`;
   10 runs, with 4 CPU-bound processes beside each
   (`.venv/Scripts/python.exe -m tools.cpu_load 4 <seconds>`), ended after each run with its whole
   tree (`taskkill /PID <pid> /T /F`: on Windows the venv's `python.exe` starts the interpreter as a
   child, so killing it leaves the interpreter and its four burners running into the next run). Show
   the per-test pass/fail counts, and beside each test the operator's ruling on it in
   `ACTIVE_PROGRAM.md`, if one is recorded.
2. Show Ed the list, then take each test in turn with a short plan for it; changing a test needs no
   approval (CLAUDE.md item 4). For each test, report four things, each with its command and output:
   1. The failure forced on demand before the fix: a command anyone can re-run that makes the timing
      happen every time (a pytest plugin passed with `-p`, a held port, Playwright's `page.clock`).
   2. The cause, as a sequence of events, down to the line of code or data (AGENTS.md First gate 4).
   3. The same forced command passing after the fix, and the test passing in many runs under load.
   4. What changed, judged by the flaky-test rule in `.claude/rules/tests.md`.
3. The fixes are one pull request, the group of one search's findings (AGENTS.md, Authority: a pull
   request is opened for a group); run the `before-done` skill on it.
