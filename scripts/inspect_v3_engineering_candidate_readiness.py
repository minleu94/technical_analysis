"""Inspect V3.0 engineering candidate readiness without writing data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
if callable(stdout_reconfigure):
    stdout_reconfigure(encoding="utf-8")
if callable(stderr_reconfigure):
    stderr_reconfigure(encoding="utf-8")

from app_module.v3_effectiveness_dashboard_service import (
    V3EffectivenessDashboardService,
)
from app_module.v3_effectiveness_read_model import (
    V3EffectivenessReadModel,
    sample_v3_effectiveness_rows,
)
from app_module.v3_effectiveness_review_scaffold import V3ReviewScaffoldBuilder


MANUAL_STATUSES = {
    "PENDING_MANUAL_VALIDATION",
    "MANUAL_VALIDATION_READY",
    "MANUAL_VALIDATION_ACCEPTED",
    "MANUAL_VALIDATION_REJECTED",
}


REQUIRED_ARTIFACTS = (
    "app_module/v3_effectiveness_dtos.py",
    "app_module/v3_gap_classifier.py",
    "app_module/v3_effectiveness_read_model.py",
    "app_module/v3_effectiveness_dashboard_service.py",
    "app_module/v3_effectiveness_review_scaffold.py",
    "scripts/inspect_v3_evidence_effectiveness.py",
    "scripts/build_v3_effectiveness_review_scaffold.py",
    "docs/06_qa/V3_0_ENGINEERING_CANDIDATE_MANUAL_VALIDATION_REPORT_2026_07_08.md",
)


def _artifact_status() -> list[dict[str, Any]]:
    return [
        {
            "path": path,
            "exists": Path(path).exists(),
        }
        for path in REQUIRED_ARTIFACTS
    ]


def _build_payload(args: argparse.Namespace) -> dict[str, Any]:
    if not args.sample:
        raise SystemExit("Only --sample is supported in this read-only slice.")
    if args.manual_validation_status not in MANUAL_STATUSES:
        raise SystemExit("invalid manual validation status")

    report = V3EffectivenessReadModel(
        min_sample_size=args.min_sample_size
    ).build_report(rows=sample_v3_effectiveness_rows())
    dashboard = V3EffectivenessDashboardService().build_dashboard(report)
    scaffold = V3ReviewScaffoldBuilder().build(report)
    artifacts = _artifact_status()
    missing_artifacts = [
        item["path"] for item in artifacts if not bool(item["exists"])
    ]
    blocking_gaps = []
    if missing_artifacts:
        blocking_gaps.append("required_artifact_missing")
    if args.manual_validation_status == "MANUAL_VALIDATION_REJECTED":
        blocking_gaps.append("manual_validation_rejected")

    engineering_status = (
        "action_required" if blocking_gaps else "ready_for_manual_validation"
    )
    if (
        not blocking_gaps
        and args.manual_validation_status == "MANUAL_VALIDATION_ACCEPTED"
    ):
        engineering_status = "V3_ENGINEERING_CANDIDATE_COMPLETE"

    return {
        "active_milestone": "V3.0 engineering candidate",
        "engineering_candidate_status": engineering_status,
        "manual_validation_status": args.manual_validation_status,
        "production_scheduler_allowed": False,
        "auto_trading": False,
        "scheduler_write_mode": False,
        "required_artifacts": artifacts,
        "blocking_gaps": blocking_gaps,
        "warnings": list(report.warnings),
        "summary_cards": dict(dashboard.summary_cards),
        "review_item_count": len(scaffold.items),
        "next_closeout_checks": [
            "人工確認 sample sufficiency threshold 是否可接受",
            "人工確認 signal / alert / gate 文案不暗示投資有效性",
            "人工確認 dashboard disclosure 可讀性",
            "Phase 0 weekly history 與 multi-day dry-run 仍需真實時間累積",
        ],
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# V3.0 Engineering Candidate Readiness",
        "",
        f"- active_milestone: {payload['active_milestone']}",
        f"- engineering_candidate_status: {payload['engineering_candidate_status']}",
        f"- manual_validation_status: {payload['manual_validation_status']}",
        f"- production_scheduler_allowed: {str(payload['production_scheduler_allowed']).lower()}",
        f"- auto_trading: {str(payload['auto_trading']).lower()}",
        f"- scheduler_write_mode: {str(payload['scheduler_write_mode']).lower()}",
        "",
        "## Required Artifacts",
        "",
        "| Path | Exists |",
        "|---|---|",
    ]
    for artifact in payload["required_artifacts"]:
        lines.append(f"| `{artifact['path']}` | {artifact['exists']} |")
    lines.extend(["", "## Blocking Gaps", ""])
    if payload["blocking_gaps"]:
        for gap in payload["blocking_gaps"]:
            lines.append(f"- {gap}")
    else:
        lines.append("- none")
    lines.extend(["", "## Next Closeout Checks", ""])
    for item in payload["next_closeout_checks"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "> Read-only readiness inspection. No production DB write, no scheduler enablement, no trading, no lifecycle action.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--json-output", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--report-output")
    parser.add_argument(
        "--manual-validation-status",
        default="PENDING_MANUAL_VALIDATION",
        choices=sorted(MANUAL_STATUSES),
    )
    parser.add_argument("--min-sample-size", type=int, default=30)
    args = parser.parse_args()

    payload = _build_payload(args)
    if args.report_output:
        Path(args.report_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_output).write_text(
            _render_markdown(payload), encoding="utf-8"
        )
    if args.markdown:
        print(_render_markdown(payload), end="")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2), end="\n")


if __name__ == "__main__":
    main()
