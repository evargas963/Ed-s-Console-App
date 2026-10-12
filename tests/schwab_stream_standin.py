"""Schwab's streamer, played by a local WebSocket server, for tests that run the capture daemon's
connection (capture.Daemon.run) through the real schwab-py StreamClient: it logs in (Schwab's
REST user preferences point schwab-py at it, tests/schwab_rest_standin.py) and answers each
request as Schwab does, in its response frame (docs/schwab/schwab_streamer_api.pdf: service,
command, requestid, timestamp, content {code, msg}).

Real data: Schwab's answers to an ADD past LEVELONE_OPTIONS' 3,000 symbols, as the daemon logged
them on 2026-10-07 04:40:39 (logs/stream_capture.log): code 19 "You've reached the maximum number of
symbols allowed.  (LEVELONE_OPTIONS=3000, DISCARDED=2181)", then code 24 "ADD command failed".
STAND-INS: the login and a code-0 answer's message (Schwab's were not logged); the limit (`limits`,
per service) a test sets; which symbols of a request past the limit Schwab keeps (the first ones).
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import defaultdict

from websockets.asyncio.server import serve


def refusal(service: str, limit: int, discarded: int) -> str:
    """Schwab's code-19 message, as logged on 2026-10-07 (two spaces before the parenthesis)."""
    return f"You've reached the maximum number of symbols allowed.  ({service}={limit}, DISCARDED={discarded})"


class LocalStreamer:
    """The streamer on 127.0.0.1 (`url`). Each request it receives is kept (`requests`), with the
    frames it answered (`answers`). SUBS/ADD hold the keys asked for up to `limits[service]`;
    past it, the request is answered twice: code 19 (refusal) and then code 24
    ("<COMMAND> command failed"), as Schwab answered on 2026-10-07. UNSUBS releases them."""

    def __init__(self, limits: "dict[str, int] | None" = None):
        self.limits = dict(limits or {})
        self.requests: list = []
        self.answers: list = []
        self.held: "dict[str, list[str]]" = defaultdict(list)
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()
        self.stop = None

        async def main():
            self.stop = asyncio.Event()
            async with serve(self._client, "127.0.0.1", 0) as server:
                self.url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
                ready.set()
                await self.stop.wait()

        self.thread = threading.Thread(target=self.loop.run_until_complete, args=(main(),), daemon=True)
        self.thread.start()
        ready.wait(10)

    async def _client(self, ws) -> None:
        async for raw in ws:
            for req in json.loads(raw)["requests"]:
                self.requests.append(req)
                for frame in self.answer(req):
                    self.answers.append(frame)
                    await ws.send(json.dumps(frame))

    def answer(self, req: dict) -> "list[dict]":
        service, command = req["service"], req["command"]

        def response(code: int, msg: str) -> dict:
            return {"response": [{"service": service, "command": command, "requestid": req["requestid"],
                                  "SchwabClientCorrelId": req["SchwabClientCorrelId"],
                                  "timestamp": int(time.time() * 1000), "content": {"code": code, "msg": msg}}]}
        if service == "ADMIN":
            return [response(0, f"{command} command succeeded")]
        keys = req["parameters"]["keys"].split(",")
        held = self.held[service]
        if command == "UNSUBS":
            self.held[service] = [k for k in held if k not in keys]
            return [response(0, "UNSUBS command succeeded")]
        if command == "SUBS":
            held = self.held[service] = []
        new = [k for k in keys if k not in held]
        limit = self.limits[service] if service in self.limits else len(held) + len(new)
        kept = new[:max(0, limit - len(held))]
        held.extend(kept)
        if len(kept) < len(new):
            return [response(19, refusal(service, limit, len(new) - len(kept))),
                    response(24, f"{command} command failed")]
        return [response(0, f"{command} command succeeded")]

    def asked(self, service: str) -> "list[tuple[str, list[str]]]":
        """(command, keys) of each request on `service`, in order."""
        return [(r["command"], r["parameters"]["keys"].split(",")) for r in self.requests if r["service"] == service]

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.stop.set)
        self.thread.join(10)
