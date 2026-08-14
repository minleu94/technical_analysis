import logging

import data_module.data_loader as data_loader_module
from analysis_module.technical_analysis.technical_indicators import (
    TechnicalIndicatorCalculator,
)
from data_module.config import TWStockConfig
from data_module.data_loader import DataLoader
from data_module.db_manager import DBManager
from data_module.data_processor import TWMarketDataProcessor


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


def test_db_manager_falls_back_when_log_file_cannot_be_opened(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "output"))
    monkeypatch.setenv("PROFILE", "test")
    config = TWStockConfig()

    logger = logging.getLogger("data_module.db_manager")
    original_handlers = list(logger.handlers)
    file_handler_type = logging.FileHandler
    logger.handlers.clear()
    monkeypatch.setattr(
        logging,
        "FileHandler",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked log")),
    )
    try:
        manager = DBManager(config)

        assert manager.db_path.exists()
        assert any(
            isinstance(handler, logging.StreamHandler)
            for handler in logger.handlers
        )
        assert not any(
            isinstance(handler, file_handler_type)
            for handler in logger.handlers
        )
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers[:] = original_handlers


def test_data_loader_falls_back_when_log_file_cannot_be_opened(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "output"))
    monkeypatch.setenv("PROFILE", "test")
    config = TWStockConfig()

    logger = logging.getLogger("data_module.data_loader")
    original_handlers = list(logger.handlers)
    file_handler_type = logging.FileHandler
    logger.handlers.clear()
    monkeypatch.setattr(
        logging,
        "FileHandler",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked log")),
    )
    monkeypatch.setattr(data_loader_module, "DBManager", lambda _config: object())
    try:
        loader = DataLoader(config)

        assert loader.db is not None
        assert any(
            isinstance(handler, logging.StreamHandler)
            for handler in logger.handlers
        )
        assert not any(
            isinstance(handler, file_handler_type)
            for handler in logger.handlers
        )
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers[:] = original_handlers


def test_market_data_processor_falls_back_when_log_file_cannot_be_opened(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "output"))
    monkeypatch.setenv("PROFILE", "test")
    config = TWStockConfig()

    logger = logging.getLogger("data_module.data_processor")
    original_handlers = list(logger.handlers)
    file_handler_type = logging.FileHandler
    monkeypatch.setattr(
        logging,
        "FileHandler",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked log")),
    )
    try:
        processor = TWMarketDataProcessor(config=config)

        assert processor.logger is logger
        assert any(
            isinstance(handler, logging.StreamHandler)
            for handler in logger.handlers
        )
        assert not any(
            isinstance(handler, file_handler_type)
            for handler in logger.handlers
        )
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers[:] = original_handlers


def test_technical_indicator_falls_back_when_log_file_cannot_be_opened(monkeypatch):
    logger = logging.getLogger(
        "analysis_module.technical_analysis.technical_indicators"
    )
    original_handlers = list(logger.handlers)
    file_handler_type = logging.FileHandler
    monkeypatch.setattr(
        logging,
        "FileHandler",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked log")),
    )
    try:
        calculator = TechnicalIndicatorCalculator()

        assert calculator.logger is logger
        assert any(
            isinstance(handler, logging.StreamHandler)
            for handler in logger.handlers
        )
        assert not any(
            isinstance(handler, file_handler_type)
            for handler in logger.handlers
        )
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers[:] = original_handlers
