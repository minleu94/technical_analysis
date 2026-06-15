from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Protocol, Sequence
from numbers import Integral, Real

import pandas as pd

from app_module.decision_desk_dtos import DecisionDeskQuality, WatchlistTriggerSummary


class WatchlistProvider(Protocol):
    def fetch(self, as_of_date: date) -> Sequence[object]:
        """Return watchlist payload for the specified date."""


class RankingProvider(Protocol):
    def fetch(self, as_of_date: date) -> Mapping[str, Any] | Sequence[Any]:
        """Return ranking payload keyed by stock code."""

    def fetch_previous(self, as_of_date: date) -> Mapping[str, Any] | Sequence[Any] | None:
        """Return previous ranking snapshot used to detect trend change."""


class WatchlistTriggerService:
    """Build watchlist trigger summary from external, read-only providers."""

    def __init__(
        self,
        watchlist_provider: WatchlistProvider,
        ranking_provider: RankingProvider,
        *,
        entry_threshold_bp: int = 6000,
    ) -> None:
        self.watchlist_provider = watchlist_provider
        self.ranking_provider = ranking_provider
        self.entry_threshold_bp = entry_threshold_bp

    def build_snapshot(self, as_of_date: date) -> WatchlistTriggerSummary:
        try:
            watchlist_codes = self._normalize_watchlist(self.watchlist_provider.fetch(as_of_date))
        except Exception as exc:  # noqa: BLE001
            return WatchlistTriggerSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=(f"watchlist_trigger_watchlist_provider_error:{exc}",),
            )

        if not watchlist_codes:
            return WatchlistTriggerSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("watchlist_trigger_watchlist_missing",),
                trigger_count=0,
                triggered_codes=(),
            )

        try:
            current_scores = self._normalize_ranking(self.ranking_provider.fetch(as_of_date))
        except Exception as exc:  # noqa: BLE001
            return WatchlistTriggerSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=(f"watchlist_trigger_ranking_provider_error:{exc}",),
                trigger_count=0,
                triggered_codes=(),
            )

        previous_scores = self._load_previous_scores(as_of_date)

        new_candidates: list[str] = []
        increases: list[str] = []
        decreases: list[str] = []
        data_insufficient_codes: list[str] = []
        risk_codes: list[str] = []
        warnings: list[str] = []

        for code in watchlist_codes:
            current = self._read_score(current_scores.get(code))
            if current is None:
                data_insufficient_codes.append(code)
                warnings.append(f"watchlist_trigger_data_insufficient:{code}")
                continue

            if self._is_risk(current_scores.get(code)):
                risk_codes.append(code)
                warnings.append(f"watchlist_trigger_risk_alert:{code}")

            previous = self._read_score(previous_scores.get(code))
            if current < self.entry_threshold_bp:
                continue

            if previous is None or previous < self.entry_threshold_bp:
                new_candidates.append(code)
            elif current > previous:
                increases.append(code)
            elif current < previous:
                decreases.append(code)

        triggered_codes = tuple(dict.fromkeys(new_candidates + increases + decreases))
        top_signal = self._build_top_signal(new_candidates, increases, decreases)
        has_data_gap = len(data_insufficient_codes) > 0
        has_any_warning = bool(warnings)

        if has_any_warning:
            # Degraded is reserved for hard errors. Data gaps remain estimated.
            quality = DecisionDeskQuality.ESTIMATED
        else:
            quality = DecisionDeskQuality.OBSERVED

        return WatchlistTriggerSummary(
            as_of_date=as_of_date,
            quality=quality,
            warnings=tuple(warnings),
            trigger_count=len(triggered_codes),
            triggered_codes=triggered_codes,
            top_signal=top_signal,
        )

    def _load_previous_scores(self, as_of_date: date) -> dict[str, Any]:
        provider = self.ranking_provider
        previous_method = getattr(provider, "fetch_previous", None)
        if not callable(previous_method):
            return {}
        try:
            previous_raw = previous_method(as_of_date)
            if previous_raw is None:
                return {}
            return self._normalize_ranking(previous_raw)
        except Exception:
            return {}

    def _build_top_signal(
        self,
        new_candidates: Sequence[str],
        increases: Sequence[str],
        decreases: Sequence[str],
    ) -> str | None:
        parts: list[str] = []
        if new_candidates:
            parts.append("new=" + ",".join(new_candidates))
        if increases:
            parts.append("up=" + ",".join(increases))
        if decreases:
            parts.append("down=" + ",".join(decreases))
        if not parts:
            return None
        return " ; ".join(parts)

    def _normalize_watchlist(self, raw_watchlist: Sequence[object]) -> tuple[str, ...]:
        if raw_watchlist is None:
            return ()
        codes: list[str] = []
        for item in raw_watchlist:
            code = self._extract_stock_code(item)
            if code is not None and code not in codes:
                codes.append(code)
        return tuple(codes)

    def _extract_stock_code(self, item: object) -> str | None:
        if isinstance(item, str):
            code = item.strip()
            return code if code else None
        if isinstance(item, Mapping):
            for key in ("stock_code", "code", "ticker", "symbol"):
                value = item.get(key)
                if isinstance(value, str):
                    code = value.strip()
                    if code:
                        return code
        return None

    def _normalize_ranking(self, raw: Mapping[str, Any] | Sequence[Any]) -> dict[str, Any]:
        if raw is None:
            return {}
        if isinstance(raw, Mapping):
            return {str(key): value for key, value in raw.items() if key is not None}

        records: dict[str, Any] = {}
        for entry in raw:
            if not isinstance(entry, Mapping):
                continue
            code = self._extract_stock_code(entry)
            if code is None:
                continue
            records[code] = entry
        return records

    def _read_score(self, payload: Any) -> int | None:
        if payload is None:
            return None
        if isinstance(payload, Mapping):
            score = payload.get("score_bp")
            if score is None:
                score = payload.get("score")
            if score is None:
                score = payload.get("intensity")
            payload = score
        if isinstance(payload, bool):
            return None
        if isinstance(payload, Integral):
            return int(payload)
        if isinstance(payload, Real):
            try:
                numeric_value = float(payload)
            except (TypeError, ValueError):
                return None
            return int(numeric_value)
        if isinstance(payload, str):
            cleaned = payload.strip()
            if cleaned.startswith(("+", "-")) and cleaned[1:].isdigit():
                try:
                    return int(cleaned)
                except ValueError:
                    return None
            if cleaned.isdigit():
                try:
                    return int(cleaned)
                except ValueError:
                    return None
        return None

    def _is_risk(self, payload: Any) -> bool:
        if not isinstance(payload, Mapping):
            return False
        for key in ("risk_alert", "risk", "warn", "warning"):
            value = payload.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"1", "y", "yes", "true", "risk", "warning"}:
                    return True
        return False


class WatchlistServiceWatchlistProvider:
    """Watchlist provider that loads active watchlist from WatchlistService."""

    def __init__(self, watchlist_service: Any, watchlist_id: str = "default") -> None:
        self.watchlist_service = watchlist_service
        self.watchlist_id = watchlist_id

    def fetch(self, as_of_date: date) -> Sequence[object]:
        if self.watchlist_service is None:
            return []
        return self.watchlist_service.get_stocks(self.watchlist_id)


class SQLiteRankingProvider:
    """Ranking provider that fetches technical indicators from SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.actual_date: date | None = None

    def fetch(self, as_of_date: date) -> dict[str, dict[str, Any]]:
        self.actual_date = as_of_date
        if not self.db_path.exists():
            return {}

        target_key = as_of_date.strftime("%Y%m%d")
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT DISTINCT 日期
                FROM technical_indicators
                WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') <= ?
                ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') DESC
                LIMIT 1
                """,
                (target_key,),
            )
            row = cursor.fetchone()
            if row is None or not row[0]:
                return {}
            actual_key = str(row[0]).replace("-", "").replace("/", "")
            try:
                self.actual_date = datetime.strptime(actual_key, "%Y%m%d").date()
            except ValueError:
                pass

            df = pd.read_sql_query(
                """
                SELECT 證券代號, RSI, Close, lowerband
                FROM technical_indicators
                WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') = ?
                """,
                conn,
                params=(actual_key,),
            )

        if df.empty:
            return {}

        result = {}
        for _, r in df.iterrows():
            code = str(r["證券代號"]).strip()
            rsi_val = r["RSI"]
            close_val = r["Close"]
            lower_val = r["lowerband"]

            score_bp = None
            if rsi_val is not None and not pd.isna(rsi_val):
                try:
                    score_bp = int(float(rsi_val) * 100)
                except (ValueError, TypeError):
                    pass

            risk_alert = False
            if rsi_val is not None and not pd.isna(rsi_val):
                if float(rsi_val) > 80 or float(rsi_val) < 20:
                    risk_alert = True
            if close_val is not None and not pd.isna(close_val) and lower_val is not None and not pd.isna(lower_val):
                if float(close_val) < float(lower_val):
                    risk_alert = True

            result[code] = {
                "score_bp": score_bp,
                "risk_alert": risk_alert,
            }
        return result

    def fetch_previous(self, as_of_date: date) -> dict[str, dict[str, Any]] | None:
        if not self.db_path.exists():
            return None

        target_key = as_of_date.strftime("%Y%m%d")
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT DISTINCT 日期
                FROM technical_indicators
                WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') < ?
                ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') DESC
                LIMIT 1
                """,
                (target_key,),
            )
            row = cursor.fetchone()
            if row is None or not row[0]:
                return None
            prev_key = str(row[0]).replace("-", "").replace("/", "")

            df = pd.read_sql_query(
                """
                SELECT 證券代號, RSI, Close, lowerband
                FROM technical_indicators
                WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') = ?
                """,
                conn,
                params=(prev_key,),
            )

        if df.empty:
            return {}

        result = {}
        for _, r in df.iterrows():
            code = str(r["證券代號"]).strip()
            rsi_val = r["RSI"]
            close_val = r["Close"]
            lower_val = r["lowerband"]

            score_bp = None
            if rsi_val is not None and not pd.isna(rsi_val):
                try:
                    score_bp = int(float(rsi_val) * 100)
                except (ValueError, TypeError):
                    pass

            risk_alert = False
            if rsi_val is not None and not pd.isna(rsi_val):
                if float(rsi_val) > 80 or float(rsi_val) < 20:
                    risk_alert = True
            if close_val is not None and not pd.isna(close_val) and lower_val is not None and not pd.isna(lower_val):
                if float(close_val) < float(lower_val):
                    risk_alert = True

            result[code] = {
                "score_bp": score_bp,
                "risk_alert": risk_alert,
            }
        return result
