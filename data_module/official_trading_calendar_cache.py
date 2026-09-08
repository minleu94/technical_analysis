"""Hash-bound offline cache for the official TWSE annual calendar.

The TWSE ``holidaySchedule`` endpoint publishes an annual market open/closed
schedule.  This module preserves the response bytes, response metadata and
the normalized full-year projection in one create-only artifact.  A consumer
may reuse the artifact only while its explicit freshness window is valid and
after the raw response hash, source identity and every normalized day have
been revalidated.  The annual endpoint is a planned closure schedule; it does
not carry later typhoon or other emergency closure announcements.

The cache is an operational source observation.  It does not create a formal
clock, make a historical PIT claim, or infer an open day from market rows.
For this endpoint, a valid annual response means a weekday absent from the
published closure rows is planned open; weekends remain closed by the exchange
calendar convention already used by the resolver.  Temporary closure events
require separate official event evidence and are never inferred from the
normalized 365-day projection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import base64
import binascii
import hashlib
import html
import json
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse

from data_module.official_phase3c_fetcher import safe_request


OFFICIAL_CALENDAR_CACHE_SCHEMA_VERSION = "official-trading-calendar-cache.v1"
TWSE_HOLIDAY_SCHEDULE_URL = (
    "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
)
DEFAULT_CACHE_MAX_AGE = timedelta(days=7)
MAX_CACHE_BYTES = 16 * 1024 * 1024
MAX_REFRESH_ATTEMPTS = 2
OFFICIAL_TEMPORARY_CLOSURE_CACHE_SCHEMA_VERSION = (
    "official-twse-temporary-closure-cache.v1"
)
TWSE_NEWS_LIST_URL = "https://www.twse.com.tw/rwd/zh/news/newsList"
TWSE_NEWS_DETAIL_URL = "https://www.twse.com.tw/rwd/zh/news/newsDetail"
TWSE_NEWS_CONTENT_URL = (
    "https://www.twse.com.tw/zh/about/news/news/content.html"
)
MAX_TEMPORARY_CLOSURE_DETAIL_REQUESTS = 8
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPEN_MARKERS = ("開始交易", "最後交易", "恢復交易", "照常交易")
_TEMPORARY_CLOSURE_MARKERS = (
    "全日休市",
    "休市一天",
    "市場休市",
    "停止交易",
    "集中交易市場休市",
)
_TEMPORARY_CLOSURE_NEGATIVE_MARKERS = (
    "不休市",
    "市場不休市",
    "不停止交易",
)
TWSE_TEMPORARY_CLOSURE_POLICY_URL = (
    "https://www.twse.com.tw/zh/clearing/suspended.html"
)
_OFFICIAL_ANNOUNCEMENT_HOSTS = frozenset(
    {"www.twse.com.tw", "wwwc.twse.com.tw"}
)
_TAIPEI_TIMEZONE = timezone(timedelta(hours=8))


class OfficialCalendarCacheError(ValueError):
    """The official calendar cache is missing, malformed or not admissible."""


class OfficialCalendarCacheExpired(OfficialCalendarCacheError):
    """The cache was validly captured but is outside its freshness window."""


@dataclass(frozen=True)
class VerifiedOfficialCalendarCache:
    """A validated annual TWSE schedule and its source custody evidence."""

    calendar_year: int
    schedule: Mapping[date, bool]
    evidence: Mapping[str, object]


@dataclass(frozen=True)
class VerifiedTemporaryClosureCache:
    """A validated official event that closes the TWSE market for one date."""

    closure_date: date
    evidence: Mapping[str, object]


def canonical_json(value: object) -> str:
    """Encode an envelope deterministically for its content hash."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def payload_hash(value: object) -> str:
    """Hash a JSON value with the cache's canonical encoding."""

    return "sha256:" + hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


def bytes_hash(raw: bytes) -> str:
    """Hash the exact response bytes captured from the official endpoint."""

    return "sha256:" + hashlib.sha256(raw).hexdigest()


def build_twse_calendar_cache(
    *,
    calendar_year: int,
    raw_response: bytes,
    requested_at: datetime,
    captured_at: datetime,
    response_status: int,
    response_headers: Mapping[str, object] | None = None,
    response_url: str | None = None,
    max_age: timedelta = DEFAULT_CACHE_MAX_AGE,
) -> dict[str, object]:
    """Build a full-year cache from one bounded official response.

    ``captured_at`` must be set by the caller immediately after the response
    bytes have been consumed.  It is deliberately not derived from the
    requested calendar year or an input date.
    """

    _validate_year(calendar_year)
    if not isinstance(raw_response, bytes) or not raw_response:
        raise OfficialCalendarCacheError("official response bytes are required")
    if len(raw_response) > MAX_CACHE_BYTES:
        raise OfficialCalendarCacheError("official response exceeds cache limit")
    if response_status != 200:
        raise OfficialCalendarCacheError("official response status must be 200")
    requested = _require_aware(requested_at, "requested_at")
    captured = _require_aware(captured_at, "captured_at")
    if captured < requested:
        raise OfficialCalendarCacheError(
            "captured_at cannot precede requested_at"
        )
    if (
        not isinstance(max_age, timedelta)
        or max_age <= timedelta(0)
        or max_age > timedelta(days=31)
    ):
        raise OfficialCalendarCacheError(
            "max_age must be greater than zero and no more than 31 days"
        )

    try:
        payload_value: object = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OfficialCalendarCacheError(
            "official holidaySchedule response must be UTF-8 JSON"
        ) from error
    schedule = parse_twse_annual_schedule(payload_value, expected_year=calendar_year)
    source_hash = bytes_hash(raw_response)
    expires = captured + max_age
    headers = _selected_headers(response_headers or {})
    request_url = TWSE_HOLIDAY_SCHEDULE_URL + "?" + urlencode(
        {"queryYear": str(calendar_year - 1911)}
    )
    observed_response_url = request_url if response_url is None else str(response_url)
    if observed_response_url != request_url:
        raise OfficialCalendarCacheError(
            "official response final URL does not match the requested annual endpoint"
        )

    days: list[dict[str, object]] = []
    current = date(calendar_year, 1, 1)
    end = date(calendar_year + 1, 1, 1)
    while current < end:
        if current.weekday() >= 5:
            is_trading_day = False
            reason_code = "weekend_closed"
        elif current in schedule:
            is_trading_day = schedule[current]
            reason_code = (
                "twse_holiday_schedule_explicit_open"
                if is_trading_day
                else "twse_holiday_schedule_closed"
            )
        else:
            is_trading_day = True
            reason_code = "twse_holiday_schedule_open"
        days.append(
            {
                "date": current.isoformat(),
                "is_trading_day": is_trading_day,
                "reason_code": reason_code,
                "source_hash": source_hash,
            }
        )
        current += timedelta(days=1)

    coverage = {
        "calendar_year": calendar_year,
        "start_date": date(calendar_year, 1, 1).isoformat(),
        "end_date": date(calendar_year, 12, 31).isoformat(),
        "day_count": len(days),
        "complete_year": True,
        "annual_schedule_scope": "planned_annual_closures",
        "temporary_closure_coverage": "not_covered",
        "temporary_closure_policy_source": {
            "provider": "TWSE",
            "url": TWSE_TEMPORARY_CLOSURE_POLICY_URL,
            "source_kind": "official_policy_only",
            "event_evidence_required": True,
        },
        "interpretation": (
            "TWSE annual holidaySchedule closure rows; weekday absence is open "
            "only after the complete annual response is hash-verified; "
            "temporary natural-disaster closures require separate official "
            "event evidence"
        ),
    }
    source: dict[str, object] = {
        "provider": "TWSE",
        "endpoint": TWSE_HOLIDAY_SCHEDULE_URL,
        "request_url": request_url,
        "response_url": observed_response_url,
        "request_params": {"queryYear": str(calendar_year - 1911)},
        "http_status": response_status,
        "response_headers": headers,
        "response_sha256": source_hash,
    }
    body: dict[str, object] = {
        "schema_version": OFFICIAL_CALENDAR_CACHE_SCHEMA_VERSION,
        "calendar_year": calendar_year,
        "capture_mode": "bounded_network",
        "network_enabled": True,
        "candidate_only": True,
        "formal_clock_created": False,
        "source": source,
        "coverage": coverage,
        "requested_at_utc": requested.astimezone(timezone.utc).isoformat(),
        "captured_at_utc": captured.astimezone(timezone.utc).isoformat(),
        "available_at_utc": captured.astimezone(timezone.utc).isoformat(),
        "max_age_seconds": int(max_age.total_seconds()),
        "expires_at_utc": expires.astimezone(timezone.utc).isoformat(),
        "raw_response_base64": base64.b64encode(raw_response).decode("ascii"),
        "raw_payload": payload_value,
        "normalized_days": days,
        "safety": {
            "read_only": True,
            "market_db_written": False,
            "formal_paths_written": False,
            "historical_backfill_claimed": False,
            "formal_clock_created": False,
            "production_scheduler_allowed": False,
            "broker_order_allowed": False,
        },
    }
    body["content_sha256"] = payload_hash(body)
    return body


def write_twse_calendar_cache(
    path: Path,
    cache: Mapping[str, object],
    *,
    allowed_root: Path,
) -> str:
    """Create one immutable cache file under an explicit repository root."""

    resolved = path.expanduser().resolve()
    root = allowed_root.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise OfficialCalendarCacheError(
            "calendar cache output must be under the allowed repository output root"
        ) from error
    if not resolved.parent.exists() or not resolved.parent.is_dir():
        raise OfficialCalendarCacheError(
            "calendar cache output parent must already exist"
        )
    if not isinstance(cache, Mapping):
        raise OfficialCalendarCacheError("calendar cache must be an object")
    encoded = (canonical_json(dict(cache)) + "\n").encode("utf-8")
    try:
        with resolved.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            import os

            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise OfficialCalendarCacheError(
            "calendar cache output already exists; use a new immutable filename"
        ) from error
    return bytes_hash(encoded)


def build_twse_temporary_closure_cache(
    *,
    closure_date: date,
    raw_response: bytes,
    source_url: str,
    requested_at: datetime,
    captured_at: datetime,
    response_status: int,
    response_headers: Mapping[str, object] | None = None,
    response_url: str | None = None,
    publication_at: datetime | None = None,
    discovery_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """建立一筆由官方公告明確證明的臨時全面休市事件。

    年度 ``holidaySchedule`` 不包含 capture 後才公布的天然災害事件；這個
    sidecar 只接受 TWSE 官方公告 response，且原始 UTF-8 內容必須同時包含
    指定日期與正面的休市語句。政策頁或缺少日期的內容不能被當成事件。
    """

    _validate_calendar_date(closure_date)
    if not isinstance(raw_response, bytes) or not raw_response:
        raise OfficialCalendarCacheError("temporary closure response bytes are required")
    if len(raw_response) > MAX_CACHE_BYTES:
        raise OfficialCalendarCacheError(
            "temporary closure response exceeds cache limit"
        )
    if response_status != 200:
        raise OfficialCalendarCacheError(
            "temporary closure response status must be 200"
        )
    _validate_official_announcement_url(source_url)
    requested = _require_aware(requested_at, "requested_at")
    captured = _require_aware(captured_at, "captured_at")
    if captured < requested:
        raise OfficialCalendarCacheError(
            "captured_at cannot precede requested_at"
        )
    publication = None
    if publication_at is not None:
        publication = _require_aware(publication_at, "publication_at")
        if publication > captured:
            raise OfficialCalendarCacheError(
                "publication_at cannot follow captured_at"
            )
    final_url = source_url if response_url is None else str(response_url)
    _validate_official_announcement_url(final_url)
    if _url_identity(final_url) != _url_identity(source_url):
        raise OfficialCalendarCacheError(
            "temporary closure response URL does not match official announcement"
        )
    text = _temporary_closure_text(raw_response)
    _validate_temporary_closure_text(text, closure_date)
    source_hash = bytes_hash(raw_response)
    body: dict[str, object] = {
        "schema_version": OFFICIAL_TEMPORARY_CLOSURE_CACHE_SCHEMA_VERSION,
        "event": {
            "market": "TWSE",
            "closure_date": closure_date.isoformat(),
            "event_type": "temporary_full_market_closure",
            "status": "closed",
        },
        "capture_mode": "bounded_network",
        "network_enabled": True,
        "candidate_only": True,
        "source": {
            "provider": "TWSE",
            "request_url": source_url,
            "response_url": final_url,
            "http_status": response_status,
            "response_headers": _selected_headers(response_headers or {}),
            "response_sha256": source_hash,
            **(
                {}
                if discovery_evidence is None
                else {"discovery": dict(discovery_evidence)}
            ),
        },
        "requested_at_utc": requested.astimezone(timezone.utc).isoformat(),
        "captured_at_utc": captured.astimezone(timezone.utc).isoformat(),
        "available_at_utc": captured.astimezone(timezone.utc).isoformat(),
        "publication_at_utc": (
            None
            if publication is None
            else publication.astimezone(timezone.utc).isoformat()
        ),
        "raw_response_base64": base64.b64encode(raw_response).decode("ascii"),
        "scope": {
            "annual_schedule_override": True,
            "source_kind": "official_event_announcement",
            "policy_source": TWSE_TEMPORARY_CLOSURE_POLICY_URL,
        },
        "safety": {
            "read_only": True,
            "market_db_written": False,
            "formal_paths_written": False,
            "historical_backfill_claimed": False,
            "formal_clock_created": False,
            "production_scheduler_allowed": False,
            "broker_order_allowed": False,
        },
    }
    body["content_sha256"] = payload_hash(body)
    return body


def write_twse_temporary_closure_cache(
    path: Path,
    cache: Mapping[str, object],
    *,
    allowed_root: Path,
) -> str:
    """以 create-only 方式保存一筆官方臨時休市事件。"""

    return _write_immutable_cache_file(path, cache, allowed_root=allowed_root)


def load_verified_twse_temporary_closure_cache(
    path: Path,
    *,
    observed_at: datetime | None = None,
) -> VerifiedTemporaryClosureCache:
    """重新驗證臨時休市公告 bytes、日期、來源與 capture 時間。"""

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise OfficialCalendarCacheError(
            "temporary closure cache file is missing"
        )
    raw_file = resolved.read_bytes()
    if len(raw_file) > MAX_CACHE_BYTES:
        raise OfficialCalendarCacheError(
            "temporary closure cache file exceeds size limit"
        )
    try:
        value: object = json.loads(raw_file.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OfficialCalendarCacheError(
            "temporary closure cache JSON is invalid"
        ) from error
    if not isinstance(value, Mapping):
        raise OfficialCalendarCacheError(
            "temporary closure cache must be an object"
        )
    payload = dict(value)
    declared_content_hash = payload.pop("content_sha256", None)
    if not isinstance(declared_content_hash, str) or not _SHA256_RE.fullmatch(
        declared_content_hash
    ):
        raise OfficialCalendarCacheError(
            "temporary closure cache content hash is invalid"
        )
    if declared_content_hash != payload_hash(payload):
        raise OfficialCalendarCacheError(
            "temporary closure cache content hash mismatch"
        )
    if payload.get("schema_version") != (
        OFFICIAL_TEMPORARY_CLOSURE_CACHE_SCHEMA_VERSION
    ):
        raise OfficialCalendarCacheError(
            "temporary closure cache schema version is invalid"
        )
    if payload.get("capture_mode") != "bounded_network" or payload.get(
        "network_enabled"
    ) is not True:
        raise OfficialCalendarCacheError(
            "temporary closure cache must identify a bounded official capture"
        )
    event = payload.get("event")
    if not isinstance(event, Mapping) or event.get("market") != "TWSE":
        raise OfficialCalendarCacheError(
            "temporary closure cache event identity is invalid"
        )
    closure_date = _parse_calendar_date(event.get("closure_date"))
    if event.get("event_type") != "temporary_full_market_closure" or event.get(
        "status"
    ) != "closed":
        raise OfficialCalendarCacheError(
            "temporary closure cache event status is invalid"
        )
    source = payload.get("source")
    if not isinstance(source, Mapping) or source.get("provider") != "TWSE":
        raise OfficialCalendarCacheError(
            "temporary closure cache source metadata is missing"
        )
    source_url = source.get("request_url")
    response_url = source.get("response_url")
    if not isinstance(source_url, str) or not isinstance(response_url, str):
        raise OfficialCalendarCacheError(
            "temporary closure cache source URL is missing"
        )
    _validate_official_announcement_url(source_url)
    _validate_official_announcement_url(response_url)
    if _url_identity(source_url) != _url_identity(response_url):
        raise OfficialCalendarCacheError(
            "temporary closure cache response URL is invalid"
        )
    if source.get("http_status") != 200:
        raise OfficialCalendarCacheError(
            "temporary closure cache HTTP status is invalid"
        )
    source_hash = source.get("response_sha256")
    if not isinstance(source_hash, str) or not _SHA256_RE.fullmatch(source_hash):
        raise OfficialCalendarCacheError(
            "temporary closure cache response hash is invalid"
        )
    encoded_response = payload.get("raw_response_base64")
    if not isinstance(encoded_response, str) or not encoded_response:
        raise OfficialCalendarCacheError(
            "temporary closure cache raw response is missing"
        )
    try:
        raw_response = base64.b64decode(encoded_response, validate=True)
    except (ValueError, binascii.Error) as error:
        raise OfficialCalendarCacheError(
            "temporary closure cache raw response encoding is invalid"
        ) from error
    if bytes_hash(raw_response) != source_hash:
        raise OfficialCalendarCacheError(
            "temporary closure cache response hash mismatch"
        )
    text = _temporary_closure_text(raw_response)
    _validate_temporary_closure_text(text, closure_date)
    observed = _require_aware(
        observed_at if observed_at is not None else datetime.now(timezone.utc),
        "observed_at",
    )
    captured = _parse_timestamp(payload.get("captured_at_utc"), "captured_at_utc")
    requested = _parse_timestamp(payload.get("requested_at_utc"), "requested_at_utc")
    available = _parse_timestamp(payload.get("available_at_utc"), "available_at_utc")
    publication_value = payload.get("publication_at_utc")
    publication = (
        None
        if publication_value is None
        else _parse_timestamp(publication_value, "publication_at_utc")
    )
    if requested > captured or available != captured:
        raise OfficialCalendarCacheError(
            "temporary closure cache timestamp chain is invalid"
        )
    if publication is not None and publication > captured:
        raise OfficialCalendarCacheError(
            "temporary closure cache publication time follows capture"
        )
    if captured > observed:
        raise OfficialCalendarCacheError(
            "temporary closure cache capture is in the future"
        )
    discovery = source.get("discovery")
    if discovery is not None:
        _validate_news_discovery_evidence(
            discovery,
            closure_date=closure_date,
            detail_source_url=source_url,
            detail_requested_at=requested,
            observed_at=observed,
        )
    scope = payload.get("scope")
    if not isinstance(scope, Mapping) or scope.get(
        "annual_schedule_override"
    ) is not True or scope.get("source_kind") != "official_event_announcement":
        raise OfficialCalendarCacheError(
            "temporary closure cache scope is invalid"
        )
    return VerifiedTemporaryClosureCache(
        closure_date=closure_date,
        evidence={
            "mode": "hash_bound_official_temporary_closure",
            "path": str(resolved),
            "cache_file_sha256": bytes_hash(raw_file),
            "cache_content_sha256": declared_content_hash,
            "closure_date": closure_date.isoformat(),
            "source": dict(source),
            "source_hash": source_hash,
            "publication_at": (
                None if publication is None else publication.isoformat()
            ),
            "captured_at": captured.isoformat(),
            "available_at": available.isoformat(),
            "validated_at": observed.isoformat(),
            "annual_schedule_override": True,
        },
    )


def _write_immutable_cache_file(
    path: Path,
    cache: Mapping[str, object],
    *,
    allowed_root: Path,
) -> str:
    """在共同的受控 root 下建立不可覆寫的 JSON cache。"""

    resolved = path.expanduser().resolve()
    root = allowed_root.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise OfficialCalendarCacheError(
            "cache output must be under the allowed repository output root"
        ) from error
    if not resolved.parent.exists() or not resolved.parent.is_dir():
        raise OfficialCalendarCacheError("cache output parent must already exist")
    if not isinstance(cache, Mapping):
        raise OfficialCalendarCacheError("cache must be an object")
    encoded = (canonical_json(dict(cache)) + "\n").encode("utf-8")
    try:
        with resolved.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            import os

            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise OfficialCalendarCacheError(
            "cache output already exists; use a new immutable filename"
        ) from error
    return bytes_hash(encoded)


def refresh_twse_calendar_cache(
    *,
    calendar_year: int,
    cache_root: Path,
    allowed_root: Path,
    observed_at: datetime | None = None,
    now_provider: Callable[[], datetime] | None = None,
    request_fn: Callable[..., Any] | None = None,
    max_attempts: int = MAX_REFRESH_ATTEMPTS,
    max_age: timedelta = DEFAULT_CACHE_MAX_AGE,
) -> dict[str, object]:
    """Refresh one annual cache without deleting a previous observation.

    A valid cache is returned without a network request.  Once its seven-day
    freshness window expires, this function makes at most ``max_attempts``
    bounded requests and writes a new create-only file only after the whole
    response has been validated.  A failed refresh leaves every previous file
    in place and returns an observable blocked result for the caller.
    """

    _validate_year(calendar_year)
    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or max_attempts <= 0
        or max_attempts > MAX_REFRESH_ATTEMPTS
    ):
        raise OfficialCalendarCacheError(
            f"max_attempts must be between 1 and {MAX_REFRESH_ATTEMPTS}"
        )
    if not isinstance(max_age, timedelta) or max_age <= timedelta(0):
        raise OfficialCalendarCacheError("max_age must be greater than zero")

    resolved_root = cache_root.expanduser().resolve()
    resolved_allowed_root = allowed_root.expanduser().resolve()
    try:
        resolved_root.relative_to(resolved_allowed_root)
    except ValueError as error:
        raise OfficialCalendarCacheError(
            "calendar refresh root must be under the allowed repository root"
        ) from error
    if resolved_root == resolved_allowed_root:
        raise OfficialCalendarCacheError(
            "calendar refresh root must be a child of the allowed repository root"
        )
    if resolved_root.exists() and not resolved_root.is_dir():
        raise OfficialCalendarCacheError("calendar refresh root is not a directory")
    resolved_root.mkdir(parents=True, exist_ok=True)

    clock = now_provider or (lambda: datetime.now(timezone.utc))
    observed = _require_aware(
        observed_at if observed_at is not None else clock(),
        "observed_at",
    )
    candidates = _refresh_cache_candidates(resolved_root, calendar_year)
    previous: list[dict[str, object]] = []
    valid: list[VerifiedOfficialCalendarCache] = []
    for candidate in candidates:
        resolved_candidate = candidate.expanduser().resolve()
        try:
            resolved_candidate.relative_to(resolved_root)
        except ValueError:
            previous.append(
                {
                    "path": str(candidate),
                    "status": "invalid_or_expired",
                    "reason": (
                        "OfficialCalendarCacheError:cache candidate escaped root"
                    ),
                }
            )
            continue
        try:
            loaded = load_verified_twse_calendar_cache(
                resolved_candidate,
                calendar_year=calendar_year,
                observed_at=observed,
            )
        except OfficialCalendarCacheError as error:
            try:
                file_hash: str | None = bytes_hash(resolved_candidate.read_bytes())
            except OSError:
                file_hash = None
            previous.append(
                {
                    "path": str(resolved_candidate),
                    "file_sha256": file_hash,
                    "status": "invalid_or_expired",
                    "reason": f"{type(error).__name__}:{error}",
                }
            )
        else:
            valid.append(loaded)
    if valid:
        valid.sort(
            key=lambda item: str(item.evidence.get("captured_at", ""))
        )
        selected = valid[-1]
        return {
            "status": "cache_valid",
            "calendar_year": calendar_year,
            "refresh_attempted": False,
            "network_attempts": 0,
            "cache_path": selected.evidence.get("path"),
            "cache_file_sha256": selected.evidence.get("cache_file_sha256"),
            "cache_content_sha256": selected.evidence.get(
                "cache_content_sha256"
            ),
            "source_hash": selected.evidence.get("source_hash"),
            "captured_at": selected.evidence.get("captured_at"),
            "expires_at": selected.evidence.get("expires_at"),
            "retained_previous_cache": False,
        }

    if request_fn is None:
        request_fn = safe_request
    errors: list[str] = []
    attempts = 0
    for attempts in range(1, max_attempts + 1):
        requested_at = observed
        try:
            response = request_fn(
                TWSE_HOLIDAY_SCHEDULE_URL,
                params={"queryYear": str(calendar_year - 1911)},
                timeout_seconds=8,
                max_attempts=1,
            )
            raw_response = getattr(response, "content", None)
            if not isinstance(raw_response, bytes) or not raw_response:
                raise OfficialCalendarCacheError(
                    "official response did not expose non-empty response bytes"
                )
            captured_at = _require_aware(clock(), "captured_at")
            if captured_at < requested_at:
                raise OfficialCalendarCacheError(
                    "captured_at cannot precede requested_at"
                )
            response_url = getattr(response, "url", None)
            if not isinstance(response_url, str):
                response_url = None
            cache = build_twse_calendar_cache(
                calendar_year=calendar_year,
                raw_response=raw_response,
                requested_at=requested_at,
                captured_at=captured_at,
                response_status=int(getattr(response, "status_code", 0)),
                response_headers=getattr(response, "headers", {}),
                response_url=response_url,
                max_age=max_age,
            )
            path = _new_refresh_cache_path(resolved_root, calendar_year, captured_at)
            file_hash = write_twse_calendar_cache(
                path,
                cache,
                allowed_root=resolved_allowed_root,
            )
            verified = load_verified_twse_calendar_cache(
                path,
                calendar_year=calendar_year,
                observed_at=captured_at,
            )
            return {
                "status": "refreshed",
                "calendar_year": calendar_year,
                "refresh_attempted": True,
                "network_attempts": attempts,
                "cache_path": str(path),
                "cache_file_sha256": file_hash,
                "cache_content_sha256": verified.evidence.get(
                    "cache_content_sha256"
                ),
                "source_hash": verified.evidence.get("source_hash"),
                "captured_at": verified.evidence.get("captured_at"),
                "expires_at": verified.evidence.get("expires_at"),
                "retained_previous_cache": bool(previous),
                "previous_cache": previous,
            }
        except (OSError, RuntimeError, ValueError, OfficialCalendarCacheError) as error:
            errors.append(f"{type(error).__name__}:{str(error)[:240]}")

    return {
        "status": "refresh_blocked",
        "calendar_year": calendar_year,
        "refresh_attempted": True,
        "network_attempts": attempts,
        "reason": "official_calendar_cache_refresh_failed",
        "errors": errors,
        "retained_previous_cache": bool(previous),
        "previous_cache": previous,
    }


def refresh_twse_temporary_closure_events(
    *,
    calendar_year: int,
    cache_root: Path,
    allowed_root: Path,
    observed_at: datetime | None = None,
    now_provider: Callable[[], datetime] | None = None,
    request_fn: Callable[..., Any] | None = None,
    max_detail_requests: int = MAX_TEMPORARY_CLOSURE_DETAIL_REQUESTS,
) -> dict[str, object]:
    """由官方新聞清單自動發現並保存臨時全面休市公告。

    這個 producer 每次 operational run 只查一次官方「休市」新聞清單，
    並對清單中最多 ``max_detail_requests`` 筆明確的單日全面休市標題抓取
    官方明細。只有明細頁本身同時證明日期與全面休市語句時才建立 sidecar；
    年度假期公告、搜尋結果、行情報表與 policy page 都不會被當成事件。
    每個 sidecar 以公告 response bytes 綁定 hash，既有同 hash 檔案只讀重用，
    不覆寫或刪除舊檔。網路不可得時回傳 observable blocked，下一次 run 可
    再試，不把一次故障轉成永久人工處理。
    """

    _validate_year(calendar_year)
    if (
        isinstance(max_detail_requests, bool)
        or not isinstance(max_detail_requests, int)
        or max_detail_requests <= 0
        or max_detail_requests > MAX_TEMPORARY_CLOSURE_DETAIL_REQUESTS
    ):
        raise OfficialCalendarCacheError(
            "max_detail_requests must be between 1 and "
            f"{MAX_TEMPORARY_CLOSURE_DETAIL_REQUESTS}"
        )
    resolved_root = cache_root.expanduser().resolve()
    resolved_allowed_root = allowed_root.expanduser().resolve()
    try:
        resolved_root.relative_to(resolved_allowed_root)
    except ValueError as error:
        raise OfficialCalendarCacheError(
            "temporary closure refresh root must be under the allowed repository root"
        ) from error
    if resolved_root == resolved_allowed_root:
        raise OfficialCalendarCacheError(
            "temporary closure refresh root must be a child of the allowed repository root"
        )
    if resolved_root.exists() and not resolved_root.is_dir():
        raise OfficialCalendarCacheError(
            "temporary closure refresh root is not a directory"
        )
    resolved_root.mkdir(parents=True, exist_ok=True)

    clock = now_provider or (lambda: datetime.now(timezone.utc))
    observed = _require_aware(
        observed_at if observed_at is not None else clock(),
        "observed_at",
    )
    request = request_fn or safe_request
    list_requested_at = _require_aware(clock(), "requested_at")
    request_count = 0
    detail_count = 0
    errors: list[str] = []
    skipped: list[dict[str, object]] = []
    try:
        request_count += 1
        response = request(
            TWSE_NEWS_LIST_URL,
            params={"tag": "休市", "response": "json"},
            timeout_seconds=8,
            max_attempts=1,
        )
        raw_list = getattr(response, "content", None)
        if not isinstance(raw_list, bytes) or not raw_list:
            raise OfficialCalendarCacheError(
                "official TWSE news list did not expose response bytes"
            )
        list_captured_at = _require_aware(clock(), "captured_at")
        if list_captured_at < list_requested_at:
            raise OfficialCalendarCacheError(
                "news list capture cannot precede request"
            )
        if int(getattr(response, "status_code", 0)) != 200:
            raise OfficialCalendarCacheError(
                "official TWSE news list status must be 200"
            )
        list_response_url = getattr(response, "url", None)
        if not isinstance(list_response_url, str):
            raise OfficialCalendarCacheError(
                "official TWSE news list final URL is missing"
            )
        _validate_news_list_url(list_response_url)
        try:
            list_payload: object = json.loads(raw_list.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OfficialCalendarCacheError(
                "official TWSE news list response must be UTF-8 JSON"
            ) from error
        news_rows = _parse_twse_news_list(list_payload)
    except (OSError, RuntimeError, ValueError, OfficialCalendarCacheError) as error:
        return {
            "status": "temporary_closure_discovery_blocked",
            "calendar_year": calendar_year,
            "network_attempts": request_count,
            "detail_requests": detail_count,
            "reason": "official_temporary_closure_news_unavailable",
            "errors": [f"{type(error).__name__}:{str(error)[:240]}"],
            "events": [],
            "skipped": skipped,
        }

    discovery = {
        "provider": "TWSE",
        "endpoint": TWSE_NEWS_LIST_URL,
        "request_url": _news_list_request_url(),
        "response_url": list_response_url,
        "http_status": 200,
        "response_sha256": bytes_hash(raw_list),
        "raw_response_base64": base64.b64encode(raw_list).decode("ascii"),
        "requested_at_utc": list_requested_at.astimezone(timezone.utc).isoformat(),
        "captured_at_utc": list_captured_at.astimezone(timezone.utc).isoformat(),
        "tag": "休市",
    }
    events: list[dict[str, object]] = []
    candidate_rows = 0
    for row in news_rows:
        title = str(row.get("title", "")).strip()
        if not _is_single_day_closure_title(title):
            skipped.append(
                {
                    "title": title,
                    "reason": "not_explicit_single_day_full_closure_title",
                }
            )
            continue
        closure_date = _extract_closure_date(title, expected_year=calendar_year)
        if closure_date is None:
            skipped.append(
                {
                    "title": title,
                    "reason": "closure_title_date_not_in_requested_year",
                }
            )
            continue
        candidate_rows += 1
        if detail_count >= max_detail_requests:
            skipped.append(
                {
                    "title": title,
                    "closure_date": closure_date.isoformat(),
                    "reason": "detail_request_bound_reached",
                }
            )
            continue
        announcement_id = str(row.get("zh_id", "")).strip()
        if not re.fullmatch(r"[0-9a-fA-F]{32}", announcement_id):
            skipped.append(
                {
                    "title": title,
                    "closure_date": closure_date.isoformat(),
                    "reason": "official_news_id_invalid",
                }
            )
            continue
        detail_url = (
            f"{TWSE_NEWS_DETAIL_URL}?id={announcement_id.lower()}"
        )
        _validate_news_detail_url(
            detail_url,
            announcement_id=announcement_id,
        )
        detail_requested_at = _require_aware(clock(), "requested_at")
        try:
            detail_count += 1
            detail_response = request(
                detail_url,
                timeout_seconds=8,
                max_attempts=1,
            )
            raw_detail = getattr(detail_response, "content", None)
            if not isinstance(raw_detail, bytes) or not raw_detail:
                raise OfficialCalendarCacheError(
                    "official TWSE news detail did not expose response bytes"
                )
            detail_captured_at = _require_aware(clock(), "captured_at")
            if detail_captured_at < detail_requested_at:
                raise OfficialCalendarCacheError(
                    "news detail capture cannot precede request"
                )
            if int(getattr(detail_response, "status_code", 0)) != 200:
                raise OfficialCalendarCacheError(
                    "official TWSE news detail status must be 200"
                )
            detail_response_url = getattr(detail_response, "url", None)
            if not isinstance(detail_response_url, str):
                raise OfficialCalendarCacheError(
                    "official TWSE news detail final URL is missing"
                )
            if _url_identity(detail_response_url) != _url_identity(detail_url):
                raise OfficialCalendarCacheError(
                    "official TWSE news detail final URL does not match announcement"
                )
            publication_at = _parse_twse_news_publication_at(raw_detail)
            event_cache = build_twse_temporary_closure_cache(
                closure_date=closure_date,
                raw_response=raw_detail,
                source_url=detail_url,
                requested_at=detail_requested_at,
                captured_at=detail_captured_at,
                response_status=int(getattr(detail_response, "status_code", 0)),
                response_headers=getattr(detail_response, "headers", {}),
                response_url=detail_response_url,
                publication_at=publication_at,
                discovery_evidence={
                    **discovery,
                    "announcement_id": announcement_id.lower(),
                    "title": title,
                    "closure_date": closure_date.isoformat(),
                },
            )
            source = event_cache.get("source")
            if not isinstance(source, Mapping):
                raise OfficialCalendarCacheError(
                    "temporary closure event source metadata is missing"
                )
            source_hash = source.get("response_sha256")
            if not isinstance(source_hash, str):
                raise OfficialCalendarCacheError(
                    "temporary closure event source hash is missing"
                )
            event_path = _temporary_closure_event_path(
                resolved_root,
                closure_date=closure_date,
                source_hash=source_hash,
            )
            if event_path.exists():
                existing = load_verified_twse_temporary_closure_cache(
                    event_path,
                    observed_at=observed,
                )
                if existing.evidence.get("source_hash") != source_hash:
                    raise OfficialCalendarCacheError(
                        "existing temporary closure event has a different source hash"
                    )
                events.append(
                    {
                        "closure_date": closure_date.isoformat(),
                        "status": "existing_verified",
                        "path": str(event_path),
                        "file_sha256": existing.evidence.get("cache_file_sha256"),
                        "source_hash": source_hash,
                    }
                )
            else:
                file_hash = write_twse_temporary_closure_cache(
                    event_path,
                    event_cache,
                    allowed_root=resolved_allowed_root,
                )
                verified = load_verified_twse_temporary_closure_cache(
                    event_path,
                    # ``observed_at`` belongs to the run start.  A network
                    # response can finish moments later; its own completion
                    # timestamp is the first valid as-of time for this new
                    # immutable sidecar.
                    observed_at=max(observed, detail_captured_at),
                )
                events.append(
                    {
                        "closure_date": closure_date.isoformat(),
                        "status": "captured",
                        "path": str(event_path),
                        "file_sha256": file_hash,
                        "cache_content_sha256": verified.evidence.get(
                            "cache_content_sha256"
                        ),
                        "source_hash": source_hash,
                        "captured_at": verified.evidence.get("captured_at"),
                    }
                )
        except (OSError, RuntimeError, ValueError, OfficialCalendarCacheError) as error:
            errors.append(
                f"{closure_date.isoformat()}:{type(error).__name__}:{str(error)[:240]}"
            )

    status = "temporary_closure_events_updated" if events else (
        "temporary_closure_events_not_found"
        if not errors
        else "temporary_closure_events_partial"
    )
    return {
        "status": status,
        "calendar_year": calendar_year,
        "network_attempts": request_count + detail_count,
        "news_list_requests": request_count,
        "detail_requests": detail_count,
        "candidate_rows": candidate_rows,
        "discovery": {
            key: value
            for key, value in discovery.items()
            if key != "raw_response_base64"
        },
        "events": events,
        "skipped": skipped,
        "errors": errors,
    }


def _refresh_cache_candidates(root: Path, calendar_year: int) -> tuple[Path, ...]:
    """列出 refresh 可觀察的同年度 immutable cache 檔案。"""

    candidates = list(
        root.glob(f"twse_holiday_schedule_{calendar_year}_*.json")
    )
    exact = root / f"twse_holiday_schedule_{calendar_year}.json"
    if exact.exists():
        candidates.append(exact)
    return tuple(sorted(set(candidates)))


def _new_refresh_cache_path(
    root: Path,
    calendar_year: int,
    captured_at: datetime,
) -> Path:
    """以實際 response completion time 建立 create-only cache 檔名。"""

    stamp = captured_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    stem = f"twse_holiday_schedule_{calendar_year}_{stamp}"
    for suffix in range(100):
        path = root / f"{stem}{'' if suffix == 0 else f'_{suffix}'}.json"
        if not path.exists():
            return path
    raise OfficialCalendarCacheError("calendar refresh filename collision")


def load_verified_twse_calendar_cache(
    path: Path,
    *,
    calendar_year: int,
    observed_at: datetime | None = None,
) -> VerifiedOfficialCalendarCache:
    """Load and revalidate one cache, including raw bytes and all days."""

    _validate_year(calendar_year)
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise OfficialCalendarCacheError("calendar cache file is missing")
    raw_file = resolved.read_bytes()
    if len(raw_file) > MAX_CACHE_BYTES:
        raise OfficialCalendarCacheError("calendar cache file exceeds size limit")
    try:
        value: object = json.loads(raw_file.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OfficialCalendarCacheError("calendar cache JSON is invalid") from error
    if not isinstance(value, Mapping):
        raise OfficialCalendarCacheError("calendar cache must be an object")
    payload = dict(value)
    declared_content_hash = payload.pop("content_sha256", None)
    if not isinstance(declared_content_hash, str) or not _SHA256_RE.fullmatch(
        declared_content_hash
    ):
        raise OfficialCalendarCacheError("calendar cache content hash is invalid")
    if declared_content_hash != payload_hash(payload):
        raise OfficialCalendarCacheError("calendar cache content hash mismatch")
    if payload.get("schema_version") != OFFICIAL_CALENDAR_CACHE_SCHEMA_VERSION:
        raise OfficialCalendarCacheError("calendar cache schema version is invalid")
    if payload.get("calendar_year") != calendar_year:
        raise OfficialCalendarCacheError("calendar cache year mismatch")
    if payload.get("capture_mode") != "bounded_network" or payload.get(
        "network_enabled"
    ) is not True:
        raise OfficialCalendarCacheError(
            "calendar cache must identify a bounded official network capture"
        )

    source = payload.get("source")
    if not isinstance(source, Mapping):
        raise OfficialCalendarCacheError("calendar cache source metadata is missing")
    if source.get("provider") != "TWSE" or source.get(
        "endpoint"
    ) != TWSE_HOLIDAY_SCHEDULE_URL:
        raise OfficialCalendarCacheError("calendar cache source endpoint is invalid")
    expected_params = {"queryYear": str(calendar_year - 1911)}
    if source.get("request_params") != expected_params:
        raise OfficialCalendarCacheError("calendar cache query year is invalid")
    expected_url = TWSE_HOLIDAY_SCHEDULE_URL + "?" + urlencode(expected_params)
    if source.get("request_url") != expected_url:
        raise OfficialCalendarCacheError("calendar cache request URL is invalid")
    response_url = source.get("response_url")
    if response_url is not None and response_url != expected_url:
        raise OfficialCalendarCacheError(
            "calendar cache response URL is invalid"
        )
    if source.get("http_status") != 200:
        raise OfficialCalendarCacheError("calendar cache HTTP status is invalid")
    source_hash = source.get("response_sha256")
    if not isinstance(source_hash, str) or not _SHA256_RE.fullmatch(source_hash):
        raise OfficialCalendarCacheError("calendar cache response hash is invalid")

    encoded_response = payload.get("raw_response_base64")
    if not isinstance(encoded_response, str) or not encoded_response:
        raise OfficialCalendarCacheError("calendar cache raw response is missing")
    try:
        raw_response = base64.b64decode(encoded_response, validate=True)
    except (ValueError, binascii.Error) as error:
        raise OfficialCalendarCacheError(
            "calendar cache raw response encoding is invalid"
        ) from error
    if bytes_hash(raw_response) != source_hash:
        raise OfficialCalendarCacheError("calendar cache response hash mismatch")
    try:
        raw_payload: object = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OfficialCalendarCacheError(
            "calendar cache raw response is not valid UTF-8 JSON"
        ) from error
    if raw_payload != payload.get("raw_payload"):
        raise OfficialCalendarCacheError("calendar cache raw payload mismatch")
    schedule = parse_twse_annual_schedule(
        raw_payload,
        expected_year=calendar_year,
    )

    coverage = payload.get("coverage")
    if not isinstance(coverage, Mapping):
        raise OfficialCalendarCacheError("calendar cache coverage is missing")
    expected_day_count = (
        date(calendar_year + 1, 1, 1) - date(calendar_year, 1, 1)
    ).days
    expected_coverage = {
        "calendar_year": calendar_year,
        "start_date": date(calendar_year, 1, 1).isoformat(),
        "end_date": date(calendar_year, 12, 31).isoformat(),
        "day_count": expected_day_count,
        "complete_year": True,
        "annual_schedule_scope": "planned_annual_closures",
        "temporary_closure_coverage": "not_covered",
        "temporary_closure_policy_source": {
            "provider": "TWSE",
            "url": TWSE_TEMPORARY_CLOSURE_POLICY_URL,
            "source_kind": "official_policy_only",
            "event_evidence_required": True,
        },
        "interpretation": (
            "TWSE annual holidaySchedule closure rows; weekday absence is open "
            "only after the complete annual response is hash-verified; "
            "temporary natural-disaster closures require separate official "
            "event evidence"
        ),
    }
    legacy_coverage = {
        "calendar_year": calendar_year,
        "start_date": date(calendar_year, 1, 1).isoformat(),
        "end_date": date(calendar_year, 12, 31).isoformat(),
        "day_count": expected_day_count,
        "complete_year": True,
        "interpretation": (
            "TWSE annual holidaySchedule closure rows; weekday absence is open "
            "only after the complete annual response is hash-verified"
        ),
    }
    coverage_dict = dict(coverage)
    if coverage_dict != expected_coverage and coverage_dict != legacy_coverage:
        raise OfficialCalendarCacheError("calendar cache coverage is incomplete")

    normalized_days = payload.get("normalized_days")
    if not isinstance(normalized_days, list) or len(normalized_days) != expected_day_count:
        raise OfficialCalendarCacheError(
            "calendar cache normalized days do not cover the full year"
        )
    current = date(calendar_year, 1, 1)
    for index, raw_day in enumerate(normalized_days):
        if not isinstance(raw_day, Mapping):
            raise OfficialCalendarCacheError(
                f"calendar cache normalized day {index} is invalid"
            )
        date_text = raw_day.get("date")
        if date_text != current.isoformat():
            raise OfficialCalendarCacheError(
                f"calendar cache normalized date {index} is not contiguous"
            )
        is_trading_day = raw_day.get("is_trading_day")
        if not isinstance(is_trading_day, bool):
            raise OfficialCalendarCacheError(
                f"calendar cache normalized day {index} flag is invalid"
            )
        if raw_day.get("source_hash") != source_hash:
            raise OfficialCalendarCacheError(
                f"calendar cache normalized day {index} source hash mismatch"
            )
        expected_flag = _normalized_flag(current, schedule)
        if is_trading_day != expected_flag:
            raise OfficialCalendarCacheError(
                f"calendar cache normalized day {index} value mismatch"
            )
        current += timedelta(days=1)

    observed = _require_aware(
        observed_at if observed_at is not None else datetime.now(timezone.utc),
        "observed_at",
    )
    captured = _parse_timestamp(payload.get("captured_at_utc"), "captured_at_utc")
    requested = _parse_timestamp(payload.get("requested_at_utc"), "requested_at_utc")
    available = _parse_timestamp(payload.get("available_at_utc"), "available_at_utc")
    expires = _parse_timestamp(payload.get("expires_at_utc"), "expires_at_utc")
    if requested > captured or available != captured or expires <= captured:
        raise OfficialCalendarCacheError("calendar cache timestamp chain is invalid")
    if captured > observed:
        raise OfficialCalendarCacheError("calendar cache capture is in the future")
    if observed >= expires:
        raise OfficialCalendarCacheExpired("calendar cache freshness window expired")
    max_age_seconds = payload.get("max_age_seconds")
    if (
        isinstance(max_age_seconds, bool)
        or not isinstance(max_age_seconds, int)
        or max_age_seconds <= 0
        or expires != captured + timedelta(seconds=max_age_seconds)
    ):
        raise OfficialCalendarCacheError("calendar cache max age is invalid")

    return VerifiedOfficialCalendarCache(
        calendar_year=calendar_year,
        # The resolver needs the source closure rows so a weekday absent from
        # the annual holiday response remains distinguishable from an
        # explicitly listed closed day.  normalized_days above still validates
        # the complete year independently.
        schedule=schedule,
        evidence={
            "mode": "hash_bound_official_calendar_cache",
            "path": str(resolved),
            "cache_file_sha256": bytes_hash(raw_file),
            "cache_content_sha256": declared_content_hash,
            "source": dict(source),
            "source_hash": source_hash,
            "calendar_year": calendar_year,
            "coverage": dict(coverage),
            "annual_schedule_scope": coverage_dict.get(
                "annual_schedule_scope",
                "planned_annual_closures",
            ),
            "temporary_closure_scope": (
                coverage_dict.get(
                    "temporary_closure_policy_source",
                    {
                        "provider": "TWSE",
                        "url": TWSE_TEMPORARY_CLOSURE_POLICY_URL,
                        "source_kind": "official_policy_only",
                        "event_evidence_required": True,
                    },
                )
            ),
            "captured_at": captured.isoformat(),
            "available_at": available.isoformat(),
            "expires_at": expires.isoformat(),
            "validated_at": observed.isoformat(),
        },
    )


def parse_twse_annual_schedule(
    payload: object,
    *,
    expected_year: int,
) -> dict[date, bool]:
    """Parse and validate the annual TWSE holiday schedule payload."""

    _validate_year(expected_year)
    if not isinstance(payload, list) or not payload:
        raise OfficialCalendarCacheError(
            "TWSE holidaySchedule payload must be a non-empty array"
        )
    schedule: dict[date, bool] = {}
    parsed_year: int | None = None
    for index, raw_row in enumerate(payload):
        if not isinstance(raw_row, Mapping) or "Date" not in raw_row:
            raise OfficialCalendarCacheError(
                f"TWSE holidaySchedule row {index} lacks Date"
            )
        row_date = _parse_roc_date(raw_row["Date"], index=index)
        if parsed_year is None:
            parsed_year = row_date.year
        elif row_date.year != parsed_year:
            raise OfficialCalendarCacheError(
                "TWSE holidaySchedule contains multiple years"
            )
        description = " ".join(
            str(raw_row.get(field, ""))
            for field in ("Name", "Description")
        )
        schedule[row_date] = schedule.get(row_date, False) or any(
            marker in description for marker in _OPEN_MARKERS
        )
    if parsed_year != expected_year:
        raise OfficialCalendarCacheError(
            f"TWSE holidaySchedule year mismatch: {parsed_year} != {expected_year}"
        )
    return schedule


def _normalized_flag(target: date, schedule: Mapping[date, bool]) -> bool:
    if target.weekday() >= 5:
        return False
    return schedule.get(target, True)


def _selected_headers(headers: Mapping[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    wanted = {"content-type", "etag", "last-modified", "date", "content-length"}
    for key, value in headers.items():
        normalized_key = str(key).casefold()
        if normalized_key in wanted:
            result[normalized_key] = str(value)
    return dict(sorted(result.items()))


def _news_list_request_url() -> str:
    """回傳公告清單請求的 canonical URL。"""

    return TWSE_NEWS_LIST_URL + "?" + urlencode(
        {"tag": "休市", "response": "json"}
    )


def _validate_news_list_url(value: str) -> None:
    """確認公告清單的 final URL 仍是指定 TWSE JSON endpoint。"""

    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise OfficialCalendarCacheError(
            "TWSE news list URL port is invalid"
        ) from error
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _OFFICIAL_ANNOUNCEMENT_HOSTS
        or port not in (None, 443)
        or parsed.path != "/rwd/zh/news/newsList"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise OfficialCalendarCacheError(
            "official TWSE news list final URL is invalid"
        )
    query = parse_qsl(parsed.query, keep_blank_values=True)
    expected = [("tag", "休市"), ("response", "json")]
    if sorted(query) != sorted(expected):
        raise OfficialCalendarCacheError(
            "official TWSE news list query is invalid"
        )


def _validate_news_detail_url(value: str, *, announcement_id: str) -> None:
    """確認公告明細 response 綁定同一筆 TWSE API 公告。"""

    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise OfficialCalendarCacheError(
            "TWSE news detail URL port is invalid"
        ) from error
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _OFFICIAL_ANNOUNCEMENT_HOSTS
        or port not in (None, 443)
        or parsed.path != "/rwd/zh/news/newsDetail"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise OfficialCalendarCacheError(
            "official TWSE news detail URL is invalid"
        )
    if not re.fullmatch(r"[0-9a-fA-F]{32}", announcement_id):
        raise OfficialCalendarCacheError(
            "official TWSE news detail announcement ID is invalid"
        )
    if parse_qsl(parsed.query, keep_blank_values=True) != [
        ("id", announcement_id.lower())
    ]:
        raise OfficialCalendarCacheError(
            "official TWSE news detail query is invalid"
        )


def _parse_twse_news_list(payload: object) -> list[dict[str, object]]:
    """解析 TWSE newsList 的欄位／資料陣列，不接受未標示欄位的猜測資料。"""

    if not isinstance(payload, Mapping):
        raise OfficialCalendarCacheError(
            "official TWSE news list must be a JSON object"
        )
    status = payload.get("stat", payload.get("status"))
    if not isinstance(status, str) or status.casefold() != "ok":
        raise OfficialCalendarCacheError(
            "official TWSE news list status is not OK"
        )
    fields_value = payload.get("fields")
    rows_value = payload.get("data")
    if not isinstance(fields_value, list) or not isinstance(rows_value, list):
        raise OfficialCalendarCacheError(
            "official TWSE news list fields/data are missing"
        )
    fields = [str(field).strip() for field in fields_value]
    title_index = _field_index(
        fields,
        {"標題", "新聞標題", "title", "Title"},
    )
    id_index = _field_index(
        fields,
        {"zhId", "zhid", "中文ID", "公告編號", "id", "ID"},
    )
    if title_index is None:
        raise OfficialCalendarCacheError(
            "official TWSE news list title field is missing"
        )
    parsed_rows: list[dict[str, object]] = []
    for index, raw_row in enumerate(rows_value):
        if isinstance(raw_row, Mapping):
            title_value = _mapping_field(
                raw_row,
                {"標題", "新聞標題", "title", "Title"},
            )
            id_value = _mapping_field(
                raw_row,
                {"zhId", "zhid", "中文ID", "公告編號", "id", "ID"},
            )
        elif isinstance(raw_row, list):
            title_value = (
                raw_row[title_index]
                if title_index < len(raw_row)
                else None
            )
            id_value = (
                raw_row[id_index]
                if id_index is not None and id_index < len(raw_row)
                else _find_news_id(raw_row)
            )
        else:
            raise OfficialCalendarCacheError(
                f"official TWSE news list row {index} is invalid"
            )
        parsed_rows.append(
            {
                "title": (
                    title_value.strip()
                    if isinstance(title_value, str)
                    else ""
                ),
                "zh_id": (
                    id_value.strip()
                    if isinstance(id_value, str)
                    else ""
                ),
            }
        )
    return parsed_rows


def _field_index(fields: list[str], names: set[str]) -> int | None:
    folded = {name.casefold() for name in names}
    for index, field in enumerate(fields):
        if field.casefold() in folded:
            return index
    return None


def _mapping_field(value: Mapping[object, object], names: set[str]) -> object:
    folded = {name.casefold() for name in names}
    for key, item in value.items():
        if str(key).strip().casefold() in folded:
            return item
    return None


def _find_news_id(row: list[object]) -> object:
    for item in row:
        if isinstance(item, str) and re.fullmatch(r"[0-9a-fA-F]{32}", item.strip()):
            return item
    return None


def _is_single_day_closure_title(title: str) -> bool:
    """只接受標題明示單日全面休市，排除年度或否定公告。"""

    normalized = " ".join(title.split())
    if not normalized or any(
        marker in normalized for marker in _TEMPORARY_CLOSURE_NEGATIVE_MARKERS
    ):
        return False
    if "休市" not in normalized or "市場" not in normalized:
        return False
    return any(
        marker in normalized
        for marker in ("休市一天", "休市一日", "休市1天", "休市1日", "全日休市")
    )


_NEWS_ROC_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>\d{3})\s*年\s*"
    r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日"
)
_NEWS_GREGORIAN_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>20\d{2})[-/]"
    r"(?P<month>\d{1,2})[-/](?P<day>\d{1,2})(?!\d)"
)


def _extract_closure_date(title: str, *, expected_year: int) -> date | None:
    """從單日公告標題提取唯一日期，避免從日期區間猜取第一日。"""

    candidates: list[date] = []
    for match in _NEWS_ROC_DATE_RE.finditer(title):
        try:
            candidates.append(
                date(
                    int(match.group("year")) + 1911,
                    int(match.group("month")),
                    int(match.group("day")),
                )
            )
        except ValueError:
            continue
    for match in _NEWS_GREGORIAN_DATE_RE.finditer(title):
        try:
            candidates.append(
                date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
            )
        except ValueError:
            continue
    unique = list(dict.fromkeys(candidates))
    if len(unique) != 1 or unique[0].year != expected_year:
        return None
    return unique[0]


_NEWS_PUBLICATION_RE = re.compile(
    r"發布日期\s*[︰:：]?\s*(?:民國\s*)?"
    r"(?P<year>\d{3})\s*年\s*(?P<month>\d{1,2})\s*月\s*"
    r"(?P<day>\d{1,2})\s*日(?:\s+|[Tt])"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})"
    r"(?::(?P<second>\d{2}))?"
)


def _parse_twse_news_publication_at(raw_response: bytes) -> datetime | None:
    """從官方明細頁保留發布時間；缺少時使用 response completion time。"""

    try:
        payload: object = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, Mapping):
        date_value = payload.get("date")
        if isinstance(date_value, str):
            compact = re.sub(r"\D", "", date_value)
            if len(compact) in (12, 14):
                try:
                    return datetime(
                        int(compact[0:4]),
                        int(compact[4:6]),
                        int(compact[6:8]),
                        int(compact[8:10]),
                        int(compact[10:12]),
                        int(compact[12:14] or 0)
                        if len(compact) == 14
                        else 0,
                        tzinfo=_TAIPEI_TIMEZONE,
                    )
                except ValueError as error:
                    raise OfficialCalendarCacheError(
                        "official TWSE news publication timestamp is invalid"
                    ) from error
    text = _temporary_closure_text(raw_response)
    match = _NEWS_PUBLICATION_RE.search(text)
    if match is None:
        return None
    try:
        return datetime(
            int(match.group("year")) + 1911,
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            int(match.group("second") or 0),
            tzinfo=_TAIPEI_TIMEZONE,
        )
    except ValueError as error:
        raise OfficialCalendarCacheError(
            "official TWSE news publication timestamp is invalid"
        ) from error


def _temporary_closure_event_path(
    root: Path,
    *,
    closure_date: date,
    source_hash: str,
) -> Path:
    """依事件日期與 response hash 建立不覆寫的 sidecar 路徑。"""

    if not _SHA256_RE.fullmatch(source_hash):
        raise OfficialCalendarCacheError(
            "temporary closure event source hash is invalid"
        )
    path = root / (
        f"twse_temporary_closure_{closure_date:%Y%m%d}_"
        f"{source_hash.split(':', 1)[1][:16]}.json"
    )
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise OfficialCalendarCacheError(
            "temporary closure event path escaped cache root"
        ) from error
    return path


def _validate_news_discovery_evidence(
    value: object,
    *,
    closure_date: date,
    detail_source_url: str,
    detail_requested_at: datetime,
    observed_at: datetime,
) -> None:
    """驗證 sidecar 所引用的新聞清單 bytes 與明細事件確實相符。"""

    if not isinstance(value, Mapping):
        raise OfficialCalendarCacheError(
            "temporary closure discovery evidence is invalid"
        )
    if value.get("provider") != "TWSE" or value.get("endpoint") != TWSE_NEWS_LIST_URL:
        raise OfficialCalendarCacheError(
            "temporary closure discovery provider is invalid"
        )
    request_url = value.get("request_url")
    response_url = value.get("response_url")
    if request_url != _news_list_request_url() or not isinstance(response_url, str):
        raise OfficialCalendarCacheError(
            "temporary closure discovery URL is invalid"
        )
    _validate_news_list_url(response_url)
    if value.get("http_status") != 200 or value.get("tag") != "休市":
        raise OfficialCalendarCacheError(
            "temporary closure discovery HTTP metadata is invalid"
        )
    source_hash = value.get("response_sha256")
    if not isinstance(source_hash, str) or not _SHA256_RE.fullmatch(source_hash):
        raise OfficialCalendarCacheError(
            "temporary closure discovery response hash is invalid"
        )
    encoded = value.get("raw_response_base64")
    if not isinstance(encoded, str) or not encoded:
        raise OfficialCalendarCacheError(
            "temporary closure discovery raw response is missing"
        )
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise OfficialCalendarCacheError(
            "temporary closure discovery raw response encoding is invalid"
        ) from error
    if bytes_hash(raw) != source_hash:
        raise OfficialCalendarCacheError(
            "temporary closure discovery response hash mismatch"
        )
    try:
        payload: object = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OfficialCalendarCacheError(
            "temporary closure discovery response is not UTF-8 JSON"
        ) from error
    rows = _parse_twse_news_list(payload)
    announcement_id = value.get("announcement_id")
    title = value.get("title")
    declared_date = value.get("closure_date")
    if (
        not isinstance(announcement_id, str)
        or not re.fullmatch(r"[0-9a-fA-F]{32}", announcement_id)
        or not isinstance(title, str)
        or declared_date != closure_date.isoformat()
    ):
        raise OfficialCalendarCacheError(
            "temporary closure discovery event identity is invalid"
        )
    _validate_news_detail_url(
        detail_source_url,
        announcement_id=announcement_id,
    )
    matches = [
        row
        for row in rows
        if str(row.get("zh_id", "")).casefold() == announcement_id.casefold()
    ]
    if len(matches) != 1 or matches[0].get("title") != title:
        raise OfficialCalendarCacheError(
            "temporary closure discovery row does not match event"
        )
    matched_title = str(matches[0].get("title", ""))
    if not _is_single_day_closure_title(matched_title):
        raise OfficialCalendarCacheError(
            "temporary closure discovery row is not a single-day closure"
        )
    if _extract_closure_date(matched_title, expected_year=closure_date.year) != closure_date:
        raise OfficialCalendarCacheError(
            "temporary closure discovery row date does not match event"
        )
    requested = _parse_timestamp(
        value.get("requested_at_utc"),
        "temporary closure discovery requested_at_utc",
    )
    captured = _parse_timestamp(
        value.get("captured_at_utc"),
        "temporary closure discovery captured_at_utc",
    )
    if requested > captured or captured > detail_requested_at or captured > observed_at:
        raise OfficialCalendarCacheError(
            "temporary closure discovery timestamp chain is invalid"
        )


def _validate_calendar_date(value: object) -> None:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise OfficialCalendarCacheError("calendar event date must be a date")


def _parse_calendar_date(value: object) -> date:
    if not isinstance(value, str) or not value:
        raise OfficialCalendarCacheError("calendar event date is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise OfficialCalendarCacheError("calendar event date is invalid") from error
    if parsed.isoformat() != value:
        raise OfficialCalendarCacheError("calendar event date is not canonical")
    return parsed


def _validate_official_announcement_url(value: str) -> None:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise OfficialCalendarCacheError(
            "temporary closure source URL port is invalid"
        ) from error
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _OFFICIAL_ANNOUNCEMENT_HOSTS
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise OfficialCalendarCacheError(
            "temporary closure source must be a TWSE HTTPS announcement"
        )
    if not parsed.path.startswith(
        (
            "/staticFiles/news/",
            "/zh/announcement/announcement/",
            "/announcement/",
            "/zh/about/news/news/",
            "/rwd/zh/news/newsDetail",
        )
    ):
        raise OfficialCalendarCacheError(
            "temporary closure source path is not a TWSE announcement"
        )


def _url_identity(value: str) -> tuple[str, str, str, str]:
    parsed = urlparse(value)
    return (
        parsed.scheme.casefold(),
        (parsed.hostname or "").casefold(),
        parsed.path,
        parsed.query,
    )


def _temporary_closure_text(raw_response: bytes) -> str:
    try:
        text = raw_response.decode("utf-8")
    except UnicodeDecodeError as error:
        raise OfficialCalendarCacheError(
            "temporary closure announcement must be UTF-8 text or JSON"
        ) from error
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def _validate_temporary_closure_text(text: str, closure_date: date) -> None:
    roc_date = f"{closure_date.year - 1911:03d}年{closure_date.month}月{closure_date.day}日"
    roc_slash = f"{closure_date.year - 1911:03d}/{closure_date.month:02d}/{closure_date.day:02d}"
    gregorian = closure_date.isoformat()
    compacted = re.sub(r"\s+", "", text)
    if not any(
        token in text or token in compacted
        for token in (gregorian, roc_date, roc_slash)
    ):
        raise OfficialCalendarCacheError(
            "temporary closure announcement does not mention the closure date"
        )
    if any(marker in text for marker in _TEMPORARY_CLOSURE_NEGATIVE_MARKERS):
        raise OfficialCalendarCacheError(
            "temporary closure announcement contains a non-closure statement"
        )
    if not any(marker in text for marker in _TEMPORARY_CLOSURE_MARKERS):
        raise OfficialCalendarCacheError(
            "temporary closure announcement lacks an explicit market-closure statement"
        )


def _parse_roc_date(value: object, *, index: int) -> date:
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 7:
        raise OfficialCalendarCacheError(
            f"TWSE holidaySchedule row {index} Date must be 7 ROC digits"
        )
    try:
        return date(
            int(digits[:3]) + 1911,
            int(digits[3:5]),
            int(digits[5:7]),
        )
    except ValueError as error:
        raise OfficialCalendarCacheError(
            f"TWSE holidaySchedule row {index} Date is invalid"
        ) from error


def _parse_timestamp(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise OfficialCalendarCacheError(f"{field_name} must be timezone-aware")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise OfficialCalendarCacheError(f"{field_name} is invalid") from error
    return _require_aware(parsed, field_name)


def _require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise OfficialCalendarCacheError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfficialCalendarCacheError(f"{field_name} must include timezone")
    return value


def _validate_year(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 2000 <= value <= 2200:
        raise OfficialCalendarCacheError("calendar_year must be an integer between 2000 and 2200")
