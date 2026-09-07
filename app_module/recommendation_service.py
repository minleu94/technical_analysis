"""
推薦服務 (Recommendation Service)
提供股票推薦的業務邏輯，供 UI 層調用
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, cast
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from copy import deepcopy
from contextlib import closing
import hashlib
import json
import sqlite3

# 確保 pd.isna 可用（pandas 兼容性）
if not hasattr(pd, 'isna'):
    pd.isna = pd.isnull

# 方案 A：不搬檔案，service 層內部 import ui_app 模組
# from ui_app.strategy_configurator import StrategyConfigurator
# from ui_app.reason_engine import ReasonEngine
# from ui_app.industry_mapper import IndustryMapper
# from ui_app.market_regime_detector import MarketRegimeDetector
from decision_module.strategy_configurator import StrategyConfigurator
from decision_module.reason_engine import ReasonEngine
from decision_module.industry_mapper import IndustryMapper
from decision_module.market_regime_detector import MarketRegimeDetector
from app_module.dtos import RecommendationDTO
from app_module.strategy_spec import StrategySpec
from app_module.preset_service import PresetService
from app_module.strategy_version_service import StrategyVersionService
from decision_module.derived_market_features import (
    enrich_latest_market_features,
    latest_feature_decimal,
)
from financial_module.units import to_decimal
from app_module.recommendation_run_support import (
    build_negative_evidence_buffers,
    configured_volume_change_min_percent,
    format_decimal_for_payload,
    matrix_row,
    validate_ranking_config,
)
from app_module.recommendation_market_data_provider import (
    DefaultRecommendationMarketDataProvider,
)
from app_module.recommendation_market_frame import normalize_market_frame
from app_module.recommendation_portfolio_dates import parse_stock_dates
from app_module.recommendation_ranking_pipeline import build_ranking_plan
from app_module.application_ports import MarketFrameProvider
from data_module.fundamental_sqlite_provider import FundamentalSQLiteProvider


class RecommendationService:
    """推薦服務類"""

    def __init__(
        self,
        config,
        industry_mapper: Optional[IndustryMapper] = None,
        market_data_provider: Optional[MarketFrameProvider] = None,
        regime_detector: Optional[MarketRegimeDetector] = None,
    ):
        """初始化推薦服務

        Args:
            config: TWStockConfig 實例
            industry_mapper: IndustryMapper 實例（可選，如果為 None 則自動創建）
        """
        self.config = config
        self.strategy_configurator = StrategyConfigurator()
        self.reason_engine = ReasonEngine()
        if industry_mapper is None:
            self.industry_mapper = IndustryMapper(config)
        else:
            self.industry_mapper = industry_mapper
        self.market_data_provider = (
            market_data_provider
            if market_data_provider is not None
            else DefaultRecommendationMarketDataProvider(config)
        )
        self.regime_detector = regime_detector or MarketRegimeDetector(config)
        self.last_screening_matrix: List[Dict[str, Any]] = []
        self.last_excluded_candidates_json: List[Dict[str, Any]] = []
        self.last_why_not_payload_json: List[Dict[str, Any]] = []
        self.last_liquidity_gate_payload_json: List[Dict[str, Any]] = []
        self.last_exclusion_quality: str = "observed"
        self.last_exclusion_warnings_json: List[str] = []
        self.last_run_context: Dict[str, Any] = {}
        self._fundamental_sqlite_provider: FundamentalSQLiteProvider | None = None
        self._fundamental_provider_initialization_attempted = False

    def _reset_negative_evidence_buffers(self) -> None:
        self.last_screening_matrix = []
        self.last_excluded_candidates_json = []
        self.last_why_not_payload_json = []
        self.last_liquidity_gate_payload_json = []
        self.last_exclusion_quality = "observed"
        self.last_exclusion_warnings_json = []
        self.last_run_context = {}

    def _matrix_row(
        self,
        *,
        stock_code: str,
        stock_name: str = "",
        status: str,
        reason_codes: List[str],
        quality: str,
        stage: str,
        threshold_name: str = "",
        observed_value: Any = None,
        required_value: Any = None,
        total_score: Any = None,
        score_bp: Optional[int] = None,
        score_percentile_bp: Optional[int] = None,
        eligible_universe_size: Optional[int] = None,
        threshold_mode: str = "fixed",
        warnings: Optional[List[str]] = None,
        industry: str = "",
    ) -> Dict[str, Any]:
        return matrix_row(
            stock_code=stock_code,
            stock_name=stock_name,
            status=status,
            reason_codes=reason_codes,
            quality=quality,
            stage=stage,
            threshold_name=threshold_name,
            observed_value=observed_value,
            required_value=required_value,
            total_score=total_score,
            score_bp=score_bp,
            score_percentile_bp=score_percentile_bp,
            eligible_universe_size=eligible_universe_size,
            threshold_mode=threshold_mode,
            warnings=warnings,
            industry=industry,
        )

    def _finalize_negative_evidence_buffers(self) -> None:
        if self.last_run_context:
            self.last_run_context["data_fingerprint"] = hashlib.sha256(json.dumps(
                {"market": self.last_run_context["market_data_fingerprint"], "fundamental": self.last_run_context["fundamental_inputs"]},
                sort_keys=True, ensure_ascii=False, default=str,
            ).encode("utf-8")).hexdigest()
        for row in self.last_screening_matrix:
            row["as_of_date"] = self.last_run_context.get("as_of_date", "")
            row["data_fingerprint"] = self.last_run_context.get("data_fingerprint", "")
        buffers = build_negative_evidence_buffers(self.last_screening_matrix)
        self.last_excluded_candidates_json = buffers.excluded_candidates
        self.last_why_not_payload_json = buffers.why_not_payload
        self.last_liquidity_gate_payload_json = buffers.liquidity_gate_payload
        self.last_exclusion_quality = buffers.exclusion_quality
        self.last_exclusion_warnings_json = buffers.exclusion_warnings
        if any(row.get("quality") in {"missing", "degraded"} for row in self.last_screening_matrix):
            self.last_exclusion_quality = "degraded"
            self.last_exclusion_warnings_json.append("screening_contains_unknown_evidence")

    @staticmethod
    def _configured_volume_change_min_percent(config: Dict[str, Any]) -> Decimal | None:
        return configured_volume_change_min_percent(config)

    @staticmethod
    def _format_decimal_for_payload(value: Decimal) -> str:
        return format_decimal_for_payload(value)

    @staticmethod
    def _validate_ranking_config(config: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
        return validate_ranking_config(config)

    @staticmethod
    def _normalize_decision_date(raw_date: Any) -> str:
        """將來源日期轉成 PIT 查詢可用的 ISO 日期；無法判讀時 fail-closed。"""
        if isinstance(raw_date, (pd.Timestamp, datetime, date)):
            if pd.isna(raw_date):
                raise ValueError("decision date is missing")
            return raw_date.strftime("%Y-%m-%d")

        date_text = str(raw_date).strip()
        if not date_text:
            raise ValueError("decision date is empty")

        normalized_text = date_text.replace("-", "").replace("/", "")
        if len(normalized_text) != 8 or not normalized_text.isdigit():
            raise ValueError(f"unsupported decision date: {date_text}")
        return datetime.strptime(normalized_text, "%Y%m%d").date().isoformat()

    def _load_governed_monthly_revenues(
        self,
        *,
        stock_code: str,
        decision_date: date,
    ):
        """只讀取有獨立正式 availability mapping 支持的月營收。"""

        provider = self._get_fundamental_sqlite_provider()
        if provider is None:
            return ()
        try:
            return provider.load_monthly_revenues(
                stock_code=stock_code,
                decision_date=decision_date,
            )
        except Exception as exc:
            # 基本面門檻無法建立正式 PIT 證據時，後續流程會以 missing 排除；
            # 不可退回到直接讀 SQLite row 的舊路徑。
            import logging

            logging.getLogger(__name__).error("查詢受治理月營收失敗: %s", exc)
            return ()

    def _get_fundamental_sqlite_provider(self) -> FundamentalSQLiteProvider | None:
        if self._fundamental_sqlite_provider is not None:
            return self._fundamental_sqlite_provider
        if self._fundamental_provider_initialization_attempted:
            return None

        self._fundamental_provider_initialization_attempted = True
        db_file = getattr(self.config, "db_file", None)
        if db_file is None:
            return None
        try:
            db_path = Path(cast(str, db_file))
        except (TypeError, ValueError):
            return None
        if not db_path.is_file():
            return None

        availability_file = getattr(
            self.config,
            "monthly_revenue_availability_file",
            None,
        )
        try:
            availability_path = (
                Path(availability_file) if availability_file is not None else None
            )
        except (TypeError, ValueError):
            availability_file = None
        else:
            availability_file = availability_path

        self._fundamental_sqlite_provider = FundamentalSQLiteProvider(
            db_path,
            monthly_revenue_availability_file=availability_file,
        )
        return self._fundamental_sqlite_provider

    def _load_historical_market_frame(self, cutoff: str | None) -> pd.DataFrame:
        """歷史入口使用決策日窗口及唯讀連線，不初始化 DBManager。"""
        if getattr(self.config, "use_sqlite", False):
            db_path = Path(self.config.db_file).resolve()
            with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as conn:
                conn.execute("PRAGMA query_only=ON")
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if cutoff is None:
                    latest = conn.execute("SELECT MAX(日期) FROM daily_prices").fetchone()[0]
                    if latest is None:
                        return pd.DataFrame(columns=["日期", "證券代號"])
                    cutoff = self._normalize_decision_date(latest)
                start = (pd.Timestamp(cutoff) - pd.Timedelta(days=60)).strftime("%Y%m%d")
                end = cutoff.replace("-", "")
                if "technical_indicators" in tables:
                    query = (
                        "SELECT p.*, t.* FROM daily_prices p LEFT JOIN technical_indicators t "
                        "ON p.證券代號=t.證券代號 AND p.日期=t.日期 "
                    )
                else:
                    query = "SELECT p.* FROM daily_prices p "
                query += "WHERE replace(CAST(p.日期 AS TEXT), '-', '') BETWEEN ? AND ? ORDER BY p.日期, p.證券代號"
                frame = pd.read_sql_query(query, conn, params=(start, end))
                return frame.loc[:, ~frame.columns.duplicated()].copy()
        paths = [getattr(self.config, "all_stocks_data_file", None), getattr(self.config, "stock_data_file", None)]
        for candidate in paths:
            if candidate is not None and candidate.is_file():
                return pd.read_csv(candidate, encoding="utf-8-sig", dtype={"證券代號": str, "股票代號": str})
        raise FileNotFoundError("歷史推薦缺少唯讀行情來源")

    def _decision_frame(self, frame: pd.DataFrame, cutoff: str | None) -> tuple[pd.DataFrame, str, str]:
        frame, stock_col = normalize_market_frame(frame)
        if frame.empty:
            return frame, stock_col, cutoff or ""
        frame["日期"] = parse_stock_dates(frame["日期"])
        frame = frame[frame["日期"].notna()].copy()
        decision_date = cutoff or (frame["日期"].max().strftime("%Y-%m-%d") if not frame.empty else "")
        if decision_date:
            limit = pd.Timestamp(decision_date)
            frame = frame[frame["日期"] <= limit].copy()
            if "available_date" in frame:
                available = parse_stock_dates(frame["available_date"])
                frame = frame[available.notna() & (available <= limit)].copy()
                frame["available_date"] = available.loc[frame.index]
                # 已知修訂優先；未到可得日的修訂不影響歷史窗口。
                frame = frame.sort_values("available_date", kind="stable").drop_duplicates([stock_col, "日期"], keep="last")
        frame[stock_col] = frame[stock_col].astype(str)
        return frame.reset_index(drop=True), stock_col, decision_date

    def run_recommendation(
        self,
        config: Dict[str, Any],
        max_stocks: int = 200,
        top_n: int = 50,
        *,
        as_of_date: str | date | None = None,
        universe: Optional[List[str]] = None,
    ) -> List[RecommendationDTO]:
        """執行推薦分析

        這是從 ui_app/main.py 的 _execute_strategy_analysis_thread 提取的核心邏輯

        Args:
            config: 策略配置字典（包含 technical, patterns, signals, filters, regime 等）
            max_stocks: 最大處理股票數量（用於性能優化）
            top_n: 返回前 N 名推薦

        Returns:
            List[RecommendationDTO]: 推薦股票列表，按總分降序排列
        """
        import logging
        logger = logging.getLogger(__name__)
        config = deepcopy(config)
        if max_stocks < 1 or top_n < 0:
            raise ValueError("max_stocks 必須為正數，top_n 不得為負數")
        ranking_config, threshold_mode = self._validate_ranking_config(config)
        self._reset_negative_evidence_buffers()
        cutoff_input = as_of_date if as_of_date is not None else config.get("as_of_date")
        cutoff = self._normalize_decision_date(cutoff_input) if cutoff_input is not None else None

        # ✅ 記錄輸入參數
        logger.info(
            f"[RecommendationService] 開始推薦分析: "
            f"max_stocks={max_stocks}, top_n={top_n}, "
            f"產業篩選={config.get('filters', {}).get('industry', '全部')}, "
            f"圖形模式={config.get('patterns', {}).get('selected', [])}, "
            f"技術指標啟用={config.get('technical', {}).get('momentum', {}).get('enabled', False) or config.get('technical', {}).get('trend', {}).get('enabled', False)}"
        )

        source = (
            self._load_historical_market_frame(cutoff)
            if isinstance(self.market_data_provider, DefaultRecommendationMarketDataProvider) and (cutoff or getattr(self.config, "use_sqlite", False))
            else self.market_data_provider()
        )
        df, stock_col, decision_cutoff = self._decision_frame(source, cutoff)
        if universe is not None and not df.empty:
            df = df[df[stock_col].isin({str(code) for code in universe})].copy()
        canonical = df.sort_values([stock_col, "日期"], kind="stable") if not df.empty else df
        fingerprint_payload = canonical.reindex(sorted(canonical.columns), axis=1).astype(str).to_dict("records")
        self.last_run_context = {
            "schema_version": "recommendation-context.v1",
            "as_of_date": decision_cutoff,
            "strategy_config": deepcopy(config),
            "profile_id": str(config.get("profile_id") or ""),
            "profile_version": str(config.get("profile_version") or ""),
            "universe_spec": {"codes": sorted({str(code) for code in universe}) if universe is not None else None, "max_stocks": max_stocks},
            "source_id": type(self.market_data_provider).__name__,
            "market_data_fingerprint": hashlib.sha256(json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
            "fundamental_inputs": [],
            "data_date": canonical["日期"].max().strftime("%Y-%m-%d") if not canonical.empty else "",
            "warnings": ["industry_membership_not_point_in_time"] if cutoff else [],
        }
        if df.empty:
            self.last_run_context["eligible_universe_size"] = 0
            self._finalize_negative_evidence_buffers()
            return []

        # ✅ 記錄數據讀取結果
        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            f"[RecommendationService] 數據讀取完成: "
            f"總筆數={len(df)}, "
            f"股票數={df[stock_col].nunique()}, "
            f"日期範圍={df['日期'].min()} ~ {df['日期'].max()}"
        )

        # 應用產業篩選（先篩選產業，再限制數量）
        industry_filter = config.get('filters', {}).get('industry', '全部')
        all_stocks = df[stock_col].unique()

        if cutoff and industry_filter and industry_filter != '全部':
            self.last_screening_matrix = [self._matrix_row(
                stock_code=str(code), status="missing", reason_codes=["industry_membership_pit_unavailable"],
                quality="missing", stage="universe_gate", threshold_mode=threshold_mode,
            ) for code in all_stocks]
            self.last_run_context["eligible_universe_size"] = 0
            self._finalize_negative_evidence_buffers()
            return []

        if industry_filter and industry_filter != '全部':
            # 先從所有股票中篩選出屬於指定產業的股票
            filtered_stocks = self.industry_mapper.filter_stocks_by_industry(
                [str(s) for s in all_stocks],
                industry_filter
            )

            if len(filtered_stocks) == 0:
                # 提供更詳細的錯誤信息，幫助調試
                all_industries = self.industry_mapper.get_all_industries()
                similar_industries = [ind for ind in all_industries
                                     if industry_filter in ind or ind in industry_filter]
                error_msg = f"在數據中沒有找到屬於「{industry_filter}」產業的股票"
                if similar_industries:
                    error_msg += f"\n\n可能的相似產業名稱：{', '.join(similar_industries[:5])}"
                error_msg += f"\n\n所有可用產業（前20個）：{', '.join(all_industries[:20])}"
                error_msg += f"\n\n總股票數：{len(all_stocks)}"
                # 嘗試檢查是否有部分匹配的股票
                test_stocks = list(all_stocks)[:10]
                for test_stock in test_stocks:
                    test_industries = self.industry_mapper.get_stock_industries(str(test_stock))
                    if test_industries:
                        error_msg += f"\n範例：股票 {test_stock} 屬於：{', '.join(test_industries[:3])}"
                        break
                self.last_run_context["warnings"].append("industry_filter_empty")

            # 只保留屬於該產業的股票
            stocks = [s for s in all_stocks if str(s) in filtered_stocks]
            # 限制處理數量（在產業篩選後）
            stocks = stocks[:max_stocks]

            # ✅ 記錄產業篩選結果
            logger.info(
                f"[RecommendationService] 產業篩選完成: "
                f"產業={industry_filter}, "
                f"篩選前股票數={len(all_stocks)}, "
                f"篩選後股票數={len(stocks)}"
            )
        else:
            # 沒有產業篩選，直接限制數量
            stocks = all_stocks[:max_stocks]

        # 🚀 效能優化：過濾 df 僅保留需要處理的股票，避免在包含所有個股的巨量 DataFrame 上進行高頻 boolean indexing
        df = df[df[stock_col].isin(stocks)].copy()

        # ✅ 記錄處理開始
        logger.info(
            f"[RecommendationService] 開始處理 {len(stocks)} 支股票"
        )

        # 對每支股票執行策略分析
        all_recommendations = []
        matrix_rows_by_stock: Dict[str, Dict[str, Any]] = {}

        # 調試統計
        stats = {
            'total_stocks': len(stocks),
            'processed': 0,
            'skipped_insufficient_data': 0,
            'skipped_no_result': 0,
            'skipped_exception': 0,
            'success': 0
        }

        for idx, stock_code in enumerate(stocks):
            stock_df = df[df[stock_col] == stock_code].copy()
            stock_df = stock_df.sort_values('日期').reset_index(drop=True)
            stock_code_text = str(stock_code)
            stock_name_text = stock_code_text
            if len(stock_df) > 0 and '證券名稱' in stock_df.columns:
                stock_name_text = str(stock_df.iloc[-1].get('證券名稱', stock_code_text))

            # 確保至少有20筆數據才能計算技術指標
            if len(stock_df) < 20:
                stats['skipped_insufficient_data'] += 1
                row = self._matrix_row(
                    stock_code=stock_code_text,
                    stock_name=stock_name_text,
                    status="missing",
                    reason_codes=["insufficient_history"],
                    quality="missing",
                    stage="pre_evaluation",
                    threshold_name="minimum_history_rows",
                    observed_value=len(stock_df),
                    required_value=20,
                    threshold_mode=threshold_mode,
                )
                self.last_screening_matrix.append(row)
                matrix_rows_by_stock[stock_code_text] = row
                continue

            stock_df = enrich_latest_market_features(stock_df)

            try:
                # 生成推薦（generate_recommendations 內部會處理篩選，這裡不需要額外篩選）
                result_df = self.strategy_configurator.generate_recommendations(stock_df, deepcopy(config))

                stats['processed'] += 1

                # ✅ 添加調試信息：記錄為什麼返回空 DataFrame
                if len(result_df) == 0:
                    # 記錄前3個被過濾的股票詳情
                    if stats['skipped_no_result'] < 3:
                        logger.warning(
                            f"[調試] 股票 {stock_code} 返回空結果: "
                            f"數據筆數={len(stock_df)}, "
                            f"日期範圍={stock_df['日期'].min() if '日期' in stock_df.columns else 'N/A'} ~ "
                            f"{stock_df['日期'].max() if '日期' in stock_df.columns else 'N/A'}"
                        )
                    reason_codes = ["strategy_filter_no_signal"]
                    threshold_name = "strategy_configurator_result"
                    observed_value: Any = "empty"
                    required_value: Any = "non_empty"
                    volume_min = self._configured_volume_change_min_percent(config)
                    observed_volume_change = latest_feature_decimal(
                        stock_df,
                        "成交量變化率%",
                    )
                    if (
                        volume_min is not None
                        and observed_volume_change is not None
                        and observed_volume_change < volume_min
                    ):
                        reason_codes = ["liquidity_volume_ratio_below_min"]
                        threshold_name = "liquidity.volume_ratio_min"
                        observed_value = self._format_decimal_for_payload(observed_volume_change)
                        required_value = self._format_decimal_for_payload(volume_min)
                    row = self._matrix_row(
                        stock_code=stock_code_text,
                        stock_name=stock_name_text,
                        status="skipped",
                        reason_codes=reason_codes,
                        quality="degraded",
                        stage="strategy_evaluation",
                        threshold_name=threshold_name,
                        observed_value=observed_value,
                        required_value=required_value,
                        threshold_mode=threshold_mode,
                    )
                    self.last_screening_matrix.append(row)
                    matrix_rows_by_stock[stock_code_text] = row

                if len(result_df) > 0:
                    latest_row = result_df.iloc[-1]

                    # 取得決策日期。基本面篩選只接受可標準化的日期，避免無效日期
                    # 造成 PIT 查詢意外納入未來資料。
                    raw_date = decision_cutoff
                    pe_ratio_max = to_decimal(config.get('filters', {}).get('pe_ratio_max', "999.0"))
                    revenue_yoy_min = to_decimal(config.get('filters', {}).get('monthly_revenue_yoy_min', "-100.0"))
                    fundamental_filters_enabled = (
                        pe_ratio_max < to_decimal("999.0")
                        or revenue_yoy_min > to_decimal("-100.0")
                    )
                    try:
                        decision_date = self._normalize_decision_date(raw_date)
                    except (TypeError, ValueError):
                        if fundamental_filters_enabled:
                            row = self._matrix_row(
                                stock_code=stock_code_text,
                                stock_name=stock_name_text,
                                status="skipped",
                                reason_codes=["fundamental_decision_date_invalid"],
                                quality="degraded",
                                stage="strategy_evaluation",
                                threshold_name="decision_date",
                                observed_value=str(raw_date),
                                required_value="YYYY-MM-DD",
                                threshold_mode=threshold_mode,
                            )
                            self.last_screening_matrix.append(row)
                            matrix_rows_by_stock[stock_code_text] = row
                            stats['skipped_no_result'] += 1
                            continue
                        decision_date = ""

                    # 1. 本益比 PE 過濾
                    if pe_ratio_max < to_decimal("999.0"):
                        pe_val_dec = None
                        try:
                            db_uri = Path(self.config.db_file).resolve().as_uri() + "?mode=ro"
                            with closing(sqlite3.connect(db_uri, uri=True)) as conn:
                                conn.execute("PRAGMA query_only=ON")
                                conn.row_factory = sqlite3.Row
                                cursor = conn.cursor()
                                cursor.execute(
                                    "SELECT value, as_of_date, available_date, source, source_version, quality FROM fundamental_valuation_metrics "
                                    "WHERE stock_code = ? AND metric_name = 'pe' AND available_date <= ? AND as_of_date <= ? AND quality = 'observed' "
                                    "ORDER BY as_of_date DESC, available_date DESC, source_version DESC LIMIT 1",
                                    (stock_code_text, decision_date, decision_date)
                                )
                                row = cursor.fetchone()
                                if row and row['value'] is not None:
                                    pe_val_dec = to_decimal(row['value'])
                                    self.last_run_context["fundamental_inputs"].append({"stock_code": stock_code_text, "metric": "pe", **dict(row)})
                        except Exception as e:
                            logger.error(f"查詢 PE 失敗: {e}")

                        if pe_val_dec is None:
                            # 查不到基本面資料，明確排除
                            row = self._matrix_row(
                                stock_code=stock_code_text,
                                stock_name=stock_name_text,
                                status="skipped",
                                reason_codes=["valuation_pe_missing"],
                                quality="missing",
                                stage="strategy_evaluation",
                                threshold_name="filters.pe_ratio_max",
                                observed_value="missing",
                                required_value=pe_ratio_max,
                                threshold_mode=threshold_mode,
                            )
                            self.last_screening_matrix.append(row)
                            matrix_rows_by_stock[stock_code_text] = row
                            stats['skipped_no_result'] += 1
                            continue

                        if pe_val_dec > pe_ratio_max:
                            row = self._matrix_row(
                                stock_code=stock_code_text,
                                stock_name=stock_name_text,
                                status="skipped",
                                reason_codes=["valuation_pe_above_max"],
                                quality="observed",
                                stage="strategy_evaluation",
                                threshold_name="filters.pe_ratio_max",
                                observed_value=pe_val_dec,
                                required_value=pe_ratio_max,
                                threshold_mode=threshold_mode,
                            )
                            self.last_screening_matrix.append(row)
                            matrix_rows_by_stock[stock_code_text] = row
                            stats['skipped_no_result'] += 1
                            continue

                    # 2. 月營收 YOY% 過濾
                    if revenue_yoy_min > to_decimal("-100.0"):
                        yoy_val_dec = None
                        revenue_records = self._load_governed_monthly_revenues(
                            stock_code=stock_code_text,
                            decision_date=date.fromisoformat(decision_date),
                        )
                        if revenue_records:
                            self.last_run_context["fundamental_inputs"].extend({
                                "stock_code": stock_code_text, "metric": "monthly_revenue", "period": record.period,
                                "available_date": record.available_date.isoformat(), "source": record.source,
                                "source_version": record.source_version, "value": str(record.revenue),
                            } for record in sorted(revenue_records, key=lambda item: (item.period, item.available_date, item.source_version)))
                            latest_revenue = max(
                                revenue_records,
                                key=lambda record: (
                                    record.period,
                                    record.available_date,
                                    record.source_version,
                                ),
                            )
                            year_curr, month_curr = map(
                                int,
                                latest_revenue.period.split("-"),
                            )
                            period_prev = f"{year_curr - 1:04d}-{month_curr:02d}"
                            prior_candidates = [
                                record
                                for record in revenue_records
                                if record.period == period_prev
                            ]
                            if prior_candidates:
                                prior_revenue = max(
                                    prior_candidates,
                                    key=lambda record: (
                                        record.available_date,
                                        record.source_version,
                                    ),
                                )
                                if prior_revenue.revenue > to_decimal("0"):
                                    yoy_val_dec = (
                                        (latest_revenue.revenue - prior_revenue.revenue)
                                        / prior_revenue.revenue
                                    ) * to_decimal("100.0")

                        if yoy_val_dec is None:
                            # 查不到營收或去年同期營收，明確排除
                            row = self._matrix_row(
                                stock_code=stock_code_text,
                                stock_name=stock_name_text,
                                status="skipped",
                                reason_codes=["fundamental_revenue_yoy_missing"],
                                quality="missing",
                                stage="strategy_evaluation",
                                threshold_name="filters.monthly_revenue_yoy_min",
                                observed_value="missing",
                                required_value=revenue_yoy_min,
                                threshold_mode=threshold_mode,
                            )
                            self.last_screening_matrix.append(row)
                            matrix_rows_by_stock[stock_code_text] = row
                            stats['skipped_no_result'] += 1
                            continue

                        if yoy_val_dec < revenue_yoy_min:
                            row = self._matrix_row(
                                stock_code=stock_code_text,
                                stock_name=stock_name_text,
                                status="skipped",
                                reason_codes=["fundamental_revenue_yoy_below_min"],
                                quality="observed",
                                stage="strategy_evaluation",
                                threshold_name="filters.monthly_revenue_yoy_min",
                                observed_value=yoy_val_dec.quantize(to_decimal("0.01")),
                                required_value=revenue_yoy_min,
                                threshold_mode=threshold_mode,
                            )
                            self.last_screening_matrix.append(row)
                            matrix_rows_by_stock[stock_code_text] = row
                            stats['skipped_no_result'] += 1
                            continue

                    # 獲取收盤價
                    close_col = None
                    for col in ['收盤價', 'Close', 'close']:
                        if col in latest_row.index:
                            close_col = col
                            break

                    price_change_value = latest_feature_decimal(stock_df, "漲幅%")
                    volume_change_value = latest_feature_decimal(
                        stock_df,
                        "成交量變化率%",
                    )
                    price_change = float(price_change_value or Decimal("0"))

                    # DTO / reason DataFrame 邊界沿用既有數值欄位型態，不重新計算。
                    latest_row = latest_row.copy()
                    latest_row['漲幅%'] = price_change
                    latest_row['成交量變化率%'] = float(
                        volume_change_value or Decimal("0")
                    )

                    # 獲取股票所屬產業
                    stock_industries = [] if cutoff else self.industry_mapper.get_stock_industries(stock_code)
                    industry_display = ', '.join(stock_industries[:2]) if stock_industries else '未知'
                    if len(stock_industries) > 2:
                        industry_display += '...'

                    # 生成推薦理由（包含市場狀態和產業信息）
                    reasons = self.reason_engine.generate_reasons(latest_row, config)

                    # 添加產業表現理由
                    if stock_industries:
                        for industry in stock_industries[:1]:  # 只取第一個產業
                            industry_perf = self.industry_mapper.get_industry_performance(industry, date=decision_date)
                            if industry_perf:
                                industry_change = industry_perf.get('漲跌百分比', 0)
                                if isinstance(industry_change, str):
                                    try:
                                        industry_change = float(industry_change.replace('%', ''))
                                    except:
                                        industry_change = 0

                                if industry_change > 0:
                                    reasons.append({
                                        'tag': f'{industry}指數上漲',
                                        'evidence': f'{industry}類指數漲幅 {industry_change:.2f}%',
                                        'score_contrib': min(industry_change * 0.5, 10)
                                    })

                    reason_text = self.reason_engine.format_reason_text(reasons, max_reasons=3)

                    # 使用 FinalScore（含 Regime Match Factor）作為排序依據
                    final_score = latest_row.get(
                        'FinalScore',
                        latest_row.get('TotalScore', latest_row.get('綜合評分'))
                    )
                    if final_score is None or not to_decimal(final_score).is_finite():
                        row = self._matrix_row(
                            stock_code=stock_code_text, stock_name=stock_name_text,
                            status="missing", reason_codes=["total_score_missing_or_nonfinite"],
                            quality="missing", stage="strategy_evaluation", threshold_mode=threshold_mode,
                        )
                        self.last_screening_matrix.append(row)
                        matrix_rows_by_stock[stock_code_text] = row
                        stats['skipped_no_result'] += 1
                        continue

                    # 判斷 Regime Match
                    regime = config.get('regime', None)
                    regime_match = False
                    if regime:
                        # 簡單判斷：如果 FinalScore > TotalScore，則匹配
                        total_score = latest_row.get('TotalScore', 0)
                        if to_decimal(final_score) > to_decimal(total_score) * to_decimal("1.05"):  # 允許5%誤差
                            regime_match = True

                    # 創建 DTO
                    recommendation = RecommendationDTO(
                        stock_code=stock_code_text,
                        stock_name=latest_row.get('證券名稱', stock_df.iloc[-1].get('證券名稱', stock_code)),
                        close_price=to_decimal(latest_row.get(close_col, stock_df.iloc[-1].get(close_col, 0))) if close_col else Decimal("0"),
                        price_change=price_change,
                        total_score=final_score,
                        indicator_score=latest_row.get('IndicatorScore', 0),
                        pattern_score=latest_row.get('PatternScore', 0),
                        volume_score=latest_row.get('VolumeScore', 0),
                        recommendation_reasons=reason_text,
                        industry=industry_display,
                        regime_match=regime_match
                    )

                    all_recommendations.append(recommendation)
                    row = self._matrix_row(
                        stock_code=stock_code_text,
                        stock_name=str(recommendation.stock_name),
                        status="fail",
                        reason_codes=["pending_final_selection"],
                        quality="observed",
                        stage="candidate_scored",
                        total_score=final_score,
                        threshold_mode=threshold_mode,
                        industry=industry_display,
                    )
                    self.last_screening_matrix.append(row)
                    matrix_rows_by_stock[stock_code_text] = row
                    stats['success'] += 1
                else:
                    stats['skipped_no_result'] += 1

            except Exception as e:
                # 跳過處理失敗的股票
                stats['skipped_exception'] += 1
                row = self._matrix_row(
                    stock_code=stock_code_text,
                    stock_name=stock_name_text,
                    status="degraded",
                    reason_codes=["screening_exception"],
                    quality="degraded",
                    stage="strategy_evaluation",
                    threshold_name=type(e).__name__,
                    observed_value=str(e),
                    required_value="successful_evaluation",
                    threshold_mode=threshold_mode,
                    warnings=[f"screening_exception:{type(e).__name__}"],
                )
                self.last_screening_matrix.append(row)
                matrix_rows_by_stock[stock_code_text] = row
                # 記錄前3個異常的詳細信息（避免日誌過多）
                if stats['skipped_exception'] <= 3:
                    import logging
                    import traceback
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        f"處理股票 {stock_code} 時發生異常: {str(e)}\n"
                        f"異常類型: {type(e).__name__}\n"
                        f"堆疊追蹤:\n{traceback.format_exc()}"
                    )
                continue

        # ✅ 記錄處理結果摘要
        logger.info(
            f"[RecommendationService] 推薦分析完成: "
            f"總股票數={stats['total_stocks']}, "
            f"已處理={stats['processed']}, "
            f"成功={stats['success']}, "
            f"返回推薦數={len(all_recommendations)}"
        )

        # 如果沒有找到任何推薦，提供調試信息
        if len(all_recommendations) == 0 and stats['total_stocks'] > 0:
            logger.warning(
                f"推薦分析未找到任何股票。統計："
                f"總股票數={stats['total_stocks']}, "
                f"已處理={stats['processed']}, "
                f"成功={stats['success']}, "
                f"數據不足={stats['skipped_insufficient_data']}, "
                f"無結果={stats['skipped_no_result']}, "
                f"異常={stats['skipped_exception']}"
            )

            # 提供診斷建議
            if stats['skipped_no_result'] > 0:
                logger.warning(
                    f"診斷建議："
                    f"有 {stats['skipped_no_result']} 支股票被篩選過濾。"
                    f"請檢查："
                    f"1. 最小漲幅% 是否過高（當前：{config.get('filters', {}).get('price_change_min', 0)}%）"
                    f"2. 最小成交量比率是否過高（當前：{config.get('filters', {}).get('volume_ratio_min', 1.0)}）"
                    f"3. 技術指標或圖形模式是否過於嚴格"
                )

        latest_date_str = ""
        if not all_recommendations:
            self.last_run_context["eligible_universe_size"] = 0
            self._finalize_negative_evidence_buffers()
            return []
        if not df.empty and "日期" in df.columns:
            latest_date_str = df["日期"].max().strftime("%Y-%m-%d")
        ranking_plan = build_ranking_plan(
            [(rec.stock_code, rec.total_score) for rec in all_recommendations],
            mode=threshold_mode,
            top_n=top_n,
            ranking_config=ranking_config,
            eligible_universe_date=decision_cutoff or latest_date_str,
        )
        self.last_run_context["eligible_universe_size"] = ranking_plan.eligible_universe_size
        recommendations_by_code = {
            rec.stock_code: rec for rec in all_recommendations
        }

        for rec in all_recommendations:
            rec.threshold_mode = ranking_plan.mode
            rec.eligible_universe_size = ranking_plan.eligible_universe_size
            rec.eligible_universe_date = ranking_plan.eligible_universe_date
            rec.ranking_method = ranking_plan.ranking_method
            matrix_row_for_rec = matrix_rows_by_stock.get(rec.stock_code)
            if ranking_plan.mode != "quantile":
                continue
            percentile_bp = ranking_plan.percentiles_bp.get(rec.stock_code, 0)
            if matrix_row_for_rec is not None:
                matrix_row_for_rec["score_percentile_bp"] = percentile_bp
                matrix_row_for_rec["eligible_universe_size"] = (
                    ranking_plan.eligible_universe_size
                )
                matrix_row_for_rec["threshold_name"] = (
                    "recommendation_min_percentile_bp"
                )
                matrix_row_for_rec["observed_value"] = str(percentile_bp)
                matrix_row_for_rec["required_value"] = str(
                    ranking_plan.minimum_percentile_bp
                )
                matrix_row_for_rec["threshold_mode"] = "quantile"
            if rec.stock_code in ranking_plan.ordered_codes:
                rec.score_percentile_bp = percentile_bp
                rec.eligible_universe_size = ranking_plan.eligible_universe_size
                rec.eligible_universe_date = ranking_plan.eligible_universe_date
                rec.ranking_method = ranking_plan.ranking_method
            elif matrix_row_for_rec is not None:
                matrix_row_for_rec["status"] = "fail"
                matrix_row_for_rec["reason_codes"] = [
                    "recommendation_percentile_below_min"
                ]
                matrix_row_for_rec["quality"] = "observed"
                matrix_row_for_rec["stage"] = "threshold_gate"

        ordered_recommendations = [
            recommendations_by_code[code] for code in ranking_plan.ordered_codes
        ]
        selected_codes = set(ranking_plan.selected_codes)
        for rank, rec in enumerate(ordered_recommendations, start=1):
            matrix_row_for_rec = matrix_rows_by_stock.get(rec.stock_code)
            if matrix_row_for_rec is None:
                continue
            if rec.stock_code in selected_codes:
                matrix_row_for_rec["status"] = "pass"
                matrix_row_for_rec["reason_codes"] = ["recommendation_selected"]
                matrix_row_for_rec["stage"] = "final_selection"
            else:
                matrix_row_for_rec["status"] = "fail"
                matrix_row_for_rec["reason_codes"] = [
                    "recommendation_outside_top_n"
                ]
                matrix_row_for_rec["stage"] = "top_n_gate"
                matrix_row_for_rec["threshold_name"] = "top_n"
                matrix_row_for_rec["observed_value"] = str(rank)
                matrix_row_for_rec["required_value"] = str(top_n)
        all_recommendations = [
            recommendations_by_code[code] for code in ranking_plan.selected_codes
        ]
        self._finalize_negative_evidence_buffers()
        return all_recommendations

    def detect_regime(self) -> Dict[str, Any]:
        """檢測市場狀態

        Returns:
            dict: {
                'regime': 'Trend' | 'Reversion' | 'Breakout',
                'confidence': float (0-1),
                'details': dict,
                'regime_name_cn': str
            }
        """
        regime_result = self.regime_detector.detect_regime()
        regime = regime_result.get('regime', 'Trend')
        confidence = regime_result.get('confidence', 0.5)
        details = regime_result.get('details', {})

        regime_name_map = {
            'Trend': '趨勢追蹤',
            'Reversion': '均值回歸',
            'Breakout': '突破準備'
        }
        regime_name_cn = regime_name_map.get(regime, regime)

        return {
            'regime': regime,
            'confidence': confidence,
            'details': details,
            'regime_name_cn': regime_name_cn
        }

    def get_strategy_config_for_regime(self, regime: str) -> Dict[str, Any]:
        """獲取指定市場狀態的策略配置

        Args:
            regime: 'Trend' | 'Reversion' | 'Breakout'

        Returns:
            dict: 策略配置字典
        """
        return self.regime_detector.get_strategy_config(regime)

    def load_strategy_from_preset(
        self,
        preset_id: str,
        preset_service: PresetService
    ) -> Optional[Dict[str, Any]]:
        """
        從 Preset 載入策略配置

        Args:
            preset_id: Preset ID
            preset_service: PresetService 實例

        Returns:
            策略配置字典或 None
        """
        preset = preset_service.load_preset(preset_id)
        if preset is None:
            return None
        preset_meta = preset.meta or {}

        # 構建策略配置字典
        config = {
            'strategy_id': preset.strategy_id,
            'params': preset.params,
            **preset_meta.get('config', {})
        }

        return config

    def load_strategy_from_version(
        self,
        version_id: str,
        strategy_version_service: StrategyVersionService
    ) -> Optional[Dict[str, Any]]:
        """
        從策略版本載入策略配置

        Args:
            version_id: 策略版本 ID
            strategy_version_service: StrategyVersionService 實例

        Returns:
            策略配置字典或 None
        """
        version = strategy_version_service.get_version(version_id)
        if version is None:
            return None

        # 構建策略配置字典
        config = {
            'strategy_id': version.strategy_id,
            'strategy_version': version.strategy_version,
            'params': version.params,
            **version.config
        }

        return config

    def load_strategy_spec_from_preset(
        self,
        preset_id: str,
        preset_service: PresetService
    ) -> Optional[StrategySpec]:
        """
        從 Preset 載入 StrategySpec

        Args:
            preset_id: Preset ID
            preset_service: PresetService 實例

        Returns:
            StrategySpec 對象或 None
        """
        preset = preset_service.load_preset(preset_id)
        if preset is None:
            return None
        preset_meta = preset.meta or {}

        return StrategySpec(
            strategy_id=preset.strategy_id,
            strategy_version=preset_meta.get('strategy_version', '1.0.0'),
            default_params=preset.params,
            config=preset_meta.get('config', {})
        )

    def load_strategy_spec_from_version(
        self,
        version_id: str,
        strategy_version_service: StrategyVersionService
    ) -> Optional[StrategySpec]:
        """
        從策略版本載入 StrategySpec

        Args:
            version_id: 策略版本 ID
            strategy_version_service: StrategyVersionService 實例

        Returns:
            StrategySpec 對象或 None
        """
        version = strategy_version_service.get_version(version_id)
        if version is None:
            return None

        return StrategySpec(
            strategy_id=version.strategy_id,
            strategy_version=version.strategy_version,
            default_params=version.params,
            config=version.config,
            regime=version.regime
        )

