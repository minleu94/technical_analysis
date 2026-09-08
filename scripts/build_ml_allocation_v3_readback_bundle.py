"""保存 v3 research readback 的小型 immutable content-addressed bundle。
命令只讀 frozen v3 input 與既有 release/training manifest，將 input bytes 與
必要 lineage metadata 寫入新的 repo output 目錄；不讀取或複製 D 槽 Direct/PIT
資料，不訓練，也不修改 release artifact。
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

from ml_module.allocation_v3_readback_bundle import (  # noqa: E402
    DEFAULT_MAX_BUNDLE_BYTES,
    create_readback_bundle,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v3-input", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--max-bundle-bytes",
        type=int,
        default=DEFAULT_MAX_BUNDLE_BYTES,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = create_readback_bundle(
            v3_input_path=args.v3_input,
            release_root=args.release_root,
            output_root=args.output_root,
            max_bundle_bytes=args.max_bundle_bytes,
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
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
