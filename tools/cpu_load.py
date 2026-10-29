"""Hold N CPU-bound processes for S seconds: the load the flaky-test skill runs the suite beside.

python tools/cpu_load.py 4 600
"""

from __future__ import annotations

import multiprocessing
import sys
import time


def burn(until: float) -> None:
    x = 0
    while time.time() < until:
        x += 1


def main(argv: list[str]) -> int:
    n, seconds = int(argv[0]), float(argv[1])
    until = time.time() + seconds
    procs = [multiprocessing.Process(target=burn, args=(until,)) for _ in range(n)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
