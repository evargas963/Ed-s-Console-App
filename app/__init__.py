"""The Ed Console application package (RC-505, rehabilitation day 2).

TARGET shape: eight packages under `app/` — domain, infrastructure, market_data, options,
signals, models, decision, api — replacing 147 production modules at the repository root.
`tools/repo_rehab_status.py` holds that target, hash-pinned, and its ratchet refuses any
child of `app/` the target does not declare.

Migration is incremental by design, and the ratchet is built to permit exactly that: a module
lands here while the root path becomes a re-export shim, so every existing import keeps
working and the root file dies in a later delta. A flag-day rewrite is the one thing this
rehabilitation must not require.
"""
