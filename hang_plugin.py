"""Throwaway: 90 s in, print every unfinished asyncio task and where each is stuck."""

import asyncio
import gc
import threading


def _dump():
    for o in gc.get_objects():
        if isinstance(o, asyncio.Task) and not o.done():
            print("TASK", o.get_name(), o.get_coro(), "cancelling", o.cancelling(), flush=True)
            for f in o.get_stack(limit=12):
                print("   ", f.f_code.co_filename, f.f_lineno, f.f_code.co_name, flush=True)


t = threading.Timer(90, _dump)
t.daemon = True
t.start()
