"""建立正式 allocation OOS portfolio replay 與 latest complete pointer。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_module.allocation_oos_portfolio_replay import (  # noqa: E402
    AllocationOOSPortfolioReplayRequest,
    build_allocation_oos_portfolio_replay,
)


DEFAULT_OUTPUT_ROOT = (
    Path(
        os.environ.get(
            "OUTPUT_ROOT",
            "D:/Min/Python/Project/FA_Data/output",
        )
    )
    / "release_v4"
    / "ml_allocation_oos_replay_production_v4"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-manifest", type=Path, required=True)
    parser.add_argument(
        "--replay-input-manifest",
        type=Path,
        help=(
            "預設讀取 training run 內 "
            "artifacts/oos_portfolio_replay_inputs/manifest.json"
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )
    parser.add_argument(
        "--role",
        choices=("primary", "verification"),
        required=True,
    )
    parser.add_argument("--replay-run-id", required=True)
    parser.add_argument(
        "--replay-as-of",
        type=_aware_datetime,
        required=True,
        help="含時區 ISO datetime；晚於此時間的 outcome 一律 fail closed",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_standard_streams_utf8()
    args = _parser().parse_args(argv)
    try:
        request = AllocationOOSPortfolioReplayRequest(
            training_manifest_path=args.training_manifest,
            replay_input_manifest_path=args.replay_input_manifest,
            output_root=args.output_root,
            replay_run_id=args.replay_run_id,
            role=args.role,
            replay_as_of=args.replay_as_of,
        )
        result = build_allocation_oos_portfolio_replay(request)
    except (OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                    "broker_order_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    payload = {
        "status": result.status,
        "replay_run_id": result.replay_run_id,
        "role": result.role,
        "blockers": list(result.blockers),
        "replay_path": str(result.replay_path),
        "replay_file_hash": result.replay_file_hash,
        "replay_result_hash": result.replay_result_hash,
        "manifest_hash": result.manifest_hash,
        "latest_pointer_path": str(result.latest_pointer_path),
        "latest_pointer_updated": result.latest_pointer_updated,
        "idempotent": result.idempotent,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
    }
    stream = sys.stdout if result.status == "complete" else sys.stderr
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stream)
    return 0 if result.status == "complete" else 2


def _aware_datetime(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--replay-as-of 必須為 ISO datetime"
        ) from exc
    if result.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "--replay-as-of 必須明確包含時區"
        )
    return result


def _configure_standard_streams_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
