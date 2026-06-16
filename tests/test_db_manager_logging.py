import logging

from data_module.config import TWStockConfig
from data_module.db_manager import DBManager


def test_db_manager_console_handler_does_not_emit_info_startup_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "output"))
    monkeypatch.setenv("PROFILE", "test")

    logger = logging.getLogger("data_module.db_manager")
    original_handlers = list(logger.handlers)
    logger.handlers.clear()
    try:
        config = TWStockConfig()
        DBManager(config)

        stream_handlers = [
            handler
            for handler in logger.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        ]

        assert stream_handlers
        assert all(handler.level >= logging.WARNING for handler in stream_handlers)
        assert logger.propagate is False
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers[:] = original_handlers
