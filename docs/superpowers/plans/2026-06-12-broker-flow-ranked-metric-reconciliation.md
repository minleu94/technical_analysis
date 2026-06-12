# Broker Flow Ranked Metric Reconciliation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:systematic-debugging`, `superpowers:test-driven-development`, and `superpowers:verification-before-completion`. Do not treat an absent E/B row as zero.

**Goal:** 正確處理 MoneyDJ `c=E` 張數榜與 `c=B` 金額榜各自獨立排序、各取買超/賣超 Top 50 的資料契約，避免把榜外資料誤判為零、抓取失敗或整檔股票不可用。

**Architecture:** E 與 B 是兩個獨立的 ranked/censored datasets。每日資料以兩榜 union 保存，每個 metric 都保留 observed、estimated、unavailable 狀態；訊號計算只聚合可用張數事件，單筆不可用不得污染整檔股票。估算資料必須保留來源、覆蓋率與 UI 警示。

**Tech Stack:** Python、pandas Nullable Integer、Decimal、SQLite、pytest、PySide6、Selenium/BeautifulSoup。

---

## 已確認的 MoneyDJ 契約

2026-06-12 實抓 5 個分點、2 個交易日，共 10 組 E/B 對照：

- E 與 B 每頁固定 100 筆。
- E：買超 50 筆＋賣超 50 筆，依張數排行。
- B：買超 50 筆＋賣超 50 筆，依金額排行。
- 每組交集僅 48 至 62 筆。
- 每組各有 38 至 52 筆 E-only 與 B-only。
- 康和永和 2026-06-11：交集 58、E-only 42、B-only 42。

結論：

- E-only：真實張數已知，金額只是未進 B 榜，不代表金額為 0。
- B-only：真實金額已知，張數只是未進 E 榜，不代表張數為 0。
- 兩榜都沒有：只代表未進任何 Top 50，不能推論沒有交易。
- 缺欄位是榜單截斷（censoring），不是一般 missing-data 或 fetch failure。

## Task 1: 固化 ranked metric contract

**Modify:**
- `app_module/broker_branch_update_service.py`
- `app_module/dtos/broker_flow_dtos.py`
- `docs/03_data/DATA_FETCHING_LOGIC.md`

**Test:**
- `tests/test_broker_branch_decode.py`

- [ ] 為每筆 parser 結果加入：

```python
metric_source: Literal["lots", "amount"]
metric_rank: int
trade_type: Literal["買超", "賣超"]
```

- [ ] rank 必須在每個方向各自從 1 到 50。
- [ ] 文件明確記載 E/B 是獨立 Top-N，不是完整資料集。
- [ ] 測試買超、賣超分別恰有 50 筆時 rank 為 1..50。

## Task 2: 正確合併 E/B union

**Modify:**
- `app_module/broker_branch_update_service.py:_merge_metric_records`

**Test:**
- `tests/test_broker_branch_decode.py`

- [ ] 合併鍵維持：

```python
("date", "trade_type", "branch_system_key", "counterparty_broker_code")
```

- [ ] 合併後加入明確欄位：

```python
lots_observed: bool
amount_observed: bool
lots_rank: Optional[int]
amount_rank: Optional[int]
```

- [ ] E-only：
  - `lots_observed=True`
  - `amount_observed=False`
  - amount 欄位保持 NULL
- [ ] B-only：
  - `lots_observed=False`
  - `amount_observed=True`
  - lots 欄位保持 NULL
- [ ] E/B 交集保留兩組真實值及兩個 rank。
- [ ] 不得使用 `fillna(0)` 表示榜外資料。

## Task 3: 修復 CSV 與 SQLite NULL 契約

**Modify:**
- `app_module/update_service.py`
- `scripts/migrate_csv_to_sqlite.py`

**Test:**
- `tests/test_update_service_status.py`

- [ ] lots 使用 pandas `Int64`：

```python
df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
```

- [ ] amount 同樣應允許 NULL；E-only 的 amount 不是 0。
- [ ] 股數只由 observed lots 轉換：

```python
shares = (lots * 1000).astype("Int64")
```

- [ ] 修正目前 regression：

```python
assert pd.isna(loaded.loc[0, "買進股數"])
```

- [ ] 新增 E-only 測試，確認金額為 NULL 而非 0。
- [ ] 新增 B-only 測試，確認股數為 NULL 而非 0。
- [ ] SQLite 同步兩次必須冪等且不改變 NULL。

## Task 4: 重新定義事件可用性

**Modify:**
- `app_module/dtos/broker_flow_dtos.py`
- `app_module/broker_flow_service.py`

- [ ] 移除容易誤解的單一 `lots_available` AND 語意，改成事件層狀態：

```python
lots_quality: Literal["observed", "estimated", "unavailable"]
amount_quality: Literal["observed", "unavailable"]
```

- [ ] E-only event：
  - lots quality = observed
  - 可直接進張數訊號
- [ ] B-only event：
  - 有同日收盤價時 lots quality = estimated
  - 無收盤價時 lots quality = unavailable
- [ ] 不可用 event 保留於資料品質統計，但不加入張數總和。

## Task 5: 修正 aggregation poisoning

**Modify:**
- `app_module/dtos/broker_flow_dtos.py`
- `app_module/broker_flow_service.py`
- `decision_module/flow_signal_engine.py`

**Test:**
- `tests/test_broker_flow_units.py`

- [ ] Stock/Branch aggregation 增加：

```python
observed_event_count: int
estimated_event_count: int
unavailable_event_count: int
usable_event_count: int
lots_coverage_ratio: Decimal
```

- [ ] aggregation 可計算條件：

```python
usable_event_count > 0
```

- [ ] 單一 unavailable event 不得讓整檔股票訊號歸零。
- [ ] 只有 `usable_event_count == 0` 才回傳「無可用張數數據」。
- [ ] 新增混合 fixture：
  - 1 筆 observed
  - 1 筆 estimated
  - 1 筆 unavailable
  - 預期仍產生訊號，總量只包含前兩筆。

## Task 6: 估算方法與限制

**Modify:**
- `app_module/broker_flow_service.py`
- `app_module/portfolio_chip_service.py`

- [ ] 僅 B-only event 可使用：

```text
estimated_lots = amount_k_twd / close_price
```

原因：`amount_k_twd × 1000 / price / 1000` 可約簡為上述張數公式。

- [ ] 使用 `Decimal` 與 `ROUND_HALF_UP`。
- [ ] 無收盤價時保持 unavailable，不使用固定價格。
- [ ] 必須標示估算限制：收盤價不等於分點實際成交均價。
- [ ] E-only event 不需要估算張數；其 lots 是真實值。
- [ ] 不得反向把 E-only 張數估成「真實金額」後寫回來源欄位。

## Task 7: 以覆蓋率治理分數

**Modify:**
- `decision_module/flow_signal_engine.py`

**Test:**
- `tests/test_broker_flow_units.py`

- [ ] 不使用「只要含一筆估算就固定乘 0.8」。
- [ ] 使用資料覆蓋率調整 confidence：

```python
estimated_ratio = estimated_event_count / usable_event_count
coverage_ratio = usable_event_count / total_event_count
```

- [ ] 建議：
  - score 仍由 usable lots 計算。
  - confidence 乘上 coverage factor。
  - estimated ratio 越高，confidence 上限越低。
- [ ] 所有比例運算使用 Decimal，僅在 DTO/UI 邊界轉 float。
- [ ] 強度門檻不可任意「全部加倍」；應透過測試資料或明確規格定義。

## Task 8: UI 顯示資料品質，而非只有星號

**Modify:**
- `app_module/dtos/flow_signal_dtos.py`
- `ui_qt/views/smart_money/terminal_table_model.py`
- `ui_qt/views/smart_money/smart_money_flow_view.py`

- [ ] Scanner 顯示：

```text
真實 68%｜估算 25%｜不可用 7%
```

- [ ] Detail table 每個分點標示：
  - 實際張數
  - 金額估算
  - 榜外且無法估算
- [ ] 不可用資料不顯示為 0 張。
- [ ] Tooltip 解釋 E/B 各自 Top 50，避免使用者誤認為空值是零交易。
- [ ] Portfolio summary 回傳：

```python
lots_quality
observed_event_count
estimated_event_count
unavailable_event_count
```

## Task 9: 收盤價查詢與效能

**Modify:**
- `app_module/broker_flow_service.py`

- [ ] 保留精確 key 查詢，不讀取整張 `daily_prices`。
- [ ] 避免 400 組 OR 條件；優先評估：
  - 暫存 key table + JOIN
  - 依日期分組後使用 `日期=? AND 證券代號 IN (...)`
- [ ] 價格 map 直接保存 Decimal-compatible 字串，不先轉 float。
- [ ] 建立正式資料效能基準：
  - 104,986 events 冷載入目標 `< 3 秒`
  - 快取後 period aggregation `< 0.2 秒`
- [ ] 測試與 walkthrough 必須區分 cold load 與 cached aggregation，不得宣稱整體 `<0.05 秒`。

## Task 10: 修復狀態卡與 coverage 統計

**Modify:**
- `app_module/update_service.py`
- `ui_qt/views/update_view.py`

- [ ] `date_count` 使用 SQL：

```sql
COUNT(DISTINCT 日期)
```

- [ ] 狀態卡新增：
  - 總天數
  - 雙指標完整天數
  - E-only rows
  - B-only rows
  - observed/estimated/unavailable lots rows
- [ ] QA 必須 assert `date_count == 158`，不能只檢查 key 存在。

## Task 11: 正式資料遷移

- [ ] 先備份 merged CSV 與 SQLite。
- [ ] 從現有 daily CSV 重建 union，不需重新爬取已有 E/B 的日期。
- [ ] 歷史 B-only 日期保留 amount observed、lots NULL。
- [ ] 不要把目前估算結果寫回 `broker_flows.買進股數`；估算應在分析層即時計算或寫入獨立欄位：

```text
估算買進股數
估算賣出股數
估算買賣超股數
估算價格來源
```

- [ ] 遷移後驗證唯一鍵、NULL、rank 與 observed flags。

## Task 12: 必跑驗證

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_broker_branch_decode.py tests/test_broker_flow_units.py tests/test_update_service_status.py tests/test_portfolio_chip_monitor.py tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
.\.venv\Scripts\python.exe -m py_compile <changed-python-files>
git diff --check
```

正式資料 smoke test：

- [ ] E/B 每方向各 50。
- [ ] E-only、B-only 均存在且保持 NULL 語意。
- [ ] 一筆 unavailable 不會清空整檔股票。
- [ ] week/month 不同且 coverage 統計合理。
- [ ] cold load 與 cached aggregation 分開報告。
- [ ] UI 不把榜外資料顯示為 0。

## Definition of Done

- [ ] 系統明確承認 E/B 是兩個獨立 Top 50 榜單。
- [ ] absent metric 永不自動轉 0。
- [ ] observed、estimated、unavailable 全鏈路可追蹤。
- [ ] 不可用事件只排除自身，不污染整個股票 aggregation。
- [ ] 估算值不寫回真實來源欄位。
- [ ] 分數與 confidence 依資料覆蓋率治理。
- [ ] 狀態卡與 QA 顯示真實 158 天及 metric coverage。
- [ ] 正式效能數字區分冷載入與快取。
