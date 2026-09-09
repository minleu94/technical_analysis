"""唯讀、有限查詢的個股研究報告 read service。

每個 section 都在自己的 query boundary 內失敗隔離；呼叫端可以在單一
SQLite table 缺資料、來源過期或 optional owner 尚未接入時，仍取得其他
可用內容。這個 service 不寫 SQLite、不重跑推薦、不建立交易動作。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import inspect
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app_module.advice_composer import AdviceComposer
from app_module.advice_dtos import AdviceMode
from app_module.advice_policy import AdvicePolicy
from app_module.position_health_service import PositionHealthService
from app_module.portfolio_condition_monitor import (
    PortfolioConditionMonitor,
    PortfolioCurrentSnapshot,
)
from app_module.sqlite_read_only import ReadOnlySQLiteManager
from app_module.stock_research_report_dtos import (
    ReportFreshness,
    ReportQuality,
    ReportSectionStatus,
    StockAdviceSnapshotDTO,
    StockEvidenceEventDTO,
    StockFlowObservationDTO,
    StockFundamentalObservationDTO,
    StockMetricDTO,
    StockMLSnapshotDTO,
    StockOutcomeDTO,
    StockPositionSnapshotDTO,
    StockPricePointDTO,
    StockReportSectionDTO,
    StockReportSourceDTO,
    StockResearchReportDTO,
    StockTechnicalSnapshotDTO,
)
from app_module.watchlist_analysis_service import WatchlistAnalysisDTO, WatchlistAnalysisService


class StockResearchReportCancelled(RuntimeError):
    """報告讀取被 UI worker 合作式取消。"""


_TAIPEI = ZoneInfo("Asia/Taipei")
_PRICE_LIMIT = 120
_FLOW_LIMIT = 120
_FUNDAMENTAL_LIMIT = 24
_EVENT_LIMIT = 24
_FRESHNESS_MAX_BYTES = 4 * 1024 * 1024

# 報告 service 只讀 freshness probe 的既有出口。這些 alias 讓 SQLite
# read model 與 probe 的 upstream source id 對齊，不能以資料日重新推導月／季 cadence。
_FRESHNESS_SOURCE_ALIASES = {
    "sqlite.daily_prices": "sqlite.daily_prices",
    "sqlite.technical_indicators": "sqlite.technical_indicators",
    "sqlite.market_indices": "sqlite.market_indices",
    "sqlite.industry_indices": "sqlite.industry_indices",
    "sqlite.broker_flows": "sqlite.broker_flows",
    "sqlite.fundamental_monthly_revenues": "fundamental.monthly_revenues",
    "sqlite.fundamental_statement_items": "fundamental.quarterly_statements",
}
_FRESHNESS_STATUS_VALUES = {
    "current",
    "expected_wait",
    "stale",
    "failed",
    "partial",
    "not_applicable",
    "unknown",
}


class StockResearchReportReadService:
    """組合單一股票的既有研究來源，維持 PIT 與 read-only 邊界。"""

    def __init__(
        self,
        config: object,
        *,
        portfolio_service: object | None = None,
        watchlist_analysis_service: WatchlistAnalysisService | None = None,
        condition_monitor: PortfolioConditionMonitor | None = None,
        position_health_service: PositionHealthService | None = None,
        exit_provider: Callable[..., object] | None = None,
        ml_provider: Callable[..., object] | None = None,
        clock: Callable[[], datetime] | None = None,
        freshness_status_path: Path | str | None = None,
    ) -> None:
        self.config = config
        self.portfolio_service = portfolio_service
        self.watchlist_analysis_service = watchlist_analysis_service
        if self.watchlist_analysis_service is None and getattr(config, "output_root", None) is not None:
            self.watchlist_analysis_service = WatchlistAnalysisService(config)
        self.condition_monitor = condition_monitor
        self.position_health_service = position_health_service or PositionHealthService()
        self.exit_provider = exit_provider
        self.ml_provider = ml_provider
        self.clock = clock or (lambda: datetime.now(_TAIPEI))
        self.freshness_status_path = _resolve_freshness_status_path(config, freshness_status_path)
        # Worker 可能同時讀取不同股票；以 context-local snapshot 避免較慢的舊請求
        # 讀到新請求的 freshness receipt。每次 read_report 都會重新載入一次 bounded bytes。
        self._freshness_statuses: ContextVar[
            Mapping[str, Mapping[str, object]]
        ] = ContextVar("stock_research_report_freshness_statuses", default={})
        db_file = getattr(config, "db_file", None) or getattr(config, "sqlite_db_file", None)
        self.db = ReadOnlySQLiteManager(Path(db_file)) if db_file else None
        self._column_cache: dict[str, tuple[str, ...]] = {}

    def read_report(
        self,
        stock_code: str,
        *,
        as_of_date: date | str | None = None,
        context: object | None = None,
        cancel_callback: Callable[[], bool] | None = None,
    ) -> StockResearchReportDTO:
        """讀取一份完整投影；每一個資料區塊都有限制筆數且可被取消。"""

        code = _normalize_stock_code(stock_code)
        cutoff = _coerce_date(as_of_date) or self.clock().date()
        cutoff_text = cutoff.isoformat()
        self._freshness_statuses.set(self._load_freshness_statuses(cutoff))
        sources: list[StockReportSourceDTO] = []
        sections: list[StockReportSectionDTO] = []
        limitations: list[str] = []
        errors: list[str] = []
        context_map = _context_map(context)
        context_code = context_map.get("stock_code", "")
        name = (
            context_map.get("stock_name", "")
            if not context_code or context_code == code
            else ""
        )
        industry = ""

        price_points: tuple[StockPricePointDTO, ...] = ()
        price_source: StockReportSourceDTO | None = None
        try:
            self._check_cancel(cancel_callback)
            price_points, price_source, discovered_name = self._read_prices(code, cutoff)
            name = name or discovered_name
        except StockResearchReportCancelled:
            raise
        except Exception as exc:
            error = _error_text("價格", exc)
            errors.append(error)
            limitations.append(error)
            sections.append(self._error_section("price", "價格", error))
        else:
            if price_source is not None:
                self._register_source(sources, price_source)
            sections.append(
                self._data_section(
                    "price",
                    "價格",
                    len(price_points),
                    price_source,
                    missing_reason="找不到不晚於查詢日的價格資料；請從「數據更新」檢查行情來源。",
                )
            )

        technical: StockTechnicalSnapshotDTO | None = None
        technical_source: StockReportSourceDTO | None = None
        try:
            self._check_cancel(cancel_callback)
            technical, technical_source = self._read_technical(code, cutoff)
        except StockResearchReportCancelled:
            raise
        except Exception as exc:
            error = _error_text("技術指標", exc)
            errors.append(error)
            limitations.append(error)
            sections.append(self._error_section("technical", "技術指標", error))
        else:
            if technical_source is not None:
                self._register_source(sources, technical_source)
            sections.append(
                self._data_section(
                    "technical",
                    "技術指標",
                    len(technical.indicators) if technical is not None else 0,
                    technical_source,
                    missing_reason="找不到不晚於查詢日的技術指標；請先更新技術資料。",
                )
            )

        fundamentals: tuple[StockFundamentalObservationDTO, ...] = ()
        fundamental_sources: tuple[StockReportSourceDTO, ...] = ()
        try:
            self._check_cancel(cancel_callback)
            fundamentals, fundamental_sources, discovered_industry = self._read_fundamentals(code, cutoff)
            industry = discovered_industry
        except StockResearchReportCancelled:
            raise
        except Exception as exc:
            error = _error_text("基本面", exc)
            errors.append(error)
            limitations.append(error)
            sections.append(self._error_section("fundamental", "基本面", error))
        else:
            for source in fundamental_sources:
                self._register_source(sources, source)
            sections.append(
                self._data_section(
                    "fundamental",
                    "基本面／營收財報",
                    len(fundamentals),
                    fundamental_sources,
                    missing_reason="沒有可用的公告／可得日基本面資料；不以缺資料推論利空。",
                )
            )

        flows: tuple[StockFlowObservationDTO, ...] = ()
        flow_source: StockReportSourceDTO | None = None
        try:
            self._check_cancel(cancel_callback)
            flows, flow_source = self._read_flows(code, cutoff)
        except StockResearchReportCancelled:
            raise
        except Exception as exc:
            error = _error_text("籌碼／分點", exc)
            errors.append(error)
            limitations.append(error)
            sections.append(self._error_section("flows", "籌碼／法人分點", error))
        else:
            if flow_source is not None:
                self._register_source(sources, flow_source)
            sections.append(
                self._data_section(
                    "flows",
                    "籌碼／法人分點",
                    len(flows),
                    flow_source,
                    missing_reason="找不到不晚於查詢日的分點資料；請從「數據更新」檢查籌碼來源。",
                )
            )

        institutional: tuple[StockMetricDTO, ...] = ()
        credit: tuple[StockMetricDTO, ...] = ()
        shareholding: tuple[StockMetricDTO, ...] = ()
        market_sources: tuple[StockReportSourceDTO, ...] = ()
        try:
            self._check_cancel(cancel_callback)
            institutional, credit, shareholding, market_sources = self._read_market_ownership(code, cutoff)
        except StockResearchReportCancelled:
            raise
        except Exception as exc:
            error = _error_text("法人／信用／集保", exc)
            errors.append(error)
            limitations.append(error)
            sections.append(self._error_section("ownership", "法人／信用／集保", error))
        else:
            for source in market_sources:
                self._register_source(sources, source)
            ownership_count = len(institutional) + len(credit) + len(shareholding)
            sections.append(
                self._data_section(
                    "ownership",
                    "法人／信用／集保",
                    ownership_count,
                    market_sources,
                    missing_reason="此股票目前沒有可用的法人、信用或集保 row；不以空白補零。",
                )
            )

        events: tuple[StockEvidenceEventDTO, ...] = ()
        evidence_source: StockReportSourceDTO | None = None
        try:
            self._check_cancel(cancel_callback)
            events, evidence_source = self._read_events(code, cutoff)
        except StockResearchReportCancelled:
            raise
        except Exception as exc:
            error = _error_text("產業／事件／歷史結果", exc)
            errors.append(error)
            limitations.append(error)
            sections.append(self._error_section("events", "產業／事件／歷史結果", error))
        else:
            if evidence_source is not None:
                self._register_source(sources, evidence_source)
            sections.append(
                self._data_section(
                    "events",
                    "產業／事件／歷史建議結果",
                    len(events),
                    evidence_source,
                    missing_reason="沒有可追溯的事件或後續結果；不把空白當成中性績效證據。",
                )
            )
            if not industry:
                industry = _first_non_empty(*(event.event_family for event in events))

        position: StockPositionSnapshotDTO | None = None
        position_source: StockReportSourceDTO | None = None
        try:
            self._check_cancel(cancel_callback)
            position, position_source = self._read_position(code, cutoff)
        except StockResearchReportCancelled:
            raise
        except Exception as exc:
            error = _error_text("持倉／Health／Exit", exc)
            errors.append(error)
            limitations.append(error)
            sections.append(self._error_section("position", "持倉／Health／Exit", error))
        else:
            if position_source is not None:
                self._register_source(sources, position_source)
            sections.append(
                self._data_section(
                    "position",
                    "持倉／Health／Exit",
                    1 if position is not None and position.is_holding else 0,
                    position_source,
                    missing_reason="此股票目前不在持倉；Health／Exit 只對現有持倉提供判讀。",
                )
            )
            if position is not None:
                limitations.extend(position.limitations)

        advice = StockAdviceSnapshotDTO()
        try:
            self._check_cancel(cancel_callback)
            advice, advice_source = self._read_advice(code, cutoff, context_map)
        except StockResearchReportCancelled:
            raise
        except Exception as exc:
            error = _error_text("Advice", exc)
            errors.append(error)
            limitations.append(error)
            advice = StockAdviceSnapshotDTO(
                status=ReportQuality.UNAVAILABLE.value,
                limitations=(error,),
            )
            advice_source = None
            sections.append(self._error_section("advice", "既有建議與依據", error))
        else:
            if advice_source is not None:
                self._register_source(sources, advice_source)
            limitations.extend(advice.limitations)
            sections.append(
                self._data_section(
                    "advice",
                    "既有建議與依據",
                    1 if advice.recommendation is not None else 0,
                    advice_source,
                    missing_reason="沒有可用的已保存 Advice／推薦契約；請從推薦分析保存研究結果。",
                )
            )

        ml_error = ""
        try:
            self._check_cancel(cancel_callback)
            ml = self._read_ml(code, cutoff)
        except StockResearchReportCancelled:
            raise
        except Exception as exc:
            error = _error_text("ML", exc)
            errors.append(error)
            limitations.append(error)
            ml = StockMLSnapshotDTO(
                status=ReportQuality.UNAVAILABLE.value,
                limitations=(error,),
            )
            ml_error = error
        limitations.extend(ml.limitations)
        if ml_error:
            sections.append(self._error_section("ml", "ML 研究結果", ml_error))
        else:
            sections.append(
                self._data_section(
                    "ml",
                    "ML 研究結果",
                    1 if ml.status not in {ReportQuality.UNAVAILABLE.value, ReportQuality.MISSING.value} else 0,
                    self._ml_source(ml, cutoff),
                    missing_reason="尚未接入合格的個股 ML read model；不顯示機率、目標價或勝率。",
                )
            )

        rule_reasons = _dedupe(
            (*advice.rule_reasons,)
            + tuple(
                reason
                for event in events
                for reason in (*event.reasons, *event.why_not_reasons, *event.risk_reasons)
            )
        )
        ml_reasons = tuple(ml.explanations)
        if ml.status not in {ReportQuality.UNAVAILABLE.value, ReportQuality.MISSING.value}:
            advice = _with_advice_agreement(advice, rule_reasons, ml_reasons)

        if self.db is None:
            limitations.append("未配置 SQLite；此報告只顯示可由外部 provider 提供的資料。")
        limitations.extend(errors)
        limitations = list(_dedupe(limitations))
        attention_reasons = _attention_reasons(price_points, fundamentals, flows, sections, advice, position)
        key_risks = _key_risks(advice, events, position, limitations)
        available_modules = tuple(
            module
            for module, available in (
                ("price", bool(price_points)),
                ("technical", technical is not None and bool(technical.indicators)),
                ("fundamental", bool(fundamentals)),
                ("flows", bool(flows)),
                ("ownership", bool(institutional or credit or shareholding)),
                ("industry_events", bool(events)),
                ("history", bool(events)),
                ("position", position is not None and position.is_holding),
                ("health", position is not None and bool(position.health_status)),
                ("advice", advice.recommendation is not None),
                ("ml", ml.status not in {ReportQuality.UNAVAILABLE.value, ReportQuality.MISSING.value}),
            )
            if available
        )

        return StockResearchReportDTO(
            stock_code=code,
            stock_name=name,
            market="台股",
            industry=industry,
            as_of=cutoff_text,
            generated_at=self.clock().isoformat(timespec="seconds"),
            sources=tuple(sources),
            sections=tuple(sections),
            available_modules=available_modules,
            attention_reasons=attention_reasons,
            key_risks=key_risks,
            limitations=tuple(limitations),
            price_points=price_points,
            technical=technical,
            fundamentals=fundamentals,
            flows=flows,
            institutional=institutional,
            credit=credit,
            shareholding=shareholding,
            events=events,
            position=position,
            advice=advice,
            ml=ml,
            rule_reasons=rule_reasons,
            research_context=context_map,
        )

    def _read_prices(
        self,
        code: str,
        cutoff: date,
    ) -> tuple[tuple[StockPricePointDTO, ...], StockReportSourceDTO | None, str]:
        table = "daily_prices"
        columns = self._columns(table)
        if not columns:
            return (), None, ""
        date_col = _pick(columns, "日期", "Date")
        code_col = _pick(columns, "證券代號", "stock_code", "Code")
        if date_col is None or code_col is None:
            raise ValueError("daily_prices 缺少股票代號／日期欄位")
        sql = f"""
            SELECT {_select_column(columns, ("日期", "Date"), "data_date")},
                   {_select_column(columns, ("證券名稱", "stock_name"), "stock_name")},
                   {_select_column(columns, ("開盤價", "Open"), "open_price")},
                   {_select_column(columns, ("最高價", "High"), "high_price")},
                   {_select_column(columns, ("最低價", "Low"), "low_price")},
                   {_select_column(columns, ("收盤價", "Close"), "close_price")},
                   {_select_column(columns, ("成交股數", "Volume"), "volume")},
                   {_select_column(columns, ("成交金額",), "turnover")},
                   {_select_column(columns, ("漲跌價差",), "change")}
            FROM {self._table(table)}
            WHERE {_quote(code_col)} = ?
              AND {_non_empty_expr(date_col)}
              AND {_date_key_expr(date_col)} <= ?
            ORDER BY {_date_key_expr(date_col)} DESC
            LIMIT ?
        """
        rows = self._query(sql, (code, _date_key(cutoff), _PRICE_LIMIT))
        points: list[StockPricePointDTO] = []
        for row in reversed(rows):
            data_date = _iso_date(row["data_date"])
            if not data_date:
                continue
            points.append(
                StockPricePointDTO(
                    data_date=data_date,
                    open_price=_decimal(row["open_price"]),
                    high_price=_decimal(row["high_price"]),
                    low_price=_decimal(row["low_price"]),
                    close_price=_decimal(row["close_price"]),
                    volume=_integer(row["volume"]),
                    turnover=_decimal(row["turnover"]),
                    change=_decimal(row["change"]),
                    source_id="sqlite.daily_prices",
                    quality=ReportQuality.OBSERVED.value,
                )
            )
        latest = points[-1] if points else None
        name = str(rows[0]["stock_name"] or "").strip() if rows else ""
        source = self._source(
            "sqlite.daily_prices",
            "SQLite 日價格",
            row_count=len(points),
            data_as_of=latest.data_date if latest else "",
            quality=ReportQuality.OBSERVED.value if points else ReportQuality.MISSING.value,
            cutoff=cutoff,
            limitations=("來源未提供 available_at；資料可得時間沿用來源契約外資訊。",),
        )
        return tuple(points), source, name

    def _read_technical(
        self,
        code: str,
        cutoff: date,
    ) -> tuple[StockTechnicalSnapshotDTO | None, StockReportSourceDTO | None]:
        table = "technical_indicators"
        columns = self._columns(table)
        if not columns:
            return None, None
        date_col = _pick(columns, "日期", "Date")
        code_col = _pick(columns, "證券代號", "stock_code", "Code")
        if date_col is None or code_col is None:
            raise ValueError("technical_indicators 缺少股票代號／日期欄位")
        indicator_columns = (
            ("RSI", "RSI"),
            ("MACD", "MACD"),
            ("MACD_signal", "MACD signal"),
            ("MACD_hist", "MACD histogram"),
            ("MA5", "MA5"),
            ("MA10", "MA10"),
            ("MA20", "MA20"),
            ("MA60", "MA60"),
            ("ATR", "ATR"),
            ("ADX", "ADX"),
        )
        select = [_select_column(columns, ("日期", "Date"), "data_date")]
        select.extend(_select_column(columns, (key,), key) for key, _label in indicator_columns)
        sql = f"""
            SELECT {", ".join(select)}
            FROM {self._table(table)}
            WHERE {_quote(code_col)} = ?
              AND {_non_empty_expr(date_col)}
              AND {_date_key_expr(date_col)} <= ?
            ORDER BY {_date_key_expr(date_col)} DESC
            LIMIT 1
        """
        rows = self._query(sql, (code, _date_key(cutoff)))
        if not rows:
            source = self._source(
                "sqlite.technical_indicators",
                "SQLite 技術指標",
                row_count=0,
                data_as_of="",
                quality=ReportQuality.MISSING.value,
                cutoff=cutoff,
            )
            return None, source
        row = rows[0]
        data_date = _iso_date(row["data_date"])
        indicators = tuple(
            StockMetricDTO(
                key=key,
                label=label,
                value=_decimal(row[key]),
                data_as_of=data_date,
                source_id="sqlite.technical_indicators",
                quality=ReportQuality.OBSERVED.value,
            )
            for key, label in indicator_columns
            if _decimal(row[key]) is not None
        )
        technical = StockTechnicalSnapshotDTO(
            data_date=data_date,
            indicators=indicators,
            source_id="sqlite.technical_indicators",
            quality=ReportQuality.OBSERVED.value if indicators else ReportQuality.DEGRADED.value,
            limitations=("來源未提供 available_at。",) if indicators else ("最新 row 沒有可呈現的指標欄位。",),
        )
        source = self._source(
            "sqlite.technical_indicators",
            "SQLite 技術指標",
            row_count=1 if indicators else 0,
            data_as_of=data_date,
            quality=technical.quality,
            cutoff=cutoff,
            limitations=technical.limitations,
        )
        return technical, source

    def _read_fundamentals(
        self,
        code: str,
        cutoff: date,
    ) -> tuple[
        tuple[StockFundamentalObservationDTO, ...],
        tuple[StockReportSourceDTO, ...],
        str,
    ]:
        observations: list[StockFundamentalObservationDTO] = []
        sources: list[StockReportSourceDTO] = []
        industry = ""
        configurations = (
            (
                "fundamental_monthly_revenues",
                "SQLite 月營收",
                "monthly_revenue",
                "月營收",
                ("revenue",),
                _FUNDAMENTAL_LIMIT,
            ),
            (
                "fundamental_statement_items",
                "SQLite 財報項目",
                "statement_item",
                "財報項目",
                ("value",),
                _FUNDAMENTAL_LIMIT,
            ),
            (
                "fundamental_valuation_metrics",
                "SQLite 估值指標",
                "valuation",
                "估值",
                ("value",),
                12,
            ),
        )
        for table, label, kind, default_label, value_candidates, limit in configurations:
            columns = self._columns(table)
            if not columns:
                continue
            code_col = _pick(columns, "stock_code", "證券代號")
            available_col = _pick(columns, "available_date", "available_at")
            if code_col is None or available_col is None:
                raise ValueError(f"{table} 缺少 stock_code／available_date 欄位")
            if table == "fundamental_monthly_revenues":
                select = (
                    _select_column(columns, ("period",), "period"),
                    _select_column(columns, ("as_of_date",), "as_of_date"),
                    _select_column(columns, ("announced_date",), "announced_date"),
                    _select_column(columns, ("available_date", "available_at"), "available_at"),
                    _select_column(columns, ("revenue",), "value"),
                    _select_column(columns, ("source",), "source"),
                    _select_column(columns, ("source_version",), "source_version"),
                    _select_column(columns, ("quality",), "quality"),
                    "NULL AS item_label",
                    "NULL AS industry",
                )
            elif table == "fundamental_statement_items":
                select = (
                    _select_column(columns, ("period",), "period"),
                    _select_column(columns, ("as_of_date",), "as_of_date"),
                    _select_column(columns, ("announced_date",), "announced_date"),
                    _select_column(columns, ("available_date", "available_at"), "available_at"),
                    _select_column(columns, value_candidates, "value"),
                    _select_column(columns, ("source",), "source"),
                    _select_column(columns, ("source_version",), "source_version"),
                    _select_column(columns, ("quality",), "quality"),
                    _select_column(columns, ("item_name",), "item_label"),
                    "NULL AS industry",
                )
            else:
                select = (
                    "NULL AS period",
                    _select_column(columns, ("as_of_date",), "as_of_date"),
                    "NULL AS announced_date",
                    _select_column(columns, ("available_date", "available_at"), "available_at"),
                    _select_column(columns, value_candidates, "value"),
                    _select_column(columns, ("source",), "source"),
                    _select_column(columns, ("source_version",), "source_version"),
                    _select_column(columns, ("quality",), "quality"),
                    _select_column(columns, ("metric_name",), "item_label"),
                    _select_column(columns, ("industry",), "industry"),
                )
            period_col = _pick(columns, "period")
            as_of_col = _pick(columns, "as_of_date")
            period_fallback = (
                f"TRIM(CAST({_quote(period_col)} AS TEXT))"
                if period_col is not None
                else "''"
            )
            if as_of_col is not None and period_col is not None:
                # 所有基本面表都有 as_of_date；period 只作缺少 as_of
                # 時的 fallback，避免比較 2024-Q1／2024Q1 等字串格式。
                report_period_order = (
                    f"CASE WHEN {_non_empty_expr(as_of_col)} "
                    f"THEN {_date_key_expr(as_of_col)} "
                    f"ELSE {period_fallback} END"
                )
            elif as_of_col is not None:
                report_period_order = _date_key_expr(as_of_col)
            elif period_col is not None:
                report_period_order = period_fallback
            else:
                report_period_order = "''"
            # 先選最新公告 period／as_of，再在同一期內選較晚可得版本；
            # 不讓歷史 row 因為 available_date 較晚而擠掉最新報告期。
            sql = f"""
                SELECT {", ".join(select)}
            FROM {self._table(table)}
            WHERE {_quote(code_col)} = ?
                  AND {_non_empty_expr(available_col)}
                  AND {_date_key_expr(available_col)} <= ?
                ORDER BY {report_period_order} DESC,
                         {_date_key_expr(available_col)} DESC
                LIMIT ?
            """
            rows = self._query(sql, (code, _date_key(cutoff), limit))
            source_id = f"sqlite.{table}"
            for row in rows:
                available_at = _iso_date(row["available_at"])
                data_as_of = _iso_date(row["as_of_date"]) or _iso_date(row["period"])
                quality = _quality(row["quality"])
                observations.append(
                    StockFundamentalObservationDTO(
                        kind=kind,
                        label=str(row["item_label"] or default_label),
                        period=str(row["period"] or ""),
                        as_of_date=data_as_of,
                        announced_date=_iso_date(row["announced_date"]),
                        available_at=available_at,
                        value=_decimal(row["value"]),
                        value_text="" if _decimal(row["value"]) is not None else str(row["value"] or ""),
                        unit="TWD" if kind == "monthly_revenue" else "",
                        source_id=source_id,
                        source_version=str(row["source_version"] or ""),
                        quality=quality,
                    )
                )
                industry = industry or str(row["industry"] or "").strip()
            source = self._source(
                source_id,
                label,
                row_count=len(rows),
                data_as_of=_latest_text(_iso_date(row["as_of_date"]) for row in rows),
                # 月／季的 freshness period 必須使用公告 period，不能把
                # available_at／as_of_date 當成 period 與 probe 比對。
                period=_latest_text(str(row["period"] or "") for row in rows),
                available_at=_latest_text(_iso_date(row["available_at"]) for row in rows),
                version=_latest_text(str(row["source_version"] or "") for row in rows),
                quality=_worst_quality(_quality(row["quality"]) for row in rows),
                cutoff=cutoff,
                limitations=("只接受 available_date 不晚於查詢日的 row。",),
            )
            sources.append(source)
        return tuple(observations), tuple(sources), industry

    def _read_flows(
        self,
        code: str,
        cutoff: date,
    ) -> tuple[tuple[StockFlowObservationDTO, ...], StockReportSourceDTO | None]:
        table = "broker_flows"
        columns = self._columns(table)
        if not columns:
            return (), None
        date_col = _pick(columns, "日期", "data_date")
        code_col = _pick(columns, "證券代號", "stock_code")
        if date_col is None or code_col is None:
            raise ValueError("broker_flows 缺少股票代號／日期欄位")
        select = (
            _select_column(columns, ("日期", "data_date"), "data_date"),
            _select_column(columns, ("分點名稱", "branch_name"), "branch_name"),
            _select_column(columns, ("買進股數", "buy_shares"), "buy_shares"),
            _select_column(columns, ("賣出股數", "sell_shares"), "sell_shares"),
            _select_column(columns, ("買賣超股數", "net_shares"), "net_shares"),
            _select_column(columns, ("買進金額千元", "buy_amount_thousand"), "buy_amount_thousand"),
            _select_column(columns, ("賣出金額千元", "sell_amount_thousand"), "sell_amount_thousand"),
            _select_column(columns, ("買賣超金額千元", "net_amount_thousand"), "net_amount_thousand"),
            _select_column(columns, ("trade_type",), "trade_type"),
            _select_column(columns, ("lots_observed",), "lots_observed"),
            _select_column(columns, ("amount_observed",), "amount_observed"),
        )
        sql = f"""
            SELECT {", ".join(select)}
            FROM {self._table(table)}
            WHERE {_quote(code_col)} = ?
              AND {_non_empty_expr(date_col)}
              AND {_date_key_expr(date_col)} <= ?
            ORDER BY {_date_key_expr(date_col)} DESC,
                     ABS(COALESCE({_select_raw(columns, ("買賣超股數", "net_shares"))}, 0)) DESC
            LIMIT ?
        """
        rows = self._query(sql, (code, _date_key(cutoff), _FLOW_LIMIT))
        flows: list[StockFlowObservationDTO] = []
        for row in rows:
            observed_flags = (_integer(row["lots_observed"]), _integer(row["amount_observed"]))
            quality = (
                ReportQuality.OBSERVED.value
                if any(flag == 1 for flag in observed_flags)
                else ReportQuality.DEGRADED.value
            )
            flows.append(
                StockFlowObservationDTO(
                    data_date=_iso_date(row["data_date"]),
                    branch_name=str(row["branch_name"] or "未提供分點"),
                    buy_shares=_integer(row["buy_shares"]),
                    sell_shares=_integer(row["sell_shares"]),
                    net_shares=_integer(row["net_shares"]),
                    buy_amount_thousand=_decimal(row["buy_amount_thousand"]),
                    sell_amount_thousand=_decimal(row["sell_amount_thousand"]),
                    net_amount_thousand=_decimal(row["net_amount_thousand"]),
                    trade_type=str(row["trade_type"] or ""),
                    source_id="sqlite.broker_flows",
                    quality=quality,
                )
            )
        source = self._source(
            "sqlite.broker_flows",
            "SQLite 分點買賣",
            row_count=len(flows),
            data_as_of=_latest_text(flow.data_date for flow in flows),
            quality=_worst_quality(flow.quality for flow in flows),
            cutoff=cutoff,
            limitations=("來源未提供 available_at；僅呈現有限筆數的近五日候選 row。",),
        )
        return tuple(flows), source

    def _read_market_ownership(
        self,
        code: str,
        cutoff: date,
    ) -> tuple[
        tuple[StockMetricDTO, ...],
        tuple[StockMetricDTO, ...],
        tuple[StockMetricDTO, ...],
        tuple[StockReportSourceDTO, ...],
    ]:
        specifications = (
            (
                "institutional_flows",
                "SQLite 法人買賣超",
                (
                    ("foreign_investor_buy", "外資買進"),
                    ("foreign_investor_sell", "外資賣出"),
                    ("foreign_investor_net", "外資淨額"),
                    ("investment_trust_buy", "投信買進"),
                    ("investment_trust_sell", "投信賣出"),
                    ("investment_trust_net", "投信淨額"),
                    ("dealer_buy", "自營商買進"),
                    ("dealer_sell", "自營商賣出"),
                    ("dealer_net", "自營商淨額"),
                ),
                "institutional",
            ),
            (
                "credit_transactions",
                "SQLite 信用交易",
                (
                    ("margin_purchase", "融資買進"),
                    ("margin_balance", "融資餘額"),
                    ("short_sale", "融券賣出"),
                    ("short_balance", "融券餘額"),
                    ("financing", "借券融通"),
                    ("securities_lending", "借券"),
                ),
                "credit",
            ),
            (
                "tdcc_shareholding",
                "SQLite 集保股權分級",
                (
                    ("large_holder_ratio_bp", "大戶持股比例"),
                    ("retail_holder_ratio_bp", "散戶持股比例"),
                    ("dispersion_index_bp", "持股分散指標"),
                    ("shareholding_tiers", "持股級距"),
                ),
                "shareholding",
            ),
        )
        result: dict[str, tuple[StockMetricDTO, ...]] = {
            "institutional": (),
            "credit": (),
            "shareholding": (),
        }
        sources: list[StockReportSourceDTO] = []
        for table, label, fields, result_key in specifications:
            columns = self._columns(table)
            if not columns:
                continue
            code_col = _pick(columns, "stock_code", "證券代號")
            decision_col = _pick(columns, "decision_date", "日期")
            available_col = _pick(columns, "available_date", "available_at")
            if code_col is None or decision_col is None:
                raise ValueError(f"{table} 缺少股票代號／決策日欄位")
            filters = [
                f"{_quote(code_col)} = ?",
                f"{_non_empty_expr(decision_col)}",
                f"{_date_key_expr(decision_col)} <= ?",
            ]
            params_list: list[Any] = [code, _date_key(cutoff)]
            if available_col:
                filters.extend(
                    (
                        f"{_non_empty_expr(available_col)}",
                        f"{_date_key_expr(available_col)} <= ?",
                    )
                )
                params_list.append(_date_key(cutoff))
            select = [
                _select_column(columns, ("decision_date", "日期"), "data_as_of"),
                _select_column(columns, ("available_date", "available_at"), "available_at"),
                _select_column(columns, ("source_version",), "source_version"),
                _select_column(columns, ("quality",), "quality"),
            ]
            select.extend(_select_column(columns, (key,), key) for key, _label in fields)
            sql = f"""
                SELECT {", ".join(select)}
                FROM {self._table(table)}
                WHERE {" AND ".join(filters)}
                ORDER BY {_date_key_expr(decision_col)} DESC
                LIMIT 1
            """
            rows = self._query(sql, tuple(params_list))
            metrics: list[StockMetricDTO] = []
            if rows:
                row = rows[0]
                data_as_of = _iso_date(row["data_as_of"])
                available_at = _iso_date(row["available_at"])
                quality = _quality(row["quality"])
                for key, field_label in fields:
                    raw = row[key]
                    number = _decimal(raw)
                    text_value = "" if number is not None else str(raw or "")
                    if number is None and not text_value:
                        continue
                    metrics.append(
                        StockMetricDTO(
                            key=key,
                            label=field_label,
                            value=number,
                            value_text=text_value,
                            unit="bp" if key.endswith("_bp") else "",
                            data_as_of=data_as_of,
                            available_at=available_at,
                            source_id=f"sqlite.{table}",
                            quality=quality,
                        )
                    )
            result[result_key] = tuple(metrics)
            sources.append(
                self._source(
                    f"sqlite.{table}",
                    label,
                    row_count=len(metrics),
                    data_as_of=_iso_date(rows[0]["data_as_of"]) if rows else "",
                    available_at=_iso_date(rows[0]["available_at"]) if rows else "",
                    version=str(rows[0]["source_version"] or "") if rows else "",
                    quality=_quality(rows[0]["quality"]) if rows else ReportQuality.MISSING.value,
                    cutoff=cutoff,
                    limitations=("沒有該股票 row 時維持缺資料，不補零。",),
                )
            )
        return result["institutional"], result["credit"], result["shareholding"], tuple(sources)

    def _read_events(
        self,
        code: str,
        cutoff: date,
    ) -> tuple[tuple[StockEvidenceEventDTO, ...], StockReportSourceDTO | None]:
        table = "evidence_events"
        columns = self._columns(table)
        if not columns:
            return (), None
        symbol_col = _pick(columns, "symbol", "stock_code", "證券代號")
        available_col = _pick(columns, "available_date", "available_at")
        decision_col = _pick(columns, "decision_date", "日期")
        if symbol_col is None or decision_col is None:
            raise ValueError("evidence_events 缺少 symbol／decision_date 欄位")
        if available_col is None:
            raise ValueError("evidence_events 缺少 available_date，拒絕猜測 PIT 可用時間")
        fields = (
            "event_id", "event_date", "decision_date", "event_type", "event_family",
            "source_type", "source_id", "source_version", "data_quality", "as_of_date",
            "available_at", "reason_codes_json", "why_not_codes_json", "risk_codes_json",
            "warnings_json", "score_bp",
        )
        select = []
        for field_name in fields:
            source_names: tuple[str, ...] = (field_name,)
            if field_name == "data_quality":
                source_names = ("data_quality", "quality")
            elif field_name == "available_at":
                source_names = ("available_at", "available_date")
            select.append(_select_column(columns, source_names, field_name))
        sql = f"""
            SELECT {", ".join(select)}
            FROM {self._table(table)}
            WHERE {_quote(symbol_col)} = ?
              AND {_non_empty_expr(available_col)}
              AND {_date_key_expr(available_col)} <= ?
              AND {_non_empty_expr(decision_col)}
              AND {_date_key_expr(decision_col)} <= ?
            ORDER BY {_date_key_expr(decision_col)} DESC
            LIMIT ?
        """
        rows = self._query(sql, (code, _date_key(cutoff), _date_key(cutoff), _EVENT_LIMIT))
        event_ids = tuple(str(row["event_id"] or "") for row in rows if row["event_id"])
        outcomes = self._read_outcomes(event_ids, cutoff) if event_ids else {}
        events = tuple(
            StockEvidenceEventDTO(
                event_id=str(row["event_id"] or ""),
                event_date=_iso_date(row["event_date"]),
                decision_date=_iso_date(row["decision_date"]),
                event_type=str(row["event_type"] or ""),
                event_family=str(row["event_family"] or ""),
                source_type=str(row["source_type"] or ""),
                source_id=str(row["source_id"] or ""),
                source_version=str(row["source_version"] or ""),
                data_quality=str(row["data_quality"] or ""),
                as_of_date=_iso_date(row["as_of_date"]),
                available_at=_iso_date(row["available_at"]),
                reasons=_json_strings(row["reason_codes_json"]),
                why_not_reasons=_json_strings(row["why_not_codes_json"]),
                risk_reasons=_json_strings(row["risk_codes_json"]),
                warnings=_json_strings(row["warnings_json"]),
                score_bp=_integer(row["score_bp"]),
                outcomes=outcomes.get(str(row["event_id"] or ""), ()),
            )
            for row in rows
        )
        source = self._source(
            "sqlite.evidence_events",
            "SQLite 事件與 Evidence",
            row_count=len(events),
            data_as_of=_latest_text(event.decision_date for event in events),
            available_at=_latest_text(event.available_at for event in events),
            version=_latest_text(event.source_version for event in events),
            quality=_worst_quality(
                _quality(event.data_quality) for event in events
            ),
            cutoff=cutoff,
            limitations=("只讀取 available_date 不晚於查詢日的有限歷史 row；沒有 outcome 不補績效。",),
        )
        return events, source

    def _read_outcomes(
        self,
        event_ids: Sequence[str],
        cutoff: date,
    ) -> dict[str, tuple[StockOutcomeDTO, ...]]:
        table = "evidence_outcomes"
        columns = self._columns(table)
        if not columns or not event_ids:
            return {}
        event_col = _pick(columns, "event_id")
        if event_col is None:
            return {}
        calculated_col = _pick(columns, "calculated_at", "available_at")
        if calculated_col is None:
            return {}
        placeholders = ", ".join("?" for _ in event_ids)
        select = (
            _select_column(columns, ("event_id",), "event_id"),
            _select_column(columns, ("window_days",), "window_days"),
            _select_column(columns, ("outcome_status",), "outcome_status"),
            _select_column(columns, ("forward_return_bp",), "forward_return_bp"),
            _select_column(columns, ("benchmark_excess_bp",), "benchmark_excess_bp"),
            _select_column(columns, ("data_quality",), "data_quality"),
            _select_column(columns, ("calculated_at", "available_at"), "calculated_at"),
        )
        sql = f"""
            SELECT {", ".join(select)}
            FROM {self._table(table)}
            WHERE {_quote(event_col)} IN ({placeholders})
              AND {_non_empty_expr(calculated_col)}
              AND {_date_key_expr(calculated_col)} <= ?
            ORDER BY {_quote(event_col)}, {_select_raw(columns, ("window_days",))}
            LIMIT ?
        """
        rows = self._query(sql, (*event_ids, _date_key(cutoff), _EVENT_LIMIT * 3))
        grouped: dict[str, list[StockOutcomeDTO]] = {}
        for row in rows:
            event_id = str(row["event_id"] or "")
            grouped.setdefault(event_id, []).append(
                StockOutcomeDTO(
                    window_days=_integer(row["window_days"]) or 0,
                    outcome_status=str(row["outcome_status"] or ""),
                    forward_return_bp=_integer(row["forward_return_bp"]),
                    benchmark_excess_bp=_integer(row["benchmark_excess_bp"]),
                    data_quality=str(row["data_quality"] or ""),
                    calculated_at=str(row["calculated_at"] or ""),
                )
            )
        return {key: tuple(value) for key, value in grouped.items()}

    def _read_position(
        self,
        code: str,
        cutoff: date,
    ) -> tuple[StockPositionSnapshotDTO | None, StockReportSourceDTO | None]:
        if self.portfolio_service is None:
            return None, None
        getter = getattr(self.portfolio_service, "get_position_detail", None)
        if not callable(getter):
            return None, None
        position = getter(code)
        if position is None:
            source = self._source(
                "portfolio.position",
                "既有 Portfolio 持倉",
                row_count=0,
                data_as_of="",
                quality=ReportQuality.MISSING.value,
                cutoff=cutoff,
                limitations=("PortfolioService 沒有此股票的持倉 row。",),
            )
            return None, source

        average_cost = _decimal(getattr(position, "average_cost", None))
        invested = _decimal(getattr(position, "invested_amount", None))
        current_price = _decimal(getattr(position, "current_price", None))
        unrealized = _decimal(getattr(position, "unrealized_pnl", None))
        unrealized_pct = _decimal(getattr(position, "unrealized_pnl_pct", None))
        exposure_bp: int | None = None
        portfolio_getter = getattr(self.portfolio_service, "get_portfolio", None)
        if callable(portfolio_getter) and invested is not None:
            with suppress(Exception):
                portfolio = portfolio_getter()
                total = _decimal(getattr(portfolio, "total_invested_amount", None))
                if total is not None and total > 0:
                    exposure_bp = int(
                        (invested / total * Decimal("10000")).to_integral_value(
                            rounding=ROUND_HALF_EVEN
                        )
                    )

        health_status = ""
        health_label = ""
        health_reasons: tuple[str, ...] = ()
        health_trace: tuple[str, ...] = ()
        limitations: list[str] = []
        if self.condition_monitor is not None:
            condition = self.condition_monitor.evaluate(
                position,
                PortfolioCurrentSnapshot(current_price=getattr(position, "current_price", None)),
            )
            health = self.position_health_service.evaluate(
                stock_code=str(getattr(position, "stock_code", code) or code),
                condition_result=condition,
                feedback_status=None,
                source_trace=tuple(
                    value
                    for value in (
                        str(getattr(position, "source_type", "") or ""),
                        str(getattr(position, "source_id", "") or ""),
                        "PortfolioConditionMonitor",
                    )
                    if value
                ),
            )
            health_status = health.state.value
            health_label = health.state.value
            health_reasons = tuple(health.reasons)
            health_trace = tuple(health.source_trace)
        else:
            limitations.append("尚未注入 PortfolioConditionMonitor／PositionHealthService read provider。")

        exit_status = "unavailable"
        exit_reasons: tuple[str, ...] = ()
        if self.exit_provider is None:
            limitations.append("Exit owner 尚未提供單股唯讀 read model；不推導賣出動作。")
        else:
            raw_exit = _call_provider(self.exit_provider, code, cutoff)
            if raw_exit is None:
                limitations.append("Exit read model 沒有此股票資料。")
            else:
                exit_status = _object_text(raw_exit, "status", "state") or "available"
                exit_reasons = _object_strings(raw_exit, "reasons", "limitations")

        snapshot = StockPositionSnapshotDTO(
            is_holding=bool(getattr(position, "is_holding", True)),
            quantity=_decimal(getattr(position, "quantity", None)),
            average_cost=average_cost,
            invested_amount=invested,
            current_price=current_price,
            unrealized_pnl=unrealized,
            unrealized_pnl_pct=unrealized_pct,
            exposure_bp=exposure_bp,
            source_type=str(getattr(position, "source_type", "") or ""),
            source_id=str(getattr(position, "source_id", "") or ""),
            source_snapshot_hash=str(getattr(position, "source_snapshot_hash", "") or ""),
            opened_at=str(getattr(position, "opened_at", "") or ""),
            last_trade_date=str(getattr(position, "last_trade_date", "") or ""),
            health_status=health_status,
            health_label=health_label,
            health_reasons=health_reasons,
            health_source_trace=health_trace,
            exit_status=exit_status,
            exit_reasons=exit_reasons,
            limitations=tuple(_dedupe(limitations)),
        )
        source = self._source(
            "portfolio.position",
            "既有 Portfolio 持倉",
            row_count=1,
            data_as_of=snapshot.last_trade_date,
            available_at=snapshot.last_trade_date,
            quality=ReportQuality.OBSERVED.value,
            cutoff=cutoff,
            limitations=snapshot.limitations,
        )
        return snapshot, source

    def _read_advice(
        self,
        code: str,
        cutoff: date,
        context: Mapping[str, str],
    ) -> tuple[StockAdviceSnapshotDTO, StockReportSourceDTO | None]:
        service = self.watchlist_analysis_service
        if service is None:
            return (
                StockAdviceSnapshotDTO(
                    limitations=("WatchlistAnalysisService 尚未提供保存結果讀取入口。",),
                ),
                None,
            )
        source_id = context.get("result_id") or context.get("source_id") or ""
        analysis = service.fetch(code, source_id, cutoff)
        if analysis.status != "saved":
            return (
                StockAdviceSnapshotDTO(
                    status=ReportQuality.UNAVAILABLE.value,
                    saved_analysis=analysis,
                    limitations=(analysis.message or "沒有可用的已保存推薦結果。",),
                ),
                self._source(
                    f"recommendation.{analysis.result_id or source_id or 'latest'}",
                    "已保存推薦結果",
                    row_count=0,
                    data_as_of=analysis.data_date or analysis.decision_date,
                    quality=ReportQuality.MISSING.value,
                    cutoff=cutoff,
                    limitations=(analysis.message or "沒有可用的已保存推薦結果。",),
                ),
            )
        result = service.load_result(analysis.result_id, as_of_date=cutoff)
        if result is None:
            return (
                StockAdviceSnapshotDTO(
                    status=ReportQuality.UNAVAILABLE.value,
                    saved_analysis=analysis,
                    limitations=("保存結果在查詢日邊界外，不能當成當下 Advice。",),
                ),
                None,
            )
        decision_date = analysis.decision_date or cutoff.isoformat()
        raw_data_date = str(analysis.data_date or "").strip()
        data_date_value = _coerce_date(raw_data_date)
        advice_limitations = [
            "Advice 沿用既有 AdviceComposer；本報告不重新計分、不自動下單。",
        ]
        if data_date_value is None:
            data_date = ""
            advice_limitations.append("推薦來源沒有可驗證的 data_date，故資料日保持未知。")
        elif data_date_value > cutoff:
            data_date = ""
            advice_limitations.append("推薦來源 data_date 晚於查詢日，故不納入本次 Advice 資料日。")
        else:
            data_date = data_date_value.isoformat()
        dashboard = AdviceComposer(AdvicePolicy()).compose(
            recommendations=result,
            portfolio_result=None,
            evidence_quality=ReportQuality.DEGRADED.value.upper(),
            decision_date=decision_date,
            # AdviceComposer 需要合法日期；缺少來源 data_date 時只以決策日
            # 完成既有唯讀投影，來源 DTO 仍保留空白，不把它宣稱為資料日。
            data_as_of_date=data_date or decision_date,
            mode=AdviceMode.GUIDED,
            evidence_warnings=("此 Advice 來自已保存研究快照，非即時重新評分。",),
        )
        recommendation = next(
            (row for row in dashboard.recommendations if row.stock_code == code),
            None,
        )
        if recommendation is None:
            return (
                StockAdviceSnapshotDTO(
                    status=ReportQuality.UNAVAILABLE.value,
                    saved_analysis=analysis,
                    limitations=("保存結果不包含此股票；未入選不等於看空。",),
                ),
                None,
            )
        rule_reasons = _dedupe(
            (
                *recommendation.why_reasons,
                *recommendation.why_not_reasons,
                *recommendation.risk_reasons,
                analysis.reasons,
            )
        )
        source = self._source(
            f"recommendation.{analysis.result_id}",
            "已保存推薦／Advice 快照",
            row_count=1,
            data_as_of=data_date,
            available_at=analysis.analysis_date,
            version=analysis.profile_version,
            quality=ReportQuality.DEGRADED.value,
            cutoff=cutoff,
            limitations=(
                "保存結果只作研究參考，Advice policy 已將 evidence_quality 設為 DEGRADED。",
                *advice_limitations[1:],
            ),
        )
        return (
            StockAdviceSnapshotDTO(
                status=ReportQuality.DEGRADED.value,
                recommendation=recommendation,
                saved_analysis=analysis,
                rule_reasons=rule_reasons,
                agreement="not_comparable",
                limitations=tuple(advice_limitations),
            ),
            source,
        )

    def _read_ml(self, code: str, cutoff: date) -> StockMLSnapshotDTO:
        if self.ml_provider is None:
            return StockMLSnapshotDTO(
                limitations=(
                    "目前沒有可用的個股 ML 分析；未訓練、全現金、過期或不合格狀態不會被猜測。",
                ),
            )
        result = _call_provider(self.ml_provider, code, cutoff)
        if result is None:
            return StockMLSnapshotDTO(
                limitations=("ML provider 沒有此股票的合格結果。",),
            )
        status = _object_text(result, "status", "model_status") or "available"
        model_version = _object_text(result, "model_version", "model_id")
        dataset_version = _object_text(result, "dataset_version", "dataset_id")
        inference_at = _object_text(result, "inference_at", "available_date", "decision_date")
        research_or_formal = _object_text(result, "research_or_formal", "lane", "mode")
        explanations = _object_strings(result, "explanations", "explain", "reasons")
        source_id = _object_text(result, "source_id", "prediction_id")
        limitations: list[str] = []
        if not model_version or not dataset_version or not inference_at:
            limitations.append("ML 結果缺少 model／dataset 版本或推論時間，故不呈現模型輸出。")
            return StockMLSnapshotDTO(
                status=ReportQuality.UNAVAILABLE.value,
                limitations=tuple(limitations),
            )
        if not explanations:
            limitations.append("ML provider 沒有提供可解釋輸出；只呈現版本與研究 lane。")
        if not research_or_formal:
            limitations.append("ML 結果未標示 research／formal lane。")
        return StockMLSnapshotDTO(
            status=status,
            model_version=model_version,
            dataset_version=dataset_version,
            inference_at=inference_at,
            research_or_formal=research_or_formal,
            explanations=explanations,
            source_id=source_id or "ml.read_provider",
            limitations=tuple(limitations),
        )

    def _ml_source(self, ml: StockMLSnapshotDTO, cutoff: date) -> StockReportSourceDTO | None:
        if ml.status in {ReportQuality.UNAVAILABLE.value, ReportQuality.MISSING.value}:
            return None
        return self._source(
            ml.source_id or "ml.read_provider",
            "ML 唯讀研究結果",
            row_count=1,
            data_as_of=_iso_date(ml.inference_at),
            available_at=_iso_date(ml.inference_at),
            version=ml.model_version,
            quality=ml.status,
            cutoff=cutoff,
            limitations=ml.limitations,
        )

    def _source(
        self,
        source_id: str,
        label: str,
        *,
        row_count: int,
        data_as_of: str,
        period: str = "",
        available_at: str = "",
        version: str = "",
        quality: str = ReportQuality.OBSERVED.value,
        cutoff: date,
        limitations: Sequence[str] = (),
    ) -> StockReportSourceDTO:
        freshness_source_id = _FRESHNESS_SOURCE_ALIASES.get(source_id, source_id)
        freshness_evidence = self._freshness_statuses.get().get(freshness_source_id)
        freshness, freshness_validation = _freshness_from_evidence(
            data_as_of,
            cutoff,
            freshness_evidence,
            period=period,
        )
        normalized_quality = _quality(quality)
        evidence_status = str(
            freshness_evidence.get("freshness_status", "")
            if freshness_evidence is not None
            else ""
        ).strip().lower()
        source_limitations = list(limitations)
        if freshness_validation:
            source_limitations.append(f"Freshness probe：{freshness_validation}")
        freshness_reason = str(
            freshness_evidence.get("reason", "")
            if freshness_evidence is not None
            else ""
        ).strip()
        if freshness_evidence is not None and evidence_status in {
            "failed",
            "unknown",
            "not_applicable",
        }:
            # 有 row 但共同 probe 無法證明來源狀態時，顯示 partial／degraded，
            # 不能讓存在資料列看起來像已完成 freshness 驗證。
            if normalized_quality in {
                ReportQuality.OBSERVED.value,
                ReportQuality.ESTIMATED.value,
            }:
                normalized_quality = ReportQuality.DEGRADED.value
            if freshness_reason:
                source_limitations.append(f"Freshness probe：{freshness_reason}")
        elif freshness_evidence is not None and evidence_status in {
            "expected_wait",
            "stale",
            "partial",
        } and freshness_reason:
            source_limitations.append(f"Freshness probe：{freshness_reason}")
        if row_count > 0 and freshness == ReportFreshness.UNKNOWN.value:
            if normalized_quality in {
                ReportQuality.OBSERVED.value,
                ReportQuality.ESTIMATED.value,
            }:
                normalized_quality = ReportQuality.DEGRADED.value
            source_limitations.append("來源沒有可驗證的 freshness cadence／期間，保留未知狀態。")
        resolved_available_at = available_at
        if not resolved_available_at and freshness_evidence is not None:
            candidate_available_at = str(
                freshness_evidence.get("available_at", "") or ""
            ).strip()
            candidate_date = _coerce_date(candidate_available_at)
            if candidate_date is not None and candidate_date <= cutoff:
                resolved_available_at = candidate_available_at
        status = (
            ReportSectionStatus.MISSING.value
            if row_count == 0
            else ReportSectionStatus.STALE.value
            if freshness == ReportFreshness.STALE.value
            else ReportSectionStatus.PARTIAL.value
            if evidence_status in {"failed", "unknown", "not_applicable"}
            or freshness == ReportFreshness.UNKNOWN.value
            else ReportSectionStatus.AVAILABLE.value
        )
        return StockReportSourceDTO(
            source_id=source_id,
            source_label=label,
            status=status,
            quality=normalized_quality,
            data_as_of=data_as_of,
            available_at=resolved_available_at,
            freshness=freshness,
            version=version,
            row_count=row_count,
            limitations=tuple(_dedupe(source_limitations)),
            frequency=(
                str(freshness_evidence.get("frequency", "") or "").strip()
                if freshness_evidence is not None
                else ""
            ),
            expected_period=(
                str(freshness_evidence.get("expected_period", "") or "").strip()
                if freshness_evidence is not None
                else ""
            ),
            freshness_reason=freshness_reason,
        )

    def _data_section(
        self,
        section_id: str,
        label: str,
        row_count: int,
        source: StockReportSourceDTO | Sequence[StockReportSourceDTO] | None,
        *,
        missing_reason: str,
    ) -> StockReportSectionDTO:
        sources = (
            (source,)
            if isinstance(source, StockReportSourceDTO)
            else tuple(source or ())
        )
        source_ids = tuple(item.source_id for item in sources)
        data_as_of = _latest_text(item.data_as_of for item in sources)
        available_at = _latest_text(item.available_at for item in sources)
        freshness = (
            ReportFreshness.STALE.value
            if any(item.freshness == ReportFreshness.STALE.value for item in sources)
            else ReportFreshness.FRESH.value
            if sources and any(item.freshness == ReportFreshness.FRESH.value for item in sources)
            else ReportFreshness.UNKNOWN.value
        )
        if row_count == 0:
            status = ReportSectionStatus.MISSING.value
            summary = missing_reason
            limitations: tuple[str, ...] = (missing_reason,)
        elif freshness == ReportFreshness.STALE.value:
            status = ReportSectionStatus.STALE.value
            summary = "來源依官方交易日／公告 cadence 判定為過期或範圍不足；詳見來源與限制。"
            limitations = _dedupe(tuple(item for source_item in sources for item in source_item.limitations))
        elif any(item.quality in {ReportQuality.DEGRADED.value, ReportQuality.ESTIMATED.value} for item in sources):
            status = ReportSectionStatus.PARTIAL.value
            summary = "有資料但品質或來源欄位不完整；詳見來源與限制。"
            limitations = _dedupe(tuple(item for source_item in sources for item in source_item.limitations))
        else:
            status = ReportSectionStatus.AVAILABLE.value
            summary = "已取得有限資料。"
            limitations = _dedupe(tuple(item for source_item in sources for item in source_item.limitations))
        return StockReportSectionDTO(
            section_id=section_id,
            label=label,
            status=status,
            summary=summary,
            data_as_of=data_as_of,
            available_at=available_at,
            freshness=freshness,
            source_ids=source_ids,
            limitations=limitations,
        )

    @staticmethod
    def _error_section(section_id: str, label: str, error: str) -> StockReportSectionDTO:
        return StockReportSectionDTO(
            section_id=section_id,
            label=label,
            status=ReportSectionStatus.ERROR.value,
            summary=error,
            limitations=(error,),
        )

    def _register_source(
        self,
        sources: list[StockReportSourceDTO],
        source: StockReportSourceDTO,
    ) -> None:
        if not any(item.source_id == source.source_id for item in sources):
            sources.append(source)

    def _load_freshness_statuses(
        self,
        cutoff: date,
    ) -> Mapping[str, Mapping[str, object]]:
        """載入單次報告使用的 freshness receipt。

        這裡只讀既有 probe 的明確檔案，不掃描 ``latest`` 檔案，也不從
        ``MAX(date)`` 猜測月／季資料是否已到期。receipt 的檢查時間若晚於
        報告 cutoff，整份證據會被忽略，避免把未來狀態包進歷史報告。
        """

        path = self.freshness_status_path
        if path is None or not path.is_file():
            return {}
        try:
            with path.open("rb") as handle:
                raw = handle.read(_FRESHNESS_MAX_BYTES + 1)
        except OSError:
            return {}
        if len(raw) > _FRESHNESS_MAX_BYTES:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, Mapping):
            return {}
        checked_date = _freshness_checked_date(payload.get("checked_at"))
        # 報告 cutoff 只採用同一個 local calendar day 的 probe receipt。
        # 舊日 receipt 沒有足夠證據證明休市／公告 cadence 可沿用，不能
        # 被套到新的報告日；跨休市沿用必須由當日 probe 自己留下 expected_period。
        if checked_date is None or checked_date != cutoff:
            return {}
        if not self._freshness_receipt_matches_config(payload):
            return {}
        items = payload.get("source_statuses")
        if not isinstance(items, list):
            return {}
        result: dict[str, Mapping[str, object]] = {}
        for item in items:
            if not isinstance(item, Mapping):
                continue
            source_id = str(item.get("source_id", "") or "").strip()
            status = str(item.get("freshness_status", "") or "").strip().lower()
            if not source_id or status not in _FRESHNESS_STATUS_VALUES:
                continue
            result[source_id] = item
        return result

    def _freshness_receipt_matches_config(self, payload: Mapping[str, object]) -> bool:
        """確認 freshness receipt 與本次報告使用同一資料根與 SQLite。"""

        checks = payload.get("checks")
        checks_map = checks if isinstance(checks, Mapping) else {}
        receipt_db = payload.get("db_path") or checks_map.get("db_path")
        receipt_root = payload.get("data_root")
        configured_db = getattr(self.config, "db_file", None)
        if configured_db is None or not receipt_db or not receipt_root:
            return False
        configured_db_path = Path(str(configured_db)).expanduser().resolve(strict=False)
        configured_root = getattr(self.config, "data_root", None)
        if configured_root is None:
            # SimpleNamespace／輕量測試 config 沒有 data_root 時，SQLite
            # 的 parent/parent 是唯一可驗證的 fallback；正式 TWStockConfig
            # 一定會走明確 data_root。
            configured_root = configured_db_path.parent.parent
        configured_root_path = Path(str(configured_root)).expanduser().resolve(strict=False)
        try:
            receipt_db_path = Path(str(receipt_db)).expanduser().resolve(strict=False)
            receipt_root_path = Path(str(receipt_root)).expanduser().resolve(strict=False)
        except (OSError, ValueError, TypeError):
            return False
        return receipt_db_path == configured_db_path and receipt_root_path == configured_root_path

    def _columns(self, table: str) -> tuple[str, ...]:
        if table in self._column_cache:
            return self._column_cache[table]
        if self.db is None:
            return ()
        columns = tuple(self.db.get_table_columns(table))
        self._column_cache[table] = columns
        return columns

    def _query(self, sql: str, params: tuple[Any, ...]) -> list[Any]:
        if self.db is None:
            return []
        with self.db.connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    @staticmethod
    def _table(table: str) -> str:
        return _quote(table)

    @staticmethod
    def _check_cancel(cancel_callback: Callable[[], bool] | None) -> None:
        if cancel_callback is not None and cancel_callback():
            raise StockResearchReportCancelled("stock research report read cancelled")


def _normalize_stock_code(value: object) -> str:
    code = str(value or "").strip()
    if not code:
        raise ValueError("stock_code is required")
    return code


def _coerce_date(value: date | str | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    with suppress(ValueError):
        return date.fromisoformat(text[:10])
    return None


def _date_key(value: date) -> str:
    return value.strftime("%Y%m%d")


def _iso_date(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    compact = text.replace("-", "").replace("/", "")
    if len(compact) >= 8 and compact[:8].isdigit():
        raw = compact[:8]
        with suppress(ValueError):
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    with suppress(ValueError):
        return date.fromisoformat(text[:10]).isoformat()
    return text


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _pick(columns: Sequence[str], *candidates: str) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _select_raw(columns: Sequence[str], candidates: Sequence[str]) -> str:
    column = _pick(columns, *candidates)
    return _quote(column) if column else "0"


def _select_column(columns: Sequence[str], candidates: Sequence[str], alias: str) -> str:
    column = _pick(columns, *candidates)
    return f"{_quote(column)} AS {_quote(alias)}" if column else f"NULL AS {_quote(alias)}"


def _date_key_expr(column: str) -> str:
    return f"substr(replace(replace(CAST({_quote(column)} AS TEXT), '-', ''), '/', ''), 1, 8)"


def _non_empty_expr(column: str) -> str:
    return f"NULLIF(TRIM(CAST({_quote(column)} AS TEXT)), '') IS NOT NULL"


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _integer(value: object) -> int | None:
    decimal = _decimal(value)
    if decimal is None:
        return None
    with suppress(InvalidOperation, ValueError):
        return int(decimal.to_integral_value(rounding=ROUND_HALF_EVEN))
    return None


def _quality(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"observed", "ready", "pass", "passed"}:
        return ReportQuality.OBSERVED.value
    if text in {"estimated", "estimate"}:
        return ReportQuality.ESTIMATED.value
    if text in {"stale", "expired"}:
        return ReportQuality.STALE.value
    if text in {"missing", "unavailable", "blocked"}:
        return ReportQuality.MISSING.value
    if text in {"", "unknown"}:
        return ReportQuality.DEGRADED.value
    return ReportQuality.DEGRADED.value


def _freshness_checked_date(value: object) -> date | None:
    """將 freshness receipt 的檢查時間轉為台北日曆日。"""

    parsed: datetime | None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            with suppress(ValueError):
                return date.fromisoformat(text[:10])
            return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.date()
    return parsed.astimezone(_TAIPEI).date()


def _freshness_from_evidence(
    data_as_of: str,
    cutoff: date,
    evidence: Mapping[str, object] | None,
    *,
    period: str = "",
) -> tuple[str, str]:
    """以 receipt cadence 與個股實際期間判斷 freshness。

    沒有與本次報告日期、資料根及 SQLite 綁定的 receipt 時，只有 PIT
    日期邊界可驗證，不能把資料日較早直接稱為 stale；週末／月季公告期
    可能合法落後，故保留 unknown。
    """

    if evidence is None:
        return (
            ReportFreshness.UNKNOWN.value,
            "缺少與本報告 cutoff、data root 及 SQLite 綁定的 freshness receipt。",
        )
    data_date = _coerce_date(data_as_of)
    if data_date is not None and data_date > cutoff:
        return ReportFreshness.UNKNOWN.value, "來源資料日晚於查詢日，拒絕 future freshness。"
    status = str(evidence.get("freshness_status", "") or "").strip().lower()
    if status in {"current", "expected_wait"}:
        expected_period = _normalize_period(evidence.get("expected_period"))
        actual_period = _normalize_period(evidence.get("actual_period"))
        observed_period = _normalize_period(period or data_as_of)
        if not expected_period:
            return ReportFreshness.UNKNOWN.value, "receipt 缺少 expected_period，不能驗證個股期間。"
        if actual_period and actual_period != expected_period:
            return (
                ReportFreshness.UNKNOWN.value,
                "receipt 的 actual_period 與 expected_period 不一致。",
            )
        if not observed_period:
            return ReportFreshness.UNKNOWN.value, "個股來源沒有可驗證的資料期間。"
        if observed_period != expected_period:
            return (
                ReportFreshness.STALE.value,
                f"個股資料期 {observed_period} 未達 receipt expected_period {expected_period}。",
            )
        return ReportFreshness.FRESH.value, "個股資料期與 receipt expected_period 相符。"
    if status in {"stale", "partial"}:
        return ReportFreshness.STALE.value, "receipt 已判定來源過期或覆蓋不完整。"
    return ReportFreshness.UNKNOWN.value, "receipt 狀態無法證明來源 freshness。"


def _normalize_period(value: object) -> str:
    """正規化 daily date／monthly period／quarter period，不混用 available_at。"""

    text = str(value or "").strip().replace("/", "-")
    if not text:
        return ""
    if len(text) == 8 and text.isdigit():
        with suppress(ValueError):
            return date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:8]}").isoformat()
    if len(text) >= 10:
        parsed = _coerce_date(text)
        if parsed is not None:
            return parsed.isoformat()
    if len(text) == 7 and text[4] == "-" and text[:4].isdigit() and text[5:].isdigit():
        return text
    compact_quarter = text.upper().replace(" ", "")
    if len(compact_quarter) == 6 and compact_quarter[4] == "Q" and compact_quarter[5] in "1234":
        return f"{compact_quarter[:4]}-{compact_quarter[4:]}"
    if len(compact_quarter) == 7 and compact_quarter[4] == "-" and compact_quarter[5] == "Q":
        return compact_quarter
    return text


def _resolve_freshness_status_path(
    config: object,
    explicit_path: Path | str | None,
) -> Path | None:
    """解析 freshness receipt 的單一受控路徑，不對 output 目錄做 glob。"""

    candidate: object = explicit_path
    if candidate is None:
        candidate = os.environ.get("DATA_FRESHNESS_STATUS_ARTIFACT")
    if candidate is None:
        candidate = getattr(config, "data_freshness_status_path", None)
    if candidate is None:
        output_root = getattr(config, "output_root", None)
        if output_root is None:
            return None
        candidate = Path(output_root) / "scheduled" / "data_freshness" / "latest_status.json"
    text = str(candidate).strip()
    return Path(text).expanduser().resolve() if text else None


def _latest_text(values: Sequence[str] | Any) -> str:
    cleaned = [str(value).strip() for value in values if str(value or "").strip()]
    return max(cleaned) if cleaned else ""


def _worst_quality(values: Sequence[str] | Any) -> str:
    rank = {
        ReportQuality.OBSERVED.value: 0,
        ReportQuality.ESTIMATED.value: 1,
        ReportQuality.DEGRADED.value: 2,
        ReportQuality.STALE.value: 3,
        ReportQuality.MISSING.value: 4,
    }
    cleaned = [_quality(value) for value in values]
    return max(cleaned, key=lambda value: rank.get(value, 2)) if cleaned else ReportQuality.MISSING.value


def _json_strings(value: object) -> tuple[str, ...]:
    if not value:
        return ()
    try:
        raw = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return (str(value),)
    if isinstance(raw, (list, tuple)):
        return tuple(str(item) for item in raw if str(item).strip())
    return (str(raw),) if str(raw).strip() else ()


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


def _context_map(context: object | None) -> dict[str, str]:
    if context is None:
        return {}
    fields = (
        "stock_code", "stock_name", "decision_date", "data_date", "result_id",
        "profile_id", "profile_version", "source_id", "source_kind",
        "source_label", "source_workspace",
    )
    if isinstance(context, Mapping):
        return {
            field: str(context.get(field, "") or "").strip()
            for field in fields
            if str(context.get(field, "") or "").strip()
        }
    return {
        field: str(getattr(context, field, "") or "").strip()
        for field in fields
        if str(getattr(context, field, "") or "").strip()
    }


def _error_text(label: str, error: BaseException) -> str:
    message = str(error).splitlines()[0].strip() or type(error).__name__
    return f"{label}區塊讀取失敗：{message}"


def _call_provider(provider: Callable[..., object], code: str, cutoff: date) -> object | None:
    try:
        parameters = inspect.signature(provider).parameters
    except (TypeError, ValueError):
        return provider(code, cutoff)
    if "stock_code" in parameters or "as_of_date" in parameters:
        kwargs: dict[str, object] = {}
        if "stock_code" in parameters:
            kwargs["stock_code"] = code
        if "as_of_date" in parameters:
            kwargs["as_of_date"] = cutoff
        return provider(**kwargs)
    return provider(code, cutoff)


def _object_text(value: object, *names: str) -> str:
    if isinstance(value, Mapping):
        for name in names:
            text = str(value.get(name, "") or "").strip()
            if text:
                return text
    for name in names:
        text = str(getattr(value, name, "") or "").strip()
        if text:
            return text
    return ""


def _object_strings(value: object, *names: str) -> tuple[str, ...]:
    raw: object = ()
    if isinstance(value, Mapping):
        for name in names:
            if value.get(name) is not None:
                raw = value.get(name)
                break
    else:
        for name in names:
            candidate = getattr(value, name, None)
            if candidate is not None:
                raw = candidate
                break
    if isinstance(raw, str):
        return _dedupe(tuple(part.strip() for part in raw.replace("；", ";").split(";") if part.strip()))
    if isinstance(raw, (list, tuple, set)):
        return _dedupe(tuple(str(item) for item in raw))
    return ()


def _first_non_empty(*values: str) -> str:
    return next((value for value in values if value.strip()), "")


def _with_advice_agreement(
    advice: StockAdviceSnapshotDTO,
    rule_reasons: tuple[str, ...],
    ml_reasons: tuple[str, ...],
) -> StockAdviceSnapshotDTO:
    if not ml_reasons:
        return advice
    return StockAdviceSnapshotDTO(
        status=advice.status,
        recommendation=advice.recommendation,
        portfolio=advice.portfolio,
        saved_analysis=advice.saved_analysis,
        rule_reasons=rule_reasons,
        ml_reasons=ml_reasons,
        agreement="needs_review",
        limitations=advice.limitations,
    )


def _attention_reasons(
    prices: Sequence[StockPricePointDTO],
    fundamentals: Sequence[StockFundamentalObservationDTO],
    flows: Sequence[StockFlowObservationDTO],
    sections: Sequence[StockReportSectionDTO],
    advice: StockAdviceSnapshotDTO,
    position: StockPositionSnapshotDTO | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not prices:
        reasons.append("缺少最新可用價格")
    if prices and not prices[-1].close_price:
        reasons.append("最新價格 row 沒有收盤價")
    if not fundamentals:
        reasons.append("基本面資料不足")
    if not flows:
        reasons.append("籌碼／分點資料不足")
    if any(section.status in {ReportSectionStatus.STALE.value, ReportSectionStatus.ERROR.value} for section in sections):
        reasons.append("部分來源過期或讀取失敗")
    reasons.extend(advice.rule_reasons[:3])
    if position is not None:
        reasons.extend(position.health_reasons[:3])
    return _dedupe(reasons)


def _key_risks(
    advice: StockAdviceSnapshotDTO,
    events: Sequence[StockEvidenceEventDTO],
    position: StockPositionSnapshotDTO | None,
    limitations: Sequence[str],
) -> tuple[str, ...]:
    risks: list[str] = list(advice.recommendation.risk_reasons if advice.recommendation else ())
    for event in events:
        risks.extend(event.risk_reasons)
    if position is not None:
        risks.extend(position.health_reasons)
        risks.extend(position.exit_reasons)
    if not risks:
        risks.extend(limitations[:3])
    return _dedupe(risks)[:8]
