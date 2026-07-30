"""替 research-shadow allocation union 建立 T-1 recursive baseline ledger。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.ml_research_causal_ledger_overlay import (  # noqa: E402
    ResearchCausalLedgerOverlayBuilder,
    ResearchCausalLedgerOverlayRequest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-union-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--risky-budget-bp", type=int, default=8_000)
    parser.add_argument("--max-positions", type=int, default=8)
    parser.add_argument("--max-single-position-bp", type=int, default=1_500)
    parser.add_argument("--minimum-cash-bp", type=int, default=2_000)
    parser.add_argument("--weekly-turnover-cap-bp", type=int, default=2_000)
    parser.add_argument("--rebalance-band-bp", type=int, default=300)
    parser.add_argument("--minimum-trade-bp", type=int, default=200)
    parser.add_argument("--cooldown-trading-days", type=int, default=5)
    parser.add_argument("--buy-cost-bp", type=int, default=25)
    parser.add_argument("--sell-cost-bp", type=int, default=55)
    parser.add_argument("--compression-level", type=int, default=6)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_streams()
    args = _parser().parse_args(argv)
    try:
        publication = ResearchCausalLedgerOverlayBuilder().build(
            ResearchCausalLedgerOverlayRequest(
                research_union_manifest_path=(
                    args.research_union_manifest
                ),
                output_root=args.output_dir,
                risky_budget_bp=args.risky_budget_bp,
                max_positions=args.max_positions,
                max_single_position_bp=args.max_single_position_bp,
                minimum_cash_bp=args.minimum_cash_bp,
                weekly_turnover_cap_bp=args.weekly_turnover_cap_bp,
                rebalance_band_bp=args.rebalance_band_bp,
                minimum_trade_bp=args.minimum_trade_bp,
                cooldown_trading_days=args.cooldown_trading_days,
                buy_cost_bp=args.buy_cost_bp,
                sell_cost_bp=args.sell_cost_bp,
                compression_level=args.compression_level,
            )
        )
    except (
        OSError,
        TypeError,
        ValueError,
        KeyError,
        RuntimeError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "research_only": True,
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": "complete",
                "publication_id": publication.publication_id,
                "manifest_path": str(publication.manifest_path),
                "manifest_hash": publication.manifest_hash,
                "dataset_identity_hash": publication.dataset_identity_hash,
                "ledger_manifest_hash": (
                    publication.ledger_manifest_hash
                ),
                "sample_count": publication.sample_count,
                "non_cash_state_day_count": (
                    publication.non_cash_state_day_count
                ),
                "add_transition_count": (
                    publication.add_transition_count
                ),
                "reduce_transition_count": (
                    publication.reduce_transition_count
                ),
                "research_only": True,
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _configure_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
