"""以官方 daily-price overlay 建立隔離 raw diagnostic／label impact artifact。

入口只讀取既有 SQLite、overlay 與可選的極值 audit；不訓練、不改資料，
同日收盤／成交量只作事後 raw diagnostic，盤前 model input 僅取前一交易日，
並將事後觀察時間保留在輸出中。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.ml_daily_price_overlay_consumer import (  # noqa: E402
    POST_CAPTURE_RESEARCH_MODE,
    build_daily_price_overlay_impact,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--benchmark-entity", default="TAIEX")
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--baseline-extreme-audit", type=Path)
    parser.add_argument(
        "--research-mode",
        default=POST_CAPTURE_RESEARCH_MODE,
        choices=(POST_CAPTURE_RESEARCH_MODE,),
        help="明確指定事後擷取研究模式；不得切換為正式決策／訓練模式",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_daily_price_overlay_impact(
        overlay_path=args.overlay,
        sqlite_path=args.sqlite,
        output_path=args.output,
        benchmark_entity=args.benchmark_entity,
        horizon=args.horizon,
        baseline_extreme_audit_path=args.baseline_extreme_audit,
        research_mode=args.research_mode,
    )
    print(
        json.dumps(
            {
                "output_path": str(result.output_path.resolve()),
                "impact_hash": result.output_hash,
                "row_count": result.row_count,
                "raw_diagnostic_changed_feature_count": result.changed_feature_count,
                "decision_time_feature_changed_count": (
                    result.decision_time_feature_changed_count
                ),
                "changed_label_count": result.changed_label_count,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
