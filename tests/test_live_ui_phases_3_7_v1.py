"""Instant-UI Phases 3–7 seams. Each expected value is independently derived."""
from __future__ import annotations


def test_token_write_is_atomic_temp_replace(tmp_path):
    from schwab_client import write_token_file_atomically

    dest = tmp_path / "schwab_token.json"
    payload = {"access_token": "aaa", "refresh_token": "bbb"}
    write_token_file_atomically(str(dest), payload)
    text = dest.read_text(encoding="utf-8")
    assert '"access_token": "aaa"' in text
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == [], leftovers
