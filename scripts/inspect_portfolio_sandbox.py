from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.portfolio_construction_dtos import (  # noqa: E402
    PortfolioConstructionCandidate,
    PortfolioConstructionRequest,
)
from app_module.portfolio_construction_service import PortfolioConstructionService  # noqa: E402
from app_module.portfolio_execution_trace_service import PortfolioExecutionTraceService  # noqa: E402


def _sample_payload() -> dict[str, Any]:
    request = PortfolioConstructionRequest(
        decision_date="2026-07-05",
        capital_amount=Decimal("500000"),
        allocation_method="score_weight",
        candidates=(
            PortfolioConstructionCandidate("2330", "TSMC", score_bp=9000, reference_price=Decimal("100")),
            PortfolioConstructionCandidate("2317", "Hon Hai", score_bp=6000, reference_price=Decimal("50")),
        ),
        max_position_weight_bp=7000,
        lot_size=1000,
    )
    construction = PortfolioConstructionService().construct(request)
    trace_events = PortfolioExecutionTraceService().build_trace(
        construction,
        partial_fill_bp_by_symbol={"2330": 5000},
        rejected_symbols={"2317": "research_rejected_sample"},
    )
    payload = construction.to_dict()
    payload["trace_events"] = [event.to_dict() for event in trace_events]
    return payload


def _to_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Portfolio Sandbox Inspection",
        "",
        f"- decision_date: {payload['decision_date']}",
        f"- allocation_method: {payload['allocation_method']}",
        f"- research_basis: {payload['research_basis']}",
        f"- residual_cash: {payload['residual_cash']}",
        "",
        "## Allocations",
    ]
    for row in payload["allocations"]:
        lines.append(
            f"- {row['stock_code']} {row['stock_name']}: "
            f"{row['constrained_weight_bp']} bp, shares={row['executable_shares']}, "
            f"amount={row['executable_amount']}"
        )
    lines.extend(["", "## Trace Events"])
    for event in payload["trace_events"]:
        lines.append(
            f"- {event['event_type']} {event['stock_code']} "
            f"qty={event['quantity']} filled={event['filled_quantity']} "
            f"reason={event['reason_code']}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect V1.8 research-only portfolio sandbox sample.")
    parser.add_argument("--sample", action="store_true", help="Output built-in sample without reading formal data.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()

    if not args.sample:
        parser.error("Only --sample is supported to avoid reading formal data by mistake.")

    payload = _sample_payload()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    else:
        print(_to_markdown(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
