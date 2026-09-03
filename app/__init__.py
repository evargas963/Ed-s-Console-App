"""The Ed Console application package.

Production code is migrating out of the repository root into ``app/`` one coherent
subsystem at a time, preserving behaviour. ``app/domain`` holds the leaf value and
policy types everything else is expressed in. ``app/market_data`` holds Collect-domain
eligibility and vendor-lifecycle predicates that consume those leaves.
"""
