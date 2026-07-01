from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app_module.portfolio_service import PortfolioService
from app_module.live_research_gap_repository import LiveResearchGapRepository
from data_module.config import TWStockConfig


ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path):
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "gap.db"
    config.use_sqlite = True
    return config


def _seed_position(config):
    PortfolioService(config).record_trade(
        stock_code="2330",
        stock_name="TSMC",
        side="buy",
        quantity=1000,
        price=100,
        trade_date="2026-07-01",
        source_type="manual",
        source_id="",
        source_summary={"portfolio_mode": "simulated"},
        trade_id="trade-001",
    )


def _run_capture(config, *args):
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "capture_live_research_gap.py"),
        "--observation-date",
        "2026-07-08",
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


def test_capture_cli_defaults_to_dry_run_and_does_not_write(tmp_path):
    config = _config(tmp_path)
    _seed_position(config)

    result = _run_capture(config)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["positions_seen"] == 1
    assert payload["gap_observations_created"] == 0
    assert LiveResearchGapRepository(config).list_observations() == []


def test_capture_cli_confirm_writes_tmp_db(tmp_path):
    config = _config(tmp_path)
    _seed_position(config)

    result = _run_capture(config, "--confirm")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is False
    assert payload["gap_observations_created"] == 1
    assert len(LiveResearchGapRepository(config).list_observations()) == 1


def test_capture_cli_confirm_requires_explicit_db_path(tmp_path):
    config = _config(tmp_path)
    _seed_position(config)
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "capture_live_research_gap.py"),
        "--observation-date",
        "2026-07-08",
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


def test_inspect_cli_outputs_summary(tmp_path):
    config = _config(tmp_path)
    _seed_position(config)
    assert _run_capture(config, "--confirm").returncode == 0
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "inspect_live_research_gap.py"),
        "--observation-date",
        "2026-07-08",
        "--db-path",
        str(config.db_file),
        "--json-output",
    ]

    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["observations_count"] == 1
    assert payload["summary"][0]["group_by"] == "source_type"
