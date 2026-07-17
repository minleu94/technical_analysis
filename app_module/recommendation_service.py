"""
推薦服務 (Recommendation Service)
提供股票推薦的業務邏輯，供 UI 層調用
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

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
from app_module.recommendation_ranking_pipeline import build_ranking_plan
from app_module.application_ports import MarketFrameProvider


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

    def _reset_negative_evidence_buffers(self) -> None:
        self.last_screening_matrix = []
        self.last_excluded_candidates_json = []
        self.last_why_not_payload_json = []
        self.last_liquidity_gate_payload_json = []
        self.last_exclusion_quality = "observed"
        self.last_exclusion_warnings_json = []

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
        buffers = build_negative_evidence_buffers(self.last_screening_matrix)
        self.last_excluded_candidates_json = buffers.excluded_candidates
        self.last_why_not_payload_json = buffers.why_not_payload
        self.last_liquidity_gate_payload_json = buffers.liquidity_gate_payload
        self.last_exclusion_quality = buffers.exclusion_quality
        self.last_exclusion_warnings_json = buffers.exclusion_warnings

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

    def run_recommendation(
        self,
        config: Dict[str, Any],
        max_stocks: int = 200,
        top_n: int = 50
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
        ranking_config, threshold_mode = self._validate_ranking_config(config)
        self._reset_negative_evidence_buffers()

        # ✅ 記錄輸入參數
        logger.info(
            f"[RecommendationService] 開始推薦分析: "
            f"max_stocks={max_stocks}, top_n={top_n}, "
            f"產業篩選={config.get('filters', {}).get('industry', '全部')}, "
            f"圖形模式={config.get('patterns', {}).get('selected', [])}, "
            f"技術指標啟用={config.get('technical', {}).get('momentum', {}).get('enabled', False) or config.get('technical', {}).get('trend', {}).get('enabled', False)}"
        )

        df, stock_col = normalize_market_frame(self.market_data_provider())

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
                raise ValueError(error_msg)

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
                result_df = self.strategy_configurator.generate_recommendations(stock_df, config)

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
                    raw_date = stock_df.iloc[-1]['日期']
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
                        import sqlite3
                        try:
                            with sqlite3.connect(self.config.db_file) as conn:
                                conn.row_factory = sqlite3.Row
                                cursor = conn.cursor()
                                cursor.execute(
                                    "SELECT value FROM fundamental_valuation_metrics "
                                    "WHERE stock_code = ? AND metric_name = 'pe' AND available_date <= ? "
                                    "ORDER BY available_date DESC, as_of_date DESC LIMIT 1",
                                    (stock_code_text, decision_date)
                                )
                                row = cursor.fetchone()
                                if row and row['value'] is not None:
                                    pe_val_dec = to_decimal(row['value'])
                        except Exception as e:
                            logger.error(f"查詢 PE 失敗: {e}")

                        if pe_val_dec is None:
                            # 查不到基本面資料，明確排除
                            row = self._matrix_row(
                                stock_code=stock_code_text,
                                stock_name=stock_name_text,
                                status="skipped",
                                reason_codes=["valuation_pe_missing"],
                                quality="observed",
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
                        import sqlite3
                        try:
                            with sqlite3.connect(self.config.db_file) as conn:
                                conn.row_factory = sqlite3.Row
                                cursor = conn.cursor()
                                cursor.execute(
                                    "SELECT period, revenue FROM fundamental_monthly_revenues "
                                    "WHERE stock_code = ? AND available_date <= ? "
                                    "ORDER BY available_date DESC, period DESC LIMIT 1",
                                    (stock_code_text, decision_date)
                                )
                                row = cursor.fetchone()
                                if row and row['revenue'] is not None:
                                    period_curr = row['period']
                                    rev_curr_dec = to_decimal(row['revenue'])

                                    year_curr, month_curr = map(int, period_curr.split('-'))
                                    period_prev = f"{year_curr - 1:04d}-{month_curr:02d}"

                                    # 去年同期營收查詢，同樣限制 available_date <= decision_date，並以 available_date 與 period 穩定降序排列以滿足 PIT 可重複性
                                    cursor.execute(
                                        "SELECT revenue FROM fundamental_monthly_revenues "
                                        "WHERE stock_code = ? AND period = ? AND available_date <= ? "
                                        "ORDER BY available_date DESC, period DESC LIMIT 1",
                                        (stock_code_text, period_prev, decision_date)
                                    )
                                    row_prev = cursor.fetchone()
                                    if row_prev and row_prev['revenue'] is not None:
                                        rev_prev_dec = to_decimal(row_prev['revenue'])
                                        if rev_prev_dec > to_decimal("0"):
                                            yoy_val_dec = ((rev_curr_dec - rev_prev_dec) / rev_prev_dec) * to_decimal("100.0")
                        except Exception as e:
                            logger.error(f"查詢月營收 YOY 失敗: {e}")

                        if yoy_val_dec is None:
                            # 查不到營收或去年同期營收，明確排除
                            row = self._matrix_row(
                                stock_code=stock_code_text,
                                stock_name=stock_name_text,
                                status="skipped",
                                reason_codes=["fundamental_revenue_yoy_missing"],
                                quality="observed",
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
                    stock_industries = self.industry_mapper.get_stock_industries(stock_code)
                    industry_display = ', '.join(stock_industries[:2]) if stock_industries else '未知'
                    if len(stock_industries) > 2:
                        industry_display += '...'

                    # 生成推薦理由（包含市場狀態和產業信息）
                    reasons = self.reason_engine.generate_reasons(latest_row, config)

                    # 添加產業表現理由
                    if stock_industries:
                        for industry in stock_industries[:1]:  # 只取第一個產業
                            industry_perf = self.industry_mapper.get_industry_performance(industry)
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
                        latest_row.get('TotalScore', latest_row.get('綜合評分', 0))
                    )

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
                        close_price=latest_row.get(close_col, stock_df.iloc[-1].get(close_col, 0)) if close_col else 0,
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
        if not df.empty and "日期" in df.columns:
            latest_date_str = df["日期"].max().strftime("%Y-%m-%d")
        ranking_plan = build_ranking_plan(
            [(rec.stock_code, rec.total_score) for rec in all_recommendations],
            mode=threshold_mode,
            top_n=top_n,
            ranking_config=ranking_config,
            eligible_universe_date=latest_date_str,
        )
        recommendations_by_code = {
            rec.stock_code: rec for rec in all_recommendations
        }

        for rec in all_recommendations:
            rec.threshold_mode = ranking_plan.mode
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

