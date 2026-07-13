"""輸出 V2.4 核准紙上投資政策的唯讀檢查報告。"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.paper_portfolio_policy import (  # noqa: E402
    PaperPortfolioPolicy,
    PaperPortfolioPolicyConfig,
    PaperPortfolioRebalanceInput,
)


def _policy_payload(config: PaperPortfolioPolicyConfig) -> dict[str, Any]:
    payload = asdict(config)
    payload["initial_capital"] = str(config.initial_capital)
    return payload


def _sample_payload() -> dict[str, Any]:
    config = PaperPortfolioPolicyConfig()
    decision = PaperPortfolioPolicy(config).evaluate(
        PaperPortfolioRebalanceInput(
            stock_code="2330",
            current_weight_bp=500,
            target_weight_bp=1500,
            current_cash_bp=3000,
            sector_weight_after_bp=2500,
            weekly_turnover_used_bp=500,
            trading_days_since_last_trade=5,
        )
    )
    return {
        "research_only": True,
        "policy": _policy_payload(config),
        "decision": {
            "action": decision.action.value,
            "weight_gap_bp": decision.weight_gap_bp,
            "estimated_round_trip_cost_bp": decision.estimated_round_trip_cost_bp,
            "reasons": list(decision.reasons),
            "research_only": decision.research_only,
        },
        "warnings": ["paper_policy_report_is_not_a_trade_instruction"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect the research-only V2.4 paper portfolio policy.")
    parser.add_argument("--sample", action="store_true", help="Use only the built-in non-persistent sample.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()
    if not args.sample:
        parser.error("Only --sample is supported; this command never reads positions or writes a database.")
    payload = _sample_payload()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        return 0
    print("# V2.4 Paper Portfolio Policy", end="\n\n")
    print(f"- action: {payload['decision']['action']}")
    print(f"- estimated_round_trip_cost_bp: {payload['decision']['estimated_round_trip_cost_bp']}")
    print("- research_only: true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
