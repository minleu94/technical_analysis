from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app_module.evidence_event_dtos import EvidenceEvent, EvidenceOutcome
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.signal_decay_repository import SignalDecayRepository
from data_module.config import TWStockConfig


ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "signal_decay.db"
    config.use_sqlite = True
    return config


def _seed(config: TWStockConfig, count: int = 12) -> None:
    repo = EvidenceEventRepository(config)
    for index in range(count):
        event = EvidenceEvent(
            event_id=f"evt-{index}",
            event_hash=f"hash-{index}",
            event_date=f"2026-06-{index + 1:02d}",
            decision_date=f"2026-06-{index + 1:02d}",
            symbol=f"23{index:02d}",
            event_type="recommendation_included",
            event_family="recommendation",
            source_type="recommendation",
            data_quality="observed",
            as_of_date="2026-06-01",
            available_date="2026-06-01",
        )
        repo.insert_event(event)
        repo.upsert_outcome(
            EvidenceOutcome(
                outcome_id=f"out-{index}",
                event_id=event.event_id,
                window_days=20,
                benchmark_excess_bp=100,
                industry_excess_bp=100,
                max_adverse_excursion_bp=-100,
                outcome_status="ready",
                data_quality="observed",
            )
        )


def _run_capture(config: TWStockConfig, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "capture_signal_decay.py"),
        "--observation-date",
        "2026-07-09",
        "--db-path",
        str(config.db_file),
        "--data-root",
        str(config.data_root),
        "--output-root",
        str(config.output_root),
        "--scope",
        "event_type",
        "--scope-id",
        "recommendation_included",
        "--short-window-events",
        "5",
        "--long-window-events",
        "12",
        "--min-sample-size",
        "3",
        "--json-output",
        *args,
    ]
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def test_capture_cli_defaults_to_dry_run_and_does_not_write(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed(config)

    result = _run_capture(config)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["observations_created"] == 0
    assert payload["scopes_evaluated"] == 1
    assert SignalDecayRepository(config).list_observations() == []


def test_capture_cli_confirm_writes_explicit_tmp_db(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed(config)

    result = _run_capture(config, "--confirm")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is False
    assert payload["observations_created"] == 1
    assert len(SignalDecayRepository(config).list_observations()) == 1


def test_capture_cli_confirm_requires_explicit_db_path(tmp_path: Path) -> None:
    config = _config(tmp_path)
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "capture_signal_decay.py"),
        "--observation-date",
        "2026-07-09",
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


def test_inspect_cli_outputs_summary(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed(config)
    assert _run_capture(config, "--confirm").returncode == 0
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "inspect_signal_decay.py"),
        "--observation-date",
        "2026-07-09",
        "--db-path",
        str(config.db_file),
        "--json-output",
    ]

    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["observations_count"] == 1
    assert payload["summary"]["observations_count"] == 1

