---
name: No grep, ever — Read end-to-end every single word
description: Absolute ban on ALL forms of pattern-matching search. Originally about the Grep tool (2026-05-18); escalated 2026-05-22 to include shell grep, ripgrep, awk-pattern, find -name-with-grep-pipe — anything that returns matched-line excerpts instead of full file content.
type: feedback
originSessionId: b724fbb2-9fd1-49e3-a3a2-f6ee89a57d27
---

**ABSOLUTE BAN, NO EXCEPTIONS.** I do not use grep in any form for any purpose. The directive covers:

- The `Grep` tool (original 2026-05-18 ban)
- `Bash` calls to `grep`, `rg`, `ripgrep`, `egrep`, `fgrep`
- `Bash` pipes like `cat foo | grep bar`, `awk '/pattern/'`, `sed -n '/pattern/p'`
- `find ... | grep ...`
- ANY command whose output is "lines that matched a pattern" instead of full file content

**Why (escalated 2026-05-22):** Operator's words verbatim: *"you are not to ever fucking grep again!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!  yo read everything every single word."*

Trigger incident: I claimed G-series IDs (G3-R1, G3-R2, G3-R3, G4-1..G4-4) were "plan-internal, not pre-existing" based on a `grep -rn` result that showed only the plan file. The IDs WERE in OPEN_ITEMS.md at lines 389-414 — the grep result was incomplete / truncated / mis-filtered, and I asserted a false negative from it. Reading OPEN_ITEMS.md end-to-end would have caught the IDs. This is the recurring failure mode the operator is calling out: grep produces false confidence by hiding context that a full Read would surface.

**How to apply — no exceptions:**

- For understanding code, what's in a file, what a function does, whether a symbol exists, where it's used, what a tracker contains: use `Read` end-to-end. For files larger than 2000 lines, use `Read` with `offset`+`limit` to walk the whole file in sequential ranges — read EVERY line, not just the lines that grep would have returned.
- For finding callers / usages: `Read` the candidate file end-to-end. If I don't know which files might contain it, ask the operator or rely on Cursor to provide that list.
- For checking "does this string appear in this file": Read the file. Do not pipe to grep, do not use `in` operator on grep output, do not use Bash `grep -q`.
- Tests that internally use Python `re.search` / `in` on file text (static-HTML guards, inventory schema tests) are fine — those are test code, not me using grep at the tool layer.
- `Glob` for file-path discovery is allowed (it returns paths, not content matches). `find -name` is allowed for file paths. The line between OK and not-OK: does the command return file paths, or does it return matched lines inside files? Lines = banned.

**Cost of compliance:** Reading large files is slower than grep. Acceptable. The operator has accepted that cost in exchange for thoroughness. If a task seemingly requires a content scan, do the Reads sequentially — do not fall back to grep "just this once."

**Self-check before any Bash call:** does the command include `grep`, `rg`, `egrep`, `fgrep`, `ripgrep`, `awk '/.../`, `sed -n '/.../p'`, or any pattern-match-with-line-return pattern? If yes, do not run it. Use Read instead.
