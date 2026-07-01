from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app_module.decision_quality_repository import DecisionQualityRepository
from app_module.portfolio_service import PortfolioService
from data_module.config import TWStockConfig


ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "decision_quality_cli.db"
    config.use_sqlite = True
    return config


def _seed(config: TWStockConfig) -> None:
    PortfolioService(config).record_trade(
        stock_code="2330",
        stock_name="TSMC",
        side="buy",
        quantity=1000,
        price=100,
        trade_date="2026-06-10",
        trade_id="trade-cli",
    )


def _capture(config: TWStockConfig, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "capture_decision_quality_review.py"),
        "--review-type",
        "monthly",
        "--start-date",
        "2026-06-01",
        "--end-date",
        "2026-06-30",
        "--db-path",
        str(config.db_file),
        "--data-root",
        str(config.data_root),
        "--output-root",
        str(config.output_root),
        "--json-output",
        *args,
    ]
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def test_capture_cli_defaults_to_dry_run_and_does_not_write(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed(config)

    result = _capture(config)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["items_seen"] >= 1
    assert payload["items_created"] == 0
    assert DecisionQualityRepository(config).list_reviews() == []


def test_capture_cli_confirm_writes_tmp_db(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed(config)

    result = _capture(config, "--confirm")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is False
    assert payload["items_created"] >= 1
    assert len(DecisionQualityRepository(config).list_reviews()) == 1


def test_capture_cli_confirm_requires_explicit_db_path(tmp_path: Path) -> None:
    config = _config(tmp_path)
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "capture_decision_quality_review.py"),
        "--review-type",
        "weekly",
        "--start-date",
        "2026-06-24",
        "--end-date",
        "2026-06-30",
        "--data-root",
        str(config.data_root),
        "--output-root",
        str(config.output_root),
        "--confirm",
        "--json-output",
    ]

    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)

    assert result.returncode != 0
    assert "explicit --db-path" in result.stderr


def test_inspect_cli_outputs_read_only_summary(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed(config)
    assert _capture(config, "--confirm").returncode == 0
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "inspect_decision_quality.py"),
        "--start-date",
        "2026-06-01",
        "--end-date",
        "2026-06-30",
        "--db-path",
        str(config.db_file),
        "--data-root",
        str(config.data_root),
        "--output-root",
        str(config.output_root),
        "--json-output",
    ]

    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["saved_reviews_count"] == 1
    assert payload["candidate_review"]["review_type"] == "custom"
    assert payload["candidate_items_seen"] >= 1
