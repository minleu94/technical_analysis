"""Captured official fixtures 對應的 P0 source-specific parsers。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import io
import json
from typing import Any, Callable, Mapping, Sequence

from data_module.p0_candidate_manifest import QuarantineRecord
from data_module.p0_source_candidate_contracts import NormalizedP0Observation


PARSER_VERSION = "p0-official-parser.v1"


@dataclass(frozen=True)
class RawFetchEnvelope:
    source_id: str
    source_version: str
    endpoint_id: str
    request_parameters: Mapping[str, object]
    fetched_at: datetime
    http_status: int
    http_headers: Mapping[str, object]
    payload: bytes

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("fetched_at 必須包含 timezone")


@dataclass(frozen=True)
class OfficialParserResult:
    accepted: tuple[NormalizedP0Observation, ...]
    quarantine: tuple[QuarantineRecord, ...]
    raw_row_count: int
    duplicate_row_count: int = 0
    blocked_row_count: int = 0

    @property
    def accepted_row_count(self) -> int:
        return len(self.accepted)

    @property
    def quarantine_row_count(self) -> int:
        return len(self.quarantine)

    def __post_init__(self) -> None:
        classified = self.accepted_row_count + self.quarantine_row_count + self.duplicate_row_count + self.blocked_row_count
        if classified != self.raw_row_count:
            raise ValueError("parser row conservation violated")


def _parse_timestamp(value: object) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("official publication timestamp 必須包含 timezone")
    return parsed


def _parse_yyyymmdd(value: object) -> str:
    return datetime.strptime(str(value).strip(), "%Y%m%d").date().isoformat()


def _parse_roc_date(value: object) -> str:
    normalized = str(value).strip().replace("-", "/")
    parts = normalized.split("/")
    if len(parts) != 3:
        raise ValueError("invalid ROC date")
    year, month, day = (int(part) for part in parts)
    return datetime(year + 1911, month, day).date().isoformat()


def _strict_int(value: object) -> int:
    if value is None or not str(value).strip():
        raise ValueError("missing integer")
    normalized = str(value).replace(",", "").strip()
    try:
        decimal_value = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("malformed integer") from exc
    integral = decimal_value.to_integral_value()
    if decimal_value != integral:
        raise ValueError("non-integral quantity")
    return int(integral)


def _raw_row_hash(row: Mapping[str, Any]) -> str:
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _quarantine(
    envelope: RawFetchEnvelope,
    row: Mapping[str, Any],
    *,
    reason_code: str,
    detail: str,
) -> QuarantineRecord:
    return QuarantineRecord.from_raw_row(
        run_id=sha256(envelope.payload).hexdigest()[:16],
        source_id=envelope.source_id,
        source_version=envelope.source_version,
        raw_row=row,
        reason_code=reason_code,
        detail=detail,
    )

def _json_payload(envelope: RawFetchEnvelope) -> Mapping[str, Any]:
    decoded = json.loads(envelope.payload.decode("utf-8-sig"))
    if not isinstance(decoded, Mapping):
        raise ValueError("official payload root 必須是 object")
    return decoded


def _twse_rows(payload: Mapping[str, Any], *, table_mode: bool) -> Sequence[Mapping[str, Any]]:
    if table_mode:
        tables = payload.get("tables")
        if not isinstance(tables, list):
            raise ValueError("schema drift: tables missing")
        rows: list[Mapping[str, Any]] = []
        for table in tables:
            if not isinstance(table, Mapping):
                continue
            fields, data = table.get("fields"), table.get("data")
            if isinstance(fields, list) and isinstance(data, list):
                rows.extend(dict(zip(fields, row)) for row in data if isinstance(row, list))
        return rows
    fields, data = payload.get("fields"), payload.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        raise ValueError("schema drift: fields/data missing")
    return tuple(dict(zip(fields, row)) for row in data if isinstance(row, list))


def _build_twse_result(
    envelope: RawFetchEnvelope,
    *,
    table_mode: bool,
    quantity_parser: Callable[[Mapping[str, Any]], tuple[dict[str, int], tuple[str, ...]]],
    malformed_reason: str,
) -> OfficialParserResult:
    payload = _json_payload(envelope)
    rows = _twse_rows(payload, table_mode=table_mode)
    publication_at = _parse_timestamp(payload.get("publicationTime"))
    observation_date = _parse_yyyymmdd(payload.get("date"))
    accepted: list[NormalizedP0Observation] = []
    quarantine: list[QuarantineRecord] = []
    for row in rows:
        try:
            symbol = str(row.get("證券代號") or row.get("股票代號") or "").strip()
            if not symbol:
                raise ValueError("missing symbol")
            quantities, warnings = quantity_parser(row)
            accepted.append(
                NormalizedP0Observation.build(
                    source_id=envelope.source_id,
                    source_version=envelope.source_version,
                    symbol=symbol,
                    observation_date=observation_date,
                    period="daily",
                    publication_at=publication_at,
                    first_observed_at=envelope.fetched_at,
                    raw_payload_sha256=_raw_row_hash(row),
                    quantities=quantities,
                    warnings=warnings,
                )
            )
        except (TypeError, ValueError) as exc:
            quarantine.append(
                _quarantine(envelope, row, reason_code=malformed_reason, detail=str(exc))
            )
    return OfficialParserResult(
        accepted=tuple(accepted),
        quarantine=tuple(quarantine),
        raw_row_count=len(rows),
    )


def parse_twse_institutional(envelope: RawFetchEnvelope) -> OfficialParserResult:
    def quantities(row: Mapping[str, Any]) -> tuple[dict[str, int], tuple[str, ...]]:
        return (
            {
                "foreign_buy_shares": _strict_int(row.get("外陸資買進股數(不含外資自營商)")),
                "foreign_sell_shares": _strict_int(row.get("外陸資賣出股數(不含外資自營商)")),
                "foreign_net_shares": _strict_int(row.get("外陸資買賣超股數(不含外資自營商)")),
            },
            (),
        )

    return _build_twse_result(
        envelope,
        table_mode=False,
        quantity_parser=quantities,
        malformed_reason="malformed_required_quantity",
    )


def parse_twse_credit(envelope: RawFetchEnvelope) -> OfficialParserResult:
    payload = _json_payload(envelope)
    tables = payload.get("tables")
    if not isinstance(tables, list):
        raise ValueError("schema drift: tables missing")

    # TWSE 現行信用交易明細表使用兩組重複的「買進／賣出」欄名，
    # 因此不能以欄名 zip 後再取值；明細表的欄位位置才是穩定契約。
    detail_table = next(
        (
            table
            for table in tables
            if isinstance(table, Mapping)
            and isinstance(table.get("fields"), list)
            and isinstance(table.get("data"), list)
            and "代號" in table["fields"]
            and "名稱" in table["fields"]
        ),
        None,
    )
    if detail_table is not None:
        publication_at = _parse_timestamp(payload.get("publicationTime"))
        observation_date = _parse_yyyymmdd(payload.get("date"))
        accepted: list[NormalizedP0Observation] = []
        quarantine: list[QuarantineRecord] = []
        rows = detail_table["data"]
        for raw_row in rows:
            if not isinstance(raw_row, list):
                continue
            row = {str(index): value for index, value in enumerate(raw_row)}
            try:
                if len(raw_row) < 13:
                    raise ValueError("credit detail row has insufficient columns")
                symbol = str(raw_row[0]).strip()
                if not symbol:
                    raise ValueError("missing symbol")
                accepted.append(
                    NormalizedP0Observation.build(
                        source_id=envelope.source_id,
                        source_version=envelope.source_version,
                        symbol=symbol,
                        observation_date=observation_date,
                        period="daily",
                        publication_at=publication_at,
                        first_observed_at=envelope.fetched_at,
                        raw_payload_sha256=_raw_row_hash(row),
                        quantities={
                            "margin_purchase_shares": _strict_int(raw_row[2]),
                            "margin_balance_shares": _strict_int(raw_row[6]),
                            "short_sale_shares": _strict_int(raw_row[9]),
                            "short_balance_shares": _strict_int(raw_row[12]),
                        },
                    )
                )
            except (TypeError, ValueError) as exc:
                quarantine.append(
                    _quarantine(
                        envelope,
                        row,
                        reason_code="malformed_credit_quantity",
                        detail=str(exc),
                    )
                )
        return OfficialParserResult(
            accepted=tuple(accepted),
            quarantine=tuple(quarantine),
            raw_row_count=len(rows),
        )

    field_map = {
        "margin_purchase_shares": "融資買進",
        "margin_balance_shares": "融資今日餘額",
        "short_sale_shares": "融券賣出",
        "short_balance_shares": "融券今日餘額",
    }

    def quantities(row: Mapping[str, Any]) -> tuple[dict[str, int], tuple[str, ...]]:
        parsed: dict[str, int] = {}
        warnings: list[str] = []
        for canonical, raw_name in field_map.items():
            raw_value = row.get(raw_name)
            if raw_value is None or not str(raw_value).strip():
                warnings.append(f"missing_quantity:{canonical}")
                continue
            parsed[canonical] = _strict_int(raw_value)
        if "margin_balance_shares" not in parsed:
            raise ValueError("missing required margin balance")
        return parsed, tuple(warnings)

    return _build_twse_result(
        envelope,
        table_mode=True,
        quantity_parser=quantities,
        malformed_reason="malformed_credit_quantity",
    )


def parse_tdcc_shareholding(envelope: RawFetchEnvelope) -> OfficialParserResult:
    text = envelope.payload.decode("utf-8-sig")
    rows = tuple(dict(row) for row in csv.DictReader(io.StringIO(text)))
    accepted: list[NormalizedP0Observation] = []
    quarantine: list[QuarantineRecord] = []
    for row in rows:
        try:
            symbol = str(row.get("證券代號") or "").strip()
            if not symbol:
                raise ValueError("missing symbol")
            ratio = Decimal(str(row.get("占集保庫存數比例%", "")).strip())
            ratio_bp = int((ratio * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))
            accepted.append(
                NormalizedP0Observation.build(
                    source_id=envelope.source_id,
                    source_version=envelope.source_version,
                    symbol=symbol,
                    observation_date=_parse_yyyymmdd(row.get("資料日期")),
                    period="weekly",
                    publication_at=None,
                    first_observed_at=envelope.fetched_at,
                    raw_payload_sha256=_raw_row_hash(row),
                    quantities={
                        "holder_tier": _strict_int(row.get("持股分級")),
                        "holder_count": _strict_int(row.get("人數")),
                        "shares": _strict_int(row.get("股數")),
                        "holding_ratio_bp": ratio_bp,
                    },
                )
            )
        except (InvalidOperation, TypeError, ValueError) as exc:
            quarantine.append(
                _quarantine(
                    envelope,
                    row,
                    reason_code="malformed_tdcc_row",
                    detail=str(exc),
                )
            )
    return OfficialParserResult(
        accepted=tuple(accepted),
        quarantine=tuple(quarantine),
        raw_row_count=len(rows),
    )


def parse_twse_disposition(envelope: RawFetchEnvelope) -> OfficialParserResult:
    """Parse TWSE disposition notices without inferring a publication timestamp."""
    payload = _json_payload(envelope)
    fields, raw_rows = payload.get("fields"), payload.get("data")
    if not isinstance(fields, list) or not isinstance(raw_rows, list):
        raise ValueError("schema drift: disposition fields/data missing")
    required = {"公布日期", "證券代號", "累計", "處置條件", "處置起迄時間", "處置措施", "處置內容"}
    if not required.issubset({str(field) for field in fields}):
        raise ValueError("schema drift: disposition required fields missing")

    accepted: list[NormalizedP0Observation] = []
    quarantine: list[QuarantineRecord] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, list):
            continue
        row = dict(zip((str(field) for field in fields), raw_row))
        try:
            symbol = str(row["證券代號"]).strip()
            if not symbol:
                raise ValueError("missing symbol")
            start_text, separator, end_text = str(row["處置起迄時間"]).strip().partition("～")
            if not separator:
                raise ValueError("missing disposition period separator")
            announcement_date = _parse_roc_date(row["公布日期"])
            effective_from = _parse_roc_date(start_text)
            effective_to = _parse_roc_date(end_text)
            accepted.append(
                NormalizedP0Observation.build(
                    source_id=envelope.source_id,
                    source_version=envelope.source_version,
                    symbol=symbol,
                    observation_date=announcement_date,
                    period="event",
                    publication_at=None,
                    first_observed_at=envelope.fetched_at,
                    raw_payload_sha256=_raw_row_hash(row),
                    quantities={"disposition_sequence": _strict_int(row["累計"])},
                    metadata={
                        "announcement_date": announcement_date,
                        "effective_from": effective_from,
                        "effective_to": effective_to,
                        "condition": str(row["處置條件"]).strip(),
                        "measure": str(row["處置措施"]).strip(),
                        "content": str(row["處置內容"]).strip(),
                    },
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            quarantine.append(_quarantine(envelope, row, reason_code="malformed_disposition_row", detail=str(exc)))
    return OfficialParserResult(accepted=tuple(accepted), quarantine=tuple(quarantine), raw_row_count=len(raw_rows))
