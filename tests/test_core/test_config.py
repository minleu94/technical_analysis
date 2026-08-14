from pathlib import Path
import logging

from data_module.config import TWStockConfig


def test_config_builds_paths_from_injected_roots(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"

    config = TWStockConfig(
        data_root=data_root,
        output_root=output_root,
        profile="prod",
    )

    assert config.data_root == data_root
    assert config.output_root == output_root
    assert config.base_dir == data_root
    assert config.daily_price_dir == data_root / "daily_price"
    assert config.meta_data_dir == data_root / "meta_data"
    assert config.technical_dir == data_root / "technical_analysis"
    assert config.db_file == data_root / "sqlite" / "twstock.db"
    assert (
        config.monthly_revenue_availability_file
        == data_root / "meta_data" / "monthly_revenue_availability.csv"
    )
    assert (
        config.statement_availability_file
        == data_root / "meta_data" / "fundamental_statement_availability.csv"
    )


def test_config_creates_required_directories(tmp_path: Path) -> None:
    config = TWStockConfig(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        profile="prod",
    )

    assert config.daily_price_dir.is_dir()
    assert config.meta_data_dir.is_dir()
    assert config.technical_dir.is_dir()
    assert config.backup_dir.is_dir()
    assert config.sqlite_dir.is_dir()
    assert config.output_root.is_dir()


def test_config_falls_back_to_console_when_log_file_is_unwritable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    logger = logging.getLogger("data_module.config")
    original_handlers = list(logger.handlers)
    file_handler_type = logging.FileHandler
    logger.handlers.clear()

    def raise_permission_error(*args, **kwargs):
        raise PermissionError("log path is read-only")

    monkeypatch.setattr(logging, "FileHandler", raise_permission_error)
    try:
        TWStockConfig(
            data_root=tmp_path / "data",
            output_root=tmp_path / "output",
            profile="prod",
        )

        assert any(
            isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, file_handler_type)
            for handler in logger.handlers
        )
        assert not any(isinstance(handler, file_handler_type) for handler in logger.handlers)
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers[:] = original_handlers
