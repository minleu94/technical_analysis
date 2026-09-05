from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
from typing import Any

import app_module.evidence_scheduler_readiness as readiness_module
from app_module.evidence_scheduler_readiness import evaluate_evidence_scheduler_readiness
from data_module.config import TWStockConfig
from scripts import evaluate_evidence_scheduler_readiness as readiness_cli


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "working-copy.db"
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _approval_artifact(tmp_path: Path) -> Path:
    path = tmp_path / "evidence-scheduler-approval.json"
    now = datetime.now(timezone.utc)
    approved_at = (now - timedelta(minutes=1)).replace(microsecond=0)
    expires_at = (now + timedelta(hours=1)).replace(microsecond=0)
    path.write_text(
        json.dumps(
            {
                "schema_version": "evidence-production-scheduler-approval.v1",
                "approval_id": "approval-test-001",
                "owner": "test-owner",
                "approved_at": approved_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "scope": "evidence_capture_scheduler",
                "approved": True,
                "production_scheduler_allowed": True,
                "checks": {
                    "source_coverage_ready": True,
                    "dry_run_passed": True,
                    "working_copy_smoke_passed": True,
                    "diagnostics_reviewed": True,
                    "backup_verified": True,
                    "rollback_verified": True,
                    "recovery_verified": True,
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def test_readiness_evaluator_fail_closes_when_source_coverage_is_missing(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    summary = evaluate_evidence_scheduler_readiness(config, db_path=config.db_file)

    assert summary["production_scheduler_allowed"] is False
    assert summary["rule_operational_scheduler_allowed"] is True
    assert summary["required_manual_checks"]
    assert "production_scheduler_approval_missing" in summary["blocking_gaps"]
    assert summary["readiness"] in {"not_ready", "dry_run_only", "ready_for_design", "ready_for_manual_confirm"}
    assert summary["readiness"] != "production_ready"
    assert "production_ready" not in summary.values()


def test_readiness_evaluator_uses_smoke_as_diagnostic_not_manual_gate(
    tmp_path: Path,
) -> None:
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
    assert summary["required_manual_checks"]
    assert "production_scheduler_approval_missing" in summary["blocking_gaps"]


def test_readiness_evaluator_requires_validated_human_approval_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _config(tmp_path)
    approval_path = _approval_artifact(tmp_path)

    class _Coverage:
        def to_dict(self) -> dict[str, object]:
            return {
                "blocking_gaps": [],
                "warnings": [],
                "scheduler_readiness": "ready_for_design",
            }

    monkeypatch.setattr(
        readiness_module.EvidenceSourceCoverageService,
        "inspect",
        lambda self, **kwargs: _Coverage(),
    )
    monkeypatch.setattr(readiness_module, "_dashboard_available", lambda: True)

    summary = evaluate_evidence_scheduler_readiness(
        config,
        db_path=config.db_file,
        approval_artifact_path=approval_path,
    )

    assert summary["readiness"] == "operational_production"
    assert summary["production_scheduler_allowed"] is True
    assert summary["evidence_capture_scheduler_allowed"] is True
    assert summary["required_manual_checks"] == []
    assert summary["formal_evidence_credit_allowed"] is False
    assert summary["ml_nonzero_alpha_allowed"] is False
    assert summary["approval_artifact"]["approval_id"] == "approval-test-001"


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


def test_readiness_cli_defaults_to_twstock_config_database(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    data_root = tmp_path / "formal-data"
    output_root = tmp_path / "formal-output"
    captured: dict[str, Any] = {}

    def fake_evaluate(
        config: TWStockConfig,
        *,
        db_path: str | Path,
        smoke_report_path: str | Path | None = None,
        decision_date: str | None = None,
        result_id: str | None = None,
        approval_artifact_path: str | Path | None = None,
    ) -> dict[str, object]:
        captured["config"] = config
        captured["db_path"] = Path(db_path)
        captured["smoke_report_path"] = smoke_report_path
        captured["decision_date"] = decision_date
        captured["result_id"] = result_id
        captured["approval_artifact_path"] = approval_artifact_path
        return {"readiness": "not_ready", "production_scheduler_allowed": False}

    monkeypatch.setenv("DATA_ROOT", str(data_root))
    monkeypatch.setenv("OUTPUT_ROOT", str(output_root))
    monkeypatch.setenv("PROFILE", "prod")
    monkeypatch.setattr(
        readiness_cli,
        "evaluate_evidence_scheduler_readiness",
        fake_evaluate,
    )

    assert readiness_cli.main([]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert captured["db_path"] == data_root / "sqlite" / "twstock.db"
    assert payload["production_scheduler_allowed"] is False
