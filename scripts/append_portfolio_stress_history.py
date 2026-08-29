"""受控保存 Portfolio Stress Lab 研究歷史快照。

預設只驗證並輸出預覽；只有傳入 ``--confirm-save-stress-history`` 才會
建立指定的 append-only history SQLite。此 CLI 不修改持倉、交易或正式資料。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.portfolio_stress_history import (  # noqa: E402
    STRESS_HISTORY_SCHEMA_VERSION,
    PortfolioStressHistoryRecord,
    PortfolioStressHistoryRepository,
)
from runtime.console_encoding import configure_utf8_console  # noqa: E402


def _load_payload(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("input JSON must contain one stress result object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    # Render the Chinese argparse description safely on Windows cp1252 hosts.
    configure_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--history-db", type=Path, required=True)
    parser.add_argument("--confirm-save-stress-history", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = _load_payload(args.input_json)
        record = PortfolioStressHistoryRecord.from_payload(payload)
        result: dict[str, Any] = {
            "schema_version": STRESS_HISTORY_SCHEMA_VERSION,
            "input_path": str(args.input_json.resolve()),
            "history_db": str(args.history_db.resolve()),
            "record": record.to_dict(),
            "write_performed": False,
            "research_only": True,
            "investment_effectiveness_claim": False,
            "writes_allowed": False,
        }
        if args.confirm_save_stress_history:
            PortfolioStressHistoryRepository(args.history_db).append(record)
            result["write_performed"] = True
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, ArithmeticError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
