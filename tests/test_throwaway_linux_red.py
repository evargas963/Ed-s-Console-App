"""Throwaway: red on Linux only. Never merged."""

import sys


def test_red_on_linux_only():
    assert sys.platform == "win32"
