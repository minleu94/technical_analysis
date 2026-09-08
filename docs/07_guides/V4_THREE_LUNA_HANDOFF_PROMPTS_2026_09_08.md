# V4 三線 Luna 接手任務

使用方式：每個新對話選擇 Luna、MAX，使用同一個既有專案的 local dev。每段 prompt 都可獨立貼上。不要建立新 worktree／branch。此文件是任務規格，不是完成證據。

## Prompt A：全資料更新與新鮮度閉環

你是本專案的資料工程負責人。請在 `C:/Projects/PythonProjects/technical_analysis` 完成全資料更新稽核、修補與每日增量更新閉環，不能只交報告。先按 AGENTS.md 閱讀必讀文件，尤其 shared_context、git_exclusions、資料稽核／清理／QA角色、目前狀態、架構及 Manual。繁體中文交付。

工作邊界：沿用 dev，不新增 branch/worktree，不 reset/stash/revert 別人的變更，不提交整個工作區。你負責 update service、資料來源更新器、freshness probe、更新排程及對應測試；不改 Health／Exit／Formal 與個股 UI。中央 Manual／Snapshot 請先提供精確補丁到自己的 handoff，交 root 統一整併。發現跨 owner 缺口時交付具體介面需求，同時繼續獨立工作。

1. 從 TWStockConfig／DATA_ROOT、資料庫 schema、更新器註冊、排程及實際 consumer 建立完整來源清冊。不要只看幾張日表。涵蓋專案實際存在的行情、指標、法人、融資融券、分點、公司資料、營收財報、產業與指數、公司行動、官方日曆與衍生資料；不存在的類型明示不存在，不新建假資料。
2. 每來源列出權威來源、頻率、資料期間、實際發布／取得時間、可得時間、預期最新期間、覆蓋率、內部缺日、重複及異常、下游、更新入口、任務與責任人。MAX(date) 不能代表全市場完整；停牌／下市／新上市與事件型資料須區別處理。
3. 日資料依官方交易日與實際發布截止判斷；月／季資料依公告週期；靜態與事件資料用最後成功檢查及有效期。檢查 `scripts/scheduled/data_freshness_probe.py` 的週末日期推算是否誤判假日／盤中，修成共用官方日曆。不得修改日期讓報表變綠，不得 forward-fill 偽造行情。
4. 逐項找根因並修復：未排程、漏接來源、parser 漂移、API 限流、錯DB／路徑、只更新少數股票、指標未重算、失敗吞掉等。重用 `app_module/update_service.py`、source status projection、現有 quick/full update 入口；不得另造一套平行更新框架。
5. 先唯讀與小範圍試跑，再執行合法來源的增量補齊。原始資料不刪除、不全庫覆寫；使用交易、可重跑 checkpoint、有限重試與速率控制。寫入前確認 DB schema、備份／恢復及 WAL 一致性。D 槽保留200 GiB，C/TEMP也檢查；不得與 Direct 爭用 heavy lock。Direct 的 frozen raw manifest／shards／依賴檔一律不可變更；需要刷新時產生不同版本，不能改正在建置的輸入。
6. 更新既有任務，查實際 task action、最近 exit 與產物，不新增重複任務。把 freshness 狀態接回既有更新頁資料模型，清楚區分正常等待公告、過期、失敗、不適用。
7. 用修補前後的真實有限讀回證明覆蓋率與新鮮度改善；測試假日、延遲公告、部分股票缺漏、API失敗、重跑與下游衍生更新。不得把 fixture 當自然成果。

完成標準：所有來源都有可解釋狀態；可取得的應更新資料已補齊，外部尚未發布者有正確原因與下次自動檢查；沒有默默失敗或僅因 MAX(date) 新而誤判完整。交付 `docs/06_qa/V4_DATA_FRESHNESS_HANDOFF.md`，含來源矩陣、修正、真實前後證據、測試、排程與剩餘外部限制；raw QA 放 ignored output，不提交DB。

## Prompt B：Direct 資料建置到可驗證 ML release

你是本專案 Direct／ML 資料鏈接手工程師。專案 `C:/Projects/PythonProjects/technical_analysis`，使用既有 local dev，先讀 AGENTS.md、目前 Snapshot、V4完成計畫、ML handoff、git exclusions 與資料／ML 架構。不得新增branch/worktree，不覆寫其他agent變更。你負責 Direct→OOC→release 的資料工程與驗收；不改 Exit、Health、更新器或UI，不做新 fit、fold-006+、promotion或券商交易。

任務不是重抓2014行情。Direct 將現有年度 raw PIT shards 轉成 ML 可分批讀取的數值特徵、標籤、索引與資料分割，避免全歷史巨大中間檔。從最早2014年處理是歷史樣本建置順序，並非現在行情停在2014。

1. 先讀 `output/v4_next_ml/direct_chain_rebuild_plan_20260908.json`、`direct_rebuild_launch_receipt_20260908.json`、`direct_dependency_freeze_qa_20260908.json`。最後已知實際builder PID23028、launcher2220；必須重新查 PID 的命令列／建立時間、heartbeat、checkpoint、stderr及產物，不靠舊PID或status=running判斷。現有 run 活著就接手觀察，不再開第二個builder。
2. 新根目錄是 `D:/Min/Python/Project/FA_Data/output/release_v4/portfolio_ml_direct_numeric_production_v4_v2-source-rebuild-79dccf8b7f0b`，舊目錄與raw必須保留。15項依賴凍結以QA清單為準，建置期間不得改這些source或切branch。檔案SHA與manifest canonical content hash不同，不得混用。
3. 驗證每年度checkpoint與block的hash、行數、型別、特徵schema、有效標籤、缺價／公司行動隔離、跨年度窗口及PIT cutoff。標籤可用未來結果，但不得進入決策特徵；split需purge／embargo且無未來標準化洩漏。不要把寫出檔案當全鏈完成。
4. 維持40 GiB暫存、35 GiB新增持久量及200 GiB安全保留，使用既有canonical OS heavy lock；檢查輸出與TEMP實際磁碟。容量不足先暫停可恢復階段，不能降低reserve或刪舊raw湊空間。
5. 若程序確認終止，先釐清錯誤與最後有效checkpoint，再按相同版本恢復。版本不相容時交root具體隔離方案，不混接舊標籤、不直接覆寫。等待timeout不是程序失敗。
6. Direct全部年度完成後，讀既有 downstream CLI 與計畫，先建立精確OOC／release preflight（來源、版本、預估峰值、lock、輸出及驗收），通過後沿既有受控流程完成資料release。遇既有明確核准Gate，將可直接執行的方案交root審核；同時完成不依賴核准的驗證。不得擅自跑fit或使用新的盲測fold。
7. 用實際consumer讀回驗證共享block重用、完整性、特徵與標籤有效性、teacher Gate及failure/resume。沒有合格teacher時如實標research-only並診斷，不重訓全現金來製造完成。

完成標準：可追溯的全年度Direct及經驗證資料release，或精確到外部Gate的可執行交付；清楚分開資料建置、模型訓練、投資成效三種狀態。以 `docs/06_qa/V4_DIRECT_RELEASE_HANDOFF.md` 交付年度矩陣、版本hash、容量、恢復策略、真實consumer證據、測試與下一步。低頻按階段觀察長程序，不反覆重跑相同測試。

## Prompt C：持倉／觀察清單的統一个股研究報告

你是資深PySide6工程師兼股票研究產品設計師。請在 `C:/Projects/PythonProjects/technical_analysis` 直接完成可用的個股研究介面，不只交設計稿。先讀 AGENTS.md、產品Roadmap、目前／目標架構、APPLICATION_MANUAL，使用 UI/UX 技能，沿用 ui_qt 設計與Qt模型。使用既有local dev，不建立branch/worktree，不覆寫別人的dirty檔。

你負責新的個股report DTO／read service／view與持倉、觀察清單下鑽入口及專屬測試。優先讀 `ui_qt/views/portfolio_view.py`、`watchlist_view.py`、`decision_desk_view.py`、`app_module/watchlist_analysis_service.py`、decision/advice composition與portfolio service。重用既有分析與建議邏輯，不在UI另寫股票評分。Health、Exit、Formal、Direct及更新器由其他owner維護，你只讀其公開契約；需要欄位時交付介面需求，先完成其餘區塊。

1. 盤點每種現有資料是否能按股票代碼取得，設計單一StockResearchReport資料契約：股票／市場、as_of、來源、資料日期與available_at、freshness、限制、可用模組。各區可各有日期，不能假裝所有資料同時更新。
2. 持倉與觀察清單雙擊／明確按鈕皆能開啟同一個股報告，可搜尋代碼、切股、返回原清單並保留篩選與選取。報告採單一入口、摘要加分頁或可展開區塊，避免一次堆滿原始表格。
3. 首屏提供個股摘要、最新可用價格、關注理由、主要風險、資料新鮮度、現有建議及依據。下鑽包含：價格／成交量／技術、基本面／營收財報、籌碼／法人分點、產業與事件、持倉成本／損益／曝險／Health／Exit、Rule與ML分析、歷史建議與後續結果。只展示實際有的來源；缺資料顯示原因及既有更新入口，不假造內容。
4. 建議呈現買進／觀察／續抱／減碼／賣出／資料不足等適用狀態，附觸發條件、反對證據、失效條件、適用期間及是否受持倉風控限制。優先映射現有Advice契約，避免新增互相矛盾的第二引擎。使用者接受研究中的不精準，但不代表可以捏造機率、價格、目標價、勝率或ML預測。
5. ML有結果才顯示模型／dataset版本、推論時間、研究或正式狀態、可解釋輸出；尚未訓練、全現金、過期或不合格時清楚顯示限制。Rule與ML不同意時分開列出理由。建議不觸發自動下單；既有持倉修改仍沿既有確認與記錄流程。
6. 真資料查詢用Qt worker、可取消、有限查詢与延遲載入，切股時丟棄舊request結果，避免A股票資料出現在B報告；不要載入整段歷史到主執行緒。SQLite只讀並確實關閉；核心金額用Decimal／整數，圖表float只在隔離視覺化邊界。
7. 做正常、空資料、過期、部分來源失敗、ML不可用、切股競態及真實有限樣本驗收；檢查鍵盤、文字與顏色共同表意、DPI／小視窗、長文字與圖表標籤。依repo要求跑UpdateView pytest、qa_validate_update_tab、指定全範圍mypy及changed Python py_compile；測試要證明入口與真service讀回，不只mock widget。

完成標準：使用者能從持倉與觀察清單打開同一份可互動的個股關注報告，看到現有資料與可追溯建議，缺失清楚且不阻斷其餘內容。交付 `docs/06_qa/V4_STOCK_RESEARCH_REPORT_HANDOFF.md`、畫面驗證、操作路徑、實際資料覆蓋矩陣、測試及Manual精確補丁供root整併。不要自行全repo commit；由root最後審核整合。
