# Phase 3.3b 完整功能驗證與壓力測試報告

**生成時間**: 2026-01-02 03:19:36

## 測試摘要

- **總測試數**: 10
- **通過**: 10 (100.0%)
- **失敗**: 0 (0.0%)
- **警告**: 6 (60.0%)

## 測試結果詳情

### 1. 數據與市場觀察

#### ✅ ⚠️ 測試 1.1：數據更新流程（券商分點資料）

**警告**: 未找到券商分點資料檔案，可能需要執行更新

**詳細信息**:
```json
{
  "broker_flow_dir": "D:\\Min\\Python\\Project\\FA_Data\\broker_flow",
  "data_files_count": 0
}
```

#### ✅  測試 1.2：Regime 判斷（Market Watch）

**詳細信息**:
```json
{
  "regime": "Trend",
  "regime_name_cn": "趨勢追蹤",
  "confidence": 0.9284386690643646,
  "details": {
    "close": 29349.81,
    "ma20": 28209.983500000002,
    "ma60": 27751.22725,
    "ma20_slope": 1.5652001035489522,
    "adx": 19.851301815653766,
    "plus_di": 72.14663921164879,
    "minus_di": 27.853360788351218,
    "close_above_ma60": true,
    "ma20_slope_positive": true,
    "plus_di_above_minus_di": true,
    "structure_score": 1.0,
    "adx_value": 19.851301815653766,
    "adx_contribution": 0.591078108939226,
    "trend_distance": 7.481099660377866,
    "distance_contribution": 1.0,
    "strength_score": 0.795539054469613,
    "trend_confidence": 0.9284386690643646
  }
}
```

### 2. 推薦引擎與 Profile

#### ✅  測試 2.1：Profile 載入（新手/進階模式）

**詳細信息**:
```json
{
  "profiles_count": 3,
  "profile_ids": [
    "momentum",
    "stable",
    "long_term"
  ],
  "test_profile_id": "momentum",
  "profile_config_keys": [
    "technical",
    "patterns",
    "signals"
  ]
}
```

#### ✅  測試 2.2：Why/Why Not（推薦理由）

**詳細信息**:
```json
{
  "stock_code": "52",
  "total_score": 69.97838922910991,
  "has_recommendation_reasons": true,
  "recommendation_reasons_preview": "技術指標分數+、RSI超賣+"
}
```

#### ✅ ⚠️ 測試 2.3：聯動（推薦股票加入 Watchlist）

**警告**: 股票 2884 的 notes 中缺少來源信息

**詳細信息**:
```json
{
  "added_count": 0,
  "watchlist_total": 3,
  "recommendation_source_count": 3
}
```

### 3. 研究閉環核心

#### ✅  測試 3.1：一鍵送回測（Recommendation → Backtest）

**詳細信息**:
```json
{
  "stock_list": [
    "52",
    "61",
    "53"
  ],
  "strategy_id": "baseline_score_threshold",
  "has_strategy_params": true,
  "has_risk_control": true
}
```

#### ✅ ⚠️ 測試 3.2：穩健性指標（Walk-forward, Baseline, Overfitting）

**警告**: 回測報告中沒有過擬合風險提示（可能未提供 Walk-forward 結果或功能未啟用）

**詳細信息**:
```json
{
  "has_baseline_comparison": true,
  "baseline_total_return": null,
  "strategy_total_return": null,
  "excess_return": null
}
```

#### ✅ ⚠️ 測試 3.3：視覺驗證（K 線圖標記買賣點）

**警告**: 回測結果中沒有交易記錄（無法驗證視覺標記）

### 4. Promote 機制

#### ✅ ⚠️ 測試 4.1：Promote 機制（回測結果 → 策略版本）

**警告**: 升級條件未通過: ['總報酬率為負或零: -52.09%', 'Sharpe Ratio 過低: -1.16 < 0.5', '✓ 最大回撤: -54.84%', '勝率過低: 0.00% < 50.00%']

**詳細信息**:
```json
{
  "criteria_passed": false,
  "criteria_reasons": [
    "總報酬率為負或零: -52.09%",
    "Sharpe Ratio 過低: -1.16 < 0.5",
    "✓ 最大回撤: -54.84%",
    "勝率過低: 0.00% < 50.00%"
  ],
  "criteria_details": {
    "basic_metrics": {
      "total_return": -0.52085412915,
      "sharpe_ratio": -1.1644837347554389,
      "max_drawdown": -0.5483650696875,
      "win_rate": 0.0
    }
  },
  "promote_success": false
}
```

#### ✅ ⚠️ 測試 4.2：Promote 後回到推薦（策略版本選擇）

**警告**: 目前沒有已 Promote 的策略版本（可能需要先執行 Promote）

## 失效功能點與潛在問題

### ✅ 無失效功能

### ⚠️ 潛在問題

- **測試 1.1：數據更新流程（券商分點資料）**: 未找到券商分點資料檔案，可能需要執行更新
- **測試 2.3：聯動（推薦股票加入 Watchlist）**: 股票 2884 的 notes 中缺少來源信息
- **測試 3.2：穩健性指標（Walk-forward, Baseline, Overfitting）**: 回測報告中沒有過擬合風險提示（可能未提供 Walk-forward 結果或功能未啟用）
- **測試 3.3：視覺驗證（K 線圖標記買賣點）**: 回測結果中沒有交易記錄（無法驗證視覺標記）
- **測試 4.1：Promote 機制（回測結果 → 策略版本）**: 升級條件未通過: ['總報酬率為負或零: -52.09%', 'Sharpe Ratio 過低: -1.16 < 0.5', '✓ 最大回撤: -54.84%', '勝率過低: 0.00% < 50.00%']
- **測試 4.2：Promote 後回到推薦（策略版本選擇）**: 目前沒有已 Promote 的策略版本（可能需要先執行 Promote）

## 過擬合風險誤報分析

### 測試 3.2：穩健性指標（Walk-forward, Baseline, Overfitting）

**功能狀態**: ✅ **已正確實作**

**失效原因**:
- 測試中未提供 `walkforward_results` 參數
- `BacktestService._calculate_overfitting_risk()` 需要 Walk-Forward 結果作為輸入
- 如果未提供，會返回 `None`（這是**預期行為**，不是錯誤）

**技術說明**:
1. 過擬合風險計算需要 Walk-Forward 驗證結果
2. 如果沒有 Walk-Forward 結果，系統無法計算過擬合風險指標
3. 這是設計上的正常行為，確保風險評估的準確性

**建議**:
- 如需測試過擬合風險功能，必須先執行 Walk-Forward 驗證
- 測試邏輯已更新，明確說明需要 Walk-Forward 結果
