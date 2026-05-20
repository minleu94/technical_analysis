# 專案盤點報告

> **最後整理**：2026-05-20
> **用途**：提供根目錄層級的目前結構盤點。細節文件以 `docs/00_core/DOCUMENTATION_INDEX.md` 為準。

---

## 1. 根目錄應保留文件

| 文件 | 角色 | 狀態 |
|---|---|---|
| `README.md` | 專案最短入口、啟動方式、目前主線 | Active |
| `PROJECT_NAVIGATION.md` | 開發者導航，回答「我要改 X 要去哪裡」 | Active |
| `PROJECT_INVENTORY.md` | 本文件，專案結構盤點摘要 | Active |
| `AGENTS.md` | Codex 自動讀取的 repo 指令入口，導向 `docs/agents/` 完整 Agent 架構 | Active |
| `requirements.txt` | Python 依賴 | Active |

已移出或刪除：

- `CLEANUP_PLAN.md`：舊清理計劃，內容已執行或被新版 docs 結構取代，已刪除。
- `策略回測功能清單.md`：已移至 `docs/02_features/BACKTEST_LAB_CHECKLIST.md`。
- `策略回測常見問題解答.md`：已移至 `docs/02_features/BACKTEST_LAB_FAQ.md`。
- `01_stock_data_collector_enhanced.py`：舊 notebook 匯出參考腳本，已刪除；正式資料處理請看 `data_module/` 與 `scripts/update_all_data.py`。
- `tests/test_finmind_integration.py`：只測舊參考腳本且依賴外部 FinMind token，已刪除。

---

## 2. 核心模組

| 目錄 | 角色 | 狀態 |
|---|---|---|
| `data_module/` | `TWStockConfig`、資料載入、日期範圍與資料處理 | Active |
| `analysis_module/` | 技術分析、型態、信號、ML 分析 | Active |
| `decision_module/` | Domain Layer：篩選、打分、推薦理由、Regime、籌碼信號 | Active |
| `app_module/` | Application Service Layer：推薦、回測、資料更新、Runtime、Portfolio services | Active |
| `backtest_module/` | 策略測試、績效分析、交易模擬與風險指標 | Active |
| `portfolio_module/` | Phase 4.1 Portfolio MVP domain layer | In Progress |
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
python ui_qt/main.py
```

目前 `ui_qt` 近期狀態：

- `ui_qt/views/update_view.py` 已重整為數據更新工作台，包含左側資料來源導覽與「安全更新所有數據」入口。
- `ui_qt/views/runtime_view.py` 與 `runtime/` 已完成 Runtime Observatory MVP。
- Portfolio 使用者可見 Tab 尚未完成，仍屬 Phase 4.1 下一步。

回測圖表渲染：

- `ui_qt/widgets/chart_payloads.py`：Backtest 圖表資料 payload layer。
- `ui_qt/widgets/fast_chart_widget.py`：QtWebEngine + HTML5 Canvas fast renderer。
- `ui_qt/widgets/chart_widget.py`：Matplotlib fallback widgets。
- 架構說明：`docs/08_technical/UI_QT_CHART_RENDERING.md`。

---

## 4. 文件系統

| 目錄 | 角色 |
|---|---|
| `docs/00_core/` | roadmap、snapshot、文件索引與維護規則 |
| `docs/01_architecture/` | 架構與流程 |
| `docs/02_features/` | 使用者可見功能與策略回測文件 |
| `docs/03_data/` | 資料更新、資料流與故障排除 |
| `docs/04_broker_branch/` | 券商分點與 Smart Money 資料 |
| `docs/05_phases/` | Phase 設計與研究 SOP |
| `docs/06_qa/` | QA 問題、總結與審核 |
| `docs/07_guides/` | 快速開始、安裝、腳本與測試 |
| `docs/08_technical/` | 技術優化與環境備忘 |
| `docs/09_archive/` | 歷史文件，不作目前狀態依據 |
| `docs/agents/` | Agent 職責與協作規範 |
| `docs/strategies/` | 策略說明 |

文件入口：

- `docs/README.md`
- `docs/00_core/DEVELOPMENT_ROADMAP.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/00_core/DOCUMENTATION_STRUCTURE.md`

---

## 5. 目前開發主線

- Phase 3.3b 已完成。
- Phase 4.1 Portfolio MVP 已開始。
- Portfolio domain / service / test skeleton 已存在。
- 待完成：`ui_qt` Portfolio Tab、Recommendation/Backtest → Portfolio 來源追蹤、持倉條件監控。

詳細狀態以 `docs/00_core/DEVELOPMENT_ROADMAP.md` 的 Living Section 為準。
