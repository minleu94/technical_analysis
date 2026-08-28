"""Build a candidate-only TWSE/TPEX official trading-calendar bundle.

This module is deliberately separate from the prospective clock planner.  It
normalizes already captured official responses (or a small, explicitly
confirmed network capture) into the planner's ``official-trading-calendar-
bundle.v1`` shape.  It never creates a clock, changes a controlled path, or
writes market data.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Callable

from data_module.official_phase3c_fetcher import safe_request
from data_module.prospective_formal_clock import payload_hash


OFFICIAL_CALENDAR_BUNDLE_SCHEMA_VERSION = "official-trading-calendar-bundle.v1"
TWSE_HOLIDAY_SCHEDULE_URL = (
    "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
)
TPEX_MARKET_CALENDAR_URL = "https://info.tpex.org.tw/api/mktCalendar"
MAX_CAPTURE_DAYS = 93
MAX_FIXTURE_BYTES = 4 * 1024 * 1024
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPEN_MARKERS = ("開始交易", "最後交易", "恢復交易", "照常交易")
_DATE_KEY_PATTERN = re.compile(r"^\d{8}$")


class OfficialCalendarBundleError(ValueError):
    """Official calendar input is malformed or insufficient for a bundle."""


@dataclass(frozen=True)
class CapturedCalendarResponse:
    """One immutable raw response and its provenance fingerprint."""

    kind: str
    key: str
    source: str
    source_hash: str
    payload: object

    def __post_init__(self) -> None:
        if self.kind not in {"twse", "tpex"}:
            raise OfficialCalendarBundleError("response kind must be twse or tpex")
        if not self.key.strip():
            raise OfficialCalendarBundleError("response key must be non-empty")
        if not self.source.strip():
            raise OfficialCalendarBundleError("response source must be non-empty")
        if SHA256_PATTERN.fullmatch(self.source_hash) is None:
            raise OfficialCalendarBundleError(
                "response source_hash must be sha256: plus 64 lowercase hex"
            )


def hash_response_bytes(raw: bytes) -> str:
    """Return the evidence hash for the bytes actually captured."""

    return "sha256:" + hashlib.sha256(raw).hexdigest()


def build_official_calendar_bundle(
    *,
    start_date: date,
    end_date: date,
    twse_responses: Mapping[int, CapturedCalendarResponse],
    tpex_responses: Mapping[str, CapturedCalendarResponse],
    capture_mode: str = "fixture_only",
    network_enabled: bool = False,
    captured_at: datetime | None = None,
) -> dict[str, object]:
    """Normalize captured annual/monthly responses into a planner bundle.

    TWSE's annual endpoint lists holidays, so a weekday absent from a valid
    annual response is an official open day under the existing project policy.
    TPEX's monthly endpoint is expected to contain every weekday in that
    month; a missing weekday is therefore rejected rather than guessed.
    """

    _validate_date_range(start_date, end_date)
    if not isinstance(twse_responses, Mapping) or not twse_responses:
        raise OfficialCalendarBundleError("twse_responses must be non-empty")
    if not isinstance(tpex_responses, Mapping) or not tpex_responses:
        raise OfficialCalendarBundleError("tpex_responses must be non-empty")
    if capture_mode not in {"fixture_only", "bounded_network", "mixed"}:
        raise OfficialCalendarBundleError("capture_mode is invalid")
    if not isinstance(network_enabled, bool):
        raise OfficialCalendarBundleError("network_enabled must be boolean")
    if network_enabled and capture_mode == "fixture_only":
        raise OfficialCalendarBundleError(
            "fixture_only capture cannot claim network_enabled"
        )

    parsed_twse: dict[int, dict[date, bool]] = {}
    for year_key, response in twse_responses.items():
        if not isinstance(year_key, int) or isinstance(year_key, bool):
            raise OfficialCalendarBundleError("TWSE response keys must be years")
        _validate_response(response, "twse", str(year_key))
        parsed_year, schedule = _parse_twse_schedule(response.payload)
        if parsed_year != year_key:
            raise OfficialCalendarBundleError(
                f"TWSE response key/year mismatch: {year_key} != {parsed_year}"
            )
        parsed_twse[year_key] = schedule

    parsed_tpex: dict[str, dict[date, bool]] = {}
    for month_key, response in tpex_responses.items():
        if not isinstance(month_key, str) or not re.fullmatch(r"\d{6}", month_key):
            raise OfficialCalendarBundleError(
                "TPEX response keys must be YYYYMM text"
            )
        _validate_response(response, "tpex", month_key)
        parsed_month, calendar = _parse_tpex_calendar(response.payload)
        if parsed_month != month_key:
            raise OfficialCalendarBundleError(
                f"TPEX response key/month mismatch: {month_key} != {parsed_month}"
            )
        parsed_tpex[month_key] = calendar

    days: list[dict[str, object]] = []
    current = start_date
    while current <= end_date:
        year = current.year
        month_key = current.strftime("%Y%m")
        twse_response = twse_responses.get(year)
        tpex_response = tpex_responses.get(month_key)
        if twse_response is None:
            raise OfficialCalendarBundleError(
                f"missing TWSE annual response for {year}"
            )
        if tpex_response is None:
            raise OfficialCalendarBundleError(
                f"missing TPEX monthly response for {month_key}"
            )

        is_weekend = current.weekday() >= 5
        twse_trading = False if is_weekend else parsed_twse[year].get(current, True)
        tpex_trading = parsed_tpex[month_key].get(current)
        if tpex_trading is None:
            if not is_weekend:
                raise OfficialCalendarBundleError(
                    f"TPEX response has no explicit weekday row for {current.isoformat()}"
                )
            tpex_trading = False

        days.append(
            {
                "date": current.isoformat(),
                "twse": {
                    "is_trading_day": twse_trading,
                    "source": twse_response.source,
                    "source_hash": twse_response.source_hash,
                },
                "tpex": {
                    "is_trading_day": tpex_trading,
                    "source": tpex_response.source,
                    "source_hash": tpex_response.source_hash,
                },
            }
        )
        current += timedelta(days=1)

    captured_at_value = captured_at or datetime.now(timezone.utc)
    if (
        not isinstance(captured_at_value, datetime)
        or captured_at_value.tzinfo is None
        or captured_at_value.utcoffset() is None
    ):
        raise OfficialCalendarBundleError("captured_at must include timezone")

    bundle: dict[str, object] = {
        "schema_version": OFFICIAL_CALENDAR_BUNDLE_SCHEMA_VERSION,
        "range": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "day_count": len(days),
        },
        "generated_at_utc": captured_at_value.astimezone(timezone.utc).isoformat(),
        "capture_mode": capture_mode,
        "network_enabled": network_enabled,
        "candidate_only": True,
        "formal_clock_created": False,
        "source_responses": {
            "twse": [
                {
                    "year": year,
                    "source": response.source,
                    "source_hash": response.source_hash,
                }
                for year, response in sorted(twse_responses.items())
            ],
            "tpex": [
                {
                    "month": month,
                    "source": response.source,
                    "source_hash": response.source_hash,
                }
                for month, response in sorted(tpex_responses.items())
            ],
        },
        "days": days,
        "safety": {
            "read_only": True,
            "market_db_written": False,
            "formal_paths_written": False,
            "formal_oos_allowed": False,
            "production_scheduler_allowed": False,
            "broker_order_allowed": False,
            "secret_values_emitted": False,
        },
    }
    bundle["bundle_hash"] = payload_hash(bundle)
    return bundle


def load_fixture_response(path: Path, *, kind: str) -> CapturedCalendarResponse:
    """Read one bounded raw fixture without writing or contacting the network."""

    resolved = path.expanduser().resolve()
    raw = resolved.read_bytes()
    if len(raw) > MAX_FIXTURE_BYTES:
        raise OfficialCalendarBundleError(
            f"fixture exceeds {MAX_FIXTURE_BYTES} bytes: {resolved}"
        )
    try:
        payload: object = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OfficialCalendarBundleError(
            f"fixture must be UTF-8 JSON: {resolved}"
        ) from error

    if kind == "twse":
        year, _ = _parse_twse_schedule(payload)
        roc_year = year - 1911
        source = f"{TWSE_HOLIDAY_SCHEDULE_URL}?queryYear={roc_year}"
        key = str(year)
    elif kind == "tpex":
        month, _ = _parse_tpex_calendar(payload)
        source = f"{TPEX_MARKET_CALENDAR_URL}?ym={month}&lang=zh-tw"
        key = month
    else:
        raise OfficialCalendarBundleError("fixture kind must be twse or tpex")
    return CapturedCalendarResponse(
        kind=kind,
        key=key,
        source=f"{source} (fixture:{resolved})",
        source_hash=hash_response_bytes(raw),
        payload=payload,
    )


def write_candidate_bundle(path: Path, bundle: Mapping[str, object]) -> str:
    """Create a candidate bundle once, restricted to the OS TEMP directory."""

    resolved = path.expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        resolved.relative_to(temp_root)
    except ValueError as error:
        raise OfficialCalendarBundleError(
            "candidate bundle output must be under the operating-system TEMP directory"
        ) from error
    if not resolved.parent.exists():
        raise OfficialCalendarBundleError(
            "candidate bundle output parent directory must already exist"
        )
    if not isinstance(bundle, Mapping):
        raise OfficialCalendarBundleError("bundle must be an object")
    encoded = (
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        with resolved.open("xb") as handle:
            handle.write(encoded)
    except FileExistsError as error:
        raise OfficialCalendarBundleError(
            "candidate bundle output already exists; choose a new path"
        ) from error
    return hash_response_bytes(encoded)


def fetch_network_responses(
    *,
    years: set[int],
    months: set[str],
    request_fn: Callable[..., Any] = safe_request,
) -> tuple[dict[int, CapturedCalendarResponse], dict[str, CapturedCalendarResponse]]:
    """Fetch only the bounded annual/monthly official endpoints requested."""

    twse: dict[int, CapturedCalendarResponse] = {}
    for year in sorted(years):
        roc_year = year - 1911
        if roc_year <= 0:
            raise OfficialCalendarBundleError(f"invalid TWSE year: {year}")
        response = request_fn(
            TWSE_HOLIDAY_SCHEDULE_URL,
            params={"queryYear": str(roc_year)},
            timeout_seconds=10,
            max_attempts=1,
        )
        payload = _response_json(response, f"TWSE {year}")
        raw = _response_bytes(response, payload)
        parsed_year, _ = _parse_twse_schedule(payload)
        if parsed_year != year:
            raise OfficialCalendarBundleError(
                f"TWSE response year mismatch: {year} != {parsed_year}"
            )
        twse[year] = CapturedCalendarResponse(
            kind="twse",
            key=str(year),
            source=f"{TWSE_HOLIDAY_SCHEDULE_URL}?queryYear={roc_year}",
            source_hash=hash_response_bytes(raw),
            payload=payload,
        )

    tpex: dict[str, CapturedCalendarResponse] = {}
    for month in sorted(months):
        response = request_fn(
            TPEX_MARKET_CALENDAR_URL,
            params={"ym": month, "lang": "zh-tw"},
            timeout_seconds=10,
            max_attempts=1,
        )
        payload = _response_json(response, f"TPEX {month}")
        raw = _response_bytes(response, payload)
        parsed_month, _ = _parse_tpex_calendar(payload)
        if parsed_month != month:
            raise OfficialCalendarBundleError(
                f"TPEX response month mismatch: {month} != {parsed_month}"
            )
        tpex[month] = CapturedCalendarResponse(
            kind="tpex",
            key=month,
            source=f"{TPEX_MARKET_CALENDAR_URL}?ym={month}&lang=zh-tw",
            source_hash=hash_response_bytes(raw),
            payload=payload,
        )
    return twse, tpex


def _validate_date_range(start_date: date, end_date: date) -> None:
    if type(start_date) is not date or type(end_date) is not date:
        raise OfficialCalendarBundleError("start_date/end_date must be dates")
    if end_date < start_date:
        raise OfficialCalendarBundleError("end_date must not precede start_date")
    span = (end_date - start_date).days + 1
    if span > MAX_CAPTURE_DAYS:
        raise OfficialCalendarBundleError(
            f"capture range cannot exceed {MAX_CAPTURE_DAYS} calendar days"
        )


def _validate_response(
    response: CapturedCalendarResponse,
    expected_kind: str,
    expected_key: str,
) -> None:
    if not isinstance(response, CapturedCalendarResponse):
        raise OfficialCalendarBundleError(
            f"{expected_kind} response {expected_key} has invalid type"
        )
    if response.kind != expected_kind or response.key != expected_key:
        raise OfficialCalendarBundleError(
            f"{expected_kind} response identity mismatch: {expected_key}"
        )


def _parse_twse_schedule(payload: object) -> tuple[int, dict[date, bool]]:
    if not isinstance(payload, list) or not payload:
        raise OfficialCalendarBundleError(
            "TWSE holidaySchedule payload must be a non-empty array"
        )
    schedule: dict[date, bool] = {}
    parsed_year: int | None = None
    valid_rows = 0
    for index, raw_row in enumerate(payload):
        if not isinstance(raw_row, Mapping) or "Date" not in raw_row:
            raise OfficialCalendarBundleError(
                f"TWSE holidaySchedule row {index} lacks Date"
            )
        row_date = _parse_roc_date(raw_row["Date"], index=index)
        if parsed_year is None:
            parsed_year = row_date.year
        elif row_date.year != parsed_year:
            raise OfficialCalendarBundleError(
                "TWSE holidaySchedule fixture contains multiple years"
            )
        description = " ".join(
            str(raw_row.get(field, ""))
            for field in ("Name", "Description")
        )
        schedule[row_date] = schedule.get(row_date, False) or any(
            marker in description for marker in _OPEN_MARKERS
        )
        valid_rows += 1
    if parsed_year is None or valid_rows == 0:
        raise OfficialCalendarBundleError("TWSE holidaySchedule has no valid rows")
    return parsed_year, schedule


def _parse_tpex_calendar(payload: object) -> tuple[str, dict[date, bool]]:
    if not isinstance(payload, Mapping):
        raise OfficialCalendarBundleError("TPEX calendar payload must be an object")
    calendar = payload.get("calendar")
    if not isinstance(calendar, Mapping):
        raise OfficialCalendarBundleError("TPEX calendar payload lacks calendar")
    status = payload.get("status", calendar.get("status", ""))
    if str(status).casefold() != "success":
        raise OfficialCalendarBundleError("TPEX calendar status must be success")
    raw_data = calendar.get("data")
    if not isinstance(raw_data, Mapping) or not raw_data:
        raise OfficialCalendarBundleError("TPEX calendar data must be non-empty")

    month: str | None = None
    parsed: dict[date, bool] = {}
    for raw_key, raw_row in raw_data.items():
        key = str(raw_key)
        if _DATE_KEY_PATTERN.fullmatch(key) is None:
            raise OfficialCalendarBundleError(
                f"TPEX calendar contains invalid date key: {key}"
            )
        try:
            row_date = datetime.strptime(key, "%Y%m%d").date()
        except ValueError as error:
            raise OfficialCalendarBundleError(
                f"TPEX calendar contains invalid date: {key}"
            ) from error
        row_month = row_date.strftime("%Y%m")
        if month is None:
            month = row_month
        elif row_month != month:
            raise OfficialCalendarBundleError(
                "TPEX calendar fixture contains multiple months"
            )
        if not isinstance(raw_row, Mapping):
            raise OfficialCalendarBundleError(f"TPEX row {key} must be an object")
        holiday = raw_row.get("holiday")
        if not isinstance(holiday, bool):
            raise OfficialCalendarBundleError(
                f"TPEX row {key}.holiday must be boolean"
            )
        holiday_list = raw_row.get("holidayList", [])
        if not isinstance(holiday_list, list):
            raise OfficialCalendarBundleError(
                f"TPEX row {key}.holidayList must be an array"
            )
        parsed[row_date] = not holiday
    if month is None or not parsed:
        raise OfficialCalendarBundleError("TPEX calendar has no valid rows")
    return month, parsed


def _parse_roc_date(value: object, *, index: int) -> date:
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 7:
        raise OfficialCalendarBundleError(
            f"TWSE holidaySchedule row {index} Date must be 7 ROC digits"
        )
    try:
        return date(
            int(digits[:3]) + 1911,
            int(digits[3:5]),
            int(digits[5:7]),
        )
    except ValueError as error:
        raise OfficialCalendarBundleError(
            f"TWSE holidaySchedule row {index} Date is invalid"
        ) from error


def _response_json(response: Any, label: str) -> object:
    try:
        payload = response.json()
    except Exception as error:  # noqa: BLE001 - external payload boundary
        raise OfficialCalendarBundleError(f"{label} response is not valid JSON") from error
    return payload


def _response_bytes(response: Any, payload: object) -> bytes:
    raw = getattr(response, "content", None)
    if isinstance(raw, bytes) and raw:
        return raw
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
