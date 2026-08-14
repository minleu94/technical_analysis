"""官方公司行動／交易限制的 immutable PIT backfill publication。

本模組只讀 TWSE／TPEx 官方 HTTP endpoint，且只寫呼叫端明確指定的
publication root。它不讀寫 active SQLite，也不修改既有正式 raw files。

PIT 語意：

* 停牌與復牌拆成獨立事件，避免停牌列攜帶未來復牌資訊。
* 有官方事件時分秒時，available_at 與 effective_at 相同。
* TWT49U／TWTAUU 是事後計算結果表；只可供 label／ledger，並保守地在
  effective date 台北時間日終才標記 available。
* 官方來源未提供 revision／supersedes link；同 natural key 若內容改變，
  publication 必須 fail closed，不得以 last-write-wins 覆蓋。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import time as time_module
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import urlencode
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests


PUBLICATION_SCHEMA_VERSION = "official-market-event-publication.v1"
LATEST_POINTER_SCHEMA_VERSION = "official-market-event-latest.v1"
RAW_INDEX_SCHEMA_VERSION = "official-market-event-raw-index.v1"
EVENT_SCHEMA_VERSION = "official-market-event.v1"
SOURCE_REGISTRY_SCHEMA_VERSION = "official-market-event-sources.v1"
FAILED_CUSTODY_SCHEMA_VERSION = "official-market-event-failed-custody.v1"

TWSE_LICENSE_URL = "https://www.twse.com.tw/zh/page/terms/use.html"
TPEX_LICENSE_URL = (
    "https://www.tpex.org.tw/web/inc/gtsm_disclaimer.php?l=zh-tw"
)
_TAIPEI = ZoneInfo("Asia/Taipei")
_UTC = timezone.utc
_SHA256_PREFIX = "sha256:"
_RESULT_AVAILABLE_TIME = time(23, 59, 59)
_TWSE_EXPLICIT_NO_DATA_STATUSES = frozenset(
    {
        "很抱歉，沒有符合條件的資料!",
        "很抱歉，沒有符合條件的資料！",
    }
)


@dataclass(frozen=True)
class OfficialMarketEndpoint:
    source_id: str
    source_version: str
    venue: str
    endpoint_url: str
    license_url: str
    parser_id: str
    request_mode: str
    result_only: bool

    def parameters_for_year(
        self,
        year: int,
        *,
        query_end_date: date | None = None,
    ) -> dict[str, str]:
        if self.request_mode == "twse_date_range":
            end_date = date(year, 12, 31)
            if (
                query_end_date is not None
                and query_end_date.year == year
            ):
                end_date = min(end_date, query_end_date)
            return {
                "response": "json",
                "startDate": f"{year:04d}0101",
                "endDate": end_date.strftime("%Y%m%d"),
            }
        if self.request_mode == "tpex_year":
            return {"date": f"{year:04d}", "cate": "1"}
        raise ValueError(
            f"unsupported official endpoint request_mode: {self.request_mode}"
        )

    def registry_payload(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_version": self.source_version,
            "venue": self.venue,
            "endpoint_url": self.endpoint_url,
            "license_url": self.license_url,
            "parser_id": self.parser_id,
            "request_mode": self.request_mode,
            "result_only": self.result_only,
            "allowed_uses": (
                ["formal_label", "formal_ledger"]
                if self.result_only
                else ["formal_trading_restriction_timeline"]
            ),
        }


OFFICIAL_MARKET_ENDPOINTS: tuple[OfficialMarketEndpoint, ...] = (
    OfficialMarketEndpoint(
        source_id="twse.TWTAWU.halt_resume",
        source_version="twse-TWTAWU-range.v1",
        venue="TWSE",
        endpoint_url="https://www.twse.com.tw/exchangeReport/TWTAWU",
        license_url=TWSE_LICENSE_URL,
        parser_id="twse_twtawu.v1",
        request_mode="twse_date_range",
        result_only=False,
    ),
    OfficialMarketEndpoint(
        source_id="tpex.sprcHis.halt_resume",
        source_version="tpex-sprcHis-year.v1",
        venue="TPEX",
        endpoint_url=(
            "https://www.tpex.org.tw/www/zh-tw/bulletin/sprcHis"
        ),
        license_url=TPEX_LICENSE_URL,
        parser_id="tpex_sprcHis.v1",
        request_mode="tpex_year",
        result_only=False,
    ),
    OfficialMarketEndpoint(
        source_id="twse.TWT49U.ex_right_dividend_result",
        source_version="twse-TWT49U-range.v1",
        venue="TWSE",
        endpoint_url="https://www.twse.com.tw/exchangeReport/TWT49U",
        license_url=TWSE_LICENSE_URL,
        parser_id="twse_twt49u.v1",
        request_mode="twse_date_range",
        result_only=True,
    ),
    OfficialMarketEndpoint(
        source_id="twse.TWTAUU.capital_reduction_result",
        source_version="twse-TWTAUU-range.v1",
        venue="TWSE",
        endpoint_url="https://www.twse.com.tw/exchangeReport/TWTAUU",
        license_url=TWSE_LICENSE_URL,
        parser_id="twse_twtauu.v1",
        request_mode="twse_date_range",
        result_only=True,
    ),
)


@dataclass(frozen=True)
class RawOfficialResponse:
    endpoint: OfficialMarketEndpoint
    request_year: int
    request_parameters: tuple[tuple[str, str], ...]
    source_url: str
    retrieved_at: str
    http_status: int
    content_type: str
    http_date: str | None
    etag: str | None
    last_modified: str | None
    payload: bytes

    def __post_init__(self) -> None:
        _aware_datetime(
            self.retrieved_at,
            field_name="raw response retrieved_at",
        )
        if self.http_status != 200:
            raise ValueError("official endpoint response must be HTTP 200")
        if not self.source_url.startswith("https://"):
            raise ValueError("official endpoint source_url must use https")

    @property
    def response_sha256(self) -> str:
        return _sha256_bytes(self.payload)


@dataclass(frozen=True)
class CanonicalMarketEvent:
    natural_key: str
    event_id: str
    source_id: str
    source_version: str
    venue: str
    symbol: str
    security_name: str
    event_type: str
    event_at: str
    effective_at: str
    announced_at: str | None
    available_at: str
    effective_precision: str
    availability_basis: str
    result_only: bool
    formal_trading_restriction_allowed: bool
    formal_label_ledger_allowed: bool
    source_year: int
    source_url: str
    license_url: str
    raw_response_sha256: str
    event_chain_id: str
    predecessor_event_id: str | None
    source_row_ordinal: int | None
    revision_availability_ambiguous: bool
    source_record_hash: str
    revision_id: str
    supersedes_revision_id: str | None
    source_record: Mapping[str, str]

    def __post_init__(self) -> None:
        effective = _aware_datetime(
            self.effective_at,
            field_name="canonical effective_at",
        )
        available = _aware_datetime(
            self.available_at,
            field_name="canonical available_at",
        )
        announced = (
            None
            if self.announced_at is None
            else _aware_datetime(
                self.announced_at,
                field_name="canonical announced_at",
            )
        )
        event = _aware_datetime(
            self.event_at,
            field_name="canonical event_at",
        )
        if event != effective:
            raise ValueError("canonical event_at must equal effective_at")
        if available < effective:
            raise ValueError("canonical available_at precedes effective_at")
        if announced is not None and available < announced:
            raise ValueError("canonical available_at precedes announced_at")
        if (
            self.result_only
            and self.formal_trading_restriction_allowed
        ):
            raise ValueError(
                "result-only event cannot enter trading restriction timeline"
            )
        if not self.result_only and self.formal_label_ledger_allowed:
            raise ValueError(
                "trading restriction event cannot masquerade as result table"
            )
        _require_sha256(self.event_id, field_name="event_id")
        _require_sha256(
            self.raw_response_sha256,
            field_name="raw_response_sha256",
        )
        _require_sha256(
            self.event_chain_id,
            field_name="event_chain_id",
        )
        if self.predecessor_event_id is not None:
            _require_sha256(
                self.predecessor_event_id,
                field_name="predecessor_event_id",
            )
        if (
            self.source_row_ordinal is not None
            and (
                isinstance(self.source_row_ordinal, bool)
                or self.source_row_ordinal <= 0
            )
        ):
            raise ValueError("source_row_ordinal must be positive integer")
        if type(self.revision_availability_ambiguous) is not bool:
            raise TypeError(
                "revision_availability_ambiguous must be bool"
            )
        _require_sha256(
            self.source_record_hash,
            field_name="source_record_hash",
        )
        _require_sha256(self.revision_id, field_name="revision_id")
        if self.supersedes_revision_id is not None:
            _require_sha256(
                self.supersedes_revision_id,
                field_name="supersedes_revision_id",
            )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "natural_key": self.natural_key,
            "event_id": self.event_id,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "venue": self.venue,
            "symbol": self.symbol,
            "security_name": self.security_name,
            "event_type": self.event_type,
            "event_at": self.event_at,
            "effective_at": self.effective_at,
            "announced_at": self.announced_at,
            "available_at": self.available_at,
            "effective_precision": self.effective_precision,
            "availability_basis": self.availability_basis,
            "result_only": self.result_only,
            "formal_trading_restriction_allowed": (
                self.formal_trading_restriction_allowed
            ),
            "formal_label_ledger_allowed": (
                self.formal_label_ledger_allowed
            ),
            "formal_decision_feature_allowed": False,
            "source_year": self.source_year,
            "source_url": self.source_url,
            "license_url": self.license_url,
            "raw_response_sha256": self.raw_response_sha256,
            "event_chain_id": self.event_chain_id,
            "predecessor_event_id": self.predecessor_event_id,
            "source_row_ordinal": self.source_row_ordinal,
            "revision_availability_ambiguous": (
                self.revision_availability_ambiguous
            ),
            "source_record_hash": self.source_record_hash,
            "revision_id": self.revision_id,
            "supersedes_revision_id": self.supersedes_revision_id,
            "source_record": dict(self.source_record),
        }


@dataclass(frozen=True)
class OfficialMarketEventBackfillRequest:
    output_root: Path
    raw_custody: Path | None = None
    start_year: int = 2014
    end_year: int = 2026
    timeout_seconds: int = 30
    max_attempts: int = 3
    retry_delay_seconds: int = 2
    request_delay_seconds: int = 1

    def __post_init__(self) -> None:
        if self.start_year < 1912 or self.end_year < self.start_year:
            raise ValueError("invalid official market event year range")
        for field_name in (
            "timeout_seconds",
            "max_attempts",
        ):
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be positive")
        for field_name in (
            "retry_delay_seconds",
            "request_delay_seconds",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be non-negative")


@dataclass(frozen=True)
class OfficialMarketEventPublication:
    publication_id: str
    publication_directory: Path
    manifest_path: Path
    latest_manifest_path: Path
    manifest_hash: str
    manifest_file_hash: str
    canonical_events_path: Path
    canonical_events_hash: str
    canonical_event_count: int
    new_event_count: int
    raw_request_count: int


class OfficialEndpointFetcher(Protocol):
    def fetch(
        self,
        endpoint: OfficialMarketEndpoint,
        request_year: int,
        *,
        timeout_seconds: int,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> RawOfficialResponse:
        """取得一個 endpoint/year 的原始 bytes。"""


class RequestsOfficialEndpointFetcher:
    """具 bounded timeout/retry 的官方唯讀 HTTP fetcher。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session or requests.Session()
        self._now = now or (lambda: datetime.now(_UTC))

    def fetch(
        self,
        endpoint: OfficialMarketEndpoint,
        request_year: int,
        *,
        timeout_seconds: int,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> RawOfficialResponse:
        request_clock = self._now()
        if (
            request_clock.tzinfo is None
            or request_clock.utcoffset() is None
        ):
            raise ValueError("fetch clock must be timezone-aware")
        query_end_date = request_clock.astimezone(_TAIPEI).date()
        parameters = endpoint.parameters_for_year(
            request_year,
            query_end_date=query_end_date,
        )
        source_url = (
            f"{endpoint.endpoint_url}?{urlencode(parameters)}"
        )
        headers = {
            "Accept": "application/json",
            "User-Agent": "baldr-official-market-event-backfill/1.0",
        }
        last_error: BaseException | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._session.get(
                    endpoint.endpoint_url,
                    params=parameters,
                    headers=headers,
                    timeout=timeout_seconds,
                )
                if response.status_code == 200:
                    try:
                        _official_response_classification(
                            endpoint,
                            bytes(response.content),
                        )
                    except (TypeError, ValueError) as exc:
                        last_error = RuntimeError(
                            "official endpoint returned anomalous "
                            f"payload: {source_url}: {exc}"
                        )
                    else:
                        retrieved_at = self._now()
                        if (
                            retrieved_at.tzinfo is None
                            or retrieved_at.utcoffset() is None
                        ):
                            raise ValueError(
                                "fetch clock must be timezone-aware"
                            )
                        return RawOfficialResponse(
                            endpoint=endpoint,
                            request_year=request_year,
                            request_parameters=tuple(
                                sorted(parameters.items())
                            ),
                            source_url=source_url,
                            retrieved_at=retrieved_at.isoformat(),
                            http_status=200,
                            content_type=str(
                                response.headers.get("Content-Type", "")
                            ),
                            http_date=_optional_header(
                                response.headers, "Date"
                            ),
                            etag=_optional_header(
                                response.headers, "ETag"
                            ),
                            last_modified=_optional_header(
                                response.headers, "Last-Modified"
                            ),
                            payload=bytes(response.content),
                        )
                else:
                    response_headers = response.headers
                    header_diagnostics = [
                        f"content_type={response_headers.get('Content-Type', '')}",
                    ]
                    for header_name in ("Server", "CF-Ray", "Retry-After"):
                        header_value = response_headers.get(header_name)
                        if header_value:
                            header_diagnostics.append(
                                f"{header_name.lower()}={header_value}"
                            )
                    last_error = RuntimeError(
                        "official endpoint returned HTTP "
                        f"{response.status_code}: {source_url}; "
                        + "; ".join(header_diagnostics)
                    )
                    if (
                        response.status_code < 500
                        and response.status_code != 429
                    ):
                        break
            except requests.RequestException as exc:
                last_error = exc
            if attempt < max_attempts and retry_delay_seconds:
                time_module.sleep(
                    min(30, retry_delay_seconds * attempt)
                )
        diagnostic = (
            ""
            if last_error is None
            else f"; last_error={_exception_summary(last_error)}"
        )
        raise RuntimeError(
            f"official endpoint fetch failed after {max_attempts} attempts: "
            f"{source_url}{diagnostic}"
        ) from last_error


@dataclass(frozen=True)
class _PriorPublication:
    manifest_hash: str | None
    manifest_file_hash: str | None
    events: tuple[CanonicalMarketEvent, ...]


class OfficialMarketEventBackfillBuilder:
    """建立 immutable raw + append-only canonical event publication。"""

    def __init__(
        self,
        *,
        endpoints: Sequence[OfficialMarketEndpoint] = (
            OFFICIAL_MARKET_ENDPOINTS
        ),
        fetcher: OfficialEndpointFetcher | None = None,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[int], None] | None = None,
    ) -> None:
        self._endpoints = tuple(endpoints)
        self._now = now or (lambda: datetime.now(_UTC))
        self._fetcher = fetcher or RequestsOfficialEndpointFetcher(
            now=self._now
        )
        self._sleep = sleep or time_module.sleep
        if not self._endpoints:
            raise ValueError("at least one official endpoint is required")

    def build(
        self,
        request: OfficialMarketEventBackfillRequest,
    ) -> OfficialMarketEventPublication:
        output_root = request.output_root.resolve()
        runs_root = output_root / "runs"
        output_root.mkdir(parents=True, exist_ok=True)
        runs_root.mkdir(parents=True, exist_ok=True)
        prior = _load_prior_publication(output_root)
        (
            raw_custody_entries,
            raw_custody_manifest_hash,
        ) = _load_failed_raw_custody(
            request.raw_custody,
            endpoints=self._endpoints,
        )
        staging = output_root / f".official-market-events-{uuid4().hex}"
        staging.mkdir()
        raw_entries: list[dict[str, object]] = []
        parsed_events: list[CanonicalMarketEvent] = []
        coverage: dict[str, dict[str, object]] = {}
        raw_request_count = 0
        network_request_count = 0
        reused_raw_response_count = 0
        total_requests = len(self._endpoints) * (
            request.end_year - request.start_year + 1
        )
        try:
            for endpoint_index, endpoint in enumerate(self._endpoints):
                source_effective_values: list[str] = []
                source_raw_rows = 0
                source_event_rows = 0
                source_requests = 0
                source_reused_responses = 0
                source_official_no_data_responses = 0
                for request_year in range(
                    request.start_year,
                    request.end_year + 1,
                ):
                    custody_key = (endpoint.source_id, request_year)
                    raw = raw_custody_entries.get(custody_key)
                    reused = raw is not None
                    if raw is None:
                        raw = self._fetcher.fetch(
                            endpoint,
                            request_year,
                            timeout_seconds=request.timeout_seconds,
                            max_attempts=request.max_attempts,
                            retry_delay_seconds=(
                                request.retry_delay_seconds
                            ),
                        )
                        network_request_count += 1
                    else:
                        source_reused_responses += 1
                        reused_raw_response_count += 1
                    relative_path = (
                        Path("raw")
                        / _safe_path_component(endpoint.source_id)
                        / f"year={request_year:04d}"
                        / "response.json"
                    )
                    target = staging / relative_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw.payload)
                    raw_index_entry = _raw_index_entry(
                        raw,
                        response_path=relative_path.as_posix(),
                    )
                    raw_index_entry["reused_from_failed_custody"] = reused
                    raw_entries.append(raw_index_entry)
                    source_requests += 1
                    raw_request_count += 1
                    response_classification = (
                        _official_response_classification(
                            endpoint,
                            raw.payload,
                        )
                    )
                    if response_classification == "official_no_data":
                        source_official_no_data_responses += 1
                    events, raw_row_count = parse_official_market_events(raw)
                    parsed_events.extend(events)
                    source_effective_values.extend(
                        event.effective_at for event in events
                    )
                    source_raw_rows += raw_row_count
                    source_event_rows += len(events)
                    if (
                        not reused
                        and request.request_delay_seconds
                        and network_request_count < total_requests
                    ):
                        self._sleep(request.request_delay_seconds)
                coverage[endpoint.source_id] = {
                    "source_id": endpoint.source_id,
                    "venue": endpoint.venue,
                    "requested_start_year": request.start_year,
                    "requested_end_year": request.end_year,
                    "request_count": source_requests,
                    "raw_custody_reused_response_count": (
                        source_reused_responses
                    ),
                    "official_no_data_response_count": (
                        source_official_no_data_responses
                    ),
                    "raw_row_count": source_raw_rows,
                    "parsed_event_count": source_event_rows,
                    "min_effective_at": (
                        min(source_effective_values)
                        if source_effective_values
                        else None
                    ),
                    "max_effective_at": (
                        max(source_effective_values)
                        if source_effective_values
                        else None
                    ),
                    "complete_year_coverage": source_requests
                    == request.end_year - request.start_year + 1,
                    "result_only": endpoint.result_only,
                    "endpoint_order": endpoint_index,
                }

            merged_events, new_event_count, duplicate_count = _merge_events(
                prior.events,
                parsed_events,
            )
            raw_index_path = staging / "raw_index.jsonl"
            raw_index_bytes = _jsonl_bytes(raw_entries)
            raw_index_path.write_bytes(raw_index_bytes)
            canonical_events_path = staging / "canonical" / "events.jsonl"
            canonical_events_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_bytes = _jsonl_bytes(
                [event.payload() for event in merged_events]
            )
            canonical_events_path.write_bytes(canonical_bytes)
            raw_index_hash = _sha256_bytes(raw_index_bytes)
            canonical_events_hash = _sha256_bytes(canonical_bytes)
            generated_at = self._now()
            if (
                generated_at.tzinfo is None
                or generated_at.utcoffset() is None
            ):
                raise ValueError("publication clock must be timezone-aware")
            generated_text = generated_at.isoformat()
            source_registry = {
                "schema_version": SOURCE_REGISTRY_SCHEMA_VERSION,
                "sources": [
                    endpoint.registry_payload()
                    for endpoint in self._endpoints
                ],
            }
            publication_identity = {
                "schema_version": PUBLICATION_SCHEMA_VERSION,
                "parent_manifest_hash": prior.manifest_hash,
                "generated_at": generated_text,
                "requested_start_year": request.start_year,
                "requested_end_year": request.end_year,
                "raw_index_hash": raw_index_hash,
                "canonical_events_hash": canonical_events_hash,
                "source_registry_hash": _sha256_json(source_registry),
            }
            publication_id = (
                "official-market-events-"
                + _sha256_json(publication_identity)[7:31]
            )
            manifest: dict[str, object] = {
                "schema_version": PUBLICATION_SCHEMA_VERSION,
                "publication_id": publication_id,
                "status": "formal_source_publication",
                "generated_at": generated_text,
                "parent_manifest_hash": prior.manifest_hash,
                "parent_manifest_file_hash": prior.manifest_file_hash,
                "request": {
                    "start_year": request.start_year,
                    "end_year": request.end_year,
                    "timeout_seconds": request.timeout_seconds,
                    "max_attempts": request.max_attempts,
                    "retry_delay_seconds": request.retry_delay_seconds,
                    "request_delay_seconds": (
                        request.request_delay_seconds
                    ),
                    "raw_custody_manifest_hash": (
                        raw_custody_manifest_hash
                    ),
                    "raw_custody_reused_response_count": (
                        reused_raw_response_count
                    ),
                    "network_request_count": network_request_count,
                },
                "source_registry": source_registry,
                "coverage": [
                    coverage[endpoint.source_id]
                    for endpoint in self._endpoints
                ],
                "raw_index": {
                    "schema_version": RAW_INDEX_SCHEMA_VERSION,
                    "path": "raw_index.jsonl",
                    "file_hash": raw_index_hash,
                    "request_count": raw_request_count,
                    "network_request_count": network_request_count,
                    "reused_failed_custody_response_count": (
                        reused_raw_response_count
                    ),
                },
                "canonical_events": {
                    "schema_version": EVENT_SCHEMA_VERSION,
                    "path": "canonical/events.jsonl",
                    "file_hash": canonical_events_hash,
                    "event_count": len(merged_events),
                    "previous_event_count": len(prior.events),
                    "new_event_count": new_event_count,
                    "exact_duplicate_count": duplicate_count,
                    "revision_availability_ambiguity_count": sum(
                        int(event.revision_availability_ambiguous)
                        for event in merged_events
                    ),
                },
                "safety": {
                    "formal_source_publication": True,
                    "active_sqlite_written": False,
                    "original_raw_files_modified": False,
                    "immutable_raw_responses": True,
                    "append_only_canonical_events": True,
                    "available_at_effective_at_separated": True,
                    "halt_resume_split_into_independent_events": True,
                    "cross_year_resume_linked_to_primary_halt": True,
                    "official_no_data_preserved_as_zero_rows": True,
                    "anomalous_api_status_fails_closed": True,
                    "bounded_retry_with_backoff": True,
                    "http_headers_used_as_publication_time": False,
                    "unlinked_revision_last_write_wins": False,
                    "unlinked_revision_fails_closed": True,
                    "all_official_revision_vintages_preserved": True,
                    "same_availability_revision_ties_diagnosed": True,
                    "same_availability_revision_claims_later_visibility": (
                        False
                    ),
                    "result_tables_label_ledger_only": True,
                    "result_tables_decision_feature_allowed": False,
                    "atomic_latest_manifest_publish": True,
                },
            }
            manifest["manifest_hash"] = _sha256_json(manifest)
            manifest_path = staging / "manifest.json"
            _write_json(manifest_path, manifest)
            manifest_file_hash = _file_sha256(manifest_path)
            publication_directory = runs_root / publication_id
            if publication_directory.exists():
                existing_manifest = publication_directory / "manifest.json"
                if (
                    not existing_manifest.exists()
                    or _file_sha256(existing_manifest) != manifest_file_hash
                ):
                    raise FileExistsError(
                        "official market event publication id collision"
                    )
                shutil.rmtree(staging)
            else:
                staging.replace(publication_directory)
            final_manifest_path = publication_directory / "manifest.json"
            latest_manifest_path = output_root / "latest_manifest.json"
            _atomic_write_json(
                latest_manifest_path,
                {
                    "schema_version": LATEST_POINTER_SCHEMA_VERSION,
                    "publication_id": publication_id,
                    "manifest_path": (
                        f"runs/{publication_id}/manifest.json"
                    ),
                    "manifest_hash": manifest["manifest_hash"],
                    "manifest_file_hash": manifest_file_hash,
                    "canonical_events_hash": canonical_events_hash,
                },
            )
            return OfficialMarketEventPublication(
                publication_id=publication_id,
                publication_directory=publication_directory,
                manifest_path=final_manifest_path,
                latest_manifest_path=latest_manifest_path,
                manifest_hash=str(manifest["manifest_hash"]),
                manifest_file_hash=manifest_file_hash,
                canonical_events_path=(
                    publication_directory / "canonical" / "events.jsonl"
                ),
                canonical_events_hash=canonical_events_hash,
                canonical_event_count=len(merged_events),
                new_event_count=new_event_count,
                raw_request_count=raw_request_count,
            )
        except Exception as exc:
            if staging.exists():
                _quarantine_failed_staging(
                    staging=staging,
                    output_root=output_root,
                    request=request,
                    raw_entries=raw_entries,
                    failure=exc,
                    generated_at=self._now(),
                    raw_custody_manifest_hash=(
                        raw_custody_manifest_hash
                    ),
                )
            raise


def parse_official_market_events(
    raw: RawOfficialResponse,
) -> tuple[tuple[CanonicalMarketEvent, ...], int]:
    """將單一官方 raw response 轉為嚴格 canonical events。"""

    try:
        payload = json.loads(raw.payload.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"official endpoint returned invalid JSON: {raw.source_url}"
        ) from exc
    if raw.endpoint.parser_id == "twse_twtawu.v1":
        result = _parse_twse_twtawu(raw, payload)
    elif raw.endpoint.parser_id == "tpex_sprcHis.v1":
        result = _parse_tpex_sprchis(raw, payload)
    elif raw.endpoint.parser_id == "twse_twt49u.v1":
        result = _parse_twse_twt49u(raw, payload)
    elif raw.endpoint.parser_id == "twse_twtauu.v1":
        result = _parse_twse_twtauu(raw, payload)
    else:
        raise ValueError(
            f"unsupported official parser_id: {raw.endpoint.parser_id}"
        )
    events, raw_row_count = result
    wrong_year = (
        ()
        if raw.endpoint.parser_id in {
            "twse_twtawu.v1",
            "tpex_sprcHis.v1",
        }
        else tuple(
            event
            for event in events
            if _aware_datetime(
                event.effective_at,
                field_name="parsed event effective_at",
            ).year
            != raw.request_year
        )
    )
    if wrong_year:
        raise ValueError(
            "official endpoint ignored requested year or returned "
            f"out-of-range events: source={raw.endpoint.source_id};"
            f"request_year={raw.request_year};"
            f"first_effective_at={wrong_year[0].effective_at}"
        )
    return events, raw_row_count


def _parse_twse_twtawu(
    raw: RawOfficialResponse,
    payload: object,
) -> tuple[tuple[CanonicalMarketEvent, ...], int]:
    fields, rows = _twse_rows(
        payload,
        required_fields={
            "證券代號",
            "證券名稱",
            "暫停交易日期",
            "暫停交易時間",
            "恢復交易日期",
            "恢復交易時間",
        },
    )
    events: list[CanonicalMarketEvent] = []
    for source_row_ordinal, values in enumerate(rows, start=1):
        row = _strict_row_mapping(fields, values)
        events.extend(_halt_resume_events(raw, row))
    return tuple(events), len(rows)


def _parse_tpex_sprchis(
    raw: RawOfficialResponse,
    payload: object,
) -> tuple[tuple[CanonicalMarketEvent, ...], int]:
    root = _required_mapping(payload, field_name="TPEx sprcHis payload")
    if root.get("stat") != "ok":
        raise ValueError("TPEx sprcHis stat is not ok")
    tables = root.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ValueError("TPEx sprcHis tables missing")
    events: list[CanonicalMarketEvent] = []
    raw_row_count = 0
    open_halts_by_symbol: dict[str, CanonicalMarketEvent] = {}
    required = {
        "有價證券代號",
        "有價證券名稱",
        "暫停交易日期",
        "暫停交易時間",
        "恢復交易日期",
        "恢復交易時間",
    }
    for table_payload in tables:
        table = _required_mapping(
            table_payload,
            field_name="TPEx sprcHis table",
        )
        raw_fields = table.get("fields")
        rows = table.get("data")
        if not isinstance(raw_fields, list) or not isinstance(rows, list):
            raise ValueError("TPEx sprcHis fields/data missing")
        fields = tuple(str(field) for field in raw_fields)
        if not required.issubset(set(fields)):
            raise ValueError("TPEx sprcHis required fields missing")
        total_count = table.get("totalCount")
        if (
            isinstance(total_count, bool)
            or not isinstance(total_count, int)
            or total_count != len(rows)
        ):
            raise ValueError("TPEx sprcHis totalCount mismatch")
        for values in rows:
            if not isinstance(values, list):
                raise ValueError("TPEx sprcHis row must be an array")
            row_fields = fields
            if (
                len(values) == len(fields) + 1
                and "有價證券類別" not in fields
            ):
                # 舊年度 payload 在「編號」後保留一個未列入 fields 的類別欄。
                row_fields = (
                    fields[:1]
                    + ("有價證券類別",)
                    + fields[1:]
                )
            row = _strict_row_mapping(row_fields, values)
            symbol = _required_text(
                row.get("有價證券代號"),
                field_name="TPEx halt/resume symbol",
            )
            row_events = _halt_resume_events(
                raw,
                row,
                prior_halt_event=open_halts_by_symbol.get(symbol),
            )
            events.extend(row_events)
            for event in row_events:
                if event.event_type == "trading_halt":
                    open_halts_by_symbol[symbol] = event
                elif (
                    event.event_type == "trading_resume"
                    and event.predecessor_event_id is not None
                ):
                    open_halts_by_symbol.pop(symbol, None)
            raw_row_count += 1
    return tuple(events), raw_row_count


def _parse_twse_twt49u(
    raw: RawOfficialResponse,
    payload: object,
) -> tuple[tuple[CanonicalMarketEvent, ...], int]:
    fields, rows = _twse_rows(
        payload,
        required_fields={
            "資料日期",
            "股票代號",
            "股票名稱",
            "除權息前收盤價",
            "除權息參考價",
            "權值+息值",
            "權/息",
            "漲停價格",
            "跌停價格",
            "開盤競價基準",
            "減除股利參考價",
        },
    )
    events: list[CanonicalMarketEvent] = []
    stable_fields = (
        "資料日期",
        "股票代號",
        "股票名稱",
        "除權息前收盤價",
        "除權息參考價",
        "權值+息值",
        "權/息",
        "漲停價格",
        "跌停價格",
        "開盤競價基準",
        "減除股利參考價",
    )
    for source_row_ordinal, values in enumerate(rows, start=1):
        row = _strict_row_mapping(fields, values)
        source_record = _selected_text_fields(row, stable_fields)
        effective_date = _parse_official_date(source_record["資料日期"])
        symbol = _required_text(
            source_record["股票代號"],
            field_name="TWT49U 股票代號",
        )
        event_type = "ex_right_dividend_result"
        effective_at = _date_start(effective_date)
        natural_key = "|".join(
            (
                raw.endpoint.source_id,
                symbol,
                event_type,
                effective_date.isoformat(),
            )
        )
        events.append(
            _canonical_event(
                raw=raw,
                natural_key=natural_key,
                symbol=symbol,
                security_name=source_record["股票名稱"],
                event_type=event_type,
                effective_at=effective_at,
                available_at=_date_end(effective_date),
                effective_precision="date",
                availability_basis=(
                    "effective_date_end_of_day_conservative_result_table"
                ),
                result_only=True,
                source_record=source_record,
                source_row_ordinal=source_row_ordinal,
            )
        )
    return tuple(events), len(rows)


def _parse_twse_twtauu(
    raw: RawOfficialResponse,
    payload: object,
) -> tuple[tuple[CanonicalMarketEvent, ...], int]:
    fields, rows = _twse_rows(
        payload,
        required_fields={
            "恢復買賣日期",
            "股票代號",
            "名稱",
            "停止買賣前收盤價格",
            "恢復買賣參考價",
            "漲停價格",
            "跌停價格",
            "開盤競價基準",
            "除權參考價",
            "減資原因",
            "詳細資料",
        },
    )
    events: list[CanonicalMarketEvent] = []
    stable_fields = (
        "恢復買賣日期",
        "股票代號",
        "名稱",
        "停止買賣前收盤價格",
        "恢復買賣參考價",
        "漲停價格",
        "跌停價格",
        "開盤競價基準",
        "除權參考價",
        "減資原因",
        "詳細資料",
    )
    for source_row_ordinal, values in enumerate(rows, start=1):
        row = _strict_row_mapping(fields, values)
        source_record = _selected_text_fields(row, stable_fields)
        effective_date = _parse_official_date(
            source_record["恢復買賣日期"]
        )
        symbol = _required_text(
            source_record["股票代號"],
            field_name="TWTAUU 股票代號",
        )
        event_type = "capital_reduction_resume_result"
        effective_at = _date_start(effective_date)
        announced_date = _parse_twse_detail_date(
            source_record["詳細資料"]
        )
        announced_at = _date_end(announced_date)
        available_at = max(
            _date_end(effective_date),
            announced_at,
        )
        natural_key = "|".join(
            (
                raw.endpoint.source_id,
                symbol,
                event_type,
                effective_date.isoformat(),
            )
        )
        events.append(
            _canonical_event(
                raw=raw,
                natural_key=natural_key,
                symbol=symbol,
                security_name=source_record["名稱"],
                event_type=event_type,
                effective_at=effective_at,
                announced_at=announced_at,
                available_at=available_at,
                effective_precision="date",
                availability_basis=(
                    "effective_date_end_of_day_conservative_result_table"
                ),
                result_only=True,
                source_record=source_record,
                source_row_ordinal=source_row_ordinal,
            )
        )
    return _link_event_revisions(events), len(rows)


def _halt_resume_events(
    raw: RawOfficialResponse,
    row: Mapping[str, object],
    *,
    prior_halt_event: CanonicalMarketEvent | None = None,
) -> tuple[CanonicalMarketEvent, ...]:
    symbol = _required_text(
        row.get("證券代號", row.get("有價證券代號")),
        field_name="halt/resume symbol",
    )
    security_name = _required_text(
        row.get("證券名稱", row.get("有價證券名稱")),
        field_name="halt/resume security name",
    )
    raw_halt_date = row.get("暫停交易日期")
    raw_resume_date = row.get("恢復交易日期")
    has_halt = not _is_missing_official_value(raw_halt_date)
    has_resume = not _is_missing_official_value(raw_resume_date)
    if not has_halt and not has_resume:
        raise ValueError("halt/resume row contains no primary event")
    primary_date = _parse_official_date(
        raw_halt_date if has_halt else raw_resume_date
    )
    if primary_date.year != raw.request_year:
        raise ValueError(
            "official endpoint ignored requested year or returned "
            "out-of-range primary event: "
            f"source={raw.endpoint.source_id};"
            f"request_year={raw.request_year};"
            f"primary_event_date={primary_date.isoformat()}"
        )
    halt_effective_at: str | None = None
    halt_event_id: str | None = None
    if has_halt:
        halt_effective_at = datetime.combine(
            _parse_official_date(raw_halt_date),
            _parse_official_time(row.get("暫停交易時間")),
            tzinfo=_TAIPEI,
        ).isoformat()
        event_chain_id = _sha256_text(
            "|".join(
                (
                    raw.endpoint.source_id,
                    symbol,
                    "halt_resume_chain",
                    halt_effective_at,
                )
            )
        )
        halt_natural_key = "|".join(
            (
                raw.endpoint.source_id,
                symbol,
                "trading_halt",
                halt_effective_at,
            )
        )
        halt_event_id = _sha256_text(halt_natural_key)
    elif (
        prior_halt_event is not None
        and prior_halt_event.symbol == symbol
        and prior_halt_event.event_type == "trading_halt"
    ):
        event_chain_id = prior_halt_event.event_chain_id
        halt_effective_at = prior_halt_event.effective_at
        halt_event_id = prior_halt_event.event_id
    else:
        resume_effective_at = datetime.combine(
            _parse_official_date(raw_resume_date),
            _parse_official_time(row.get("恢復交易時間")),
            tzinfo=_TAIPEI,
        ).isoformat()
        event_chain_id = _sha256_text(
            "|".join(
                (
                    raw.endpoint.source_id,
                    symbol,
                    "unlinked_resume_chain",
                    resume_effective_at,
                )
            )
        )
    specifications = (
        (
            "trading_halt",
            raw_halt_date,
            row.get("暫停交易時間"),
            None,
        ),
        (
            "trading_resume",
            raw_resume_date,
            row.get("恢復交易時間"),
            halt_event_id,
        ),
    )
    events: list[CanonicalMarketEvent] = []
    for event_type, raw_date, raw_time, predecessor_event_id in specifications:
        if _is_missing_official_value(raw_date):
            if not _is_missing_official_value(raw_time):
                raise ValueError(
                    f"{event_type} time exists without event date"
                )
            continue
        effective_date = _parse_official_date(raw_date)
        effective_time = _parse_official_time(raw_time)
        effective_at = datetime.combine(
            effective_date,
            effective_time,
            tzinfo=_TAIPEI,
        ).isoformat()
        if (
            halt_effective_at is not None
            and effective_at < halt_effective_at
        ):
            raise ValueError(
                "halt/resume continuation precedes primary halt event"
            )
        source_record = {
            "symbol": symbol,
            "security_name": security_name,
            "event_type": event_type,
            "effective_date": effective_date.isoformat(),
            "effective_time": effective_time.isoformat(),
            "event_chain_id": event_chain_id,
        }
        natural_key = "|".join(
            (
                raw.endpoint.source_id,
                symbol,
                event_type,
                effective_at,
            )
        )
        events.append(
            _canonical_event(
                raw=raw,
                natural_key=natural_key,
                symbol=symbol,
                security_name=security_name,
                event_type=event_type,
                effective_at=effective_at,
                available_at=effective_at,
                effective_precision="second",
                availability_basis=(
                    "official_effective_timestamp_conservative_observation"
                ),
                result_only=False,
                source_record=source_record,
                event_chain_id=event_chain_id,
                predecessor_event_id=predecessor_event_id,
            )
        )
    if not events:
        raise ValueError("halt/resume row contains no event")
    return tuple(events)


def _canonical_event(
    *,
    raw: RawOfficialResponse,
    natural_key: str,
    symbol: str,
    security_name: str,
    event_type: str,
    effective_at: str,
    available_at: str,
    effective_precision: str,
    availability_basis: str,
    result_only: bool,
    source_record: Mapping[str, str],
    announced_at: str | None = None,
    event_chain_id: str | None = None,
    predecessor_event_id: str | None = None,
    source_row_ordinal: int | None = None,
) -> CanonicalMarketEvent:
    resolved_event_chain_id = (
        event_chain_id
        if event_chain_id is not None
        else _sha256_text(f"single_event_chain|{natural_key}")
    )
    normalized_source_record = dict(source_record)
    normalized_source_record["event_chain_id"] = resolved_event_chain_id
    source_record_hash = _sha256_json(normalized_source_record)
    return CanonicalMarketEvent(
        natural_key=natural_key,
        event_id=_sha256_text(natural_key),
        source_id=raw.endpoint.source_id,
        source_version=raw.endpoint.source_version,
        venue=raw.endpoint.venue,
        symbol=symbol,
        security_name=security_name,
        event_type=event_type,
        event_at=effective_at,
        effective_at=effective_at,
        announced_at=announced_at,
        available_at=available_at,
        effective_precision=effective_precision,
        availability_basis=availability_basis,
        result_only=result_only,
        formal_trading_restriction_allowed=not result_only,
        formal_label_ledger_allowed=result_only,
        source_year=raw.request_year,
        source_url=raw.source_url,
        license_url=raw.endpoint.license_url,
        raw_response_sha256=raw.response_sha256,
        event_chain_id=resolved_event_chain_id,
        predecessor_event_id=predecessor_event_id,
        source_row_ordinal=source_row_ordinal,
        revision_availability_ambiguous=False,
        source_record_hash=source_record_hash,
        revision_id=source_record_hash,
        supersedes_revision_id=None,
        source_record=normalized_source_record,
    )


def _merge_events(
    prior: Sequence[CanonicalMarketEvent],
    current: Sequence[CanonicalMarketEvent],
) -> tuple[tuple[CanonicalMarketEvent, ...], int, int]:
    by_revision: dict[
        tuple[str, str],
        CanonicalMarketEvent,
    ] = {}
    by_natural_key: dict[str, list[CanonicalMarketEvent]] = {}
    for event in prior:
        revision_key = (event.natural_key, event.revision_id)
        existing = by_revision.get(revision_key)
        if existing is not None:
            raise ValueError(
                "prior publication contains duplicate canonical revision"
            )
        by_revision[revision_key] = event
        by_natural_key.setdefault(event.natural_key, []).append(event)
    for natural_key, revisions in by_natural_key.items():
        _validate_revision_chain(natural_key, revisions)
    new_event_count = 0
    duplicate_count = 0
    for event in current:
        revision_key = (event.natural_key, event.revision_id)
        existing = by_revision.get(revision_key)
        if existing is not None:
            duplicate_count += 1
            continue
        revisions = by_natural_key.setdefault(event.natural_key, [])
        if revisions:
            latest = max(revisions, key=_revision_order_key)
            if (
                event.supersedes_revision_id != latest.revision_id
                or _revision_order_key(event)
                <= _revision_order_key(latest)
            ):
                raise ValueError(
                    "unlinked_revision_conflict:"
                    f"{event.natural_key}:prior={latest.revision_id}:"
                    f"current={event.revision_id}"
                )
        elif event.supersedes_revision_id is not None:
            raise ValueError(
                "unlinked_revision_conflict:"
                f"{event.natural_key}:missing_predecessor="
                f"{event.supersedes_revision_id}:"
                f"current={event.revision_id}"
            )
        by_revision[revision_key] = event
        revisions.append(event)
        new_event_count += 1
    for natural_key, revisions in by_natural_key.items():
        _validate_revision_chain(natural_key, revisions)
    return (
        tuple(
            sorted(
                by_revision.values(),
                key=lambda item: (
                    item.effective_at,
                    item.venue,
                    item.symbol,
                    item.event_type,
                    item.natural_key,
                    *_revision_order_key(item),
                ),
            )
        ),
        new_event_count,
        duplicate_count,
    )


def _validate_revision_chain(
    natural_key: str,
    revisions: Sequence[CanonicalMarketEvent],
) -> None:
    ordered = sorted(
        revisions,
        key=_revision_order_key,
    )
    previous_revision_id: str | None = None
    for event in ordered:
        if event.supersedes_revision_id != previous_revision_id:
            raise ValueError(
                "unlinked_revision_conflict:"
                f"{natural_key}:expected_supersedes="
                f"{previous_revision_id}:actual="
                f"{event.supersedes_revision_id}"
            )
        previous_revision_id = event.revision_id


def _revision_order_key(
    event: CanonicalMarketEvent,
) -> tuple[str, str, int, str]:
    return (
        event.available_at,
        event.announced_at or "",
        (
            event.source_row_ordinal
            if event.source_row_ordinal is not None
            else 2_147_483_647
        ),
        event.revision_id,
    )


def _link_event_revisions(
    events: Sequence[CanonicalMarketEvent],
) -> tuple[CanonicalMarketEvent, ...]:
    grouped: dict[str, dict[str, CanonicalMarketEvent]] = {}
    for event in events:
        revisions = grouped.setdefault(event.natural_key, {})
        existing = revisions.get(event.revision_id)
        if existing is not None:
            if (
                event.source_row_ordinal is not None
                and (
                    existing.source_row_ordinal is None
                    or event.source_row_ordinal
                    < existing.source_row_ordinal
                )
            ):
                revisions[event.revision_id] = event
            continue
        revisions[event.revision_id] = event
    linked: list[CanonicalMarketEvent] = []
    for natural_key, by_revision in grouped.items():
        ordered = sorted(
            by_revision.values(),
            key=_revision_order_key,
        )
        availability_counts: dict[str, int] = {}
        for event in ordered:
            availability_counts[event.available_at] = (
                availability_counts.get(event.available_at, 0) + 1
            )
        previous_revision_id: str | None = None
        for event in ordered:
            linked.append(
                replace(
                    event,
                    supersedes_revision_id=previous_revision_id,
                    revision_availability_ambiguous=(
                        availability_counts[event.available_at] > 1
                    ),
                )
            )
            previous_revision_id = event.revision_id
    return tuple(
        sorted(
            linked,
            key=lambda event: (
                event.effective_at,
                event.natural_key,
                *_revision_order_key(event),
            ),
        )
    )


def _load_prior_publication(output_root: Path) -> _PriorPublication:
    pointer_path = output_root / "latest_manifest.json"
    if not pointer_path.exists():
        return _PriorPublication(None, None, ())
    pointer = _read_json_mapping(
        pointer_path,
        field_name="official market event latest pointer",
    )
    if pointer.get("schema_version") != LATEST_POINTER_SCHEMA_VERSION:
        raise ValueError("unsupported official market event latest pointer")
    manifest_relative = _required_text(
        pointer.get("manifest_path"),
        field_name="latest manifest_path",
    )
    manifest_path = (output_root / manifest_relative).resolve()
    runs_root = (output_root / "runs").resolve()
    if not manifest_path.is_relative_to(runs_root):
        raise ValueError("latest manifest_path escapes runs root")
    expected_file_hash = _required_text(
        pointer.get("manifest_file_hash"),
        field_name="latest manifest_file_hash",
    )
    if _file_sha256(manifest_path) != expected_file_hash:
        raise ValueError("prior manifest file hash mismatch")
    manifest = _read_json_mapping(
        manifest_path,
        field_name="official market event manifest",
    )
    if manifest.get("schema_version") != PUBLICATION_SCHEMA_VERSION:
        raise ValueError("unsupported prior publication schema")
    expected_manifest_hash = _required_text(
        manifest.get("manifest_hash"),
        field_name="prior manifest_hash",
    )
    payload = dict(manifest)
    payload.pop("manifest_hash", None)
    if _sha256_json(payload) != expected_manifest_hash:
        raise ValueError("prior manifest logical hash mismatch")
    if pointer.get("manifest_hash") != expected_manifest_hash:
        raise ValueError("latest pointer logical manifest hash mismatch")
    canonical = _required_mapping(
        manifest.get("canonical_events"),
        field_name="prior canonical_events",
    )
    relative_events_path = _required_text(
        canonical.get("path"),
        field_name="prior canonical events path",
    )
    events_path = (manifest_path.parent / relative_events_path).resolve()
    if not events_path.is_relative_to(manifest_path.parent.resolve()):
        raise ValueError("prior canonical events path escapes publication")
    expected_events_hash = _required_text(
        canonical.get("file_hash"),
        field_name="prior canonical events file_hash",
    )
    if _file_sha256(events_path) != expected_events_hash:
        raise ValueError("prior canonical events file hash mismatch")
    events = tuple(
        _event_from_payload(payload)
        for payload in _read_jsonl_mappings(events_path)
    )
    expected_count = canonical.get("event_count")
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count != len(events)
    ):
        raise ValueError("prior canonical event_count mismatch")
    _merge_events((), events)
    return _PriorPublication(
        manifest_hash=expected_manifest_hash,
        manifest_file_hash=expected_file_hash,
        events=events,
    )


def _event_from_payload(
    payload: Mapping[str, object],
) -> CanonicalMarketEvent:
    if payload.get("schema_version") != EVENT_SCHEMA_VERSION:
        raise ValueError("unsupported canonical market event schema")
    source_record_payload = _required_mapping(
        payload.get("source_record"),
        field_name="canonical source_record",
    )
    source_record = {
        str(key): str(value)
        for key, value in source_record_payload.items()
    }
    return CanonicalMarketEvent(
        natural_key=_required_text(
            payload.get("natural_key"),
            field_name="canonical natural_key",
        ),
        event_id=_required_text(
            payload.get("event_id"),
            field_name="canonical event_id",
        ),
        source_id=_required_text(
            payload.get("source_id"),
            field_name="canonical source_id",
        ),
        source_version=_required_text(
            payload.get("source_version"),
            field_name="canonical source_version",
        ),
        venue=_required_text(
            payload.get("venue"),
            field_name="canonical venue",
        ),
        symbol=_required_text(
            payload.get("symbol"),
            field_name="canonical symbol",
        ),
        security_name=_required_text(
            payload.get("security_name"),
            field_name="canonical security_name",
        ),
        event_type=_required_text(
            payload.get("event_type"),
            field_name="canonical event_type",
        ),
        event_at=_required_text(
            payload.get("event_at"),
            field_name="canonical event_at",
        ),
        effective_at=_required_text(
            payload.get("effective_at"),
            field_name="canonical effective_at",
        ),
        announced_at=(
            None
            if payload.get("announced_at") is None
            else _required_text(
                payload.get("announced_at"),
                field_name="canonical announced_at",
            )
        ),
        available_at=_required_text(
            payload.get("available_at"),
            field_name="canonical available_at",
        ),
        effective_precision=_required_text(
            payload.get("effective_precision"),
            field_name="canonical effective_precision",
        ),
        availability_basis=_required_text(
            payload.get("availability_basis"),
            field_name="canonical availability_basis",
        ),
        result_only=_required_json_bool(
            payload.get("result_only"),
            field_name="canonical result_only",
        ),
        formal_trading_restriction_allowed=_required_json_bool(
            payload.get("formal_trading_restriction_allowed"),
            field_name="canonical formal_trading_restriction_allowed",
        ),
        formal_label_ledger_allowed=_required_json_bool(
            payload.get("formal_label_ledger_allowed"),
            field_name="canonical formal_label_ledger_allowed",
        ),
        source_year=_required_int(
            payload.get("source_year"),
            field_name="canonical source_year",
        ),
        source_url=_required_text(
            payload.get("source_url"),
            field_name="canonical source_url",
        ),
        license_url=_required_text(
            payload.get("license_url"),
            field_name="canonical license_url",
        ),
        raw_response_sha256=_required_text(
            payload.get("raw_response_sha256"),
            field_name="canonical raw_response_sha256",
        ),
        event_chain_id=_required_text(
            payload.get("event_chain_id"),
            field_name="canonical event_chain_id",
        ),
        predecessor_event_id=(
            None
            if payload.get("predecessor_event_id") is None
            else _required_text(
                payload.get("predecessor_event_id"),
                field_name="canonical predecessor_event_id",
            )
        ),
        source_row_ordinal=(
            None
            if payload.get("source_row_ordinal") is None
            else _required_int(
                payload.get("source_row_ordinal"),
                field_name="canonical source_row_ordinal",
            )
        ),
        revision_availability_ambiguous=_required_json_bool(
            payload.get("revision_availability_ambiguous"),
            field_name=(
                "canonical revision_availability_ambiguous"
            ),
        ),
        source_record_hash=_required_text(
            payload.get("source_record_hash"),
            field_name="canonical source_record_hash",
        ),
        revision_id=_required_text(
            payload.get("revision_id"),
            field_name="canonical revision_id",
        ),
        supersedes_revision_id=(
            None
            if payload.get("supersedes_revision_id") is None
            else _required_text(
                payload.get("supersedes_revision_id"),
                field_name="canonical supersedes_revision_id",
            )
        ),
        source_record=source_record,
    )


def _raw_index_entry(
    raw: RawOfficialResponse,
    *,
    response_path: str,
) -> dict[str, object]:
    return {
        "schema_version": RAW_INDEX_SCHEMA_VERSION,
        "source_id": raw.endpoint.source_id,
        "source_version": raw.endpoint.source_version,
        "venue": raw.endpoint.venue,
        "request_year": raw.request_year,
        "request_parameters": [
            [key, value] for key, value in raw.request_parameters
        ],
        "source_url": raw.source_url,
        "license_url": raw.endpoint.license_url,
        "retrieved_at": raw.retrieved_at,
        "http_status": raw.http_status,
        "content_type": raw.content_type,
        "http_date": raw.http_date,
        "etag": raw.etag,
        "last_modified": raw.last_modified,
        "response_classification": _official_response_classification(
            raw.endpoint,
            raw.payload,
        ),
        "http_headers_used_as_publication_time": False,
        "response_path": response_path,
        "response_sha256": raw.response_sha256,
        "response_bytes": len(raw.payload),
    }


def _quarantine_failed_staging(
    *,
    staging: Path,
    output_root: Path,
    request: OfficialMarketEventBackfillRequest,
    raw_entries: Sequence[Mapping[str, object]],
    failure: BaseException,
    generated_at: datetime,
    raw_custody_manifest_hash: str | None,
) -> Path:
    if (
        generated_at.tzinfo is None
        or generated_at.utcoffset() is None
    ):
        raise ValueError("quarantine clock must be timezone-aware")
    raw_index_bytes = _jsonl_bytes(raw_entries)
    raw_index_path = staging / "raw_index.jsonl"
    raw_index_path.write_bytes(raw_index_bytes)
    raw_index_hash = _sha256_bytes(raw_index_bytes)
    failure_id = "failed-" + staging.name.rsplit("-", 1)[-1]
    manifest: dict[str, object] = {
        "schema_version": FAILED_CUSTODY_SCHEMA_VERSION,
        "failure_id": failure_id,
        "status": "rejected_failure_custody",
        "generated_at": generated_at.isoformat(),
        "failure": {
            "error_type": type(failure).__name__,
            "message": str(failure),
        },
        "request": {
            "start_year": request.start_year,
            "end_year": request.end_year,
            "timeout_seconds": request.timeout_seconds,
            "max_attempts": request.max_attempts,
            "retry_delay_seconds": request.retry_delay_seconds,
            "request_delay_seconds": request.request_delay_seconds,
            "parent_raw_custody_manifest_hash": (
                raw_custody_manifest_hash
            ),
        },
        "raw_index": {
            "schema_version": RAW_INDEX_SCHEMA_VERSION,
            "path": "raw_index.jsonl",
            "file_hash": raw_index_hash,
            "response_count": len(raw_entries),
        },
        "safety": {
            "formal_publication": False,
            "latest_manifest_updated": False,
            "immutable_successful_raw_preserved": True,
            "active_sqlite_written": False,
            "offline_replay_allowed": True,
        },
    }
    manifest["manifest_hash"] = _sha256_json(manifest)
    _write_json(staging / "failure_manifest.json", manifest)
    quarantine_root = output_root / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)
    quarantine_directory = quarantine_root / failure_id
    if quarantine_directory.exists():
        raise FileExistsError(
            f"failed custody id collision: {quarantine_directory}"
        )
    staging.replace(quarantine_directory)
    return quarantine_directory


def _load_failed_raw_custody(
    path: Path | None,
    *,
    endpoints: Sequence[OfficialMarketEndpoint],
) -> tuple[
    dict[tuple[str, int], RawOfficialResponse],
    str | None,
]:
    if path is None:
        return {}, None
    resolved = path.resolve()
    manifest_path = (
        resolved / "failure_manifest.json"
        if resolved.is_dir()
        else resolved
    )
    manifest = _read_json_mapping(
        manifest_path,
        field_name="failed raw custody manifest",
    )
    if manifest.get("schema_version") != FAILED_CUSTODY_SCHEMA_VERSION:
        raise ValueError("unsupported failed raw custody schema")
    if manifest.get("status") != "rejected_failure_custody":
        raise ValueError("raw custody is not rejected failure custody")
    expected_manifest_hash = _required_text(
        manifest.get("manifest_hash"),
        field_name="failed raw custody manifest_hash",
    )
    logical_manifest = dict(manifest)
    logical_manifest.pop("manifest_hash", None)
    if _sha256_json(logical_manifest) != expected_manifest_hash:
        raise ValueError("failed raw custody manifest hash mismatch")
    raw_index = _required_mapping(
        manifest.get("raw_index"),
        field_name="failed raw custody raw_index",
    )
    relative_index = _required_text(
        raw_index.get("path"),
        field_name="failed raw custody raw_index path",
    )
    custody_root = manifest_path.parent.resolve()
    raw_index_path = (custody_root / relative_index).resolve()
    if not raw_index_path.is_relative_to(custody_root):
        raise ValueError("failed raw custody raw index escapes root")
    expected_index_hash = _required_text(
        raw_index.get("file_hash"),
        field_name="failed raw custody raw_index file_hash",
    )
    if _file_sha256(raw_index_path) != expected_index_hash:
        raise ValueError("failed raw custody raw index hash mismatch")
    endpoint_by_source = {
        endpoint.source_id: endpoint for endpoint in endpoints
    }
    responses: dict[tuple[str, int], RawOfficialResponse] = {}
    for payload in _read_jsonl_mappings(raw_index_path):
        source_id = _required_text(
            payload.get("source_id"),
            field_name="failed raw custody source_id",
        )
        endpoint = endpoint_by_source.get(source_id)
        if endpoint is None:
            continue
        request_year = _required_int(
            payload.get("request_year"),
            field_name="failed raw custody request_year",
        )
        response_relative = _required_text(
            payload.get("response_path"),
            field_name="failed raw custody response_path",
        )
        response_path = (custody_root / response_relative).resolve()
        if not response_path.is_relative_to(custody_root):
            raise ValueError("failed raw custody response escapes root")
        response_payload = response_path.read_bytes()
        expected_response_hash = _required_text(
            payload.get("response_sha256"),
            field_name="failed raw custody response_sha256",
        )
        if _sha256_bytes(response_payload) != expected_response_hash:
            raise ValueError("failed raw custody response hash mismatch")
        raw_parameters = payload.get("request_parameters")
        if not isinstance(raw_parameters, list):
            raise TypeError(
                "failed raw custody request_parameters must be array"
            )
        parameters: list[tuple[str, str]] = []
        for pair in raw_parameters:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not all(isinstance(item, str) for item in pair)
            ):
                raise TypeError(
                    "failed raw custody request parameter must be text pair"
                )
            parameters.append((pair[0], pair[1]))
        response = RawOfficialResponse(
            endpoint=endpoint,
            request_year=request_year,
            request_parameters=tuple(parameters),
            source_url=_required_text(
                payload.get("source_url"),
                field_name="failed raw custody source_url",
            ),
            retrieved_at=_required_text(
                payload.get("retrieved_at"),
                field_name="failed raw custody retrieved_at",
            ),
            http_status=_required_int(
                payload.get("http_status"),
                field_name="failed raw custody http_status",
            ),
            content_type=str(payload.get("content_type", "")),
            http_date=_optional_text(payload.get("http_date")),
            etag=_optional_text(payload.get("etag")),
            last_modified=_optional_text(payload.get("last_modified")),
            payload=response_payload,
        )
        _official_response_classification(endpoint, response_payload)
        key = (source_id, request_year)
        if key in responses:
            raise ValueError("failed raw custody contains duplicate request")
        responses[key] = response
    expected_count = _required_int(
        raw_index.get("response_count"),
        field_name="failed raw custody response_count",
    )
    if expected_count != len(tuple(_read_jsonl_mappings(raw_index_path))):
        raise ValueError("failed raw custody response_count mismatch")
    return responses, expected_manifest_hash


def _official_response_classification(
    endpoint: OfficialMarketEndpoint,
    payload_bytes: bytes,
) -> str:
    try:
        payload = json.loads(payload_bytes.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("official response is not valid JSON") from exc
    root = _required_mapping(payload, field_name="official response")
    stat = root.get("stat")
    if endpoint.request_mode == "twse_date_range":
        if stat in _TWSE_EXPLICIT_NO_DATA_STATUSES:
            return "official_no_data"
        if stat != "OK":
            raise ValueError(
                f"TWSE anomalous response stat: {stat!r}"
            )
        if not isinstance(root.get("fields"), list) or not isinstance(
            root.get("data"), list
        ):
            raise ValueError("TWSE OK response misses fields/data arrays")
        return "ok"
    if endpoint.request_mode == "tpex_year":
        if stat != "ok":
            raise ValueError(
                f"TPEx anomalous response stat: {stat!r}"
            )
        if not isinstance(root.get("tables"), list):
            raise ValueError("TPEx ok response misses tables array")
        return "ok"
    raise ValueError(
        f"unsupported response request_mode: {endpoint.request_mode}"
    )


def _twse_rows(
    payload: object,
    *,
    required_fields: set[str],
) -> tuple[tuple[str, ...], list[object]]:
    root = _required_mapping(payload, field_name="TWSE payload")
    stat = root.get("stat")
    if stat in _TWSE_EXPLICIT_NO_DATA_STATUSES:
        return (), []
    if stat != "OK":
        raise ValueError(f"TWSE response stat is not OK: {stat!r}")
    raw_fields = root.get("fields")
    rows = root.get("data")
    if not isinstance(raw_fields, list) or not isinstance(rows, list):
        raise ValueError("TWSE response fields/data missing")
    fields = tuple(str(field) for field in raw_fields)
    if not required_fields.issubset(set(fields)):
        raise ValueError("TWSE response required fields missing")
    return fields, rows


def _strict_row_mapping(
    fields: Sequence[str],
    values: object,
) -> dict[str, object]:
    if not isinstance(values, list):
        raise ValueError("official response row must be an array")
    if len(values) != len(fields):
        raise ValueError(
            "official response row length does not match fields"
        )
    if len(set(fields)) != len(fields):
        raise ValueError("official response fields contain duplicates")
    return dict(zip(fields, values))


def _selected_text_fields(
    row: Mapping[str, object],
    fields: Sequence[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in fields:
        if field not in row:
            raise ValueError(f"official response field missing: {field}")
        result[field] = str(row[field]).strip()
    return result


def _parse_official_date(value: object) -> date:
    text = str(value).strip()
    if _is_missing_official_value(text):
        raise ValueError("official event date is missing")
    normalized = (
        text.replace("年", "/")
        .replace("月", "/")
        .replace("日", "")
        .replace("-", "/")
    )
    if re.fullmatch(r"\d{7,8}", normalized):
        if len(normalized) == 8 and int(normalized[:4]) >= 1912:
            return date(
                int(normalized[:4]),
                int(normalized[4:6]),
                int(normalized[6:8]),
            )
        if len(normalized) == 7:
            return date(
                int(normalized[:3]) + 1911,
                int(normalized[3:5]),
                int(normalized[5:7]),
            )
    parts = normalized.split("/")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"invalid official event date: {text}")
    year = int(parts[0])
    if year < 1912:
        year += 1911
    return date(year, int(parts[1]), int(parts[2]))


def _parse_twse_detail_date(value: object) -> date:
    text = str(value).strip()
    matched = re.search(r"(20\d{6})\s*$", text)
    if matched is None:
        raise ValueError(
            f"TWSE detail field misses revision date: {text}"
        )
    revision_date = matched.group(1)
    try:
        return date(
            int(revision_date[:4]),
            int(revision_date[4:6]),
            int(revision_date[6:8]),
        )
    except ValueError as exc:
        raise ValueError(
            f"TWSE detail revision date is invalid: {text}"
        ) from exc


def _parse_official_time(value: object) -> time:
    text = str(value).strip()
    if _is_missing_official_value(text):
        raise ValueError("official event time is missing")
    if ":" in text:
        parts = text.split(":")
        if len(parts) not in (2, 3):
            raise ValueError(f"invalid official event time: {text}")
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    else:
        if not text.isdigit() or len(text) > 6:
            raise ValueError(f"invalid official event time: {text}")
        compact = text.zfill(6)
        hour = int(compact[:2])
        minute = int(compact[2:4])
        second = int(compact[4:6])
    return time(hour, minute, second)


def _date_start(value: date) -> str:
    return datetime.combine(
        value,
        time(0, 0),
        tzinfo=_TAIPEI,
    ).isoformat()


def _date_end(value: date) -> str:
    return datetime.combine(
        value,
        _RESULT_AVAILABLE_TIME,
        tzinfo=_TAIPEI,
    ).isoformat()


def _is_missing_official_value(value: object) -> bool:
    return str(value).strip() in {"", "-", "--", "N/A", "null", "None"}


def _exception_summary(error: BaseException) -> str:
    """Return a bounded, single-line diagnostic safe for scheduled status."""

    message = str(error).replace("\r", " ").replace("\n", " ").strip()
    if not message:
        message = type(error).__name__
    return message[:512]


def _optional_header(
    headers: Mapping[str, object],
    name: str,
) -> str | None:
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            text = str(value).strip()
            return text or None
    return None


def _safe_path_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    if not safe or safe in {".", ".."}:
        raise ValueError("unsafe official source_id path component")
    return safe


def _jsonl_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    return "".join(
        json.dumps(
            dict(row),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for row in rows
    ).encode("utf-8")


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _atomic_write_json(
    path: Path,
    payload: Mapping[str, object],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                dict(payload),
                stream,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json_mapping(
    path: Path,
    *,
    field_name: str,
) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field_name} is unreadable or invalid") from exc
    return _required_mapping(payload, field_name=field_name)


def _read_jsonl_mappings(path: Path) -> tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"invalid canonical JSONL at line {line_number}"
                    ) from exc
                rows.append(
                    _required_mapping(
                        payload,
                        field_name=(
                            f"canonical JSONL line {line_number}"
                        ),
                    )
                )
    except OSError as exc:
        raise ValueError("canonical JSONL is unreadable") from exc
    return tuple(rows)


def _required_mapping(
    value: object,
    *,
    field_name: str,
) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a JSON object")
    return value


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_json_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a JSON boolean")
    return value


def _required_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _aware_datetime(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone")
    return parsed


def _require_sha256(value: str, *, field_name: str) -> None:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError(f"{field_name} must be sha256:<64 lowercase hex>")


def _sha256_bytes(payload: bytes) -> str:
    return _SHA256_PREFIX + sha256(payload).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()
