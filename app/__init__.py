"""The Ed Console application package.

Production code is migrating out of the repository root into ``app/`` one coherent
subsystem at a time, preserving behaviour. ``app/domain`` holds leaf value types.
``app/market_data`` holds Collect-domain streaming and eligibility.
``app/options`` holds options/order-flow product assembly that consumes those
authorities — it does not open a second Schwab session or recompute book math.
"""
