---
name: housekeeping
description:
  Use to clean up open pull requests, branches, worktrees, stashes and disk. Lists each with its
  evidence first, acts only on Ed's yes, and gives Ed the commands for anything permanent.
---

# Housekeeping

1. List, change nothing, and show each command's output:
   - `gh pr list --state open --json number,title,headRefName,updatedAt` — each open PR, and whether
     its change is already on `main` (`git log origin/main --grep` or a patch-id match).
   - `git branch -r --merged origin/main` and `git branch --merged origin/main` — branches whose
     work is on `main`.
   - `git worktree list` — each worktree, its branch, and whether its tree has uncommitted work.
   - Disk: the largest files and folders outside `data/`, with size and last-modified time.
2. Prove each candidate truly deletable (AGENTS.md Authority) and show the evidence, one line each:

   - nothing reads it: no tracked file of `origin/main` names it, and nothing changed it lately;
   - nothing is lost: its content is in `main`'s history (name the commit), or it is first copied
     outside the checkout and the copy proved whole (each file's SHA-256 matches; a git bundle of
     the branches and stashes, fetched into a fresh clone of GitHub, gives back every ref at its
     commit, and `git fsck` passes);
   - it is not a record of what Schwab sent or Ed's own work: those are copied and kept until he
     says.

   A candidate that fails a test stays. Propose what to close or delete, and wait for Ed's yes.

3. On Ed's yes: close a PR with a comment naming what replaced it; delete merged branches
   (recoverable from GitHub). Remove a worktree only after each `.venv` or `node_modules` in it that
   is a junction to production is unlinked (`cmd /c rmdir <junction>`; a `.venv` built by
   `tools/bootstrap_worktree_venv.py` is the worktree's own), then run `pip check` in production.
4. Anything permanent (a stash drop, an unmerged branch, a folder, anything under `data/`): give Ed
   the exact commands, one group at a time, and wait for his result. The agent does not run them.
5. Show the state after (step 1 again).
