"""Count the calls of functions with Python's own monitoring, the code itself untouched."""

from __future__ import annotations

import sys


def calls(codes, run) -> dict[str, int]:
    """Run `run`, counting the calls of each function in `codes` (name -> its code object).

    A call is counted on whatever thread makes it.
    """
    mon = sys.monitoring
    tool = next(i for i in range(6) if mon.get_tool(i) is None)
    by_code = {code: name for name, code in codes.items()}
    counts = dict.fromkeys(codes, 0)

    def start(code, _offset):
        counts[by_code[code]] += 1

    mon.use_tool_id(tool, "call count")
    mon.register_callback(tool, mon.events.PY_START, start)
    try:
        for code in codes.values():
            mon.set_local_events(tool, code, mon.events.PY_START)
        run()
    finally:
        for code in codes.values():
            mon.set_local_events(tool, code, 0)
        mon.free_tool_id(tool)
    return counts
