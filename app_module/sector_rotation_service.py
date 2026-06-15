from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Protocol, TypedDict

import pandas as pd

from app_module.decision_desk_dtos import DecisionDeskQuality, SectorRotationSummary


class SectorRotationProvider(Protocol):
    def fetch(self, as_of_date: date) -> pd.DataFrame: ...


class _SectorRankingItem(TypedDict):
    sector: str
    relative_strength_bp: int
    change_5d_bp: int
    change_20d_bp: int


class SectorRotationService:
    """Build sector rotation summary from injected industry index data."""

    def __init__(self, provider: SectorRotationProvider | None = None, *, data: pd.DataFrame | None = None):
        if provider is None and data is None:
            raise ValueError("must provide provider or data")
        if provider is not None and data is not None:
            raise ValueError("provider and data cannot both be provided")
        self.provider = provider
        self.data = data

    def build_snapshot(self, as_of_date: date) -> SectorRotationSummary:
        try:
            if self.provider is not None:
                data = self.provider.fetch(as_of_date)
            else:
                data = self.data
        except Exception as exc:  # noqa: BLE001
            return SectorRotationSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=(f"sector_rotation_provider_error:{exc}",),
            )

        if data is None or data.empty:
            return SectorRotationSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("sector_rotation_missing",),
            )

        ranked, parse_issues, effective_date = self._build_sector_ranking(data, as_of_date)
        if not ranked:
            warnings = ("sector_rotation_missing",) if not parse_issues else tuple(parse_issues)
            return SectorRotationSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING if not parse_issues else DecisionDeskQuality.DEGRADED,
                warnings=warnings,
            )

        warnings = tuple(parse_issues)
        leading_sector: str | None
        trailing_sector: str | None
        rotation_intensity_bp: int | None
        if len(ranked) < 2:
            quality = DecisionDeskQuality.DEGRADED
            leading_sector = ranked[0]["sector"]
            trailing_sector = None
            rotation_intensity_bp = None
        else:
            quality = DecisionDeskQuality.OBSERVED if not warnings else DecisionDeskQuality.DEGRADED
            leading_sector = ranked[0]["sector"]
            trailing_sector = ranked[-1]["sector"]
            rotation_intensity_bp = ranked[0]["relative_strength_bp"] - ranked[-1]["relative_strength_bp"]

        return SectorRotationSummary(
            as_of_date=effective_date,
            quality=quality,
            warnings=warnings,
            leading_sector=leading_sector,
            trailing_sector=trailing_sector,
            rotation_intensity_bp=rotation_intensity_bp,
            meta={"sector_ranking": ranked, "source": self._resolve_source(data)},
        )

    def _build_sector_ranking(
        self,
        data: pd.DataFrame,
        as_of_date: date,
    ) -> tuple[list[_SectorRankingItem], list[str], date]:
        parsed_data = self._prepare_frame(data)
        if parsed_data is None:
            return [], ["sector_rotation_invalid_data"], as_of_date

        date_col = self._resolve_date_column(parsed_data)
        sector_col = self._resolve_sector_column(parsed_data)
        close_col = self._resolve_close_column(parsed_data)
        if date_col is None or sector_col is None or close_col is None:
            return [], ["sector_rotation_missing_required_columns"], as_of_date

        helper_cols = [
            col
            for col in ("_sector_rotation_effective_as_of_date", "_sector_rotation_warnings", "_sector_rotation_source")
            if col in parsed_data.columns
        ]
        parsed_data = parsed_data[[date_col, sector_col, close_col, *helper_cols]].copy()
        parsed_data["_parsed_date"] = self._parse_date_series(parsed_data[date_col])
        parsed_data = parsed_data.dropna(subset=["_parsed_date"])
        parsed_data["_sector"] = parsed_data[sector_col].map(self._normalize_sector)
        parsed_data["_close"] = parsed_data[close_col].map(self._to_decimal)
        parsed_data = parsed_data.dropna(subset=["_sector", "_close"])

        if parsed_data.empty:
            return [], ["sector_rotation_no_valid_rows"], as_of_date

        effective_date = as_of_date
        target = parsed_data.loc[parsed_data["_parsed_date"] == as_of_date]
        if target.empty:
            fallback_date = self._resolve_provider_effective_date(parsed_data, as_of_date)
            if fallback_date is None:
                return [], [], as_of_date
            effective_date = fallback_date
            target = parsed_data.loc[parsed_data["_parsed_date"] == effective_date]
            if target.empty:
                return [], [], as_of_date

        warnings: list[str] = self._resolve_provider_warnings(parsed_data)
        ranking: list[_SectorRankingItem] = []

        for sector, records in parsed_data.groupby("_sector", sort=False):
            history = records.sort_values("_parsed_date")
            target_rows = history.loc[history["_parsed_date"] == effective_date]
            if target_rows.empty:
                continue
            current = target_rows.iloc[-1]["_close"]

            history_unique = history.drop_duplicates(subset=["_parsed_date"], keep="last")
            if len(history_unique) < 21:
                if len(history_unique) > 1:
                    warnings.append(f"sector_rotation_data_insufficient:{sector}:history={len(history_unique)}")
                continue

            closes = history_unique.set_index("_parsed_date")["_close"]
            current_idx = closes.index.get_loc(effective_date)
            five_idx = current_idx - 5
            twenty_idx = current_idx - 20
            if five_idx < 0 or twenty_idx < 0:
                warnings.append(f"sector_rotation_data_insufficient:{sector}:history={len(history_unique)}")
                continue

            close_5 = closes.iloc[five_idx]
            close_20 = closes.iloc[twenty_idx]
            if close_5 == 0 or close_20 == 0:
                warnings.append(f"sector_rotation_invalid_base_value:{sector}")
                continue
            change_5 = (current - close_5) / close_5 * Decimal("100")
            change_20 = (current - close_20) / close_20 * Decimal("100")
            change_5_bp = self._to_int_bp(change_5)
            change_20_bp = self._to_int_bp(change_20)
            if change_5_bp is None or change_20_bp is None:
                warnings.append(f"sector_rotation_data_insufficient:{sector}")
                continue

            relative_strength = (change_5 + change_20) / Decimal("2")
            relative_strength_bp = self._to_int_bp(relative_strength)
            if relative_strength_bp is None:
                warnings.append(f"sector_rotation_data_insufficient:{sector}")
                continue

            ranking.append(
                {
                    "sector": sector,
                    "relative_strength_bp": relative_strength_bp,
                    "change_5d_bp": change_5_bp,
                    "change_20d_bp": change_20_bp,
                }
            )

        if not ranking:
            return [], warnings, effective_date

        # Stable deterministic ordering: strength desc, sector name asc.
        ranked = sorted(
            ranking,
            key=lambda item: (-item["relative_strength_bp"], item["sector"]),
        )

        deduped_meta: list[_SectorRankingItem] = []
        seen: set[str] = set()
        for item in ranked:
            sector = item["sector"]
            if sector in seen:
                continue
            seen.add(sector)
            deduped_meta.append(item)

        return deduped_meta, warnings, effective_date

    @staticmethod
    def _resolve_provider_effective_date(data: pd.DataFrame, requested_date: date) -> date | None:
        if "_sector_rotation_effective_as_of_date" not in data.columns:
            return None
        parsed = SectorRotationService._parse_date_series(data["_sector_rotation_effective_as_of_date"])
        if parsed is None:
            return None
        valid = [item for item in parsed.dropna().unique() if item <= requested_date]
        return max(valid) if valid else None

    @staticmethod
    def _resolve_provider_warnings(data: pd.DataFrame) -> list[str]:
        if "_sector_rotation_warnings" not in data.columns:
            return []
        warnings: list[str] = []
        for raw in data["_sector_rotation_warnings"].dropna().unique():
            for item in str(raw).split("|"):
                if item and item not in warnings:
                    warnings.append(item)
        return warnings

    @staticmethod
    def _resolve_source(data: pd.DataFrame) -> str | None:
        if "_sector_rotation_source" not in data.columns:
            return None
        values = [str(item) for item in data["_sector_rotation_source"].dropna().unique() if str(item)]
        return values[0] if values else None

    @staticmethod
    def _prepare_frame(data: pd.DataFrame) -> pd.DataFrame | None:
        if not isinstance(data, pd.DataFrame):
            return None
        if data.empty:
            return None
        return data.copy()

    @staticmethod
    def _resolve_date_column(frame: pd.DataFrame) -> str | None:
        for name in ("as_of_date", "date", "trade_date", "日期", "timestamp", "time", "datetime"):
            if name in frame.columns:
                return name
        return None

    @staticmethod
    def _resolve_sector_column(frame: pd.DataFrame) -> str | None:
        for name in ("sector", "industry", "industry_name", "sector_name", "產業", "產業別", "指數名稱"):
            if name in frame.columns:
                return name
        return None

    @staticmethod
    def _resolve_close_column(frame: pd.DataFrame) -> str | None:
        for name in ("close", "close_price", "close_index", "收盤指數", "收盤價", "close_price_adjusted"):
            if name in frame.columns:
                return name
        return None

    @staticmethod
    def _parse_date_series(values: pd.Series) -> pd.Series | None:
        parsed: list[date | None] = []
        for raw in values:
            parsed_date = SectorRotationService._parse_date_value(raw)
            if parsed_date is None:
                parsed.append(None)
            else:
                parsed.append(parsed_date)
        return pd.Series(parsed, index=values.index)

    @staticmethod
    def _parse_date_value(value: object) -> date | None:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if pd.isna(value):
            return None
        if isinstance(value, (int, float)):
            raw = str(int(value))
            return SectorRotationService._parse_date_str(raw, "%Y%m%d")
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%Y%m%d"):
                parsed = SectorRotationService._parse_date_str(value.strip(), fmt)
                if parsed is not None:
                    return parsed
        return None

    @staticmethod
    def _parse_date_str(raw: str, fmt: str) -> date | None:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            return None

    @staticmethod
    def _normalize_sector(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text if text else None
        return str(value).strip() if str(value).strip() else None

    @staticmethod
    def _to_decimal(value: object) -> Decimal | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, Integral):
            return Decimal(int(value))
        if isinstance(value, Real):
            try:
                return Decimal(str(value))
            except (ValueError, InvalidOperation, TypeError):
                return None
        if isinstance(value, str):
            text = value.strip().replace(",", "")
            if not text:
                return None
            if text.endswith("%"):
                text = text[:-1]
            try:
                return Decimal(text)
            except (ValueError, InvalidOperation):
                return None
        return None

    @staticmethod
    def _to_int_bp(value: Decimal | None) -> int | None:
        if value is None:
            return None
        try:
            return int((value * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except (ValueError, InvalidOperation, TypeError):
            return None


class SQLiteIndustryIndexSectorRotationProvider:
    """Read-only provider that supplies industry index history from SQLite."""

    def __init__(self, db_path: str | Path, *, lookback_days: int = 80):
        self.db_path = Path(db_path)
        self.lookback_days = lookback_days

    def fetch(self, as_of_date: date) -> pd.DataFrame:
        if not self.db_path.exists():
            return pd.DataFrame()

        target_key = as_of_date.strftime("%Y%m%d")
        with sqlite3.connect(self.db_path) as conn:
            date_rows = pd.read_sql_query(
                """
                SELECT DISTINCT 日期
                FROM industry_indices
                WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') <= ?
                ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') DESC
                LIMIT ?
                """,
                conn,
                params=(target_key, self.lookback_days),
            )
            if date_rows.empty:
                return pd.DataFrame()

            normalized_dates = [
                str(item).replace("-", "").replace("/", "")
                for item in date_rows["日期"].tolist()
            ]
            actual_key = normalized_dates[0]
            placeholders = ",".join("?" for _ in normalized_dates)
            history = pd.read_sql_query(
                f"""
                SELECT 日期, 指數名稱, 收盤指數
                FROM industry_indices
                WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') IN ({placeholders})
                ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') ASC, 指數名稱 ASC
                """,
                conn,
                params=tuple(normalized_dates),
            )

        if history.empty:
            return pd.DataFrame()

        actual_date = self._parse_date_key(actual_key)
        warnings: list[str] = []
        if actual_key != target_key and actual_date is not None:
            warnings.append(f"sector_rotation_as_of_fallback:{actual_date.isoformat()}")

        history["_sector_rotation_effective_as_of_date"] = actual_date.isoformat() if actual_date else actual_key
        history["_sector_rotation_warnings"] = "|".join(warnings)
        history["_sector_rotation_source"] = "sqlite_industry_indices"
        return history

    @staticmethod
    def _parse_date_key(value: str) -> date | None:
        try:
            return datetime.strptime(value, "%Y%m%d").date()
        except ValueError:
            return None
