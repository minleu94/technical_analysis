from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from tests.fixtures.portfolio_ml_ooc_support import run_synthetic_ml_cli


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "build_ml_pit_year_shards.py"


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE daily_prices (
                日期 TEXT,
                證券代號 TEXT,
                成交股數 INTEGER,
                收盤價 TEXT
            );
            INSERT INTO daily_prices VALUES
                ('20240102', '2330', 1000, '100.25'),
                ('20240102', '2317', 2000, '50.50');
            """
        )


def _run(database: Path, output: Path, *universe: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    return run_synthetic_ml_cli(
        [
            sys.executable,
            str(SCRIPT),
            "--database",
            str(database),
            "--output-dir",
            str(output),
            "--decision-at",
            "2024-01-03",
            "--history-start-date",
            "2024-01-01",
            *universe,
            "--years",
            "2024",
            "--batch-size",
            "1",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_cli_supports_bounded_symbols_and_emits_raw_stage_manifest(
    tmp_path: Path,
) -> None:
    database = tmp_path / "source.db"
    _database(database)
    result = _run(database, tmp_path / "out", "--symbols", "2330")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["sqlite_mode"] == "ro"
    assert payload["query_only"] is True
    assert payload["parquet_dependency_added"] is False
    manifest = json.loads(
        Path(payload["manifest_path"]).read_text(encoding="utf-8")
    )
    assert manifest["stage"] == "raw_pit_observations"
    assert manifest["training_adapter"]["direct_training_input"] is False
    assert (
        manifest["training_adapter"]["target_schema_version"]
        == "allocation-training-input-v1"
    )
    assert manifest["scope"]["symbols"] == ["2330"]


def test_cli_requires_explicit_bounded_or_all_universe(tmp_path: Path) -> None:
    database = tmp_path / "source.db"
    _database(database)
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--database",
            str(database),
            "--output-dir",
            str(tmp_path / "out"),
            "--decision-at",
            "2024-01-03",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 2
    assert "--symbols" in result.stderr
    assert "--all-universe" in result.stderr


def test_cli_supports_explicit_all_universe(tmp_path: Path) -> None:
    database = tmp_path / "source.db"
    _database(database)
    result = _run(database, tmp_path / "out", "--all-universe")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    manifest = json.loads(
        Path(payload["manifest_path"]).read_text(encoding="utf-8")
    )
    assert manifest["scope"]["all_universe"] is True
    assert manifest["scope"]["symbols"] is None
