# 測試目錄與執行指南

本文件是 `tests/` 的目前權威入口。舊版長篇指南已移至
`docs/09_archive/readme_test.txt`，僅供歷史追溯。

## 自動測試邊界

repo 根目錄的 `pytest.ini` 定義正式收集範圍：

- 自動測試位於 `tests/`，檔名採 `test_*.py`。
- `tests/manual/` 保存歷史探索、外部網路、繪圖、互動式或固定真實路徑腳本。
- `tests/scripts/` 保存需人工啟動的整合檢查。
- `tests/manual/` 與 `tests/scripts/` 不進入預設 pytest 收集。

正式測試必須可重現、可隔離，優先使用合成資料、mock 與 `tmp_path`，不得
預設 `D:/...` 真實資料存在，也不得在 import 階段建立輸出目錄或啟動網路。

## 現行模組契約

早期腳本曾引用 `DataConfig`、`DataProcessor` 與扁平分析模組路徑。這些名稱
不是目前正式 API，也不應為了讓歷史測試通過而新增空殼相容層。

| 早期假設 | 現行責任 |
|---|---|
| `DataConfig` | `data_module.config.TWStockConfig` |
| 通用 `DataProcessor` | `DataLoader`、`TechnicalIndicatorCalculator` 與各領域 service |
| `analysis_module.pattern_analyzer` | `analysis_module.pattern_analysis.PatternAnalyzer` |
| `analysis_module.technical_analyzer` | `analysis_module.technical_analysis.TechnicalAnalyzer` |
| 通用 `validate_data()` | 依資料領域使用明確驗證，例如 `validate_stock_data()` |

`PatternAnalyzer` 與 `TechnicalAnalyzer` 並未移除；它們已位於明確的領域子套件。
資料清理、技術特徵、推薦與回測也已拆分到各自負責的元件，不再集中於一個
模糊的 `DataProcessor`。

## 主要目錄

- `tests/test_core/`：設定與資料載入契約。
- `tests/test_analysis/`、`tests/test_pattern_analysis/`：技術與型態分析。
- `tests/test_backtest/` 及根目錄 backtest 測試：回測、時間軸與風險。
- `tests/e2e/`：路徑隔離等跨元件契約。
- `tests/manual/`：已棄用或需人工改寫後才能恢復的歷史情境。
- `tests/scripts/`：真實來源或人工操作檢查。

## 執行方式

```powershell
# 完整自動測試
.\.venv\Scripts\python.exe -m pytest -q

# 僅確認可完整收集
.\.venv\Scripts\python.exe -m pytest --collect-only -q

# UI 工作台強制測試
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=

# Update Tab QA
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

## 新增與恢復測試

1. 先確認被測行為是現行公開契約，而非歷史方法名。
2. 以合成資料重現最小行為，避免真實資料與網路依賴。
3. 外部 API 情境應 mock；真實端點探測留在 manual 或 scripts。
4. 若要恢復 `tests/manual/` 的情境，應重新拆成單元或整合測試，不要直接把
   舊檔改回 `test_*.py`。
5. 完成後先跑 focused pytest，再跑完整 pytest 與任務要求的 QA gate。
