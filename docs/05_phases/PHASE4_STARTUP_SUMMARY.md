# Phase 4 啟動總結

## 概述

Phase 4 的最小可用骨架已建立，提供 **Read-only / Decision-support** 的 Position/Portfolio Layer，用於觀察、理解與管理既有策略/股票的部位狀態。

**啟動日期**：2026-01-07  
**狀態**：骨架已建立，待實作 UI 層

---

## 已建立的骨架

### 1. 設計文檔

**`PHASE4_PORTFOLIO_DESIGN.md`**
- Phase 4 的完整設計規格
- Position 和 Portfolio 的資料結構定義
- 與 Phase 3 的關聯說明
- 實作順序建議

### 2. 資料結構（DTO）

**`app_module/position_dtos.py`**
- `PositionDTO`：單一持倉的資料結構
- `PortfolioDTO`：投資組合總覽的資料結構

**關鍵欄位**：
- 進場來源追溯（entry_source_type, entry_source_id）
- 進場快照（entry_snapshot）
- 當前狀態對照（current_regime, current_total_score）
- 條件監控狀態（condition_status, condition_details）

### 3. 服務層骨架

**`app_module/position_service.py`**
- `PositionService`：管理 Position 的 CRUD 操作
- 主要方法：
  - `create_position()`：建立新持倉
  - `get_position()`：取得持倉資訊
  - `list_positions()`：列出所有持倉
  - `update_position_status()`：更新當前狀態
  - `check_condition()`：檢查條件狀態
  - `close_position()`：平倉

**`app_module/portfolio_service.py`**
- `PortfolioService`：管理 Portfolio 總覽
- 主要方法：
  - `get_portfolio()`：取得投資組合總覽
  - `update_portfolio()`：更新投資組合資訊
  - `get_benchmark_comparison()`：取得 Benchmark 對比（待實作）

---

## 資料儲存結構

### Position 儲存

**位置**：`{output_root}/portfolio/positions/{position_id}.json`

**格式**：JSON 檔案（每個 Position 一個檔案）

### Portfolio 儲存

**位置**：`{output_root}/portfolio/portfolio.json`

**格式**：單一 JSON 檔案（包含總覽資訊）

---

## 與 Phase 3 的關聯

### 進場來源追溯

每個 Position 必須可追溯回 Phase 3 的產出：

1. **從推薦進場**：
   - `entry_source_type = 'recommendation'`
   - `entry_source_id = recommendation_result_id`
   - `entry_snapshot` 包含完整的 `RecommendationResultDTO`

2. **從回測進場**：
   - `entry_source_type = 'backtest'`
   - `entry_source_id = backtest_run_id`
   - `entry_snapshot` 包含完整的 `BacktestRun`

3. **從策略版本進場**：
   - `entry_source_type = 'strategy_version'`
   - `entry_source_id = strategy_version_id`
   - `entry_snapshot` 包含完整的 `StrategyVersion`

### 條件監控

系統會自動監控以下條件變化：

1. **Regime 變化**：進場時的 Regime vs 當前 Regime
2. **TotalScore 下降**：進場時的 TotalScore vs 當前 TotalScore
3. **價格變化**：進場價格 vs 當前價格

**條件狀態**：
- `valid`：仍符合進場條件
- `warning`：部分條件改變，需要關注
- `invalid`：明顯不符合進場條件

---

## 下一步實作

### 階段 1：基本 CRUD 功能驗證（1-2 天）

1. 測試 `create_position`（從 Phase 3 建立持倉）
2. 測試 `get_position` 和 `list_positions`
3. 測試 `update_position_status`（更新當前狀態）

### 階段 2：條件監控實作（2-3 天）

1. 實作 `check_condition`（檢查條件變化）
2. 整合 `RegimeService` 獲取當前 Regime
3. 整合 `RecommendationService` 獲取當前 TotalScore
4. 實作條件狀態判斷邏輯

### 階段 3：UI 骨架（2-3 天）

1. 建立 `PortfolioView` 基本結構
2. 實作持倉列表顯示
3. 實作持倉詳細資訊顯示
4. 添加「此為資訊呈現，不作為交易建議」標示

### 階段 4：與 Phase 3 整合（1-2 天）

1. 在 `RecommendationView` 添加「建立持倉」按鈕
2. 在 `BacktestView` 添加「建立持倉」按鈕
3. 確保可以追溯回 Phase 3 的原始產出

---

## 成功標準（DoD）

### 使用者可以一眼回答：

1. ✅ **我現在有哪些部位？從哪來？**
   - 可以在 Portfolio 視圖看到所有持倉列表
   - 每個持倉都標示進場來源
   - 可以點擊查看進場時的完整 Snapshot

2. ✅ **這些部位是否已經「不符合當初進場假設」？**
   - 可以看到條件監控狀態（valid / warning / invalid）
   - 可以看到進場時 vs 當前狀態的對照
   - 可以看到條件變化的詳細資訊

3. ✅ **如果要調整，我該回到 Phase 3 哪一層重新研究？**
   - 可以從 Position 追溯到 Phase 3 的原始產出
   - 可以清楚看到問題出在哪一層
   - 可以回到 Phase 3 對應的 Tab 重新研究

### 不引入任何自動化風險

- ✅ 系統不執行任何自動操作
- ✅ 所有數值僅供參考
- ✅ UI 明確標示「此為資訊呈現，不作為交易建議」

---

## 注意事項

### 資料一致性

- Position 的 `entry_snapshot` 必須保存完整的 Snapshot
- 即使 Phase 3 的原始資料變更，Position 仍能查看進場時的狀態

### 性能考量

- `update_position_status` 可能需要批量更新多個 Position
- 考慮使用 Worker 線程進行非同步更新

### 向後兼容

- Phase 4 不影響 Phase 3 的任何功能
- Phase 3 的研究閉環完全獨立運作

---

## 相關文檔

- [Phase 4 設計規格](PHASE4_PORTFOLIO_DESIGN.md) - 完整的設計文檔
- [Phase 4 進入條件](phase3_5_research/PHASE4_ENTRY_CRITERIA.md) - 進入 Phase 4 的前置條件
- [開發路線圖](../00_core/DEVELOPMENT_ROADMAP.md) - Phase 4 的整體規劃

---

**文檔版本**：v1.0  
**最後更新**：2026-01-07  
**狀態**：骨架已建立，待實作 UI 層

