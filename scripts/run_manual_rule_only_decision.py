"""Owner-invoked foreground producer for one Rule-only formal source artifact.

This is intentionally not a scheduler and it does not append the evidence
ledger.  It only creates a TEMP ``manual_observed`` source during the actual
bound Taiwan session; the existing manual capture command remains a separate,
explicit owner action.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from development_module.manual_rule_only_decision import (
    MANUAL_CONFIRMATION,
    ManualRuleOnlyDecisionError,
    produce_manual_rule_only_decision,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="在實際台灣盤中手動產生一筆 TEMP-only Rule-only 觀測來源。"
    )
    parser.add_argument(
        "--development-output-root",
        required=True,
        help="名稱必須為 technical_analysis_development_output 的 TEMP 根目錄",
    )
    parser.add_argument(
        "--market-db",
        required=True,
        help="唯讀 daily_prices SQLite 路徑；本工具不寫入此資料庫",
    )
    parser.add_argument(
        "--lane-decision-json",
        required=True,
        help="development output root 內已綁定的 FormalObservationLaneDecision JSON",
    )
    parser.add_argument(
        "--universe-symbols-json",
        type=Path,
        default=None,
        help="可選的 clock-bound sorted company symbol JSON；缺少時使用完整 daily_prices universe",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=f"必須完全等於：{MANUAL_CONFIRMATION}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Windows terminals inherited by automation can use a legacy code page.
    # The decision artifact paths and operator diagnostics are Traditional
    # Chinese, so make this foreground CLI self-contained rather than failing
    # while argparse tries to print --help or a rejection reason.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")
    args = build_parser().parse_args(argv)
    try:
        eligible_symbols = None
        if args.universe_symbols_json is not None:
            try:
                value = json.loads(
                    args.universe_symbols_json.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ManualRuleOnlyDecisionError(
                    "clock_bound_rule_universe_json_unreadable"
                ) from exc
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                raise ManualRuleOnlyDecisionError(
                    "clock_bound_rule_universe_json_invalid"
                )
            eligible_symbols = tuple(value)
        result = produce_manual_rule_only_decision(
            development_output_root=args.development_output_root,
            market_db=args.market_db,
            lane_decision_json=args.lane_decision_json,
            confirmation=args.confirm,
            eligible_symbols=eligible_symbols,
        )
    except ManualRuleOnlyDecisionError as exc:
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "reason": str(exc),
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
