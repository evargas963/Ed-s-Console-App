---
name: deploy
description: Use to start, stop, restart or deploy the production capture daemon and console (the EdWebConsole checkout). Runs each step and shows its output; a merged PR is deployed only after these steps.
---

Production is the `EdWebConsole` checkout: `start_ed_console.bat` runs `launch.py`, which brings the
checkout to `origin/main`, starts the capture daemon in its own window and `uvicorn server:app` on port
8000. Python 3.13, the project `.venv`; live needs `schwab_token.json` (`python reauth_schwab.py`). Probe
`127.0.0.1`, never `localhost` (Windows tries IPv6 first, about 2 s per probe).

1. Read the session the yes guard reads (Schwab's /markets answer, as the daemon recorded it):
   `.venv/Scripts/python.exe -c "import sys; sys.path.insert(0, 'tools'); import operator_yes_guard as g, time_et; from db_authority import canonical_stream_db_path; print(g.market_session(time_et.now_et(), canonical_stream_db_path()))"`.
   In RTH or an unknown session a start or stop goes to Ed as an Allow/Deny prompt
   (`tools/operator_yes_guard.py`): say in chat what it is for first. In Pre-Market, After-Hours and
   Closed, post a notice in chat and go on.
2. Before: `git -C <production> log --oneline -1` and `git -C <production> fetch -q && git -C <production> log --oneline -1 origin/main` — what will deploy.
3. Stop both: `.venv/Scripts/python.exe launch.py stop` in the production checkout; show its output.
4. Start both from outside this session, so an app restart cannot end them:
   `explorer.exe start_ed_console.bat` in the production checkout.
5. Confirm both came back and run the merge commit: the processes
   (`Get-CimInstance Win32_Process` with `capture` / `uvicorn` in the command line), port 8800 and 8000
   answering (`launch.in_use`), `curl -s http://127.0.0.1:8000/api/health`, and
   `git -C <production> rev-parse --short HEAD` equal to `origin/main`. Show each output.
6. Deployed means step 5 passed and the screen was checked during market hours. Until then report the
   change as on disk, not deployed.
