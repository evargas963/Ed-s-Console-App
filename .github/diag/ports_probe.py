"""DIAGNOSTIC, DO NOT MERGE: what takes the runner's ephemeral TCP ports during the browser tests.

Every 50 ms it asks Windows for one ephemeral port (bind to port 0) and gives it back; a refusal is
the moment the port space is spent, and at that moment it prints the whole TCP table as netstat
-anoq lists it (BOUND included), by state and by process. Every second it prints the stack's own
cumulative counters (GetTcpStatisticsEx, IPv4 and IPv6): connections opened out (active) and in
(passive), failed attempts, resets, and the number of entries in the table.
"""

import collections
import ctypes
import socket
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import UTC, datetime

import time_et

FIELDS = [
    "rto_alg",
    "rto_min",
    "rto_max",
    "max_conn",
    "active",
    "passive",
    "attempt_fails",
    "estab_resets",
    "curr_estab",
    "in_segs",
    "out_segs",
    "retrans",
    "in_errs",
    "out_rsts",
    "num_conns",
]
COUNTED = ("active", "passive", "attempt_fails", "estab_resets")


class MibTcpStats(ctypes.Structure):
    _fields_ = [(f, wintypes.DWORD) for f in FIELDS]


def tcp_stats(family):
    s = MibTcpStats()
    ctypes.windll.iphlpapi.GetTcpStatisticsEx(ctypes.byref(s), family)
    return {f: getattr(s, f) for f in FIELDS}


def process_names():
    out = subprocess.run(
        ["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, check=False
    ).stdout
    names = {}
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1:
            names[parts[1]] = parts[0]
    return names


def stamp():
    return datetime.fromtimestamp(time_et.now(), UTC).strftime("%H:%M:%S.%f")[:-3]


def table_snapshot(why):
    t0 = time_et.elapsed()
    out = subprocess.run(
        ["netstat", "-anoq", "-p", "TCP"], capture_output=True, text=True, check=False
    ).stdout
    rows = [r for r in (line.split() for line in out.splitlines()) if len(r) == 5 and r[0] == "TCP"]
    states = collections.Counter(r[3] for r in rows)
    by_pid = collections.Counter((r[3], r[4]) for r in rows)
    ports_by_pid = collections.Counter(r[4] for r in rows if int(r[1].rsplit(":", 1)[1]) >= 49152)
    names = process_names()
    took = time_et.elapsed() - t0
    print(f"### SNAPSHOT {stamp()} ({why}) netstat took {took:.2f}s rows={len(rows)}", flush=True)
    print(f"###   by state: {dict(states)}", flush=True)
    for (state, pid), n in by_pid.most_common(12):
        print(f"###   {n:6d} {state:12s} pid {pid} {names.get(pid, '?')}", flush=True)
    for pid, n in ports_by_pid.most_common(6):
        print(f"###   local port in 49152+: {n:6d} pid {pid} {names.get(pid, '?')}", flush=True)
    udp = subprocess.run(
        ["netstat", "-ano", "-p", "UDP"], capture_output=True, text=True, check=False
    ).stdout
    print(f"###   UDP endpoints: {sum(1 for x in udp.splitlines() if 'UDP' in x)}", flush=True)


def main(seconds):
    end = time_et.elapsed() + seconds
    prev4, prev6 = tcp_stats(socket.AF_INET), tcp_stats(socket.AF_INET6)
    next_line = time_et.elapsed() + 1
    next_snapshot = 0.0
    next_routine = time_et.elapsed() + 30
    fails = 0
    while time_et.elapsed() < end:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", 0))
        except OSError as e:
            fails += 1
            print(f"### PORT REFUSED {stamp()} {e!r}", flush=True)
            if time_et.elapsed() >= next_snapshot:
                table_snapshot("port refused")
                next_snapshot = time_et.elapsed() + 2
        finally:
            s.close()
        now = time_et.elapsed()
        if now >= next_line:
            s4, s6 = tcp_stats(socket.AF_INET), tcp_stats(socket.AF_INET6)
            d = {k: s4[k] - prev4[k] for k in COUNTED}
            d6 = s6["active"] - prev6["active"]
            print(
                f"{stamp()} v4 active+{d['active']} passive+{d['passive']} "
                f"fails+{d['attempt_fails']} resets+{d['estab_resets']} estab={s4['curr_estab']} "
                f"table={s4['num_conns']} | v6 active+{d6} table={s6['num_conns']} "
                f"| refused={fails}",
                flush=True,
            )
            prev4, prev6 = s4, s6
            next_line = now + 1
        if now >= next_routine:
            table_snapshot("every 30 s")
            next_routine = now + 30
        time.sleep(0.05)


if __name__ == "__main__":
    main(float(sys.argv[1]))
