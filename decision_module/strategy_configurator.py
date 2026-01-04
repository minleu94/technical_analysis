"""
策略配置器模組
整合所有分析功能，提供靈活的策略配置
"""

import pandas as pd
import numpy as np
from analysis_module import (
    TechnicalAnalyzer,
    PatternAnalyzer,
    SignalCombiner,
    MLAnalyzer
)
from decision_module.scoring_engine import ScoringEngine

class StrategyConfigurator:
    """策略配置器，整合所有分析功能"""
    
    def __init__(self):
        """初始化策略配置器"""
        self.technical_analyzer = TechnicalAnalyzer()
        self.pattern_analyzer = PatternAnalyzer()
        self.signal_combiner = SignalCombiner()
        self.ml_analyzer = MLAnalyzer()
        self.scoring_engine = ScoringEngine()  # 統一打分引擎
        
        # 可用的圖形模式
        self.available_patterns = [
            'W底', '頭肩頂', '頭肩底', '雙頂', '雙底',
            '三角形', '旗形', 'V形反轉', '圓頂', '圓底', '矩形', '楔形'
        ]
    
    def configure_technical_indicators(self, df, config):
        """配置技術指標
        
        Args:
            df: 股票數據DataFrame
            config: 配置字典，格式如下：
                {
                    'momentum': {
                        'enabled': True,
                        'rsi': {'enabled': True, 'period': 14},
                        'macd': {'enabled': True, 'fast': 12, 'slow': 26, 'signal': 9},
                        'kd': {'enabled': False}
                    },
                    'volatility': {
                        'enabled': True,
                        'bollinger': {'enabled': True, 'window': 20, 'std': 2},
                        'atr': {'enabled': True, 'period': 14}
                    },
                    'trend': {
                        'enabled': True,
                        'adx': {'enabled': True, 'period': 14},
                        'ma': {'enabled': True, 'windows': [5, 10, 20, 60]}
                    }
                }
        
        Returns:
            DataFrame: 添加技術指標後的數據
        """
        df_result = df.copy()
        
        try:
            # 動量指標
            if config.get('momentum', {}).get('enabled', False):
                momentum_config = config['momentum']
                if momentum_config.get('rsi', {}).get('enabled', False):
                    df_result = self.technical_analyzer.add_momentum_indicators(df_result)
                if momentum_config.get('macd', {}).get('enabled', False):
                    df_result = self.technical_analyzer.add_momentum_indicators(df_result)
                if momentum_config.get('kd', {}).get('enabled', False):
                    df_result = self.technical_analyzer.add_momentum_indicators(df_result)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"配置動量指標時發生異常: {str(e)}")
        
        try:
            # 波動率指標
            if config.get('volatility', {}).get('enabled', False):
                df_result = self.technical_analyzer.add_volatility_indicators(df_result)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"配置波動率指標時發生異常: {str(e)}")
        
        try:
            # 趨勢指標
            if config.get('trend', {}).get('enabled', False):
                df_result = self.technical_analyzer.add_trend_indicators(df_result)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"配置趨勢指標時發生異常: {str(e)}")
        
        return df_result
    
    def identify_patterns(self, df, pattern_types):
        """識別圖形模式
        
        Args:
            df: 股票數據DataFrame
            pattern_types: 要識別的圖形模式列表，例如 ['W底', '頭肩頂']
        
        Returns:
            dict: 識別出的圖形模式，格式為 {模式名稱: [(開始索引, 結束索引), ...]}
        """
        patterns_found = {}
        for pattern_type in pattern_types:
            if pattern_type in self.available_patterns:
                patterns = self.pattern_analyzer.identify_pattern(df, pattern_type)
                if patterns:
                    patterns_found[pattern_type] = patterns
        return patterns_found
    
    def combine_signals(self, df, config):
        """組合信號
        
        Args:
            df: 股票數據DataFrame（已包含技術指標）
            config: 配置字典，格式如下：
                {
                    'pattern_types': ['W底', '頭肩底'],
                    'technical_indicators': ['momentum', 'volatility', 'trend'],
                    'volume_conditions': ['increasing', 'spike'],
                    'weights': {
                        'pattern': 0.3,
                        'technical': 0.5,
                        'volume': 0.2
                    }
                }
        
        Returns:
            DataFrame: 包含組合信號的DataFrame
        """
        pattern_types = config.get('pattern_types', [])
        technical_indicators = config.get('technical_indicators', [])
        volume_conditions = config.get('volume_conditions', [])
        
        # 使用 SignalCombiner 組合信號
        df_result = self.signal_combiner.analyze_combined_signals(
            df,
            pattern_types=pattern_types,
            technical_indicators=technical_indicators,
            volume_conditions=volume_conditions
        )
        
        return df_result
    
    def screen_stocks(self, df, filters):
        """篩選股票
        
        Args:
            df: 股票數據DataFrame
            filters: 篩選條件字典，格式如下：
                {
                    'price_change_min': 0.0,  # 最小漲幅（%）
                    'price_change_max': 100.0,  # 最大漲幅（%）
                    'volume_ratio_min': 1.0,  # 最小成交量比率
                    'rsi_min': 0,  # RSI最小值
                    'rsi_max': 100,  # RSI最大值
                    'market_cap_min': None,  # 最小市值（可選）
                    'market_cap_max': None  # 最大市值（可選）
                }
        
        Returns:
            DataFrame: 篩選後的股票數據
        """
        import logging
        logger = logging.getLogger(__name__)
        
        df_result = df.copy()
        original_count = len(df_result)
        
        # ✅ 記錄篩選開始
        logger.debug(
            f"[screen_stocks] 開始篩選: "
            f"原始筆數={original_count}, "
            f"篩選條件={filters}"
        )
        
        # 漲幅篩選
        if 'price_change_min' in filters or 'price_change_max' in filters:
            if '漲幅%' in df_result.columns:
                before = len(df_result)
                if 'price_change_min' in filters:
                    df_result = df_result[df_result['漲幅%'] >= filters['price_change_min']]
                if 'price_change_max' in filters:
                    df_result = df_result[df_result['漲幅%'] <= filters['price_change_max']]
                after = len(df_result)
                
                # ✅ 記錄篩選結果
                logger.debug(
                    f"[screen_stocks] 漲幅篩選: {before} -> {after} "
                    f"(條件: {filters.get('price_change_min', 'N/A')} ~ {filters.get('price_change_max', 'N/A')})"
                )
                
                if before > 0 and after == 0:
                    # 顯示被過濾的樣本值
                    sample_values = df.iloc[0]['漲幅%'] if len(df) > 0 else 'N/A'
                    if not hasattr(StrategyConfigurator, '_price_filter_log_count'):
                        StrategyConfigurator._price_filter_log_count = 0
                    StrategyConfigurator._price_filter_log_count += 1
                    if StrategyConfigurator._price_filter_log_count <= 3:
                        logger.warning(
                            f"[漲幅篩選] 要求 >= {filters['price_change_min']}%, "
                            f"但樣本值={sample_values:.2f}%"
                        )
            else:
                # 如果欄位不存在，跳過漲幅篩選（不應該發生，但為了安全）
                import logging
                logger = logging.getLogger(__name__)
                logger.debug("漲幅%欄位不存在，跳過漲幅篩選")
        
        # 成交量比率篩選
        if 'volume_ratio_min' in filters:
            if '成交量變化率%' in df_result.columns:
                before = len(df_result)
                df_result = df_result[
                    df_result['成交量變化率%'] >= filters['volume_ratio_min']
                ]
                after = len(df_result)
                
                # ✅ 記錄篩選結果
                logger.debug(
                    f"[screen_stocks] 成交量篩選: {before} -> {after} "
                    f"(條件: >= {filters['volume_ratio_min']:.2f}%)"
                )
                
                if before > 0 and after == 0:
                    # 顯示被過濾的樣本值
                    sample_values = df.iloc[0]['成交量變化率%'] if len(df) > 0 else 'N/A'
                    if not hasattr(StrategyConfigurator, '_volume_filter_log_count'):
                        StrategyConfigurator._volume_filter_log_count = 0
                    StrategyConfigurator._volume_filter_log_count += 1
                    if StrategyConfigurator._volume_filter_log_count <= 3:
                        logger.warning(
                            f"[成交量篩選] 要求 >= {filters['volume_ratio_min']:.2f}%, "
                            f"但樣本值={sample_values:.2f}%"
                        )
            else:
                # 如果欄位不存在，跳過成交量篩選（不應該發生，但為了安全）
                import logging
                logger = logging.getLogger(__name__)
                logger.debug("成交量變化率%欄位不存在，跳過成交量篩選")
        
        # RSI篩選
        if 'rsi_min' in filters or 'rsi_max' in filters:
            rsi_col = None
            for col in ['RSI', 'rsi', 'RSI_14']:
                if col in df_result.columns:
                    rsi_col = col
                    break
            
            if rsi_col:
                if 'rsi_min' in filters:
                    df_result = df_result[df_result[rsi_col] >= filters['rsi_min']]
                if 'rsi_max' in filters:
                    df_result = df_result[df_result[rsi_col] <= filters['rsi_max']]
        
        # ✅ 記錄最終結果
        logger.debug(
            f"[screen_stocks] 篩選完成: "
            f"{original_count} -> {len(df_result)} "
            f"(過濾 {original_count - len(df_result)} 筆)"
        )
        
        return df_result
    
    def generate_recommendations(self, df, config):
        """生成股票推薦（使用統一打分模型）
        
        Args:
            df: 股票數據DataFrame（單一股票的歷史數據）
            config: 完整策略配置
        
        Returns:
            DataFrame: 推薦股票列表，包含評分和理由（只返回最新一筆）
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if len(df) == 0:
            return pd.DataFrame()
        
        # ✅ 記錄輸入
        stock_code = df.iloc[-1].get('證券代號', 'Unknown') if len(df) > 0 else 'Unknown'
        logger.debug(
            f"[StrategyConfigurator] 生成推薦: "
            f"股票={stock_code}, "
            f"數據筆數={len(df)}, "
            f"圖形模式={config.get('patterns', {}).get('selected', [])}"
        )
        
        try:
            # 確保日期欄位正確
            if '日期' in df.columns:
                df = df.sort_values('日期')
            
            # 1. 配置技術指標
            df = self.configure_technical_indicators(df, config.get('technical', {}))
            
            # ✅ 記錄技術指標計算結果
            indicator_cols = [col for col in df.columns if col in ['RSI', 'RSI_14', 'MACD', 'MACD_signal', 'MACD_hist', 
                                                           'ADX', 'MA5', 'MA10', 'MA20', 'MA60', 'ATR']]
            if indicator_cols:
                nan_ratio = df[indicator_cols].isna().sum().sum() / (len(df) * len(indicator_cols))
                logger.debug(
                    f"[StrategyConfigurator] 技術指標計算完成: "
                    f"指標欄位數={len(indicator_cols)}, "
                    f"NaN比例={nan_ratio:.2%}"
                )
            
            # 2. 識別圖形模式
            pattern_types = config.get('patterns', {}).get('selected', [])
            patterns_found = self.identify_patterns(df, pattern_types)
            
            # 3. 使用統一打分模型計算總分（含 Regime Match Factor）
            regime = config.get('regime', None)
            df = self.scoring_engine.calculate_total_score(df, config, regime=regime)
            
            # ✅ 記錄分數計算結果
            if len(df) > 0:
                latest_row = df.iloc[-1]
                logger.debug(
                    f"[StrategyConfigurator] 分數計算完成: "
                    f"股票={stock_code}, "
                    f"總分={latest_row.get('TotalScore', latest_row.get('FinalScore', 0)):.2f}, "
                    f"指標分={latest_row.get('IndicatorScore', 0):.2f}, "
                    f"圖形分={latest_row.get('PatternScore', 0):.2f}, "
                    f"成交量分={latest_row.get('VolumeScore', 0):.2f}"
                )
            
            # 4. 應用硬門檻篩選（在最新日期上）
            if len(df) == 0:
                return pd.DataFrame()
            
            latest_df = df.iloc[[-1]].copy()  # 只取最新一筆
            
            # 計算漲幅%（如果需要的話，用於篩選）
            # 注意：latest_df 是 DataFrame，應該檢查 columns 而不是 index
            if '漲幅%' not in latest_df.columns and len(df) >= 2:
                close_col = None
                for col in ['收盤價', 'Close', 'close']:
                    if col in df.columns:
                        close_col = col
                        break
                
                if close_col:
                    # ✅ 修復：確保轉換為數值類型
                    try:
                        # 正確獲取前一日價格（直接從 DataFrame 訪問）
                        prev_price_val = df[close_col].iloc[-2] if len(df) >= 2 else 0
                        prev_price = pd.to_numeric(prev_price_val, errors='coerce')
                        
                        # 正確獲取當前價格（latest_df 只有一行，直接訪問）
                        if len(latest_df) > 0 and close_col in latest_df.columns:
                            curr_price_val = latest_df[close_col].iloc[0]
                            curr_price = pd.to_numeric(curr_price_val, errors='coerce')
                        else:
                            curr_price = 0
                        
                        # 處理 NaN
                        if pd.isna(prev_price):
                            prev_price = 0
                        if pd.isna(curr_price):
                            curr_price = 0
                        
                        if prev_price > 0:
                            price_change = (curr_price - prev_price) / prev_price * 100
                            latest_df.loc[latest_df.index[0], '漲幅%'] = price_change
                        else:
                            latest_df.loc[latest_df.index[0], '漲幅%'] = 0.0
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"計算漲幅%時發生錯誤: {str(e)}, close_col={close_col}")
                        if len(latest_df) > 0:
                            latest_df.loc[latest_df.index[0], '漲幅%'] = 0.0
                        else:
                            latest_df['漲幅%'] = 0.0
                else:
                    latest_df['漲幅%'] = 0.0
            
            # 計算成交量變化率%（如果需要的話，用於篩選）
            # 注意：latest_df 是 DataFrame，應該檢查 columns 而不是 index
            if '成交量變化率%' not in latest_df.columns and '成交股數' in df.columns:
                # ✅ 修復：確保轉換為數值類型
                if len(df) >= 21:
                    latest_volume = pd.to_numeric(df['成交股數'].iloc[-1], errors='coerce')
                    volume_ma20 = pd.to_numeric(df['成交股數'].iloc[-21:-1], errors='coerce').mean()
                    if pd.isna(latest_volume):
                        latest_volume = 0
                    if pd.isna(volume_ma20) or volume_ma20 <= 0:
                        latest_df['成交量變化率%'] = 0.0
                    else:
                        volume_ratio = latest_volume / volume_ma20
                        latest_df['成交量變化率%'] = (volume_ratio - 1) * 100
                elif len(df) >= 2:
                    latest_volume = pd.to_numeric(df['成交股數'].iloc[-1], errors='coerce')
                    volume_ma = pd.to_numeric(df['成交股數'].iloc[:-1], errors='coerce').mean()
                    if pd.isna(latest_volume):
                        latest_volume = 0
                    if pd.isna(volume_ma) or volume_ma <= 0:
                        latest_df['成交量變化率%'] = 0.0
                    else:
                        volume_ratio = latest_volume / volume_ma
                        latest_df['成交量變化率%'] = (volume_ratio - 1) * 100
                else:
                    latest_df['成交量變化率%'] = 0.0
        except Exception as e:
            # 記錄異常但不中斷整個流程
            import logging
            import traceback
            logger = logging.getLogger(__name__)
            logger.debug(f"generate_recommendations 處理異常: {str(e)}")
            logger.debug(f"異常類型: {type(e).__name__}")
            logger.debug(f"堆疊追蹤:\n{traceback.format_exc()}")
            return pd.DataFrame()
        
        if 'filters' in config:
            # 轉換篩選參數格式（從 RecommendationService 格式轉為 screen_stocks 格式）
            filters = config['filters'].copy()
            screen_filters = {}
            
            # 轉換 min_return_pct -> price_change_min
            if 'min_return_pct' in filters:
                screen_filters['price_change_min'] = filters['min_return_pct']
            
            # 轉換 min_volume_ratio -> volume_ratio_min
            # 注意：volume_ratio_min 是比率（如 1.0 = 100%），需要轉換為百分比變化
            if 'min_volume_ratio' in filters:
                # min_volume_ratio = 1.0 表示成交量 >= 100%，即變化率 >= 0%
                # min_volume_ratio = 0.5 表示成交量 >= 50%，即變化率 >= -50%
                min_volume_ratio = filters['min_volume_ratio']
                screen_filters['volume_ratio_min'] = (min_volume_ratio - 1) * 100  # 轉換為百分比變化
            elif 'volume_ratio_min' in filters:
                # 如果直接傳遞 volume_ratio_min（來自 UI），也需要轉換
                # UI 傳遞的是比率（1.0 = 100%），需要轉換為百分比變化（0%）
                volume_ratio = filters['volume_ratio_min']
                # 判斷是否已經是百分比變化（通常 > 10 或 < -50 表示是百分比變化）
                # 否則假設是比率，需要轉換
                if -50 <= volume_ratio <= 10:
                    # 可能是比率，轉換為百分比變化
                    screen_filters['volume_ratio_min'] = (volume_ratio - 1) * 100
                else:
                    # 已經是百分比變化，直接使用
                    screen_filters['volume_ratio_min'] = volume_ratio
            
            # 其他篩選條件直接傳遞
            for key in ['price_change_min', 'price_change_max', 'rsi_min', 'rsi_max', 'market_cap_min', 'market_cap_max']:
                if key in filters:
                    screen_filters[key] = filters[key]
            
            if screen_filters:
                # 記錄篩選前的狀態（用於診斷）
                import logging
                logger = logging.getLogger(__name__)
                before_count = len(latest_df)
                
                # 獲取篩選前的值（使用 iloc[0] 因為 latest_df 只有一行）
                if before_count > 0:
                    row = latest_df.iloc[0]
                    before_score = row.get('TotalScore', row.get('FinalScore', 0))
                    before_price_change = row.get('漲幅%', 'N/A')
                    before_volume_change = row.get('成交量變化率%', 'N/A')
                    
                    # 記錄前3個被過濾的股票（避免日誌過多）
                    stock_code = row.get('證券代號', 'Unknown')
                    
                    # 使用類變數而不是實例變數，確保計數正確
                    if not hasattr(StrategyConfigurator, '_filter_log_count'):
                        StrategyConfigurator._filter_log_count = 0
                    
                    # 檢查欄位是否存在
                    has_price_change = '漲幅%' in latest_df.columns
                    has_volume_change = '成交量變化率%' in latest_df.columns
                    
                    latest_df = self.screen_stocks(latest_df, screen_filters)
                    
                    after_count = len(latest_df)
                    if before_count > 0 and after_count == 0:
                        StrategyConfigurator._filter_log_count += 1
                        if StrategyConfigurator._filter_log_count <= 5:
                            logger.warning(
                                f"[篩選診斷 #{StrategyConfigurator._filter_log_count}] 股票 {stock_code} 被過濾："
                                f"總分={before_score:.2f}, "
                                f"漲幅%={before_price_change} (欄位存在: {has_price_change}), "
                                f"成交量變化率%={before_volume_change} (欄位存在: {has_volume_change}), "
                                f"篩選條件={screen_filters}"
                            )
                else:
                    latest_df = self.screen_stocks(latest_df, screen_filters)
        
        # 5. 重命名分數欄位以保持兼容性
        if 'TotalScore' in latest_df.columns:
            latest_df['綜合評分'] = latest_df['TotalScore']
        
        # 6. 如果通過篩選，返回結果
        if len(latest_df) > 0:
            logger.debug(
                f"[StrategyConfigurator] 返回推薦: "
                f"股票={stock_code}, "
                f"總分={latest_df.iloc[0].get('TotalScore', latest_df.iloc[0].get('FinalScore', 0)):.2f}"
            )
            return latest_df
        else:
            # ✅ 添加調試信息：記錄為什麼返回空
            logger.debug(
                f"[StrategyConfigurator] 返回空結果: "
                f"股票={stock_code}, "
                f"篩選後 latest_df 長度=0"
            )
            return pd.DataFrame()
    
    def _calculate_composite_score(self, df, config):
        """計算綜合評分（已廢棄，改用統一打分模型）
        
        此方法保留以保持向後兼容，實際使用 ScoringEngine.calculate_total_score
        """
        # 如果已經有 TotalScore，直接使用
        if 'TotalScore' in df.columns:
            return df['TotalScore']
        
        # 否則使用舊的計算方式（向後兼容）
        score = pd.Series(0.0, index=df.index)
        
        # 技術指標評分
        if 'technical' in config:
            tech_config = config['technical']
            if tech_config.get('momentum', {}).get('enabled', False):
                # RSI評分（30-70為正常，<30超賣加分，>70超買減分）
                if 'RSI' in df.columns:
                    rsi_score = pd.Series(0.0, index=df.index)
                    rsi_score[df['RSI'] < 30] = 10  # 超賣
                    rsi_score[(df['RSI'] >= 30) & (df['RSI'] <= 70)] = 5  # 正常
                    rsi_score[df['RSI'] > 70] = 0  # 超買
                    score += rsi_score * 0.2
            
            if tech_config.get('momentum', {}).get('macd', {}).get('enabled', False):
                # MACD評分
                if 'MACD' in df.columns and 'MACD_Signal' in df.columns:
                    macd_score = (df['MACD'] > df['MACD_Signal']).astype(int) * 10
                    score += macd_score * 0.2
        
        # 圖形模式評分
        if 'patterns' in config and config['patterns'].get('selected'):
            pattern_score = pd.Series(0.0, index=df.index)
            if 'Pattern_Signal' in df.columns:
                pattern_score[df['Pattern_Signal'] > 0] = 10
                pattern_score[df['Pattern_Signal'] < 0] = -5
            score += pattern_score * 0.3
        
        # 成交量評分
        if '成交量變化率%' in df.columns:
            volume_score = df['成交量變化率%'].clip(0, 50) / 50 * 10
            score += volume_score * 0.2
        
        # 漲幅評分
        if '漲幅%' in df.columns:
            change_score = df['漲幅%'].clip(0, 20) / 20 * 10
            score += change_score * 0.3
        
        return score

