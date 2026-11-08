# Ed Web Console

One program (`capture_main`): the Schwab streaming connection, the recording, and the console's
pages (`server.py`, served by the program on port 8000), with one static page (`static/`).

- Rules for every change: `AGENTS.md`. The design: `docs/DATA_FLOW.md`. Where code lives:
  `docs/ARCHITECTURE.md`. The work list: `ACTIVE_PROGRAM.md`.
- Run: `start_ed_console.bat`, the one start: it brings the checkout to origin/main, then starts
  the program in its own window and opens the console (port 8000). Stop: `python launch.py stop`.
- Tests: `npm install` once, then `npm run test:all` (Playwright, then pytest) — see
  [docs/playwright.md](docs/playwright.md).
