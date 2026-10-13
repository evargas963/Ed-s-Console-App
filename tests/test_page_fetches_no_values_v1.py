"""The page fetches no value (operator 2026-10-13: "No SSE notices, no follow-up fetches"): every
value it shows is pushed -- Schwab's over the daemon's socket, the console's over /api/live
(EdShell.live). What the page still sends over HTTP is a command: a watchlist add or removal, the
Flow panel's contract. Read from the page's own code (static/js), every file, every call."""
from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "static" / "js"
#: a call that sends a request: the browser's fetch, the watchlist's command helper, and the
#: browser's change stream
_CALL = re.compile(r"\b(fetch|wlFetch|EventSource)\s*\(")
_COMMAND = re.compile(r"method:\s*'(POST|DELETE)'")


def _calls() -> "list[tuple[str, int, str]]":
    """(file, line, the call's text to its closing parenthesis) of every request call."""
    out = []
    for path in sorted(JS.glob("*.js")):
        src = path.read_text(encoding="utf-8")
        for m in _CALL.finditer(src):
            line_start = src.rfind("\n", 0, m.start()) + 1
            if src[line_start:m.start()].lstrip().startswith("//") or src[m.start() - 9:m.start()] == "function ":
                continue                                  # a comment, or the helper's own name
            depth, i = 0, m.end() - 1
            while i < len(src):
                depth += {"(": 1, ")": -1}.get(src[i], 0)
                if depth == 0:
                    break
                i += 1
            out.append((path.name, src.count("\n", 0, m.start()) + 1, src[m.start():i + 1]))
    return out


def test_every_request_the_page_sends_is_a_command():
    calls = _calls()
    assert calls, "no request call found: the scan reads nothing"
    reads = [(f, n, text[:120]) for f, n, text in calls
             if not _COMMAND.search(text) and not text.startswith("fetch(url, opts)")]
    assert reads == [], f"the page reads values over HTTP: {reads}"


def test_the_one_command_helper_is_only_called_with_a_command():
    helper = [(f, n, text) for f, n, text in _calls() if text.startswith("fetch(url, opts)")]
    assert [f for f, _n, _t in helper] == ["ed-core.js"], "the command helper is the watchlist's (wlFetch)"
    wl = [text for f, _n, text in _calls() if text.startswith("wlFetch(")]
    assert wl and all(_COMMAND.search(text) for text in wl), wl
