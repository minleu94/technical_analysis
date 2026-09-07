"""
篩選服務 (Screening Service)
提供強勢股/產業篩選的業務邏輯
"""

from datetime import date, datetime
from typing import Any, Optional

import pandas as pd

# 方案 A：不搬檔案，service 層內部 import ui_app 模組
# from ui_app.stock_screener import StockScreener
# from ui_app.industry_mapper import IndustryMapper
from decision_module.stock_screener import StockScreener
from decision_module.industry_mapper import IndustryMapper
from app_module.dtos.market_loop_dtos import ScreeningResultDTO


class ScreeningService:
    """篩選服務類"""
    
    def __init__(
        self,
        config,
        industry_mapper: Optional[IndustryMapper] = None,
        stock_screener: Optional[StockScreener] = None,
    ):
        """初始化篩選服務
        
        Args:
            config: TWStockConfig 實例
            industry_mapper: IndustryMapper 實例（可選，如果為 None 則自動創建）
        """
        self.config = config
        if industry_mapper is None:
            self.industry_mapper = IndustryMapper(config)
        else:
            self.industry_mapper = industry_mapper
        self.stock_screener = stock_screener or StockScreener(
            config, self.industry_mapper
        )
    
    def get_strong_stocks(
        self, 
        period: str = 'day', 
        top_n: int = 20,
        min_volume: Optional[int] = None,
        decision_date: date | datetime | str | None = None,
        *,
        as_of_date: date | datetime | str | None = None,
    ) -> tuple[pd.DataFrame, int]:
        """獲取強勢股
        
        Args:
            period: 'day' 或 'week'，表示本日或本周
            top_n: 返回前N名
            min_volume: 最小成交量（可選）
            
        Returns:
            tuple: (DataFrame, universe_count)
                - DataFrame: 強勢股列表，包含排名、證券代號、證券名稱、收盤價、漲幅%、評分、推薦理由
                - universe_count: Universe 股票數量（有效數據的股票數）
        """
        requested = self._resolve_decision_date(decision_date, as_of_date)
        if requested is not None:
            return self.get_strong_stocks_dto(
                period=period,
                top_n=top_n,
                min_volume=min_volume,
                decision_date=requested,
            ).to_legacy()
        return self.stock_screener.get_strong_stocks(
            period=period,
            top_n=top_n,
            min_volume=min_volume
        )
    
    def get_strong_industries(
        self, 
        period: str = 'day', 
        top_n: int = 20,
        decision_date: date | datetime | str | None = None,
        *,
        as_of_date: date | datetime | str | None = None,
    ) -> pd.DataFrame:
        """獲取強勢產業
        
        Args:
            period: 'day' 或 'week'，表示本日或本周
            top_n: 返回前N名
            
        Returns:
            DataFrame: 強勢產業列表，包含排名、指數名稱、收盤指數、漲幅%
        """
        requested = self._resolve_decision_date(decision_date, as_of_date)
        if requested is not None:
            return self.get_strong_industries_dto(
                period=period,
                top_n=top_n,
                decision_date=requested,
            ).to_legacy()
        return self.stock_screener.get_strong_industries(
            period=period,
            top_n=top_n
        )
    
    def get_weak_stocks(
        self, 
        period: str = 'day', 
        top_n: int = 20,
        min_volume: Optional[int] = None,
        decision_date: date | datetime | str | None = None,
        *,
        as_of_date: date | datetime | str | None = None,
    ) -> tuple[pd.DataFrame, int]:
        """獲取弱勢股（與強勢股同架構，反向排名）
        
        Args:
            period: 'day' 或 'week'，表示本日或本周
            top_n: 返回前N名（最弱的）
            min_volume: 最小成交量（可選）
            
        Returns:
            tuple: (DataFrame, universe_count)
                - DataFrame: 弱勢股列表，包含排名、證券代號、證券名稱、收盤價、漲幅%、評分、推薦理由
                - universe_count: Universe 股票數量（有效數據的股票數）
        """
        requested = self._resolve_decision_date(decision_date, as_of_date)
        if requested is not None:
            return self.get_weak_stocks_dto(
                period=period,
                top_n=top_n,
                min_volume=min_volume,
                decision_date=requested,
            ).to_legacy()
        return self.stock_screener.get_weak_stocks(
            period=period,
            top_n=top_n,
            min_volume=min_volume
        )
    
    def get_weak_industries(
        self, 
        period: str = 'day', 
        top_n: int = 20,
        decision_date: date | datetime | str | None = None,
        *,
        as_of_date: date | datetime | str | None = None,
    ) -> pd.DataFrame:
        """獲取弱勢產業（與強勢產業同架構，反向排名）
        
        Args:
            period: 'day' 或 'week'，表示本日或本周
            top_n: 返回前N名（最弱的）
            
        Returns:
            DataFrame: 弱勢產業列表，包含排名、指數名稱、收盤指數、漲幅%
        """
        requested = self._resolve_decision_date(decision_date, as_of_date)
        if requested is not None:
            return self.get_weak_industries_dto(
                period=period,
                top_n=top_n,
                decision_date=requested,
            ).to_legacy()
        return self.stock_screener.get_weak_industries(
            period=period,
            top_n=top_n
        )

    def get_strong_stocks_dto(
        self,
        period: str = 'day',
        top_n: int = 20,
        min_volume: Optional[int] = None,
        decision_date: date | datetime | str | None = None,
        *,
        as_of_date: date | datetime | str | None = None,
    ) -> ScreeningResultDTO:
        return self._get_stock_dto(
            direction="strong",
            period=period,
            top_n=top_n,
            min_volume=min_volume,
            decision_date=self._resolve_decision_date(decision_date, as_of_date),
        )

    def get_weak_stocks_dto(
        self,
        period: str = 'day',
        top_n: int = 20,
        min_volume: Optional[int] = None,
        decision_date: date | datetime | str | None = None,
        *,
        as_of_date: date | datetime | str | None = None,
    ) -> ScreeningResultDTO:
        return self._get_stock_dto(
            direction="weak",
            period=period,
            top_n=top_n,
            min_volume=min_volume,
            decision_date=self._resolve_decision_date(decision_date, as_of_date),
        )

    def get_strong_industries_dto(
        self,
        period: str = 'day',
        top_n: int = 20,
        decision_date: date | datetime | str | None = None,
        *,
        as_of_date: date | datetime | str | None = None,
    ) -> ScreeningResultDTO:
        return self._get_industry_dto(
            direction="strong",
            period=period,
            top_n=top_n,
            decision_date=self._resolve_decision_date(decision_date, as_of_date),
        )

    def get_weak_industries_dto(
        self,
        period: str = 'day',
        top_n: int = 20,
        decision_date: date | datetime | str | None = None,
        *,
        as_of_date: date | datetime | str | None = None,
    ) -> ScreeningResultDTO:
        return self._get_industry_dto(
            direction="weak",
            period=period,
            top_n=top_n,
            decision_date=self._resolve_decision_date(decision_date, as_of_date),
        )

    def _get_stock_dto(
        self,
        *,
        direction: str,
        period: str,
        top_n: int,
        min_volume: Optional[int],
        decision_date: date | None,
    ) -> ScreeningResultDTO:
        frame = self._load_screening_frame("stocks", period)
        if frame is None:
            if decision_date is not None:
                return self._missing_screening_dto(
                    "stocks", direction, period, decision_date, "screening_source_unavailable"
                )
            try:
                legacy = (
                    self.stock_screener.get_strong_stocks(period, top_n, min_volume)
                    if direction == "strong"
                    else self.stock_screener.get_weak_stocks(period, top_n, min_volume)
                )
            except Exception as exc:  # noqa: BLE001
                return self._missing_screening_dto(
                    "stocks", direction, period, None, f"screening_error:{exc}"
                )
            return ScreeningResultDTO.from_legacy(
                legacy,
                result_kind="stocks",
                direction=direction,
                period=period,
                quality="degraded",
                warnings=("screening_decision_date_unverified",),
            )

        filtered, effective, quality, warnings = self._freeze_frame(frame, decision_date)
        if filtered.empty or effective is None:
            return self._missing_screening_dto(
                "stocks", direction, period, decision_date, "screening_missing_or_future_only"
            )
        try:
            builder = getattr(self.stock_screener, "_build_stock_screen_from_frame")
            result = builder(
                filtered.reset_index(drop=True),
                period,
                top_n,
                min_volume,
                direction,
            )
        except Exception as exc:  # noqa: BLE001
            return self._missing_screening_dto(
                "stocks", direction, period, decision_date, f"screening_error:{exc}"
            )
        return ScreeningResultDTO.from_legacy(
            result,
            result_kind="stocks",
            direction=direction,
            period=period,
            decision_date=decision_date,
            effective_date=effective,
            quality=quality,
            warnings=warnings,
            source_id="screening.stock_screener",
        )

    def _get_industry_dto(
        self,
        *,
        direction: str,
        period: str,
        top_n: int,
        decision_date: date | None,
    ) -> ScreeningResultDTO:
        frame = self._load_screening_frame("industries", period)
        if frame is None:
            if decision_date is not None:
                return self._missing_screening_dto(
                    "industries", direction, period, decision_date, "screening_source_unavailable"
                )
            try:
                legacy = (
                    self.stock_screener.get_strong_industries(period, top_n)
                    if direction == "strong"
                    else self.stock_screener.get_weak_industries(period, top_n)
                )
            except Exception as exc:  # noqa: BLE001
                return self._missing_screening_dto(
                    "industries", direction, period, None, f"screening_error:{exc}"
                )
            return ScreeningResultDTO.from_legacy(
                legacy,
                result_kind="industries",
                direction=direction,
                period=period,
                quality="degraded",
                warnings=("screening_decision_date_unverified",),
            )

        filtered, effective, quality, warnings = self._freeze_frame(frame, decision_date)
        if filtered.empty or effective is None:
            return self._missing_screening_dto(
                "industries", direction, period, decision_date, "screening_missing_or_future_only"
            )
        try:
            builder = getattr(self.stock_screener, "_build_industry_screen_from_frame")
            result = builder(filtered.reset_index(drop=True), top_n, direction)
        except Exception as exc:  # noqa: BLE001
            return self._missing_screening_dto(
                "industries", direction, period, decision_date, f"screening_error:{exc}"
            )
        eligible = self._industry_universe(filtered, effective)
        return ScreeningResultDTO.from_legacy(
            result,
            result_kind="industries",
            direction=direction,
            period=period,
            decision_date=decision_date,
            effective_date=effective,
            quality=quality,
            warnings=warnings,
            source_id="screening.stock_screener",
            ranking_method="legacy-industry-screener",
            eligible_universe_size=eligible,
        )

    def _load_screening_frame(self, kind: str, period: str) -> pd.DataFrame | None:
        method_name = (
            "_load_sqlite_recent_stock_prices"
            if kind == "stocks"
            else "_load_sqlite_recent_industry_indices"
        )
        loader = getattr(self.stock_screener, method_name, None)
        if not callable(loader):
            return None
        try:
            frame = loader(period)
        except Exception:
            return None
        return frame.copy() if isinstance(frame, pd.DataFrame) else None

    def _freeze_frame(
        self,
        frame: pd.DataFrame,
        decision_date: date | None,
    ) -> tuple[pd.DataFrame, date | None, str, tuple[str, ...]]:
        if "日期" not in frame.columns:
            return pd.DataFrame(), None, "degraded", ("screening_missing_date_column",)
        work = frame.copy()
        parsed = pd.to_datetime(
            work["日期"].astype(str).str.replace("-", "", regex=False).str.replace("/", "", regex=False),
            format="%Y%m%d",
            errors="coerce",
        )
        work = work.loc[parsed.notna()].copy()
        parsed = parsed.loc[work.index]
        if decision_date is not None:
            keep = parsed <= pd.Timestamp(decision_date)
            work = work.loc[keep].copy()
            parsed = parsed.loc[work.index]
        if work.empty or parsed.empty:
            return pd.DataFrame(), None, "missing", ("screening_missing_or_future_only",)
        effective = parsed.max().date()
        warnings: list[str] = []
        quality = "observed"
        if decision_date is not None and effective != decision_date:
            quality = "degraded"
            warnings.append(f"screening_as_of_fallback:{effective.isoformat()}")
        return work, effective, quality, tuple(warnings)

    @staticmethod
    def _industry_universe(frame: pd.DataFrame, effective: date) -> int:
        if "指數名稱" not in frame.columns:
            return 0
        parsed = pd.to_datetime(
            frame["日期"].astype(str).str.replace("-", "", regex=False).str.replace("/", "", regex=False),
            format="%Y%m%d",
            errors="coerce",
        )
        current = frame.loc[parsed == pd.Timestamp(effective), "指數名稱"]
        return int(current.dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique())

    @staticmethod
    def _missing_screening_dto(
        result_kind: str,
        direction: str,
        period: str,
        decision_date: date | None,
        warning: str,
    ) -> ScreeningResultDTO:
        return ScreeningResultDTO(
            result_kind=result_kind,
            direction=direction,
            period=period,
            decision_date=decision_date,
            effective_date=None,
            quality="missing",
            eligible_universe_size=0,
            rows=(),
            warnings=(warning,),
            source_id="screening.stock_screener",
        )

    @staticmethod
    def _resolve_decision_date(
        decision_date: date | datetime | str | None,
        as_of_date: date | datetime | str | None,
    ) -> date | None:
        raw = decision_date if decision_date is not None else as_of_date
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw.date()
        if isinstance(raw, date):
            return raw
        text = str(raw).strip().replace("/", "-")
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"invalid decision date: {raw}")

