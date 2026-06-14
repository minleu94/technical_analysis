from pathlib import Path

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
