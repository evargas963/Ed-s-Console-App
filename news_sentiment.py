"""
News & sentiment context layer for EdWebConsole.

Feeds optional REST APIs (Finnhub, Alpha Vantage) into snapshots and MarketState.
Does not replace prediction or The Call — annotates risk and narrative.

Env:
  FINNHUB_API_KEY      — REST; `.env` in app dir overrides OS env when present
  ALPHAVANTAGE_API_KEY — optional; FinBERT-style scores (low free quota)
  ED_NEWS_THROTTLE_SEC        — min seconds between REST refreshes per ticker (default 90)
  ED_NEWS_HTTP_TIMEOUT_SEC    — per HTTP call timeout (default 5; CLI __main__ can use 30s deadline)
  ED_NEWS_CONTEXT_DEADLINE_SEC — max wall time for UI/server path (default 5); 0 = unlimited

Free Finnhub: `/news-sentiment` may return 403; `/company-news` + headline impact scan still run
(`available: true`, `sources: ["finnhub_company_news"]`, `finnhub_sentiment_status: plan_restriction`).
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
log = logging.getLogger(__name__)

from time_et import ET as _ET

_throttle_sec = float(__import__("os").environ.get("ED_NEWS_THROTTLE_SEC", "90"))
_lock = threading.Lock()
_last_fetch: dict[str, float] = {}
_cache: dict[str, dict[str, Any]] = {}
_pre_market_by_key: dict[str, float] = {}  # "TICKER|YYYY-MM-DD" -> composite at last premarket refresh
_av_date: str = ""
_av_calls: int = 0
_MAX_AV_PER_DAY = 22

_env_file_loaded = False


def _load_local_env_once() -> None:
    """Load `.env` then `.env.local` from app directory (later file wins; overrides OS env)."""
    global _env_file_loaded
    if _env_file_loaded:
        return
    _env_file_loaded = True
    import os
    from pathlib import Path

    try:
        base = Path(__file__).resolve().parent
        for fname in (".env", ".env.local"):
            path = base / fname
            if not path.is_file():
                continue
            for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key:
                    os.environ[key] = val
    except OSError:
        pass


CRITICAL_KEYWORDS = (
    "tariff", "sanction", "halt", "suspend trading", "fed rate", "interest rate",
    "powell", "cpi", "nvidia", "earnings miss", "earnings beat", "guidance cut",
    "guidance raise", "merger", "acquisition", "sec investigation", "bankruptcy",
    "fda approval", "fda rejection", "emergency", "default",
)


def _parse_article_datetime(raw_ts: Any) -> Optional[datetime]:
    """Finnhub company-news: unix int or (rarely) numeric string; tolerate ISO."""
    if raw_ts is None:
        return None
    try:
        if isinstance(raw_ts, (int, float)):
            return datetime.fromtimestamp(int(raw_ts), tz=_ET)
        if isinstance(raw_ts, str):
            s = raw_ts.strip()
            if s.isdigit():
                return datetime.fromtimestamp(int(s), tz=_ET)
            if s[:1] in "-0123456789" and "T" in s:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(_ET)
    except (OSError, ValueError, TypeError):
        return None
    return None


def classify_headline_impact(headline: str) -> str:
    if not headline:
        return "LOW"
    t = headline.lower()
    n = sum(1 for kw in CRITICAL_KEYWORDS if kw in t)
    if n >= 2:
        return "HIGH"
    if n == 1:
        return "MEDIUM"
    return "LOW"


@dataclass
class NewsEvent:
    timestamp: str
    source: str
    headline: str
    ticker: Optional[str]
    sentiment_score: Optional[float]
    impact_level: str
    url: str
    raw: dict


def _http_timeout_sec() -> float:
    """Per-request HTTP timeout; keep low on server hot path (Finnhub + AV)."""
    return float(__import__("os").environ.get("ED_NEWS_HTTP_TIMEOUT_SEC", "5"))


def _http_json_any(url: str, timeout: Optional[float] = None) -> tuple[Any, Optional[str]]:
    """Returns (parsed_json, error_message). Parsed value may be dict or list."""
    if timeout is None:
        timeout = _http_timeout_sec()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "EdWebConsole/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body), None
    except urllib.error.HTTPError as e:
        try:
            hint = e.read().decode("utf-8", errors="replace")[:240]
        except OSError:
            hint = ""
        msg = f"HTTP {e.code} {e.reason}" + (f" — {hint}" if hint else "")
        log.debug("news_sentiment HTTP: %s", msg[:200])
        return None, msg
    except urllib.error.URLError as e:
        log.debug("news_sentiment URL error: %s", e)
        return None, f"network: {e.reason!s}"
    except TimeoutError:
        return None, "timeout"
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    except OSError as e:
        log.debug("news_sentiment I/O: %s", e)
        return None, str(e)


def _finnhub_token() -> str:
    import os

    _load_local_env_once()
    return (os.environ.get("FINNHUB_API_KEY") or "").strip()


def _av_token() -> str:
    import os

    _load_local_env_once()
    return (os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY") or "").strip()


def fetch_finnhub_sentiment(symbol: str) -> dict[str, Any]:
    """Finnhub /news-sentiment — returns buzz + bullish/bearish percentages."""
    tok = _finnhub_token()
    out: dict[str, Any] = {
        "ok": False,
        "composite": None,
        "buzz": None,
        "company_news_score": None,
        "finnhub_error": None,
    }
    if not tok:
        out["finnhub_error"] = (
            "FINNHUB_API_KEY is empty — set Windows env var or put FINNHUB_API_KEY=... in .env next to server.py"
        )
        return out
    sym = symbol.upper().strip()
    q = urllib.parse.urlencode({"symbol": sym, "token": tok})
    data, err = _http_json_any(f"https://finnhub.io/api/v1/news-sentiment?{q}")
    if err:
        out["finnhub_error"] = err
        return out
    if not isinstance(data, dict):
        out["finnhub_error"] = f"unexpected response ({type(data).__name__})"
        return out
    if data.get("error"):
        out["finnhub_error"] = str(data.get("error"))
        return out
    out["ok"] = True
    buzz = data.get("buzz") or {}
    if isinstance(buzz, dict):
        bz = buzz.get("buzz")
        try:
            out["buzz"] = float(bz) if bz is not None else None
        except (TypeError, ValueError):
            out["buzz"] = None
    sent = data.get("sentiment") or {}  # external-key-ok: Finnhub /api/v1/news-sentiment payload (fetched this module, line ~187)
    bullish = bearish = None
    if isinstance(sent, dict):
        try:
            bull_raw = float(sent.get("bullishPercent"))  # external-key-ok: Finnhub /api/v1/news-sentiment payload (fetched this module, line ~187)
            bullish = bull_raw / 100.0 if bull_raw > 1.0 else bull_raw
        except (TypeError, ValueError):
            bullish = None
        try:
            bear_raw = float(sent.get("bearishPercent"))  # external-key-ok: Finnhub /api/v1/news-sentiment payload (fetched this module, line ~187)
            bearish = bear_raw / 100.0 if bear_raw > 1.0 else bear_raw
        except (TypeError, ValueError):
            bearish = None
    if bullish is not None and bearish is not None and (bullish + bearish) > 1e-6:
        out["composite"] = round((bullish - bearish) / max(1e-6, bullish + bearish), 4)
    cns = data.get("companyNewsScore")  # external-key-ok: Finnhub /api/v1/news-sentiment payload (fetched this module, line ~187)
    try:
        out["company_news_score"] = float(cns) if cns is not None else None
    except (TypeError, ValueError):
        out["company_news_score"] = None
    return out


def fetch_finnhub_recent_company_news(symbol: str, days_back: int = 1) -> list[dict]:
    tok = _finnhub_token()
    if not tok:
        return []
    sym = symbol.upper().strip()
    to_d = datetime.now(tz=_ET).date()
    fr_d = to_d - timedelta(days=days_back)
    q = urllib.parse.urlencode(
        {
            "symbol": sym,
            "from": fr_d.isoformat(),
            "to": to_d.isoformat(),
            "token": tok,
        }
    )
    data, err = _http_json_any(f"https://finnhub.io/api/v1/company-news?{q}")
    if err or not isinstance(data, list):
        return []
    return data[:25]


def fetch_alpha_vantage_sentiment(symbols: list[str]) -> dict[str, float]:
    """NEWS_SENTIMENT for one or more tickers; respects coarse daily call budget."""
    global _av_date, _av_calls
    tok = _av_token()
    out: dict[str, float] = {}
    if not tok or not symbols:
        return out
    today = datetime.now(tz=_ET).strftime("%Y-%m-%d")
    with _lock:
        if _av_date != today:
            _av_date = today
            _av_calls = 0
        if _av_calls >= _MAX_AV_PER_DAY:
            return out
        _av_calls += 1
    tickers = ",".join(s[:12].upper() for s in symbols[:12])
    q = urllib.parse.urlencode({"function": "NEWS_SENTIMENT", "tickers": tickers, "limit": 40, "apikey": tok})
    data, err = _http_json_any(f"https://www.alphavantage.co/query?{q}")
    if err or not isinstance(data, dict) or "feed" not in data:
        return out
    agg: dict[str, list[float]] = {}
    for art in data.get("feed") or []:  # external-key-ok: AlphaVantage NEWS_SENTIMENT payload (fetched this module, line ~266)
        for ts in art.get("ticker_sentiment") or []:  # external-key-ok: AlphaVantage NEWS_SENTIMENT payload (fetched this module, line ~266)
            sym = (ts.get("ticker") or "").upper()
            if not sym:
                continue
            rel_raw = ts.get("relevance_score")  # external-key-ok: AlphaVantage NEWS_SENTIMENT payload (fetched this module, line ~266)
            sc_raw = ts.get("ticker_sentiment_score")  # external-key-ok: AlphaVantage NEWS_SENTIMENT payload (fetched this module, line ~266)
            if rel_raw is None or sc_raw is None:
                continue
            try:
                rel = float(rel_raw)
                sc = float(sc_raw)
            except (TypeError, ValueError):
                continue
            if rel < 0.25:
                continue
            agg.setdefault(sym, []).append(sc)
    for sym, vals in agg.items():
        if vals:
            out[sym] = round(float(sum(vals) / len(vals)), 4)
    return out


def _update_pre_market_store(ticker: str, composite: Optional[float]) -> None:
    if composite is None:
        return
    now = datetime.now(tz=_ET)
    key_date = now.strftime("%Y-%m-%d")
    k = f"{ticker.upper()}|{key_date}"
    h, m = now.hour, now.minute
    # Pre-market window ET: treat as 04:00–09:30 anchor for "story at open"
    if (h < 9 or (h == 9 and m < 30)) and h >= 4:
        _pre_market_by_key[k] = float(composite)


def get_sentiment_features_for_snapshot(ctx: dict[str, Any]) -> dict[str, Any]:
    """Flatten context dict to SnapshotRow-friendly keys."""
    return {
        "sentiment_composite": ctx.get("sentiment_composite"),
        "sentiment_buzz": ctx.get("sentiment_buzz"),
        "sentiment_finnhub": ctx.get("sentiment_finnhub"),
        "sentiment_av": ctx.get("sentiment_av"),
        "breaking_news_flag": ctx.get("breaking_news_flag"),
        "breaking_news_headline": ctx.get("breaking_news_headline"),
        "pre_market_sentiment": ctx.get("pre_market_sentiment"),
    }


def _merge_finnhub_av(
    fh: dict, av_map: dict[str, float], ticker: str
) -> tuple[Optional[float], Optional[float]]:
    t = ticker.upper()
    comp_fh = fh.get("composite")
    comp_av = av_map.get(t)
    if comp_fh is not None and comp_av is not None:
        return round(0.6 * comp_fh + 0.4 * comp_av, 4), comp_av
    if comp_fh is not None:
        return comp_fh, comp_av
    if comp_av is not None:
        return comp_av, comp_av
    return None, None


def refresh_and_context(
    ticker: str,
    *,
    db: Any = None,
    throttle_sec: Optional[float] = None,
) -> dict[str, Any]:
    """
    Rate-limited refresh for one ticker. Returns API/snapshot-ready context dict.
    """
    tkr = ticker.upper().strip()
    ts = float(throttle_sec if throttle_sec is not None else _throttle_sec)
    now = time.time()

    with _lock:
        if ts > 0 and (now - _last_fetch.get(tkr, 0.0)) < ts:
            c = dict(_cache.get(tkr) or {})
            c["throttled"] = True
            c["ticker"] = tkr
            return c
        _last_fetch[tkr] = now

    fh = fetch_finnhub_sentiment(tkr)
    av_map: dict[str, float] = {}
    if _av_token():
        try:
            av_map = fetch_alpha_vantage_sentiment([tkr])
        except Exception as e:
            log.debug("Alpha Vantage sentiment: %s", e)

    composite, av_used = _merge_finnhub_av(fh, av_map, tkr)
    buzz_n = None
    if fh.get("buzz") is not None:
        try:
            bz = float(fh["buzz"])
            buzz_n = bz if 0.0 <= bz <= 1.0 else min(1.0, max(0.0, bz / 100.0))
        except (TypeError, ValueError):
            buzz_n = None

    pm_key = f"{tkr}|{datetime.now(tz=_ET).strftime('%Y-%m-%d')}"
    if fh.get("ok"):
        pm_src = composite if composite is not None else fh.get("composite")
        _update_pre_market_store(tkr, pm_src)

    pre_mkt = _pre_market_by_key.get(pm_key)

    breaking = 0
    break_h = ""
    max_imp = "LOW"
    articles = fetch_finnhub_recent_company_news(tkr, days_back=1)
    now_et = datetime.now(tz=_ET)
    for art in articles:
        headline = (art.get("headline") or "").strip()
        if not headline:
            continue
        ts_art = _parse_article_datetime(art.get("datetime"))
        if ts_art is None:
            continue
        age_sec = (now_et - ts_art).total_seconds()
        if age_sec > 900:
            continue
        imp = classify_headline_impact(headline)
        rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        if rank.get(imp, 0) >= rank.get(max_imp, 0):
            max_imp = imp
        if imp == "HIGH":
            breaking = 1
            break_h = headline[:500]
        elif imp == "MEDIUM" and not breaking:
            breaking = 1
            break_h = headline[:500]

    company_news_ok = len(articles) > 0
    # Free Finnhub tiers: /news-sentiment may 403 while /company-news works.
    feed_activity = min(1.0, len(articles) / 40.0) if company_news_ok else None

    src = []
    if fh.get("ok"):
        src.append("finnhub")
    elif company_news_ok:
        src.append("finnhub_company_news")
    if av_used is not None:
        src.append("alphavantage")

    _news_available = bool(fh.get("ok") or av_used is not None or company_news_ok)
    ctx: dict[str, Any] = {
        "ticker": tkr,
        "available": _news_available,
        "finnhub_company_news_ok": company_news_ok,
        "company_news_count": len(articles),
        "throttled": False,
        "sentiment_composite": composite
        if composite is not None
        else fh.get("composite"),
        "sentiment_buzz": buzz_n if buzz_n is not None else feed_activity,
        "sentiment_finnhub": fh.get("composite"),
        "sentiment_av": av_used,
        "breaking_news_flag": breaking if _news_available else None,
        "breaking_news_headline": break_h if breaking else ("" if _news_available else None),
        "pre_market_sentiment": pre_mkt,
        "impact_level": max_imp if breaking else ("LOW" if _news_available else None),
        "sources": src,
    }
    fe = fh.get("finnhub_error")
    if fe:
        # 403 on /news-sentiment is common on free tier while /company-news still works — don't surface as global failure.
        if company_news_ok and fe.startswith("HTTP 403"):
            ctx["finnhub_sentiment_status"] = "plan_restriction"
        else:
            ctx["finnhub_error"] = fe
    if not ctx["available"]:
        ctx["note"] = "No Finnhub key, network failure, or no company news — check FINNHUB_API_KEY and connectivity"
    elif not fh.get("ok") and company_news_ok:
        ctx["note"] = (
            "Finnhub /news-sentiment not available on this plan (403); "
            "using company news + headline scan only — upgrade Finnhub for scored sentiment"
        )
    elif not fh.get("ok") and av_used is None and company_news_ok is False:
        ctx["note"] = "Finnhub connected but no recent company news returned for this window"

    with _lock:
        _cache[tkr] = dict(ctx)
    return ctx


def refresh_and_context_for_ui(
    ticker: str,
    *,
    db: Any = None,
    throttle_sec: Optional[float] = None,
) -> dict[str, Any]:
    """
    Same as refresh_and_context but bounded wall-clock time so /api/state never
    blocks on Finnhub for long (see ED_NEWS_CONTEXT_DEADLINE_SEC, default 5s).
    On timeout, returns last cached context for that ticker if any.
    """
    import concurrent.futures
    import os

    dline = float(os.environ.get("ED_NEWS_CONTEXT_DEADLINE_SEC", "5"))
    if dline <= 0:
        return refresh_and_context(ticker, db=db, throttle_sec=throttle_sec)
    tkr = ticker.upper().strip()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(
            refresh_and_context,
            tkr,
            db=db,
            throttle_sec=throttle_sec,
        )
        try:
            return fut.result(timeout=dline)
        except concurrent.futures.TimeoutError:
            log.warning(
                "news_sentiment: context fetch exceeded %.1fs for %s",
                dline,
                tkr,
            )
            with _lock:
                cached = dict(_cache.get(tkr, {}))
            if cached:
                out = {**cached, "ticker": tkr, "timed_out": True}
                prev = (out.get("note") or "").strip()
                suffix = "prior cache (fresh fetch timed out)"
                out["note"] = f"{prev} — {suffix}" if prev else suffix
                return out
            return {
                "ticker": tkr,
                "available": False,
                "timed_out": True,
                "throttled": False,
                "note": (
                    f"News layer timed out after {dline}s "
                    "(raise ED_NEWS_CONTEXT_DEADLINE_SEC or ED_NEWS_HTTP_TIMEOUT_SEC)"
                ),
                "sources": [],
                "breaking_news_flag": None,
                "breaking_news_headline": None,
                "impact_level": None,
                "finnhub_company_news_ok": False,
                "company_news_count": 0,
            }


if __name__ == "__main__":
    import os
    import sys

    # CLI: slightly longer per-request timeout than server default unless overridden
    if "ED_NEWS_HTTP_TIMEOUT_SEC" not in os.environ:
        os.environ["ED_NEWS_HTTP_TIMEOUT_SEC"] = "12"
    _sym = (sys.argv[1] if len(sys.argv) > 1 else "SPY").upper()
    _ctx = refresh_and_context(_sym, db=None, throttle_sec=0.0)
    print(json.dumps(_ctx, indent=2, default=str))
