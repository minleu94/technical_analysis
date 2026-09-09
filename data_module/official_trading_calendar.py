"""官方交易日曆判定介面。

嚴禁單純以「週一至週五」當作台股交易日。本模組以 TWSE 官方
``holidaySchedule`` 年度休市表為主要證據；只有在年度表成功取得且通過
結構驗證後，才可將「非週末且不在休市表」判為開市。官方表取得失敗時
一律回傳未知，不得以一般工作日推定開市。
若呼叫端提供新鮮且 hash-bound 的官方 annual cache，則可在官方請求不可得時
唯讀重驗該 cache；cache 缺失、過期或竄改時仍回傳未知。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import logging
from pathlib import Path
import re
import sqlite3
from typing import Mapping, Optional, Tuple

from data_module.config import TWStockConfig
from data_module.official_phase3c_fetcher import safe_request
from data_module.official_trading_calendar_cache import (
    OfficialCalendarCacheError,
    OfficialCalendarCacheExpired,
    TWSE_TEMPORARY_CLOSURE_POLICY_URL,
    VerifiedOfficialCalendarCache,
    VerifiedTemporaryClosureCache,
    load_verified_twse_calendar_cache,
    load_verified_twse_temporary_closure_cache,
    parse_twse_annual_schedule,
)

logger = logging.getLogger(__name__)

HOLIDAY_SCHEDULE_URL = (
    "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
)
_OFFICIAL_OPEN_MARKERS = (
    "開始交易",
    "最後交易",
    "恢復交易",
    "照常交易",
)


class OfficialTradingCalendar:
    """台股官方交易日判定器。"""

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        *,
        calendar_cache_path: Optional[str | Path] = None,
        temporary_closure_path: Optional[str | Path] = None,
    ) -> None:
        if db_path is None:
            config = TWStockConfig()
            self.db_path = Path(config.db_file)
        else:
            self.db_path = Path(db_path)
        self.calendar_cache_path = (
            None
            if calendar_cache_path is None
            else Path(calendar_cache_path)
        )
        self.temporary_closure_path = (
            None
            if temporary_closure_path is None
            else Path(temporary_closure_path)
        )
        self._schedule_cache: dict[int, Mapping[date, bool] | None] = {}
        self._schedule_evidence: dict[int, dict[str, object]] = {}
        self._schedule_failure_reason: dict[int, str] = {}
        self._last_cache_error: OfficialCalendarCacheError | None = None
        self._temporary_closure_cache: dict[
            date, VerifiedTemporaryClosureCache | None
        ] = {}
        self._temporary_closure_failure_reason: dict[date, str] = {}

    @staticmethod
    def _parse_roc_date(value: object, *, expected_year: int) -> date:
        digits = re.sub(r"\D", "", str(value))
        if len(digits) != 7:
            raise ValueError("TWSE holidaySchedule Date 必須是 7 碼民國日期")
        roc_year = int(digits[:3])
        result = date(roc_year + 1911, int(digits[3:5]), int(digits[5:7]))
        if result.year != expected_year:
            raise ValueError("TWSE holidaySchedule 回傳非查詢年度日期")
        return result

    @staticmethod
    def _row_is_open(row: Mapping[str, object]) -> bool:
        description = " ".join(
            str(row.get(field, "")) for field in ("Name", "Description")
        )
        return any(marker in description for marker in _OFFICIAL_OPEN_MARKERS)

    def _fetch_official_year_schedule(
        self,
        calendar_year: int,
    ) -> Mapping[date, bool] | None:
        if calendar_year in self._schedule_cache:
            return self._schedule_cache[calendar_year]

        cache_error: OfficialCalendarCacheError | None = None
        cached = self._load_cached_year_schedule(calendar_year)
        if cached is not None:
            self._schedule_cache[calendar_year] = cached.schedule
            self._schedule_evidence[calendar_year] = dict(cached.evidence)
            return self._schedule_cache[calendar_year]
        if self.calendar_cache_path is not None:
            cache_error = self._last_cache_error

        try:
            response = safe_request(
                HOLIDAY_SCHEDULE_URL,
                params={"queryYear": str(calendar_year - 1911)},
                timeout_seconds=8,
                max_attempts=1,
            )
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                raise ValueError("TWSE holidaySchedule 必須回傳非空 array")

            schedule = parse_twse_annual_schedule(
                payload,
                expected_year=calendar_year,
            )
            response_content = getattr(response, "content", b"")
            source_hash = None
            if isinstance(response_content, bytes) and response_content:
                import hashlib

                source_hash = "sha256:" + hashlib.sha256(response_content).hexdigest()
            self._schedule_evidence[calendar_year] = {
                "mode": "live_official_calendar",
                "source": HOLIDAY_SCHEDULE_URL,
                "request_params": {"queryYear": str(calendar_year - 1911)},
                "source_hash": source_hash,
                "validated_at": datetime.now(timezone.utc).isoformat(),
                "annual_schedule_scope": "planned_annual_closures",
                "temporary_closure_scope": {
                    "provider": "TWSE",
                    "url": TWSE_TEMPORARY_CLOSURE_POLICY_URL,
                    "source_kind": "official_policy_only",
                    "event_evidence_required": True,
                },
            }
            self._schedule_failure_reason.pop(calendar_year, None)
            self._schedule_cache[calendar_year] = schedule
        except Exception as exc:  # noqa: BLE001 - 網路／官方格式皆須 fail closed
            logger.warning(
                "取得 TWSE holidaySchedule 失敗 (%s): %s",
                calendar_year,
                exc,
            )
            self._schedule_cache[calendar_year] = None
            if cache_error is not None:
                self._schedule_failure_reason[calendar_year] = (
                    self._cache_error_reason(cache_error)
                )
            else:
                self._schedule_failure_reason[calendar_year] = (
                    "twse_holiday_schedule_unavailable"
                )
        return self._schedule_cache[calendar_year]

    def _cache_candidates(self, calendar_year: int) -> tuple[Path, ...]:
        """列出指定年度的 immutable cache candidates。"""

        if self.calendar_cache_path is None:
            return ()
        root = self.calendar_cache_path.expanduser()
        if root.exists() and root.is_file():
            return (root,)
        if root.suffix.casefold() == ".json":
            return (root,)
        if not root.is_dir():
            return ()
        candidates = list(
            root.glob(f"twse_holiday_schedule_{calendar_year}_*.json")
        )
        exact = root / f"twse_holiday_schedule_{calendar_year}.json"
        if exact.exists():
            candidates.append(exact)
        return tuple(sorted(set(candidates)))

    def _load_cached_year_schedule(
        self,
        calendar_year: int,
    ) -> VerifiedOfficialCalendarCache | None:
        """只讀載入最新且仍在 freshness window 的官方 cache。"""

        self._last_cache_error = None
        candidates = self._cache_candidates(calendar_year)
        if not candidates:
            if self.calendar_cache_path is not None:
                self._last_cache_error = OfficialCalendarCacheError(
                    "calendar cache file is missing"
                )
            return None
        verified: list[VerifiedOfficialCalendarCache] = []
        errors: list[OfficialCalendarCacheError] = []
        observed = datetime.now(timezone.utc)
        for candidate in candidates:
            try:
                verified.append(
                    load_verified_twse_calendar_cache(
                        candidate,
                        calendar_year=calendar_year,
                        observed_at=observed,
                    )
                )
            except OfficialCalendarCacheError as error:
                errors.append(error)
        if verified:
            verified.sort(
                key=lambda item: str(item.evidence.get("captured_at", ""))
            )
            return verified[-1]
        if errors:
            self._last_cache_error = errors[0]
        return None

    @staticmethod
    def _cache_error_reason(error: OfficialCalendarCacheError) -> str:
        if isinstance(error, OfficialCalendarCacheExpired):
            return "twse_holiday_schedule_cache_expired"
        message = str(error).casefold()
        if "year mismatch" in message:
            return "twse_holiday_schedule_cache_wrong_year"
        if "missing" in message:
            return "twse_holiday_schedule_cache_missing"
        return "twse_holiday_schedule_cache_invalid"

    def _schedule_reason(self, calendar_year: int) -> str:
        return self._schedule_failure_reason.get(
            calendar_year,
            "twse_holiday_schedule_unavailable",
        )

    def _temporary_closure_candidates(self) -> tuple[Path, ...]:
        if self.temporary_closure_path is None:
            return ()
        root = self.temporary_closure_path.expanduser()
        if root.exists() and root.is_file():
            return (root,)
        if root.suffix.casefold() == ".json":
            return (root,)
        if not root.is_dir():
            return ()
        return tuple(sorted(root.glob("twse_temporary_closure_*.json")))

    def _temporary_closure_for(
        self,
        target_date: date,
    ) -> VerifiedTemporaryClosureCache | None:
        """讀取指定日期的官方臨時全面休市事件，缺件不猜。"""

        if self.temporary_closure_path is None:
            return None
        if target_date in self._temporary_closure_cache:
            return self._temporary_closure_cache[target_date]
        verified: list[VerifiedTemporaryClosureCache] = []
        errors: list[OfficialCalendarCacheError] = []
        observed = datetime.now(timezone.utc)
        for candidate in self._temporary_closure_candidates():
            try:
                item = load_verified_twse_temporary_closure_cache(
                    candidate,
                    observed_at=observed,
                )
            except OfficialCalendarCacheError as error:
                errors.append(error)
                continue
            if item.closure_date == target_date:
                verified.append(item)
        selected: VerifiedTemporaryClosureCache | None = None
        if verified:
            verified.sort(
                key=lambda item: str(item.evidence.get("captured_at", ""))
            )
            selected = verified[-1]
        if errors:
            self._temporary_closure_failure_reason[target_date] = (
                f"{type(errors[0]).__name__}:{errors[0]}"
            )
        self._temporary_closure_cache[target_date] = selected
        return selected

    def _temporary_closure_scope(self, target_date: date) -> dict[str, object]:
        result: dict[str, object] = {
            "provider": "TWSE",
            "policy_url": TWSE_TEMPORARY_CLOSURE_POLICY_URL,
            "source_kind": "official_event_announcement_optional",
            "event_evidence_required": True,
            "event_evidence_required_for_unplanned_closure": True,
            "path": (
                None
                if self.temporary_closure_path is None
                else str(self.temporary_closure_path.expanduser())
            ),
            "target_date": target_date.isoformat(),
            "status": "not_captured",
        }
        error = self._temporary_closure_failure_reason.get(target_date)
        if error is not None:
            result.update({"status": "invalid", "error": error})
        return result

    def evidence_for(self, target_date: date) -> dict[str, object]:
        """傳回最近一次判定所使用的 calendar source custody evidence。"""

        if target_date.weekday() >= 5:
            return {
                "mode": "calendar_weekend_convention",
                "target_date": target_date.isoformat(),
                "is_trading_day": False,
                "reason_code": "weekend_closed",
            }
        temporary = self._temporary_closure_for(target_date)
        if temporary is not None:
            evidence = dict(temporary.evidence)
            evidence.update(
                {
                    "target_date": target_date.isoformat(),
                    "is_trading_day": False,
                    "reason_code": "twse_temporary_closure_official",
                    "temporary_closure_scope": {
                        **self._temporary_closure_scope(target_date),
                        "status": "verified",
                    },
                    "annual_schedule_evidence": {
                        "status": "not_required_for_explicit_closure"
                    },
                }
            )
            return evidence
        schedule = self._fetch_official_year_schedule(target_date.year)
        evidence = dict(self._schedule_evidence.get(target_date.year, {}))
        evidence["target_date"] = target_date.isoformat()
        evidence.setdefault(
            "annual_schedule_scope",
            "planned_annual_closures",
        )
        evidence["temporary_closure_scope"] = self._temporary_closure_scope(
            target_date
        )
        if schedule is None:
            evidence["is_trading_day"] = None
            evidence["reason_code"] = self._schedule_reason(target_date.year)
        else:
            flag = (
                schedule[target_date]
                if target_date in schedule
                else True
            )
            evidence["is_trading_day"] = flag
            if evidence.get("mode") == "hash_bound_official_calendar_cache":
                evidence["reason_code"] = (
                    "twse_holiday_schedule_cache_explicit_open"
                    if target_date in schedule and flag
                    else "twse_holiday_schedule_cache_closed"
                    if target_date in schedule
                    else "twse_holiday_schedule_cache_open"
                )
            else:
                evidence["reason_code"] = (
                    "twse_holiday_schedule_explicit_open"
                    if target_date in schedule and flag
                    else "twse_holiday_schedule_closed"
                    if target_date in schedule
                    else "twse_holiday_schedule_open"
                )
        return evidence

    def _has_local_market_index_evidence(self, target_date: date) -> bool:
        """僅供停用線上查詢的歷史回補使用，不推定缺列是休市。"""

        date_yyyymmdd = target_date.strftime("%Y%m%d")
        if not self.db_path.exists():
            return False
        try:
            uri = f"file:{self.db_path.resolve().as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as conn:
                conn.execute("PRAGMA query_only=ON")
                columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(market_indices)")
                }
                date_column = next(
                    (
                        column
                        for column in ("日期", "trade_date", "date")
                        if column in columns
                    ),
                    None,
                )
                if date_column is None:
                    return False
                count = conn.execute(
                    f'SELECT COUNT(*) FROM market_indices WHERE "{date_column}" = ?',
                    (date_yyyymmdd,),
                ).fetchone()[0]
                return bool(count > 0)
        except Exception as exc:  # noqa: BLE001 - 本地證據失效時保持未知
            logger.warning("讀取 DB 交易日證據失敗 (%s): %s", target_date, exc)
            return False

    def is_official_trading_day(
        self, target_date: date, allow_online_probe: bool = True
    ) -> Tuple[Optional[bool], str]:
        """判定指定日期是否為台股官方交易日。

        Returns:
            (is_trading_day, reason_code)
            - (True, "twse_holiday_schedule_open")
            - (True, "twse_holiday_schedule_explicit_open")
            - (True, "twstock_db_market_indices_evidence")
            - (False, "weekend_closed")
            - (False, "twse_holiday_schedule_closed")
            - (None, "twse_holiday_schedule_unavailable")
        """
        if target_date.weekday() >= 5:
            return False, "weekend_closed"

        if self._temporary_closure_for(target_date) is not None:
            return False, "twse_temporary_closure_official"

        if not allow_online_probe:
            cached = self._load_cached_year_schedule(target_date.year)
            if cached is not None:
                self._schedule_cache[target_date.year] = cached.schedule
                self._schedule_evidence[target_date.year] = dict(cached.evidence)
                flag = cached.schedule.get(target_date, True)
                if target_date in cached.schedule:
                    return (
                        flag,
                        "twse_holiday_schedule_cache_explicit_open"
                        if flag
                        else "twse_holiday_schedule_cache_closed",
                    )
                return True, "twse_holiday_schedule_cache_open"
            if self._has_local_market_index_evidence(target_date):
                return True, "twstock_db_market_indices_evidence"
            return None, "lacks_official_evidence"

        schedule = self._fetch_official_year_schedule(target_date.year)
        if schedule is None:
            return None, self._schedule_reason(target_date.year)
        if self._schedule_evidence.get(target_date.year, {}).get("mode") == (
            "hash_bound_official_calendar_cache"
        ):
            if target_date not in schedule:
                return True, "twse_holiday_schedule_cache_open"
            if schedule[target_date]:
                return True, "twse_holiday_schedule_cache_explicit_open"
            return False, "twse_holiday_schedule_cache_closed"
        if target_date not in schedule:
            return True, "twse_holiday_schedule_open"
        if schedule[target_date]:
            return True, "twse_holiday_schedule_explicit_open"
        return False, "twse_holiday_schedule_closed"

    def get_trading_days_in_range(
        self, start_date: date, end_date: date, allow_online_probe: bool = True
    ) -> list[dict[str, object]]:
        """掃描日期區間並傳回各日之官方交易日判定。

        Returns:
            [
                {
                    "date": date_obj,
                    "date_str": "YYYY-MM-DD",
                    "is_trading_day": True | False | None,
                    "reason_code": str
                }, ...
            ]
        """
        results = []
        current = start_date
        while current <= end_date:
            is_td, reason = self.is_official_trading_day(
                current, allow_online_probe=allow_online_probe
            )
            results.append({
                "date": current,
                "date_str": current.isoformat(),
                "is_trading_day": is_td,
                "reason_code": reason,
            })
            current += timedelta(days=1)
        return results

    def require_trading_days_in_range(
        self,
        start_date: date,
        end_date: date,
        *,
        allow_online_probe: bool = True,
    ) -> list[dict[str, object]]:
        """Return only dates with a resolved official-calendar decision.

        The existing ``get_trading_days_in_range`` method intentionally keeps
        ``None`` results so callers can inspect an unknown calendar.  Update
        jobs need a stricter boundary: an unavailable annual schedule must not
        silently turn into a Monday--Friday date list.  This helper therefore
        raises a typed error when any date is unresolved and returns the same
        evidence-rich records for callers that need to persist the decision.
        """

        if start_date > end_date:
            raise ValueError("start_date must be <= end_date")

        results = self.get_trading_days_in_range(
            start_date,
            end_date,
            allow_online_probe=allow_online_probe,
        )
        unknown = [
            str(item["date_str"])
            for item in results
            if item.get("is_trading_day") is None
        ]
        if unknown:
            raise OfficialTradingCalendarError(
                "official trading calendar unresolved: " + ", ".join(unknown)
            )
        for item in results:
            target = item.get("date")
            if isinstance(target, date):
                item["evidence"] = self.evidence_for(target)
        return results

    def get_recent_official_trading_days(
        self,
        reference_date: date,
        count: int,
        *,
        include_reference: bool = True,
        allow_online_probe: bool = True,
        max_lookback_days: int = 92,
    ) -> list[dict[str, object]]:
        """Return the most recent resolved official sessions in ascending order.

        ``reference_date`` may be a weekend or an exchange holiday.  The
        method walks calendar dates and asks the official resolver for every
        date; it never treats a weekday as a session.  A calendar ``None`` is
        an operational error because the caller cannot establish a safe
        freshness window.
        """

        if count <= 0:
            return []
        if max_lookback_days < count:
            raise ValueError("max_lookback_days must be >= count")

        selected: list[dict[str, object]] = []
        current = reference_date
        scanned = 0
        while scanned <= max_lookback_days and len(selected) < count:
            is_trading, reason = self.is_official_trading_day(
                current,
                allow_online_probe=allow_online_probe,
            )
            if is_trading is None:
                raise OfficialTradingCalendarError(
                    f"official trading calendar unresolved: {current.isoformat()} ({reason})"
                )
            if is_trading and (include_reference or current != reference_date):
                selected.append(
                    {
                        "date": current,
                        "date_str": current.isoformat(),
                        "is_trading_day": True,
                        "reason_code": reason,
                        "evidence": self.evidence_for(current),
                    }
                )
            current -= timedelta(days=1)
            scanned += 1

        if len(selected) < count:
            raise OfficialTradingCalendarError(
                "official trading calendar lookback exhausted: "
                f"requested={count}, resolved={len(selected)}, "
                f"reference={reference_date.isoformat()}"
            )
        selected.reverse()
        return selected


class OfficialTradingCalendarError(RuntimeError):
    """Raised when an update cannot establish an official trading-day set."""
