"""
推薦服務 (Recommendation Service)
提供股票推薦的業務邏輯，供 UI 層調用
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

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


class RecommendationService:
    """推薦服務類"""
    
    def __init__(self, config, industry_mapper: Optional[IndustryMapper] = None):
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
        self.regime_detector = MarketRegimeDetector(config)
    
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
        
        # ✅ 記錄輸入參數
        logger.info(
            f"[RecommendationService] 開始推薦分析: "
            f"max_stocks={max_stocks}, top_n={top_n}, "
            f"產業篩選={config.get('filters', {}).get('industry', '全部')}, "
            f"圖形模式={config.get('patterns', {}).get('selected', [])}, "
            f"技術指標啟用={config.get('technical', {}).get('momentum', {}).get('enabled', False) or config.get('technical', {}).get('trend', {}).get('enabled', False)}"
        )
        
        # 讀取股票數據（優先使用備用文件，因為它通常更新）
        primary_file = self.config.stock_data_file
        backup_file = self.config.all_stocks_data_file
        
        # ✅ 優先使用備用文件（all_stocks_data.csv），因為它通常包含最新數據
        # 如果備用文件不存在，再使用主要文件
        if backup_file.exists():
            stock_data_file = backup_file
            logger.info(
                f"[RecommendationService] 使用備用數據文件（通常較新）: {backup_file}"
            )
        elif primary_file.exists():
            stock_data_file = primary_file
            logger.info(
                f"[RecommendationService] 使用主要數據文件: {primary_file}"
            )
        else:
            raise FileNotFoundError(
                f"找不到股票數據文件:\n"
                f"主要文件: {primary_file} (存在: {primary_file.exists()})\n"
                f"備用文件: {backup_file} (存在: {backup_file.exists()})\n"
                f"請確認數據文件是否存在，或執行數據更新"
            )
        
        # ✅ 記錄實際使用的數據文件
        logger.info(
            f"[RecommendationService] 使用數據文件: {stock_data_file}, "
            f"文件大小: {stock_data_file.stat().st_size / 1024 / 1024:.2f} MB"
        )
        
        # ✅ 記錄實際使用的數據文件
        logger.info(
            f"[RecommendationService] 使用數據文件: {stock_data_file}, "
            f"文件大小: {stock_data_file.stat().st_size / 1024 / 1024:.2f} MB"
        )
        
        # 讀取最新數據（最近60天，確保有足夠數據計算技術指標）
        df = pd.read_csv(
            stock_data_file, 
            encoding='utf-8-sig', 
            on_bad_lines='skip', 
            engine='python', 
            nrows=500000
        )
        
        # ✅ 修復：改進日期解析（支持多種格式）
        if '日期' in df.columns:
            date_col = df['日期'].copy()
            # 嘗試多種日期格式
            if date_col.dtype in ['int64', 'int32', 'float64']:
                # 如果是數字，嘗試 YYYYMMDD 格式
                df['日期'] = pd.to_datetime(date_col.astype(str), errors='coerce', format='%Y%m%d')
            else:
                # 如果是字符串，先嘗試 YYYYMMDD
                date_str = date_col.astype(str)
                # 檢查是否為 8 位數字字符串
                if date_str.str.len().eq(8).all() and date_str.str.isdigit().all():
                    df['日期'] = pd.to_datetime(date_str, errors='coerce', format='%Y%m%d')
                else:
                    # 否則自動解析
                    df['日期'] = pd.to_datetime(date_col, errors='coerce')
        else:
            raise ValueError("找不到日期欄位")
        
        df = df[df['日期'].notna()]

        if len(df) == 0:
            raise ValueError("沒有找到股票數據")

        # ✅ 記錄原始數據的日期範圍
        raw_min_date = df['日期'].min()
        raw_max_date = df['日期'].max()
        logger.info(
            f"[RecommendationService] 原始數據日期範圍: {raw_min_date} ~ {raw_max_date}, "
            f"總筆數={len(df)}"
        )
        
        # 檢查數據是否過舊（超過1年）
        from datetime import datetime
        one_year_ago = datetime.now() - pd.Timedelta(days=365)
        if raw_max_date < one_year_ago:
            logger.warning(
                f"[RecommendationService] ⚠️ 警告：數據文件中的最新日期 ({raw_max_date}) "
                f"已經超過1年，建議更新數據文件: {stock_data_file}"
            )

        latest_date = df['日期'].max()
        # 取最近60天的數據
        df = df[df['日期'] >= (latest_date - pd.Timedelta(days=60))]
        
        if len(df) == 0:
            raise ValueError("沒有找到足夠的歷史數據")
        
        # 按股票分組處理
        if '證券代號' in df.columns:
            stock_col = '證券代號'
        elif '股票代號' in df.columns:
            stock_col = '股票代號'
            df['證券代號'] = df['股票代號']
            stock_col = '證券代號'
        else:
            raise ValueError("找不到股票代號欄位")
        
        # 確保有證券名稱欄位
        if '證券名稱' not in df.columns:
            if '股票名稱' in df.columns:
                df['證券名稱'] = df['股票名稱']
            else:
                df['證券名稱'] = df['證券代號']
        
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
        
        # ✅ 記錄處理開始
        logger.info(
            f"[RecommendationService] 開始處理 {len(stocks)} 支股票"
        )
        
        # 對每支股票執行策略分析
        all_recommendations = []
        
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
            
            # 確保至少有20筆數據才能計算技術指標
            if len(stock_df) < 20:
                stats['skipped_insufficient_data'] += 1
                continue
            
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
                
                if len(result_df) > 0:
                    latest_row = result_df.iloc[-1]
                    
                    # 獲取收盤價
                    close_col = None
                    for col in ['收盤價', 'Close', 'close']:
                        if col in latest_row.index:
                            close_col = col
                            break
                    
                    # 計算漲幅（與前一日比較）
                    price_change = 0
                    if len(stock_df) >= 2 and close_col:
                        # ✅ 修復：確保轉換為數值類型
                        prev_price = pd.to_numeric(stock_df.iloc[-2].get(close_col, 0), errors='coerce')
                        curr_price = pd.to_numeric(latest_row.get(close_col, 0), errors='coerce')
                        # 處理 NaN
                        if pd.isna(prev_price):
                            prev_price = 0
                        if pd.isna(curr_price):
                            curr_price = 0
                        
                        if prev_price > 0:
                            price_change = (curr_price - prev_price) / prev_price * 100
                    
                    # 將漲幅添加到 latest_row（用於篩選）
                    latest_row = latest_row.copy()
                    latest_row['漲幅%'] = price_change
                    
                    # 計算成交量變化率（如果需要的話）
                    if '成交股數' in stock_df.columns and len(stock_df) >= 21:
                        # ✅ 修復：確保轉換為數值類型
                        latest_volume = pd.to_numeric(stock_df['成交股數'].iloc[-1], errors='coerce')
                        volume_ma20 = pd.to_numeric(stock_df['成交股數'].iloc[-21:-1], errors='coerce').mean()
                        if pd.isna(latest_volume):
                            latest_volume = 0
                        if pd.isna(volume_ma20) or volume_ma20 <= 0:
                            latest_row['成交量變化率%'] = 0.0
                        else:
                            volume_ratio = latest_volume / volume_ma20
                            latest_row['成交量變化率%'] = (volume_ratio - 1) * 100
                    elif '成交股數' in stock_df.columns and len(stock_df) >= 2:
                        latest_volume = stock_df['成交股數'].iloc[-1]
                        volume_ma = stock_df['成交股數'].iloc[:-1].mean()
                        if volume_ma > 0:
                            volume_ratio = latest_volume / volume_ma
                            latest_row['成交量變化率%'] = (volume_ratio - 1) * 100
                        else:
                            latest_row['成交量變化率%'] = 0
                    else:
                        latest_row['成交量變化率%'] = 0
                    
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
                        if final_score > total_score * 1.05:  # 允許5%誤差
                            regime_match = True
                    
                    # 創建 DTO
                    recommendation = RecommendationDTO(
                        stock_code=str(stock_code),
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
                    stats['success'] += 1
                else:
                    stats['skipped_no_result'] += 1
                    
            except Exception as e:
                # 跳過處理失敗的股票
                stats['skipped_exception'] += 1
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
        
        # 按總分降序排序，返回前 top_n 名
        all_recommendations.sort(key=lambda x: x.total_score, reverse=True)
        return all_recommendations[:top_n]
    
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
        
        # 構建策略配置字典
        config = {
            'strategy_id': preset.strategy_id,
            'params': preset.params,
            **preset.meta.get('config', {})
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
        
        return StrategySpec(
            strategy_id=preset.strategy_id,
            strategy_version=preset.meta.get('strategy_version', '1.0.0'),
            default_params=preset.params,
            config=preset.meta.get('config', {})
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

