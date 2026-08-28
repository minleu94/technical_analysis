"""Export an empty, governed Paper trade fills CSV template.

The template contains headers only.  It never creates a Paper Trade Ledger,
does not infer fills from Portfolio history, and refuses to overwrite an
existing file unless ``--overwrite`` is explicitly supplied.
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

from app_module.paper_trade_import_service import (  # noqa: E402
    PAPER_TRADE_IMPORT_FIELDS,
    PAPER_TRADE_IMPORT_SCHEMA_VERSION,
    PaperTradeImportService,
)


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="允許覆寫既有範本；不會覆寫 Paper ledger 或正式資料。",
    )
    args = parser.parse_args(argv)

    try:
        path = PaperTradeImportService.write_template(args.output_csv, overwrite=args.overwrite)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
        return 2

    payload: dict[str, Any] = {
        "status": "created",
        "schema_version": PAPER_TRADE_IMPORT_SCHEMA_VERSION,
        "output_csv": str(path),
        "fields": list(PAPER_TRADE_IMPORT_FIELDS),
        "row_count": 0,
        "write_performed": True,
        "writes_paper_ledger": False,
        "research_only": True,
        "broker_order_allowed": False,
        "auto_rebalance_allowed": False,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _configure_utf8_stdio() -> None:
    """讓直接執行腳本的 Windows 主控台也能顯示繁中說明與診斷。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            # 測試 capture stream 或外部 host 管理的 stream 可能禁止重設；
            # 這不應改變範本產製結果。
            continue


if __name__ == "__main__":
    raise SystemExit(main())
