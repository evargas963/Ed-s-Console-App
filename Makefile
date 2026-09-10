# Issue 40/46 — single entrypoint for Playwright E2E (delegates to npm).
.PHONY: test-e2e test-all
test-e2e:
	npm run test:e2e

# E2E runs first, then the full pytest suite; each step's exit code is its proof (the
# marker file pytest used to require was retired by RC-542).
# Either step failing stops the recipe (non-zero exit).
# Windows without make: npm run test:all
# RC-535: both steps write their child's output to logs/ (file descriptors, never the
# terminal pipe) and echo only a bounded tail, so a terminal that stops draining cannot
# block the run. The pytest step is `python -m pytest -n auto --dist loadfile
# --durations=20` inside scripts/run-pytest-full.mjs.
test-all:
	npm run test:e2e
	node scripts/run-pytest-full.mjs
