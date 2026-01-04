# 應用服務層 (Application Service Layer)

## 概述

`app_module/` 是應用服務層，提供統一的業務邏輯接口，供各種 UI（Tkinter/Qt/Web/CLI）調用。

## 架構設計原則

### 方案 A：最小重工（當前採用）

- **不搬檔案**：`ui_app/` 中的業務邏輯模組（`stock_screener.py`, `strategy_configurator.py` 等）暫時保留在原位置
- **Service 層包裝**：`app_module/*_service.py` 內部 import `ui_app` 模組
- **未來遷移**：等 Qt UI 穩定後，再將這些模組搬到 `recommendation_module/` 或新建 `decision_module/`

### 優勢

- ✅ 最小改動，不破壞現有功能
- ✅ UI 與邏輯解耦，未來可支持多種 UI
- ✅ 逐步遷移，風險可控

## 目錄結構

```
app_module/
├── __init__.py              # 模組導出
├── dtos.py                  # 數據傳輸對象定義
├── recommendation_service.py # 推薦服務（已完成）
├── screening_service.py     # 強勢股/產業篩選服務（待實現）
├── regime_service.py        # 市場狀態檢測服務（待實現）
├── update_service.py        # 數據更新服務（待實現）
└── backtest_service.py      # 回測服務（待實現）
```

## 已實現服務

### RecommendationService

**功能**：執行股票推薦分析

**主要方法**：
- `run_recommendation(config, max_stocks=200, top_n=50) -> List[RecommendationDTO]`
  - 執行策略分析，返回推薦股票列表
  - 內部調用 `ui_app.strategy_configurator`, `ui_app.reason_engine`, `ui_app.industry_mapper`
  
- `detect_regime() -> Dict[str, Any]`
  - 檢測市場狀態（Trend/Reversion/Breakout）
  - 內部調用 `ui_app.market_regime_detector`
  
- `get_strategy_config_for_regime(regime) -> Dict[str, Any]`
  - 獲取指定市場狀態的策略配置

**使用範例**：
```python
from app_module.recommendation_service import RecommendationService
from data_module.config import TWStockConfig

config = TWStockConfig()
service = RecommendationService(config)

# 執行推薦
recommendations = service.run_recommendation(
    config={
        'technical': {...},
        'patterns': {...},
        'signals': {...},
        'filters': {...},
        'regime': 'Trend'
    },
    max_stocks=200,
    top_n=50
)

# 使用推薦結果
for rec in recommendations:
    print(f"{rec.stock_code}: {rec.total_score}")
```

## 已實現服務（骨架）

### ScreeningService ✅

**功能**：強勢股/產業篩選

**主要方法**：
- `get_strong_stocks(period='day', top_n=20, min_volume=None) -> pd.DataFrame`
- `get_strong_industries(period='day', top_n=20) -> pd.DataFrame`

**內部調用**：`ui_app.stock_screener`

### RegimeService ✅

**功能**：市場狀態檢測

**主要方法**：
- `detect_regime(date=None) -> RegimeResultDTO`
- `get_strategy_config(regime) -> Dict[str, Any]`

**內部調用**：`ui_app.market_regime_detector`

### UpdateService ✅（完整實現）

**功能**：數據更新

**主要方法**：
- `update_daily(start_date, end_date, delay_seconds=4.0) -> Dict[str, Any]`
  - 更新每日股票數據，調用 `scripts/batch_update_daily_data.py`
  - 返回更新結果：成功/失敗日期列表、消息
- `update_market(start_date, end_date) -> Dict[str, Any]`
  - 更新大盤指數數據（待實現）
- `update_industry(start_date, end_date) -> Dict[str, Any]`
  - 更新產業指數數據（待實現）
- `merge_daily_data(force_all=False) -> Dict[str, Any]`
  - 合併每日數據到 `stock_data_whole.csv`
  - `force_all=True`：強制重新合併所有數據（完全重建）
  - `force_all=False`：增量合併，只處理新文件
- `check_data_status() -> Dict[str, Any]`
  - 檢查數據狀態：每日股票數據、大盤指數、產業指數的最新日期

**內部調用**：
- `scripts/batch_update_daily_data.py`：每日數據更新
- `scripts/merge_daily_data.py`：數據合併

### BacktestService ✅（Stub）

**功能**：回測分析

**主要方法**：
- `run_backtest(stock_code, start_date, end_date, capital=1000000.0, strategy_name='default', strategy_config=None) -> BacktestReportDTO`
- `run_multi_stock_backtest(stock_codes, start_date, end_date, capital=1000000.0, strategy_name='default', strategy_config=None) -> Dict[str, BacktestReportDTO]`

**內部調用**：`backtest_module.strategy_tester`, `backtest_module.performance_analyzer`（待實現）

## 數據傳輸對象 (DTOs)

定義在 `dtos.py`：

- `RecommendationDTO`：股票推薦結果
- `RegimeResultDTO`：市場狀態檢測結果
- `BacktestReportDTO`：回測報告（待實現）

## 遷移計劃

### Step 1：✅ 已完成
- [x] 創建 `app_module/` 目錄
- [x] 創建 `dtos.py`
- [x] 創建 `recommendation_service.py`
- [x] 修改 `ui_app/main.py` 使用 `RecommendationService`

### Step 2：✅ 已完成
- [x] 實現 `screening_service.py`（完整實現）
- [x] 實現 `regime_service.py`（完整實現）
- [x] 實現 `update_service.py`（完整實現：數據更新、合併、狀態檢查）
- [x] 實現 `backtest_service.py`（Stub，方法簽名穩定）

### Step 3：未來遷移
- [ ] 將 `ui_app/stock_screener.py` 等模組搬到 `recommendation_module/` 或新建 `decision_module/`
- [ ] 更新所有 import 路徑
- [ ] 移除 `ui_app/` 中的業務邏輯，只保留 UI 代碼

## 注意事項

1. **向後兼容**：`ui_app/main.py` 仍保留原有實例（`self.strategy_configurator` 等），確保現有代碼不中斷
2. **逐步遷移**：不要一次性搬動所有模組，先確保 service 層穩定
3. **測試優先**：每次遷移後都要測試，確保功能正常

