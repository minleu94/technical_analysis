# Broker Flow Dual Metric Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 MoneyDJ 券商分點資料改為同時抓取張數 `c=E` 與金額 `c=B`，並確保 Phase 4.2 只以張數進行籌碼判斷。

**Architecture:** 每個分點與交易日分別取得兩種指標，以股票代碼及買賣超方向合併為單一事件。CSV 儲存明確的 `*_lots` 與 `*_amount_k_twd` 欄位；SQLite 保留既有股數欄位作相容介面，並新增仟元金額欄位。沒有明確張數欄位的舊資料視為 legacy amount，不得進入籌碼判斷。

**Tech Stack:** Python、pandas、BeautifulSoup、Selenium、SQLite、pytest

---

### Task 1: 鎖定 MoneyDJ 指標契約

**Files:**
- Modify: `tests/test_broker_branch_decode.py`
- Modify: `app_module/broker_branch_update_service.py`

- [ ] 新增 URL 測試，驗證 `metric="lots"` 產生 `c=E`，`metric="amount"` 產生 `c=B`。
- [ ] 新增 E/B 記錄合併測試，驗證同股票資料寫入 `buy_lots` 與 `buy_amount_k_twd`。
- [ ] 執行測試並確認因功能尚未實作而失敗。
- [ ] 實作 URL 指標與合併 helper。
- [ ] 重跑測試至通過。

### Task 2: 雙指標下載與 CSV 契約

**Files:**
- Modify: `app_module/broker_branch_update_service.py`
- Test: `tests/test_broker_branch_decode.py`

- [ ] 新增 HTML 表格解析測試，分別辨認張數與仟元標題。
- [ ] 實作每日期 E/B 雙抓取，任一指標失敗時不寫入不完整檔案。
- [ ] 每日與 merged CSV 寫入明確欄位，去重鍵維持日期、方向與股票代碼。
- [ ] 驗證空資料檔也包含完整的新欄位表頭。

### Task 3: SQLite 與分析讀取邊界

**Files:**
- Modify: `data_module/db_manager.py`
- Modify: `app_module/update_service.py`
- Modify: `app_module/broker_flow_service.py`
- Modify: `app_module/portfolio_chip_service.py`
- Test: `tests/test_update_service_status.py`
- Test: `tests/test_portfolio_chip_monitor.py`

- [ ] 新增測試，證明 `buy_lots=600` 轉為 SQLite `買進股數=600000`。
- [ ] 新增測試，證明只有舊 `buy_qty` 的 B 資料不會被當成張數。
- [ ] SQLite 新增買進、賣出、買賣超金額千元欄位。
- [ ] BrokerFlowService 只讀明確的 lot 欄位。
- [ ] PortfolioChipService 維持股數門檻，CSV 與 SQLite 結果一致。

### Task 4: a577f4f 更新流程回歸

**Files:**
- Modify: `tests/test_broker_branch_decode.py`
- Modify: `tests/test_ui_qt_update_view_workbench.py` if required
- Modify: `app_module/broker_branch_update_service.py`

- [ ] 驗證長碼解密與總公司判定仍通過。
- [ ] 驗證已有舊 B 檔案時不會誤判為完整 E+B 而跳過。
- [ ] 驗證快速更新與安全更新取得相同雙指標欄位。

### Task 5: 文件與完整驗證

**Files:**
- Modify: `docs/01_architecture/data_collection_architecture.md`
- Modify: `docs/03_data/DATA_FETCHING_LOGIC.md`
- Modify: `docs/03_data/daily_data_update_guide.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/02_features/UI_FEATURES_DOCUMENTATION.md`
- Modify: `docs/02_features/USER_GUIDE.md`
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`

- [ ] 記錄 `E=張數`、`B=仟元` 與 legacy 資料限制。
- [ ] 執行相關 pytest、UI workbench、QA、mypy 與 py_compile。
- [ ] 比對工作樹，確認沒有覆寫其他未提交變更或正式資料。
