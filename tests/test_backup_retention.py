from pathlib import Path

from data_module.backup_retention import create_retained_backup
from data_module.config import TWStockConfig


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_create_retained_backup_keeps_latest_five_dates(tmp_path):
    source = tmp_path / "twstock.db"
    backup_dir = tmp_path / "backup"
    _write(source, "current")

    existing_names = [
        "twstock_statement_items_backfill_20260101_090000.db",
        "twstock_statement_items_backfill_20260102_090000.db",
        "twstock_statement_items_backfill_20260103_090000.db",
        "twstock_statement_items_backfill_20260104_090000.db",
        "twstock_statement_items_backfill_20260105_090000.db",
        "twstock_statement_items_backfill_20260106_090000.db",
        "twstock_statement_items_backfill_20260106_120000.db",
        "twstock_statement_items_backfill_20260107_090000.db",
    ]
    for name in existing_names:
        _write(backup_dir / name, name)

    backup_file = create_retained_backup(
        source,
        backup_dir,
        label="statement_items_backfill",
        timestamp="20260108_090000",
    )

    assert backup_file == backup_dir / "twstock_statement_items_backfill_20260108_090000.db"
    assert backup_file.read_text(encoding="utf-8") == "current"
    assert sorted(path.name for path in backup_dir.glob("twstock_statement_items_backfill_*.db")) == [
        "twstock_statement_items_backfill_20260104_090000.db",
        "twstock_statement_items_backfill_20260105_090000.db",
        "twstock_statement_items_backfill_20260106_120000.db",
        "twstock_statement_items_backfill_20260107_090000.db",
        "twstock_statement_items_backfill_20260108_090000.db",
    ]


def test_create_retained_backup_does_not_delete_other_prefixes(tmp_path):
    source = tmp_path / "twstock.db"
    backup_dir = tmp_path / "backup"
    _write(source, "current")
    _write(backup_dir / "twstock_other_backfill_20260101_090000.db", "keep")

    create_retained_backup(
        source,
        backup_dir,
        label="statement_items_backfill",
        timestamp="20260108_090000",
    )

    assert (backup_dir / "twstock_other_backfill_20260101_090000.db").exists()


def test_config_backup_cleanup_does_not_delete_labeled_twstock_backups(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "output"))
    config = TWStockConfig()
    source = config.sqlite_dir / "twstock.db"
    _write(source, "current")
    labeled_backup = config.backup_dir / "twstock_fundamental_schema_20260101_090000.db"
    _write(labeled_backup, "schema")

    for day in range(2, 9):
        _write(config.backup_dir / f"twstock_202601{day:02d}_090000.db", str(day))

    config.create_backup(source, config.backup_dir / "twstock_20260109_090000.db")

    assert labeled_backup.exists()
