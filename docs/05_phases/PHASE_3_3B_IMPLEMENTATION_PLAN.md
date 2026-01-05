# Phase 3.3b 架構層級實施規劃

**版本**：v1.2.0  
**狀態**：Implementation In Progress  
**最後更新**：2025-12-30

**進度更新**：
- ✅ Epic 2 MVP-1（Warmup Days + Baseline 對比）已完成（2025-12-30）
  - 驗證狀態：29/29 測試案例通過（100% 通過率）
  - 驗證報告：`output/qa/epic2_mvp1_validation/VALIDATION_REPORT.md`
  - 驗證腳本：`scripts/qa_validate_epic2_mvp1.py`
- 🚧 Epic 2 MVP-2（過擬合風險提示）實作中（2025-12-30）
  - 架構設計文檔：`EPIC2_MVP2_ARCHITECTURE_DESIGN.md`（同目錄）
  - 實作檢查清單：`EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md`（同目錄）
  - 實作進度：
    - ✅ 階段 1：核心計算方法實作（已完成）
      - `calculate_walkforward_degradation()` 方法
      - `calculate_consistency()` 方法
      - `calculate_overfitting_risk()` 整合方法
    - ✅ 階段 2：DTO 與服務整合（已完成）
      - `BacktestReportDTO` 新增 `overfitting_risk` 欄位
      - `BacktestService.run_backtest()` 整合過擬合風險計算
    - ⏸️ 階段 3：測試與驗證（待實作）
  - 狀態：實作中 → 待測試驗證
- ⏸️ Epic 3（視覺驗證）待開始
- ⏸️ Epic 1（Promote 機制）待開始

---

## 概述

本文檔提供 Phase 3.3b 三個 Implementation Epic 的架構層級實施規劃，重點在於：
- Epic 實施順序建議
- 各 Epic 的架構影響分析
- MVP 版本建議
- 風險隔離策略
- 潛在架構風險識別

---

## 建議實施順序

### 順序：Epic 2 → Epic 3 → Epic 1

**理由**：

1. **Epic 2（回測穩健性驗證）優先**
   - **前置依賴**：Epic 1（Promote 機制）需要 Walk-Forward 和 Baseline 對比結果作為升級條件
   - **風險最低**：主要是擴充現有服務，不涉及新模組
   - **價值獨立**：即使不做 Promote，穩健性驗證本身就有價值
   - **技術基礎**：`WalkForwardService` 已存在，只需擴充功能

2. **Epic 3（視覺驗證）其次**
   - **獨立性高**：不依賴其他 Epic，可獨立開發與測試
   - **用戶價值**：提供即時反饋，提升使用者體驗
   - **技術基礎**：`EquityCurveWidget` 已存在，只需擴展為 K 線圖
   - **風險可控**：UI 層變更，不影響核心業務邏輯

3. **Epic 1（Promote 機制）最後**
   - **依賴前兩者**：需要 Walk-Forward 和 Baseline 對比結果（Epic 2）
   - **複雜度最高**：涉及版本管理、Profile 整合、資料遷移
   - **可先做 MVP**：先實作「保存為 Preset」功能，降低風險

---

## 各 Epic 的架構影響摘要

### Epic 2：回測穩健性驗證

#### 架構影響：**低**（僅擴充既有模組）

**需要修改的模組**：
1. **`app_module/walkforward_service.py`**（擴充）
   - 新增 `warmup_days` 參數
   - 修改訓練期計算邏輯（從「開始日期 + 暖機期」開始）
   - 在 `WalkForwardResult` 中新增暖機期資訊

2. **`backtest_module/performance_metrics.py`**（擴充）
   - 新增 Baseline 策略計算方法（Buy & Hold、Random Entry）
   - 新增統計顯著性檢驗方法（t-test）

3. **`app_module/backtest_service.py`**（擴充）
   - 在 `BacktestReportDTO` 中新增 Baseline 對比欄位
   - 在回測報告生成時計算 Baseline 對比

4. **`app_module/dtos.py`**（擴充）
   - 在 `BacktestReportDTO` 中新增：
     - `baseline_comparison: Dict[str, Any]`（Baseline 對比結果）
     - `overfitting_risk: Dict[str, Any]`（過擬合風險指標）

**不需要新增的模組**：
- ✅ 所有功能都可以在現有模組中擴充
- ✅ 不需要新建服務或儲存庫

**依賴關係**：
```
WalkForwardService → BacktestService → PerformanceAnalyzer
（現有依賴，無新增）
```

**MVP 版本建議**：
- **階段 1**：Walk-Forward 暖機期（1-2 天）
- **階段 2**：Baseline 對比（Buy & Hold 即可，2-3 天）
- **階段 3**：過擬合風險提示（可延後，2-3 天）

---

### Epic 3：視覺驗證（K 線標記）

#### 架構影響：**低**（僅擴充 UI 層）

**需要修改的模組**：
1. **`ui_qt/widgets/chart_widget.py`**（擴充）
   - 新增 `CandlestickWidget` 類（基於 `EquityCurveWidget`）
   - 實作 K 線圖繪製（使用 `mplfinance` 或 `matplotlib`）
   - 實作買賣點標記（綠色向上箭頭、紅色向下箭頭）
   - 實作 hover tooltip 顯示理由標籤

2. **`ui_qt/views/backtest_view.py`**（擴充）
   - 新增 K 線圖 Tab 或切換按鈕
   - 整合 `CandlestickWidget` 到回測視圖
   - 從 `DailySignalFrame` 提取買賣點與理由標籤

3. **`app_module/chart_data_service.py`**（擴充，如果需要的話）
   - 新增方法：`get_candlestick_data(run_id)` 返回 OHLC 數據
   - 新增方法：`get_trade_signals_with_reasons(run_id)` 返回買賣點與理由

**不需要新增的模組**：
- ✅ 所有功能都可以在現有 UI 組件中擴充
- ✅ 不需要修改業務邏輯層

**依賴關係**：
```
BacktestView → CandlestickWidget → ChartDataService → BacktestRunRepository
（現有依賴，無新增）
```

**MVP 版本建議**：
- **階段 1**：基本 K 線圖顯示（使用 `mplfinance`，1-2 天）
- **階段 2**：買賣點標記（2 天）
- **階段 3**：理由標籤 hover tooltip（1 天）
- **可延後**：技術指標疊加（MA、RSI 等）

---

### Epic 1：Promote 機制

#### 架構影響：**中高**（需要新增服務，但可先做 MVP）

**需要新增的模組**：
1. **`app_module/promotion_service.py`**（新建）
   - 職責：管理回測結果升級為策略版本的流程
   - 方法：
     - `check_promotion_criteria(run_id) -> Dict[str, Any]`（檢查升級條件）
     - `promote_to_strategy_version(run_id, profile_id=None) -> str`（執行升級）
     - `list_promoted_versions() -> List[Dict]`（列出已升級的版本）

2. **`app_module/strategy_version_service.py`**（新建，可選）
   - 職責：管理策略版本的生命週期
   - 方法：
     - `create_version(strategy_id, params, config, backtest_summary) -> str`
     - `get_version(version_id) -> StrategyVersion`
     - `list_versions(strategy_id) -> List[StrategyVersion]`
   - **注意**：如果複雜度過高，可先使用 `PresetService` 作為 MVP

**需要修改的模組**：
1. **`app_module/preset_service.py`**（擴充，MVP 方案）
   - 新增方法：`save_from_backtest_run(run_id, name) -> str`
   - 在 `StrategyPreset` 中新增欄位：`source_run_id`, `validation_metrics`

2. **`app_module/recommendation_service.py`**（擴充）
   - 修改策略載入邏輯，支援從 `PresetService` 或 `StrategyVersionService` 載入
   - 新增方法：`load_strategy_version(version_id) -> StrategySpec`

3. **`app_module/backtest_repository.py`**（擴充）
   - 在 `BacktestRun` 中新增欄位：`promoted_version_id: Optional[str]`
   - 新增方法：`mark_as_promoted(run_id, version_id)`

**依賴關係**：
```
PromotionService → WalkForwardService (Epic 2)
                 → BacktestService
                 → PresetService (MVP) / StrategyVersionService (完整版)
                 → RecommendationService
```

**MVP 版本建議**：
- **階段 1**：簡化版 Promote（保存為 Preset，3-4 天）
  - 使用現有 `PresetService`
  - 不實作完整的版本管理
  - 升級條件檢查：僅檢查 Walk-Forward 和 Baseline 對比（需 Epic 2 完成）
- **階段 2**：完整版 Promote（策略版本管理，5-7 天）
  - 新建 `StrategyVersionService`
  - 實作版本號生成、Profile 整合
  - 實作版本查詢與載入

---

## 必須先做的前置條件

### Epic 1（Promote 機制）的前置條件

1. **Epic 2 必須完成**：
   - Walk-Forward 暖機期功能（用於升級條件檢查）
   - Baseline 對比功能（用於升級條件檢查）
   - 過擬合風險提示（用於風險評估）

2. **資料結構準備**：
   - `BacktestRun` 需要包含完整的策略配置（`strategy_spec`）
   - `BacktestRun` 需要包含 Walk-Forward 結果（如果有的話）

### Epic 2（回測穩健性驗證）的前置條件

**無特殊前置條件**：
- ✅ `WalkForwardService` 已存在
- ✅ `BacktestService` 已存在
- ✅ `PerformanceAnalyzer` 已存在
- ✅ 可以直接開始實作

### Epic 3（視覺驗證）的前置條件

**無特殊前置條件**：
- ✅ `EquityCurveWidget` 已存在
- ✅ `BacktestRunRepository` 已存在
- ✅ `DailySignalFrame` 已包含 `reason_tags`
- ✅ 可以直接開始實作

---

## 可延後處理的項目

### Epic 1（Promote 機制）

**可延後項目**：
1. **完整版策略版本管理**：
   - 版本號自動生成（semantic versioning）
   - 版本依賴關係管理
   - 版本回滾機制
   - **建議**：先做 MVP（保存為 Preset），後續再升級

2. **Profile 自動整合**：
   - 自動推斷適用 Regime
   - 自動掛載到 Profile
   - **建議**：先手動選擇 Profile，後續再自動化

3. **版本比較功能**：
   - 比較不同版本的績效
   - 版本演進歷史
   - **建議**：Phase 4 或後續版本

### Epic 2（回測穩健性驗證）

**可延後項目**：
1. **過擬合風險提示**：
   - ✅ 風險指標計算（參數敏感性、退化程度等）- **已完成核心實作**（2025-12-30）
   - ✅ 風險提示等級判斷 - **已完成**（2025-12-30）
   - ⏸️ 參數敏感性計算（需要最佳化結果）- **可延後**
   - **狀態**：核心功能已完成，參數敏感性計算可延後

2. **多種 Baseline 策略**：
   - Random Entry 策略（可選）
   - Simple Moving Average Crossover（可選）
   - **建議**：先做 Buy & Hold，其他可延後

3. **可調整的暖機期長度**：
   - 目前使用固定 20 個交易日
   - **建議**：先固定，後續再實作可調整

### Epic 3（視覺驗證）

**可延後項目**：
1. **技術指標疊加**：
   - MA、RSI、MACD 等指標顯示在 K 線圖上
   - **建議**：先做基本 K 線圖和買賣點標記，指標疊加可延後

2. **互動功能優化**：
   - 縮放、平移功能
   - 多時間週期切換
   - **建議**：先做基本顯示，互動功能可延後

---

## 需要特別隔離的部分

### Feature Flag 建議

1. **Promote 機制 Feature Flag**：
   ```python
   # app_module/config.py 或環境變數
   ENABLE_PROMOTE_MECHANISM = True  # 預設開啟，但可關閉
   ```
   - **用途**：如果 Promote 功能有問題，可以快速關閉
   - **影響範圍**：`PromotionService`、`BacktestView` 的 Promote 按鈕

2. **K 線圖 Feature Flag**：
   ```python
   ENABLE_CANDLESTICK_CHART = True  # 預設開啟
   ```
   - **用途**：如果 K 線圖渲染有性能問題，可以切換回權益曲線
   - **影響範圍**：`BacktestView` 的圖表切換

### Adapter 模式建議

1. **Baseline 策略 Adapter**：
   ```python
   # backtest_module/baseline_strategies.py
   class BaselineStrategyAdapter:
       """Baseline 策略適配器，統一介面"""
       def calculate(self, data, start_date, end_date) -> Dict[str, float]:
           # 統一返回績效指標
   ```
   - **用途**：未來新增 Baseline 策略時，不需要修改 `BacktestService`
   - **好處**：符合開閉原則，易於擴展

2. **策略版本載入 Adapter**：
   ```python
   # app_module/strategy_loader_adapter.py
   class StrategyLoaderAdapter:
       """策略載入適配器，統一從 Preset 或 Version 載入"""
       def load(self, source: str, source_id: str) -> StrategySpec:
           # source: 'preset' | 'version'
   ```
   - **用途**：MVP 使用 Preset，完整版使用 Version，但 `RecommendationService` 不需要知道差異
   - **好處**：平滑過渡，降低重構風險

---

## 潛在架構風險與反向依賴風險

### 風險 1：Promote 機制與 PresetService 的耦合

**風險描述**：
- MVP 版本使用 `PresetService` 作為儲存，但 `PresetService` 的資料結構可能不適合策略版本管理
- 未來升級到 `StrategyVersionService` 時，可能需要資料遷移

**緩解措施**：
1. **使用 Adapter 模式**（見上）
2. **在 `PresetService` 中預留擴展欄位**：
   ```python
   @dataclass
   class StrategyPreset:
       # ... 現有欄位
       source_run_id: Optional[str] = None  # 預留
       validation_metrics: Optional[Dict] = None  # 預留
   ```
3. **明確標註 MVP 與完整版的差異**：在文檔中說明哪些功能是 MVP，哪些是完整版

### 風險 2：Walk-Forward 暖機期與現有邏輯的衝突

**風險描述**：
- 現有 `WalkForwardService` 可能沒有考慮暖機期，直接修改可能影響現有功能

**緩解措施**：
1. **向後兼容**：新增 `warmup_days` 參數，預設為 0（不影響現有調用）
2. **單元測試**：確保修改後，不帶暖機期的 Walk-Forward 結果與修改前一致
3. **Feature Flag**：可以關閉暖機期功能（雖然不建議，但作為安全網）

### 風險 3：K 線圖性能問題

**風險描述**：
- 大量 K 線數據（如 1000+ 根）可能導致渲染緩慢
- `mplfinance` 或 `matplotlib` 可能不適合即時互動

**緩解措施**：
1. **限制顯示數量**：預設只顯示最近 200 根 K 線
2. **使用 Adapter**：如果性能問題嚴重，可以切換到其他圖表庫（如 PyQtGraph）
3. **異步渲染**：在背景線程渲染圖表，避免阻塞 UI

### 風險 4：Baseline 對比計算的準確性

**風險描述**：
- Buy & Hold 的計算邏輯可能與實際市場有差異（如除權除息）
- 統計顯著性檢驗的計算可能不準確

**緩解措施**：
1. **單元測試**：使用已知數據驗證 Baseline 計算結果
2. **文檔說明**：明確說明 Baseline 計算的假設與限制
3. **可選功能**：如果計算不準確，可以標註為「實驗性功能」

### 風險 5：Promote 機制與 RecommendationService 的循環依賴

**風險描述**：
- `PromotionService` 需要 `RecommendationService` 來驗證升級後的策略版本
- `RecommendationService` 需要 `PromotionService` 來載入策略版本
- 可能形成循環依賴

**緩解措施**：
1. **依賴注入**：`PromotionService` 不直接依賴 `RecommendationService`，而是依賴 `StrategyLoaderAdapter`
2. **事件驅動**：使用事件機制，`PromotionService` 發布「策略版本已升級」事件，`RecommendationService` 訂閱事件
3. **明確依賴方向**：`PromotionService` → `StrategyLoaderAdapter` → `RecommendationService`（單向依賴）

---

## 實施檢查清單

### Epic 2（回測穩健性驗證）

#### MVP-1：Warmup Days + Baseline 對比（✅ 已完成 - 2025-12-30）

- [x] 修改 `WalkForwardService`，新增暖機期參數（`warmup_days`，預設 0，向後兼容）
- [x] 修改 `WalkForwardResult`，新增 `warmup_days` 欄位
- [x] 修改訓練期計算邏輯：從「開始日期 + warmup_days」開始計算
- [x] 修改 `PerformanceAnalyzer`，新增 `calculate_buy_hold_return()` 方法
- [x] 修改 `PerformanceAnalyzer`，新增 `calculate_baseline_comparison()` 方法
- [x] 修改 `BacktestService`，在報告生成時計算 Baseline 對比
- [x] 修改 `BacktestReportDTO`，新增 `baseline_comparison` 欄位
- [x] 更新 `BacktestReportDTO.to_dict()`，包含 Baseline 對比結果
- [x] 向後兼容：所有參數預設值為 0，現有程式碼行為不變
- [x] 功能驗證：29/29 測試案例通過（100% 通過率）
- [x] 驗證報告：`output/qa/epic2_mvp1_validation/VALIDATION_REPORT.md`
- [x] 驗證腳本：`scripts/qa_validate_epic2_mvp1.py`

#### MVP-2：過擬合風險提示（📋 架構規劃完成 - 2025-12-30）

**規劃狀態**：
- ✅ 架構設計文檔已完成：`EPIC2_MVP2_ARCHITECTURE_DESIGN.md`（同目錄）
- ✅ 實作檢查清單已完成：`EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md`（同目錄）
- 🎯 狀態：規劃完成 → 待實作

**實作檢查清單**：
- [ ] 實作 `calculate_walkforward_degradation()` 方法
- [ ] 實作 `calculate_consistency()` 方法
- [ ] 實作 `calculate_parameter_sensitivity()` 方法（可選，可延後）
- [ ] 實作 `calculate_overfitting_risk()` 整合方法
- [ ] 修改 `BacktestReportDTO`，新增 `overfitting_risk` 欄位
- [ ] 修改 `BacktestService.run_backtest()`，整合過擬合風險計算
- [ ] 單元測試：驗證風險指標計算正確
- [ ] 整合測試：驗證風險提示在回測報告中正確顯示
- [ ] 驗證腳本：`scripts/qa_validate_epic2_mvp2.py`

**詳細步驟**：見 `EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md`（同目錄）

### Epic 3（視覺驗證）

- [ ] 新建 `CandlestickWidget` 類
- [ ] 實作 K 線圖繪製
- [ ] 實作買賣點標記
- [ ] 實作理由標籤 hover tooltip
- [ ] 修改 `BacktestView`，整合 K 線圖
- [ ] 修改 `ChartDataService`，新增 K 線數據提取方法
- [ ] 視覺測試：驗證標記準確性
- [ ] 性能測試：驗證大量數據下的渲染性能

### Epic 1（Promote 機制）

- [ ] 新建 `PromotionService`（或擴充 `PresetService`）
- [ ] 實作升級條件檢查邏輯
- [ ] 實作「保存為 Preset」功能（MVP）
- [ ] 修改 `BacktestRepository`，新增 `promoted_version_id` 欄位
- [ ] 修改 `RecommendationService`，支援從 Preset 載入策略
- [ ] 修改 `BacktestView`，新增 Promote 按鈕
- [ ] 單元測試：驗證升級條件檢查邏輯
- [ ] 整合測試：驗證完整的 Promote 流程
- [ ] 端到端測試：驗證升級後的策略版本在推薦系統中正常使用

---

## 總結

### 建議實施順序

1. **Epic 2（回測穩健性驗證）**：優先實施，風險最低，為 Epic 1 提供前置條件
2. **Epic 3（視覺驗證）**：其次實施，獨立性高，可與 Epic 2 並行開發
3. **Epic 1（Promote 機制）**：最後實施，依賴前兩者，可先做 MVP 版本

### 架構影響總結

- **Epic 2**：低影響，僅擴充既有模組
- **Epic 3**：低影響，僅擴充 UI 層
- **Epic 1**：中高影響，需要新增服務，但可先做 MVP 降低風險

### 風險控制

- 使用 Feature Flag 隔離新功能
- 使用 Adapter 模式降低耦合
- MVP 版本優先，降低複雜度
- 完整的單元測試與整合測試

---

**文檔版本**：v1.0.0  
**最後更新**：2025-01-XX  
**維護者**：架構團隊

