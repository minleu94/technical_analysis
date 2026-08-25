"""Fixture-only CLI for one prospective simulated Portfolio transition.

PFS-02 尚未是正式 activation runner；必須明確提供 ``--fixture-only``。CLI 只
寫呼叫端指定的 SQLite，不建立正式路徑、不讀 secret、不啟動 ML watcher。
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.formal_simulated_portfolio_ledger import (  # noqa: E402
    ZERO_CHAIN_HASH,
    SimulatedPortfolioLedgerError,
    append_simulated_transition,
    build_simulated_transition,
)
from data_module.prospective_formal_clock import (  # noqa: E402
    load_clock_manifest_for_capture,
)
from ml_module.allocation_contracts import (  # noqa: E402
    AllocationWeightContract,
    CausalPortfolioState,
)


def _parse_now(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include timezone")
    return parsed


def _read_object(path: Path) -> dict[str, object]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} root must be an object")
    return value


def _state(payload: dict[str, object]) -> CausalPortfolioState:
    weights = payload.get("weights")
    if not isinstance(weights, dict):
        raise ValueError("state weights must be an object")
    positions = weights.get("positions_bp")
    if not isinstance(positions, list):
        raise ValueError("state positions_bp must be an array")
    parsed_positions: list[tuple[str, int]] = []
    for row in positions:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("state position row is invalid")
        if not isinstance(row[0], str) or not row[0].strip():
            raise ValueError("state position symbol is invalid")
        parsed_positions.append((row[0], _integer(row[1], "state position weight")))
    return CausalPortfolioState.create(
        as_of_date=_text(payload.get("as_of_date"), "state as_of_date"),
        weights=AllocationWeightContract(
            positions_bp=tuple(parsed_positions),
            cash_bp=_integer(weights.get("cash_bp"), "state cash_bp"),
        ),
        weekly_turnover_used_bp=_integer(
            payload.get("weekly_turnover_used_bp"),
            "state weekly_turnover_used_bp",
        ),
    )


def _weights(payload: dict[str, object]) -> AllocationWeightContract:
    positions = payload.get("positions_bp")
    if not isinstance(positions, list):
        raise ValueError("desired weights positions_bp must be an array")
    parsed_positions: list[tuple[str, int]] = []
    for row in positions:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("desired weights position row is invalid")
        if not isinstance(row[0], str) or not row[0].strip():
            raise ValueError("desired weights position symbol is invalid")
        parsed_positions.append(
            (row[0], _integer(row[1], "desired weights position weight"))
        )
    return AllocationWeightContract(
        positions_bp=tuple(parsed_positions),
        cash_bp=_integer(payload.get("cash_bp"), "desired weights cash_bp"),
    )


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fixture-only append of one prospective simulated Portfolio transition。"
    )
    parser.add_argument("--fixture-only", action="store_true", required=True)
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--decision-date", required=True)
    parser.add_argument("--decision-at", required=True)
    parser.add_argument("--previous-trading-day", required=True)
    parser.add_argument("--input-state", type=Path, required=True)
    parser.add_argument("--desired-weights", type=Path, required=True)
    parser.add_argument("--feature-input-hash", required=True)
    parser.add_argument("--estimated-cost-bp", type=int, required=True)
    parser.add_argument("--output-weekly-turnover-used-bp", type=int, required=True)
    parser.add_argument("--previous-chain-hash", default=ZERO_CHAIN_HASH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        # This command is an activation-time capture entry.  The clock remains
        # immutable and is only read through the explicit elapsed-activation
        # loader; the planning loader would reject the valid activation day.
        clock = load_clock_manifest_for_capture(
            args.clock_manifest,
            now=_parse_now(args.now),
        )
        transition = build_simulated_transition(
            clock=clock,
            decision_date=args.decision_date,
            decision_at=args.decision_at,
            previous_trading_day=args.previous_trading_day,
            input_state=_state(_read_object(args.input_state)),
            desired_weights=_weights(_read_object(args.desired_weights)),
            feature_input_hash=args.feature_input_hash,
            estimated_cost_bp=args.estimated_cost_bp,
            output_weekly_turnover_used_bp=args.output_weekly_turnover_used_bp,
            previous_chain_hash=args.previous_chain_hash,
        )
        result = append_simulated_transition(args.sqlite, transition)
        print(
            json.dumps(
                {
                    "schema_version": "causal-simulated-portfolio-transition-result.v1",
                    "status": "idempotent" if result.idempotent else "appended",
                    "read_only": False,
                    "fixture_only": True,
                    "clock_id": transition.clock_id,
                    "decision_date": transition.decision_date,
                    "transition_hash": transition.transition_hash,
                    "chain_hash": transition.chain_hash,
                    "future_teacher_target_used": False,
                    "same_day_advice_used": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError, SimulatedPortfolioLedgerError) as error:
        print(
            json.dumps(
                {
                    "schema_version": "causal-simulated-portfolio-transition-result.v1",
                    "status": "blocked",
                    "fixture_only": True,
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                    "broker_order_allowed": False,
                    "secret_values_emitted": False,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
