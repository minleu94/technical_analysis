# LUNA B 開發環境與依賴基線

> 目的：把 runtime、QA/development 與已驗證版本分開，避免把一次性的 `pip freeze` 誤當成可重建的專案需求。本文是 B 線工程環境紀錄，不改寫產品狀態或正式資料政策。

## 1. 需求檔關係

| 檔案 | 用途 | 範圍 |
|---|---|---|
| `requirements-runtime.txt` | 最小直接 runtime 依賴 | UI、資料抓取、分析、ML artifact、Parquet、MCP server 所需的直接套件 |
| `requirements-dev.txt` | 開發／QA 環境 | `requirements-runtime.txt` 加上 `pytest`、`pytest-qt`、`mypy` |
| `requirements.txt` | 相容入口 | 只轉接 `requirements-dev.txt`，保留既有安裝指令的行為 |
| `requirements-py311-windows.constraints.txt` | 已驗證 direct constraints | 對現有 Windows x64 / Python 3.11.9 `.venv` 的 direct package 版本快照 |

建議安裝命令（只在自己的新 venv 執行，本文本身未執行安裝）：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-runtime.txt -c requirements-py311-windows.constraints.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -c requirements-py311-windows.constraints.txt
```

`requirements.txt` 是向後相容的 all-in-one 入口；新環境若只需要啟動應用程式，使用 runtime manifest 即可。constraints 只約束本專案辨識出的 direct dependencies，不宣稱已鎖定所有 transitive packages，也不包含本機下載的 `fubon_neo` wheel 或 Codex 專用套件。

## 2. 實際驗證基線

本次在既有隔離環境完成版本與 import 檢查：

- Windows x64、Python `3.11.9`，執行檔為 repo `.venv\Scripts\python.exe`。
- `pandas 2.3.3`、`numpy 2.3.5`、`scikit-learn 1.8.0`、`scipy 1.16.3`、`statsmodels 0.14.6`。
- `TA-Lib 0.6.8`（import 名稱 `talib`）與 fallback `ta 0.5.25` 均可取得。
- `PySide6 6.10.1` 可取得；`pytest-qt` 在本環境缺失，因此 Qt plugin 測試不列為本批已驗證結果。
- `pyarrow 22.0.0`、`joblib 1.5.2`、`psutil 7.1.3`、`requests 2.32.5`、`beautifulsoup4 4.14.3`、`tqdm 4.67.1`、`loguru 0.7.3` 與 `pywin32 311` 可取得。
- `pytest 9.0.2`、`mypy 2.1.0` 可執行。

可重複執行的檢查命令：

```powershell
.\.venv\Scripts\python.exe -c "import sys, pandas, numpy, talib, ta, PySide6, pyarrow, joblib, psutil, requests; print(sys.version); print('runtime imports OK')"
.\.venv\Scripts\python.exe -m pip check
```

上述版本檢查是對現有 `.venv` 的 evidence；沒有建立 clean clone、沒有下載套件、沒有執行全量升級，故不能把它寫成 clean-install passed。

## 3. Windows / TA-Lib / PySide6 邊界

- Python 以 3.11 x64 為本專案已驗證基線；換 Python major/minor 或 CPU architecture 前要重新驗證 wheel、NumPy、TA-Lib 與 PySide6。
- `technical_analyzer.py` / `technical_indicators.py` 使用 `talib`；`talib_compatibility.py` 另保留 `ta` fallback。兩者都列在 runtime manifest，避免只安裝其中一個造成啟動路徑缺依賴。
- `PySide6` 是主要 UI runtime。`pytest-qt` 只屬 dev/QA，且本次環境未安裝；應在具備 Qt test plugin 的新 venv 個別執行 UI gate。
- Parquet 路徑以 `pyarrow` 為首選 engine；`backtest_repository.py` 保留 `fastparquet` fallback，但本 manifest 不同時要求兩套 engine。
- `pywin32` 僅在 Windows marker 下安裝，用於 promotion authority 的 DPAPI secret store；Fubon SDK 是外部、optional 的 broker probe，不是本專案 runtime baseline。

## 4. 測試資料與容量安全

- 正式資料位置仍以 `TWStockConfig` 為準，預設 `D:/Min/Python/Project/FA_Data`；本批沒有改變 `DATA_ROOT`、`OUTPUT_ROOT` 或 200 GiB production reserve。
- B 線測試與暫存只允許落在 `output/luna_B/`；OOC capacity fixture 只在測試 scope 內 patch `storage_capacity.filesystem_usage`，不改 production reserve，也不讀正式資料。
- 真實 capacity tests 仍保留低空間、跨磁碟、concurrency、watchdog 與 no-write coverage；不能以 synthetic fixture 取代這些實際 policy tests。
