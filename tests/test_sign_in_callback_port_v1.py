"""The sign-in's wait for its callback port (schwab_client._wait_for_callback_port).

A real socket on this machine: ready once something listens on the port, not ready while nothing
does, and the wait ends at its limit.
"""

from __future__ import annotations

import socket

import schwab_client as sc
import time_et


def test_the_callback_port_is_ready_only_once_something_listens_on_it():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert sc._wait_for_callback_port("127.0.0.1", port, timeout=5.0) is True
    began = time_et.elapsed()
    assert sc._wait_for_callback_port("127.0.0.1", port, timeout=0.5) is False
    assert 0.5 <= time_et.elapsed() - began < 5.0
