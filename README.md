# Ed Web Console

A financial application: a FastAPI console (`server.py`) and a Schwab capture daemon, with one
static page (`static/`). Its output can drive real financial decisions; every value it shows is
live and correct, or says it is not.

- Rules for every change: `AGENTS.md`. The design and each value's definition:
  `docs/DATA_FLOW.md`. Where code lives: `docs/ARCHITECTURE.md`. Operations: `docs/host/`. The
  work list: `ACTIVE_PROGRAM.md`.
- Run: `start_ed_console.bat` (port 8000) and `start_capture_daemon.bat`.
- Tests: `npm install` once, then `npm run test:all` (Playwright, then pytest) — see
  [docs/playwright.md](docs/playwright.md).
