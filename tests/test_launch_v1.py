"""The launcher (launch.py): whether a port is in use, against real local listeners on free ports.
It stops nothing: a port in use is reported and the console in it opened."""
from __future__ import annotations

import socket

import launch


def test_a_port_with_a_listener_is_in_use_and_a_free_one_is_not():
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        assert launch.in_use(port) is True
    assert launch.in_use(port) is False
