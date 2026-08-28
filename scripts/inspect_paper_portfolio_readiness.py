"""唯讀檢查 Paper Portfolio／Equal Weight readiness。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.paper_portfolio_readiness_service import (  # noqa: E402
    PaperPortfolioReadinessService,
)


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Paper Portfolio Readiness",
        "",
        f"- status: `{payload['status']}`",
        f"- latest daily status: `{payload['latest_status']}`",
        f"- raw snapshots: `{payload['snapshot_count']}`",
        f"- latest usable snapshot: `{payload['latest_snapshot_date'] or 'N/A'}`",
        f"- latest usable total value: `{payload['latest_total_value'] or 'N/A'}`",
        f"- benchmark observations: `{payload['benchmark_observation_count']}`",
        f"- cost ledger: `{payload['cost_ledger_status']}` ({payload['cost_record_count']} records)",
        f"- total recorded cost: `{payload['cost_total_cost'] or 'N/A'}`",
        f"- fills: `{payload['filled_event_count']}` full / `{payload['partial_fill_event_count']}` partial / `{payload['rejected_event_count']}` rejected",
        f"- weekly report: `{payload['weekly_report_status']}`",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {item}" for item in payload["blockers"] or ["none"])
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {item}" for item in payload["warnings"] or ["none"])
    lines.extend(
        [
            "",
            "## Safety boundary",
            "",
            "- research_only: `true`",
            "- investment_effectiveness_claim: `false`",
            "- read_only: `true`",
            "- writes_allowed: `false`",
            "- broker_execution: `false`",
            "- auto_rebalance_allowed: `false`",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--status-path", type=Path)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--benchmark-db", type=Path)
    parser.add_argument("--cost-ledger-db", type=Path)
    parser.add_argument("--portfolio-id", default="paper-main")
    parser.add_argument("--benchmark-id", default="paper-main-equal")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)

    result = PaperPortfolioReadinessService(
        output_root=args.output_root,
        status_path=args.status_path,
        state_db_path=args.state_db,
        baseline_path=args.baseline,
        benchmark_db_path=args.benchmark_db,
        cost_ledger_db_path=args.cost_ledger_db,
        portfolio_id=args.portfolio_id,
        benchmark_id=args.benchmark_id,
    ).inspect()
    payload = result.to_dict()
    if args.format == "markdown":
        print(_markdown(payload), end="")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.status in {"ready", "partial"} else 2


def _configure_utf8_stdio() -> None:
    """讓直接執行腳本的 Windows 主控台也能顯示繁中說明與診斷。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # 測試 capture stream 或外部 host 管理的 stream 可能禁止重設；
            # 這不應改變 readiness 結果。
            continue


if __name__ == "__main__":
    raise SystemExit(main())
