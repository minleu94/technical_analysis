# LUNA C 投資研究 UI／UX 交接

## 1. 交付摘要

- 工作線：LUNA C／投資研究 UI／UX。
- 執行日期：2026-09-08（沿用工作線日期標籤 `2026-09-07`）。
- 分支：`codex/luna-c-uiux`。
- 交付：本文件與程式已在本分支單一 C commit；實際 hash 以 `git rev-parse HEAD` 為準（避免在 commit 內嵌自我雜湊）。
- 基線：`71500ef6fc834da285c19255e5c03f1846412329`；工作樹原先已有 A／B 整併的未提交變更，本工作線未重置、覆寫或整批清理。
- 所有資料根目錄、輸出根目錄與暫存根目錄均指向 `output/luna_C/` 下的合成／隔離路徑；未連接真實交易、未啟用 scheduler、未寫正式資料或 promotion。
- 交付檔：本文件與 `output/luna_C/manifest.json`；raw screenshots、QA logs 與隔離資料均不納入 Git。

本輪已達 UI 驗收：日常研究者可從資料狀態、研究 context、理由／反對證據、比較假設與 Portfolio scope 取得下一步；窄版不再把主要內容藏在右側 split pane。計算、查 DB、動態掃來源與風險 policy 仍留在既有 service／DTO 邊界。

## 2. C1 基線與 Workbench 契約

### 實際 UI 基線

使用真實 `MainWindow`、左側 8 工作區導覽與 `Qt offscreen` 實際抓圖；requested／actual／DPR 由 evidence JSON 記錄，不以 QSS 靜態閱讀代替畫面驗收。

| 項目 | 實測結果 |
|---|---|
| Desktop requested | `1366×768` |
| Narrow requested | `390×844` |
| final flow actual | Workbench／Recommendation／Backtest／Portfolio／Update 均分別為 `1366×768` 與 `390×844` |
| DPR | `1.0`（offscreen；未宣稱 Windows 150%／200% 實體螢幕外觀） |
| full smoke | 8／8 workspace 可切換，兩個 viewport `matched`，無 forbidden action |

Baseline flow screenshots 位於：

- `output/luna_C/before_1366/before_*_1366x768.png`
- `output/luna_C/before_390/before_*_390x844.png`

Final flow screenshots 位於：

- `output/luna_C/final3_1366/final3_*_1366x768.png`
- `output/luna_C/final3_390/final3_*_390x844.png`

本機 offscreen 的 default capture 曾沒有載入中文字型，故 baseline flow 圖有 glyph fallback；final3 capture 已呼叫既有 `apply_app_theme`，full healthcheck 亦使用同一套 theme。比較重點是實際重排、可見操作與 viewport 尺寸；中文字型仍需在 Windows 實機確認。

### 三項失敗的契約重現與責任判定

執行前以隔離 interpreter 重跑 `tests/test_workbench_source_service.py`，得到 `2 passed / 3 failed`：

1. read-only source status 預期為 passed，但 fixture 未建立 `scheduled/data_freshness/latest_status.json`；`ScheduledEvidenceStatusService` 正確採保守 `source_missing`，責任在不完整 fixture，不在 source service。
2. 未來 snapshot warning 已由 source service 產生 `decision_desk_snapshot_future_date...`，但 composer 沒把明示 source diagnostic 投影成可讀 review item；責任在 composer contract。
3. snapshot table 缺失同樣已有 `decision_desk_snapshots_table_missing`，但沒有 `readiness_source_gaps` 審查項；責任仍在 composer projection，不是用改 expected value 遮蔽。

處置：補上 synthetic freshness fixture；`WorkbenchReadOnlyComposer` 只將明示 `decision_desk_snapshot*` diagnostic 映射為 `readiness_source_gaps` warning／`evidence_mode` 下鑽，保留 raw diagnostic code，且不把 machine-only readiness gap 改分類成人工 review。修復後：`21 passed`。

## 3. 五項問題與處置

| # | 使用任務／卡點 | 畫面或元件證據 | C 處置 | 驗收方式 |
|---|---|---|---|---|
| 1 | 資料準備到可研究：資料日、基準日與缺口不能判讀 | Workbench 原先把來源資訊壓成單一 raw 行；future／missing snapshot 只留 warning | 顯示 `as_of`、資料日期、source status／mode、DTO generated time；缺欄明示未知；composer 投影來源缺口；不猜台股交易日 | source/composer 21 passed；Workbench Inspector 測試；final screenshot |
| 2 | 今日先看誰：390px action cards 與 primary／Inspector 橫排造成裁切 | before Workbench 390px 兩欄卡與右側內容被截斷 | 今日卡片窄版改單欄；primary、summary、drilldown、evidence summary 垂直重排；技術 DTO raw 欄位預設收合 | Workbench UI test；1366／390 實際抓圖 |
| 3 | 候選到研究假說：股票／區間／資料日／Profile 容易在結果頁遺失 | Recommendation result split 在窄版只剩一側，空結果沒有 context anchor | 保留既有 Profile policy；在結果首層增加 research context banner，標示標的、區間、決策日、資料日、來源、結果 ID；清楚寫 confidence 不等於勝率／風險預算 | Recommendation UI test；126 focused passed；final screenshot |
| 4 | 比較到證據：回測設定與結果在窄版互相遮擋，scope 容易混同 | Backtest left config／right result splitter 在 390px 只看得到局部 | 既有 splitter 窄版上下排列；表格保留需要時水平捲動；以現有 evidence scope 分開研究回放／自然前瞻／Paper／正式可用；沒有數值時不補值 | Research workflow／mode／registry tests；full smoke 兩 viewport |
| 5 | 觀察／Portfolio：操作列與交易／Paper tabs 被擠在同一行，建議、待成交、成交語意不清 | Portfolio before narrow 右側明細 tabs 與操作列不可完整閱讀 | 操作列、歷史 filter、Paper controls 窄版直排；Portfolio view minimum hint 不再把主視窗撐高；既有狀態 tooltip／accessibility description 明示三層 scope與不自動下單 | Portfolio UI test；126 focused passed；final screenshot |

## 4. 三條核心流程 before／after 證據

| 流程 | Before 1366 | After 1366 | Before 390 | After 390 |
|---|---|---|---|---|
| 資料準備→可研究／Workbench | `before_1366/before_workbench_1366x768.png`（actual 1366×768） | `final3_1366/final3_workbench_1366x768.png`（actual 1366×768） | `before_390/before_workbench_390x844.png`（actual 390×844） | `final3_390/final3_workbench_390x844.png`（actual 390×844） |
| 候選→研究假說／Recommendation | `before_1366/before_recommendation_1366x768.png`（actual 1366×768） | `final3_1366/final3_recommendation_1366x768.png`（actual 1366×768） | `before_390/before_recommendation_390x844.png`（actual 390×844） | `final3_390/final3_recommendation_390x844.png`（actual 390×844） |
| 比較→觀察／Portfolio | `before_1366/before_portfolio_1366x768.png`（actual 1366×808，既有最小高度約束） | `final3_1366/final3_portfolio_1366x768.png`（actual 1366×768） | `before_390/before_portfolio_390x844.png`（actual 390×844） | `final3_390/final3_portfolio_390x844.png`（actual 390×844） |

補充驗證也保存 Backtest before／after；final3 的 Backtest actual 為兩個 requested viewport，且 390px 已顯示垂直設定／結果流程。完整逐 workspace evidence 在 `final3_1366/final3_evidence.json` 與 `final3_390/final3_evidence.json`。

## 5. 變更檔案與邊界

### 受控程式／測試／手冊

- `app_module/workbench_read_only_composer.py`：既有 source diagnostic 的窄幅 read-only review projection。
- `tests/test_workbench_source_service.py`：補齊 synthetic scheduled freshness fixture。
- `ui_qt/views/workbench_view.py`：來源 metadata、窄版 layout、Inspector technical toggle、table scroll policy。
- `ui_qt/views/recommendation_view.py`：研究 context banner、窄版 splitter／結果控制列與既有 token 化建議卡。
- `ui_qt/views/backtest_view.py`：窄版 splitter、viewport 最小高度與結果／設定重排。
- `ui_qt/views/portfolio_view.py`：scope 說明、操作列／tabs 重排、viewport 最小高度與資料表捲動。
- `tests/test_ui_qt_workbench_view.py`、`tests/test_ui_qt_recommendation_profiles.py`、`tests/test_ui_qt_portfolio_view.py`：以使用者可見 layout／toggle／context／scope 行為驗證。
- `docs/07_guides/APPLICATION_MANUAL.md`：更新 Workbench、Recommendation、Research Lab 與 Portfolio 既有章節。

沒有修改 A 的來源品質工具、B 的分類／架構決策、資料／ML／策略計算或 financial domain。未新建 DTO；不需要把缺欄位塞入 view。既有 `WorkbenchDashboardDTO`、`RecommendationProfileService`、`PortfolioDTO`、Research Lab DTO／evidence scope 契約均保留。

## 6. Manual 對照

- `APPLICATION_MANUAL.md` 2.6：今日行動中心、基準日／資料日、source gap、窄版重排與 technical raw 展開。
- `APPLICATION_MANUAL.md` 6.1／6.4：研究 context、規則分數／資料品質／研究訊號／校準機率分離，以及 Profile policy 不自動升級風險。
- `APPLICATION_MANUAL.md` 9.1／9.9：Research Lab 窄版上下排列、比較前的股票池／期間／成本／成交／樣本／benchmark 假設與 evidence scope 分層。
- `APPLICATION_MANUAL.md` 10.2／10.4：研究建議、待成交／Paper 與已記錄成交分層；缺數值顯示 unknown／not-computable；不自動下單。

核心 Snapshot／Roadmap 未改；若整合後需要改目前狀態或 roadmap，交由 integration owner 依 Scoped SSOT 更新。

## 7. 驗證命令與 exit code

| 類型 | 命令／結果 |
|---|---|
| Contract reproduction before | `pytest tests/test_workbench_source_service.py -q -o addopts=` → exit `1`，`2 passed / 3 failed` |
| Contract repair | `pytest tests/test_workbench_source_service.py tests/test_workbench_read_only_composer.py -q -o addopts=` → exit `0`，`21 passed` |
| C focused UI／workflow | 9 個 Workbench／Recommendation／Portfolio／Research Lab 測試檔 → exit `0`，`126 passed` |
| Mandatory Update UI | `pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=` → exit `0`，`81 passed` |
| Mandatory Update QA | `python scripts/qa_validate_update_tab.py` → exit `0`，`25 passed / 0 failed / 4 skipped`；下載與 merge 實測依腳本安全策略跳過 |
| Mandatory mypy | `mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` → exit `0`，`Success: no issues found in 565 source files` |
| Changed Python syntax | `py_compile` 10 個 changed Python files → exit `0` |
| Full app smoke | `qa.full_app_healthcheck.mainwindow_smoke_child --screenshot --switch-tabs --resize 1366x768 --resize 390x844` → exit `0`；8／8 workspaces、2／2 viewport matched、forbidden actions 0 |
| Flow screenshots | `output/luna_C/capture_flows.py`（theme + synthetic isolated root）兩個 viewport → exit `0`；5 個 C workspaces 各自 actual=requested |

Pytest 僅有既有 `.pytest_cache` permission warning，未影響 exit code。所有命令使用實際存在的 `.venv/Scripts/python.exe`。

## 8. 未驗範圍

- 沒有 native foreground／Windows 實體螢幕 CUA；已用真實 PySide6 `MainWindow` offscreen render、widget resize、screenshot 與 full healthcheck 取代 QSS-only 審查。
- offscreen final flow DPR 為 1.0；Windows 150%／200% 的實體 DPI、螢幕閱讀器與真人 Tab／Escape 體驗尚未驗證。
- 使用空的合成資料根目錄，未宣稱 live source freshness、長時間 worker 網路下載、實際取消競速或真實 snapshot／成交內容通過。
- 沒有執行真實資料更新、promotion、scheduler、broker、Portfolio 寫入、Paper ledger append 或自動配置；Update QA 的 destructive／大量下載分支依腳本顯示為 skipped。
- Recommendation 的真實 populated result、Portfolio 交易帳本／Paper fill 與 Backtest 的完整證據數值，仍須用 owner 提供的受治理 projection／隔離 fixture 做後續資料驗證。
- 既有 Recommendation／Portfolio 部分 legacy white controls 尚未全頁換色；本輪只補相容既有 `MIDNIGHT_ANALYST` token 的必要區塊，未建立第二套 theme。

## 9. DTO proposal（未接線）

本輪不新增 DTO，已用既有 source projection 與 `WorkbenchReviewItem` 完成可操作缺口。若 integration owner 後續要讓資料日／freshness 在多頁一致，建議在既有 `WorkbenchDashboardDTO`／source projection 增加 optional read-only 欄位：

`data_date`、`freshness_status`、`required_field_gaps`、`source_coverage`、`snapshot_hash`、`schema_version`、`gate_details`。

欄位缺失必須維持 `unknown`，由 source service 供應並保留 source trace；view 不查 DB、不掃檔、不重建 hash、不改 Gate 分類。此 proposal 不改 A／B 的 DTO 或來源決策，交整合 owner 審查後再決定是否進入下一版契約。

## 10. 精確回滾與剩餘風險

回滾時只針對本工作線檔案，不可對混合 dirty tree 使用 `git reset --hard`、`git checkout --` 或整樹 clean：

1. 先 `git status --short`，確認 A／B 既有變更仍在。
2. 若本 C commit 尚未提交，對下列 11 個受控檔案逐一反向套用本次 diff，或從本 C review 只恢復同名檔案：`app_module/workbench_read_only_composer.py`、`tests/test_workbench_source_service.py`、4 個 `ui_qt/views/*.py`、3 個 UI test、`docs/07_guides/APPLICATION_MANUAL.md`、本 handoff；不要碰其他 dirty path。
3. 若已提交，對本次 C commit 執行 `git revert <C-commit>`；不要 reset／checkout。revert 後重跑 Workbench contract、focused UI、mandatory Update 與 full smoke。
4. 可移除 ignored 的 `output/luna_C/` raw evidence；它們是合成資料，可重新生成，不是正式資料。不要刪除 `DATA_ROOT` 正式根目錄或任何原始資料。

剩餘風險：offscreen 字型與實機輔助科技尚待驗證；legacy control 的視覺一致性仍有少量技術債；Workbench source projection 仍受上游 DTO 欄位完整度限制。這些風險不會授予正式 evidence、ML alpha、promotion 或交易權限。
