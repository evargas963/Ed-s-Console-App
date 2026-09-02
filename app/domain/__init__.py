"""Domain value types — the leaf of the dependency lattice.

Nothing here may import another `app` package, any legacy top-level directory, or any root
module. These are the definitions everything else is expressed in: what a ticker IS, what a
distance MEANS. That is why the migration starts here — a leaf can move without moving
anything else, so behaviour cannot change as a side effect.

The ratchet enforces the direction: `app_files_importing_legacy` is a ratcheted metric and may
only fall.
"""
