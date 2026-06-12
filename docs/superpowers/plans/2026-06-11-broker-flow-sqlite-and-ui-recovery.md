# Broker Flow SQLite and UI Recovery Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:systematic-debugging` first, then `superpowers:test-driven-development`. Do not modify production data until the duplicate-key source and the broken read path are proven.

**Goal:** 找出並修復券商分點同步 SQLite 的唯一鍵衝突，以及主力流向頁面資料錯誤、空白或數值異常問題，同時保證 MoneyDJ `c=E` 張數與 `c=B` 千元金額不再混用。

**Architecture:** 將問題拆成四段資料鏈逐段驗證：MoneyDJ 原始回應 -> daily CSV -> merged CSV -> SQLite -> BrokerFlowService/UI。每一段都必須檢查唯一鍵、日期格式、分點識別、股票代碼與單位契約；只有找到第一個產生錯誤資料的邊界後才允許修改程式。

**Tech Stack:** Python、pandas、SQLite、pytest、PySide6、Selenium/BeautifulSoup、MoneyDJ。

---

## 0. 安全限制

- 不得直接刪除或覆寫正式 `DATA_ROOT` 的 CSV。
- 不得先執行 `DELETE FROM broker_flows`、重建正式 SQLite 或全量重新抓取。
- 所有重現先使用 `tmp_path`、資料庫副本或唯讀 SQL。
- 保留 `c=E -> 張數 -> 股數乘 1000` 與 `c=B -> 金額千元` 的契約。
- 不得用成交均價把 B 金額反推張數。
- 不得把 legacy `buy_qty/sell_qty/net_qty` 當成張數；現有歷史資料需先確認當初 URL 指標。
- 修復時不得順帶提交目前亂碼的 `docs/02_features/UI_FEATURES_DOCUMENTATION.md`。

## 1. 建立故障基線

### Task 1: 記錄環境與實際資料位置

**Read:**
- `data_module/config.py`
- `app_module/update_service.py`
- `app_module/broker_branch_update_service.py`
- `data_module/db_manager.py`

- [ ] 執行以下命令，記錄目前 branch、commit、dirty files：

```powershell
git status --short --branch
git log -3 --oneline --decorate
```

- [ ] 使用 `TWStockConfig` 印出以下實際路徑，不要假設預設值：
  - `db_path`
  - `broker_flow_dir`
  - `broker_branch_registry_file`
  - `use_sqlite`

- [ ] 複製 SQLite 到暫存位置，後續所有破壞性驗證只操作副本。

**Expected evidence:** 明確知道 UI 實際讀寫哪個 DB 與哪個 broker-flow 目錄。

### Task 2: 重現 SQLite 同步錯誤並取得完整 stack trace

**Read:**
- `app_module/update_service.py:27`
- `app_module/update_service.py:_replace_sqlite_dates`
- `data_module/db_manager.py:write_dataframe`

- [ ] 以和 UI 相同的 `source/start_date/end_date` 呼叫 `sync_source_to_sqlite()`。
- [ ] 暫時讓 `_replace_sqlite_dates()` 不吞例外，或使用測試包裝器輸出完整 stack trace。
- [ ] 記錄：
  - normalized source 是 `broker_branch` 還是 `broker_branch_files`
  - DataFrame 筆數
  - DataFrame 欄位
  - 日期最小值與最大值
  - 寫入前唯一鍵重複數

```python
key = ["分點名稱", "證券代號", "日期"]
duplicates = df[df.duplicated(key, keep=False)].sort_values(key)
print("rows", len(df))
print("duplicate_rows", len(duplicates))
print("duplicate_keys", duplicates[key].drop_duplicates().shape[0])
print(duplicates.head(50).to_string(index=False))
```

**Decision:**
- 若 `duplicate_rows > 0`，衝突來源在待寫入 DataFrame 內。
- 若 `duplicate_rows == 0`，檢查刪除日期與 append 是否在同一 transaction/同一 DB，並確認日期正規化是否一致。

## 2. 唯一鍵衝突根因調查

### Task 3: 追查重複鍵來自哪個 CSV

**Inspect:**
- `*/daily/*.csv`
- `*/meta/merged.csv`
- broker branch registry

- [ ] 在載入每個 CSV 時新增診斷欄位，但不可寫入 SQLite：

```python
df["_source_file"] = str(path)
df["_source_branch_dir"] = branch_dir.name
```

- [ ] 對每個重複唯一鍵列出：
  - source file
  - source branch directory
  - `branch_system_key`
  - `branch_display_name`
  - `counterparty_broker_code`
  - date
  - E/B 六個數值欄位

- [ ] 分類根因：
  1. 同一 CSV 本身重複股票列。
  2. 同一日期被多個檔案載入。
  3. 多個 branch system key 共用相同 display name。
  4. `branch_display_name` 缺失後 fallback 導致名稱碰撞。
  5. `merged.csv` 已含重複資料。
  6. 股票代號在字串化前後碰撞，例如前導零遺失。

**Acceptance:** 每一組重複鍵都能指回具體來源檔與產生原因。

### Task 4: 驗證 delete-then-append transaction

- [ ] 在 SQLite 副本執行同步前後查詢：

```sql
SELECT 日期, COUNT(*) AS rows
FROM broker_flows
WHERE 日期 IN (...)
GROUP BY 日期;
```

- [ ] 確認 `_replace_sqlite_dates()`：
  - delete 與 append 使用相同 connection。
  - `df["日期"]` 與 DB `日期` 使用完全相同格式。
  - append 失敗時 delete 會 rollback。

- [ ] 特別比對 `2026-06-11`、`20260611`、`115/06/11` 是否被正規化成同一鍵。

**Expected:** 排除「舊資料未刪到」或「日期格式不同」造成的假性 upsert。

## 3. 主力流向資料鏈調查

### Task 5: 驗證 daily CSV 的 E/B 契約

**Read:**
- `app_module/broker_branch_update_service.py`
- `tests/test_broker_branch_decode.py`

- [ ] 以康和永和同一日期取樣，直接比較：
  - `c=E`: `buy_lots/sell_lots/net_lots`
  - `c=B`: `buy_amount_k_twd/sell_amount_k_twd/net_amount_k_twd`

- [ ] 檢查 daily CSV 每列必須同時包含：

```text
date
branch_system_key
branch_display_name
counterparty_broker_code
counterparty_broker_name
buy_lots
sell_lots
net_lots
buy_amount_k_twd
sell_amount_k_twd
net_amount_k_twd
```

- [ ] 驗證等式：
  - `net_lots == buy_lots - sell_lots`
  - `net_amount_k_twd == buy_amount_k_twd - sell_amount_k_twd`

- [ ] 驗證 E/B 合併鍵至少包含股票代號，且不因股票名稱空白或名稱差異而漏合併。

**Acceptance:** 同一股票的 E/B 數值可追溯到兩個不同 URL，沒有欄位覆蓋。

### Task 6: 驗證 merged.csv 完整性

**Read:**
- `app_module/broker_branch_update_service.py` 的 merge 流程
- `app_module/broker_flow_service.py:_load_data`

- [ ] 對每個分點統計：
  - daily 檔日期數
  - merged 日期數
  - merged 總列數
  - 缺少 `buy_lots/sell_lots/net_lots` 的日期數
  - 唯一鍵重複數

- [ ] 確認更新 daily CSV 後，是否真的重建或增量更新 `meta/merged.csv`。
- [ ] 確認舊 B-only merged 檔是否導致 `BrokerFlowService` 整個分點被跳過。
- [ ] 不允許用缺欄位補零後把 B-only 日期偽裝成完整雙指標日期。

**Likely failure to verify:** `BrokerFlowService` 只讀 merged.csv；若 merged 未重建或仍是 B-only，主力流向會空白或大量缺資料，即使 daily CSV 已抓取成功。

### Task 7: 驗證日期與股票代號契約

- [ ] 列出 events 中日期格式分布：

```python
from collections import Counter
print(Counter(
    "dash" if len(e.date) == 10 and "-" in e.date
    else "compact" if len(e.date) == 8 and e.date.isdigit()
    else "other"
    for e in events
))
```

- [ ] 驗證 `_filter_events_by_period()` 不可只解析 `%Y-%m-%d` 後在失敗時使用系統今天；它必須支援實際 CSV 日期格式並以資料最新日為基準。
- [ ] 所有股票代號以字串讀取，保留前導零與字母，例如 `00631L`。
- [ ] 禁止先由 pandas 推斷成數字再轉字串。

**Acceptance:** day/week/month 在固定測試資料上回傳正確日期集合。

### Task 8: 驗證單位在服務與 UI 邊界

**Read:**
- `app_module/broker_flow_service.py`
- `app_module/portfolio_chip_service.py`
- `decision_module/flow_signal_engine.py`
- `ui_qt/views/smart_money/`
- `ui_qt/views/portfolio_view.py`

- [ ] 建立單位矩陣：

| 邊界 | 欄位 | 單位 |
|---|---|---|
| daily/merged CSV | `*_lots` | 張 |
| daily/merged CSV | `*_amount_k_twd` | 千元 |
| `BrokerFlowEvent.*_qty` | 張 |
| SQLite `*股數` | 股 |
| SQLite `*金額千元` | 千元 |
| FlowSignalEngine aggregation | 張 |
| PortfolioChipService summary | 股 |
| UI 顯示主力流向 | 張 |
| UI 顯示持倉籌碼 | 由股數除 1000 顯示張 |

- [ ] 搜尋所有 `*1000`、`/1000`，逐一確認只出現在 CSV 張數與 SQLite/UI 股數的明確邊界。
- [ ] 確認 FlowSignalEngine 的門檻 `500` 是 500 張，不是 500 股或 500 千元。
- [ ] 確認 sparkline、分數、強度、標籤均只使用 lots，不使用 amount。

## 4. 先寫失敗測試

### Task 9: SQLite 同批重複鍵測試

**Modify:** `tests/test_update_service_status.py`

- [ ] 建立兩個來源檔，刻意產生相同 `(分點名稱, 證券代號, 日期)`。
- [ ] 先依 Task 3 的根因定義正確行為：
  - 完全相同列：安全去重。
  - E/B 欄位互補列：按欄位合併。
  - 同欄位數值衝突：同步失敗並輸出來源，不可靜默保留任一筆。
- [ ] 執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_update_service_status.py -q -o addopts=
```

**Expected before fix:** UNIQUE constraint failure or assertion failure。

### Task 10: 重複同步冪等測試

- [ ] 同一日期範圍連續同步兩次。
- [ ] 驗證第二次成功，總列數不增加，所有 E/B 值相同。
- [ ] 驗證某日期內容更新後再同步，該日期被正確替換。

### Task 11: merged 與主力流向測試

**Modify/Create:**
- `tests/test_broker_flow_units.py`
- `tests/test_broker_flow_service.py`（若不存在則建立）

- [ ] 測試雙指標 merged 可載入。
- [ ] 測試 B-only legacy 不會被當張數。
- [ ] 測試某分點 legacy、另一分點雙指標時，不會讓整個頁面無資料且會產生可見診斷。
- [ ] 測試 `YYYY-MM-DD` 與 `YYYYMMDD` 經正規化後 week/month 結果一致。
- [ ] 測試偏多、偏空、neutral 股票的 tags、reasons、intensity。
- [ ] 測試 `00631L` 不會被截斷或改碼。

### Task 12: SQLite/CSV 等價測試

- [ ] 以相同 fixture 分別走：
  - BrokerFlowService CSV 路徑
  - PortfolioChipService SQLite 路徑
- [ ] 比較每個股票/分點/日期的買、賣、淨額，換算後必須一致。
- [ ] 金額欄位獨立比較，不參與張數斷言。

## 5. 修復策略（必須依證據選擇）

### Task 13: 修復 DataFrame 唯一鍵

- [ ] 在 `_load_broker_branch_csv_for_sqlite()` 與 `_load_broker_branch_files_for_sqlite()` 回傳前，先驗證唯一鍵。
- [ ] 不可直接無條件 `drop_duplicates(keep="last")`。
- [ ] 完全相同重複列可去重。
- [ ] E/B 互補列應 deterministic merge。
- [ ] 同一唯一鍵同一 metric 出現不同值時，回報來源檔並停止同步。
- [ ] 寫入前 assert：

```python
key = ["分點名稱", "證券代號", "日期"]
assert not df.duplicated(key).any()
```

### Task 14: 實作明確 upsert/日期替換

- [ ] 保留 transaction。
- [ ] broker flow 日期替換前必須先通過唯一鍵驗證。
- [ ] SQL 識別字需安全引用。
- [ ] 例外不可被 `_replace_sqlite_dates()` 靜默吞掉；至少記錄 table、日期範圍、rows、duplicate keys 與 stack trace。
- [ ] 不建議用 `INSERT OR REPLACE` 掩蓋來源重複；它只能在來源唯一性已驗證後使用。

### Task 15: 修復 merged 更新與讀取

- [ ] daily 成功後，merged 必須反映相同日期的雙指標資料。
- [ ] merged completeness 以實際欄位與非空值判斷，不只看檔案存在。
- [ ] BrokerFlowService 應提供每個分點載入/跳過原因摘要。
- [ ] 日期在進入 DTO 前正規化成單一格式 `YYYY-MM-DD`。
- [ ] 修復後清除或版本化記憶體快取，確保 UI reload 不會繼續顯示舊 events。

### Task 16: 修復 UI 錯誤呈現

- [ ] 主力流向頁面顯示：
  - 載入事件數
  - 有效分點數
  - 最新資料日
  - 被跳過分點數與原因
- [ ] SQLite 同步失敗不得只顯示「失敗」，需包含 duplicate-key 摘要。
- [ ] UI refresh 必須使用 `force_reload=True` 或明確 cache invalidation。

## 6. 驗證順序

### Task 17: 自動測試

依序執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_broker_branch_decode.py tests/test_broker_flow_units.py tests/test_update_service_status.py tests/test_portfolio_chip_monitor.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

- [ ] 對所有修改 Python 檔執行 `py_compile`。
- [ ] 執行 `git diff --check`。

### Task 18: 暫存資料端到端驗證

- [ ] 用臨時目錄抓康和永和 E/B。
- [ ] 產生 daily 與 merged。
- [ ] 同步到臨時 SQLite 兩次。
- [ ] 驗證：
  - 兩次同步都成功。
  - DB 無重複唯一鍵。
  - E 張數乘 1000 後等於 SQLite 股數。
  - B 數值原樣進 SQLite 金額千元。
  - BrokerFlowService 有事件。
  - week/month 有訊號。

### Task 19: 正式資料修復前審計

- [ ] 先產出報告，不直接改資料：
  - B-only 日期
  - E/B 完整日期
  - merged 缺失日期
  - duplicate keys
  - SQLite 現有日期與列數
- [ ] 由使用者確認後，才執行受控重抓/重合併/重同步。
- [ ] 正式修復需可從備份復原。

## 7. Definition of Done

- [ ] 同一日期範圍可重複同步，無 UNIQUE constraint error。
- [ ] 待寫入 DataFrame 與 SQLite 都沒有重複 `(分點名稱, 證券代號, 日期)`。
- [ ] 康和永和 `c=E` 與 `c=B` 可抓取且六個 metric 正確保存。
- [ ] 主力流向頁有合理的股票列表、張數、sparkline、偏多/偏空標籤。
- [ ] 持倉籌碼 SQLite 與 CSV fallback 結果一致。
- [ ] 日期篩選以資料最新交易日為基準，不受系統今天或格式差異影響。
- [ ] 重整 UI 後快取失效，立即看到新資料。
- [ ] 所有目標測試、UI QA、mypy、py_compile 通過。
- [ ] 正式資料變更前後都有審計報告與備份。
- [ ] 文件明確記錄 E/B 單位、唯一鍵、日期格式與同步冪等行為。
