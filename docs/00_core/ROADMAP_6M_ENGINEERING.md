# 6 個月可執行工程路線（2026-06 至 2026-12）

> **最後更新**：2026-06-14
> **定位**：本文件是未來 6 個月工程執行與研究能力成長的權威路線圖。當它與短期 Snapshot 衝突時，以 Snapshot 的「本週優先事項」決定今天先做什麼；當它與歷史 Roadmap 衝突時，以本文件作為未來方向依據。

---

## 1. 目標

6 個月內把系統從「功能已形成三個閉環」推進到「能用可驗證實證與資料因子治理持續提高策略品質」。

核心成果：

1. 建立 fixed / quantile 與後續策略變體的真實 walk-forward 實證基準線。
2. 建立研究 run、資料版本、策略版本與因子貢獻的可追溯治理。
3. 將營收、基本面、估值、三大法人與券商籌碼納入可插拔 factor layer。
4. 補齊 Phase 5 研究輸出，讓回測與推薦組合結果能被保存、比較、匯出與複盤。
5. 建立 promote / demote / retire 規則，讓策略能被系統性升級或淘汰。

---

## 2. 不做什麼

- 不把 quantile 設成預設，直到真實股票池實證完成。
- 不把營收、財報、三大法人資料直接硬塞進 `ScoringEngine`。
- 不把推薦組合回測結果宣稱為實盤績效，除非成交假設改為可交易價格並揭露限制。
- 不導入黑箱 ML 作為主線；若未建立資料版本、OOS、因子歸因與漂移監控，ML 只會增加不可解釋風險。
- 不重建或破壞正式資料；所有資料新增必須非破壞性、可回溯、可降級。

---

## 3. 工程主線

### Track A：實證與回測可信度

目的：讓每一個策略改善都有 OOS 證據，而不是只看單次回測。

交付物：

- fixed / quantile walk-forward 比較報告。
- 實驗 run registry：保存資料版本、策略版本、參數、成本模型、成交假設與結果。
- rolling risk metrics：Rolling Sharpe / Sortino、VaR / CVaR、drawdown duration、turnover。
- benchmark-relative attribution：策略 vs TAIEX / 產業 / buy-and-hold 的超額報酬與風險歸因。

### Track B：Factor Layer 與資料治理

目的：讓新資料能被安全接入，不污染既有 scoring 與回測核心。

交付物：

- Factor contract：`factor_name`、`as_of_date`、`available_date`、`value`、`score_bp`、`quality`、`missing_policy`、`source_version`。
- Factor registry：技術、圖形、量能、券商分點、營收、基本面、法人、估值、custom。
- Indicator Parameter Registry：RSI、MACD、KD、ADX、MA、ATR、BBANDS 等參數的單位、範圍、預設值、版本與資料頻率。
- Recommendation Weight Contract：技術、圖形、量能與後續 factor 權重必須可版本化、可保存、可比較，不得只存在 UI 或程式硬編碼。
- Missing / neutral / stale 三態處理規則。
- Look-ahead gate：所有 factor 必須證明決策當下可取得。

### Track C：資料擴充

目的：建立能支援估值與籌碼研究的資料底座。

交付物：

- 月營收資料表：MoM、YoY、累計營收、資料公告日。
- 基本面資料表：EPS、ROE、毛利率、營益率、負債比、現金流、股本。
- 估值資料表或視圖：P/E、P/B、P/S、殖利率、產業相對估值分位。
- 三大法人資料表：外資、投信、自營商買賣超股數與金額、連買連賣、成交占比。

### Track D：研究輸出與使用體驗

目的：讓研究結果能被比較、匯出、審查，而不是只停留在 UI 當下畫面。

交付物：

- 大表格分頁或虛擬滾動。
- Excel / PDF 報告匯出模板。
- Cross-run comparison：比較不同策略版本、因子組合、成本假設、期間與股票池。
- Research dashboard：目前最佳候選、已淘汰策略、待驗證策略、資料品質警示。

### Track E：Portfolio 回饋閉環

目的：讓實際交易 / 模擬持倉能反饋研究，而不只是持倉監控。

交付物：

- 持倉原因與現況差異歸因：Regime、Score、Factor、法人、籌碼、估值。
- 實際交易 vs 回測預期落差：進場價差、滑價、出場原因、持有天數、最大不利走勢。
- Promote / demote / retire 規則：以 OOS、持倉後驗、風險與資料品質決定策略生命週期。

---

## 4. 月度里程碑

### Month 1：實證基準線與文件治理完成

> 2026-06-14 狀態：10 檔 fixed / quantile OOS 實證、100% Regime coverage、SQLite 穩定分頁與規格化 Excel 報告背景原子寫入均已完成。Quantile 未優於 fixed，維持 opt-in。

目標：

- 完成 fixed / quantile 真實 walk-forward 比較。
- 完成文件治理重構，讓 Snapshot / Roadmap Hub / 6M Roadmap / Architecture / Agent 指引一致。
- 完成 Phase 5 報告輸出的最小規格。
- 完成 Phase 5 最小可用實作 (SQLite 檢視器分頁與規格化 Excel 報告匯出已完成，PDF 仍在後續)。

交付物：

- 更新 [WALK_FORWARD_COMPARISON_REPORT.md](../06_qa/WALK_FORWARD_COMPARISON_REPORT.md)，加入真實股票池比較結果。
- 建立 `ResearchRun` 或等價 registry 規格。
- SQLite Inspector 穩定分頁。 (已完成)
- 回測 run / 推薦回放的規格化 Excel 匯出。 (已完成 Excel 匯出；PDF 仍待後續)
- Active docs 不再把舊 Roadmap 當單一最高權威。 (已完成)

驗收標準：

- fixed / quantile 使用同一資料版本、成本模型、成交假設與股票池。
- 報告明確列出 quantile 是否改善，若沒有改善也要保留結果。
- 所有 Agent 必讀規則能清楚指向 scoped authority。
- Phase 5 最小輸出可實際操作，且報告包含資料、策略、參數、成本、成交假設、Regime、benchmark、風險與驗證狀態。 (Excel 匯出符合此標準)

### Month 2：參數治理、Research Run Registry 與 Cross-run Comparison

目標：

- 讓每一次研究 run 可保存、可比較、可重播。
- 完成舊 Roadmap 的指標參數與推薦權重治理，避免新 Factor 建在不可追溯的參數底座上。

交付物：

- run metadata：資料截止日、資料 hash、策略版本、參數、成本、成交假設、universe。（M2-B 基礎保存已完成）
- Research Run Registry immutable save：SQLite metadata、Parquet 明細、hash 驗證、crash reconciliation、legacy backfill 與 UI 保存入口。（M2-B 已完成）
- Indicator Parameter Registry。（M2-A 已完成）
- Recommendation Weight Contract，並移除核心推薦權重只靠硬編碼保存的狀態。（M2-A 已完成）
- Cross-run comparison UI 與服務。（M2-C 已完成第一版；支援 2-5 個 run、三態 comparability、參數差異、metrics、Regime、benchmark 與正規化 equity 交集比較）
- strategy promote gate 改為讀取 registry，不只讀單次 summary。（M2-C 已完成第一版；以 Registry run 為來源，採 JSON Strategy Version 補償交易與 reconciliation 掃描）

驗收標準：

- 任一 promoted strategy 都能追溯到當時資料、參數、成本模型與結果。（M2-C Gate 已完成服務層 gate 與補償 / reconciliation 防線）
- 至少能比較 3 個策略版本或 3 組參數的 OOS 指標。（M2-C Gate 已完成第一版；比較 UI 支援 2-5 個 run，並禁止 incompatible run 被排序成優劣）
- 任一推薦或策略研究 run 都能還原當時的指標參數與權重版本。（M2-A / M2-B 已完成，M2-C 已補上比較與 promote 驗收）

### Month 3：Factor Layer v1

目標：

- 把新資料接入方式標準化，先不急著新增所有資料。

交付物：

- Factor DTO / registry / scoring adapter。
- 技術、量能、券商分點先以 factor contract 包裝。
- 推薦組合回測保存 factor contribution。

驗收標準：

- [LEGACY_ROADMAP_CARRYOVER.md](LEGACY_ROADMAP_CARRYOVER.md) 的 Carryover Gate 已通過；若未通過，Month 3 不得宣告開始。
- 缺少某因子資料時回傳 `missing` 或 `neutral`，不讓流程中斷。
- factor `available_date` 晚於決策日時必須拒絕使用。
- `ScoringEngine` 不直接依賴新資料表。

### Month 4：營收與估值資料 v1

目標：

- 建立基本面與估值研究的最小可用資料底座。

交付物：

- 月營收表與公告日欄位。
- 營收 YoY / MoM / 累計營收 factor。
- 第一版估值視圖：P/E、P/B、P/S、產業相對分位。

驗收標準：

- 回測使用營收與估值因子時只讀 `available_date <= decision_date` 的資料。
- 估值先以相對分位與區間呈現，不輸出未驗證的單點目標價。

### Month 5：三大法人與籌碼因子 v1

目標：

- 補足外資、投信、自營商資料，並與券商分點形成籌碼交叉驗證。

交付物：

- institutional_flows 表或等價 SQLite schema。
- 外資 / 投信 / 自營連買連賣、成交占比、產業聚集因子。
- 法人因子與 broker_flow 因子的共振 / 背離診斷。

驗收標準：

- 法人資料缺日、改值、不同資料源單位差異都有品質標示。
- 策略與推薦 UI 顯示法人因子時能說清楚資料日期與品質。

### Month 6：策略生命週期與 Portfolio 回饋

目標：

- 讓策略能被系統性升級、降級與淘汰。

交付物：

- promote / demote / retire 規則。
- Portfolio post-trade attribution。
- 實際 / 模擬交易與研究預期落差報告。
- 6 個月成果回顧與下一版 roadmap 草案。

驗收標準：

- 策略不能只靠單次高報酬被升級；必須通過 OOS、風險、交易次數與資料品質門檻。
- 被淘汰策略保留原因與證據，不刪除歷史。
- Portfolio 能回答「這筆交易原始假設是否仍成立」與「落差來自訊號、執行、資料或市場」。

---

## 5. 立即待辦清單

1. Fixed / quantile walk-forward 實證已完成；Research Run Registry 已承接 Cross-run comparison 與已保存 benchmark-relative attribution。
2. 大表格分頁 (SQLite 穩定分頁) 與規格化報告 (Excel 報告匯出) 已完成，PDF 仍在後續。
3. Research Run Registry immutable save、Cross-run comparison 與 registry-based promote gate 已完成第一版。
4. 定義 Factor Contract，不先接營收與法人。
5. 更新 `system_architecture.md` 已完成。
6. 依 [LEGACY_ROADMAP_CARRYOVER.md](LEGACY_ROADMAP_CARRYOVER.md) 關閉所有已完成的舊 Roadmap 移交項目。

---

## 6. 驗證規則

- UI 修改：依專案規範執行 Update Tab pytest、QA script、mypy 與 py_compile。
- 策略 / 回測 / 推薦 / factor 修改：必須先寫 Look-ahead 自查，並新增 no-look-ahead 測試。
- 金融核心數值：必須通過 `scripts/check_financial_float_boundaries.py` 與對應 pytest gate。
- 資料 schema：必須提供 migration / fallback / 資料品質驗證，且不得破壞正式資料。

---

## 7. 更新記錄

- 2026-06-14：完成 Phase 5 Month 1 的 SQLite 檢視器分頁與規格化 Excel 報告匯出 (單股/批次/組合回放/目前推薦)，並更新 6M Roadmap、Snapshot 及 Architecture。
- 2026-06-13：建立 6 個月可執行工程路線，作為未來方向的 scoped authority。
- 2026-06-13：加入 Legacy Carryover Gate，明確承接指標參數治理、推薦權重治理、Phase 5 輸出與穩定性驗證。
