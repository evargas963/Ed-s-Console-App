"""Domain leaves — the value and policy types everything else computes in.

Every module here imports only the standard library: no other `app` package, no
repository-root module, no I/O. That is what makes them movable without moving
anything else, and it is the property to preserve as more subsystems arrive.

Current members:
  time_et             canonical Eastern market-session clock and calendar
  numeric_contract    finite-number contract for model and market values
  instrument_identity canonical ticker key for storage and joins
  canonical_distances non-negative nearest-level distance magnitudes
"""
