"""Fail-closed TWSE T86 bytes-to-candidate normalizer。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import Any

from data_module.twse_t86_candidate_contracts import T86CandidateRow, T86NormalizationResult


NORMALIZER_VERSION = "twse-t86-normalizer.v2"


REQUIRED_FIELDS = (
    "證券代號", "證券名稱", "外陸資買進股數(不含外資自營商)",
    "外陸資賣出股數(不含外資自營商)", "外陸資買賣超股數(不含外資自營商)",
    "投信買進股數", "投信賣出股數", "投信買賣超股數",
    "自營商買進股數(自行買賣)", "自營商賣出股數(自行買賣)",
    "自營商買賣超股數(自行買賣)", "自營商買進股數(避險)",
    "自營商賣出股數(避險)", "自營商買賣超股數(避險)",
)

QUANTITY_FIELDS = {
    "foreign_buy_shares": REQUIRED_FIELDS[2], "foreign_sell_shares": REQUIRED_FIELDS[3],
    "foreign_net_shares": REQUIRED_FIELDS[4], "trust_buy_shares": REQUIRED_FIELDS[5],
    "trust_sell_shares": REQUIRED_FIELDS[6], "trust_net_shares": REQUIRED_FIELDS[7],
    "dealer_proprietary_buy_shares": REQUIRED_FIELDS[8],
    "dealer_proprietary_sell_shares": REQUIRED_FIELDS[9],
    "dealer_proprietary_net_shares": REQUIRED_FIELDS[10],
    "dealer_hedge_buy_shares": REQUIRED_FIELDS[11], "dealer_hedge_sell_shares": REQUIRED_FIELDS[12],
    "dealer_hedge_net_shares": REQUIRED_FIELDS[13],
}


def _integer(value: Any) -> int:
    text = str(value).replace(",", "").strip()
    if not text or text in {"--", "X", "null", "None"}:
        raise ValueError("missing_quantity")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("invalid_quantity") from exc
    if number != number.to_integral_value():
        raise ValueError("non_integer_quantity")
    return int(number)


def _row_hash(row: Any) -> str:
    return sha256(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def normalize_t86_payload(
    payload: bytes, *, observation_date: str, retrieved_at: datetime,
    allowed_symbols: set[str] | None = None,
) -> T86NormalizationResult:
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json_payload") from exc
    if document.get("stat") != "OK" or not isinstance(document.get("fields"), list) or not isinstance(document.get("data"), list):
        raise ValueError("invalid_t86_response")
    fields = tuple(str(value) for value in document["fields"])
    raw_rows = document["data"]
    schema_hash = sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()
    missing_fields = set(REQUIRED_FIELDS) - set(fields)
    if missing_fields:
        schema_quarantines = tuple({"reason": "schema_drift", "raw_row_sha256": _row_hash(row)} for row in raw_rows)
        return T86NormalizationResult((), len(raw_rows), 0, len(raw_rows), 0, 0, 0, schema_quarantines, (), (), (), fields, schema_hash, ("schema_drift",))

    accepted: list[T86CandidateRow] = []
    quarantines: list[dict[str, str]] = []
    ignored: list[dict[str, str]] = []
    by_symbol: dict[str, T86CandidateRow] = {}
    observed_symbols: set[str] = set()
    duplicate_count = conflict_count = 0
    for raw_row in raw_rows:
        raw_hash = _row_hash(raw_row)
        if not isinstance(raw_row, list) or len(raw_row) != len(fields):
            quarantines.append({"reason": "row_width_mismatch", "raw_row_sha256": raw_hash})
            continue
        item = dict(zip(fields, raw_row))
        symbol = str(item["證券代號"]).strip()
        if not re.fullmatch(r"[0-9A-Z]{4,10}", symbol):
            ignored.append({"reason": "non_security_or_subtotal", "raw_row_sha256": raw_hash})
            continue
        observed_symbols.add(symbol)
        if allowed_symbols is not None and symbol not in allowed_symbols:
            ignored.append({"reason": "outside_ordinary_stock_universe", "raw_row_sha256": raw_hash, "symbol": symbol})
            continue
        try:
            quantities = {name: _integer(item[field]) for name, field in QUANTITY_FIELDS.items()}
        except ValueError as exc:
            quarantines.append({"reason": str(exc), "raw_row_sha256": raw_hash, "symbol": symbol})
            continue
        candidate = T86CandidateRow(observation_date, symbol, str(item["證券名稱"]).strip(), quantities, raw_hash, retrieved_at)
        previous = by_symbol.get(symbol)
        if previous is not None:
            if previous.quantities == candidate.quantities:
                duplicate_count += 1
                ignored.append({"reason": "duplicate_identical", "raw_row_sha256": raw_hash, "symbol": symbol})
            else:
                conflict_count += 1
                quarantines.append({"reason": "natural_key_conflict", "raw_row_sha256": raw_hash, "symbol": symbol})
            continue
        by_symbol[symbol] = candidate
        accepted.append(candidate)
    return T86NormalizationResult(
        tuple(accepted), len(raw_rows), len(accepted), len(quarantines), len(ignored),
        duplicate_count, conflict_count, tuple(quarantines), tuple(ignored),
        tuple(sorted(by_symbol)), tuple(sorted(observed_symbols)), fields, schema_hash, (),
    )
