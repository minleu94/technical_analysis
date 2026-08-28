"""唯讀建立 Paper Portfolio 週報 evidence。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.paper_portfolio_weekly_evidence_service import (  # noqa: E402
    PaperPortfolioWeeklyEvidenceService,
)


def _markdown(payload: dict[str, Any]) -> str:
    report = payload.get("report") or {}
    lines = [
        "# Paper Portfolio Weekly Evidence",
        "",
        f"- status: `{payload['status']}`",
        f"- period: `{payload.get('period_start') or 'N/A'}` → `{payload.get('period_end') or 'N/A'}`",
        f"- expected trading days: `{payload['expected_trading_days']}`",
        f"- snapshots / benchmark observations: `{payload['snapshot_count']}` / `{payload['benchmark_observation_count']}`",
        f"- cost records: `{payload['cost_record_count']}`",
        f"- weekly report: `{payload['weekly_report_status']}`",
    ]
    if report:
        lines.extend(
            [
                f"- gross / net / benchmark / excess (bp): `{report['gross_return_bp']}` / `{report['net_return_bp']}` / `{report['benchmark_return_bp']}` / `{report['net_excess_return_bp']}`",
                f"- total cost / turnover (bp): `{report['total_cost']}` / `{report['turnover_bp']}`",
                f"- data quality: `{report['data_quality']}`",
            ]
        )
    lines.extend(["", "## Blockers", ""])
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
    parser.add_argument("--period-start", required=True)
    parser.add_argument("--period-end", required=True)
    parser.add_argument("--expected-trading-days", type=int, required=True)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--benchmark-db", type=Path)
    parser.add_argument("--cost-ledger-db", type=Path)
    parser.add_argument("--portfolio-id", default="paper-main")
    parser.add_argument("--benchmark-id", default="paper-main-equal")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)

    try:
        result = PaperPortfolioWeeklyEvidenceService(
            output_root=args.output_root,
            state_db_path=args.state_db,
            benchmark_db_path=args.benchmark_db,
            cost_ledger_db_path=args.cost_ledger_db,
            portfolio_id=args.portfolio_id,
            benchmark_id=args.benchmark_id,
        ).build(
            period_start=args.period_start,
            period_end=args.period_end,
            expected_trading_days=args.expected_trading_days,
        )
    except (TypeError, ValueError, OSError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
        return 2

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
