"""執行 v3 h5 線性 shadow release 的唯讀資料與容量 preflight。
這個入口不讀 fold-005/006 以後的資料，也不建立輸出目錄；它只驗證
post-freeze 60-feature input、唯讀 Direct parent、h5 labels、TAIEX close
衍生來源，以及 1 GiB/1 GiB/4 GiB/200 GiB 的 bounded policy。
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
from ml_module.allocation_v3_linear_release import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    MAX_FIT_SAMPLE_ROWS,
    V3LinearReleaseRequest,
    preflight_v3_linear_release,
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
        help="每個 bounded scope 的 deterministic sample 上限",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
    )
    parser.add_argument("--heavy-lock-path", type=Path)
    parser.add_argument("--output", type=Path, required=True)
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
        heavy_lock_path=args.heavy_lock_path,
    )
    try:
        result = preflight_v3_linear_release(request)
    except (OSError, TypeError, ValueError, KeyError, StorageCapacityError) as exc:
        result = {
            "schema_version": "allocation-v3-linear-shadow-release.v1",
            "status": "blocked",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "production_action_allowed": False,
            "broker_order_allowed": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": result["status"], "output": str(output)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
