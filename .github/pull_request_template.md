## On screen
<!-- what the operator sees change -->

## Values touched
<!-- each value → its definition in docs/DATA_FLOW.md §7 (updated in this PR where the change alters it): source, one producer and lifecycle owner, times, when it is current, what each consumer shows when it is missing, stale or disconnected; whether it is current state, a new event or history -->

## Conflicts
<!-- each direction or recommendation this change follows that conflicts, or may, with an AGENTS.md rule, and the operator's explicit confirmation (words, date, exception, scope, justification); or "none" -->

## Violations
<!-- existing violations this change touches and leaves: each stays in ACTIVE_PROGRAM.md with its evidence, owner and closure -->

## Proof
<!-- each requirement → the test that fails when it is broken (shown failing on the old code or a named broken input); commands, exit codes and output; tier of each (unit, integration, browser, host, deployed app, live market) -->

## Independent verification
<!-- reviewer (a fresh-context agent given only AGENTS.md, the definitions touched and the diff, or the operator): what it checked, including each changed test, fixture, expected value, hook and CI step for a weakened requirement; the evidence it cites; its verdict (PASS / FAIL / NOT_PROVEN). The PR merges only on PASS. -->

## Closed
<!-- changed plan or behavior → affected docs, tests, checks and callers updated; superseded statements removed; ACTIVE_PROGRAM rows finished or changed; unverified paths listed NOT_PROVEN -->

## Deleted
<!-- what this replaces, removed in this PR -->

## Screen check
<!-- after deploy: production commit, restart, what was looked at on real data -->
