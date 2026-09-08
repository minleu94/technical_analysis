"""建立一個可由 AllocationReleaseAdapter 載入的 v3 h5 線性 shadow release。

執行前應先完成同一組 input/parent/output 的 preflight。正式執行固定以
release_v4 共用 OS lock 持有全生命週期；Direct
parent 與 official market SQLite 只讀，所有 production/formal/broker 權限
固定關閉，亦不讀 fold-005/006 以後的資料。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.ml_storage_capacity import StorageCapacityError  # noqa: E402
# Importing the application adapter bootstraps the neutral release loader.  The
# producer itself remains free of app_module imports, while published artifacts
# still require the real adapter readback before the CLI can succeed.
from app_module import allocation_release_adapter as _release_adapter  # noqa: E402,F401
from ml_module.allocation_v3_linear_release import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    MAX_FIT_SAMPLE_ROWS,
    V3LinearReleaseRequest,
    build_v3_linear_release,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v3-input", type=Path, required=True)
    parser.add_argument("--parent-store-manifest", type=Path, required=True)
    parser.add_argument("--market-database", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--fit-sample-rows",
        type=int,
        default=MAX_FIT_SAMPLE_ROWS,
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--heavy-lock-path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    request = V3LinearReleaseRequest(
        v3_input_path=args.v3_input,
        parent_store_manifest_path=args.parent_store_manifest,
        market_database_path=args.market_database,
        output_root=args.output_root,
        fit_sample_rows=args.fit_sample_rows,
        batch_size=args.batch_size,
        # production CLI 不提供繞過共用 lock 的分支；library helper 仍保留
        # explicit flag 供 bounded unit fixture 使用。
        acquire_heavy_lock=True,
        heavy_lock_path=args.heavy_lock_path,
    )
    try:
        result = build_v3_linear_release(request)
    except (OSError, TypeError, ValueError, KeyError, StorageCapacityError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                    "production_action_allowed": False,
                    "broker_order_allowed": False,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
