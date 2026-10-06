# Ed Web Console

A FastAPI console (`server.py`) and a Schwab capture daemon, with one static page (`static/`).

- Rules for every change: `AGENTS.md`. The design: `docs/DATA_FLOW.md`. Where code lives:
  `docs/ARCHITECTURE.md`. The work list: `ACTIVE_PROGRAM.md`.
- Run: `start_ed_console.bat` (`launch.py`: it reads `.env` and starts the capture daemon and the
  console, port 8000, with it). Neither process reads `.env` itself.
- Tests: `npm install` once, then `npm run test:all` (Playwright, then pytest) — see
  [docs/playwright.md](docs/playwright.md).
