# Legacy Test Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清除 legacy 測試的無效 API 引用，隔離手動測試，讓 repository pytest gate 可完整收集與執行。

**Architecture:** 測試直接依賴現行正式 package API，不在 production code 增加假 compatibility alias。自動測試與 manual/integration diagnostics 分流，所有自動資料測試使用臨時目錄或合成 DataFrame。

**Tech Stack:** Python、pytest、pandas、PySide6、TA-Lib compatibility layer

---

### Task 1: 建立 collection error 清單

**Files:**
- Inspect: `tests/`

- [x] 執行 `python -m pytest --collect-only -q -o addopts=`。
- [x] 將錯誤依無效 API、錯誤模組路徑、固定資料、外部服務與 package collision 分類。
- [x] 確認每個錯誤都有「遷移、隔離或刪除」唯一處置。

### Task 2: 遷移資料基礎設施測試

**Files:**
- Modify: `tests/test_core/test_config.py`
- Modify: `tests/test_data/test_data_loading.py`
- Modify: `tests/test_data/test_daily_data.py`
- Modify: `tests/test_backtest/test_backtest_recommendation.py`
- Modify: `tests/test_ml_analysis/test_ml_analyzer.py`
- Modify: `tests/test_recommendation/test_recommendation_report.py`

- [x] 先執行個別測試，確認 legacy import failure。
- [x] 將 `DataConfig` 改為 `TWStockConfig` 並使用 `tmp_path`。
- [x] 將 `DataProcessor` 期待拆成 `DataLoader` 與 `TechnicalIndicatorCalculator` 的合成資料測試。
- [x] 移除固定正式資料路徑、`input()` 與人工輸出依賴。
- [x] 執行修改後測試確認通過。

### Task 3: 修正分析模組測試入口

**Files:**
- Modify: `tests/test_pattern_analysis/*.py`
- Modify: `tests/test_technical_analysis/*.py`

- [x] 將扁平 import 改為正式子套件入口。
- [x] 將需要真實檔案或繪圖人工判讀的腳本移至 manual 分類。
- [x] 保留合成 OHLCV 的 Pattern 與 Technical Analyzer 行為測試。
- [x] 執行分析測試確認通過。

### Task 4: 隔離外部與手動測試

**Files:**
- Create: `tests/manual/README.md`
- Move or remove: 外部 API、固定資料、互動式與一次性診斷測試
- Modify: `tests/pytest.ini` 或根 pytest 設定

- [x] 將真實 TWSE/API、視覺化、人工輸入與本機資料診斷移出自動 collection。
- [x] 在 README 記錄用途、前提與手動執行方式。
- [x] 執行 `pytest --collect-only` 確認不再有 collection error。

### Task 5: 修正剩餘真實失敗

**Files:**
- Modify: 僅限全量 pytest 揭露且屬現行 API 的測試或最小 production fix

- [x] 執行全量 pytest。
- [x] 對每個失敗確認是過時測試或正式回歸。
- [x] 過時測試改寫；正式回歸依 TDD 做最小修正。
- [x] 重跑至全量 gate 通過。

### Task 6: 文件與最終驗證

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`（若新增永久文件入口）

- [x] 記錄現行 API 與 legacy test 處置。
- [x] 執行全量 pytest、mypy、float boundary、py_compile。
- [x] 執行 `git diff --check` 與 staged diff review。
- [x] Commit 並 push 目前分支。
