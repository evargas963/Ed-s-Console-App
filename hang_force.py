"""Throwaway: replace one line of a test with a raise."""

import sys
from pathlib import Path

path, line = Path(sys.argv[1]), sys.argv[2]
text = path.read_text(encoding="utf-8")
assert text.count(line) == 1, line
path.write_text(text.replace(line, "raise RuntimeError('forced')"), encoding="utf-8")
