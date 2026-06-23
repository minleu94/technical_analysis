# Full App Healthcheck Issue Resolution Design

> 日期：2026-06-23  
> 來源：`docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`  
> 範圍：PySide6 主 UI、跨工作區流程、healthcheck 已知 issue 收斂設計。  
> 狀態：待使用者審閱。本文是設計規格，不直接代表程式已修改。

## 目標

把 full app healthcheck 目前仍未驗證通過的已知問題，整理成可執行的分批修復設計。設計必須同時覆蓋：

1. 已與使用者討論並定案的產品 / 資訊架構方向。
2. 不需再做產品取捨、可直接修復的 bug 與 UX 問題。
3. 需先做技術排查再決定方案的效能 / 計算問題。
4. 已修正待驗證項目的回歸驗證清單。

## 非目標

1. 本設計不新增交易建議、自動下單或自動調倉能力。
2. 不破壞正式資料與 raw CSV，不做資料重建或高風險 apply。
3. 不把基本面 factor 自動接入 `ScoringEngine`。
4. 不在本設計階段改程式碼；實作需另寫 implementation plan 後分批執行。

## 全域原則

1. 所有使用者可見文字以繁體中文呈現；raw key / event type 可保留在 tooltip、展開細節或 debug metadata。
2. 股票、策略、推薦、回測、績效與資金相關數值不得新增裸 `float` 核心計算；必要時計算用 `Decimal`、整數基點、股數或分為單位。
3. 策略、推薦與回測邏輯修改前需做 look-ahead bias 自查。
4. UI 的主結論與警示只能作研究輔助，不得寫成買賣建議。
5. Healthcheck 中 `已修正待驗證` 的項目，實作後仍需等待使用者重新人工驗證，才能改成 `驗證通過`。
6. 所有指標與分類邏輯皆封裝於後端 Service / domain 層，例如 `DecisionDeskService`、`BrokerFlowService` 或後續抽出的 `SmartMoneyService`；UI 僅負責唯讀渲染、DTO 映射、排序顯示與導覽，不直接呼叫 domain 運算模組或重算領域規則。
7. 回測、推薦回放與任何 decision-date 情境必須用 `decision_date` 或可取得的 T-1 交易日作為資料截止點；所有 rolling window、分位數、最高價與籌碼統計都只能向前取資料，不得使用決策日後資料。

## 已確認產品決策

### Daily Decision Dashboard v2

Daily Decision 升級為 answer-first / sector-first 的市場總覽首頁。

1. 最上方顯示市場主結論：
   - 行動等級：`積極研究`、`正常研究`、`保守觀察`、`暫停新進場`。
   - 等級由 Regime、市場廣度與 confidence 決定。
   - Watchlist / 持倉 / 個股風險不直接降低整體市場等級，只影響研究方向與警示。
   - 文案需標示這是研究模式，不是交易建議。
2. 第二層以產業為主線：
   - `優先產業`：強勢或轉強產業。
   - `避開產業 / 風險區`：主力賣超、弱勢集中或 Watchlist / 持倉風險較多的產業。
   - 產業卡可 drill down 到市場觀察對應子頁。
3. 第三層是產業內股票：
   - 股票來源採混合：先列 Watchlist / 持倉，再補全市場代表股票。
   - 每檔股票顯示觸發原因、主力流向摘要、價格 / 漲跌幅、推薦分數與 regime match。
   - 點股票預設跳到 `市場觀察 > 主力流向` 並定位該股票。
4. 避開清單優先序：
   - Watchlist / 持倉風險警示。
   - 主力流向賣超累積。
   - 相對弱勢。

覆蓋 issue：`DECISION-ISSUE-002`、`DECISION-ISSUE-003`、`MARKET-ISSUE-006`、`MARKET-ISSUE-007` 的 dashboard 依賴部分。

### Smart Money 語意層

Smart Money 改成「卡片顯示語意狀態，展開顯示完整 5 / 20 / 60 日診斷」。

1. 卡片簡潔狀態：
   - `初轉買`
   - `買超延續`
   - `初轉賣`
   - `賣超延續`
   - `高檔出貨疑慮`
   - `分點集中異常`
2. 展開或 tooltip 顯示：
   - 5 / 20 / 60 日累積買賣超。
   - 連續買賣超天數。
   - 5 日 Top 3 分點集中度。
   - 20 日 Top 5 分點集中度。
   - 60 日價格分位與距離高點。
   - 集中度採用的單位、資料品質旗標與排除筆數。
3. 排序規則：
   - 產業仍是第一層主線。
   - Smart Money 只在同一產業內調整股票排序，不跨產業改變首頁優先順序。
4. 籌碼集中度單位與品質契約：
   - 5 日 Top 3、20 日 Top 5 與 Portfolio chip monitor 的集中度主契約採 `張數 / 股數等價 quantity`，不是千元金額。
   - 若資料源已有 observed 張數或股數，集中度以該 quantity 加總；若只有金額千元且有決策日前可取得收盤價，才可用 `Decimal` 折算為 estimated quantity。
   - 千元金額只作為 estimated quantity 的 fallback，不得直接拿金額千元計算同一個集中度欄位；若未來需要金額集中度，必須使用另一個明確命名的 metric。
   - `observed`：使用原始張數 / 股數資料。
   - `estimated`：由金額千元與決策日前可取得價格折算 quantity，會降低 confidence 並標示估算。
   - `unavailable`：不可放入集中度分子或分母，必須排除該筆並揭露排除筆數；若可用筆數為 0，集中度狀態為 unavailable，不得用 0% 假裝正常。
   - Tooltip / 詳情面板必須揭露 quality flags，至少包含 observed / estimated / unavailable 筆數、usable coverage ratio、是否含估算張數、排除原因與計算單位。
   - 單筆 unavailable 不得污染整個集中度計算；只降級該筆並在聚合結果上標示資料品質與覆蓋率。
5. `高檔出貨疑慮` 規則：
   - 近 60 日價格分位 >= 80%。
   - 距離近 60 日最高價小於 10%。
   - 同時主力為初轉賣或賣超延續。
   - 顯示為風險提示，不等於賣出建議。
   - Look-ahead 自查：近 60 日價格分位與最高價必須嚴格以當前 `decision_date` 或 T-1 交易日為基準向前推算 60 個交易日，禁止使用整段回測時間軸的未來高點或未來價格。
6. `分點集中異常` 規則：
   - 5 日 Top 3 分點佔淨買賣超絕對值 >= 60%。
   - 20 日 Top 5 分點佔淨買賣超絕對值 >= 60%。
   - 5 日與 20 日方向一致。
   - 顯示為注意標籤，不直接代表利多或利空。
   - Top N 集中度沿用上述 quantity 與 quality contract；分母只包含同方向且 quality 不是 unavailable 的分點資料。

覆蓋 issue：`MARKET-ISSUE-006`、`MARKET-ISSUE-007`、`PORTFOLIO-ISSUE-006`、`PORTFOLIO-ISSUE-007` 的籌碼語意部分。

### Recommendation Profile / Regime

推薦分析支援內建、自訂與策略版本 Profile。

1. Profile 類型：
   - `內建 Profile`：系統預設。
   - `自訂 Profile`：使用者在推薦分析保存進階設定，保存後可直接使用，但標示 `自訂，未經回測驗證`。
   - 自訂 Profile 的門檻分數、權重、百分位與其他量化參數寫入 JSON 時，必須比照 `PORTFOLIO-ISSUE-008` 建立序列化防禦；不得因讀寫設定檔把 `Decimal`、基點或整數權重轉成裸 `float` 並引入精度問題。
   - `策略版本 Profile`：Research Lab 通過 Gate 升級後進入推薦分析，可手動啟用 / 停用。
2. Profile 下拉：
   - 三類 Profile 混在同一個下拉，但前綴清楚標示。
   - 例：`內建｜暴衝策略`、`自訂｜我的短線突破`、`策略版本｜半導體突破 v2`。
   - 停用的策略版本不顯示，但不刪除歷史 run 或策略版本。
3. Regime match 顯示：
   - 顯示目前 regime。
   - 顯示 Profile 適用 regime。
   - 顯示匹配狀態。
   - 顯示分數影響，例如 bonus、未加分或降權。
   - 不匹配不排除結果，只做解釋與排序 / 分數揭露。

覆蓋 issue：`RECOMMEND-ISSUE-001`、`RECOMMEND-ISSUE-002`、`RECOMMEND-ISSUE-003`、`RECOMMEND-ISSUE-004`、`RECOMMEND-ISSUE-008`。

### Runtime Observatory

Runtime Observatory 只監控 agent / governance / runtime workflow，不監控資料更新、回測、推薦、匯出等一般 App 任務。

1. UI 需明確說明範圍：
   - Runtime Observatory 不監控資料更新背景任務。
   - 資料更新、回測與推薦長任務仍由各自頁面顯示狀態。
2. 中文化：
   - `FSM State Machine` → `任務狀態機`
   - `Objective` → `目前治理目標`
   - `No task assigned` → `尚未指派治理任務`
   - `IDLE` → `閒置`
   - `HALTED` → `治理暫停`
   - `Rejection Rate` → `驗證拒絕率`
   - `Consecutive Fails` → `連續失敗次數`
   - `GovernanceViolation` → `治理規則違反`
3. 警示：
   - `HALTED`、高拒絕率、連續失敗在 Runtime 頁內用紅色警示。
   - 同區塊明確說明這不代表主 App 一般功能失敗。
4. Event Stream：
   - 主要顯示中文摘要。
   - raw event type、payload、exception 放在展開細節。

覆蓋 issue：`RUNTIME-ISSUE-001`、`RUNTIME-ISSUE-002`、`RUNTIME-ISSUE-003`、`RUNTIME-ISSUE-004`。

### Research Lab 分批策略

Research Lab / Backtest 分三批修。

第一批：UX 可讀性與導引。

1. 模式說明：單股、批次、固定組合、推薦回放、策略研究差異。
2. 日期日曆：開始 / 結束日期 calendar popup。
3. 歷史與 Registry 自動刷新：首次進入、保存後、刪除後、升級後一致刷新。
4. 保存 / 升級成功後下一步導引。
5. Excel 報告缺失欄位中文說明。
6. Registry / run type / 參數差異基礎中文化。

第二批：結果頁資訊架構。

1. 推薦回放結果頁重排。
2. Registry 比較頁重設計。
3. 批次比較目的與判讀。
4. Train-Test / Walk-forward 樣本可靠度與不直覺指標診斷。

第三批：最佳化效能與取消。

1. 參數組合數預估與警告。
2. worker 數設定。
3. 取消流程與錯誤訊息收斂。
4. ProcessPool / vectorized / early pruning 可行性排查。

本輪 Research Lab 可先更新 healthcheck；若實作改變既有 Manual 明確描述，需在該批或總收斂階段補最小 Manual 更新，以符合 repo 文檔同步規則。

覆蓋 issue：`BACKTEST-ISSUE-002` 至 `BACKTEST-ISSUE-005`、`BACKTEST-ISSUE-010` 至 `BACKTEST-ISSUE-015`、`BACKTEST-ISSUE-019`、`BACKTEST-ISSUE-021` 至 `BACKTEST-ISSUE-024`。

## 直接修復範圍

這些 issue 不需再做產品決策，納入第一批實作。

### UpdateView / Data Update

1. `UPDATE-ISSUE-030`：資料源狀態檢查結果可見性。
   - 每日股價與券商分點點「檢查此資料源狀態」後，在分頁內顯示摘要列或小卡。
   - 摘要至少包含最新日期、SQLite 筆數、CSV 日檔狀態、缺漏日期與品質 / warning。
   - 日誌保留細節，但不作唯一可見入口。
2. `UPDATE-ISSUE-031`：高風險強制合併確認 / 取消流程。
   - 使用二次確認對話框。
   - 按鈕文案明確：`取消`、`確認強制合併`。
   - 對話框說明會重建哪些資料、是否影響 raw CSV、預估耗時與建議備份。
   - 對話框需明確宣告：`強制合併是針對 SQLite 資料庫重新進行 CSV 匯入與索引建立，不應亦不會修改或刪除 {DATA_ROOT} 底下的 raw CSV 原始檔案，以保障資料安全性`。
3. `UPDATE-ISSUE-029`：已修正待驗證。
   - 納入回歸測試與人工驗證清單。
   - 確認從開始日期包含第一個缺漏日，不再跳過 0618 這類首日缺口。

### Portfolio

1. `PORTFOLIO-ISSUE-001`：手動記錄交易預設台股費稅與股票名稱查找。
   - 費率預填，但可覆寫。
   - 股票代號輸入後查正式股票來源並自動補名稱。
   - 不存在代號顯示清楚錯誤。
2. `PORTFOLIO-ISSUE-002`：活躍持倉摘要卡 UI。
   - 摘要卡顯示持倉檔數與前幾大持倉代號 / 名稱。
   - 調整字級、間距與資訊層級。
3. `PORTFOLIO-ISSUE-003`：交易歷史清除篩選入口。
   - 提供明顯的 `清除篩選 / 顯示全部交易歷史`。
   - 顯示目前是否正在依股票過濾。
4. `PORTFOLIO-ISSUE-004`：最新價格日期。
   - 最新價格旁顯示 as-of date。
   - 若價格非最新交易日或 fallback，顯示品質提示。
5. `PORTFOLIO-ISSUE-005`：手動來源語意。
   - 手動建立持倉顯示 `手動建立，無推薦 / 回測來源`。
   - 不只顯示 `未知`。
6. `PORTFOLIO-ISSUE-006`：籌碼風險中文化。
   - low / medium / high 等級顯示為 `低 / 中 / 高`。
   - raw key 放 tooltip 或 debug detail。
7. `PORTFOLIO-ISSUE-007`：持倉到主力流向下鑽定位。
   - 下鑽帶入目前股票代號。
   - 市場觀察主力流向定位或篩選該股票。
   - 無資料時顯示清楚空狀態。
8. `PORTFOLIO-ISSUE-008`：推薦分析記錄到持倉 Decimal JSON 序列化錯誤。
   - JSON metadata 寫入前將 `Decimal` 轉為安全格式。
   - 金額 / 股數 / 基點不可因轉型喪失精度。
   - 優先使用字串或整數基點，避免裸 float。
9. `PORTFOLIO-ISSUE-009`：Research Lab 記錄持倉入口語意。
   - 明確定義支援來源：單股回測交易、推薦回放交易。
   - 若批次結果不支援直接記錄持倉，UI、healthcheck 與提示需改寫，不讓使用者期待錯誤入口。

### Watchlist / 已修正待驗證

`WATCHLIST-ISSUE-001`、`WATCHLIST-ISSUE-002` 已修正待驗證，只納入回歸驗證，不再新增設計。

### 已修正待驗證項目

以下不應重做，除非驗證失敗：

1. Update 已修正待驗證 / 通過項目：`UPDATE-ISSUE-001`、`UPDATE-ISSUE-002`、`UPDATE-ISSUE-003`、`UPDATE-ISSUE-004`、`UPDATE-ISSUE-005`、`UPDATE-ISSUE-006`、`UPDATE-ISSUE-007`、`UPDATE-ISSUE-008`、`UPDATE-ISSUE-009`、`UPDATE-ISSUE-010`、`UPDATE-ISSUE-011`、`UPDATE-ISSUE-012`、`UPDATE-ISSUE-015`、`UPDATE-ISSUE-016`、`UPDATE-ISSUE-017`、`UPDATE-ISSUE-018`、`UPDATE-ISSUE-019`、`UPDATE-ISSUE-020`、`UPDATE-ISSUE-021`、`UPDATE-ISSUE-022`、`UPDATE-ISSUE-023`、`UPDATE-ISSUE-024`、`UPDATE-ISSUE-025`、`UPDATE-ISSUE-026`、`UPDATE-ISSUE-027`、`UPDATE-ISSUE-028`、`UPDATE-ISSUE-029`。
2. `MARKET-ISSUE-001`、`MARKET-ISSUE-004`、`MARKET-ISSUE-005`。
3. `DECISION-ISSUE-001`。
4. `BACKTEST-ISSUE-001`、`006`、`007`、`008`、`009`、`014`、`016`、`017`、`018`、`020`。
5. `RECOMMEND-ISSUE-005`、`006`、`007`、`009`、`010`。
6. `WATCHLIST-ISSUE-001`、`WATCHLIST-ISSUE-002`。

## 需排查後決策

這些項目不能直接承諾完整修法，需先做技術或資料路徑排查。

1. `MARKET-ISSUE-002`：Regime confidence 100% 與子分數全 1。
   - 先確認是否為正常 bounded score、顯示四捨五入、或計算問題。
   - 若計算正常，補語意與 UI 文案。
   - 若計算不合理，另開修復任務。
2. `MARKET-ISSUE-003`：強 / 弱勢股與產業 SQLite-first。
   - 盤點 `ScreeningService`、`StockScreener`、`IndustryMapper` 實際資料來源。
   - 評估 SQLite-first、快取或背景載入。
3. `UPDATE-ISSUE-013`：券商分點受控並行。
   - 先確認下載與合併瓶頸、rate limit、retry、站方阻擋風險。
4. `UPDATE-ISSUE-014`：技術指標多核心。
   - 先拆分計算瓶頸與寫入瓶頸。
   - 不允許多進程同時寫 SQLite 或覆寫 CSV。
   - 多進程 / 多核心僅可用於 CPU-bound 技術指標計算；SQLite 寫入必須收集回主線程或單一進程循序寫入，避免 `database is locked` 與資料庫鎖定衝突。
5. `BACKTEST-ISSUE-011`、`BACKTEST-ISSUE-012`：最佳化效能與取消。
   - 先盤點目前 ThreadPoolExecutor、資料預載、SQLite / CSV 路徑與取消流程。
   - 再決定 ProcessPool、vectorized、early pruning 或 worker 設定。
6. `BACKTEST-ISSUE-013`：Train-Test / Walk-forward 指標不直覺。
   - 先驗證 MDD、勝率、fold 數與交易數計算。
   - 再補樣本不足與結果解讀 UI。

## 實作批次建議

### Batch 0：基線與驗證盤點

1. 確認 healthcheck issue ledger 最新狀態。
2. 為已修正待驗證項目建立回歸測試清單。
3. 不改功能，只確認測試 baseline。

### Batch 1：直接修復與低風險 UX

1. UpdateView：`UPDATE-ISSUE-030`、`UPDATE-ISSUE-031`。
2. Portfolio：`PORTFOLIO-ISSUE-001` 至 `PORTFOLIO-ISSUE-009`。
3. Runtime Observatory：`RUNTIME-ISSUE-001` 至 `RUNTIME-ISSUE-004`。
4. Research Lab 第一批 UX：模式說明、日期日曆、自動刷新、保存 / 升級導引、Excel 缺失欄位中文說明、Registry 基礎中文化。
5. Healthcheck 更新對應項目為 `已修正待驗證`。

### Batch 2：Daily Dashboard 與 Smart Money

1. 建立 Daily Decision Dashboard v2。
2. 建立 Smart Money 語意層與 5 / 20 / 60 日診斷。
3. 建立 Dashboard 到市場觀察主力流向的股票定位。
4. 更新 healthcheck。

### Batch 3：Recommendation Profile / Regime

1. Profile 下拉支援內建 / 自訂 / 策略版本。
2. 自訂 Profile 保存與標示未驗證。
3. 策略版本啟用 / 停用。
4. Regime match 詳情與分數影響揭露。
5. 更新 healthcheck。

### Batch 4：Research Lab 結果頁

1. 推薦回放結果頁重排。
2. Registry 比較頁重設計。
3. 批次比較判讀。
4. Train-Test / Walk-forward 樣本可靠度提示。
5. 更新 healthcheck。

### Batch 5：效能與計算排查

1. Regime confidence 計算排查。
2. 強弱股 / 產業 SQLite-first 排查與實作。
3. 券商分點並行可行性。
4. 技術指標多核心可行性。
   - 多核心只負責計算，寫入 SQLite 採主線程或單一 writer。
5. 最佳化效能與取消流程。

## 測試策略

1. 每個 batch 先補失敗測試，再改實作。
2. UI 變更至少補 PySide6 widget-level 測試。
3. Portfolio Decimal 序列化需測試不產生裸 float 且 JSON 可寫入。
4. Smart Money 語意層需用固定 fixture 測試：
   - 初轉買。
   - 買超延續。
   - 初轉賣。
   - 賣超延續。
   - 高檔出貨疑慮。
   - 分點集中異常。
   - 集中度以 quantity 計算，不以千元金額直接計算。
   - observed / estimated / unavailable 混合資料時，unavailable 被排除並揭露 quality flags。
   - 高檔出貨疑慮的 60 日價格分位與最高價不使用 `decision_date` 後資料。
5. Recommendation Profile 需測：
   - 內建 / 自訂 / 策略版本顯示前綴。
   - 停用策略版本不出現在下拉。
   - 自訂 Profile 顯示未驗證標記。
   - 自訂 Profile JSON round-trip 不引入裸 `float` 精度問題。
   - Regime 不匹配不排除結果。
6. Runtime Observatory 需測：
   - 中文摘要。
   - raw event 展開。
   - HALTED 紅色警示。
   - 範圍說明不監控一般 App 任務。
7. 必跑既有驗證：
   - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=`
   - `.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py`
   - `.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`
   - `.\.venv\Scripts\python.exe -m py_compile <changed-python-files>`

## 文件策略

1. 每批實作後必須更新 healthcheck 狀態。
2. Research Lab 本輪依討論先以 healthcheck 收斂為主。
3. 若 UI 行為與 Application Manual 現有文字直接矛盾，該批需做最小 Manual 修正，避免手冊誤導使用者。
4. 三批 Research Lab 穩定後，再集中整理完整 Manual。

## Issue 覆蓋檢查

已討論並有設計決策：

- `DECISION-ISSUE-002`
- `DECISION-ISSUE-003`
- `MARKET-ISSUE-006`
- `MARKET-ISSUE-007`
- `RECOMMEND-ISSUE-001`
- `RECOMMEND-ISSUE-002`
- `RECOMMEND-ISSUE-003`
- `RECOMMEND-ISSUE-004`
- `RECOMMEND-ISSUE-008`
- `RUNTIME-ISSUE-001`
- `RUNTIME-ISSUE-002`
- `RUNTIME-ISSUE-003`
- `RUNTIME-ISSUE-004`
- `BACKTEST-ISSUE-002`
- `BACKTEST-ISSUE-003`
- `BACKTEST-ISSUE-004`
- `BACKTEST-ISSUE-005`
- `BACKTEST-ISSUE-010`
- `BACKTEST-ISSUE-011`
- `BACKTEST-ISSUE-012`
- `BACKTEST-ISSUE-013`
- `BACKTEST-ISSUE-015`
- `BACKTEST-ISSUE-019`
- `BACKTEST-ISSUE-021`
- `BACKTEST-ISSUE-022`
- `BACKTEST-ISSUE-023`
- `BACKTEST-ISSUE-024`

直接納入第一批修復：

- `UPDATE-ISSUE-030`
- `UPDATE-ISSUE-031`
- `PORTFOLIO-ISSUE-001`
- `PORTFOLIO-ISSUE-002`
- `PORTFOLIO-ISSUE-003`
- `PORTFOLIO-ISSUE-004`
- `PORTFOLIO-ISSUE-005`
- `PORTFOLIO-ISSUE-006`
- `PORTFOLIO-ISSUE-007`
- `PORTFOLIO-ISSUE-008`
- `PORTFOLIO-ISSUE-009`

需排查後決策：

- `MARKET-ISSUE-002`
- `MARKET-ISSUE-003`
- `UPDATE-ISSUE-013`
- `UPDATE-ISSUE-014`
- `BACKTEST-ISSUE-011`
- `BACKTEST-ISSUE-012`
- `BACKTEST-ISSUE-013`

只需回歸驗證或重測：

- `UPDATE-ISSUE-001`
- `UPDATE-ISSUE-002`
- `UPDATE-ISSUE-003`
- `UPDATE-ISSUE-004`
- `UPDATE-ISSUE-005`
- `UPDATE-ISSUE-006`
- `UPDATE-ISSUE-007`
- `UPDATE-ISSUE-008`
- `UPDATE-ISSUE-009`
- `UPDATE-ISSUE-010`
- `UPDATE-ISSUE-011`
- `UPDATE-ISSUE-012`
- `UPDATE-ISSUE-015`
- `UPDATE-ISSUE-016`
- `UPDATE-ISSUE-017`
- `UPDATE-ISSUE-018`
- `UPDATE-ISSUE-019`
- `UPDATE-ISSUE-020`
- `UPDATE-ISSUE-021`
- `UPDATE-ISSUE-022`
- `UPDATE-ISSUE-023`
- `UPDATE-ISSUE-024`
- `UPDATE-ISSUE-025`
- `UPDATE-ISSUE-026`
- `UPDATE-ISSUE-027`
- `UPDATE-ISSUE-028`
- `UPDATE-ISSUE-029`
- `MARKET-ISSUE-001`
- `MARKET-ISSUE-004`
- `MARKET-ISSUE-005`
- `DECISION-ISSUE-001`
- `BACKTEST-ISSUE-001`
- `BACKTEST-ISSUE-006`
- `BACKTEST-ISSUE-007`
- `BACKTEST-ISSUE-008`
- `BACKTEST-ISSUE-009`
- `BACKTEST-ISSUE-014`
- `BACKTEST-ISSUE-016`
- `BACKTEST-ISSUE-017`
- `BACKTEST-ISSUE-018`
- `BACKTEST-ISSUE-020`
- `RECOMMEND-ISSUE-005`
- `RECOMMEND-ISSUE-006`
- `RECOMMEND-ISSUE-007`
- `RECOMMEND-ISSUE-009`
- `RECOMMEND-ISSUE-010`
- `WATCHLIST-ISSUE-001`
- `WATCHLIST-ISSUE-002`
