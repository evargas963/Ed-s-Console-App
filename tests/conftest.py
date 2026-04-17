"""
Pytest: allow EdDB against temp paths (non-canonical) without per-call flags.

Production processes must NOT set ED_CONSOLE_ALLOW_NONCANONICAL_DB globally.
"""
from __future__ import annotations

import os

os.environ.setdefault("ED_CONSOLE_ALLOW_NONCANONICAL_DB", "1")
