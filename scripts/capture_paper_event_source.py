"""在合法台北 session 內保存 Paper 用官方 MIS quote source。

正式 caller 以 ``--recommendation-json`` 傳入已凍結 recommendation，並以
``--durable-root`` 將同一份 raw/envelope 以 hash-pinned create-only 方式保存；
TEMP 只是 HTTP candidate。這個入口不建立 Paper fill、不修改任何 SQLite，
也不把 source capture 自動提升為 Formal input。
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

from data_module.paper_event_source_capture import (  # noqa: E402
    PaperEventSourceCaptureError,
    _parse_date,
    _read_symbols_file,
    capture_twse_session_open_prices,
    capture_twse_session_open_prices_for_recommendation,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-date", required=True)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--recommendation-json", type=Path)
    source_group.add_argument("--symbols", help="逗號分隔的四碼 TWSE 代號")
    source_group.add_argument("--symbols-file", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--durable-root",
        type=Path,
        help=(
            "受控 repository output/paper_execution_eod_replay/event_captures "
            "根目錄；recommendation 路徑必須提供"
        ),
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-live-readonly", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not args.live or not args.confirm_live_readonly:
            raise PaperEventSourceCaptureError(
                "官方 Paper capture 必須同時帶 --live 與 --confirm-live-readonly"
            )
        execution_date = _parse_date(args.execution_date)
        if args.recommendation_json is not None:
            if args.durable_root is None:
                raise PaperEventSourceCaptureError(
                    "--recommendation-json 必須同時帶 --durable-root"
                )
            result = capture_twse_session_open_prices_for_recommendation(
                recommendation_path=args.recommendation_json,
                execution_date=execution_date,
                output_dir=args.output_dir,
                durable_root=args.durable_root,
                timeout_seconds=args.timeout_seconds,
            )
        elif args.symbols_file is not None:
            symbols = _read_symbols_file(args.symbols_file)
            result = capture_twse_session_open_prices(
                symbols=symbols,
                execution_date=execution_date,
                output_dir=args.output_dir,
                timeout_seconds=args.timeout_seconds,
            )
        else:
            assert args.symbols is not None
            symbols = tuple(item.strip() for item in args.symbols.split(","))
            result = capture_twse_session_open_prices(
                symbols=symbols,
                execution_date=execution_date,
                output_dir=args.output_dir,
                timeout_seconds=args.timeout_seconds,
            )
    except (OSError, TypeError, ValueError, PaperEventSourceCaptureError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "reason": str(error),
                    "formal_credit": False,
                    "broker_order_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
