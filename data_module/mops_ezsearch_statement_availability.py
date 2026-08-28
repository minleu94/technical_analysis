"""MOPS 公告快易查季度財報發布時間的唯讀、研究用途 adapter。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping, Protocol
from urllib.parse import urlparse

from data_module.fundamental_availability import (
    FORMAL_AVAILABILITY_CONTRACT_VERSION,
    OFFICIAL_ANNOUNCEMENT_EVIDENCE_CLASS,
)

MOPS_EZSEARCH_URL = "https://mopsov.twse.com.tw/mops/web/ezsearch"
MOPS_EZSEARCH_QUERY_URL = "https://mopsov.twse.com.tw/mops/web/ezsearch_query"
MOPS_STATEMENT_AVAILABILITY_SOURCE = "mops.ezsearch.statement_publication"
MOPS_STATEMENT_AVAILABILITY_SCHEMA = "mops-ezsearch-statement-availability.v1"
MOPS_STATEMENT_AVAILABILITY_SOURCE_VERSION = "mops-ezsearch-statement-publication.v1"
MOPS_RESPONSE_ROW_LIMIT = 1000
TAIPEI_TIMEZONE = timezone(timedelta(hours=8))

# EZSearch uses ``status=fail`` for a valid response with no matching rows.
# Keep that separate from transport/parser errors so a bounded capture does
# not present an official empty result as an outage.
_QUERY_SUCCESS_STATUS = "success"
_QUERY_OFFICIAL_NO_DATA_STATUS = "fail"
_QUERY_ERROR_STATUS = "error"

MOPS_STATEMENT_ITEMS: dict[str, str] = {
    "F26": "balance_sheet",
    "F27": "income_statement",
    "F28": "cash_flows_statement",
    "F29": "equity_changes_statement",
}
MOPS_MARKETS = ("sii", "otc", "rotc", "pub")

_PERIOD_PATTERN = re.compile(r"(?P<roc_year>\d{3})年第(?P<quarter>[1-4])季")
_STOCK_CODE_PATTERN = re.compile(r"^\d{4,6}$")


class MOPSEzSearchSession(Protocol):
    def post(
        self,
        url: str,
        *,
        data: Mapping[str, str],
        headers: Mapping[str, str],
        timeout: int,
    ) -> Any: ...


@dataclass(frozen=True)
class MOPSQueryResult:
    market: str
    announcement_item: str
    rows: tuple[dict[str, str], ...]
    response_sha256: str
    source_status: str
    error_code: str = ""


def build_query_payload(
    *,
    market: str,
    announcement_item: str,
    start_date: date,
    end_date: date,
) -> dict[str, str]:
    if market not in MOPS_MARKETS:
        raise ValueError(f"unsupported MOPS market: {market}")
    if announcement_item not in MOPS_STATEMENT_ITEMS:
        raise ValueError(f"unsupported MOPS statement item: {announcement_item}")
    if end_date < start_date:
        raise ValueError("end_date must not be earlier than start_date")
    return {
        "step": "00",
        "RADIO_CM": "1",
        "TYPEK": market,
        "CO_MARKET": "",
        "CO_ID": "",
        "PRO_ITEM": announcement_item,
        "SUBJECT": "",
        "SDATE": _gregorian_to_roc_date(start_date),
        "EDATE": _gregorian_to_roc_date(end_date),
        "lang": "TW",
        "AN": "",
    }


def query_mops_ezsearch(
    session: MOPSEzSearchSession,
    *,
    market: str,
    announcement_item: str,
    start_date: date,
    end_date: date,
    timeout_seconds: int = 30,
) -> MOPSQueryResult:
    payload = build_query_payload(
        market=market,
        announcement_item=announcement_item,
        start_date=start_date,
        end_date=end_date,
    )
    response = session.post(
        MOPS_EZSEARCH_QUERY_URL,
        data=payload,
        headers={
            "Referer": MOPS_EZSEARCH_URL,
            "User-Agent": "technical-analysis-research-readonly/1.0",
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if not isinstance(body, Mapping):
        raise ValueError("MOPS EZSearch response must be a JSON object")
    rows = body.get("data")
    if rows is None:
        rows = []
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise ValueError("MOPS EZSearch response data must be a list of objects")
    if len(rows) >= MOPS_RESPONSE_ROW_LIMIT:
        raise ValueError("MOPS EZSearch response reached the 1000-row cap; narrow the date range")
    status = str(body.get("status", "")).strip()
    if status not in {"success", "fail"}:
        raise ValueError("MOPS EZSearch response has an unsupported status")
    if status == "fail" and rows:
        raise ValueError("MOPS EZSearch failed response must not contain rows")
    normalized_rows = tuple({str(key): str(value) for key, value in row.items()} for row in rows)
    return MOPSQueryResult(
        market=market,
        announcement_item=announcement_item,
        rows=normalized_rows,
        response_sha256=sha256(canonical.encode("utf-8")).hexdigest(),
        source_status=status,
    )


def build_statement_availability_artifact(
    query_results: Iterable[MOPSQueryResult],
    *,
    start_date: date,
    end_date: date,
    captured_at: str,
) -> dict[str, Any]:
    captured = _parse_timestamp(captured_at)
    parsed_rows: list[dict[str, Any]] = []
    query_manifest: list[dict[str, Any]] = []
    seen_event_hashes: set[str] = set()
    duplicate_event_count = 0

    for result in query_results:
        if result.market not in MOPS_MARKETS:
            raise ValueError(f"unsupported MOPS market: {result.market}")
        if result.announcement_item not in MOPS_STATEMENT_ITEMS:
            raise ValueError(f"unsupported MOPS statement item: {result.announcement_item}")
        if re.fullmatch(r"[0-9a-fA-F]{64}", result.response_sha256) is None:
            raise ValueError("MOPS query result response_sha256 must be a SHA-256 hex digest")
        query_status = str(result.source_status).strip().lower()
        if query_status not in {
            _QUERY_SUCCESS_STATUS,
            _QUERY_OFFICIAL_NO_DATA_STATUS,
            _QUERY_ERROR_STATUS,
        }:
            raise ValueError(f"unsupported MOPS query source status: {result.source_status}")
        if query_status == _QUERY_OFFICIAL_NO_DATA_STATUS and result.rows:
            raise ValueError("MOPS official no-data query must not contain rows")
        query_manifest.append(
            {
                "market": result.market,
                "announcement_item": result.announcement_item,
                "response_sha256": result.response_sha256,
                "source_status": query_status,
                "row_count": len(result.rows),
                "error_code": result.error_code,
            }
        )
        for raw_row in result.rows:
            row = _parse_statement_row(
                raw_row,
                expected_market=result.market,
                expected_item=result.announcement_item,
                start_date=start_date,
                end_date=end_date,
                captured_at=captured,
                source_hash=f"sha256:{result.response_sha256}",
            )
            if row["event_hash"] in seen_event_hashes:
                duplicate_event_count += 1
                continue
            seen_event_hashes.add(row["event_hash"])
            parsed_rows.append(row)

    parsed_rows.sort(
        key=lambda item: (
            item["announcement_at"],
            item["stock_code"],
            item["announcement_item"],
        )
    )
    projection_rows = build_availability_projection(parsed_rows)
    return {
        "schema_version": MOPS_STATEMENT_AVAILABILITY_SCHEMA,
        "source_id": MOPS_STATEMENT_AVAILABILITY_SOURCE,
        "source_version": MOPS_STATEMENT_AVAILABILITY_SOURCE_VERSION,
        "source_url": MOPS_EZSEARCH_URL,
        "query_start_date": start_date.isoformat(),
        "query_end_date": end_date.isoformat(),
        "captured_at": captured.isoformat(),
        "timezone": "Asia/Taipei (+08:00)",
        "research_only": True,
        "read_only_source": True,
        "formal_oos_allowed": False,
        "formal_credit_authorized": False,
        "production_scheduler_allowed": False,
        "production_blend_alpha_bp": 0,
        "availability_policy": (
            "preserve official announcement_at; date-only projection becomes available "
            "on the next calendar day to prevent same-day intraday look-ahead"
        ),
        "authoritative_announcement_items": sorted(MOPS_STATEMENT_ITEMS),
        "excluded_umbrella_items": {
            "M31": (
                "mixed semantics: contains both future board-meeting notices and completed "
                "financial-report approvals; not used as statement publication evidence"
            )
        },
        "query_manifest": query_manifest,
        "quality_summary": {
            "event_count": len(parsed_rows),
            "projection_count": len(projection_rows),
            "duplicate_event_count": duplicate_event_count,
            "future_event_count": 0,
            "invalid_event_count": 0,
            "query_count": len(query_manifest),
            "successful_query_count": sum(
                1
                for item in query_manifest
                if item["source_status"] == _QUERY_SUCCESS_STATUS
            ),
            "official_no_data_query_count": sum(
                1
                for item in query_manifest
                if item["source_status"] == _QUERY_OFFICIAL_NO_DATA_STATUS
            ),
            "failed_query_count": sum(
                1
                for item in query_manifest
                if item["source_status"] == _QUERY_ERROR_STATUS
            ),
        },
        "rows": parsed_rows,
        "availability_projection": projection_rows,
    }


def build_availability_projection(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    earliest: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in rows:
        key = (
            str(row["stock_code"]),
            str(row["statement_type"]),
            str(row["period"]),
        )
        current = earliest.get(key)
        if current is None or str(row["announcement_at"]) < str(current["announcement_at"]):
            earliest[key] = row

    projected: list[dict[str, str]] = []
    for key in sorted(earliest):
        row = earliest[key]
        announcement_at = _parse_timestamp(str(row["announcement_at"]))
        projected.append(
            {
                "stock_code": str(row["stock_code"]),
                "statement_type": str(row["statement_type"]),
                "period": str(row["period"]),
                "as_of_date": str(row["period_end"]),
                "announced_date": announcement_at.date().isoformat(),
                "available_date": (announcement_at.date() + timedelta(days=1)).isoformat(),
                "source": MOPS_STATEMENT_AVAILABILITY_SOURCE,
                "source_version": MOPS_STATEMENT_AVAILABILITY_SOURCE_VERSION,
                "availability_contract_version": FORMAL_AVAILABILITY_CONTRACT_VERSION,
                "evidence_class": OFFICIAL_ANNOUNCEMENT_EVIDENCE_CLASS,
                "source_hash": str(row["source_hash"]),
                "revision": "1",
                "parent_revision": "",
            }
        )
    return projected


def _parse_statement_row(
    raw_row: Mapping[str, str],
    *,
    expected_market: str,
    expected_item: str,
    start_date: date,
    end_date: date,
    captured_at: datetime,
    source_hash: str,
) -> dict[str, Any]:
    required = {
        "CDATE",
        "CTIME",
        "TYPEK",
        "COMPANY_ID",
        "COMPANY_NAME",
        "AN_CODE",
        "AN_NAME",
        "SUBJECT",
        "HYPERLINK",
    }
    missing = sorted(field for field in required if not str(raw_row.get(field, "")).strip())
    if missing:
        raise ValueError(f"MOPS statement row is missing required fields: {','.join(missing)}")
    item = str(raw_row["AN_CODE"]).strip()
    if item != expected_item:
        raise ValueError("MOPS statement row announcement item does not match the query")
    stock_code = str(raw_row["COMPANY_ID"]).strip()
    if not _STOCK_CODE_PATTERN.fullmatch(stock_code):
        raise ValueError("MOPS statement row has an invalid company id")
    period, period_end = _parse_period(str(raw_row["SUBJECT"]))
    announcement_at = _parse_roc_timestamp(
        str(raw_row["CDATE"]).strip(),
        str(raw_row["CTIME"]).strip(),
    )
    if not start_date <= announcement_at.date() <= end_date:
        raise ValueError("MOPS statement row timestamp is outside the requested date range")
    if announcement_at > captured_at.astimezone(TAIPEI_TIMEZONE):
        raise ValueError("MOPS statement row timestamp is later than captured_at")
    detail_url = str(raw_row["HYPERLINK"]).strip()
    parsed_url = urlparse(detail_url)
    if parsed_url.scheme != "https" or parsed_url.hostname != "mopsov.twse.com.tw":
        raise ValueError("MOPS statement row detail URL is not an official HTTPS URL")
    event_material = {
        "announcement_at": announcement_at.isoformat(),
        "announcement_item": item,
        "detail_url": detail_url,
        "period": period,
        "stock_code": stock_code,
    }
    event_hash = sha256(
        json.dumps(
            event_material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "stock_code": stock_code,
        "company_name": str(raw_row["COMPANY_NAME"]).strip(),
        "market": expected_market,
        "market_name": str(raw_row["TYPEK"]).strip(),
        "industry": str(raw_row.get("CODE_NAME", "")).strip(),
        "announcement_item": item,
        "announcement_name": str(raw_row["AN_NAME"]).strip(),
        "statement_type": MOPS_STATEMENT_ITEMS[item],
        "subject": str(raw_row["SUBJECT"]).strip(),
        "period": period,
        "period_end": period_end.isoformat(),
        "announcement_at": announcement_at.isoformat(),
        "detail_url": detail_url,
        "event_hash": event_hash,
        "source_hash": source_hash,
    }


def _parse_period(subject: str) -> tuple[str, date]:
    normalized = re.sub(r"\s+", "", subject)
    match = _PERIOD_PATTERN.search(normalized)
    if match is None:
        raise ValueError("MOPS statement subject does not contain an ROC year and quarter")
    gregorian_year = int(match.group("roc_year")) + 1911
    quarter = int(match.group("quarter"))
    end_month = quarter * 3
    end_day = (31, 30, 30, 31)[quarter - 1]
    return (
        f"{gregorian_year}-Q{quarter}",
        date(gregorian_year, end_month, end_day),
    )


def _parse_roc_timestamp(roc_date: str, clock: str) -> datetime:
    match = re.fullmatch(r"(\d{3})/(\d{2})/(\d{2})", roc_date)
    if match is None:
        raise ValueError("MOPS statement row has an invalid ROC date")
    parsed_clock = datetime.strptime(clock, "%H:%M:%S").time()
    return datetime(
        int(match.group(1)) + 1911,
        int(match.group(2)),
        int(match.group(3)),
        parsed_clock.hour,
        parsed_clock.minute,
        parsed_clock.second,
        tzinfo=TAIPEI_TIMEZONE,
    )


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("captured_at must include a timezone")
    return parsed


def _gregorian_to_roc_date(value: date) -> str:
    if value.year <= 1911:
        raise ValueError("MOPS ROC date requires a Gregorian year after 1911")
    return f"{value.year - 1911:03d}/{value.month:02d}/{value.day:02d}"
