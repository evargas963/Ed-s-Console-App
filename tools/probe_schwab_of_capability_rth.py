#!/usr/bin/env python3
"""RC-438 — Smallest RTH Schwab Order-Flow capability probe.

Captures **raw** streamer data frames (numeric field keys, pre schwab-py relabel)
and **decoded** named frames (schwab-py BookFields / BidFields / AskFields /
PerExchange* relabel) side-by-side. Does **not** run Ed Console order_flow_engine
normalization and does **not** add analytics/UI.

Priorities:
  1. NYSE_BOOK + NASDAQ_BOOK for SPY/QQQ/IWM
  2. NUM_BIDS / NUM_ASKS measurable relationships
  3. Nested EXCHANGE raw values (identity NOT_PROVEN)
  4. BOOK_TIME + SEQUENCE characterization
  5. OPTIONS_BOOK entitlement / shape
  6. TIMESALE re-probe (via StreamClient._service_op)
  7. Optional LEVELONE_OPTIONS
  8. Absence scan for NOII / aggressor key names

Usage (operator host, RTH, Schwab token present; stop console streamer first):

  python tools/probe_schwab_of_capability_rth.py --duration-sec 90
  python tools/probe_schwab_of_capability_rth.py --symbols SPY,QQQ,IWM \\
      --duration-sec 120 --with-options-book --with-timesales --with-levelone-options

Outputs under reports/of_capability_probe/<stamp>/ including capability_matrix.json
(PASS / NOT_PROVEN / UNAVAILABLE).

Reuse note: full CR-01 daemon (tools/run_stream_capture.py) does not subscribe books
or preserve numeric raw book frames. schwab_full_field_inventory.py only probes
NASDAQ_BOOK briefly. This script is the smallest dedicated OF capability probe.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.of_schwab_capability_lib import (  # noqa: E402
    NOT_PROVEN,
    UNAVAILABLE,
    analyze_book_time_sequence,
    analyze_exchange_semantics,
    analyze_num_semantics,
    apply_live_results_to_matrix,
    decode_book_content_item,
    empty_capability_matrix,
    scan_keys_for_forbidden_concepts,
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8")


def _pick_option_symbol(client: Any, underlying: str = "SPY") -> str | None:
    """Best-effort ATM-ish option symbol from REST chain for LEVELONE_OPTIONS."""
    try:
        from schwab_client import safe_get_chain

        resp = safe_get_chain(client, underlying, strike_count=6, include_underlying_quote=True)
        if not resp.ok or not isinstance(resp.data, dict):
            return None
        data = resp.data
        und = data.get("underlying") or {}
        spot = und.get("last") or und.get("mark") or data.get("underlyingPrice")
        best = None
        best_dist = None
        for side in ("callExpDateMap", "putExpDateMap"):
            m = data.get(side) or {}
            if not isinstance(m, dict):
                continue
            for _exp, strikes in m.items():
                if not isinstance(strikes, dict):
                    continue
                for strike_s, contracts in strikes.items():
                    try:
                        k = float(strike_s)
                    except (TypeError, ValueError):
                        continue
                    rows = contracts if isinstance(contracts, list) else [contracts]
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        sym = row.get("symbol")
                        if not sym:
                            continue
                        if spot is None:
                            return str(sym)
                        dist = abs(k - float(spot))
                        if best_dist is None or dist < best_dist:
                            best_dist = dist
                            best = str(sym)
        return best
    except Exception:  # noqa: BLE001
        return None


async def _probe_timesales(stream: Any, symbols: list[str]) -> dict[str, Any]:
    """Re-probe TIMESALE_EQUITY via low-level _service_op (not wrapped in schwab-py)."""
    out: dict[str, Any] = {
        "service": "TIMESALE_EQUITY",
        "symbols": symbols,
        "response_code": None,
        "error": None,
        "n_frames": 0,
    }
    try:
        # Field type omitted — send keys only; Schwab may reject regardless.
        await stream._service_op(symbols, "TIMESALE_EQUITY", "SUBS")
        out["response_code"] = 0
        out["subs_ok"] = True
    except Exception as exc:  # noqa: BLE001
        out["subs_ok"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
        resp = getattr(exc, "response", None)
        try:
            if isinstance(resp, dict):
                out["response_code"] = resp["response"][0]["content"]["code"]
                out["response_msg"] = resp["response"][0]["content"].get("msg")
        except Exception:  # noqa: BLE001
            pass
    return out


async def _run_probe(args: argparse.Namespace) -> int:
    from config import build_config
    from schwab.streaming import StreamClient
    from schwab_client import build_client_from_token

    cfg = build_config(str(ROOT))
    state = build_client_from_token(
        api_key=cfg.api_key, app_secret=cfg.app_secret, token_path=cfg.token_path
    )
    if not state.ok or state.client is None:
        out_dir = ROOT / "reports" / "of_capability_probe" / f"OFFLINE_{_utc_stamp()}"
        out_dir.mkdir(parents=True, exist_ok=True)
        matrix = empty_capability_matrix(live_ran=False)
        _write_json(out_dir / "capability_matrix.json", matrix)
        _write_json(
            out_dir / "probe_manifest.json",
            {
                "ok": False,
                "reason": state.message,
                "note": "No live Schwab client — matrix left NOT_PROVEN. Run on operator host with token during RTH.",
            },
        )
        print(f"OFFLINE: {state.message}")
        print(f"Wrote template matrix → {out_dir / 'capability_matrix.json'}")
        return 2

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    stamp = _utc_stamp()
    out_dir = Path(args.out_dir) if args.out_dir else (
        ROOT / "reports" / "of_capability_probe" / stamp
    )
    frames_dir = out_dir / "frames"
    analysis_dir = out_dir / "analysis"
    frames_dir.mkdir(parents=True, exist_ok=True)
    analysis_dir.mkdir(parents=True, exist_ok=True)

    raw_frames: list[dict[str, Any]] = []
    decoded_book_frames: list[dict[str, Any]] = []
    service_counts: dict[str, int] = {}
    book_services: dict[str, Any] = {}
    labeled_by_svc: dict[str, list] = {}

    stream = StreamClient(state.client)
    await stream.login()

    # Capture pump: preserve numeric-key raw BEFORE schwab-py relabel.
    async def pump_until(deadline: float) -> None:
        while time.monotonic() < deadline:
            try:
                async with stream._lock:
                    msg = await asyncio.wait_for(stream._receive(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:  # noqa: BLE001
                print(f"receive error: {type(exc).__name__}: {exc}")
                break
            if "response" in msg:
                # unexpected during data phase
                continue
            if "notify" in msg:
                continue
            if "data" not in msg:
                continue
            for d in msg["data"]:
                svc = d.get("service")
                service_counts[svc] = service_counts.get(svc, 0) + 1
                raw = copy.deepcopy(d)
                raw_frames.append({"service": svc, "raw": raw, "recv_mono": time.monotonic()})
                handlers = stream._handlers.get(svc) or []
                labeled = d
                if handlers:
                    labeled = handlers[0].label_message(d)
                labeled_by_svc.setdefault(svc, []).append(labeled)
                if svc in ("NYSE_BOOK", "NASDAQ_BOOK", "OPTIONS_BOOK"):
                    for c in labeled.get("content") or []:
                        if isinstance(c, dict):
                            decoded_book_frames.append(decode_book_content_item(c))
                # Persist first N per service (raw + schwab-py-decoded side-by-side)
                idx = service_counts[svc]
                if idx <= args.max_frames_per_service:
                    sym = "?"
                    try:
                        content0 = (labeled.get("content") or [None])[0] or {}
                        sym = content0.get("SYMBOL") or content0.get("key") or "?"
                    except Exception:  # noqa: BLE001
                        pass
                    base = f"{svc}_{sym}_{idx:04d}"
                    _write_json(frames_dir / f"{base}_raw.json", raw)
                    _write_json(frames_dir / f"{base}_decoded.json", labeled)

    # Subscriptions
    async def try_subs(label: str, coro) -> dict[str, Any]:
        info: dict[str, Any] = {"subs_ok": False, "error": None, "refused": False}
        try:
            await coro
            info["subs_ok"] = True
        except Exception as exc:  # noqa: BLE001
            info["error"] = f"{type(exc).__name__}: {exc}"
            resp = getattr(exc, "response", None)
            try:
                if isinstance(resp, dict):
                    code = resp["response"][0]["content"]["code"]
                    info["response_code"] = code
                    info["refused"] = code not in (0, None)
            except Exception:  # noqa: BLE001
                pass
        book_services[label] = info
        return info

    # Register handlers so label_message path matches production BookHandler.
    stream.add_nyse_book_handler(lambda _msg: None)
    stream.add_nasdaq_book_handler(lambda _msg: None)
    if args.with_options_book:
        stream.add_options_book_handler(lambda _msg: None)
    stream.add_level_one_equity_handler(lambda _msg: None)
    if args.with_levelone_options:
        stream.add_level_one_option_handler(lambda _msg: None)

    await try_subs("NYSE_BOOK", stream.nyse_book_subs(symbols))
    await try_subs("NASDAQ_BOOK", stream.nasdaq_book_subs(symbols))
    await stream.level_one_equity_subs(symbols)

    option_sym = None
    levelone_options: dict[str, Any] = {"enabled": bool(args.with_levelone_options)}
    if args.with_options_book:
        # Options book often wants option symbols; also try underlyings for entitlement signal.
        await try_subs("OPTIONS_BOOK", stream.options_book_subs(symbols))
    if args.with_levelone_options:
        option_sym = _pick_option_symbol(state.client, symbols[0] if symbols else "SPY")
        levelone_options["option_symbol"] = option_sym
        if option_sym:
            try:
                await stream.level_one_option_subs([option_sym])
                levelone_options["subs_ok"] = True
            except Exception as exc:  # noqa: BLE001
                levelone_options["subs_ok"] = False
                levelone_options["error"] = f"{type(exc).__name__}: {exc}"
        else:
            levelone_options["subs_ok"] = False
            levelone_options["error"] = "no option symbol from chain"

    timesales_info: dict[str, Any] | None = None
    if args.with_timesales:
        timesales_info = await _probe_timesales(stream, symbols)

    deadline = time.monotonic() + max(5, int(args.duration_sec))
    print(
        f"probing duration_sec={args.duration_sec} symbols={symbols} "
        f"out={out_dir} (stop console/capture streamer first)"
    )
    await pump_until(deadline)

    # Count frames per book service
    for svc in ("NYSE_BOOK", "NASDAQ_BOOK", "OPTIONS_BOOK"):
        info = book_services.setdefault(svc, {"subs_ok": False})
        info["n_frames"] = service_counts.get(svc, 0)

    if timesales_info is not None:
        timesales_info["n_frames"] = service_counts.get("TIMESALE_EQUITY", 0)

    if args.with_levelone_options:
        levelone_options["n_frames"] = service_counts.get("LEVELONE_OPTIONS", 0)

    try:
        await stream.logout()
    except Exception as exc:  # noqa: BLE001
        print(f"logout: {type(exc).__name__}: {exc}")

    num_analysis = analyze_num_semantics(decoded_book_frames)
    exchange_analysis = analyze_exchange_semantics(decoded_book_frames)
    time_seq = analyze_book_time_sequence(decoded_book_frames)

    # Absence scan over all labeled payloads
    absence = scan_keys_for_forbidden_concepts(
        {"labeled": labeled_by_svc, "raw_services": list(service_counts)}
    )

    _write_json(analysis_dir / "num_bids_asks_semantics.json", num_analysis)
    _write_json(analysis_dir / "exchange_semantics.json", exchange_analysis)
    _write_json(analysis_dir / "book_time_sequence.json", time_seq)
    _write_json(analysis_dir / "noii_aggressor_absence.json", absence)
    _write_json(analysis_dir / "book_services.json", book_services)
    if timesales_info is not None:
        _write_json(analysis_dir / "timesales.json", timesales_info)
    if args.with_levelone_options:
        _write_json(analysis_dir / "levelone_options.json", levelone_options)

    matrix = empty_capability_matrix(live_ran=True)
    matrix = apply_live_results_to_matrix(
        matrix,
        book_services=book_services,
        num_analysis=num_analysis,
        exchange_analysis=exchange_analysis,
        timesales=timesales_info,
        options_book=book_services.get("OPTIONS_BOOK"),
        levelone_options=levelone_options if args.with_levelone_options else None,
        absence_scan=absence,
    )
    # Explicit: semantics for NUM/EXCHANGE stay NOT_PROVEN
    for r in matrix["rows"]:
        if r["concept"] in (
            "NUM_BIDS / NUM_ASKS",
            "Nested EXCHANGE + BID_VOLUME/ASK_VOLUME",
            "Vendor 'level two' book = full MM montage",
        ):
            r["semantics"] = NOT_PROVEN

    _write_json(out_dir / "capability_matrix.json", matrix)
    _write_json(
        out_dir / "probe_manifest.json",
        {
            "ok": True,
            "stamp": stamp,
            "symbols": symbols,
            "duration_sec": args.duration_sec,
            "service_counts": service_counts,
            "n_raw_frames": len(raw_frames),
            "n_decoded_book_content_items": len(decoded_book_frames),
            "out_dir": str(out_dir),
            "single_streamer_note": (
                "Do not run alongside server order_flow_streaming or "
                "tools/run_stream_capture.py (single-streamer-owner)."
            ),
        },
    )

    # Human summary
    print("=== service_counts ===")
    print(json.dumps(service_counts, indent=2))
    print("=== NUM_* analysis ruling ===", num_analysis.get("ruling"))
    print("=== EXCHANGE analysis ruling ===", exchange_analysis.get("ruling"))
    print(f"capability_matrix → {out_dir / 'capability_matrix.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", default="SPY,QQQ,IWM")
    p.add_argument("--duration-sec", type=int, default=90)
    p.add_argument("--max-frames-per-service", type=int, default=8)
    p.add_argument("--out-dir", default="")
    p.add_argument("--with-options-book", action="store_true", default=True)
    p.add_argument("--no-options-book", action="store_true")
    p.add_argument("--with-timesales", action="store_true", default=True)
    p.add_argument("--no-timesales", action="store_true")
    p.add_argument("--with-levelone-options", action="store_true", default=False)
    args = p.parse_args(argv)
    if args.no_options_book:
        args.with_options_book = False
    if args.no_timesales:
        args.with_timesales = False
    try:
        return asyncio.run(_run_probe(args))
    except KeyboardInterrupt:
        print("interrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
