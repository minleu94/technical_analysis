# Docs 資料夾重新整理建議

**生成日期**：2026-01-03  
**目的**：提出清晰的文檔組織結構，解決當前文檔混亂的問題

---

## 📊 當前問題分析

### 問題 1：所有文件都在根目錄
- **現狀**：68 個文件（66 個 .md + 2 個 .txt）全部在 `docs/` 根目錄
- **問題**：無法快速找到需要的文檔，缺乏分類

### 問題 2：相關文檔分散
- **QA 文檔**：`QA_RECOMMENDATION_TAB_*`（7 個）、`QA_UPDATE_TAB_*`（2 個）分散在根目錄
- **Phase 文檔**：`PHASE2_*`、`PHASE_3_3B_*`、`PHASE3_3B_*` 分散在根目錄
- **Broker Branch 文檔**：`BROKER_BRANCH_*`（6 個）分散在根目錄
- **數據文檔**：`DATA_*`、`daily_data_update_guide.md`、`HOW_TO_UPDATE_DAILY_DATA.md` 分散在根目錄

### 問題 3：歷史記錄/總結文檔混雜
- `DOCUMENTATION_UPDATE_SUMMARY.md`
- `DOCUMENTATION_CLEANUP_REPORT.md`
- `SOLUTION_SUMMARY.md`
- `API_INVESTIGATION_REPORT.md`
- 這些文檔應該歸檔或整合

### 問題 4：命名不一致
- 有些用下劃線：`PHASE2_ARCHITECTURE.md`
- 有些用連字符：`PHASE_3_3B_IMPLEMENTATION_PLAN.md`
- 有些混合：`EPIC2_MVP2_ARCHITECTURE_DESIGN.md`

---

## 🎯 建議的新組織結構

```
docs/
├── 00_core/                          # 核心文檔（必讀）
│   ├── DEVELOPMENT_ROADMAP.md        # 開發路線圖（最高權威）
│   ├── PROJECT_SNAPSHOT.md           # 專案快照（開場 30 秒）
│   ├── DOCUMENTATION_INDEX.md        # 文檔索引
│   ├── DOC_COVERAGE_MAP.md           # 文檔覆蓋矩陣
│   └── note.txt                      # 開發進度記錄
│
├── 01_architecture/                  # 架構文檔
│   ├── system_architecture.md        # 系統架構
│   ├── system_flow_end_to_end.md     # 端到端流程
│   ├── data_collection_architecture.md
│   └── REFACTORING_MIGRATION_PLAN.md # 重構遷移計劃
│
├── 02_features/                      # 功能文檔
│   ├── UI_FEATURES_DOCUMENTATION.md  # UI 功能文檔
│   ├── USER_GUIDE.md                 # 使用者指南
│   ├── BACKTEST_LAB_FEATURES.md      # 回測功能
│   ├── BACKTEST_LAB_COMPLETE.md      # 回測完成狀態
│   ├── SCORE_EXPLANATION.md          # 評分系統說明
│   └── STRATEGY_DESIGN_SPECIFICATION.md
│
├── 03_data/                          # 數據相關文檔
│   ├── HOW_TO_UPDATE_DAILY_DATA.md   # 如何更新每日數據（快速指南）
│   ├── daily_data_update_guide.md    # 每日數據更新指南（詳細）
│   ├── DATA_FETCHING_LOGIC.md        # 數據獲取邏輯
│   ├── DATA_FLOW_LOGIC.md            # 數據流程邏輯
│   ├── DATA_REBUILD_GUIDE.md         # 數據重建指南
│   ├── TROUBLESHOOTING_DAILY_UPDATE.md # 故障排除
│   ├── INDUSTRY_INDEX_UPDATE_SUMMARY.md
│   ├── MERGE_AND_MARKET_INDEX_SUMMARY.md
│   └── README_UPDATE.md
│
├── 04_broker_branch/                 # 券商分點相關文檔
│   ├── BROKER_BRANCH_DATA_MODULE_DESIGN_V2.md
│   ├── BROKER_BRANCH_IMPLEMENTATION_SUMMARY.md
│   ├── BROKER_BRANCH_TESTING_AND_TROUBLESHOOTING.md
│   ├── BROKER_BRANCH_ERROR_DETECTION_IMPROVEMENT.md
│   └── BROKER_BRANCH_PARSING_IMPROVEMENT.md
│
├── 05_phases/                        # Phase 相關文檔
│   ├── PHASE2_ARCHITECTURE.md
│   ├── PHASE2_STRATEGY_LIBRARY.md
│   ├── PHASE2_5_COMPLETION_STATUS.md
│   ├── PHASE3_3B_RESEARCH_DESIGN.md
│   ├── PHASE_3_3B_IMPLEMENTATION_PLAN.md
│   ├── EPIC2_MVP2_ARCHITECTURE_DESIGN.md
│   └── EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md
│
├── 06_qa/                            # QA 相關文檔
│   ├── QA_RECOMMENDATION_TAB_ISSUES.md
│   ├── QA_RECOMMENDATION_TAB_SUMMARY.md
│   ├── QA_RECOMMENDATION_TAB_FIXES_APPLIED.md
│   ├── QA_RECOMMENDATION_TAB_DEBUG_LOG.md
│   ├── QA_RECOMMENDATION_TAB_FIX_SUGGESTION.md
│   ├── QA_RECOMMENDATION_TAB_LOGGING_PATCH.md
│   ├── QA_UPDATE_TAB_ISSUES.md
│   └── QA_UPDATE_TAB_SUMMARY.md
│
├── 07_guides/                        # 指南文檔
│   ├── QUICK_START.md                # 快速開始
│   ├── QUICK_REFERENCE.md            # 快速參考
│   ├── INSTALL_GUIDE.md              # 安裝指南
│   ├── EXECUTION_GUIDE.md            # 執行指南
│   ├── scripts_readme.md             # 腳本說明
│   └── tests_readme.md               # 測試說明
│
├── 08_technical/                     # 技術文檔
│   ├── PARAMETER_DESIGN_IMPROVEMENTS.md
│   ├── technical_analysis_optimizations.md
│   ├── path_isolation_update.md
│   └── RUN_WITHOUT_VENV.md
│
├── 09_archive/                       # 歸檔文檔（歷史記錄/總結）
│   ├── DOCUMENTATION_UPDATE_SUMMARY.md
│   ├── DOCUMENTATION_CLEANUP_REPORT.md
│   ├── SOLUTION_SUMMARY.md
│   ├── API_INVESTIGATION_REPORT.md
│   └── readme_test.txt               # 歷史測試文檔
│
├── agents/                           # Agent 文檔（保持現有結構）
│   ├── README.md
│   ├── shared_context.md
│   ├── documentation_agent.md
│   ├── data_cleanup_agent.md
│   ├── data_audit_agent.md
│   ├── execution_agent.md
│   └── tech_lead.md
│
└── strategies/                       # 策略文檔（保持現有結構）
    ├── momentum_aggressive_v1.md
    └── stable_conservative_v1.md
```

---

## 📋 整理步驟

### 階段 1：創建新目錄結構
1. 創建所有新目錄（`00_core/`、`01_architecture/`、`02_features/` 等）
2. 使用數字前綴確保排序順序

### 階段 2：移動文件
1. 按照上述結構移動所有文件
2. 保持 `agents/` 和 `strategies/` 子目錄不變

### 階段 3：更新引用
1. 更新 `DOCUMENTATION_INDEX.md` 中的所有路徑引用
2. 更新 `README.md` 中的引用
3. 更新其他文檔中的交叉引用
4. 更新 `DOC_COVERAGE_MAP.md` 中的路徑

### 階段 4：創建 README
1. 在每個新目錄中創建 `README.md`，說明該目錄的用途
2. 在 `docs/` 根目錄創建 `README.md`，說明整體結構

---

## ⚠️ 注意事項

### 1. 引用更新
- 所有文檔中的相對路徑引用都需要更新
- 特別是 `DOCUMENTATION_INDEX.md` 需要大幅更新

### 2. Git 歷史
- 使用 `git mv` 移動文件以保留歷史記錄
- 或者先移動，然後提交變更

### 3. 向後兼容
- 如果其他系統或腳本依賴特定路徑，需要考慮兼容性
- 可以創建符號連結（如果系統支持）

---

## ✅ 預期效果

### 優點
1. **清晰的分類**：相關文檔集中在一起
2. **易於導航**：數字前綴確保排序，核心文檔在最前面
3. **易於維護**：新文檔可以輕鬆歸類
4. **減少混亂**：歷史文檔歸檔，不影響日常使用

### 缺點
1. **需要更新大量引用**：工作量較大
2. **短期混亂**：整理期間可能暫時找不到文件
3. **需要測試**：確保所有引用都正確更新

---

## 🎯 建議執行方式

### 選項 1：一次性完整整理（推薦）
- **優點**：徹底解決問題，一勞永逸
- **缺點**：需要一次性更新所有引用
- **時間**：約 1-2 小時

### 選項 2：分階段整理
- **階段 1**：先整理核心文檔和架構文檔
- **階段 2**：整理功能文檔和數據文檔
- **階段 3**：整理 QA 文檔和歸檔文檔
- **優點**：風險較小，可以逐步驗證
- **缺點**：需要多次提交，時間較長

---

## 📝 待確認事項

1. **是否保留所有歸檔文檔**？
   - 建議：保留，但移到 `09_archive/` 目錄
   - 可以考慮刪除一些明顯過時的文檔

2. **是否統一命名規範**？
   - 建議：保持現有命名，只移動文件
   - 統一命名需要更多工作，可以後續進行

3. **是否創建目錄 README**？
   - 建議：創建，幫助理解目錄結構

---

## 🚀 下一步

請確認：
1. 是否同意這個組織結構？
2. 選擇哪種執行方式（一次性 vs 分階段）？
3. 是否有需要特別處理的文檔？

確認後，我將開始執行整理工作。

