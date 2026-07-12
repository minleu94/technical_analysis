"""券商分點 lots/amount records 的純 merge plan。"""

from typing import Any, Dict, List, Tuple


def merge_metric_records(
    lot_records: List[Dict[str, Any]],
    amount_records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

    def key_of(record: Dict[str, Any]) -> Tuple[str, str, str, str]:
        return (
            str(record.get("date", "")),
            str(record.get("trade_type", "")),
            str(record.get("branch_system_key", "")),
            str(record.get("counterparty_broker_code", "")),
        )

    def identity(record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            name: record.get(name)
            for name in (
                "date",
                "trade_type",
                "branch_system_key",
                "branch_broker_code",
                "branch_code",
                "branch_display_name",
                "counterparty_broker_code",
                "counterparty_broker_name",
            )
        }

    for record in lot_records:
        merged.setdefault(
            key_of(record),
            {
                **identity(record),
                "buy_lots": record.get("buy_lots"),
                "sell_lots": record.get("sell_lots"),
                "net_lots": record.get("net_lots"),
                "buy_amount_k_twd": None,
                "sell_amount_k_twd": None,
                "net_amount_k_twd": None,
                "lots_observed": True,
                "amount_observed": False,
                "lots_rank": record.get("metric_rank"),
                "amount_rank": None,
            },
        )

    for record in amount_records:
        key = key_of(record)
        if key not in merged:
            merged[key] = {
                **identity(record),
                "buy_lots": None,
                "sell_lots": None,
                "net_lots": None,
                "buy_amount_k_twd": record.get("buy_amount_k_twd"),
                "sell_amount_k_twd": record.get("sell_amount_k_twd"),
                "net_amount_k_twd": record.get("net_amount_k_twd"),
                "lots_observed": False,
                "amount_observed": True,
                "lots_rank": None,
                "amount_rank": record.get("metric_rank"),
            }
            continue
        merged[key].update(
            {
                "buy_amount_k_twd": record.get("buy_amount_k_twd"),
                "sell_amount_k_twd": record.get("sell_amount_k_twd"),
                "net_amount_k_twd": record.get("net_amount_k_twd"),
                "amount_observed": True,
                "amount_rank": record.get("metric_rank"),
            }
        )
    return list(merged.values())
