# 文檔索引

> **重要**：以 `DEVELOPMENT_ROADMAP.md` 的 Living Section 為準；若索引內進度文字過期，視為待更新。  
> **Living Section 定義**：見 `DEVELOPMENT_ROADMAP.md` 的「📍 Living Section 定義」段落。

## 📖 核心文檔（必讀）

### 1. [專案導航文件](../PROJECT_NAVIGATION.md) ⭐ **快速查找必讀**
**專案開發者的日常導航手冊**
- 專案一句話定位
- 三層架構導航（UI / Service / Domain）
- 功能導航（我要做 X，要去哪裡看？）
- 高風險核心檔案清單
- **5-10 分鐘快速了解專案結構**

### 2. [專案盤點報告](../PROJECT_INVENTORY.md)
**完整的專案結構盤點**
- 專案結構總覽
- 核心進入點
- 主要功能模組盤點
- 可疑或高風險區域
- 專案狀態總結

### 3. [開發演進地圖](DEVELOPMENT_ROADMAP.md) ⭐ **最重要**
**系統的完整演進計劃，從 Phase 1 到 Phase 4**
- 系統定位和最終藍圖
- 4 個階段的詳細說明
- 當前位置和下一步行動
- **建議先讀這份文檔**

### 4. [當前開發狀態](CURRENT_STATUS.md)
**系統當前狀態的詳細說明**
- Phase 1 完成項目清單
- Phase 2 進行中項目
- 功能清單和技術架構
- 下一步行動計劃

### 5. [開發進度記錄](note.txt)
**詳細的開發日誌**
- 每次更新的詳細記錄
- 功能實作細節
- 問題和解決方案

---

## 🏗️ 架構文檔

### 6. [系統架構文檔](system_architecture.md)
**系統的技術架構說明**
- 模組結構
- 數據流程
- 技術細節

### 7. [數據收集架構](data_collection_architecture.md)
**數據收集系統的架構**
- API 端點
- 數據更新流程
- 數據存儲結構

---

## 📚 功能文檔

### 6. [Phase 2 策略資料庫設計](PHASE2_STRATEGY_LIBRARY.md)
**Phase 2 的詳細設計文檔**
- 預設策略庫設計
- 策略說明格式
- 單一策略回測設計
- 實作計劃

### 6.1. [Phase 2 架構設計](PHASE2_ARCHITECTURE.md)
**Phase 2 的架構設計文檔**
- 策略可插拔規格（StrategySpec + StrategyExecutor）
- 策略執行器介面設計
- 策略註冊機制
- 策略版本管理

### 6.2. [策略設計規格書](STRATEGY_DESIGN_SPECIFICATION.md)
**Baseline Score Threshold Strategy 的完整設計規格**
- 研究假設
- 參數/信號定義（TotalScore、PatternScore、IndicatorScore、VolumeScore）
- 策略邏輯（進場/出場條件、確認機制、冷卻期）
- 回測參數設計
- 風險管理機制

### 7. [數據更新指南](daily_data_update_guide.md)
**如何更新每日數據**
- 批量更新
- 單日更新
- 數據合併
- 故障排除

### 7.1. [如何更新每日數據](HOW_TO_UPDATE_DAILY_DATA.md)
**每日數據更新的快速指南**
- 推薦方法（UI 應用程式）
- 批量更新腳本
- 單日更新腳本
- 常見問題

### 8. [腳本使用說明](scripts_readme.md)
**scripts/ 目錄下的腳本說明**
- 腳本分類
- 執行順序建議
- 使用範例

### 8.1. [Phase 2.5 驗證腳本](../scripts/qa_validate_phase2_5.py)
**Phase 2.5 功能驗證腳本**
- 驗證範圍：Market Watch、Recommendation、Watchlist、Backtest、Strategy 系統
- 執行方式：`python scripts/qa_validate_phase2_5.py`
- 驗證報告：`output/qa/phase2_5_validation/VALIDATION_REPORT.md`
- 執行日誌：`output/qa/phase2_5_validation/RUN_LOG.txt`

### 8.2. [推薦分析 Tab 驗證腳本](../scripts/qa_validate_recommendation_tab.py)
**推薦分析功能驗證腳本**
- 驗證範圍：Recommendation Analysis Tab 的 Service 層、UI ↔ Service Contract、篩選邏輯
- 執行方式：`python scripts/qa_validate_recommendation_tab.py`
- 驗證報告：`output/qa/recommendation_tab/VALIDATION_REPORT.md`
- 執行日誌：`output/qa/recommendation_tab/RUN_LOG.txt`

### 8.3. [數據更新 Tab 驗證腳本](../scripts/qa_validate_update_tab.py)
**數據更新功能驗證腳本**
- 驗證範圍：Data Update Tab 的 Service 層、UI ↔ Service Contract、數據狀態檢查邏輯
- 執行方式：`python scripts/qa_validate_update_tab.py`
- 驗證報告：`output/qa/update_tab/VALIDATION_REPORT.md`
- 執行日誌：`output/qa/update_tab/RUN_LOG.txt`

### 8.4. [Epic 2 MVP-1 驗證腳本](../scripts/qa_validate_epic2_mvp1.py)
**Epic 2 MVP-1 功能驗證腳本（Warmup Days + Baseline 對比）**
- 驗證範圍：Walk-Forward 暖機期、Baseline 對比功能
- 執行方式：`python scripts/qa_validate_epic2_mvp1.py`
- 驗證報告：`output/qa/epic2_mvp1_validation/VALIDATION_REPORT.md`
- 驗證狀態：29/29 測試案例通過（100% 通過率）
- 最後更新：2025-12-30

### 8.5. [Epic 2 MVP-2 驗證腳本](../scripts/qa_validate_epic2_mvp2.py)
**Epic 2 MVP-2 功能驗證腳本（過擬合風險提示）**
- 驗證範圍：過擬合風險指標計算、風險等級判斷、風險警告生成
- 執行方式：`python scripts/qa_validate_epic2_mvp2.py`
- 驗證報告：`output/qa/epic2_mvp2_validation/VALIDATION_REPORT.md`
- 驗證狀態：11/11 測試案例通過（100% 通過率）
- 單元測試：20/20 通過（100% 通過率）
- 最後更新：2026-01-02

### 9. UI 應用程式
**UI 相關文檔**
- **Tkinter UI**：`../ui_app/README.md` - 原有 Tkinter 界面說明
- **Qt UI**：`../ui_qt/README.md` - 新增 PySide6 界面說明（推薦使用）
- **應用服務層**：`../app_module/README.md` - UI 與業務邏輯解耦架構

### 9.1. [UI 功能文檔](UI_FEATURES_DOCUMENTATION.md)
**完整的 UI 功能說明和參數文檔**
- 所有 Tab 的功能說明（含 Phase 3.3b 研究閉環功能）
- 技術指標詳細參數
- 圖形模式詳細參數（含 Phase 2.5 ATR-based 參數）
- 回測參數完整說明（含 Phase 2.5 新參數、Phase 3.3b Walk-forward 暖機期、Baseline 對比、過擬合風險提示）
- Promote 機制說明（Phase 3.3b 新增）
- K 線圖標記買賣點功能（Phase 3.3b 新增）

### 9.2. [使用者指南](USER_GUIDE.md)
**複雜功能的使用教程**
- 推薦分析產業篩選
- 策略參數最佳化
- Walk-forward 驗證
- Phase 2.5 新參數使用指南（執行價格、停損停利模式、部位管理）
- 推薦分析 Tab UI 使用指南（策略傾向引導、系統角色說明、推薦理由解讀）

### 9.3. [策略回測實驗室功能說明](BACKTEST_LAB_FEATURES.md)
**策略回測標籤的完整功能說明**
- 策略預設（Strategy Preset）
- 參數最佳化（Optimization）
- Walk-Forward 驗證
- 批量回測（Batch Backtest）
- 回測報告功能

### 9.4. [評分系統說明](SCORE_EXPLANATION.md)
**buy_score 與 sell_score 的詳細說明**
- TotalScore 計算方式
- 子分數詳細計算（PatternScore、IndicatorScore、VolumeScore）
- 閾值參數說明
- 使用範例

---

## 🔧 技術文檔

### 10. [數據獲取邏輯](DATA_FETCHING_LOGIC.md)
**數據獲取的詳細邏輯**
- API 端點和參數
- 數據提取方法
- 錯誤處理

### 10.1. [數據流程邏輯](DATA_FLOW_LOGIC.md)
**推薦分析數據流程邏輯說明**
- 產業篩選階段
- 股票數據讀取階段
- 技術指標計算階段
- 推薦分析階段
- 數據來源與處理流程

### 10.2. [數據重建指南](DATA_REBUILD_GUIDE.md)
**當 daily_price 數據完整時，如何重建其他數據**
- 數據流程說明
- 重建步驟（合併每日數據、計算技術指標）
- 驗證方法
- 常見問題

### 11. [如何更新每日數據](HOW_TO_UPDATE_DAILY_DATA.md)
**每日數據更新的快速指南**
- 推薦方法
- 使用範例
- 常見問題

---

## 📊 數據文檔

### 12. [產業指數更新說明](INDUSTRY_INDEX_UPDATE_SUMMARY.md)
**產業指數數據的更新說明**
- 更新位置
- API 資訊
- 數據處理邏輯

### 13. [市場指數更新說明](MERGE_AND_MARKET_INDEX_SUMMARY.md)
**市場指數數據的更新說明**
- 更新方法
- 數據格式
- 使用方式

### 13.1. [券商分點資料模組設計](BROKER_BRANCH_DATA_MODULE_DESIGN_V2.md)
**券商分點資料更新模組的設計規格（修正版 v2.0）**
- 設計修正摘要（追蹤對象、欄位命名、目錄結構、Merge 規則）
- CSV 欄位定義
- 目錄結構設計
- 核心方法接口規格
- 整合到 UpdateService 和 UI

### 13.2. [券商分點資料實作總結](BROKER_BRANCH_IMPLEMENTATION_SUMMARY.md)
**券商分點資料更新功能的實作總結**
- 變更清單
- 本地測試方式
- 驗收標準檢查
- 資料結構驗證
- 修復記錄（2025-12-29）

### 13.3. [券商分點資料測試與故障排除指南](BROKER_BRANCH_TESTING_AND_TROUBLESHOOTING.md) ⭐ **測試必讀**
**完整的測試方法和故障排除指南**
- 快速測試方法（單一分點、所有分點、多天測試）
- 常見問題與解決方案（URL 參數、編碼、前導零、ChromeDriver 崩潰等）
- 測試腳本說明
- URL 格式說明
- 資料存儲結構
- Registry 檔案說明
- 已知限制與注意事項
- 驗證清單
- 測試記錄（2025-12-29）
**券商分點資料更新功能的實作總結**
- 變更清單（新增/修改檔案）
- 本地測試方式
- 驗收標準

---

## 🚀 快速參考

### 14. [快速參考](QUICK_REFERENCE.md)
**常用命令和操作的快速參考**

### 15. [快速開始](QUICK_START.md)
**系統的快速開始指南**

### 16. [安裝指南](INSTALL_GUIDE.md)
**系統安裝和環境設置指南**

---

## 📝 開發文檔

### 16.1. [Phase 3.3b 實施規劃](PHASE_3_3B_IMPLEMENTATION_PLAN.md)
**Phase 3.3b 三個 Implementation Epic 的架構層級實施規劃**
- Epic 實施順序建議
- 各 Epic 的架構影響分析
- MVP 版本建議
- 風險隔離策略
- **進度更新**：
  - ✅ Epic 2 MVP-1（Warmup Days + Baseline 對比）已完成
  - ✅ Epic 2 MVP-2（過擬合風險提示）已完成（2026-01-02）
  - ⏸️ Epic 3（視覺驗證）待開始
  - ⏸️ Epic 1（Promote 機制）待開始

### 16.2. [Epic 2 MVP-2 架構設計](EPIC2_MVP2_ARCHITECTURE_DESIGN.md)
**Epic 2 MVP-2（過擬合風險提示）的架構設計文檔**
- 風險指標定義（參數敏感性、退化程度、一致性）
- 資料結構設計（overfitting_risk 欄位結構）
- 整合點分析（需要修改的模組與方法）
- 依賴關係分析
- 風險評估與緩解措施
- 驗證策略
- **狀態**：✅ 已完成（2026-01-02，所有階段完成）

### 16.3. [Epic 2 MVP-2 實作檢查清單](EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md)
**Epic 2 MVP-2（過擬合風險提示）的詳細實作檢查清單**
- 階段 1：核心計算方法實作（✅ 已完成）
- 階段 2：DTO 與服務整合（✅ 已完成）
- 階段 3：測試與驗證（✅ 已完成）
- 每個步驟的驗收標準與測試案例
- **狀態**：✅ 已完成（2026-01-02，所有階段完成）
- **驗證狀態**：單元測試 20/20 通過，驗證腳本 11/11 通過（100% 通過率）

### 17. [當前問題](current_issues.md)
**當前已知問題和解決方案**

### 17.1. [推薦分析 Tab QA 問題](QA_RECOMMENDATION_TAB_ISSUES.md)
**推薦分析 Tab 的 QA 驗證發現的問題**
- 邏輯錯誤、Contract 違規、數據品質問題
- 修復建議和已應用修復

### 17.2. [數據更新 Tab QA 問題](QA_UPDATE_TAB_ISSUES.md)
**數據更新 Tab 的 QA 驗證發現的問題**
- Service 層測試結果
- UI ↔ Service Contract 驗證
- 數據狀態檢查邏輯驗證

### 17.3. [每日股票更新故障排除指南](TROUBLESHOOTING_DAILY_UPDATE.md) ⭐ **故障排除必讀**
**每日股票更新卡住時的完整故障排除指南**
- 快速檢查清單（日誌、數據狀態、進程、網路、權限）
- 常見問題與解決方案（卡住、編碼錯誤、HTTP 307、文件損壞、Worker 線程）
- 進階故障排除（驗證腳本、手動測試、配置檢查）
- 診斷資訊收集指南
- 快速修復檢查表

### 18. [清理總結](CLEANUP_SUMMARY.md)
**專案清理的總結報告**

### 19. [系統流程（端到端）](system_flow_end_to_end.md)
**系統端到端流程說明**

### 20. [Phase 2.5 完成狀態](PHASE2_5_COMPLETION_STATUS.md)
**Phase 2.5 完成狀態檢查報告**
- 優先級 1-4 功能完成狀態
- 實現位置與方式
- 驗證結果
- 最後更新：2025-12-20

### 21. [測試文檔說明](tests_readme.md)
**tests/ 目錄的檔案結構和組織方式**
- 測試檔案結構
- 測試分類說明
- 相關文檔連結
- **完整測試指南**：`docs/readme_test.txt`

---

## 🎯 閱讀順序建議

### 第一次接觸系統
1. [開發演進地圖](DEVELOPMENT_ROADMAP.md) - 了解系統定位和演進計劃
2. [當前開發狀態](CURRENT_STATUS.md) - 了解當前狀態
3. [系統架構文檔](system_architecture.md) - 了解技術架構

### 開始使用系統
1. [快速開始](QUICK_START.md) - 快速上手
2. [數據更新指南](daily_data_update_guide.md) - 更新數據
3. [腳本使用說明](scripts_readme.md) - 使用腳本

### 開發新功能
1. [開發演進地圖](DEVELOPMENT_ROADMAP.md) - 確認功能屬於哪個 Phase
2. [Phase 2 策略資料庫設計](PHASE2_STRATEGY_LIBRARY.md) - 如果是 Phase 2 功能
3. [開發進度記錄](note.txt) - 了解歷史開發過程

---

## 📌 重要提醒

### ✅ 現在該做（Phase 2.5 完成 → Phase 3 準備）
- ✅ 應用服務層（app_module/）- 已完成
- ✅ Qt UI（ui_qt/）- 已完成
- ✅ 預設策略庫設計 - 已完成
- ✅ 策略說明文檔 - 已完成
- ✅ 單一策略回測 - 已完成
- ✅ 參數設計優化（Phase 2.5）- 已完成並驗證通過（18/18 功能通過）
- ✅ 推薦分析 Tab UI 可理解性優化 - 已完成（Phase 3 準備工作）
  - ✅ 說明資料集中管理、策略傾向引導、系統角色說明、推薦結果可反推
- ✅ Epic 2 MVP-1（Warmup Days + Baseline 對比）- 已完成（2025-12-30）
- ✅ Epic 2 MVP-2（過擬合風險提示）- 已完成（2026-01-02）
- 🚧 推薦產品化（Phase 3）
- 🚧 策略驗證（Phase 3）

### ❌ 現在不要急
- ML（機器學習）
- 即時交易
- 太多參數
- 預測未來報酬
- 多策略組合（Phase 3）
- 持倉管理（Phase 4）

---

## 🔄 文檔更新原則

1. **每次重大功能更新**：更新 [開發進度記錄](note.txt)
2. **每次 Phase 轉換**：更新 [開發演進地圖](DEVELOPMENT_ROADMAP.md) 和 [當前開發狀態](CURRENT_STATUS.md)
3. **每次架構變更**：更新 [系統架構文檔](system_architecture.md)
4. **每次新增功能**：更新對應的功能文檔

---

## 📞 相關連結

- [主 README](../README.md) - 專案主頁
- [UI 應用程式說明](../ui_app/README.md) - UI 應用程式詳細說明

