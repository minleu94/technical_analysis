"""在同程序內 gate 後執行預先登記的 fold-005 read-only comparison。

預設會讀取 fold-005 的 immutable parent source 並寫入獨立 repo output；
執行前請先由 reviewer 確認 preflight JSON。``--preflight-only`` 只讀
published receipt、parent/store manifest，不開啟 fold-005 price/label/result。
所有正式 alpha、broker 與 promotion flags 固定關閉。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.ml_storage_capacity import StorageCapacityError  # noqa: E402
from ml_module.allocation_confirmatory_runner import (  # noqa: E402
    ConfirmatoryComparisonExecutionError,
    preflight_confirmatory_comparison,
    run_confirmatory_comparison,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--published-comparison",
        type=Path,
        required=True,
        help="immutable exploratory fold-004 comparison.json receipt",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="獨立 repo output root；不可以是 parent/store 來源路徑",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="只驗證 gate 與 bound request，不讀 fold-005 source",
    )
    return parser


def _blocked(exc: Exception) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "blocked",
        "error_type": type(exc).__name__,
        "message": str(exc),
        "price_data_read": False,
        "label_data_read": False,
        "result_data_read": False,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
    }
    if isinstance(exc, ConfirmatoryComparisonExecutionError):
        # source phase 已經開始時，資料是否完整讀取只能依 receipt 判定；
        # 不可把 exception 方便地折成三個 false，掩蓋已暴露的 future data。
        result["status"] = "blocked_after_confirmatory_source_phase"
        result.update(
            {
                "phase": exc.exposure.get("phase"),
                "source_read_attempted": exc.exposure.get(
                    "source_read_attempted"
                ),
                "source_read_completed": exc.exposure.get(
                    "source_read_completed"
                ),
                "price_data_read": exc.exposure.get("price_data_read"),
                "label_data_read": exc.exposure.get("label_data_read"),
                "result_data_read": exc.exposure.get("result_data_read"),
                "exposure_receipt_path": str(exc.exposure_receipt_path),
                "exposure_status": exc.exposure.get("status"),
            }
        )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.preflight_only:
            result = preflight_confirmatory_comparison(
                args.published_comparison,
                output_root=args.output_root,
            )
        else:
            publication = run_confirmatory_comparison(
                args.published_comparison,
                output_root=args.output_root,
            )
            result = {
                "status": "confirmatory_comparison_completed",
                "comparison_path": str(publication.comparison_path),
                "comparison_hash": publication.comparison_hash,
                "latest_pointer_path": str(publication.latest_pointer_path),
                "run_id": publication.run_id,
                "output_size_bytes": publication.output_size_bytes,
                "capacity_preflight": dict(publication.capacity_preflight),
                "idempotent": publication.idempotent,
                "price_data_read": True,
                "label_data_read": True,
                "result_data_read": True,
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            }
    except (OSError, TypeError, ValueError, KeyError, StorageCapacityError) as exc:
        print(json.dumps(_blocked(exc), ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
