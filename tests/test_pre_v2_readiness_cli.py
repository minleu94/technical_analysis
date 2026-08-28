from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _empty_record(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "| Date | Data update status | Source coverage status | Dry-run pipeline status | Working-copy confirm smoke status | Events seen | Events inserted in working copy | Outcomes created in working copy | Summary groups | Warnings count | Blocking gaps | Dashboard review completed | Human reviewer notes | Decision |",
                "|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|",
            ]
        ),
        encoding="utf-8",
    )


def _run_cli(
    tmp_path: Path,
    *args: str,
    env_overrides: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Tests that do not explicitly provide a projection must exercise the
    # default no-projection path, independent of the developer shell.
    env.pop("WEEKLY_EVIDENCE_HISTORY_PROJECTION_PATH", None)
    for key, value in (env_overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [
            sys.executable,
            "scripts/inspect_pre_v2_readiness.py",
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(tmp_path / "output"),
            *args,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def _write_approved_projection(path: Path) -> None:
    records = []
    for index, (period_start, period_end) in enumerate(
        (
            ("2026-07-06", "2026-07-12"),
            ("2026-07-13", "2026-07-19"),
            ("2026-07-20", "2026-07-26"),
        ),
        start=1,
    ):
        records.append(
            {
                "review_id": f"review-{index}",
                "review_hash": f"sha256:{index:064d}",
                "period_start": period_start,
                "period_end": period_end,
                "owner_role": "release_owner",
                "approved_at": f"2026-07-{12 + index:02d}T12:00:00Z",
                "status": "approved_weekly_review",
            }
        )
    path.write_text(
        json.dumps(
            {
                "schema_version": "approved-weekly-history-projection.v1",
                "formal_credit_authorized": False,
                "purpose": "test-only read-only projection",
                "records": records,
            }
        ),
        encoding="utf-8",
    )


def test_pre_v2_readiness_cli_reports_json_without_creating_missing_db(tmp_path: Path) -> None:
    missing_db = tmp_path / "missing" / "evidence.db"
    record_path = tmp_path / "multi-day.md"
    _empty_record(record_path)

    result = _run_cli(
        tmp_path,
        "--db-path",
        str(missing_db),
        "--decision-date",
        "2026-07-06",
        "--multi-day-record-path",
        str(record_path),
        "--json-output",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["overall_status"] == "action_required"
    assert payload["production_scheduler_allowed"] is False
    assert payload["rule_operational_scheduler_allowed"] is True
    assert payload["required_human_action"] is False
    assert payload["blocking_scope"] == "formal_evidence_credit_only"
    assert any(item["item_id"] == "weekly_history" for item in payload["items"])
    assert not missing_db.exists()


def test_pre_v2_readiness_cli_can_emit_markdown_report_file(tmp_path: Path) -> None:
    record_path = tmp_path / "multi-day.md"
    report_path = tmp_path / "pre-v2.md"
    _empty_record(record_path)

    result = _run_cli(
        tmp_path,
        "--db-path",
        str(tmp_path / "missing.db"),
        "--multi-day-record-path",
        str(record_path),
        "--markdown",
        "--report-output",
        str(report_path),
    )

    assert result.returncode == 0
    assert "# Pre-V2 Readiness Report" in result.stdout
    assert "V2.0" in report_path.read_text(encoding="utf-8")


def test_pre_v2_readiness_cli_reads_approved_projection_from_environment(tmp_path: Path) -> None:
    projection_path = tmp_path / "approved-weekly-history.json"
    _write_approved_projection(projection_path)
    record_path = tmp_path / "multi-day.md"
    _empty_record(record_path)

    result = _run_cli(
        tmp_path,
        "--db-path",
        str(tmp_path / "missing.db"),
        "--multi-day-record-path",
        str(record_path),
        "--json-output",
        env_overrides={"WEEKLY_EVIDENCE_HISTORY_PROJECTION_PATH": str(projection_path)},
    )
    payload = json.loads(result.stdout)
    weekly = next(item for item in payload["items"] if item["item_id"] == "weekly_history")

    assert result.returncode == 0
    assert weekly["status"] == "ready"
    assert weekly["observed_count"] == 3
    assert weekly["evidence"]["approved_projection_configured"] is True
    assert weekly["evidence"]["approved_projection_path"] == str(projection_path.resolve())
    assert "approved_weekly_history_projection_not_configured" not in weekly["diagnostics"]
