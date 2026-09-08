"""將 minimal OOC 線性 shadow run 發布成 daily 可載入的 ML release。

此 CLI 不訓練模型、不重建資料，只讀取已完成的
``allocation-ooc-training.v5`` 與其 frozen store。若 OOF 校準來源不足，
命令以 blocked 結束，不會把 diagnostic-only 結果標成可交付校準器。
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

from ml_module.allocation_ooc_release_builder import (  # noqa: E402
    AllocationOOCReleaseRequest,
    build_allocation_ooc_release,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--training-manifest",
        type=Path,
        required=True,
        help="已完成的 allocation-ooc-training.v5 manifest.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="獨立 release root；既有不同內容的檔案拒絕覆寫",
    )
    parser.add_argument(
        "--model-id",
        default="baldr-ml-allocation-bounded-v4-operational",
    )
    parser.add_argument("--policy-id", default="balanced-v4-operational")
    parser.add_argument("--batch-size", type=int, default=8_192)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8()
    args = _parser().parse_args(argv)
    try:
        publication = build_allocation_ooc_release(
            AllocationOOCReleaseRequest(
                training_manifest_path=args.training_manifest,
                output_root=args.output_root,
                model_id=args.model_id,
                policy_id=args.policy_id,
                batch_size=args.batch_size,
            )
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
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": "release_completed",
                "release_root": str(publication.release_root),
                "release_manifest": str(publication.release_manifest_path),
                "release_identity_hash": publication.release_identity_hash,
                "model_artifact_hash": publication.model_artifact_hash,
                "calibration_id": publication.calibration_id,
                "calibration_fit_fold_ids": list(
                    publication.calibration_fit_fold_ids
                ),
                "calibration_fit_row_count": publication.calibration_fit_row_count,
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "production_action_allowed": False,
                "broker_order_allowed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _configure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
