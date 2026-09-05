# 專案盤點報告

> **最後整理**：2026-08-30
> **用途**：提供根目錄層級的目前結構盤點。細節文件以 `docs/00_core/DOCUMENTATION_INDEX.md` 為準。
>
> **目前程式盤點**：七個 readiness lane、已完成工程、未完成產品 Gate 與推進順序見
> `docs/06_qa/PROGRAM_STATUS_REBASELINE_2026_08_29.md`。2026-08-29 的
> `FA_Data/output/release_v4` retention 行為、43 個刪除目標、18 個 retained runs、pointer
> 與歷史 tombstone 見
> `docs/06_qa/ML_RELEASE_V4_STORAGE_RETENTION_CLEANUP_2026_08_29.md`；8/30 P0 官方唯讀
> refresh 見 `docs/06_qa/P0_EVIDENCE_REFRESH_2026_08_30.md`；raw data 未納入清理。

---

## 1. 根目錄應保留文件

| 文件 | 角色 | 狀態 |
|---|---|---|
| `README.md` | 使用者導向專案入口、啟動方式、功能概覽與分支策略 | Active |
| `AGENT_CONTEXT.md` | Agent / 開發者快速上下文，補充文件權威、分支策略與接手導覽 | Active |
| `PROJECT_NAVIGATION.md` | 開發者導航，回答「我要改 X 要去哪裡」 | Active |
| `PROJECT_INVENTORY.md` | 本文件，專案結構盤點摘要 | Active |
| `AGENTS.md` | Codex 自動讀取的 repo 指令入口，導向 `docs/agents/` 完整 Agent 架構 | Active |
| `GEMINI.md` | Antigravity 自動讀取的 repo 指令入口，導向 `docs/agents/antigravity/` 與 `.agent/rules/` | Active |
| `requirements.txt` | Python 依賴 | Active |

已移出或刪除：

- `CLEANUP_PLAN.md`：舊清理計劃，內容已執行或被新版 docs 結構取代，已刪除。
- `策略回測功能清單.md`：已移至 `docs/02_features/BACKTEST_LAB_CHECKLIST.md`。
- `策略回測常見問題解答.md`：已移至 `docs/02_features/BACKTEST_LAB_FAQ.md`。
- `01_stock_data_collector_enhanced.py`：舊 notebook 匯出參考腳本，已刪除；正式資料處理請看 `data_module/` 與 `scripts/update_all_data.py`。
- `tests/test_finmind_integration.py`：只測舊參考腳本且依賴外部 FinMind token，已刪除。
- `readme.txt`：原根目錄長版舊 README，內容停留在舊 Phase、舊入口與舊路徑說明；2026-06-18 已移至 `docs/09_archive/root_readme_legacy_2025_12.txt`。
- `docs/00_core/note.txt`：歷史開發進度筆記，已於 2026-06-30 移至 `docs/09_archive/dev_progress_note_legacy_2026_01.txt`，不再作為核心權威文件。
- `output/` 與根目錄 `test.parquet`：本機 QA / 驗證 / 測試產物，已從乾淨 `main` 移出 Git 追蹤；可分享結論請整理到 `docs/06_qa/`。

---

## 2. 核心模組

| 目錄 | 角色 | 狀態 |
|---|---|---|
| `data_module/` | `TWStockConfig`、資料載入、日期範圍與資料處理 | Active |
| `analysis_module/` | 技術分析、型態、信號、ML 分析 | Active |
| `decision_module/` | Domain Layer：篩選、打分、推薦理由、Regime、籌碼信號 | Active |
| `app_module/` | Application Service Layer：推薦、回測、資料更新、Runtime、Portfolio services | Active |
| `backtest_module/` | 策略測試、績效分析、交易模擬與風險指標 | Active |
| `portfolio_module/` | Portfolio domain layer（append-only trades、positions projection、Decimal 邊界） | Active |
| `runtime/` | Governance-aware AI Runtime、event/store/state/registry | Active |

---

## 3. UI 與入口

| 目錄 | 角色 | 狀態 |
|---|---|---|
| `ui_qt/` | PySide6 Qt UI，目前主要入口 | Active |
| `ui_app/` | 舊版 Tkinter UI | Legacy |
| `examples/` | 範例與舊示範 | Reference |

主要啟動方式：

```bash
.\.venv\Scripts\python.exe ui_qt\main.py
```

目前 `ui_qt` 近期狀態：

- 8 個頂層工作區：決策工作台、市場探索（市場總覽／每日決策唯一實例與主力流向等子頁）、推薦分析、策略回測（Research Lab）、觀察清單、持倉管理、數據更新、Runtime。
- `ui_qt/views/update_view.py` 已重整為數據更新工作台，包含左側資料來源導覽與「安全更新所有數據」入口。
- `ui_qt/views/runtime_view.py` 與 `runtime/` 已完成 Runtime Observatory MVP。
- `ui_qt` 主 UI 已接上 Daily Decision Desk v1，透過 service snapshot 顯示 Market Breadth、Sector Rotation、Relative Strength / Liquidity Ranking、Watchlist Trigger、Portfolio Alert 與 fundamental risk prompts。
- `ui_qt/views/portfolio_view.py`：Portfolio Tab 已建立，含策略與價格監控、生命週期回顧、未實現損益、停損停利警示、籌碼監控與 Smart Money 下鑽。
- 策略回測頁已整理為 Research Lab 多模式實驗室語意。

回測圖表渲染：

- `ui_qt/widgets/chart_payloads.py`：Backtest 圖表資料 payload layer。
- `ui_qt/widgets/fast_chart_widget.py`：QtWebEngine + HTML5 Canvas fast renderer。
- `ui_qt/widgets/chart_widget.py`：Matplotlib fallback widgets。
- 架構說明：`docs/08_technical/UI_QT_CHART_RENDERING.md`。

---

## 4. 文件系統

| 目錄 | 角色 |
|---|---|
| `docs/00_core/` | snapshot、6 個月 roadmap、Roadmap Hub、文件索引與維護規則 |
| `docs/01_architecture/` | 架構與流程 |
| `docs/02_features/` | 使用者可見功能與策略回測文件 |
| `docs/03_data/` | 資料更新、資料流與故障排除 |
| `docs/04_broker_branch/` | 券商分點與 Smart Money 資料 |
| `docs/05_phases/` | 歷史 Phase 設計與研究 SOP 追溯；Historical / Reference，不作目前 roadmap |
| `docs/06_qa/` | QA 問題、總結與審核 |
| `docs/07_guides/` | 快速開始、安裝、腳本與測試 |
| `docs/08_technical/` | 技術優化與環境備忘 |
| `docs/09_archive/` | 歷史文件，不作目前狀態依據 |
| `docs/agents/` | Agent 職責與協作規範 |
| `docs/strategies/` | 策略說明 |
| `docs/superpowers/` | Superpowers specs / plans implementation trace，不作目前 roadmap |

文件入口：

- `docs/README.md`
- `README.md`
- `AGENT_CONTEXT.md`
- `docs/00_core/DEVELOPMENT_ROADMAP.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`
- `docs/00_core/EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md`
- `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/00_core/DOCUMENTATION_STRUCTURE.md`
- `docs/07_guides/APPLICATION_MANUAL.md`

---

## 5. 目前開發主線

專案已形成四個可操作產品閉環：資料與市場狀態 ✅、研究驗證 ✅、持倉檢查 ✅、每日決策 ✅。V1 release baseline 已完成，V1 的意義是工程入口、資料契約、操作流程與 release gate 可用，不代表投資有效性。

- Strategy & Scoring Governance 增量 A / B 與 10 檔 fixed / quantile OOS 實證已完成；quantile 未優於 fixed，維持 opt-in。
- Phase 5 圖表渲染、批次並行化、SQLite 穩定分頁與規格化 Excel 報告匯出已完成；PDF 報告輸出仍在後續 backlog。
- Month 2 Research Run Registry、Cross-run Comparison 與 Registry-based Promote Gate 已完成 final governance gate；Month 3 Factor Layer / Portfolio Replay 可信度與 Month 5 Fundamental Layer v1 已關閉。Month 6 Strategy Lifecycle / Portfolio Feedback v1 已落地 lifecycle gate、append-only lifecycle evidence、current state projection、drift detector、Portfolio feedback attribution、Portfolio Review snapshot 與持倉管理生命週期回顧分頁。
- Post-V1 V1.1 至 V1.9 v1 已完成，包含 workflow bridge、research credibility、weekly evidence operations、evidence review history、data credibility gate、cross-sectional factor snapshot、negative evidence、portfolio sandbox 與 read-only Agent / MCP。
- V3.3 engineering foundation 與 Workbench 主 UI 已 closeout；目前是 V4 evidence accumulation，而不是正式 V4.0。七個 current lane 中 Update History 最近觀測為 ready，Runtime 已有 TEMP transaction probe 但正式 Registry canary 仍待核准；P0 acceptance、Evidence formal credit、Paper fills／成本、Formal inputs 與 production canary 仍未完成。8/30 fresh capacity inventory 為 `headroom_ok`（約 338.9 GiB），但不改上述 Gate；Data Update timeline 與舊 readiness artifact 顯示邊界已補上 regression。
- `docs/05_phases/` 保留為 Historical / Reference；Phase 文件內的下一步或 Gate 不作目前 roadmap 判斷。

目前狀態以 `docs/00_core/PROJECT_SNAPSHOT.md` 為準；未來 6 個月路線以 `docs/00_core/ROADMAP_6M_ENGINEERING.md` 為準；V2.0 之後長期版號階梯以 `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md` 為準；舊 Roadmap 未完成事項是否已承接，以 `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md` 為準。

## 6. 更新記錄

- 2026-08-30：完成 P0／Evidence／Paper／Formal／Runtime／Performance／Data Update refresh；整理 current SSOT、8/30 fresh capacity、週末 freshness 語意、舊 readiness artifact marker 與完整 pytest `3,826 passed / 1 skipped`。
- 2026-08-29：依全程式 rebaseline 校正八個工作區名稱與目前主線；新增七個 readiness lane、release_v4 retention cleanup 與容量不等於 Gate closeout 的邊界。
- 2026-07-06：補上 V2.1 至 V4.0 長期版本路線圖入口，並同步 Post-V1 V1.7-V1.9、V2.0 Phase 1 與後續 gate-based 主線描述。
- 2026-07-05：同步 Post-V1 V1.5 / V1.6 v1 完成狀態，新增 data credibility gate 與 cross-sectional factor pipeline closeout，下一步改為 V1.7 Negative Evidence。
- 2026-07-03：同步 Post-V1 V1.1 至 V1.4 v1 完成狀態，並將 `docs/05_phases/` 定位改為 Historical / Reference。
- 2026-06-30：將根目錄 `README.md` 改為使用者導向入口，新增 `AGENT_CONTEXT.md` 承接 Agent / 開發者上下文；將歷史 `docs/00_core/note.txt` 歸檔，並將 `output/` raw output 從乾淨 `main` 移出追蹤。
- 2026-06-18：整理根目錄 README 入口，將過期 `readme.txt` 移入 `docs/09_archive/root_readme_legacy_2025_12.txt`，並同步 docs 索引。
- 2026-06-17：同步 Month 5 Fundamental Layer v1 closeout 與 Daily Decision Desk v1 主 UI 狀態，將目前主線轉向 Month 6 Strategy Lifecycle / Portfolio Feedback scope。
- 2026-06-17：同步 Month 6 Strategy Lifecycle / Portfolio Feedback v1，新增 lifecycle gate、post-trade attribution 與持倉管理生命週期回顧入口。
- 2026-06-17：同步 Month 6 lifecycle residual，新增 append-only evidence、latest state projection 與 demote / retire proposed evidence 保存。
- 2026-06-15：同步 baldr 願景與新版 6M Roadmap，標示 Daily Decision Desk 為未完成目標閉環，並更新未來主線排序。
