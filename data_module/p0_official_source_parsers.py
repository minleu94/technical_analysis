"""Captured official fixtures 對應的 P0 source-specific parsers。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import io
import json
import re
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
    normalized = re.sub(r"(\d+)年(\d+)月(\d+)日", r"\1/\2/\3", str(value).strip()).replace("-", "/")
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


def _normalized_mapping(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize BOM-prefixed official CSV/JSON keys without changing values."""

    return {str(key).lstrip("\ufeff").strip(): value for key, value in row.items()}


def _json_or_csv_rows(payload: bytes, *, source_name: str) -> tuple[dict[str, Any], ...]:
    """Read equivalent official JSON-array and CSV distributions fail-closed."""

    text = payload.decode("utf-8-sig")
    stripped = text.lstrip()
    if stripped.startswith("["):
        decoded = json.loads(text)
        if not isinstance(decoded, list):
            raise ValueError(f"schema drift: {source_name} JSON root must be a list")
        rows: list[dict[str, Any]] = []
        for item in decoded:
            if not isinstance(item, Mapping):
                rows.append({"_unparseable_row": item})
            else:
                rows.append(_normalized_mapping(item))
        return tuple(rows)
    if stripped.startswith("{"):
        raise ValueError(f"schema drift: {source_name} JSON root must be a list")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError(f"schema drift: {source_name} CSV header missing")
    return tuple(_normalized_mapping(dict(row)) for row in reader)


def parse_monthly_revenue_open_data(envelope: RawFetchEnvelope) -> OfficialParserResult:
    """Parse official revenue JSON or CSV; report date is not publication time."""

    rows = _json_or_csv_rows(envelope.payload, source_name="monthly revenue")
    required = {"出表日期", "資料年月", "公司代號", "營業收入-當月營收"}
    accepted: list[NormalizedP0Observation] = []
    quarantine: list[QuarantineRecord] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            if not required.issubset(set(row)):
                raise ValueError("monthly revenue required fields missing")
            symbol = str(row["公司代號"]).strip()
            period = str(row["資料年月"]).strip()
            if not symbol or not re.fullmatch(r"\d{5}", period):
                raise ValueError("malformed symbol or ROC period")
            report_date = _parse_roc_date(str(row["出表日期"])[:3] + "/" + str(row["出表日期"])[3:5] + "/" + str(row["出表日期"])[5:])
            accepted.append(NormalizedP0Observation.build(source_id=envelope.source_id, source_version=envelope.source_version, symbol=symbol, observation_date=report_date, period="monthly", publication_at=None, first_observed_at=envelope.fetched_at, raw_payload_sha256=_raw_row_hash(row), quantities={"monthly_revenue": _strict_int(row["營業收入-當月營收"])}, metadata={"report_date": report_date, "roc_period": period, "availability_policy": "first_observed_only_report_date_not_intraday_publication"}))
        except (KeyError, TypeError, ValueError) as exc:
            quarantine.append(_quarantine(envelope, row, reason_code="malformed_monthly_revenue_row", detail=str(exc)))
    return OfficialParserResult(accepted=tuple(accepted), quarantine=tuple(quarantine), raw_row_count=len(rows))


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


def _parse_tpex_date(value: object) -> str:
    """Normalize TPEx OpenAPI's ROC compact date (for example ``1150827``)."""

    normalized = str(value).strip()
    if re.fullmatch(r"\d{7}", normalized):
        return _parse_roc_date(
            f"{normalized[:3]}/{normalized[3:5]}/{normalized[5:]}"
        )
    if re.fullmatch(r"\d{8}", normalized):
        if normalized[:4] in {"19", "20"}:
            return _parse_yyyymmdd(normalized)
        raise ValueError("unsupported TPEx compact date")
    return _parse_roc_date(normalized)


def _build_tpex_openapi_result(
    envelope: RawFetchEnvelope,
    *,
    source_name: str,
    quantity_parser: Callable[[Mapping[str, Any]], tuple[dict[str, int], tuple[str, ...]]],
    malformed_reason: str,
) -> OfficialParserResult:
    """Parse TPEx OpenAPI list-of-object distributions with row conservation."""

    rows = _json_or_csv_rows(envelope.payload, source_name=source_name)
    if not rows:
        raise ValueError(f"schema drift: {source_name} rows missing")
    accepted: list[NormalizedP0Observation] = []
    quarantine: list[QuarantineRecord] = []
    for row in rows:
        try:
            symbol = str(
                row.get("SecuritiesCompanyCode")
                or row.get("證券代號")
                or row.get("股票代號")
                or ""
            ).strip()
            if not symbol:
                raise ValueError("missing symbol")
            observation_date = _parse_tpex_date(row.get("Date"))
            quantities, warnings = quantity_parser(row)
            accepted.append(
                NormalizedP0Observation.build(
                    source_id=envelope.source_id,
                    source_version=envelope.source_version,
                    symbol=symbol,
                    observation_date=observation_date,
                    period="daily",
                    publication_at=None,
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


def parse_tpex_institutional_openapi(envelope: RawFetchEnvelope) -> OfficialParserResult:
    """Parse TPEx's official daily institutional-flow OpenAPI fallback."""

    field_map = {
        "foreign_buy_shares": (
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Buy"
        ),
        "foreign_sell_shares": (
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Sell"
        ),
        "foreign_net_shares": (
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference"
        ),
    }

    def quantities(row: Mapping[str, Any]) -> tuple[dict[str, int], tuple[str, ...]]:
        return ({name: _strict_int(row[key]) for name, key in field_map.items()}, ())

    return _build_tpex_openapi_result(
        envelope,
        source_name="TPEx institutional flow",
        quantity_parser=quantities,
        malformed_reason="malformed_institutional_quantity",
    )


def parse_tpex_credit_openapi(envelope: RawFetchEnvelope) -> OfficialParserResult:
    """Parse TPEx's official daily margin-balance OpenAPI fallback."""

    field_map = {
        "margin_purchase_shares": "MarginPurchase",
        "margin_balance_shares": "MarginPurchaseBalance",
        "short_sale_shares": "ShortSale",
        "short_balance_shares": "ShortSaleBalance",
    }

    def quantities(row: Mapping[str, Any]) -> tuple[dict[str, int], tuple[str, ...]]:
        return ({name: _strict_int(row[key]) for name, key in field_map.items()}, ())

    return _build_tpex_openapi_result(
        envelope,
        source_name="TPEx credit transaction",
        quantity_parser=quantities,
        malformed_reason="malformed_credit_quantity",
    )


def parse_tdcc_shareholding(envelope: RawFetchEnvelope) -> OfficialParserResult:
    """Parse TDCC 1-5 from either the legacy CSV or official OpenAPI JSON."""

    rows = _json_or_csv_rows(envelope.payload, source_name="TDCC 1-5")
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


def parse_twse_periodic_call_auction(envelope: RawFetchEnvelope) -> OfficialParserResult:
    """Extract periodic-call-auction measures from official TWSE disposition notices."""
    disposition = parse_twse_disposition(envelope)
    periodic_measure = re.compile(r"(?:分鐘\s*撮合|分盤)")
    accepted = tuple(
        observation
        for observation in disposition.accepted
        if periodic_measure.search(
            f"{observation.metadata.get('measure', '')} {observation.metadata.get('content', '')}"
        )
    )
    return OfficialParserResult(
        accepted=accepted,
        quarantine=disposition.quarantine,
        raw_row_count=disposition.raw_row_count,
    )


def _request_date(envelope: RawFetchEnvelope) -> str:
    raw_date = envelope.request_parameters.get("date")
    if raw_date is None:
        return envelope.fetched_at.date().isoformat()
    if not isinstance(raw_date, str) or not re.fullmatch(r"\d{8}", raw_date):
        raise ValueError("malformed request date")
    return datetime.strptime(raw_date, "%Y%m%d").date().isoformat()


def parse_twse_full_delivery(envelope: RawFetchEnvelope) -> OfficialParserResult:
    """Parse the official altered-trading-method (full-delivery) daily snapshot."""
    payload = _json_payload(envelope)
    fields, raw_rows = payload.get("fields"), payload.get("data")
    if not isinstance(fields, list) or not isinstance(raw_rows, list):
        raise ValueError("schema drift: full-delivery fields/data missing")
    required = {"證券代號", "證券名稱", "分盤集合競價(以**表示)"}
    if not required.issubset({str(field) for field in fields}):
        raise ValueError("schema drift: full-delivery required fields missing")
    snapshot_date = _request_date(envelope)
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
            periodic_marker = str(row["分盤集合競價(以**表示)"]).strip()
            accepted.append(
                NormalizedP0Observation.build(
                    source_id=envelope.source_id,
                    source_version=envelope.source_version,
                    symbol=symbol,
                    observation_date=snapshot_date,
                    period="daily",
                    publication_at=None,
                    first_observed_at=envelope.fetched_at,
                    raw_payload_sha256=_raw_row_hash(row),
                    quantities={"full_delivery_member": 1},
                    metadata={
                        "event_type": "altered_trading_method_full_delivery_snapshot",
                        "snapshot_date": snapshot_date,
                        "security_name": str(row["證券名稱"]).strip(),
                        "periodic_call_auction_marker": periodic_marker == "**",
                    },
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            quarantine.append(_quarantine(envelope, row, reason_code="malformed_full_delivery_row", detail=str(exc)))
    return OfficialParserResult(accepted=tuple(accepted), quarantine=tuple(quarantine), raw_row_count=len(raw_rows))


def parse_twse_halt_resume(envelope: RawFetchEnvelope) -> OfficialParserResult:
    """Parse the official TWSE halt/resume table without inventing announcement time."""
    payload = _json_payload(envelope)
    fields, raw_rows = payload.get("fields"), payload.get("data")
    if not isinstance(fields, list) or not isinstance(raw_rows, list):
        raise ValueError("schema drift: halt/resume fields/data missing")
    required = {"證券代號", "暫停交易日期", "暫停交易時間", "恢復交易日期", "恢復交易時間"}
    if not required.issubset({str(field) for field in fields}):
        raise ValueError("schema drift: halt/resume required fields missing")
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
            halt_date = _parse_roc_date(row["暫停交易日期"])
            resume_date = _parse_roc_date(row["恢復交易日期"])
            accepted.append(
                NormalizedP0Observation.build(
                    source_id=envelope.source_id,
                    source_version=envelope.source_version,
                    symbol=symbol,
                    observation_date=halt_date,
                    period="event",
                    publication_at=None,
                    first_observed_at=envelope.fetched_at,
                    raw_payload_sha256=_raw_row_hash(row),
                    quantities={"halt_resume_event": 1},
                    metadata={
                        "event_type": "suspended_halt_resume",
                        "halt_date": halt_date,
                        "halt_time": str(row["暫停交易時間"]).strip(),
                        "resume_date": resume_date,
                        "resume_time": str(row["恢復交易時間"]).strip(),
                    },
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            quarantine.append(_quarantine(envelope, row, reason_code="malformed_halt_resume_row", detail=str(exc)))
    return OfficialParserResult(accepted=tuple(accepted), quarantine=tuple(quarantine), raw_row_count=len(raw_rows))


def parse_twse_ex_dividend(envelope: RawFetchEnvelope) -> OfficialParserResult:
    """Parse the official ex-right/ex-dividend calculation table as an observed candidate."""
    payload = _json_payload(envelope)
    fields, raw_rows = payload.get("fields"), payload.get("data")
    if not isinstance(fields, list) or not isinstance(raw_rows, list):
        raise ValueError("schema drift: ex-dividend fields/data missing")
    required = {"資料日期", "股票代號", "權/息", "除權息參考價"}
    if not required.issubset({str(field) for field in fields}):
        raise ValueError("schema drift: ex-dividend required fields missing")
    accepted: list[NormalizedP0Observation] = []
    quarantine: list[QuarantineRecord] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, list):
            continue
        row = dict(zip((str(field) for field in fields), raw_row))
        try:
            symbol = str(row["股票代號"]).strip()
            if not symbol:
                raise ValueError("missing symbol")
            event_date = _parse_roc_date(row["資料日期"])
            accepted.append(
                NormalizedP0Observation.build(
                    source_id=envelope.source_id,
                    source_version=envelope.source_version,
                    symbol=symbol,
                    observation_date=event_date,
                    period="event",
                    publication_at=None,
                    first_observed_at=envelope.fetched_at,
                    raw_payload_sha256=_raw_row_hash(row),
                    quantities={"event_count": 1},
                    metadata={
                        "event_type": "ex_dividend_or_ex_right",
                        "event_date": event_date,
                        "right_or_dividend": str(row["權/息"]).strip(),
                        "reference_price": str(row["除權息參考價"]).strip(),
                    },
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            quarantine.append(_quarantine(envelope, row, reason_code="malformed_ex_dividend_row", detail=str(exc)))
    return OfficialParserResult(accepted=tuple(accepted), quarantine=tuple(quarantine), raw_row_count=len(raw_rows))


def parse_twse_reduction(envelope: RawFetchEnvelope) -> OfficialParserResult:
    """Parse the official reduction-resumption table without inventing announcement time."""
    payload = _json_payload(envelope)
    fields, raw_rows = payload.get("fields"), payload.get("data")
    if not isinstance(fields, list) or not isinstance(raw_rows, list):
        raise ValueError("schema drift: reduction fields/data missing")
    required = {"恢復買賣日期", "股票代號", "恢復買賣參考價", "減資原因"}
    if not required.issubset({str(field) for field in fields}):
        raise ValueError("schema drift: reduction required fields missing")
    accepted: list[NormalizedP0Observation] = []
    quarantine: list[QuarantineRecord] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, list):
            continue
        row = dict(zip((str(field) for field in fields), raw_row))
        try:
            symbol = str(row["股票代號"]).strip()
            if not symbol:
                raise ValueError("missing symbol")
            resume_date = _parse_roc_date(row["恢復買賣日期"])
            accepted.append(
                NormalizedP0Observation.build(
                    source_id=envelope.source_id,
                    source_version=envelope.source_version,
                    symbol=symbol,
                    observation_date=resume_date,
                    period="event",
                    publication_at=None,
                    first_observed_at=envelope.fetched_at,
                    raw_payload_sha256=_raw_row_hash(row),
                    quantities={"event_count": 1},
                    metadata={
                        "event_type": "reduction_split_or_par_value",
                        "resume_date": resume_date,
                        "reduction_reason": str(row["減資原因"]).strip(),
                        "resume_reference_price": str(row["恢復買賣參考價"]).strip(),
                    },
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            quarantine.append(_quarantine(envelope, row, reason_code="malformed_reduction_row", detail=str(exc)))
    return OfficialParserResult(accepted=tuple(accepted), quarantine=tuple(quarantine), raw_row_count=len(raw_rows))


def parse_twse_limit_lock(envelope: RawFetchEnvelope) -> OfficialParserResult:
    """Parse TWSE limit-lock observations from the official TWT84U report.

    The live TWSE ``MI_INDEX`` response does not expose the synthetic
    ``漲跌停標示`` column used by the original engineering fixture.  The
    official ``TWT84U`` report does expose the daily upper/lower limit,
    closing price, and final bid/ask quotes.  A lock is therefore recorded
    only when the close equals the applicable limit *and* the opposite quote
    is absent.  Merely closing at the limit is not promoted to a lock.

    The legacy marker schema remains readable so previously captured
    candidate fixtures stay reproducible.
    """
    payload = _json_payload(envelope)
    fields, raw_rows = payload.get("fields"), payload.get("data")
    if not isinstance(fields, list) or not isinstance(raw_rows, list):
        raise ValueError("schema drift: limit_lock fields/data missing")
    field_names = {str(field) for field in fields}
    legacy_required = {"證券代號", "收盤價", "漲跌停標示"}
    twt84u_required = {
        "證券代號",
        "漲停價",
        "跌停價",
        "收盤價",
        "買進揭示價",
        "賣出揭示價",
    }
    if not legacy_required.issubset(field_names) and not twt84u_required.issubset(
        field_names
    ):
        raise ValueError("schema drift: limit_lock required fields missing")
    uses_twt84u = twt84u_required.issubset(field_names)
    observation_date = _parse_yyyymmdd(payload.get("date")) if payload.get("date") else _request_date(envelope)
    publication_at = _parse_timestamp(payload.get("publicationTime"))
    accepted: list[NormalizedP0Observation] = []
    quarantine: list[QuarantineRecord] = []
    blocked_row_count = 0
    for raw_row in raw_rows:
        if not isinstance(raw_row, list):
            continue
        row = dict(zip((str(field) for field in fields), raw_row))
        try:
            symbol = str(row["證券代號"]).strip()
            if not symbol:
                raise ValueError("missing symbol")
            if uses_twt84u:
                close_price = _optional_price(row["收盤價"])
                limit_up_price = _optional_price(row["漲停價"])
                limit_down_price = _optional_price(row["跌停價"])
                if (
                    close_price is None
                    or limit_up_price is None
                    or limit_down_price is None
                ):
                    blocked_row_count += 1
                    continue
                best_bid = str(row["買進揭示價"]).replace(",", "").strip()
                best_ask = str(row["賣出揭示價"]).replace(",", "").strip()
                no_quote = {"", "--", "-", "0", "0.0", "0.00"}
                if close_price == limit_up_price and best_ask in no_quote:
                    marker = "漲停鎖死"
                elif close_price == limit_down_price and best_bid in no_quote:
                    marker = "跌停鎖死"
                else:
                    blocked_row_count += 1
                    continue
            else:
                marker = str(row["漲跌停標示"]).strip()
            if marker not in {"漲停鎖死", "跌停鎖死"}:
                # 一般上漲／下跌不是鎖死事件；保留 row conservation。
                blocked_row_count += 1
                continue
            quantity_name = "limit_up_locked" if marker == "漲停鎖死" else "limit_down_locked"
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
                    quantities={quantity_name: 1},
                    metadata={
                        "event_type": "microstructure_limit_lock",
                        "limit_lock_marker": marker,
                        "close_price": str(row["收盤價"]).strip(),
                        "limit_price_source": (
                            "twse.TWT84U" if uses_twt84u else "legacy_explicit_marker"
                        ),
                    },
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            quarantine.append(_quarantine(envelope, row, reason_code="malformed_limit_lock_row", detail=str(exc)))
    return OfficialParserResult(
        accepted=tuple(accepted),
        quarantine=tuple(quarantine),
        raw_row_count=len(raw_rows),
        blocked_row_count=blocked_row_count,
    )


def _optional_price(value: object) -> Decimal | None:
    text = str(value).replace(",", "").strip()
    if text in {"", "--", "-"}:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("malformed price") from exc
    if not parsed.is_finite() or parsed <= 0:
        return None
    return parsed


def parse_mops_quarterly_financials(envelope: RawFetchEnvelope) -> OfficialParserResult:
    """Parse MOPS quarterly financials candidate observations."""
    payload = _json_payload(envelope)
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else ([payload] if "stock_code" in payload else [])
    if not isinstance(rows, list):
        raise ValueError("schema drift: quarterly financials rows missing")
    accepted: list[NormalizedP0Observation] = []
    quarantine: list[QuarantineRecord] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            symbol = str(row.get("stock_code") or row.get("證券代號") or "").strip()
            if not symbol:
                raise ValueError("missing symbol")
            period = str(row.get("period") or "").strip()
            period_end = str(row.get("period_end") or "").strip()
            announcement_raw = row.get("announcement_date")
            publication_at = _parse_timestamp(announcement_raw) if announcement_raw else None
            accepted.append(
                NormalizedP0Observation.build(
                    source_id=envelope.source_id,
                    source_version=envelope.source_version,
                    symbol=symbol,
                    observation_date=period_end or envelope.fetched_at.date().isoformat(),
                    period="quarterly",
                    publication_at=publication_at,
                    first_observed_at=envelope.fetched_at,
                    raw_payload_sha256=str(row.get("source_hash") or _raw_row_hash(row)),
                    quantities={"financial_report_count": 1},
                    metadata={
                        "period": period,
                        "statement_scope": str(row.get("statement_scope", "consolidated")),
                        "revision": int(row.get("revision", 1)),
                    },
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            quarantine.append(_quarantine(envelope, row, reason_code="malformed_quarterly_financials_row", detail=str(exc)))
    return OfficialParserResult(accepted=tuple(accepted), quarantine=tuple(quarantine), raw_row_count=len(rows))
