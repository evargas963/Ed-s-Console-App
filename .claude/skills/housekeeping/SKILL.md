---
name: housekeeping
description: Use to clean up open pull requests, branches, worktrees, stashes and disk. Lists each with its evidence first, acts only on Ed's yes, and gives Ed the commands for anything permanent.
---

1. List, change nothing, and show each command's output:
   - `gh pr list --state open --json number,title,headRefName,updatedAt` — each open PR, and whether its
     change is already on `main` (`git log origin/main --grep` or a patch-id match).
   - `git branch -r --merged origin/main` and `git branch --merged origin/main` — branches whose work
     is on `main`.
   - `git worktree list` — each worktree, its branch, and whether its tree has uncommitted work.
   - `git stash list` — each stash.
   - Disk: the largest files and folders outside `data/`, with size and last-modified time.
2. Propose what to close or delete, one line each with its evidence. Wait for Ed's yes.
3. On Ed's yes: close a PR with a comment naming what replaced it; delete merged branches (recoverable
   from GitHub). Remove a worktree only after its `.venv` and `node_modules` junctions are unlinked
   (`cmd /c rmdir <junction>`), then run `pip check` in production.
4. Anything permanent (a stash drop, an unmerged branch, a folder, anything under `data/`): give Ed the
   exact commands, one group at a time, and wait for his result. The agent does not run them.
5. Show the state after (step 1 again).
