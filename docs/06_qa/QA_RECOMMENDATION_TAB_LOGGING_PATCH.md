# Recommendation Analysis Tab Logging Patch

## 目標
在不改商業邏輯的前提下，補齊關鍵步驟的 logging，便於 QA 驗證和問題診斷。

## Patch 1: RecommendationService.run_recommendation()

**文件**: `app_module/recommendation_service.py`

**位置**: `run_recommendation()` 方法開始處

```python
def run_recommendation(
    self, 
    config: Dict[str, Any],
    max_stocks: int = 200,
    top_n: int = 50
) -> List[RecommendationDTO]:
    """執行推薦分析"""
    import logging
    logger = logging.getLogger(__name__)
    
    # ✅ 添加：記錄輸入參數
    logger.info(
        f"[RecommendationService] 開始推薦分析: "
        f"max_stocks={max_stocks}, top_n={top_n}, "
        f"產業篩選={config.get('filters', {}).get('industry', '全部')}, "
        f"圖形模式={config.get('patterns', {}).get('selected', [])}, "
        f"技術指標={config.get('technical', {})}"
    )
    
    # 讀取股票數據
    stock_data_file = self.config.stock_data_file
    # ... 現有代碼 ...
```

**位置**: 讀取數據後

```python
    # 讀取最新數據（最近60天，確保有足夠數據計算技術指標）
    df = pd.read_csv(
        stock_data_file, 
        encoding='utf-8-sig', 
        on_bad_lines='skip', 
        engine='python', 
        nrows=500000
    )
    df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
    df = df[df['日期'].notna()]
    
    # ✅ 添加：記錄數據讀取結果
    logger.info(
        f"[RecommendationService] 數據讀取完成: "
        f"總筆數={len(df)}, "
        f"股票數={df[stock_col].nunique() if stock_col in df.columns else 0}, "
        f"日期範圍={df['日期'].min()} ~ {df['日期'].max()}"
    )
    
    # ... 現有代碼 ...
```

**位置**: 產業篩選後

```python
    if industry_filter and industry_filter != '全部':
        # ... 現有代碼 ...
        
        # ✅ 添加：記錄產業篩選結果
        logger.info(
            f"[RecommendationService] 產業篩選完成: "
            f"產業={industry_filter}, "
            f"篩選前股票數={len(all_stocks)}, "
            f"篩選後股票數={len(stocks)}"
        )
```

**位置**: 處理循環開始前

```python
    # 對每支股票執行策略分析
    all_recommendations = []
    
    # ✅ 添加：記錄處理開始
    logger.info(
        f"[RecommendationService] 開始處理 {len(stocks)} 支股票"
    )
    
    # ... 現有代碼 ...
```

**位置**: 處理循環結束後

```python
        # 如果沒有找到任何推薦，提供調試信息
        if len(all_recommendations) == 0 and stats['total_stocks'] > 0:
            # ... 現有代碼 ...
        
        # ✅ 添加：記錄處理結果摘要
        logger.info(
            f"[RecommendationService] 推薦分析完成: "
            f"總股票數={stats['total_stocks']}, "
            f"已處理={stats['processed']}, "
            f"成功={stats['success']}, "
            f"返回推薦數={len(all_recommendations)}"
        )
        
        # 按總分降序排序，返回前 top_n 名
        all_recommendations.sort(key=lambda x: x.total_score, reverse=True)
        return all_recommendations[:top_n]
```

---

## Patch 2: StrategyConfigurator.generate_recommendations()

**文件**: `ui_app/strategy_configurator.py`

**位置**: 方法開始處

```python
def generate_recommendations(self, df, config):
    """生成股票推薦（使用統一打分模型）"""
    import logging
    logger = logging.getLogger(__name__)
    
    if len(df) == 0:
        return pd.DataFrame()
    
    # ✅ 添加：記錄輸入
    stock_code = df.iloc[-1].get('證券代號', 'Unknown') if len(df) > 0 else 'Unknown'
    logger.debug(
        f"[StrategyConfigurator] 生成推薦: "
        f"股票={stock_code}, "
        f"數據筆數={len(df)}, "
        f"圖形模式={config.get('patterns', {}).get('selected', [])}"
    )
    
    # ... 現有代碼 ...
```

**位置**: 技術指標計算後

```python
    # 1. 配置技術指標
    df = self.configure_technical_indicators(df, config.get('technical', {}))
    
    # ✅ 添加：記錄技術指標計算結果
    indicator_cols = [col for col in df.columns if col in ['RSI', 'MACD', 'MACD_signal', 'MACD_hist', 
                                                           'ADX', 'MA5', 'MA10', 'MA20', 'MA60', 'ATR']]
    logger.debug(
        f"[StrategyConfigurator] 技術指標計算完成: "
        f"指標欄位數={len(indicator_cols)}, "
        f"NaN比例={df[indicator_cols].isna().sum().sum() / (len(df) * len(indicator_cols)) if indicator_cols else 0:.2%}"
    )
```

**位置**: 分數計算後

```python
    # 3. 使用統一打分模型計算總分（含 Regime Match Factor）
    regime = config.get('regime', None)
    df = self.scoring_engine.calculate_total_score(df, config, regime=regime)
    
    # ✅ 添加：記錄分數計算結果
    if len(df) > 0:
        latest_row = df.iloc[-1]
        logger.debug(
            f"[StrategyConfigurator] 分數計算完成: "
            f"總分={latest_row.get('TotalScore', latest_row.get('FinalScore', 0)):.2f}, "
            f"指標分={latest_row.get('IndicatorScore', 0):.2f}, "
            f"圖形分={latest_row.get('PatternScore', 0):.2f}, "
            f"成交量分={latest_row.get('VolumeScore', 0):.2f}"
        )
```

**位置**: 篩選後

```python
            if screen_filters:
                # ... 現有代碼 ...
                
                latest_df = self.screen_stocks(latest_df, screen_filters)
                
                # ✅ 添加：記錄篩選結果
                after_count = len(latest_df)
                if before_count > 0 and after_count == 0:
                    logger.debug(
                        f"[StrategyConfigurator] 股票被篩選過濾: "
                        f"股票={stock_code}, "
                        f"篩選條件={screen_filters}"
                    )
```

---

## Patch 3: StrategyConfigurator.screen_stocks()

**文件**: `ui_app/strategy_configurator.py`

**位置**: 方法開始處

```python
def screen_stocks(self, df, filters):
    """篩選股票"""
    import logging
    logger = logging.getLogger(__name__)
    
    df_result = df.copy()
    original_count = len(df_result)
    
    # ✅ 添加：記錄篩選開始
    logger.debug(
        f"[screen_stocks] 開始篩選: "
        f"原始筆數={original_count}, "
        f"篩選條件={filters}"
    )
    
    # ... 現有代碼 ...
```

**位置**: 每個篩選步驟後

```python
    # 漲幅篩選
    if 'price_change_min' in filters or 'price_change_max' in filters:
        if '漲幅%' in df_result.columns:
            before = len(df_result)
            if 'price_change_min' in filters:
                df_result = df_result[df_result['漲幅%'] >= filters['price_change_min']]
            if 'price_change_max' in filters:
                df_result = df_result[df_result['漲幅%'] <= filters['price_change_max']]
            after = len(df_result)
            
            # ✅ 添加：記錄篩選結果
            logger.debug(
                f"[screen_stocks] 漲幅篩選: {before} -> {after} "
                f"(條件: {filters.get('price_change_min', 'N/A')} ~ {filters.get('price_change_max', 'N/A')})"
            )
```

```python
    # 成交量比率篩選
    if 'volume_ratio_min' in filters:
        if '成交量變化率%' in df_result.columns:
            before = len(df_result)
            df_result = df_result[
                df_result['成交量變化率%'] >= filters['volume_ratio_min']
            ]
            after = len(df_result)
            
            # ✅ 添加：記錄篩選結果
            logger.debug(
                f"[screen_stocks] 成交量篩選: {before} -> {after} "
                f"(條件: >= {filters['volume_ratio_min']:.2f}%)"
            )
```

**位置**: 方法結束前

```python
    # ✅ 添加：記錄最終結果
    logger.debug(
        f"[screen_stocks] 篩選完成: "
        f"{original_count} -> {len(df_result)} "
        f"(過濾 {original_count - len(df_result)} 筆)"
    )
    
    return df_result
```

---

## 使用說明

1. **日誌級別**: 
   - `INFO`: Service 入口、關鍵步驟、結果摘要
   - `DEBUG`: 詳細的處理過程、中間結果

2. **日誌格式**: 
   - 使用 `[模組名]` 前綴，便於過濾
   - 包含關鍵參數和統計信息

3. **性能影響**: 
   - DEBUG 日誌在生產環境可關閉
   - INFO 日誌開銷很小

4. **驗證方式**: 
   - 運行 QA 腳本時，檢查日誌文件
   - 確認關鍵步驟都有日誌記錄

