"""官方三大法人與信用交易候選資料的可重跑 capture／匯入服務。

本模組和既有 Phase 3C shadow adapter 分離，負責保存每次官方 HTTP
response 的原始 bytes、解析後的候選列與可重建的 manifest。預設只寫入
repo 的 ignored output；正式 SQLite 只有在呼叫者明確提供 manifest、DB 路徑
與確認 token 後才會以交易寫入，且遇到既有內容衝突時 fail-closed。

資料來源仍是 candidate-only。這個模組不授予 source acceptance、PIT credit、
ScoringEngine、Advice 或 scheduler 權限，也不會自行開啟正式資料庫。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode

import requests


PARSER_VERSION = "institutional-credit-flows.v1"
APPLY_CONFIRM_TOKEN = "apply-institutional-credit-flows"
DEFAULT_OUTPUT_ROOT = Path("output/data_completion_20260909/flows")
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_LOOKBACK_DAYS = 45

INSTITUTIONAL_TABLE = "institutional_flows"
CREDIT_TABLE = "credit_transactions"

INSTITUTIONAL_COLUMNS = (
    "stock_code",
    "decision_date",
    "available_date",
    "observed_at",
    "source_version",
    "quality",
    "foreign_investor_buy",
    "foreign_investor_sell",
    "foreign_investor_net",
    "investment_trust_buy",
    "investment_trust_sell",
    "investment_trust_net",
    "dealer_buy",
    "dealer_sell",
    "dealer_net",
)
CREDIT_COLUMNS = (
    "stock_code",
    "decision_date",
    "available_date",
    "observed_at",
    "source_version",
    "quality",
    "margin_purchase",
    "margin_balance",
    "short_sale",
    "short_balance",
    "financing",
    "securities_lending",
)

_USER_AGENT = "technical-analysis-p0-flow-capture/1.0"
_SAFE_HEADERS = ("content-type", "date", "etag", "last-modified")


class FlowCaptureError(RuntimeError):
    """官方來源無法取得、解析或保存時的 fail-closed 錯誤。"""


class FlowApplyError(RuntimeError):
    """候選 manifest 不可安全套用至明確 DB 時的錯誤。"""


@dataclass(frozen=True)
class HttpResponse:
    """只保留 bounded response 所需的 transport evidence。"""

    status_code: int
    headers: Mapping[str, str]
    payload: bytes
    url: str
    attempts: int


Transport = Callable[[str, Mapping[str, str], int], HttpResponse]


@dataclass(frozen=True)
class EndpointSpec:
    source_id: str
    market: str
    endpoint_id: str
    source_version: str
    url: str
    params: Mapping[str, str]
    parser_kind: str
    quantity_unit: str


@dataclass(frozen=True)
class ParsedSource:
    rows: tuple[dict[str, Any], ...]
    quarantine: tuple[dict[str, Any], ...]
    observation_date: str
    publication_at: str | None
    availability_evidence: str
    quantity_unit: str


@dataclass
class CaptureStats:
    source_id: str
    market: str
    endpoint_id: str
    requested_date: str
    status: str
    http_status: int | None
    raw_path: str | None
    metadata_path: str | None
    payload_sha256: str | None
    payload_size_bytes: int = 0
    raw_row_count: int = 0
    accepted_row_count: int = 0
    quarantine_row_count: int = 0
    error: str | None = None


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_date(value: object) -> str:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            continue
    # TPEx compact ROC date (例如 1150908 / 115/09/08)。
    compact = text.replace("/", "").replace("-", "")
    if len(compact) == 7 and compact.isdigit():
        return date(
            int(compact[:3]) + 1911,
            int(compact[3:5]),
            int(compact[5:]),
        ).isoformat()
    raise FlowCaptureError(f"無法解析官方資料日期: {value!r}")


def _roc_date(value: date) -> str:
    return f"{value.year - 1911:03d}/{value.month:02d}/{value.day:02d}"


def _as_int(value: object, *, field_name: str) -> int:
    if value is None:
        raise FlowCaptureError(f"{field_name} 缺少整數值")
    text = str(value).replace(",", "").strip()
    if not text or text in {"-", "--", "—", "N/A"}:
        raise FlowCaptureError(f"{field_name} 缺少整數值")
    try:
        parsed = int(text)
    except ValueError as exc:
        raise FlowCaptureError(f"{field_name} 不是整數: {value!r}") from exc
    return parsed


def _parse_publication_at(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("publicationTime")
    if value is None or not str(value).strip():
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise FlowCaptureError(f"官方 publicationTime 格式無效: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FlowCaptureError("官方 publicationTime 缺少 timezone")
    return parsed.isoformat()


def _observation_evidence(
    *, publication_at: str | None, completed_at: datetime
) -> tuple[str, str | None, str]:
    """回傳 (available_at, available_date, evidence_kind)。"""

    if publication_at is not None:
        parsed = datetime.fromisoformat(publication_at)
        return publication_at, parsed.date().isoformat(), "official_publication_timestamp"
    # 不把交易日或 period end 冒充 publication；只保存實際完成抓取時間。
    observed = completed_at.isoformat()
    return observed, None, "first_observed_only"


def _normalise_keyed_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key).strip().lstrip("\ufeff"): value for key, value in row.items()}


def _twse_rows(payload: Mapping[str, Any], *, table: bool) -> list[dict[str, Any]]:
    if table:
        tables = payload.get("tables")
        if not isinstance(tables, list):
            raise FlowCaptureError("TWSE payload 缺少 tables")
        for item in tables:
            if not isinstance(item, Mapping):
                continue
            fields = item.get("fields")
            data = item.get("data")
            if not isinstance(fields, list) or not isinstance(data, list):
                continue
            if "代號" in fields and "名稱" in fields:
                return [
                    _normalise_keyed_row(dict(zip(fields, values)))
                    for values in data
                    if isinstance(values, list)
                ]
        raise FlowCaptureError("TWSE payload 缺少明細 table")
    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        raise FlowCaptureError("TWSE payload 缺少 fields/data")
    return [
        _normalise_keyed_row(dict(zip(fields, values)))
        for values in data
        if isinstance(values, list)
    ]


def _require_date(payload: Mapping[str, Any], requested_date: str) -> str:
    raw_date = payload.get("date")
    if raw_date is None:
        tables = payload.get("tables")
        if isinstance(tables, list):
            for item in tables:
                if isinstance(item, Mapping) and item.get("date"):
                    raw_date = item.get("date")
                    break
    if raw_date is None:
        raise FlowCaptureError("官方 payload 缺少資料日期")
    actual = _parse_iso_date(raw_date)
    if actual != requested_date:
        raise FlowCaptureError(
            f"官方回應日期不符: expected={requested_date}, actual={actual}"
        )
    return actual


def _payload_object(payload: bytes) -> Mapping[str, Any]:
    try:
        decoded = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FlowCaptureError("官方 response 不是可解析 JSON") from exc
    if not isinstance(decoded, Mapping):
        raise FlowCaptureError("官方 JSON root 不是 object")
    return decoded


def _payload_list(payload: bytes) -> list[Mapping[str, Any]]:
    try:
        decoded = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FlowCaptureError("TPEx OpenAPI response 不是可解析 JSON") from exc
    if not isinstance(decoded, list):
        raise FlowCaptureError("TPEx OpenAPI JSON root 不是 list")
    rows: list[Mapping[str, Any]] = []
    for item in decoded:
        if isinstance(item, Mapping):
            rows.append(_normalise_keyed_row(item))
    if not rows:
        raise FlowCaptureError("TPEx OpenAPI 沒有資料列")
    return rows


def _base_row(
    *,
    symbol: object,
    requested_date: str,
    source_version: str,
    completed_at: datetime,
    publication_at: str | None,
    endpoint_id: str,
    market: str,
    payload_sha256: str,
    quantity_unit: str,
) -> dict[str, Any]:
    stock_code = str(symbol or "").strip()
    if not stock_code:
        raise FlowCaptureError("官方資料列缺少證券代號")
    available_at, available_date, evidence = _observation_evidence(
        publication_at=publication_at, completed_at=completed_at
    )
    return {
        "stock_code": stock_code,
        "decision_date": requested_date,
        "available_date": available_date,
        "observed_at": completed_at.isoformat(),
        "source_version": source_version,
        "quality": "verified" if publication_at else "degraded",
        "available_at": available_at,
        "availability_evidence": evidence,
        "provenance": {
            "endpoint_id": endpoint_id,
            "market": market,
            "payload_sha256": payload_sha256,
            "quantity_unit": quantity_unit,
        },
    }


def _validate_flow_quantities(
    row: object, *, prefix: str, buy: int, sell: int, net: int
) -> None:
    if buy - sell != net:
        raise FlowCaptureError(
            f"{prefix} 買賣超不守恆: buy={buy}, sell={sell}, net={net}"
        )


def _parse_twse_institutional(
    payload: bytes,
    *,
    requested_date: str,
    completed_at: datetime,
    spec: EndpointSpec,
    payload_sha256: str,
) -> ParsedSource:
    decoded = _payload_object(payload)
    if str(decoded.get("stat", "")).strip().upper() not in {"OK", "SUCCESS"}:
        raise FlowCaptureError(f"TWSE T86 官方狀態: {decoded.get('stat')!r}")
    observation_date = _require_date(decoded, requested_date)
    publication_at = _parse_publication_at(decoded)
    parsed_rows: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for index, raw in enumerate(_twse_rows(decoded, table=False)):
        try:
            foreign_buy = _as_int(
                raw.get("外陸資買進股數(不含外資自營商)"),
                field_name="外陸資買進股數",
            ) + _as_int(raw.get("外資自營商買進股數"), field_name="外資自營商買進股數")
            foreign_sell = _as_int(
                raw.get("外陸資賣出股數(不含外資自營商)"),
                field_name="外陸資賣出股數",
            ) + _as_int(raw.get("外資自營商賣出股數"), field_name="外資自營商賣出股數")
            foreign_net = _as_int(
                raw.get("外陸資買賣超股數(不含外資自營商)"),
                field_name="外陸資買賣超股數",
            ) + _as_int(raw.get("外資自營商買賣超股數"), field_name="外資自營商買賣超股數")
            trust_buy = _as_int(raw.get("投信買進股數"), field_name="投信買進股數")
            trust_sell = _as_int(raw.get("投信賣出股數"), field_name="投信賣出股數")
            trust_net = _as_int(raw.get("投信買賣超股數"), field_name="投信買賣超股數")
            dealer_buy = _as_int(raw.get("自營商買進股數(自行買賣)"), field_name="自營商買進股數") + _as_int(raw.get("自營商買進股數(避險)"), field_name="自營商避險買進股數")
            dealer_sell = _as_int(raw.get("自營商賣出股數(自行買賣)"), field_name="自營商賣出股數") + _as_int(raw.get("自營商賣出股數(避險)"), field_name="自營商避險賣出股數")
            dealer_net = _as_int(raw.get("自營商買賣超股數(自行買賣)"), field_name="自營商買賣超股數") + _as_int(raw.get("自營商買賣超股數(避險)"), field_name="自營商避險買賣超股數")
            _validate_flow_quantities(raw, prefix="foreign", buy=foreign_buy, sell=foreign_sell, net=foreign_net)
            _validate_flow_quantities(raw, prefix="trust", buy=trust_buy, sell=trust_sell, net=trust_net)
            _validate_flow_quantities(raw, prefix="dealer", buy=dealer_buy, sell=dealer_sell, net=dealer_net)
            item = _base_row(
                symbol=raw.get("證券代號"), requested_date=requested_date,
                source_version=spec.source_version, completed_at=completed_at,
                publication_at=publication_at, endpoint_id=spec.endpoint_id,
                market=spec.market, payload_sha256=payload_sha256,
                quantity_unit=spec.quantity_unit,
            )
            item.update({
                "foreign_investor_buy": foreign_buy,
                "foreign_investor_sell": foreign_sell,
                "foreign_investor_net": foreign_net,
                "investment_trust_buy": trust_buy,
                "investment_trust_sell": trust_sell,
                "investment_trust_net": trust_net,
                "dealer_buy": dealer_buy,
                "dealer_sell": dealer_sell,
                "dealer_net": dealer_net,
            })
            parsed_rows.append(item)
        except (FlowCaptureError, TypeError, ValueError) as exc:
            quarantine.append({"row_index": index, "reason": str(exc), "raw_row": raw})
    if not parsed_rows:
        raise FlowCaptureError("TWSE T86 沒有可接受資料列")
    return ParsedSource(tuple(parsed_rows), tuple(quarantine), observation_date, publication_at, "official_publication_timestamp" if publication_at else "first_observed_only", spec.quantity_unit)


def _parse_tpex_institutional_rows(
    rows: Sequence[Sequence[Any]],
    *,
    requested_date: str,
    completed_at: datetime,
    spec: EndpointSpec,
    payload_sha256: str,
    publication_at: str | None,
) -> ParsedSource:
    parsed_rows: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        try:
            if len(raw) < 23:
                raise FlowCaptureError("TPEx 三大法人列少於 23 欄")
            foreign_buy = _as_int(raw[8], field_name="TPEx 外資買進")
            foreign_sell = _as_int(raw[9], field_name="TPEx 外資賣出")
            foreign_net = _as_int(raw[10], field_name="TPEx 外資買賣超")
            trust_buy = _as_int(raw[11], field_name="TPEx 投信買進")
            trust_sell = _as_int(raw[12], field_name="TPEx 投信賣出")
            trust_net = _as_int(raw[13], field_name="TPEx 投信買賣超")
            dealer_buy = _as_int(raw[20], field_name="TPEx 自營商買進")
            dealer_sell = _as_int(raw[21], field_name="TPEx 自營商賣出")
            dealer_net = _as_int(raw[22], field_name="TPEx 自營商買賣超")
            _validate_flow_quantities(raw, prefix="foreign", buy=foreign_buy, sell=foreign_sell, net=foreign_net)
            _validate_flow_quantities(raw, prefix="trust", buy=trust_buy, sell=trust_sell, net=trust_net)
            _validate_flow_quantities(raw, prefix="dealer", buy=dealer_buy, sell=dealer_sell, net=dealer_net)
            item = _base_row(
                symbol=raw[0], requested_date=requested_date,
                source_version=spec.source_version, completed_at=completed_at,
                publication_at=publication_at, endpoint_id=spec.endpoint_id,
                market=spec.market, payload_sha256=payload_sha256,
                quantity_unit=spec.quantity_unit,
            )
            item.update({
                "foreign_investor_buy": foreign_buy,
                "foreign_investor_sell": foreign_sell,
                "foreign_investor_net": foreign_net,
                "investment_trust_buy": trust_buy,
                "investment_trust_sell": trust_sell,
                "investment_trust_net": trust_net,
                "dealer_buy": dealer_buy,
                "dealer_sell": dealer_sell,
                "dealer_net": dealer_net,
            })
            parsed_rows.append(item)
        except (FlowCaptureError, TypeError, ValueError) as exc:
            quarantine.append({"row_index": index, "reason": str(exc), "raw_row": list(raw)})
    if not parsed_rows:
        raise FlowCaptureError("TPEx 三大法人沒有可接受資料列")
    return ParsedSource(tuple(parsed_rows), tuple(quarantine), requested_date, publication_at, "first_observed_only", spec.quantity_unit)


def _parse_tpex_institutional(
    payload: bytes,
    *,
    requested_date: str,
    completed_at: datetime,
    spec: EndpointSpec,
    payload_sha256: str,
) -> ParsedSource:
    decoded = _payload_object(payload)
    # 舊 web route：tables[].data；OpenAPI fallback：list-of-object。
    tables = decoded.get("tables")
    if isinstance(tables, list):
        table = next((x for x in tables if isinstance(x, Mapping) and isinstance(x.get("data"), list)), None)
        if table is None:
            raise FlowCaptureError("TPEx 三大法人缺少明細 table")
        actual = _require_date(decoded, requested_date)
        raw_rows = [x for x in table["data"] if isinstance(x, list)]
        return _parse_tpex_institutional_rows(
            raw_rows, requested_date=actual, completed_at=completed_at,
            spec=spec, payload_sha256=payload_sha256, publication_at=None,
        )
    rows = _payload_list(payload)
    dates = {_parse_iso_date(row.get("Date")) for row in rows}
    if dates != {requested_date}:
        raise FlowCaptureError(f"TPEx OpenAPI 三大法人日期不符: {sorted(dates)}")
    parsed_rows: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    def get(row: Mapping[str, Any], suffix: str) -> object:
        for key, value in row.items():
            if str(key).strip().endswith(suffix):
                return value
        raise FlowCaptureError(f"TPEx OpenAPI 缺少欄位: {suffix}")
    for index, raw in enumerate(rows):
        try:
            foreign_buy = _as_int(get(raw, "Total Buy"), field_name="TPEx 外資買進")
            foreign_sell = _as_int(get(raw, "Total Sell"), field_name="TPEx 外資賣出")
            foreign_net = _as_int(get(raw, "Difference"), field_name="TPEx 外資買賣超")
            # OpenAPI 的 current schema 未提供可驗證的投信／自營商合計；
            # 不補 0，這一路只能作部分候選，供 owner 另行判定。
            raise FlowCaptureError("TPEx OpenAPI 三大法人缺少投信／自營商欄位")
        except (FlowCaptureError, TypeError, ValueError) as exc:
            quarantine.append({"row_index": index, "reason": str(exc), "raw_row": dict(raw)})
    raise FlowCaptureError(
        f"TPEx OpenAPI 三大法人無完整三類法人資料；quarantine={len(quarantine)}"
    )


def _parse_credit_rows(
    rows: Sequence[Sequence[Any]],
    *,
    requested_date: str,
    completed_at: datetime,
    spec: EndpointSpec,
    payload_sha256: str,
) -> ParsedSource:
    parsed_rows: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        try:
            required_len = 13 if spec.market == "TWSE" else 15
            if len(raw) < required_len:
                raise FlowCaptureError(f"信用交易列少於 {required_len} 欄")
            if spec.market == "TWSE":
                margin_purchase, margin_balance = raw[2], raw[6]
                short_sale, short_balance = raw[9], raw[12]
            else:
                margin_purchase, margin_balance = raw[3], raw[6]
                short_sale, short_balance = raw[11], raw[14]
            values = {
                "margin_purchase": _as_int(margin_purchase, field_name="融資買進"),
                "margin_balance": _as_int(margin_balance, field_name="融資餘額"),
                "short_sale": _as_int(short_sale, field_name="融券賣出"),
                "short_balance": _as_int(short_balance, field_name="融券餘額"),
            }
            if any(value < 0 for value in values.values()):
                raise FlowCaptureError("信用交易數量不可為負")
            item = _base_row(
                symbol=raw[0], requested_date=requested_date,
                source_version=spec.source_version, completed_at=completed_at,
                publication_at=None, endpoint_id=spec.endpoint_id,
                market=spec.market, payload_sha256=payload_sha256,
                quantity_unit=spec.quantity_unit,
            )
            item.update({**values, "financing": None, "securities_lending": None})
            parsed_rows.append(item)
        except (FlowCaptureError, TypeError, ValueError) as exc:
            quarantine.append({"row_index": index, "reason": str(exc), "raw_row": list(raw)})
    if not parsed_rows:
        raise FlowCaptureError("信用交易沒有可接受資料列")
    return ParsedSource(tuple(parsed_rows), tuple(quarantine), requested_date, None, "first_observed_only", spec.quantity_unit)


def _parse_twse_credit(
    payload: bytes,
    *,
    requested_date: str,
    completed_at: datetime,
    spec: EndpointSpec,
    payload_sha256: str,
) -> ParsedSource:
    decoded = _payload_object(payload)
    if str(decoded.get("stat", "")).strip().upper() not in {"OK", "SUCCESS"}:
        raise FlowCaptureError(f"TWSE MI_MARGN 官方狀態: {decoded.get('stat')!r}")
    actual = _require_date(decoded, requested_date)
    tables = decoded.get("tables")
    if not isinstance(tables, list):
        raise FlowCaptureError("TWSE MI_MARGN 缺少 tables")
    table = next(
        (
            x for x in tables
            if isinstance(x, Mapping)
            and isinstance(x.get("fields"), list)
            and "代號" in x["fields"]
            and "名稱" in x["fields"]
        ),
        None,
    )
    if table is None:
        raise FlowCaptureError("TWSE MI_MARGN 缺少個股明細 table")
    rows = [x for x in table["data"] if isinstance(x, list)]
    return _parse_credit_rows(
        rows, requested_date=actual, completed_at=completed_at,
        spec=spec, payload_sha256=payload_sha256,
    )


def _parse_tpex_credit(
    payload: bytes,
    *,
    requested_date: str,
    completed_at: datetime,
    spec: EndpointSpec,
    payload_sha256: str,
) -> ParsedSource:
    decoded = _payload_object(payload)
    tables = decoded.get("tables")
    if isinstance(tables, list):
        table = next(
            (
                x for x in tables
                if isinstance(x, Mapping)
                and isinstance(x.get("fields"), list)
                and "資買" in x["fields"]
                and "資餘額" in x["fields"]
            ),
            None,
        )
        if table is None:
            raise FlowCaptureError("TPEx 信用交易缺少個股明細 table")
        actual = _require_date(decoded, requested_date)
        table_rows: list[list[Any]] = [x for x in table["data"] if isinstance(x, list)]
        return _parse_credit_rows(
            table_rows, requested_date=actual, completed_at=completed_at,
            spec=spec, payload_sha256=payload_sha256,
        )
    openapi_rows = _payload_list(payload)
    dates = {_parse_iso_date(row.get("Date")) for row in openapi_rows}
    if dates != {requested_date}:
        raise FlowCaptureError(f"TPEx OpenAPI 信用交易日期不符: {sorted(dates)}")
    converted: list[list[Any]] = []
    for row in openapi_rows:
        converted.append([
            row.get("SecuritiesCompanyCode"),
            row.get("CompanyName"),
            row.get("MarginPurchaseBalancePreviousDay"),
            row.get("MarginPurchase"),
            row.get("MarginSales"),
            row.get("CashRedemption"),
            row.get("MarginPurchaseBalance"),
            row.get("MarginPurchaseBalanceBelongSecuritiesFinanceEnterprise"),
            row.get("MarginPurchaseUtilizationRate"),
            row.get("MarginPurchaseQuota"),
            row.get("ShortSaleBalancePreviousDay"),
            row.get("ShortSale"),
            row.get("ShortConvering"),
            row.get("StockRedemption"),
            row.get("ShortSaleBalance"),
        ])
    return _parse_credit_rows(
        converted, requested_date=requested_date, completed_at=completed_at,
        spec=spec, payload_sha256=payload_sha256,
    )


def _default_transport(url: str, params: Mapping[str, str], timeout_seconds: int) -> HttpResponse:
    """有界官方 GET；不把 secret header 或 response body 寫入 log。"""

    response = requests.get(
        url,
        params=dict(params),
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json,text/plain,*/*"},
        timeout=timeout_seconds,
    )
    payload = bytes(response.content)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise FlowCaptureError(
            f"官方 response 超過 bounded cap: {len(payload)} > {MAX_RESPONSE_BYTES}"
        )
    safe_headers = {
        key.lower(): str(response.headers[key])
        for key in _SAFE_HEADERS
        if key in response.headers
    }
    return HttpResponse(
        status_code=int(response.status_code),
        headers=safe_headers,
        payload=payload,
        url=str(response.url),
        attempts=1,
    )


def _request_with_retries(
    transport: Transport,
    *,
    spec: EndpointSpec,
    timeout_seconds: int = 30,
    max_attempts: int = 2,
    retry_sleep_seconds: float = 0.4,
) -> tuple[HttpResponse, list[dict[str, Any]]]:
    if max_attempts <= 0 or timeout_seconds <= 0:
        raise ValueError("max_attempts／timeout_seconds 必須為正數")
    attempts: list[dict[str, Any]] = []
    query = urlencode(dict(spec.params))
    request_url = f"{spec.url}?{query}" if query else spec.url
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        started = _utc_now()
        try:
            response = transport(spec.url, spec.params, timeout_seconds)
            attempts.append({
                "attempt": attempt,
                "started_at": started.isoformat(),
                "completed_at": _utc_now().isoformat(),
                "status_code": response.status_code,
                "payload_size_bytes": len(response.payload),
            })
            if response.status_code == 200:
                if len(response.payload) > MAX_RESPONSE_BYTES:
                    raise FlowCaptureError("response exceeds bounded cap")
                return response, attempts
            last_error = FlowCaptureError(f"HTTP status {response.status_code}")
        except Exception as exc:
            last_error = exc
            attempts.append({
                "attempt": attempt,
                "started_at": started.isoformat(),
                "completed_at": _utc_now().isoformat(),
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
        if attempt < max_attempts:
            time.sleep(max(0.0, retry_sleep_seconds))
    raise FlowCaptureError(f"官方 GET 失敗 {request_url}: {last_error}")


def _endpoint_specs(target_date: date) -> tuple[EndpointSpec, ...]:
    date_ce = target_date.strftime("%Y%m%d")
    date_roc = _roc_date(target_date)
    return (
        EndpointSpec(
            "institutional_flows", "TWSE", "twse:T86", "twse-T86.v1",
            "https://www.twse.com.tw/fund/T86",
            {"response": "json", "date": date_ce, "selectType": "ALL"},
            "twse_institutional", "shares",
        ),
        EndpointSpec(
            "institutional_flows", "TPEx", "tpex:3itrade", "tpex-3insti-web.v1",
            "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php",
            {"l": "zh-tw", "o": "json", "d": date_roc, "se": "AL"},
            "tpex_institutional", "shares",
        ),
        EndpointSpec(
            "credit_transactions", "TWSE", "twse:MI_MARGN", "twse-MI_MARGN.v1",
            "https://www.twse.com.tw/exchangeReport/MI_MARGN",
            {"response": "json", "date": date_ce, "selectType": "ALL"},
            "twse_credit", "trading_units",
        ),
        EndpointSpec(
            "credit_transactions", "TPEx", "tpex:margin_bal", "tpex-margin-web.v1",
            "https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php",
            {"l": "zh-tw", "o": "json", "d": date_roc},
            "tpex_credit", "lots",
        ),
    )


def _parse_endpoint(
    spec: EndpointSpec,
    payload: bytes,
    *,
    requested_date: str,
    completed_at: datetime,
) -> ParsedSource:
    payload_sha256 = _sha256(payload)
    if spec.parser_kind == "twse_institutional":
        return _parse_twse_institutional(payload, requested_date=requested_date, completed_at=completed_at, spec=spec, payload_sha256=payload_sha256)
    if spec.parser_kind == "tpex_institutional":
        return _parse_tpex_institutional(payload, requested_date=requested_date, completed_at=completed_at, spec=spec, payload_sha256=payload_sha256)
    if spec.parser_kind == "twse_credit":
        return _parse_twse_credit(payload, requested_date=requested_date, completed_at=completed_at, spec=spec, payload_sha256=payload_sha256)
    if spec.parser_kind == "tpex_credit":
        return _parse_tpex_credit(payload, requested_date=requested_date, completed_at=completed_at, spec=spec, payload_sha256=payload_sha256)
    raise FlowCaptureError(f"未知 parser_kind: {spec.parser_kind}")


def _write_create_only(path: Path, payload: bytes) -> bool:
    """原子 create-only 寫入；相同 bytes 重跑視為冪等。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_bytes()
        if existing == payload:
            return False
        raise FlowCaptureError(f"候選 artifact 已存在但 bytes 不同: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=".tmp_", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise FlowCaptureError(f"候選 artifact race conflict: {path}")
            return False
        return True
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _write_json_create_only(path: Path, payload: Any) -> str:
    data = _json_bytes(payload)
    _write_create_only(path, data)
    return _sha256(data)


def _raw_filename(spec: EndpointSpec) -> str:
    return spec.endpoint_id.replace(":", "_").replace("/", "_") + ".json"


def _merge_rows(
    source_id: str, rows_by_endpoint: Sequence[ParsedSource]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    merged: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for result in rows_by_endpoint:
        quarantine.extend(result.quarantine)
        for row in result.rows:
            key = (str(row["stock_code"]), str(row["decision_date"]))
            if key in seen:
                raise FlowCaptureError(
                    f"{source_id} 跨市場 natural identity 衝突: {key}; 不自動合併"
                )
            seen[key] = row
            merged.append(row)
    merged.sort(key=lambda row: (str(row["decision_date"]), str(row["stock_code"])))
    return merged, quarantine


def _candidate_row(row: Mapping[str, Any], *, source_id: str) -> dict[str, Any]:
    columns = INSTITUTIONAL_COLUMNS if source_id == INSTITUTIONAL_TABLE else CREDIT_COLUMNS
    return {
        "table": source_id,
        "values": {column: row.get(column) for column in columns},
        "available_at": row.get("available_at"),
        "availability_evidence": row.get("availability_evidence"),
        "provenance": row.get("provenance"),
    }


def _code_shape_diagnostics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """標記官方明細中 ETF／權證／特別商品等非四碼代號，不擅自刪列。"""

    codes = sorted({str(row.get("values", {}).get("stock_code", "")).strip() for row in rows})
    ordinary = [code for code in codes if re.fullmatch(r"\d{4}", code)]
    other = [code for code in codes if code not in ordinary]
    return {
        "distinct_symbol_count": len(codes),
        "four_digit_code_count": len(ordinary),
        "other_code_count": len(other),
        "other_code_examples": other[:20],
        "other_codes_retained": True,
    }


def _validate_candidate_row(item: Mapping[str, Any], *, source_id: str) -> dict[str, Any]:
    if item.get("table") != source_id or not isinstance(item.get("values"), Mapping):
        raise FlowApplyError(f"candidate row table/value shape 不符: {source_id}")
    values = dict(item["values"])
    columns = INSTITUTIONAL_COLUMNS if source_id == INSTITUTIONAL_TABLE else CREDIT_COLUMNS
    missing = [column for column in columns if column not in values]
    if missing:
        raise FlowApplyError(f"candidate row 缺少欄位: {missing}")
    symbol = str(values["stock_code"] or "").strip()
    decision_date = _parse_iso_date(values["decision_date"])
    values["stock_code"] = symbol
    values["decision_date"] = decision_date
    if not symbol:
        raise FlowApplyError("candidate row stock_code 不可為空")
    if values.get("available_date") is not None:
        available_date = _parse_iso_date(values["available_date"])
        if available_date < decision_date:
            raise FlowApplyError("available_date 早於 report/decision date")
        values["available_date"] = available_date
    observed_at = values.get("observed_at")
    if not isinstance(observed_at, str) or not observed_at.strip():
        raise FlowApplyError("observed_at 必須保存實際 UTC capture 完成時間")
    try:
        observed_dt = datetime.fromisoformat(observed_at)
    except ValueError as exc:
        raise FlowApplyError("observed_at 不是 ISO timestamp") from exc
    if observed_dt.tzinfo is None or observed_dt.utcoffset() is None:
        raise FlowApplyError("observed_at 必須包含 timezone")
    values["observed_at"] = observed_dt.isoformat()
    for column in columns[6:]:
        value = values.get(column)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise FlowApplyError(f"{source_id}.{column} 必須是 integer 或 null")
    if source_id == INSTITUTIONAL_TABLE:
        for actor in ("foreign_investor", "investment_trust", "dealer"):
            buy = values.get(f"{actor}_buy")
            sell = values.get(f"{actor}_sell")
            net = values.get(f"{actor}_net")
            if not all(isinstance(value, int) for value in (buy, sell, net)):
                raise FlowApplyError(f"{source_id} 缺少 {actor} 完整數值")
            assert isinstance(buy, int)
            assert isinstance(sell, int)
            assert isinstance(net, int)
            if buy - sell != net:
                raise FlowApplyError(f"{source_id} {actor} 買賣超不守恆")
    else:
        for column in ("margin_purchase", "margin_balance", "short_sale", "short_balance"):
            if values.get(column) is None or int(values[column]) < 0:
                raise FlowApplyError(f"{source_id}.{column} 必須是非負 integer")
    return values


def _ensure_formal_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS institutional_flows (
            stock_code TEXT,
            decision_date TEXT,
            available_date TEXT,
            observed_at TEXT,
            source_version TEXT,
            quality TEXT,
            foreign_investor_buy INTEGER,
            foreign_investor_sell INTEGER,
            foreign_investor_net INTEGER,
            investment_trust_buy INTEGER,
            investment_trust_sell INTEGER,
            investment_trust_net INTEGER,
            dealer_buy INTEGER,
            dealer_sell INTEGER,
            dealer_net INTEGER,
            PRIMARY KEY (stock_code, decision_date)
        );
        CREATE TABLE IF NOT EXISTS credit_transactions (
            stock_code TEXT,
            decision_date TEXT,
            available_date TEXT,
            observed_at TEXT,
            source_version TEXT,
            quality TEXT,
            margin_purchase INTEGER,
            margin_balance INTEGER,
            short_sale INTEGER,
            short_balance INTEGER,
            financing INTEGER,
            securities_lending INTEGER,
            PRIMARY KEY (stock_code, decision_date)
        );
        """
    )
    # 舊正式／candidate schema 沒有實際 capture 完成時間；只在明確 apply
    # transaction 內補欄位，保留既有列，不猜測歷史 observed_at。
    for table in (INSTITUTIONAL_TABLE, CREDIT_TABLE):
        columns = {
            str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")
        }
        if "observed_at" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN observed_at TEXT")


def _manifest_file_hash(path: Path) -> str:
    try:
        return _sha256(path.read_bytes())
    except OSError as exc:
        raise FlowApplyError(f"manifest artifact 無法讀取: {path}") from exc


def _resolve_manifest_child(base: Path, relative_path: object, *, label: str) -> Path:
    """解析 manifest 相對路徑並拒絕 ``..``／junction 外逃。"""

    raw = str(relative_path or "").strip()
    if not raw:
        raise FlowApplyError(f"{label} path 不可為空")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise FlowApplyError(f"{label} 必須是 manifest 相對路徑")
    resolved_base = base.resolve(strict=True)
    resolved = (resolved_base / candidate).resolve(strict=False)
    if not resolved.is_relative_to(resolved_base):
        raise FlowApplyError(f"{label} path escape: {raw}")
    return resolved


def _earliest_date(existing: object, incoming: object) -> str | None:
    values = [str(value) for value in (existing, incoming) if value not in (None, "")]
    return min(values) if values else None


def _earliest_timestamp(existing: object, incoming: object) -> str | None:
    values: list[tuple[datetime, str]] = []
    for value in (existing, incoming):
        if value in (None, ""):
            continue
        text = str(value)
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise FlowApplyError(f"既有／候選 observed_at 無法解析: {text}") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise FlowApplyError("既有／候選 observed_at 必須包含 timezone")
        values.append((parsed, parsed.isoformat()))
    return min(values, key=lambda item: item[0])[1] if values else None


def apply_flow_manifest(
    manifest_path: str | Path,
    *,
    db_path: str | Path,
    confirm_token: str,
    receipt_path: str | Path | None = None,
) -> dict[str, Any]:
    """將已審核 candidate manifest 以顯式 token 匯入指定 SQLite。

    這個函式不會被 capture CLI 自動呼叫。既有不同 bytes 的 natural identity
    直接中止並 rollback，避免把 candidate-only 內容靜默覆蓋正式列。
    """

    if confirm_token != APPLY_CONFIRM_TOKEN:
        raise FlowApplyError(f"需要 confirm token: {APPLY_CONFIRM_TOKEN}")
    manifest_file = Path(manifest_path).expanduser().resolve(strict=True)
    target = Path(db_path).expanduser().resolve(strict=False)
    if target == manifest_file or target.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        raise FlowApplyError("--db-path 必須是明確 SQLite 檔案路徑")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FlowApplyError("manifest 無法讀取或不是 JSON") from exc
    if manifest.get("candidate_only") is not True:
        raise FlowApplyError("manifest candidate_only contract 不符")
    if manifest.get("formal_apply_allowed") is not False:
        raise FlowApplyError("manifest 必須保留 candidate-only 邊界")
    base = manifest_file.parent.resolve(strict=True)
    source_entries = manifest.get("sources")
    if not isinstance(source_entries, list) or not source_entries:
        raise FlowApplyError("manifest 缺少 sources")
    grouped: dict[str, list[dict[str, Any]]] = {INSTITUTIONAL_TABLE: [], CREDIT_TABLE: []}
    for entry in source_entries:
        if not isinstance(entry, Mapping):
            raise FlowApplyError("manifest source entry 不是 object")
        row_path = _resolve_manifest_child(
            base, entry.get("candidate_rows_path"), label="candidate rows"
        )
        expected_hash = str(entry.get("candidate_rows_sha256", ""))
        if not row_path.is_file() or _manifest_file_hash(row_path) != expected_hash:
            raise FlowApplyError(f"candidate rows hash/path 不符: {row_path}")
        source_id = str(entry.get("source_id", ""))
        if source_id not in grouped:
            raise FlowApplyError(f"不支援的 source_id: {source_id}")
        try:
            rows_payload = json.loads(row_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FlowApplyError(f"candidate rows 不是 JSON: {row_path}") from exc
        if not isinstance(rows_payload, list):
            raise FlowApplyError(f"candidate rows 必須是 list: {row_path}")
        grouped[source_id].extend(rows_payload)
        raw_entries = entry.get("raw_artifacts")
        if not isinstance(raw_entries, list) or not raw_entries:
            raise FlowApplyError(f"{source_id} 缺少 raw_artifacts")
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, Mapping):
                raise FlowApplyError("raw artifact entry 不是 object")
            raw_path = _resolve_manifest_child(
                base, raw_entry.get("path"), label="raw artifact"
            )
            if not raw_path.is_file() or _manifest_file_hash(raw_path) != str(raw_entry.get("sha256", "")):
                raise FlowApplyError(f"raw artifact hash/path 不符: {raw_path}")
            metadata_path = _resolve_manifest_child(
                base, raw_entry.get("metadata_path"), label="raw metadata"
            )
            if not metadata_path.is_file():
                raise FlowApplyError(f"raw metadata 缺失: {metadata_path}")
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise FlowApplyError(f"raw metadata 無法解析: {metadata_path}") from exc
            if not isinstance(metadata, Mapping) or str(metadata.get("payload_sha256")) != str(raw_entry.get("sha256")):
                raise FlowApplyError(f"raw metadata hash 不符: {metadata_path}")
    run_seen: set[tuple[str, str, str]] = set()
    normalized_rows: dict[str, list[dict[str, Any]]] = {}
    for source_id, items in grouped.items():
        normalized_rows[source_id] = []
        for item in items:
            values = _validate_candidate_row(item, source_id=source_id)
            identity = (source_id, str(values["stock_code"]), str(values["decision_date"]))
            if identity in run_seen:
                raise FlowApplyError(f"candidate manifest duplicate identity: {source_id}:{identity}")
            run_seen.add(identity)
            normalized_rows[source_id].append(values)

    target.parent.mkdir(parents=True, exist_ok=True)
    inserted = 0
    duplicates = 0
    try:
        with sqlite3.connect(target) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            _ensure_formal_tables(conn)
            for source_id, rows in normalized_rows.items():
                columns = INSTITUTIONAL_COLUMNS if source_id == INSTITUTIONAL_TABLE else CREDIT_COLUMNS
                placeholders = ",".join("?" for _ in columns)
                select_sql = f"SELECT {','.join(columns)} FROM {source_id} WHERE stock_code=? AND decision_date=?"
                insert_sql = f"INSERT INTO {source_id} ({','.join(columns)}) VALUES ({placeholders})"
                for values in rows:
                    params = tuple(values[column] for column in columns)
                    existing = conn.execute(select_sql, (values["stock_code"], values["decision_date"])).fetchone()
                    if existing is None:
                        conn.execute(insert_sql, params)
                        inserted += 1
                    else:
                        # 重抓時 observed_at 會自然不同；只要同一 source
                        # version 的實值相同，視為冪等 duplicate，並保留較早
                        # 的觀測／官方可得日期。實值改變或 source version 改變
                        # 仍然拒絕，避免靜默覆寫來源 revision。
                        excluded = {"available_date", "observed_at", "quality"}
                        existing_by_column = dict(zip(columns, tuple(existing)))
                        if any(
                            existing_by_column[column] != values[column]
                            for column in columns
                            if column not in excluded
                        ):
                            raise FlowApplyError(f"正式表既有列內容衝突: {source_id}:{values['stock_code']}:{values['decision_date']}")
                        merged_available = _earliest_date(
                            existing_by_column.get("available_date"), values.get("available_date")
                        )
                        merged_observed = _earliest_timestamp(
                            existing_by_column.get("observed_at"), values.get("observed_at")
                        )
                        if (
                            merged_available != existing_by_column.get("available_date")
                            or merged_observed != existing_by_column.get("observed_at")
                        ):
                            conn.execute(
                                f"UPDATE {source_id} SET available_date=?, observed_at=? WHERE stock_code=? AND decision_date=?",
                                (
                                    merged_available,
                                    merged_observed,
                                    values["stock_code"],
                                    values["decision_date"],
                                ),
                            )
                        duplicates += 1
            conn.commit()
    except Exception:
        # sqlite context manager rollback；明確再開 read-only 不需要。
        raise

    receipt = {
        "schema_version": "institutional-credit-flows-apply-receipt.v1",
        "manifest_path": str(manifest_file),
        "manifest_sha256": _manifest_file_hash(manifest_file),
        "db_path": str(target),
        "inserted": inserted,
        "duplicates": duplicates,
        "candidate_only_before_explicit_apply": True,
        "formal_credit_granted": False,
        "applied_at": _utc_now().isoformat(),
    }
    if receipt_path is not None:
        _write_json_create_only(Path(receipt_path).expanduser(), receipt)
    return receipt


def capture_recent_flows(
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    as_of_date: date,
    sessions: int = 10,
    max_lookback_days: int = DEFAULT_MAX_LOOKBACK_DAYS,
    transport: Transport | None = None,
    timeout_seconds: int = 30,
    max_attempts: int = 2,
    rate_limit_seconds: float = 0.25,
) -> dict[str, Any]:
    """捕捉最近官方交易 sessions 並保存 candidate-only bundle。"""

    if sessions <= 0 or sessions > 30:
        raise ValueError("sessions 必須介於 1 與 30")
    if max_lookback_days < sessions:
        raise ValueError("max_lookback_days 必須足以涵蓋 sessions")
    transport_fn = transport or _default_transport
    output_path = Path(output_root).expanduser().resolve()
    run_id = _utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = output_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    def fetch_spec(spec: EndpointSpec) -> tuple[HttpResponse, list[dict[str, Any]], datetime]:
        response, attempts = _request_with_retries(
            transport_fn, spec=spec, timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
        completed_at = _utc_now()
        return response, attempts, completed_at

    # 先用 TWSE T86 找最近官方 sessions，避免把週末／休市日寫成 0 rows。
    discovered: list[date] = []
    discovery_responses: dict[str, tuple[HttpResponse, list[dict[str, Any]], datetime, EndpointSpec]] = {}
    for offset in range(max_lookback_days + 1):
        candidate_date = as_of_date - timedelta(days=offset)
        spec = _endpoint_specs(candidate_date)[0]
        try:
            response, attempts, completed_at = fetch_spec(spec)
            decoded = _payload_object(response.payload)
            if str(decoded.get("stat", "")).strip().upper() in {"OK", "SUCCESS"}:
                _require_date(decoded, candidate_date.isoformat())
                rows = _twse_rows(decoded, table=False)
                if rows:
                    discovered.append(candidate_date)
                    discovery_responses[candidate_date.isoformat()] = (response, attempts, completed_at, spec)
        except Exception:
            pass
        if len(discovered) >= sessions:
            break
        if rate_limit_seconds > 0:
            time.sleep(rate_limit_seconds)
    if len(discovered) < sessions:
        raise FlowCaptureError(
            f"官方 T86 在 lookback {max_lookback_days} 天只找到 {len(discovered)} 個 sessions，需求 {sessions}"
        )
    discovered = sorted(discovered, reverse=True)[:sessions]

    manifest_sources: list[dict[str, Any]] = []
    source_rows: dict[str, list[dict[str, Any]]] = {INSTITUTIONAL_TABLE: [], CREDIT_TABLE: []}
    session_statuses: list[dict[str, Any]] = []
    for session_date in sorted(discovered):
        date_str = session_date.isoformat()
        per_session: dict[str, Any] = {"decision_date": date_str, "sources": []}
        parsed_by_source: dict[str, list[ParsedSource]] = {INSTITUTIONAL_TABLE: [], CREDIT_TABLE: []}
        for spec_index, spec in enumerate(_endpoint_specs(session_date)):
            if spec_index == 0 and date_str in discovery_responses:
                response, attempts, completed_at, _ = discovery_responses[date_str]
            else:
                if rate_limit_seconds > 0:
                    time.sleep(rate_limit_seconds)
                response, attempts, completed_at = fetch_spec(spec)
            payload_sha = _sha256(response.payload)
            raw_path = run_dir / "raw" / date_str / _raw_filename(spec)
            _write_create_only(raw_path, response.payload)
            metadata = {
                "schema_version": "institutional-credit-flows-raw-metadata.v1",
                "source_id": spec.source_id,
                "market": spec.market,
                "endpoint_id": spec.endpoint_id,
                "source_version": spec.source_version,
                "url": response.url,
                "request_parameters": dict(spec.params),
                "requested_date": date_str,
                "completed_at": completed_at.isoformat(),
                "http_status": response.status_code,
                "http_headers": dict(response.headers),
                "attempts": attempts,
                "payload_sha256": payload_sha,
                "payload_size_bytes": len(response.payload),
                "quantity_unit": spec.quantity_unit,
            }
            metadata_path = run_dir / "raw" / date_str / (_raw_filename(spec) + ".metadata.json")
            _write_json_create_only(metadata_path, metadata)
            stats = {
                "source_id": spec.source_id,
                "market": spec.market,
                "endpoint_id": spec.endpoint_id,
                "requested_date": date_str,
                "status": "captured",
                "http_status": response.status_code,
                "raw_path": str(raw_path.relative_to(run_dir)),
                "metadata_path": str(metadata_path.relative_to(run_dir)),
                "payload_sha256": payload_sha,
                "payload_size_bytes": len(response.payload),
            }
            try:
                parsed = _parse_endpoint(
                    spec, response.payload, requested_date=date_str,
                    completed_at=completed_at,
                )
                parsed_by_source[spec.source_id].append(parsed)
                stats.update({
                    "status": "parsed",
                    "raw_row_count": len(parsed.rows) + len(parsed.quarantine),
                    "accepted_row_count": len(parsed.rows),
                    "quarantine_row_count": len(parsed.quarantine),
                    "availability_evidence": parsed.availability_evidence,
                })
            except Exception as exc:
                stats.update({"status": "parse_failed", "error": str(exc)})
                raise FlowCaptureError(f"{spec.endpoint_id} {date_str} 解析失敗: {exc}") from exc
            manifest_sources.append({
                "source_id": spec.source_id,
                "market": spec.market,
                "decision_date": date_str,
                "endpoint_id": spec.endpoint_id,
                "source_version": spec.source_version,
                "quantity_unit": spec.quantity_unit,
                "raw_artifacts": [{
                    "path": str(raw_path.relative_to(run_dir)),
                    "sha256": payload_sha,
                    "metadata_path": str(metadata_path.relative_to(run_dir)),
                }],
                "capture": stats,
            })
            per_session["sources"].append(stats)
        for source_id, parsed_items in parsed_by_source.items():
            merged, quarantine = _merge_rows(source_id, parsed_items)
            rows_payload = [_candidate_row(row, source_id=source_id) for row in merged]
            rows_path = run_dir / "candidate" / source_id / f"{date_str}.json"
            rows_hash = _write_json_create_only(rows_path, rows_payload)
            source_rows[source_id].extend(rows_payload)
            for entry in reversed(manifest_sources):
                if entry["source_id"] == source_id and entry["decision_date"] == date_str:
                    entry["candidate_rows_path"] = str(rows_path.relative_to(run_dir))
                    entry["candidate_rows_sha256"] = rows_hash
                    entry["accepted_row_count"] = len(rows_payload)
                    entry["quarantine_row_count"] = len(quarantine)
                    break
            per_session.setdefault("merged", {})[source_id] = {
                "candidate_rows_path": str(rows_path.relative_to(run_dir)),
                "candidate_rows_sha256": rows_hash,
                "accepted_row_count": len(rows_payload),
                "quarantine_row_count": len(quarantine),
            }
        session_statuses.append(per_session)

    # apply 以 source/date 文件為單位；兩個市場的 raw artifact 必須綁到同一
    # candidate rows 文件，不能讓 apply 只驗到其中一個 endpoint。
    grouped_entries: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in manifest_sources:
        key = (str(entry["source_id"]), str(entry["decision_date"]))
        grouped = grouped_entries.setdefault(
            key,
            {
                "source_id": key[0],
                "decision_date": key[1],
                "raw_artifacts": [],
            },
        )
        grouped["raw_artifacts"].extend(entry["raw_artifacts"])
    for (source_id, date_str), grouped in grouped_entries.items():
        rows_path = run_dir / "candidate" / source_id / f"{date_str}.json"
        if not rows_path.is_file():
            raise FlowCaptureError(f"candidate rows 缺失: {rows_path}")
        grouped["candidate_rows_path"] = str(rows_path.relative_to(run_dir))
        grouped["candidate_rows_sha256"] = _manifest_file_hash(rows_path)
    grouped_sources: list[dict[str, Any]] = []
    for key in sorted(grouped_entries):
        grouped_entry = grouped_entries[key]
        rows_path = run_dir / str(grouped_entry["candidate_rows_path"])
        rows_payload = json.loads(rows_path.read_text(encoding="utf-8"))
        grouped_entry["accepted_row_count"] = len(rows_payload)
        grouped_sources.append(grouped_entry)

    # apply 以 source/date 文件為單位，manifest 需把每個 source/date 納入一次。
    manifest = {
        "schema_version": "institutional-credit-flows-candidate-bundle.v1",
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "created_at": _utc_now().isoformat(),
        "as_of_date": as_of_date.isoformat(),
        "discovered_sessions": [value.isoformat() for value in sorted(discovered)],
        "session_count": len(discovered),
        "candidate_only": True,
        "formal_apply_allowed": False,
        "source_acceptance": "requires_human_acceptance",
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
        "quantity_units_require_owner_review": True,
        "code_shape_diagnostics": {
            source_id: _code_shape_diagnostics(rows)
            for source_id, rows in source_rows.items()
        },
        "sources": grouped_sources,
        "sessions": session_statuses,
        "totals": {
            source_id: len(rows)
            for source_id, rows in source_rows.items()
        },
    }
    manifest_path = run_dir / "manifest.json"
    manifest_hash = _write_json_create_only(manifest_path, manifest)
    readback = {
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "run_id": run_id,
        "as_of_date": as_of_date.isoformat(),
        "sessions": manifest["discovered_sessions"],
        "totals": manifest["totals"],
        "candidate_only": True,
        "formal_apply_allowed": False,
    }
    _write_json_create_only(run_dir / "readback.json", readback)
    return readback


def rebuild_flow_manifest_from_raw(
    run_dir: str | Path,
    *,
    manifest_name: str = "manifest.json",
) -> dict[str, Any]:
    """從既有 raw／metadata 重播 candidate，不重新發 HTTP，也不改 raw bytes。"""

    root = Path(run_dir).expanduser().resolve(strict=True)
    original_manifest_path = _resolve_manifest_child(root, manifest_name, label="原始 manifest")
    try:
        original = json.loads(original_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FlowCaptureError("原始 manifest 無法解析") from exc
    entries = original.get("sources")
    if not isinstance(entries, list) or not entries:
        raise FlowCaptureError("原始 manifest 缺少 sources")

    parsed_by_key: dict[tuple[str, str], list[ParsedSource]] = {}
    raw_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise FlowCaptureError("原始 source entry 不是 object")
        source_id = str(entry.get("source_id", ""))
        requested_date = str(entry.get("decision_date", ""))
        raw_entries = entry.get("raw_artifacts")
        if source_id not in {INSTITUTIONAL_TABLE, CREDIT_TABLE} or not isinstance(raw_entries, list):
            raise FlowCaptureError("原始 source identity／raw_artifacts 不符")
        key = (source_id, requested_date)
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, Mapping):
                raise FlowCaptureError("原始 raw artifact 不是 object")
            raw_path = _resolve_manifest_child(root, raw_entry.get("path"), label="原始 raw")
            metadata_path = _resolve_manifest_child(root, raw_entry.get("metadata_path"), label="原始 metadata")
            raw_bytes = raw_path.read_bytes()
            expected_sha = str(raw_entry.get("sha256", ""))
            if _sha256(raw_bytes) != expected_sha:
                raise FlowCaptureError(f"原始 raw hash 不符: {raw_path}")
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise FlowCaptureError(f"原始 metadata 無法解析: {metadata_path}") from exc
            if not isinstance(metadata, Mapping) or str(metadata.get("payload_sha256")) != expected_sha:
                raise FlowCaptureError(f"原始 metadata hash 不符: {metadata_path}")
            endpoint_id = str(metadata.get("endpoint_id", ""))
            parser_kind = {
                "twse:T86": "twse_institutional",
                "tpex:3itrade": "tpex_institutional",
                "twse:MI_MARGN": "twse_credit",
                "tpex:margin_bal": "tpex_credit",
            }.get(endpoint_id)
            if parser_kind is None:
                raise FlowCaptureError(f"原始 endpoint 不支援重播: {endpoint_id}")
            try:
                completed_at = datetime.fromisoformat(str(metadata["completed_at"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise FlowCaptureError(f"原始 metadata 缺少合法 completed_at: {metadata_path}") from exc
            spec = EndpointSpec(
                source_id=source_id,
                market=str(metadata.get("market", "")),
                endpoint_id=endpoint_id,
                source_version=str(metadata.get("source_version", "")),
                url=str(metadata.get("url", "")),
                params={str(k): str(v) for k, v in dict(metadata.get("request_parameters", {})).items()},
                parser_kind=parser_kind,
                quantity_unit=str(metadata.get("quantity_unit", "")),
            )
            parsed = _parse_endpoint(
                spec, raw_bytes, requested_date=requested_date, completed_at=completed_at
            )
            parsed_by_key.setdefault(key, []).append(parsed)
            raw_by_key.setdefault(key, []).append(dict(raw_entry))

    replayed_sources: list[dict[str, Any]] = []
    source_rows: dict[str, list[dict[str, Any]]] = {INSTITUTIONAL_TABLE: [], CREDIT_TABLE: []}
    for key in sorted(parsed_by_key):
        source_id, date_str = key
        merged, quarantine = _merge_rows(source_id, parsed_by_key[key])
        rows_payload = [_candidate_row(row, source_id=source_id) for row in merged]
        rows_path = root / "candidate_v2" / source_id / f"{date_str}.json"
        rows_hash = _write_json_create_only(rows_path, rows_payload)
        source_rows[source_id].extend(rows_payload)
        replayed_sources.append({
            "source_id": source_id,
            "decision_date": date_str,
            "raw_artifacts": raw_by_key[key],
            "candidate_rows_path": str(rows_path.relative_to(root)),
            "candidate_rows_sha256": rows_hash,
            "accepted_row_count": len(rows_payload),
            "quarantine_row_count": len(quarantine),
        })

    replay_manifest = {
        "schema_version": "institutional-credit-flows-candidate-bundle.v1",
        "parser_version": PARSER_VERSION,
        "run_id": f"{original.get('run_id', 'unknown')}-raw-replay-v2",
        "created_at": _utc_now().isoformat(),
        "replayed_from_manifest": str(original_manifest_path),
        "capture_replayed_without_network": True,
        "as_of_date": original.get("as_of_date"),
        "discovered_sessions": original.get("discovered_sessions", []),
        "session_count": original.get("session_count"),
        "candidate_only": True,
        "formal_apply_allowed": False,
        "source_acceptance": "requires_human_acceptance",
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
        "quantity_units_require_owner_review": True,
        "code_shape_diagnostics": {
            source_id: _code_shape_diagnostics(rows)
            for source_id, rows in source_rows.items()
        },
        "sources": replayed_sources,
        "totals": {source_id: len(rows) for source_id, rows in source_rows.items()},
    }
    replay_manifest_path = root / "manifest_with_observed_at.json"
    replay_hash = _write_json_create_only(replay_manifest_path, replay_manifest)
    readback = {
        "manifest_path": str(replay_manifest_path),
        "manifest_sha256": replay_hash,
        "replayed_from_manifest": str(original_manifest_path),
        "capture_replayed_without_network": True,
        "sessions": replay_manifest["discovered_sessions"],
        "totals": replay_manifest["totals"],
        "candidate_only": True,
        "formal_apply_allowed": False,
    }
    _write_json_create_only(root / "readback_with_observed_at.json", readback)
    return readback


__all__ = [
    "APPLY_CONFIRM_TOKEN",
    "CREDIT_TABLE",
    "DEFAULT_OUTPUT_ROOT",
    "FlowApplyError",
    "FlowCaptureError",
    "HttpResponse",
    "INSTITUTIONAL_TABLE",
    "apply_flow_manifest",
    "capture_recent_flows",
    "rebuild_flow_manifest_from_raw",
]
