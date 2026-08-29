"""Preview or explicitly apply a governed monthly-revenue availability candidate.

預設只驗證並顯示 merge plan。只有同時指定 ``--apply`` 與精確的
``--confirm apply-monthly-revenue-availability`` 才會備份目標 mapping，並以
同目錄 atomic replace 寫入合併後的完整 CSV；candidate、raw CSV 與 SQLite
都不會由本 CLI 自動改寫。
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

from data_module.config import TWStockConfig
from data_module.monthly_revenue_availability_merge import (
    apply_monthly_revenue_availability_merge,
    plan_monthly_revenue_availability_merge,
)
from runtime.console_encoding import configure_utf8_console  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    # The module docstring is rendered by argparse for ``--help``; configure
    # UTF-8 before parsing so a Windows cp1252 console cannot abort the CLI.
    configure_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--target", type=Path, default=None)
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm",
        choices=["apply-monthly-revenue-availability"],
        default=None,
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)

    config = TWStockConfig()
    target = args.target or config.monthly_revenue_availability_file
    backup_dir = args.backup_dir or target.parent / "backup"

    if args.apply and args.confirm != "apply-monthly-revenue-availability":
        print(
            "Applying monthly revenue availability requires "
            "--confirm apply-monthly-revenue-availability",
            file=sys.stderr,
        )
        return 2

    try:
        plan = plan_monthly_revenue_availability_merge(
            candidate_file=args.candidate,
            target_file=target,
        )
        result = None
        if args.apply:
            result = apply_monthly_revenue_availability_merge(
                plan=plan,
                backup_dir=backup_dir,
            )
    except (OSError, TypeError, ValueError) as error:
        print(f"monthly revenue availability merge blocked: {error}", file=sys.stderr)
        return 2

    payload = _payload(plan, result)
    rendered = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.format == "json"
        else _render_markdown(payload) + "\n"
    )
    print(rendered, end="")
    if not plan.ready_for_apply:
        return 1
    return 0


def _payload(plan: Any, result: Any) -> dict[str, Any]:
    return {
        "schema_version": "monthly-revenue-availability-merge.v1",
        "status": "applied" if result is not None and result.applied else "preview",
        "ready_for_apply": plan.ready_for_apply,
        "target_exists": plan.target_exists,
        "target_file": str(plan.target_file),
        "candidate_file": str(plan.candidate_file),
        "existing_count": plan.existing_count,
        "candidate_count": plan.candidate_count,
        "added_count": plan.added_count,
        "unchanged_count": plan.unchanged_count,
        "conflict_count": plan.conflict_count,
        "merged_count": len(plan.merged_rows),
        "applied": bool(result.applied) if result is not None else False,
        "backup_file": str(result.backup_file) if result is not None and result.backup_file else None,
        "diagnostics": [
            {
                "code": item.code,
                "factor_name": item.factor_name,
                "stock_code": item.stock_code,
                "message": item.message,
            }
            for item in plan.diagnostics
        ],
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Monthly Revenue Availability Merge",
        "",
        f"- status: `{payload['status']}`",
        f"- ready_for_apply: `{str(payload['ready_for_apply']).lower()}`",
        f"- target_file: `{payload['target_file']}`",
        f"- candidate_file: `{payload['candidate_file']}`",
        f"- existing_count: `{payload['existing_count']}`",
        f"- candidate_count: `{payload['candidate_count']}`",
        f"- added_count: `{payload['added_count']}`",
        f"- unchanged_count: `{payload['unchanged_count']}`",
        f"- conflict_count: `{payload['conflict_count']}`",
        f"- merged_count: `{payload['merged_count']}`",
        f"- applied: `{str(payload['applied']).lower()}`",
        f"- backup_file: `{payload['backup_file'] or 'none'}`",
    ]
    diagnostics = payload["diagnostics"]
    if diagnostics:
        lines.extend(["", "Diagnostics:", ""])
        lines.extend(f"- `{item['code']}: {item['message']}`" for item in diagnostics)
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
