"""Create the approved future-effective Paper machine policy artifact.

The command is intentionally explicit about the approval reference.  It only
writes repository-isolated immutable policy/activation receipts and never
touches Paper, Formal, broker, or D: raw data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.forward_machine_policy_producer import (  # noqa: E402
    DEFAULT_ACTOR,
    DEFAULT_POLICY_ID,
    DEFAULT_RULES,
    DEFAULT_SOURCE,
    ForwardMachinePolicyProducer,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create an immutable, future-effective research-only Paper machine policy."
    )
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--calendar-cache", required=True)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--policy-id", default=DEFAULT_POLICY_ID)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--actor", default=DEFAULT_ACTOR)
    parser.add_argument("--holding-horizon-trading-days", type=int, default=20)
    parser.add_argument("--review-cadence-trading-days", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = ForwardMachinePolicyProducer(
        args.output_root,
        calendar_cache_path=args.calendar_cache,
    ).create(
        policy_id=args.policy_id,
        version=args.version,
        source=args.source,
        actor=args.actor,
        approval_reference=args.approval_reference,
        holding_horizon_trading_days=args.holding_horizon_trading_days,
        review_cadence_trading_days=args.review_cadence_trading_days,
        rules=DEFAULT_RULES,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("status") in {"created", "idempotent"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
