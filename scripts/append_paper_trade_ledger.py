"""受控 append Paper Trade Ledger fill events。

預設只驗證並輸出預覽；只有傳入
``--confirm-append-paper-ledger`` 才會建立 ledger SQLite 並 append。這個
入口不接受 broker order，也不會修改手動 Portfolio 的 trades.jsonl。
"""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.paper_trade_ledger import (  # noqa: E402
    PAPER_TRADE_LEDGER_SCHEMA_VERSION,
    PaperTradeFill,
    PaperTradeLedgerRepository,
)
from runtime.console_encoding import configure_utf8_console  # noqa: E402


def _load_fills(path: Path) -> tuple[PaperTradeFill, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_fills: object
    if isinstance(payload, Mapping):
        raw_fills = payload.get("fills")
    else:
        raw_fills = payload
    if not isinstance(raw_fills, list) or not raw_fills:
        raise ValueError("input JSON must contain a non-empty fills list")
    fills: list[PaperTradeFill] = []
    for index, raw in enumerate(raw_fills, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"fill {index} must be an object")
        fills.append(_fill_from_mapping(raw, index=index))
    return tuple(fills)


def _fill_from_mapping(raw: Mapping[str, Any], *, index: int) -> PaperTradeFill:
    def required_text(name: str) -> str:
        value = str(raw.get(name, "")).strip()
        if not value:
            raise ValueError(f"fill {index}: {name} is required")
        return value

    def required_int(name: str) -> int:
        value = raw.get(name)
        if isinstance(value, bool):
            raise ValueError(f"fill {index}: {name} must be an integer")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"fill {index}: {name} must be an integer") from exc

    def required_decimal(name: str) -> Decimal:
        value = raw.get(name)
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"fill {index}: {name} must be Decimal text") from exc
        return parsed

    def optional_decimal(name: str) -> Decimal | None:
        value = raw.get(name)
        if value is None or str(value).strip() == "":
            return None
        return required_decimal(name)

    def optional_int(name: str) -> int | None:
        value = raw.get(name)
        if value is None or str(value).strip() == "":
            return None
        if isinstance(value, bool):
            raise ValueError(f"fill {index}: {name} must be an integer")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"fill {index}: {name} must be an integer") from exc

    override_reason = raw.get("override_reason")
    return PaperTradeFill(
        fill_id=required_text("fill_id"),
        order_id=required_text("order_id"),
        portfolio_id=str(raw.get("portfolio_id") or "paper-main").strip(),
        event_date=required_text("event_date"),
        stock_code=required_text("stock_code"),
        side=required_text("side"),
        requested_quantity=required_int("requested_quantity"),
        filled_quantity=required_int("filled_quantity"),
        reference_price=required_decimal("reference_price"),
        fill_price=optional_decimal("fill_price"),
        commission=required_decimal("commission"),
        tax=required_decimal("tax"),
        slippage_cost=required_decimal("slippage_cost"),
        turnover_bp=optional_int("turnover_bp"),
        execution_gap_bp=optional_int("execution_gap_bp"),
        status=required_text("status"),
        source_event_id=required_text("source_event_id"),
        override_reason=(None if override_reason is None else str(override_reason)),
        source_type=str(raw.get("source_type") or "paper_simulation"),
        research_only=bool(raw.get("research_only", True)),
        broker_order_allowed=bool(raw.get("broker_order_allowed", False)),
        auto_rebalance_allowed=bool(raw.get("auto_rebalance_allowed", False)),
    )


def _preview_payload(input_path: Path, fills: tuple[PaperTradeFill, ...]) -> dict[str, Any]:
    statuses = Counter(item.status for item in fills)
    return {
        "schema_version": PAPER_TRADE_LEDGER_SCHEMA_VERSION,
        "input_path": str(input_path.resolve()),
        "fill_count": len(fills),
        "statuses": dict(sorted(statuses.items())),
        "total_cost": str(sum((item.total_cost for item in fills), Decimal("0")).quantize(Decimal("0.01"))),
        "research_only": True,
        "broker_order_allowed": False,
        "auto_rebalance_allowed": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--ledger-db", type=Path, required=True)
    parser.add_argument("--confirm-append-paper-ledger", action="store_true")
    args = parser.parse_args(argv)

    try:
        fills = _load_fills(args.input_json)
        payload = _preview_payload(args.input_json, fills)
        payload["write_performed"] = False
        if args.confirm_append_paper_ledger:
            PaperTradeLedgerRepository(args.ledger_db).append_many(fills)
            payload["write_performed"] = True
            payload["ledger_db"] = str(args.ledger_db.resolve())
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
