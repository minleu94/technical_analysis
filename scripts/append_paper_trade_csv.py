"""受控 append Paper Trade Ledger 的 CSV producer。

預設只預覽與驗證；只有傳入 ``--confirm-append-paper-ledger`` 才會建立
ledger SQLite 並 atomic append。此入口只寫研究用 Paper Trade Ledger，
不改手動 Portfolio、Paper snapshot、正式市場資料或 broker。
"""

from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.paper_trade_import_service import (  # noqa: E402
    PAPER_TRADE_IMPORT_SCHEMA_VERSION,
    PaperTradeImportService,
)
from runtime.console_encoding import configure_utf8_console  # noqa: E402


def _preview_payload(source_path: Path, preview) -> dict[str, Any]:
    total_cost = sum(
        (fill.total_cost for fill in PaperTradeImportService().build_fills(preview)),
        start=Decimal("0"),
    )
    return {
        "schema_version": PAPER_TRADE_IMPORT_SCHEMA_VERSION,
        "input_path": str(source_path.resolve()),
        "source_hash": f"sha256:{preview.source_hash}",
        "encoding": preview.encoding,
        "row_count": len(preview.rows),
        "valid_row_count": len(preview.valid_rows),
        "invalid_row_count": len(preview.invalid_rows),
        "total_cost": str(total_cost.quantize(Decimal("0.01"))),
        "warnings": list(preview.warnings),
        "research_only": True,
        "broker_order_allowed": False,
        "auto_rebalance_allowed": False,
        "write_performed": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--ledger-db", type=Path, required=True)
    parser.add_argument("--confirm-append-paper-ledger", action="store_true")
    args = parser.parse_args(argv)

    try:
        service = PaperTradeImportService()
        preview = service.preview_csv(args.input_csv)
        if not preview.ready_to_import:
            payload = {
                "status": "rejected",
                "schema_version": PAPER_TRADE_IMPORT_SCHEMA_VERSION,
                "input_path": str(args.input_csv.resolve()),
                "source_hash": f"sha256:{preview.source_hash}",
                "row_count": len(preview.rows),
                "invalid_row_count": len(preview.invalid_rows),
                "warnings": list(preview.warnings),
                "errors": [
                    {
                        "row_number": row.row_number,
                        "errors": list(row.errors),
                    }
                    for row in preview.invalid_rows
                ],
                "write_performed": False,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            return 2

        payload = _preview_payload(args.input_csv, preview)
        if args.confirm_append_paper_ledger:
            fills = service.commit(preview, args.ledger_db, confirm=True)
            payload["write_performed"] = True
            payload["fill_count"] = len(fills)
            payload["ledger_db"] = str(args.ledger_db.resolve())
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, TypeError, ArithmeticError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
