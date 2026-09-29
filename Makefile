# The test entrypoints (docs/playwright.md); Windows without make: npm run test:all
.PHONY: test-e2e test-all
test-e2e:
	npm run test:e2e

# Playwright first, then the full pytest suite; either failing stops the recipe.
test-all:
	npm run test:e2e
	node scripts/run-pytest-full.mjs
