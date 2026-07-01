from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from app_module.evidence_scheduler_readiness import evaluate_evidence_scheduler_readiness
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "working-copy.db"
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def test_readiness_evaluator_never_allows_production_scheduler(tmp_path: Path) -> None:
    config = _config(tmp_path)

    summary = evaluate_evidence_scheduler_readiness(config, db_path=config.db_file)

    assert summary["production_scheduler_allowed"] is False
    assert summary["readiness"] in {"not_ready", "dry_run_only", "ready_for_design", "ready_for_manual_confirm"}
    assert summary["readiness"] != "production_ready"
    assert "production_ready" not in summary.values()


def test_readiness_evaluator_uses_smoke_report_but_still_requires_manual_approval(tmp_path: Path) -> None:
    config = _config(tmp_path)
    smoke_report = tmp_path / "smoke.json"
    smoke_report.write_text(
        json.dumps(
            {
                "readiness_after_smoke": "ready_for_manual_confirm",
                "idempotency_check": {"passed": True},
                "blocking_gaps": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    summary = evaluate_evidence_scheduler_readiness(config, db_path=config.db_file, smoke_report_path=smoke_report)

    assert summary["latest_smoke_status"] == "passed"
    assert summary["working_copy_confirm_passed"] is True
    assert summary["production_scheduler_allowed"] is False
    assert "manual approval" in " ".join(summary["required_manual_checks"]).lower()


def test_readiness_cli_outputs_json(tmp_path: Path) -> None:
    config = _config(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate_evidence_scheduler_readiness.py",
            "--db-path",
            str(config.db_file),
            "--data-root",
            str(config.data_root),
            "--output-root",
            str(config.output_root),
            "--json-output",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["production_scheduler_allowed"] is False
    assert payload["readiness"] != "production_ready"
