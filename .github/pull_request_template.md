## On screen
<!-- what the operator sees change -->

Wiring:
<!-- each value this PR adds or changes → its Schwab field (docs/schwab_fields.csv row, or Streamer Guide / API page or section), or its canonical derived producer (docs/DATA_FLOW.md §3.6) with the cited proof that Schwab does not send it -->

Schwab → screen:
<!-- the path each changed value takes, hop by hop -->

## Closed
<!-- changed plan or behavior → affected docs, tests, checks and callers updated; superseded statements removed; ACTIVE_PROGRAM rows finished or changed; paths without proof on the final commit listed NOT_PROVEN -->

Deleted:
<!-- what this replaces, removed in this PR -->

End-to-end test:
<!-- the real line added to tests/test_data_path_*.py or tests/e2e/*.spec.js; a PR that only removes product lines names the existing tests that cover it by node id (tests/<file>.py::<test>) -->

## Proof
<!-- commands + exit codes + output, each with its tier (unit, integration, browser, deployed app, live market) and label (CONFIRMED / INDUCED / HYPOTHESIS / NOT_PROVEN); a check shown failing on the old code -->

Architecture review:
<!-- the architecture reviewer's report (.claude/agents/architecture-reviewer.md) on this PR's final commit: per value, PASS / FAIL / NOT_PROVEN against the First gate, with citations -->

Correctness review:
<!-- the correctness reviewer's report (.claude/agents/correctness-reviewer.md) on this PR's final commit: per claim, PASS / FAIL / NOT_PROVEN, with the command output that reproduces it -->

## Screen check
<!-- after deploy: production commit, restart, what was looked at on real data -->
