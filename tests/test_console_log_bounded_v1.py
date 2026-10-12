"""The console's log file is bounded: rotated at 50 MB, one previous file kept."""
import logging
from logging.handlers import RotatingFileHandler

import server


def test_the_console_log_rotates_at_50_mb_keeping_one(tmp_path):
    path = tmp_path / "ed_server.log"
    h = server.install_ed_server_file_sink(path)
    try:
        assert isinstance(h, RotatingFileHandler)
        assert (h.maxBytes, h.backupCount) == (50 * 1024 * 1024, 1)
        logging.getLogger("ed_server").info("written as it happens")
        assert "written as it happens" in path.read_text(encoding="utf-8")   # flushed per record
    finally:
        logging.getLogger().removeHandler(h)
        h.close()
