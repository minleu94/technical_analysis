"""輸出 V2.5 持倉健康狀態的唯讀樣本報告。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.portfolio_condition_monitor import PortfolioConditionResult  # noqa: E402
from app_module.position_health_service import PositionHealthService  # noqa: E402
from app_module.strategy_lifecycle_service import GateStatus  # noqa: E402


def _sample_payload() -> dict[str, object]:
    condition = PortfolioConditionResult(
        stock_code="2330",
        status="invalid",
        label="假設失效",
        source_label="recommendation:balanced",
        reasons=["regime_changed", "score_degraded"],
    )
    result = PositionHealthService().evaluate(
        stock_code="2330",
        condition_result=condition,
        feedback_status=GateStatus.FAIL,
        source_trace=("recommendation:sample",),
    )
    return {
        "stock_code": result.stock_code,
        "state": result.state.value,
        "reasons": list(result.reasons),
        "source_trace": list(result.source_trace),
        "auto_action_allowed": result.auto_action_allowed,
        "research_only": True,
        "warnings": ["position_health_state_is_not_an_order"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect the read-only V2.5 position health state.")
    parser.add_argument("--sample", action="store_true", help="Use only the built-in non-persistent sample.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()
    if not args.sample:
        parser.error("Only --sample is supported; this command never reads positions or writes a database.")
    payload = _sample_payload()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        return 0
    print("# V2.5 Position Health", end="\n\n")
    print(f"- stock_code: {payload['stock_code']}")
    print(f"- state: {payload['state']}")
    print("- auto_action_allowed: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
