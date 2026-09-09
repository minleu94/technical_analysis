from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_DIR = ROOT / "scripts" / "scheduled"


def _scheduled_texts() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in SCHEDULED_DIR.glob("*")
        if path.suffix.lower() in {".ps1", ".cmd"}
    }


def _called_function_names(source: str) -> set[str]:
    """Return direct and attribute call names, excluding string mentions."""

    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name):
            names.add(function.id)
        elif isinstance(function, ast.Attribute):
            names.add(function.attr)
    return names


def test_confirm_is_not_embedded_in_general_scheduled_cmd_or_ps1_wrappers() -> None:
    for name, text in _scheduled_texts().items():
        lowered = text.lower()
        assert "--confirm" not in lowered or name in {
            "run_evidence_working_copy_smoke.ps1",
            "run_evidence_working_copy_smoke.cmd",
            "run_paper_execution_daily.cmd",
        }
        assert "--allow-production-db-confirm" not in lowered
    readme = (SCHEDULED_DIR / "README.md").read_text(encoding="utf-8").lower()
    assert "only the dedicated decision/evidence capture task" in readme


def test_general_daily_tasks_remain_read_only_or_dry_run() -> None:
    register_text = (SCHEDULED_DIR / "register_baldr_scheduled_tasks.cmd").read_text(encoding="utf-8")
    dry_run_text = (SCHEDULED_DIR / "run_evidence_pipeline_dry_run.cmd").read_text(encoding="utf-8")
    recommendation_text = (SCHEDULED_DIR / "run_recommendation_snapshot.cmd").read_text(encoding="utf-8")
    freshness_probe_text = (SCHEDULED_DIR / "data_freshness_probe.py").read_text(encoding="utf-8")

    assert "run_daily_data_freshness_check.cmd" in register_text
    assert "run_recommendation_snapshot.cmd" in register_text
    assert "run_evidence_pipeline_dry_run.cmd" in register_text
    assert "run_decision_evidence_capture.cmd" in register_text
    assert "--dry-run" in dry_run_text
    assert "--confirm" not in dry_run_text.lower()
    assert "--confirm" not in recommendation_text.lower()
    assert "mode=ro" in freshness_probe_text
    called_names = _called_function_names(freshness_probe_text)
    assert "update_daily" not in called_names
    assert "sync_source_to_sqlite" not in called_names


def test_writer_call_ast_guard_detects_direct_and_attribute_calls() -> None:
    assert "update_daily" in _called_function_names("update_daily()")
    assert "sync_source_to_sqlite" in _called_function_names(
        "service.sync_source_to_sqlite()"
    )


def test_paper_eod_wrapper_only_appends_research_ledger_with_explicit_opt_out() -> None:
    text = (SCHEDULED_DIR / "run_paper_execution_daily.cmd").read_text(encoding="utf-8").lower()

    assert "--recommendation-root" in text
    assert "--receipt-root" in text
    assert "--confirm-append-paper-ledger" in text
    assert "paper_execution_append" in text
    assert "paper_execution_append=0" in text
    assert "paper_execution_ledger_db" in text
