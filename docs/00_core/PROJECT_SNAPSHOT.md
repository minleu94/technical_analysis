# PROJECT_SNAPSHOT（必讀｜每次開新對話先看）

> **開場 30 秒內讀完** - 只放今天的狀態，不放歷史細節

## 系統定位（一句話）

這不是每天吐股票的工具，而是一個可驗證、可回溯、可演化的投資決策系統。

## 當前狀態（以 DEVELOPMENT_ROADMAP.md 的 Living Section 為準）

> **注意**：Living Section 定義見 `DEVELOPMENT_ROADMAP.md` 的「📍 Living Section 定義」段落。

- Phase 1 ✅ / Phase 2 ✅ / Phase 2.5 ✅（核心已完成並驗證）
- Phase 3.1 ✅ / Phase 3.2 ✅ / Phase 3.3b ✅（研究閉環已完成，含 Promote / Walk-forward / Baseline / Overfitting risk / 視覺驗證）
- AI Runtime Subsystem MVP ✅（Governance-aware 狀態機監控站已完成）
- Smart Money Terminal MVP ✅（高密度、低延遲的專業級籌碼分析終端已完成）
- UI Qt Backtest chart renderer ✅（QtWebEngine + HTML5 Canvas fast renderer 已完成，Matplotlib fallback 保留）
- Recommendation Portfolio Backtest MVP ✅（推薦 Profile/Config 可在歷史日期重播，回測整組推薦組合績效與個股貢獻）
- 數據更新工作台 ✅（`UpdateView` 已整理為左側導覽維運工作台，新增「安全更新所有數據」日常維護入口）
- Codex / Agent 指引 ✅（repo 根目錄 `AGENTS.md` 已建立，`docs/agents/` 已對齊目前 `ui_qt`、資料根目錄與文檔路徑）
- Phase 4.1 Portfolio MVP 🚧（service/domain/test 骨架已開始；`ui_qt` Portfolio Tab 與 Phase 3 → Portfolio 整合尚未完成）

## 現在的工作模式（你每天要用的流程）

1. Update 使用「安全更新所有數據」或左側資料來源頁更新資料
2. Market Watch 看 Regime + 強弱
3. Recommendation 用 Profile 出名單 + 看 Why/WhyNot → 丟 Watchlist，或送「推薦組合回測」
4. Backtest 可跑 Watchlist/現有名單批次回測，也可用歷史重播推薦邏輯評估整組推薦組合

## Tech Lead 的預設任務（開場要先做什麼）

- 給出「下一步最合理的工程行動」與原因（不寫 code）
- 如需看程式碼：先提出要 review 的檔案清單與目的，等我授權 scope

## 本週優先事項（只列 3 個）

1. 補強推薦組合回測的穩健分析指標（Sortino、Sharpe、Monte Carlo）與結果可讀性
2. 評估將回測最佳 Profile/Config 回灌推薦頁，形成可優化的推薦系統
3. 保持 Roadmap / Snapshot / Documentation Index / UI docs / Agent docs 一致

## 高風險區（改動需謹慎）

- `app_module/backtest_service.py` / `backtest_module/*`
- `app_module/recommendation_service.py`
- `app_module/recommendation_replay_service.py` / `app_module/recommendation_portfolio_backtest_service.py`
- Strategy registry / preset / promotion 相關服務
- UI ↔ service contract（DTO）
- `runtime/` 核心子系統與 FSM 狀態機
- `ui_qt/widgets/fast_chart_widget.py` / `ui_qt/widgets/chart_payloads.py`（回測圖表 renderer 與資料 payload contract）
- `ui_qt/views/update_view.py` / `app_module/update_service.py`（數據更新工作台與安全更新流程）

## 指定權威文件（需要細節再看）

- `DEVELOPMENT_ROADMAP.md` - 完整開發路線圖（Single Source of Truth）
- `DOCUMENTATION_INDEX.md` - 文檔索引
- `DOCUMENTATION_STRUCTURE.md` - docs 資料夾歸屬、生命週期、刪除/歸檔規則
- `DOC_COVERAGE_MAP.md` - 文檔覆蓋矩陣（Documentation Agent 判斷 coverage 的規則）
- `PROJECT_NAVIGATION.md` / `PROJECT_INVENTORY.md` - 專案導航與盤點

---

**注意**：此 Snapshot 內容從 `DEVELOPMENT_ROADMAP.md` 的「Living Section」（定義見該文件的「📍 Living Section 定義」段落）與 `DOCUMENTATION_INDEX.md` 抽出的短版入口。詳細資訊請參考權威文件。

