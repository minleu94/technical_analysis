# 共用上下文 - 不可違背前提

> **所有 Agent 必須遵守的專案規範與前提條件**

## 🎯 核心原則

### 1. 資料完整性優先
- **絕對不可刪除或修改正式資料根目錄內的原始/每日資料檔案**。正式資料根目錄由 `data_module/config.py` 的 `TWStockConfig.data_root` 決定，預設為 `D:/Min/Python/Project/FA_Data`，也可由 `DATA_ROOT` 覆蓋。
- 所有資料處理必須是**非破壞性**的
- 資料驗證失敗時，必須**停止執行**並報告問題

### 2. 向後相容性
- **不可破壞現有功能**
- API 變更必須保持向後相容，或提供明確的遷移路徑
- 移除功能前必須先確認沒有其他地方使用

### 3. 測試覆蓋
- **關鍵功能必須有測試**
- 修改現有功能時，必須更新或新增對應測試
- 測試失敗時不可合併代碼

### 4. 文檔同步
- **代碼變更必須同步更新文檔**
- API 變更必須更新對應的使用文檔
- 新增功能必須更新相關文檔（README、使用指南等）

### 4.1 Git 暫存與排除規範
- Stage 或 commit 前必須先查看 `docs/agents/git_exclusions.md`。
- `.superpowers/`、`docs/.tmp.driveupload/` 與一般快取/測試輸出不得提交。
- `output/qa/update_tab/RUN_LOG.txt` 與 `output/qa/update_tab/VALIDATION_REPORT.md` 目前是 tracked 易變輸出；除非任務明確要求更新 QA 報告，否則不要 stage。
- 不得為了讓 working tree 乾淨而 revert、刪除或覆寫其他 agent / 使用者留下的未提交變更。

### 4.2 股票/量化防禦條款（高優先級）
- 策略、回測、推薦、資金、倉位、風控、交易成本、滑價、績效與風險指標等核心計算，嚴禁新增裸 `float` 計算。
- 金融核心數值必須使用 `Decimal`、整數單位（分、股、基點、萬分點）或明確定義的量化格式；若第三方套件、pandas/numpy 或圖表需要浮點數，必須隔離在資料分析、轉換或展示邊界，不能反向污染策略決策層。
- 實作或修改任何策略、回測、推薦、篩選、績效或 benchmark 邏輯前，必須先完成未來函數（Look-ahead bias）自查。
- Look-ahead 自查至少確認：訊號日期、特徵窗口、標準化樣本、排序/篩選 universe、停損停利判斷、benchmark 對齊、交易價格與持倉更新，都只使用決策當下可取得的資料。
- 無法證明無未來資料滲漏時，必須停止實作並標示「需要確認」。

### 5. 語言規範（強制要求）
- **所有 Agent 必須使用繁體中文**
- **所有文檔、對話、回答、註解都必須使用繁體中文**
- **禁止使用簡體中文**
- **程式碼註解也必須使用繁體中文**

## 📁 專案結構規範

### 核心模組（不可隨意修改）
```
analysis_module/      # 技術分析模組
app_module/          # 應用層模組
backtest_module/     # 回測模組
data_module/         # 資料處理模組
decision_module/     # 決策引擎模組
portfolio_module/    # Portfolio domain layer
runtime/             # Governance-aware AI Runtime
ui_qt/               # PySide6 Qt UI（目前主要 UI）
```

### 資料目錄結構（目前實際規則）

資料不以 repo 內 `data/` 作為唯一來源。所有 Agent 必須先查看 `TWStockConfig` 或執行環境變數，再判定資料位置：

- `DATA_ROOT`：正式資料根目錄，預設 `D:/Min/Python/Project/FA_Data`
- `OUTPUT_ROOT`：輸出根目錄，預設 `D:/Min/Python/Project/FA_Data/output`
- `PROFILE=test` 時，`data_root` 與 `output_root` 會自動加上 `_test`

```
{DATA_ROOT}/
├── daily_price/          # 每日價格資料（YYYYMMDD.csv）
├── meta_data/            # 元資料與整合檔
│   ├── market_index.csv
│   ├── industry_index.csv
│   ├── stock_data_whole.csv
│   ├── all_stocks_data.csv
│   └── broker_branch_registry.csv
├── technical_analysis/   # 技術指標資料
├── broker_flow/          # 券商分點資料
└── logs/                 # 更新與設定日誌
```

### 文檔目錄
```
docs/                # 專案文檔
├── agents/          # Agent 文檔（本目錄）
├── strategies/      # 策略文檔
└── [其他文檔]
```

## 🔧 技術棧與依賴

### 核心技術
- **Python 3.x**
- **PySide6**（目前主要 UI：`ui_qt/`）
- **pandas**（資料處理）
- **numpy**（數值計算）

### 資料格式
- **CSV**：主要資料格式（`stock_data_whole.csv` 等）
- **Parquet**：高效能資料儲存（可選）
- **JSON**：配置與元資料

## 🔁 推薦組合回測共同規範

- 推薦組合回測不是「拿當下推薦名單去批次回測」，而是用 Recommendation Profile/Config 在歷史日期重播推薦邏輯，再依持有天數與資金配置形成整組 portfolio result。
- 相關服務入口：`app_module/recommendation_replay_service.py`、`app_module/recommendation_portfolio_backtest_service.py`、`app_module/recommendation_dataframe_provider.py`、`app_module/recommendation_portfolio_dates.py`。
- 台股資料的 `日期` 欄可能是數字型 `YYYYMMDD`。處理 replay / backtest 日期時必須使用 `parse_stock_dates()` 或同等明確格式解析，不可直接用裸 `pd.to_datetime(series)`，否則會被解讀成 epoch nanoseconds 而落到 1970 年。
- 歷史 replay 需要保留 `candidate_limit` / prefilter 機制；不要在沒有上限的情況下對全市場每期都跑完整 pattern analysis。
- Pattern regression 點位不足或 x 值退化時應安全跳過，不應讓 `np.polyfit` 的 underconstrained case 汙染 UI log 或中斷推薦 replay。
- 後續擴充券商表現、營收數據、Sortino / Sharpe / Monte Carlo 等穩健分析時，應新增 factor/metric layer，避免把新因子硬塞進 UI 或現有單一 scoring 函式。
- 後續擴充營收、基本面、估值、三大法人與其他資料因子時，必須保存 `as_of_date` / `available_date` / 資料品質狀態，避免未來函數滲漏。

## ⚠️ 禁止事項

### 絕對禁止
1. ❌ **刪除或修改原始資料檔案**
2. ❌ **破壞現有 API 的向後相容性**
3. ❌ **移除未經確認的依賴**（可能被其他模組使用）
4. ❌ **跳過測試直接合併代碼**
5. ❌ **修改核心模組結構而未更新文檔**

### 需要謹慎操作
1. ⚠️ **修改資料處理邏輯**（可能影響下游）
2. ⚠️ **重構核心模組**（需要完整測試）
3. ⚠️ **變更資料格式**（需要遷移腳本）
4. ⚠️ **移除功能**（需要確認使用情況）

## 📋 工作流程規範

### 開發流程
1. **閱讀相關文檔** → 了解現有架構
2. **檢查測試** → 確認現有測試狀態
3. **實現代碼** → 遵循編碼規範
4. **執行測試** → 確保所有測試通過
5. **更新文檔** → 同步更新相關文檔
6. **代碼審查** → 使用 tech_lead Agent 進行審查

### UI 修改後強制驗證
1. 執行 `.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=`
2. 執行 `.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py`
3. 執行型態檢查：`.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`
4. 對本次修改的 Python 檔執行 `.\.venv\Scripts\python.exe -m py_compile <changed-python-files>`

### 資料處理流程
1. **驗證輸入資料** → 使用 data_audit_agent
2. **處理資料** → 非破壞性處理
3. **驗證輸出資料** → 確保資料完整性
4. **記錄變更** → 更新資料處理日誌

### 清理流程
1. **識別目標** → 使用 data_cleanup_agent 分析
2. **確認影響** → 檢查依賴關係
3. **備份重要資料** → 以防萬一
4. **執行清理** → 逐步進行
5. **驗證功能** → 確保無破壞性影響

## 📝 文件更新責任與規範

### 文件更新責任

**負責者：**
- **Documentation Agent**：負責識別需要更新的文件、產出更新內容（Coverage Pass + Patch Pass）
- **人類確認**：確認 Coverage 清單、審查更新內容、決定是否合併
- **Execution Agent**：執行代碼變更時，必須同步觸發 Documentation Agent 的 Coverage Pass

**責任流程：**
1. 代碼變更發生 → Execution Agent 或人類通知 Documentation Agent
2. Documentation Agent 執行 Coverage Pass → 列出需要更新的文件清單
3. 人類確認 Coverage 清單 → 授權更新範圍
4. Documentation Agent 執行 Patch Pass → 產出更新內容
5. 人類審查更新內容 → 確認後合併

### 必須更新文件的情況

以下情況發生時，**必須**更新對應文件：

1. **功能行為改變**
   - 功能新增、修改、移除
   - API 介面變更（參數、返回值、行為）
   - 使用者操作流程變更

2. **系統狀態改變**
   - Phase 完成狀態變更
   - 優先事項變更
   - 高風險區變更
   - 系統定位變更

3. **架構或流程改變**
   - 模組結構變更
   - 資料流程變更
   - 工作流程變更（「現在的工作模式」）

4. **文件結構改變**
   - 新增/刪除/重組文檔
   - 文檔索引結構變更

**更新範圍：**
- 根據 `docs/00_core/DOC_COVERAGE_MAP.md` 的「變更類型 → 必須更新的文件對照表」識別
- 所有標示為 Must 優先級的文件必須更新
- 必須執行 Snapshot / Roadmap Hub / 6M Roadmap / Legacy Carryover / Architecture / Manual / Index 一致性檢查
- 使用者可見流程、參數、結果判讀或安全限制改變時，必須同步 `docs/07_guides/APPLICATION_MANUAL.md`

### 可以不更新文件的情況

以下情況發生時，**可以不更新**文件（但建議記錄在變更日誌）：

1. **純內部重構**
   - 代碼重構但不改變外部行為
   - 函數/類別重命名但不改變功能
   - 代碼風格調整

2. **不影響外部行為的變更**
   - 性能優化但不改變功能
   - Bug 修復但不改變 API
   - 測試覆蓋增加但不改變功能

3. **臨時性變更**
   - 實驗性功能（未正式發布）
   - 開發中的功能（未完成）

**判斷標準：**
- 使用者是否會感受到差異？
- API 是否改變？
- 操作流程是否改變？
- 如果答案都是「否」，則可以不更新文件

### 更新記錄 / 變更日誌規範

**位置：**
- **文件底部**：每個文件在底部維護「🔄 更新記錄」段落
- **集中式變更日誌**：重大變更記錄在 `docs/UPDATE_LOG_YYYY_MM_DD.md`（如存在）

**基本格式：**

**文件底部更新記錄格式：**
```markdown
## 🔄 更新記錄

- YYYY-MM-DD：[變更摘要]（影響範圍：XXX）
- YYYY-MM-DD：[變更摘要]（影響範圍：XXX）
```

**集中式變更日誌格式（如存在）：**
```markdown
## YYYY-MM-DD 變更記錄

### 變更摘要
[1-2 句話描述變更內容]

### 影響範圍
- 文件：[列出受影響的文件]
- 功能：[列出受影響的功能]
- 使用者：[說明對使用者的影響]

### 相關文件
- [文件路徑 1]：更新了 XXX 段落
- [文件路徑 2]：更新了 XXX 段落
```

**更新記錄責任：**
- **Documentation Agent**：在 Patch Pass 階段產出更新記錄內容
- **人類確認**：確認更新記錄準確性後合併

**更新記錄時機：**
- 所有 Must 優先級的文件更新時，必須更新記錄
- 重大變更（影響多個文件、影響使用者流程）時，建議記錄在集中式變更日誌

## 🔍 驗證檢查清單

在執行任何重要操作前，必須檢查：

- [ ] 是否影響現有功能？
- [ ] 是否有對應的測試？
- [ ] 是否更新了相關文檔？
- [ ] 是否破壞了向後相容性？
- [ ] 是否影響資料完整性？
- [ ] 是否遵循了專案結構規範？

## 📚 參考資源

- **專案文檔**：`docs/` 目錄
- **策略文檔**：`docs/strategies/`
- **目前狀態**：`docs/00_core/PROJECT_SNAPSHOT.md`
- **6 個月工程路線**：`docs/00_core/ROADMAP_6M_ENGINEERING.md`
- **Roadmap Hub**：`docs/00_core/DEVELOPMENT_ROADMAP.md`
- **舊 Roadmap 移交**：`docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`
- **系統架構**：`docs/01_architecture/system_architecture.md`
- **完整操作手冊**：`docs/07_guides/APPLICATION_MANUAL.md`

## 🔄 更新記錄

- 2026-01-03：初始建立共用上下文規範
- 2026-01-03：新增「文件更新責任與規範」段落（定義更新責任、必須/可以不更新情況、更新記錄格式）
- 2026-05-20：更新資料根目錄、`ui_qt`/PySide6、Portfolio 與 Runtime 現況，避免 Agent 誤判 repo 內 `data/` 為正式資料位置
- 2026-05-29：新增股票/量化防禦條款，並將 UI 修改後 QA script 與型態檢查列為強制驗證流程
- 2026-06-13：更新文件治理規範為 Scoped SSOT，補充 factor layer 資料可得日與品質治理要求
- 2026-06-13：補入 Legacy Carryover 與 Application Manual 的權威範圍及同步要求

