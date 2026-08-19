# Issue 40/46 — single entrypoint for Playwright E2E (delegates to npm).
.PHONY: test-e2e test-all
test-e2e:
	npm run test:e2e

# E2E must run first (writes .playwright_last_run_success); pytest enforces the marker.
# Either step failing stops the recipe (non-zero exit).
# Windows without make: npm run test:all
test-all:
	npm run test:e2e
	python -m pytest -n auto --dist loadfile --durations=20
