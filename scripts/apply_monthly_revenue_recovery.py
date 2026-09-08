"""預覽或套用一次受治理的月營收恢復交易。

此命令會串接 availability mapping 合併與 SQLite backfill；accepted snapshot
可透過 scope manifest 明確標示為 partial。套用需要精確確認字串與任務專用備份目錄。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.monthly_revenue_recovery import (  # noqa: E402
    MonthlyRevenueRecoveryApplyResult,
    apply_monthly_revenue_recovery,
    plan_monthly_revenue_recovery,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-mapping", type=Path, required=True)
    parser.add_argument("--snapshot-file", type=Path, required=True)
    parser.add_argument("--scope-manifest", type=Path, default=None)
    parser.add_argument("--target-mapping", type=Path, required=True)
    parser.add_argument("--db-file", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument(
        "--journal-file",
        type=Path,
        default=None,
        help="跨檔 phase journal 路徑；省略時使用 evidence-file 加上 .journal.json",
    )
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm",
        choices=["apply-monthly-revenue-recovery"],
        default=None,
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)

    if args.apply and args.confirm != "apply-monthly-revenue-recovery":
        print(
            "月營收恢復套用需要 --confirm apply-monthly-revenue-recovery",
            file=sys.stderr,
        )
        return 2

    try:
        if args.apply:
            result = apply_monthly_revenue_recovery(
                candidate_mapping_file=args.candidate_mapping,
                snapshot_file=args.snapshot_file,
                scope_manifest_file=args.scope_manifest,
                target_mapping_file=args.target_mapping,
                db_file=args.db_file,
                backup_dir=args.backup_dir,
                evidence_file=args.evidence_file,
                source_version=args.source_version,
                journal_file=args.journal_file,
            )
            payload = _apply_payload(result)
            ready = result.plan.ready_for_apply
            applied = result.applied
        else:
            plan = plan_monthly_revenue_recovery(
                candidate_mapping_file=args.candidate_mapping,
                snapshot_file=args.snapshot_file,
                scope_manifest_file=args.scope_manifest,
                target_mapping_file=args.target_mapping,
                source_version=args.source_version,
            )
            payload = {
                "status": "preview",
                "plan": plan.to_payload(),
            }
            ready = plan.ready_for_apply
            applied = False
    except (OSError, TypeError, ValueError) as error:
        print(f"monthly revenue recovery blocked: {error}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_render_markdown(payload))
    return 0 if (applied or ready) else 1


def _apply_payload(result: MonthlyRevenueRecoveryApplyResult) -> dict[str, Any]:
    payload = result.plan.to_payload()
    payload.update(
        {
            "status": (
                "applied"
                if result.applied
                else "rolled_back"
                if result.rolled_back
                else "failed"
            ),
            "applied": result.applied,
            "rolled_back": result.rolled_back,
            "mapping_backup_file": (
                str(result.mapping_backup_file)
                if result.mapping_backup_file is not None
                else None
            ),
            "db_backup_file": (
                str(result.db_backup_file)
                if result.db_backup_file is not None
                else None
            ),
            "evidence_file": str(result.evidence_file),
            "journal_file": (
                str(result.journal_file) if result.journal_file is not None else None
            ),
            "commit_observed_after_error": result.commit_observed_after_error,
            "error": result.error,
        }
    )
    return payload


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 月營收恢復",
        "",
        f"- status: `{payload['status']}`",
    ]
    if "plan" in payload:
        plan = payload["plan"]
        lines.extend(
            [
                f"- snapshot_scope: `{plan['snapshot_scope']}`",
                f"- full_snapshot_row_count: `{plan['full_snapshot_row_count']}`",
                f"- accepted_snapshot_row_count: `{plan['accepted_snapshot_row_count']}`",
                f"- excluded_snapshot_row_count: `{plan['excluded_snapshot_row_count']}`",
                f"- availability_added_count: `{plan['availability']['added_count']}`",
                f"- availability_conflict_count: `{plan['availability']['conflict_count']}`",
                f"- backfill_raw_row_count: `{plan['backfill']['raw_row_count']}`",
                f"- backfill_normalized_record_count: `{plan['backfill']['normalized_record_count']}`",
                f"- ready_for_apply: `{str(plan['ready_for_apply']).lower()}`",
            ]
        )
    else:
        lines.extend(
            [
                f"- snapshot_scope: `{payload['snapshot_scope']}`",
                f"- full_snapshot_row_count: `{payload['full_snapshot_row_count']}`",
                f"- accepted_snapshot_row_count: `{payload['accepted_snapshot_row_count']}`",
                f"- excluded_snapshot_row_count: `{payload['excluded_snapshot_row_count']}`",
                f"- applied: `{str(payload['applied']).lower()}`",
                f"- rolled_back: `{str(payload['rolled_back']).lower()}`",
                f"- mapping_backup_file: `{payload['mapping_backup_file'] or 'none'}`",
                f"- db_backup_file: `{payload['db_backup_file'] or 'none'}`",
                f"- evidence_file: `{payload['evidence_file']}`",
                f"- journal_file: `{payload['journal_file'] or 'none'}`",
                "- commit_observed_after_error: `"
                f"{str(payload['commit_observed_after_error']).lower()}`",
            ]
        )
        if payload.get("error"):
            lines.append(f"- error: `{payload['error']}`")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
