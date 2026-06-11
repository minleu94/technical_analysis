# 下一步行動計畫

> 建立日期：2026-06-09  
> 用途：給使用者與後續 Agent 的交接文件。若本文件與 `DEVELOPMENT_ROADMAP.md` 衝突，以 Roadmap Living Section 為準，但本文件指出下一輪應如何重整 Roadmap。

---

## 1. Tech Lead 結論

不要先把舊 Phase 1-5 全部走完。

目前專案已經超出早期線性 Phase 規劃，實際產品主線已成為三個閉環：

1. 資料與市場狀態閉環：Update → SQLite 狀態 → Market Watch / Smart Money → 候選池。
2. 研究驗證閉環：Recommendation Profile → Research Lab / Backtest / Replay / Walk-forward → Promote。
3. 持倉檢查閉環：Recommendation / Backtest → Portfolio → Condition Monitor → Journal → 回到研究。

因此下一步應先做 Roadmap Rebaseline，把「實際產品形狀、目前風險、下一輪優先級」重新寫清楚，再繼續新增功能。

---

## 2. 目前真實狀態

### 已完成或已進入 MVP

- Phase 1 到 Phase 3.3b 主要功能已完成。
- Runtime Observatory MVP 已完成，作為治理與狀態觀察入口，不是自動 Agent router。
- Smart Money Terminal MVP 已完成，已能承接 Market Watch 與候選池。
- Research Lab 已從單股回測頁擴展為多模式研究實驗室。
- Recommendation Portfolio Backtest MVP 已完成，支援推薦組合歷史回放、績效、交易紀錄、保存與 Promote。
- Portfolio Tab 已建立，支援交易記錄、交易歷史、覆盤日誌、positions projection、Recommendation / Backtest 來源追溯 metadata。
- PortfolioConditionMonitor 已接入，可比對來源快照與目前快照，顯示仍符合、需要留意、假設失效或來源不足。

### 尚未完成的 Phase 4.1 深化

- Portfolio 策略版本追蹤視圖。
- Portfolio Price 對照。
- 持倉層風險提示。
- Smart Money 下鑽到持倉。

### 舊 Phase 中部分已提前完成

- Phase 5 的 Backtest chart fast renderer 已完成：QtWebEngine + HTML5 Canvas fast renderer，Matplotlib fallback 保留。

### 舊 Phase 中仍未完成但不應立刻插隊

- 大表格分頁。
- 批次回測並行化。
- Excel / PDF 研究報告輸出。

這些可以保留為後續 Track，但目前不應優先於回測時間軸與文件 rebaseline。

---

## 3. 下一輪最高優先順序

### P0：Roadmap Rebaseline

目標：讓所有後續 Agent 讀到一致的專案方向。

需要完成：

1. 將 Roadmap 從舊線性 Phase 敘事改為「產品閉環 / Track」敘事。
2. 保留 Phase 1-3.3b 作為歷史 Done。
3. 將 Phase 4.1 定義為「Portfolio MVP 已建立，深化仍在進行」。
4. 將 Phase 5 拆成已完成與未完成項，不要整段標成待開始。
5. 清理 Next，只保留真正下一步：
   - 回測時間軸契約與 no-look-ahead 測試。
   - 金融核心數值治理。
   - Portfolio 策略版本追蹤。
   - Price 對照。
   - 持倉層風險提示。
6. Blockers / Risks 必須對齊 `PROJECT_SNAPSHOT.md` 的高風險區。

### P0：回測時間軸契約治理

目標：先定義「訊號日、資料可得日、成交日、成交價、停損停利、equity curve 記錄日」的統一契約。

狀態（2026-06-10）：初版已完成。`BrokerSimulator next_open` 帳務錯位已修正；`close` 模式與推薦組合回測同日收盤成交假設已加入 warning / metadata；已新增 timeline contract 測試。

優先檢查：

- `app_module/recommendation_portfolio_backtest_service.py`
- `app_module/recommendation_replay_service.py`
- `app_module/recommendation_dataframe_provider.py`
- `app_module/recommendation_service.py`
- `backtest_module/broker_simulator.py`
- `backtest_module/performance_metrics.py`

必要測試：

- 推薦 replay 不可使用未來資料。
- 推薦組合回測不可同日收盤訊號同日收盤成交，除非明確標註為不可實盤假設。
- 單股回測 `next_open` 的成交日與 equity curve 記錄日必須一致。
- `execution_price="close"` 必須禁止、警示，或明確標成研究假設。
- benchmark 對齊不可使用決策日之後資料。

### P0：金融核心數值治理 ✅ 已完成

目標：停止在金融核心新增裸 `float`，並規劃既有裸 `float` 遷移。

狀態（2026-06-11）：核心金額與 float 邊界治理已全部完成。
- 已新增 `financial_module/units.py` 並將手續費、滑價、稅率等轉為 Decimal/整數/基點處理。
- 已實施金融核心白名單（6 個核心檔案）的 `float()`、`.astype(float)`、`dtype=float` 防回歸靜態掃描器（`check_financial_float_boundaries.py`）。
- 成功為所有白名單檔案的 float 轉換加入 `dto` / `analytics` / `visualization` 的 `# numeric-boundary:` 行尾註解。
- 建立 pytest repository gate（`test_financial_core_allowlist_has_no_unmarked_float_boundaries`）自動阻擋任何未標記的 float 邊界。

優先範圍：

- `backtest_module/broker_simulator.py`
- `backtest_module/performance_metrics.py`（核心交易損益已遷移，Sharpe / annualized return 屬 analytics 邊界）
- `app_module/recommendation_portfolio_backtest_service.py`（推薦組合 PnL / mark-to-market PnL 已遷移，同日收盤成交假設仍以 warning / metadata 揭露）
- `portfolio_module/core.py`
- `app_module/portfolio_service.py`（Portfolio summary 金額加總已遷移）

原則：

- 金額使用 Decimal 或整數分。
- 股數使用整數或明確的小數股單位。
- 費率、滑價、稅率使用整數基點或 Decimal。
- 視覺化與 pandas 統計可以在明確隔離邊界轉成 float，但不可回流核心計算。

---

## 4. 需要同步修正的文件

### Must

| 文件 | 修正重點 |
|---|---|
| `docs/00_core/DEVELOPMENT_ROADMAP.md` | Rebaseline Living Section、Next、Risks；移除已完成項目對 Next 的干擾。 |
| `docs/00_core/PROJECT_SNAPSHOT.md` | 對齊 Roadmap Rebaseline 後的目前狀態、本週優先事項、高風險區。 |
| `docs/00_core/AI_CONTEXT_PACK.md` | 移除「即將邁入 Phase 4」、固定 4 Tab、Portfolio UI 未完成等過期敘述。 |
| `PROJECT_NAVIGATION.md` | 更新 Portfolio、Research Lab、Runtime、服務對應與入口狀態。 |
| `PROJECT_INVENTORY.md` | 更新 Portfolio UI、來源追溯、條件監控、Research Lab 真實完成狀態。 |

### Should

| 文件 | 修正重點 |
|---|---|
| `docs/01_architecture/system_architecture.md` | 從舊 Phase 3.3b / Phase 4 未完成敘事改成目前分層與產品閉環。 |
| `docs/02_features/UI_FEATURES_DOCUMENTATION.md` | 補 Portfolio Tab、Runtime、Research Lab、Smart Money 現況；移除內部矛盾。 |
| `docs/02_features/BACKTEST_LAB_FEATURES.md` | 統一 Sortino / Sharpe / Monte Carlo 已完成或後續深化的描述。 |
| `docs/02_features/BACKTEST_LAB_CHECKLIST.md` | 移除「待補 Sortino / Sharpe / Monte Carlo」與後段已完成文字的矛盾。 |
| `docs/00_core/DOCUMENTATION_INDEX.md` | 補入新增或漏列的重要治理、spec、plan 文件。 |

### Nice-to-have

| 文件 | 修正重點 |
|---|---|
| `app_module/README.md` | 更新 BacktestReportDTO、Portfolio、Research Lab 現況。 |
| `ui_qt/README.md` | 更新 Portfolio Tab 已完成、Runtime Observatory、實際主入口。 |
| `docs/01_architecture/data_collection_architecture.md` | 移除 CSV-only 或 repo `data/` 舊敘事。 |
| `docs/03_data/DATA_FLOW_LOGIC.md` | 對齊 SQLite DB-first + CSV fallback contract。 |

---

## 5. 不建議現在做的事

- 不要直接開發新的大型功能，例如新因子、ML 模型、自動交易、報告輸出。
- 不要先補完舊 Phase 5 報告輸出，再處理回測時間軸。
- 不要在未定義成交契約前擴大推薦組合回測功能。
- 不要刪除 legacy 模組，除非先做 cleanup plan、影響盤點與 rollback 清單。
- 不要把 QA output、暫存檔、本機資料庫或資料根目錄內容順手提交。

---

## 6. 建議分支與 commit 順序

### 分支 1：文件與方向重整

建議分支：

```powershell
git checkout -b codex/rebaseline-roadmap-architecture
```

建議 commit：

```text
docs: rebaseline roadmap and architecture status
```

範圍：

- Roadmap Living Section。
- Snapshot。
- AI Context Pack。
- Project Navigation。
- Project Inventory。
- Documentation Index。
- UI / architecture secondary docs。

### 分支 2：回測時間軸治理

建議分支：

```powershell
git checkout -b codex/backtest-timeline-contract
```

建議 commit：

```text
test: define no-look-ahead backtest timeline contract
```

第一步先加測試，不急著大改實作。

### 分支 3：金融核心數值治理

建議分支：

```powershell
git checkout -b codex/financial-numeric-governance
```

建議 commit：

```text
refactor: introduce financial numeric governance boundaries
```

第一步先建立 helper / policy / tests，再逐步遷移高風險核心。

---

## 7. 給下一位 Agent 的直接任務

請先閱讀：

1. `AGENTS.md`
2. `docs/agents/README.md`
3. `docs/agents/shared_context.md`
4. `docs/agents/git_exclusions.md`
5. `docs/00_core/PROJECT_SNAPSHOT.md`
6. `docs/00_core/DEVELOPMENT_ROADMAP.md`
7. `docs/00_core/NEXT_ACTION_PLAN.md`
8. `docs/agents/tech_lead.md`
9. 若要改文件，再讀 `docs/agents/documentation_agent.md` 與 `docs/00_core/DOC_COVERAGE_MAP.md`

接著執行：

1. 做 Roadmap Rebaseline，不新增功能。
2. 將 Snapshot / Index / Navigation / Inventory / AI Context Pack 對齊。
3. 清理 UI / Architecture / Backtest feature docs 的過期敘述。
4. Commit 文件重整。
5. 再開始回測時間軸契約測試。

---

## 8. 驗證要求

文件重整後：

```powershell
git status --short
```

如果只改 Markdown：

- 不需要跑完整 UI 測試。
- 需要人工檢查 Roadmap / Snapshot / Index / Navigation 是否互相一致。
- 若新增或刪除 Markdown，必須更新 `docs/00_core/DOCUMENTATION_INDEX.md`。

若後續修改 Python：

```powershell
.\.venv\Scripts\python.exe -m py_compile <changed-python-files>
```

若修改 UI：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

---

## 9. 一句話版本

先不要補舊 Phase。先把專案重新定義成「資料治理、研究驗證、持倉監控」三個產品閉環，接著優先修回測時間軸與金融核心數值治理，最後再繼續 Portfolio 深化與報告輸出。
