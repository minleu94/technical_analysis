from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "inspect_ml_all_field_readiness.py"


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE daily_prices (
                日期 TEXT,
                證券代號 TEXT,
                證券名稱 TEXT,
                成交股數 INTEGER,
                收盤價 REAL
            );
            CREATE TABLE downstream_outputs (
                stock_id TEXT,
                decision_date TEXT,
                target_weight_bp INTEGER,
                custom_metric REAL
            );
            INSERT INTO daily_prices VALUES
                ('20240102', '2330', '台積電', 100, 100.25),
                ('20240103', '2330', '台積電', 120, 101.50),
                ('20240104', '2330', '台積電', 130, 102.75);
            """
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run(database: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--database",
            str(database),
            "--decision-at",
            "2024-01-04T08:30:00+08:00",
            "--history-start-date",
            "2024-01-01",
            "--symbols",
            "2330",
            *extra,
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_cli_emits_all_table_matrix_and_dataset_manifests_without_db_write(
    tmp_path: Path,
) -> None:
    database = tmp_path / "readiness.db"
    _database(database)
    before_hash = _sha256(database)
    before_stat = database.stat()

    result = _run(database)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_version"] == "ml-all-field-readiness.v1"
    assert report["eligibility"]["table_count"] == 2
    assert report["eligibility"]["column_count"] == 9
    assert report["eligibility"]["source_unreviewed_count"] == 0
    records = {
        record["feature_id"]: record for record in report["eligibility"]["records"]
    }
    assert (
        records["downstream_outputs.custom_metric"]["eligibility_status"]
        == "unreviewed"
    )
    assert (
        records["downstream_outputs.target_weight_bp"]["eligibility_status"]
        == "excluded_leakage"
    )
    core = report["datasets"]["core_long_history"]
    enriched = report["datasets"]["all_field_enriched"]
    research_shadow = report["datasets"]["research_shadow_all_fields"]
    assert "daily_prices.收盤價" in core["feature_ids"]
    assert "downstream_outputs.custom_metric" not in enriched["feature_ids"]
    assert "downstream_outputs.target_weight_bp" not in enriched["feature_ids"]
    assert core["manifest_hash"].startswith("sha256:")
    assert enriched["manifest_hash"].startswith("sha256:")
    assert research_shadow["manifest_hash"].startswith("sha256:")
    assert "research_shadow" not in enriched["included_statuses"]
    assert "research_shadow" in research_shadow["included_statuses"]
    assert report["masks"]["missing_is_not_zero"] is True
    assert report["snapshot"]["snapshot_hash"].startswith("sha256:")
    assert report["safety"]["query_only"] is True
    assert report["safety"]["unreviewed_training_allowed"] is False

    after_stat = database.stat()
    assert _sha256(database) == before_hash
    assert (after_stat.st_size, after_stat.st_mtime_ns) == (
        before_stat.st_size,
        before_stat.st_mtime_ns,
    )


def test_cli_writes_only_explicit_release_output_directory(tmp_path: Path) -> None:
    database = tmp_path / "readiness.db"
    _database(database)
    output_dir = tmp_path / "output" / "release_v4"
    before_hash = _sha256(database)

    result = _run(database, "--output-dir", str(output_dir))

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    expected = {
        "ml_all_field_readiness.json",
        "feature_eligibility_matrix.json",
        "core_long_history_manifest.json",
        "all_field_enriched_manifest.json",
        "research_shadow_all_fields_manifest.json",
    }
    assert {path.name for path in output_dir.iterdir()} == expected
    assert {Path(path).name for path in report["written_artifacts"]} == expected
    readiness = json.loads(
        (output_dir / "ml_all_field_readiness.json").read_text(encoding="utf-8")
    )
    assert readiness["report_hash"] == report["report_hash"]
    assert _sha256(database) == before_hash
