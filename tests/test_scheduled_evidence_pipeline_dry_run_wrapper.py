from __future__ import annotations

import io
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.scheduled import run_scheduled_evidence_pipeline_dry_run


def test_scheduled_wrapper_stdout_survives_cp1252_console_with_chinese_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "輸出"
    db_path = tmp_path / "資料" / "sqlite" / "twstock.db"

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="pipeline ok\n")

    output_buffer = io.BytesIO()
    stdout = io.TextIOWrapper(output_buffer, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(subprocess, "run", fake_run)

    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        [
            "--dry-run",
            "--data-root",
            str(tmp_path / "資料"),
            "--output-root",
            str(output_root),
            "--db-path",
            str(db_path),
            "--sources",
            "all",
        ]
    )

    stdout.flush()
    raw_output = output_buffer.getvalue().decode("cp1252")
    payload = json.loads(raw_output)
    assert exit_code == 0
    assert payload["db_path"] == str(db_path)
    assert payload["confirm"] is False
    assert payload["production_scheduler_allowed"] is False
    assert payload["manual_action_required"] is True
    assert "輸出" in payload["report_path"]
    assert "\\u8f38\\u51fa" in raw_output
    assert (output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json").exists()


def test_scheduled_wrapper_persists_pipeline_source_coverage_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "output"
    db_path = tmp_path / "data" / "sqlite" / "twstock.db"
    paper_operation_root = tmp_path / "paper-operation"
    paper_health_baseline = tmp_path / "health" / "baseline.json"
    paper_status_path = tmp_path / "paper-status.json"
    freshness_status_path = output_root / "scheduled" / "data_freshness" / "latest_status.json"
    freshness_status_path.parent.mkdir(parents=True)
    freshness_status_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    pipeline_summary = {
        "overall_status": "degraded",
        "warnings_count": 3,
        "warning_counts": {"screening_matrix_missing": 2, "diagnostic:source_missing_screening_matrix": 1},
        "errors_count": 0,
        "blocking_gaps": [],
        "diagnostic_codes": ["source_missing_screening_matrix"],
        "scheduler_readiness_before": "dry_run_only",
        "scheduler_readiness_after": "ready_for_manual_confirm",
        "source_coverage": {
            "warnings": ["screening_matrix_missing"],
            "blocking_gaps": [],
            "recommendation_screening_matrix_available": False,
            "recommendation_exclusion_payload_available": True,
            "source_coverage_basis": "dry_run_transient_decision_desk_snapshot",
        },
    }

    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = args[0]
        stdout = "config log before json\n" + json.dumps(pipeline_summary)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        [
            "--dry-run",
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(output_root),
            "--db-path",
            str(db_path),
            "--sources",
            "all",
            "--paper-evidence-operation-root",
            str(paper_operation_root),
            "--paper-evidence-health-baseline",
            str(paper_health_baseline),
            "--paper-evidence-status-path",
            str(paper_status_path),
        ]
    )

    status_path = output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "degraded"
    assert payload["pipeline_overall_status"] == "degraded"
    assert payload["pipeline_summary_available"] is True
    assert payload["pipeline_warning_counts"] == {
        "diagnostic:source_missing_screening_matrix": 1,
        "screening_matrix_missing": 2,
    }
    assert payload["pipeline_warning_unique_count"] == 2
    assert payload["pipeline_warning_top_counts"] == [
        {"warning": "screening_matrix_missing", "count": 2},
        {"warning": "diagnostic:source_missing_screening_matrix", "count": 1},
    ]
    assert payload["pipeline_diagnostic_codes"] == ["source_missing_screening_matrix"]
    assert payload["source_coverage_warnings"] == ["screening_matrix_missing"]
    assert payload["recommendation_screening_matrix_available"] is False
    assert payload["recommendation_exclusion_payload_available"] is True
    assert payload["source_coverage_basis"] == "dry_run_transient_decision_desk_snapshot"
    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("--data-root") + 1] == str(tmp_path / "data")
    assert command[command.index("--output-root") + 1] == str(output_root)
    assert command[command.index("--paper-evidence-operation-root") + 1] == str(paper_operation_root)
    assert command[command.index("--paper-evidence-health-baseline") + 1] == str(paper_health_baseline)
    assert command[command.index("--paper-evidence-status-path") + 1] == str(paper_status_path)
    assert payload["pipeline_actionable_warning_count"] == 3
    assert payload["manual_action_required"] is True
    assert payload["natural_maturity_only"] is False


def test_scheduled_wrapper_marks_only_future_outcomes_as_natural_maturity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "output"
    db_path = tmp_path / "data" / "sqlite" / "twstock.db"
    freshness_path = output_root / "scheduled" / "data_freshness" / "latest_status.json"
    freshness_path.parent.mkdir(parents=True)
    freshness_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    pipeline_summary = {
        "overall_status": "degraded",
        "dry_run": True,
        "confirm": False,
        "warnings_count": 2,
        "warning_counts": {"insufficient_future_data": 2},
        "advisories_count": 1,
        "advisory_counts": {"portfolio_alerts_chip_estimated:2330": 1},
        "errors_count": 0,
        "blocking_gaps": [],
        "source_coverage": {},
    }

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(pipeline_summary),
        ),
    )

    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        [
            "--dry-run",
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(output_root),
            "--db-path",
            str(db_path),
        ]
    )

    payload = json.loads(
        (output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json").read_text(
            encoding="utf-8"
        )
    )
    assert exit_code == 0
    assert payload["status"] == "degraded"
    assert payload["pipeline_natural_maturity_warning_count"] == 2
    assert payload["pipeline_natural_maturity_warning_counts"] == {"insufficient_future_data": 2}
    assert payload["pipeline_actionable_warning_count"] == 0
    assert payload["manual_action_required"] is False
    assert payload["natural_maturity_only"] is True
    assert payload["dry_run"] is True
    assert payload["confirm"] is False
    assert payload["writes_evidence_db"] is False
    assert payload["production_scheduler_allowed"] is False


def test_scheduled_wrapper_preserves_ready_with_advisories(tmp_path: Path, monkeypatch) -> None:
    output_root = tmp_path / "output"
    db_path = tmp_path / "data" / "sqlite" / "twstock.db"
    freshness_path = output_root / "scheduled" / "data_freshness" / "latest_status.json"
    freshness_path.parent.mkdir(parents=True)
    freshness_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    pipeline_summary = {
        "overall_status": "ready_with_advisories",
        "warnings_count": 0,
        "warning_counts": {},
        "advisories_count": 2,
        "advisory_counts": {"portfolio_alerts_chip_estimated:2330": 1},
        "errors_count": 0,
        "blocking_gaps": [],
        "source_coverage": {},
    }

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(pipeline_summary)),
    )

    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        ["--dry-run", "--data-root", str(tmp_path / "data"), "--output-root", str(output_root), "--db-path", str(db_path)]
    )

    payload = json.loads((output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "ready_with_advisories"
    assert payload["pipeline_advisories_count"] == 2
    assert payload["pipeline_advisory_counts"] == {"portfolio_alerts_chip_estimated:2330": 1}


def test_scheduled_wrapper_refreshes_paper_health_before_child(tmp_path: Path, monkeypatch) -> None:
    output_root = tmp_path / "output"
    db_path = tmp_path / "data" / "sqlite" / "twstock.db"
    paper_operation_root = tmp_path / "paper-operation"
    health_path = output_root / "position_health" / "latest.json"
    freshness_path = output_root / "scheduled" / "data_freshness" / "latest_status.json"
    freshness_path.parent.mkdir(parents=True)
    freshness_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeHealthRefresh:
        def __init__(self, **kwargs: object) -> None:
            captured["health_init"] = kwargs

        def refresh(self, **kwargs: object) -> dict[str, object]:
            captured["health_refresh"] = kwargs
            health_path.parent.mkdir(parents=True, exist_ok=True)
            health_path.write_text("{}\n", encoding="utf-8")
            return {
                "status": "passed",
                "latest_path": str(health_path),
                "baseline_path": str(health_path),
                "blockers": [],
                "warnings": [],
            }

    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "PositionHealthDailyRefreshService",
        FakeHealthRefresh,
    )
    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "scheduled_now",
        lambda: datetime(2026, 9, 8, 5, 15, tzinfo=ZoneInfo("America/Los_Angeles")),
    )

    pipeline_summary = {
        "overall_status": "ready",
        "warnings_count": 0,
        "warning_counts": {},
        "errors_count": 0,
        "blocking_gaps": [],
        "source_coverage": {},
    }

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = args[0]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(pipeline_summary))

    monkeypatch.setattr(subprocess, "run", fake_run)
    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        [
            "--dry-run",
            "--refresh-paper-health",
            "--paper-evidence-operation-root",
            str(paper_operation_root),
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(output_root),
            "--db-path",
            str(db_path),
        ]
    )

    payload = json.loads(
        (output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json").read_text(
            encoding="utf-8"
        )
    )
    command = captured["command"]
    assert exit_code == 0
    assert isinstance(command, list)
    assert command[command.index("--paper-evidence-health-baseline") + 1] == str(health_path)
    assert payload["paper_health_refresh_status"] == "passed"
    assert payload["paper_evidence_health_baseline"] == str(health_path)
    assert payload["paper_evidence_health_status_path"] == str(
        paper_operation_root / "scheduled" / "paper_portfolio_isolated" / "latest_status.json"
    )
    assert payload["paper_evidence_ledger_db"] == str(
        paper_operation_root / "paper_trade_ledger.sqlite"
    )
    health_init = captured["health_init"]
    assert isinstance(health_init, dict)
    assert str(health_init["coverage_status_path"]) == str(
        paper_operation_root / "scheduled" / "paper_portfolio_isolated" / "latest_status.json"
    )
    assert str(health_init["ledger_db_path"]) == str(
        paper_operation_root / "paper_trade_ledger.sqlite"
    )
    assert payload["manual_action_required"] is False


def test_scheduled_wrapper_blocks_stale_health_when_refresh_is_blocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "output"
    db_path = tmp_path / "data" / "sqlite" / "twstock.db"
    paper_operation_root = tmp_path / "paper-operation"
    health_path = output_root / "position_health" / "latest.json"
    health_path.parent.mkdir(parents=True)
    stale_health = json.dumps(
        {"decision_date": "2026-09-07", "positions": [{"stock_code": "2330"}]},
        sort_keys=True,
    ) + "\n"
    health_path.write_text(stale_health, encoding="utf-8")
    freshness_path = output_root / "scheduled" / "data_freshness" / "latest_status.json"
    freshness_path.parent.mkdir(parents=True)
    freshness_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeHealthRefresh:
        def __init__(self, **kwargs: object) -> None:
            captured["health_init"] = kwargs

        def refresh(self, **kwargs: object) -> dict[str, object]:
            captured["health_refresh"] = kwargs
            return {
                "status": "blocked",
                "latest_path": str(health_path),
                "blockers": ["paper_status_missing"],
                "warnings": [],
            }

    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "PositionHealthDailyRefreshService",
        FakeHealthRefresh,
    )
    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "scheduled_now",
        lambda: datetime(2026, 9, 8, 5, 15, tzinfo=ZoneInfo("America/Los_Angeles")),
    )

    pipeline_summary = {
        "overall_status": "ready",
        "warnings_count": 0,
        "warning_counts": {},
        "errors_count": 0,
        "blocking_gaps": [],
        "source_coverage": {},
    }

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = args[0]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(pipeline_summary))

    monkeypatch.setattr(subprocess, "run", fake_run)
    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        [
            "--dry-run",
            "--refresh-paper-health",
            "--paper-evidence-operation-root",
            str(paper_operation_root),
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(output_root),
            "--db-path",
            str(db_path),
        ]
    )

    status_path = output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    command = captured["command"]
    assert isinstance(command, list)
    sentinel = Path(command[command.index("--paper-evidence-health-baseline") + 1])
    assert sentinel != health_path
    assert sentinel.name == ".paper_health_unavailable_20260908.json"
    assert not sentinel.exists()
    assert health_path.read_text(encoding="utf-8") == stale_health
    assert exit_code == 2
    assert payload["status"] == "failed"
    assert payload["exit_code"] == 2
    assert payload["pipeline_exit_code"] == 0
    assert payload["paper_health_refresh_status"] == "blocked"
    assert payload["paper_health_refresh_blocked"] is True
    assert payload["paper_evidence_health_baseline"] == str(sentinel)
    assert payload["manual_action_required"] is True


def test_scheduled_wrapper_connects_market_sources_to_transition_evaluator(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "output"
    baseline = tmp_path / "health" / "baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(
        json.dumps({"decision_date": "2026-09-08", "positions": []}),
        encoding="utf-8",
    )
    quick = tmp_path / "quick.json"
    freshness = tmp_path / "freshness.json"
    binding = tmp_path / "forward_binding.json"
    quick.write_text("{}", encoding="utf-8")
    freshness.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeMarketSource:
        def __init__(self, **kwargs: object) -> None:
            captured["market_source_init"] = kwargs

        def produce(self, **kwargs: object) -> dict[str, object]:
            captured["market_source_produce"] = kwargs
            return {
                "status": "degraded",
                "condition_source_path": str(tmp_path / "sources" / "condition.json"),
                "metrics_source_path": str(tmp_path / "sources" / "metrics.json"),
                "source_snapshot_hash": "sha256:" + "1" * 64,
                "warnings": ["position_health_source_identity_missing:2330"],
                "blockers": [],
            }

    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "PositionHealthMarketSourceProducer",
        FakeMarketSource,
    )
    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "scheduled_now",
        lambda: datetime(2026, 9, 8, 5, 15, tzinfo=ZoneInfo("America/Los_Angeles")),
    )

    def fake_evaluate(**kwargs: object) -> dict[str, object]:
        captured["evaluator"] = kwargs
        return {"status": "degraded", "blockers": [], "warnings": ["thesis_missing"]}

    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "evaluate_baseline_file",
        fake_evaluate,
    )
    pipeline_summary = {
        "overall_status": "ready",
        "warnings_count": 0,
        "warning_counts": {},
        "errors_count": 0,
        "blocking_gaps": [],
        "source_coverage": {},
    }
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args, returncode=0, stdout=json.dumps(pipeline_summary)
        ),
    )

    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        [
            "--dry-run",
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(output_root),
            "--db-path",
            str(tmp_path / "market.sqlite"),
            "--paper-evidence-health-baseline",
            str(baseline),
            "--produce-position-health-sources",
            "--paper-health-source-output",
            str(tmp_path / "sources"),
            "--paper-health-quick-status-path",
            str(quick),
            "--paper-health-freshness-status-path",
            str(freshness),
            "--evaluate-position-health-transition",
            "--paper-health-forward-binding",
            str(binding),
        ]
    )

    payload = json.loads(
        (output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json").read_text(
            encoding="utf-8"
        )
    )
    evaluator = captured["evaluator"]
    assert exit_code == 0
    assert payload["paper_health_source_status"] == "degraded"
    assert payload["paper_health_source_blocked"] is False
    assert payload["paper_health_source_receipt"]["source_snapshot_hash"].startswith("sha256:")
    assert isinstance(evaluator, dict)
    assert evaluator["condition_source_path"] == str(tmp_path / "sources" / "condition.json")
    assert evaluator["metrics_source_path"] == str(tmp_path / "sources" / "metrics.json")
    assert evaluator["forward_binding_path"] == str(binding)
    produce_kwargs = captured["market_source_produce"]
    assert isinstance(produce_kwargs, dict)
    assert produce_kwargs["decision_date"] == "2026-09-08"
    assert "decision_at" not in produce_kwargs
    assert "observed_at" not in produce_kwargs


def test_scheduled_wrapper_runs_daily_forward_binder_for_all_current_entries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "output"
    paper_operation_root = tmp_path / "paper-operation"
    baseline = tmp_path / "health" / "baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(
        json.dumps({"source_snapshot_date": "2026-09-09", "positions": []}),
        encoding="utf-8",
    )
    freshness = output_root / "scheduled" / "data_freshness" / "latest_status.json"
    freshness.parent.mkdir(parents=True)
    freshness.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeHealthRefresh:
        def __init__(self, **kwargs: object) -> None:
            pass

        def refresh(self, **kwargs: object) -> dict[str, object]:
            return {"status": "passed", "latest_path": str(baseline)}

    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "PositionHealthDailyRefreshService",
        FakeHealthRefresh,
    )
    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "scheduled_now",
        lambda: datetime(2026, 9, 9, 5, 15, tzinfo=ZoneInfo("America/Los_Angeles")),
    )

    def fake_bind(**kwargs: object) -> dict[str, object]:
        captured["bind"] = kwargs
        return {
            "status": "degraded",
            "candidate_count": 2,
            "bound_count": 1,
            "awaiting_count": 1,
            "blocked_count": 0,
            "results": [],
            "warnings": ["paper_entry_not_observed"],
            "blockers": [],
        }

    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "bind_available_candidates",
        fake_bind,
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                {
                    "overall_status": "ready",
                    "warnings_count": 0,
                    "errors_count": 0,
                    "blocking_gaps": [],
                    "source_coverage": {},
                }
            ),
        ),
    )

    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        [
            "--dry-run",
            "--refresh-paper-health",
            "--bind-forward-thesis",
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(output_root),
            "--db-path",
            str(tmp_path / "market.sqlite"),
            "--paper-evidence-operation-root",
            str(paper_operation_root),
        ]
    )

    bind_kwargs = captured["bind"]
    assert isinstance(bind_kwargs, dict)
    assert bind_kwargs["baseline_path"] == baseline
    assert bind_kwargs["candidate_root"] == Path.cwd() / "output" / "forward_position_thesis"
    assert bind_kwargs["paper_candidate_root"] == paper_operation_root / "candidates"
    payload = json.loads(
        (output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json").read_text(
            encoding="utf-8"
        )
    )
    assert exit_code == 0
    assert payload["forward_position_thesis_binding"]["bound_count"] == 1
    assert payload["forward_position_thesis_binding_blocked"] is False


def test_scheduled_wrapper_runs_bounded_exit_effectiveness_child(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "output"
    paper_operation_root = tmp_path / "paper-operation"
    paper_ledger = paper_operation_root / "paper_trade_ledger.sqlite"
    market_db = tmp_path / "market.sqlite"
    freshness_path = output_root / "scheduled" / "data_freshness" / "latest_status.json"
    freshness_path.parent.mkdir(parents=True)
    freshness_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    monkeypatch.setattr(
        run_scheduled_evidence_pipeline_dry_run,
        "scheduled_now",
        lambda: datetime(2026, 9, 8, 5, 15, tzinfo=ZoneInfo("America/Los_Angeles")),
    )

    calls: list[tuple[list[str], dict[str, object]]] = []
    pipeline_summary = {
        "overall_status": "ready",
        "warnings_count": 0,
        "errors_count": 0,
        "blocking_gaps": [],
        "source_coverage": {},
    }
    exit_receipt = {
        "status": "passed",
        "research_only": True,
        "historical_backfill": False,
        "auto_exit_allowed": False,
        "broker_order_allowed": False,
        "observations": [],
        "blockers": [],
    }

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = list(args[0])
        calls.append((command, dict(kwargs)))
        if any(str(item).endswith("run_exit_effectiveness_daily.py") for item in command):
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=json.dumps(exit_receipt),
            )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(pipeline_summary),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        [
            "--dry-run",
            "--run-exit-effectiveness",
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(output_root),
            "--db-path",
            str(market_db),
            "--paper-evidence-operation-root",
            str(paper_operation_root),
            "--paper-evidence-ledger-db",
            str(paper_ledger),
        ]
    )

    status_path = output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["exit_effectiveness_status"] == "passed"
    assert payload["exit_effectiveness_blocked"] is False
    assert payload["exit_effectiveness_receipt"]["receipt"]["research_only"] is True
    assert payload["exit_effectiveness_receipt"]["receipt"]["historical_backfill"] is False
    assert len(calls) == 2
    exit_command, exit_kwargs = calls[0]
    assert "scripts/run_exit_effectiveness_daily.py" in exit_command
    assert "--as-of-date" not in exit_command
    assert exit_command[exit_command.index("--transition-db") + 1] == str(
        output_root / "position_health_transition" / "position_health_transitions.sqlite"
    )
    assert exit_command[exit_command.index("--paper-ledger-db") + 1] == str(paper_ledger)
    assert exit_command[exit_command.index("--market-db") + 1] == str(market_db)
    assert exit_command[exit_command.index("--output") + 1] == str(
        output_root / "exit_effectiveness" / "20260908.json"
    )
    assert exit_kwargs["timeout"] == 120
    assert exit_kwargs["cwd"] == str(run_scheduled_evidence_pipeline_dry_run.REPO_ROOT)
    assert Path(payload["exit_effectiveness_log"]).is_file()


def test_scheduled_wrapper_surfaces_exit_effectiveness_timeout_without_stale_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "output"
    freshness_path = output_root / "scheduled" / "data_freshness" / "latest_status.json"
    freshness_path.parent.mkdir(parents=True)
    freshness_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    pipeline_summary = {
        "overall_status": "ready",
        "warnings_count": 0,
        "errors_count": 0,
        "blocking_gaps": [],
        "source_coverage": {},
    }

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = list(args[0])
        if any(str(item).endswith("run_exit_effectiveness_daily.py") for item in command):
            raise subprocess.TimeoutExpired(
                cmd=command,
                timeout=run_scheduled_evidence_pipeline_dry_run.EXIT_EFFECTIVENESS_TIMEOUT_SECONDS,
                output="partial child output",
            )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(pipeline_summary),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        [
            "--dry-run",
            "--run-exit-effectiveness",
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(output_root),
            "--db-path",
            str(tmp_path / "market.sqlite"),
        ]
    )

    status_path = output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert payload["status"] == "failed"
    assert payload["exit_effectiveness_status"] == "blocked"
    assert payload["exit_effectiveness_blocked"] is True
    assert "exit_effectiveness_child_timeout" in payload["exit_effectiveness_receipt"]["blockers"]
    assert not (output_root / "exit_effectiveness" / "20260908.json").exists()
    assert "partial child output" in Path(payload["exit_effectiveness_log"]).read_text(
        encoding="utf-8"
    )
