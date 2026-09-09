# V4 持續完成計畫與驗收帳

日期：2026-09-07。狀態：進行中。這是本次使用者目標的執行與驗收計畫，不取代現況、產品方向或版本成熟度的 Scoped SSOT。

## 使用者目標與授權

持續迭代修復全專案、恢復先前無法取得的資料、移除不必要的強制人工審核，直到 V4 完成。根代理負責規劃與審核，實作與定向測試交由 `gpt-5.6-luna`／`max` 子代理。

人工批准不能再單獨成為可客觀驗證工作的阻擋理由。既有文件的「等待人工」應逐項轉成有版本、輸入雜湊、明確規則、結果與原因的自動判定；自動執行者不得冒充具名人類。保留實際來源授權、PIT、資料品質、自然時間、成交、成本、模型有效性與回退驗證；未具備的證據由生產流程補齊，不能以修改狀態值取代。

本目標不含券商自動下單、偽造歷史資料或績效、刪除原始資料。正式環境的可逆更新依已驗收的更新路徑與容量限制執行，不能把所有工作永久留在 fixture 便宣稱完成。

## 開場現況

- 前一輪已完成三面向清查，並有後續工程實作與 `4003 passed / 2 skipped` 的保存驗收；本輪以最新工作樹重新判讀，這不是本輪測試結果。
- D 槽本輪唯讀可用 bytes=`354755321856`，約 330.39 GiB；容量政策已有未提交實作，需核對跨階段與並行工作保障。
- 正式 ML inputs 仍有 0/3 的最近觀察；OOC diagnostic calibration 不能當成已載入推論的校準器。
- 工作樹有其他任務的 staged／unstaged 變更，且 Git 批次提交任務尚有進行中紀錄。本任務不 stage／commit，不覆寫其差異。
- External Validation Register 的 7/30 complete／automatic projection 是歷史，不能用來證明目前正式可用。

## 完成條件

| 項目 | 完成所需的權威證據 | 本輪開始判定 |
|---|---|---|
| 資料取得 | 正確官方來源成功回應、解析及來源雜湊；合理重試／無資料語意；隔離驗證後正式更新與新鮮度一致 | 月營收／財報恢復待執行 |
| PIT／來源接受 | 逐來源 license、available_at、coverage、quality、版本與用途限制的機器判定；不能 blanket accepted | 待自動化與真資料驗證 |
| 正式三項輸入 | 真正發布的因果投組帳本、Rule 快照歷史、PIT 產業成分；consumer 重新驗證 | 最近觀察 0/3，待重驗／生產 |
| 人工 Gate 移除 | caller 到 consumer 不再因缺人名而阻擋已有完整證據；自動身分與審核紀錄可追溯 | 子代理處理 |
| ML 交付 | 校準器實際接入、模型／特徵／缺值／來源 hash 綁定，研究與日常推論 frozen-row parity | 子代理處理 |
| ML 容量 | 全鏈持久新增＋暫存＋保留額、超額安全停止、重啟、並行與跨 run 重用實證 | 既有工程待審核，重用仍缺 |
| 推薦／配置 | 成本後、合理市場／產業／流動性 benchmark、樣本與不確定度；共享現金與等權比較 | 已有工程，實證未齊 |
| Portfolio／Paper | 可重播股數／現金／費稅、真實 producer 成交、對帳及正式儲存切換驗收 | 仍待完成 |
| Health／Exit | 分級動作、完整交易日曆、成熟避損／機會成本結果、風控不可被ML取消 | 工程已補，成熟結果未齊 |
| Drift／淘汰／回退 | 可判定訊號衰退、預先登記搜尋預算、無增益限制、last approved champion 回退實測 | 待全路徑審核 |
| UI／UX | 研究上下文、狀態翻譯、跨頁任務回饋、關鍵流程及鍵盤／縮放實機驗收 | 工程已補，實機未驗 |
| 正式運作 | 更新、Evidence、Paper、模型推論各自的實際工作結果與恢復；不是僅status檔或fixture | 待驗證 |
| 最終 V4 | 版本路線圖第6節八項成熟度逐項證據、完整適用測試、操作手冊與狀態一致 | 尚未達成 |

V4 的有效性證據不足時保持目標 active，不重新定義為「工程版 V4」結案，也不強迫沒有增益的模型取得非零權重。

### 自然累積的既有最低門檻（2026-09-08 root 程式核對）

`data_module/prospective_shadow_maturity.py` 現行定義為20個shadow days，5／10／20／60交易日各至少20筆成熟觀測。`ml_module/natural_shadow_pruning_evidence.py` 使用同一組常數，另要求每個horizon具有實際downside兩種類別、完整pruning metrics，以及一致model／dataset／policy身分；replay、backfill及合成outcome不得計入。這是既有審查入口最低門檻，不是V4八項成熟度已足夠的統計保證，也不更改原實驗設計。

因此不能排程20天後就自動宣告完成：60交易日結果須先自然成熟，再取得足夠不同決策日的成熟觀測。每日工作必須保存固定版本觀測、以官方交易日更新既有outcome，週期審查讀取同一sidecar；新版模型或政策不得與舊版混合湊數。各V4 Gate尚需逐項對應實際producer、consumer及事前門檻，缺失者先完成設計凍結，不以觀察到的績效反推門檻。

## 第一輪分工

### 2026-09-08 接續 ownership 更正（優先於舊交接）

**新持倉研究政策 root 審查決議**：已審核 `V4_FORWARD_MACHINE_POLICY_CANDIDATE_2026_09_08.md`，接受 macd_hist<=0／rsi<=30／adx<15 各產生reduce提案、20交易日觀察窗及5交易日自動review evidence cadence，僅為未驗證的前瞻研究假設，不授予投資有效性或自動交易信用。20日不是從Rule歷史窗口推導；macd_hist<=0只表示當下值，不證明穿越事件。Ops須先完成真policy producer→binder→Health evaluator隔離正負驗收，再依本次machine root授權保存實際可得時間、下一官方交易日生效的immutable policy及caller binding；舊entry不回填。移除固定人工review／未定義expiry的手動續期阻塞，保留可選人工覆核與明確supersede／retire；資料或日曆失效仍須經可驗證renewal恢復。尚未取得activation receipt，不能宣稱已啟用。

**Formal 跨月持續性（缺口與最新工程驗收）**：root讀回active binding 的 `FORMAL_DAILY_ROLLING_CALENDAR_BUNDLE` 固定archive只涵蓋2026-09-09至2026-09-30。後續已新增以原anchor雜湊串接不可覆寫successor的renewal，保留固定portfolio clock與環境anchor。root重跑 `test_formal_runtime_roll_forward.py`／`test_paper_execution_retry_runner.py` 共25 passed（2.12秒）；其中真capture fixture CLI→persist子程序→正式validator→TEMP移除後durable讀回正例獨立1 passed（1.31秒），其餘包含跨日、休市與link重用。測試HTTP來源為fixture，尚未有自然跨月成果；最終型態／文件／caller收尾由Formal owner交付，不能把25項隔離通過解讀為自然10月排程已成功。

**Exit 自然累積接續缺口（root程式核對）**：`ExitEffectivenessReadModel`／`ExitEffectivenessObservation` 的 repository 引用目前僅有模組及單元測試，尚無日常 producer／caller。隔離輸入一筆ready proposal（post-exit -800 bp）及一筆ready closed（+500 bp），現行report合併為ready_count=2、avoided_loss_count=1；這證明action_stage未分層，不代表正式歷史成果曾被污染。Ops在新持倉policy交付後，須接持久化proposal／實際退出lineage、官方交易日及當時可得價格的outcome producer，將提案反事實與實際退出成效分開，並接既有每日caller。只有提案存在，不構成Exit自然成效累積完成。

- Formal／Paper：負責 `paper_daily_execution_producer.py` 與測試、`run_paper_execution_daily_isolated.py`、capture scheduled script／CMD／註冊計畫，以及 `run_ml_allocation_copilot.cmd` 的canonical state預設切換。必須完成真caller接線，bridge CLI或契約不單獨構成交付。
- ML：負責Direct計算版本guard、續跑／替代資料建構計畫及ML前瞻；不再持有Paper writer。
- Ops：負責Health binding每日生產、consumer與Health CMD，不代持Formal capture入口。
- root：審核來源、測試及live註冊／部署讀回；不因舊ownership文字讓實作停在交接契約。

### 2026-09-08 每日帳本切換待驗收差異

**最新驗收更正**：下方為發現缺口時的紀錄。現行 Copilot CMD 已保留 D `OUTPUT_ROOT` 並將預設 Paper state 指向 repo canonical，EOD writer → durable capture → Formal consumer 隔離正例已通過；root 最新五套相關回歸為47 passed、1 skipped（3.73秒）。尚待自然日推薦／成交／隔日持倉承接，不再把預設路徑修改列為未實作。Formal owner 接續確認首次啟用日後的 roll-forward、週末與下一交易日，不以固定9/9測試代替長期日常運作。

root 重新讀取實際 CMD：`run_ml_allocation_copilot.cmd` 未指定覆蓋值時，仍讀取 `%OUTPUT_ROOT%/paper_portfolio/paper_portfolio.sqlite`，而 OUTPUT_ROOT 預設位於 D 槽。`run_paper_portfolio_daily.cmd` 的後續 writer 則使用 repo `output/paper_execution_eod_replay/paper_portfolio/paper_portfolio.sqlite`。因此目前不是同一帳本閉環，不能以 portfolio_id 相同視為已整合。

Formal owner 完成來源資格修補後，須將未來每日推薦的預設 state 接向上述 repo canonical state，保留 D 歷史來源唯讀及明確覆蓋參數；同時驗證推薦決策當下只能選到當時可得的 snapshot。部署前交付 CMD 差異與隔離 caller 測試，部署後核對 fresh-process 路徑、snapshot hash、推薦 receipt 與翌日成交承接。不要複製合併兩庫的歷史紀錄，也不要把新帳本回填成過去推薦依據。此項仍待實作，並非本節已完成切換。

1. `data_recovery`：定位並修復基本面取得；有界官方請求保存小型證據；先隔離測試。
2. `automatic_gate_review`：選一條具客觀輸入的人工 Gate，完成自動審核 producer／consumer 與負向測試。
3. `ml_release_completion`：接通單一線性 shadow 的校準與可載入 release，驗證 parity。
4. root：界定 owner、審核 diff／失敗案例／證據、合併驗收與安排後續輪次。

各子代理先聲明修改範圍，不改中央文件；專題報告分別為 `V4_DATA_RECOVERY_2026_09_07.md`、`V4_AUTOMATED_REVIEW_2026_09_07.md`、`V4_ML_RELEASE_2026_09_07.md`（尚未交付前不能作完成證據）。

## 文件與驗證規則

功能變動後同步 Snapshot、Manual、目前架構及相應 feature／QA 文件；人工政策改動另同步 Product／6M／Version 的相關條件，保存歷史而不回寫當年決議。僅在實作與驗收成立後更新完成狀態。

每輪先跑定向 tests、型態、語法與適用 quant/look-ahead 檢查，再依變更範圍做整合；UI 變更執行 repository 強制驗證。每個具體缺口保留已完成、待驗證、缺真實證據與可執行下一步，不把觀察逾時視為工作已停止。

## 根代理審核紀錄

- 容量單元測試本輪重跑：`6 passed / 1 skipped`，0.78 秒，TEMP 隔離雙根；skip 不當成驗證成功。
- 待修復審查項目：`directory_size_bytes()` 使用 `os.walk` 未提供 `onerror`，無法讀取的子目錄有被忽略風險；Windows junction 與普通 symlink 語意亦須分開測試。
- 待補保障：Raw 與 Direct/OOC 各有程序 lock，但目前尚未查到跨兩條流程的共用容量預留／互斥證據。三段式算式本身不能證明並行任務不超額。
- 現行容量 API 為舊 caller 保留 None 配額，scheduled 預設仍可退回20 GiB。正式操作需明確採有界政策，不能以可選參數存在宣稱預設已保障200 GiB。
- 根代理用 `unittest.mock.patch` 注入 `os.scandir` 的 PermissionError，實際呼叫 `directory_size_bytes(Path('tests'))` 回傳0，沒有拋出容量錯誤；未修改檔案或權限。此項已由疑點提升為可重現缺陷。
- 基線核對已推翻先前的 parser 根因猜測：舊 regex 可匹配官方 window.open 的第二參數形式；WinError10013 是沙盒網路權限問題。解析器此次增加市場、期別、官方路徑與引號變體驗證。官方 2026-07 月營收已解析 TWSE 992 筆、TPEx 859 筆；正式表停在 6 月的接續缺口是 candidate 抓取後尚無自動 intake／materialization。筆數與證據由資料專題 QA 保存，正式更新仍待驗收。
- 本次延續輪的前一輪分類為 progress：重新核對 D 槽可用 bytes=354755321856、確認 parser 根因誤判並修正後續方向、向三個仍執行中的子代理送出具體審核缺陷。尚未宣稱任何正式發布完成。
- 根代理獨立重跑月營收 harvester／availability tests：22 passed，1.16 秒，TEMP 隔離雙根，未寫正式資料。
- 自動來源審核施工中版本的負例已實測：coverage_bp=None 造成 TypeError；observed_at=2099-01-01 並重新計算封套 hash 後仍 machine_verified。已退回子代理補型態與決策時間檢查；在修復和重驗前不能視為可用審核入口。
- 自動審核另需補足子證據內容驗證與獨立覆蓋分母：雜湊格式、傳入的 approved／verified 布林及整包 canonical hash 本身不能證明官方來源、資料完整性或時間真實性。
- 入庫程式審核：`_iter_mops_snapshot_rows` 在缺 availability mapping 時直接略過，plan.raw_row_count 因而不是原始 snapshot 分母；自動 intake 必須揭露缺件且不可把部分入庫當全量完成。既有寫入刪除同股票／期別後重插，需補修訂保全與真實捕捉時間語意；今日 static 數值不能僅依首次公告日取得過去 PIT 信用。
- ML 新 release builder 已進入實作審核：需確認校準 base downside 後沒有把改變分布的向量直接交給以未校準 OOF 訓練的 Meta；研究／日常 parity 必須涵蓋 Meta 的實際輸入。另需真實有界 minimal run 的交付證據，不能只用 fixture 或舊 full run 的 metadata 改名。
- 根代理後續驗證：既有 registry／append caller／governance／P0 verifier 共30 passed（0.66秒）；新 machine review＋OOC release builder 共14 passed（29.13秒），均隔離雙根。這些定向結果不等於正式來源裁決或實際 ML 發布已完成。
- 根代理直接核對月營收 candidate CSV：1851筆，TWSE992／TPEx859，唯一期別2026-07，(market, stock_code, period)重複鍵0；檔案SHA256為585ddfcae282030f66459abd997b58294fb4b7a3e0dff3045d7c6540a3b67336。尚未以此宣稱歷史PIT或正式DB更新。
- 新增審核限制：目前 release test 的 expected 由同一 MLAllocationInferenceService 產生，只證明 loader parity；已要求以原始 OOC numeric→base→Meta 計算作獨立對照。月營收保留多版本後需同步驗證 consumer 的單筆版本選擇與台北時區／盤後可用性，避免重複聚合或日期倒流。
- 根代理定向 mypy（governance、registry、append CLI、OOC release builder、inference）在治理模組發現9處 int(Any|None) arg-type，已交回補實際型態縮窄；其他四個檔案本次未報錯。這是施工中失敗紀錄，未宣稱型態驗收通過。
- 月營收 backfill＋CLI 本輪10 passed／1 failed：舊成功fixture的mapping日2026-06-11早於capture可用日2026-06-17，被新PIT檢查正確擋下；已要求更新成功fixture並保留負例。ML修正另需保護legacy：原訓練服務Meta使用downside_probability_bp，不能為OOC raw向量而全域改變所有模型的輸入；應以artifact契約明確選擇。
- 上述失敗後續已重驗：governance／registry／append CLI 三檔mypy通過；backfill＋CLI＋fundamental SQLite provider 共19 passed（1.69秒）。這取代先前該測試組10/1失敗現況，但provider新增審核尚未結束：同日版本目前以source_version字串排序，雜湊大小不代表修訂先後；已要求真實序時或歧義阻擋。
- 最新ML builder／inference／adapter 17 passed（39.61秒），含原始OOC numeric batch及base／Meta独立重播；1個loky實體核心查詢回退警告。此驗證仍為隔離測試，不代表真實大資料release完成。
- root唯讀核對真實月營收隔離DB：2026-07共1849筆、可用日2026-09-08；完整候選1851=接受1849+缺官方對照2（2850、2883）。正式更新前需重跑冪等、cutoff不可見／可見與歷史revision不變性；目前唯一(stock,period)mapping會排除不同available_date舊版，已要求補版本化可得日證據。
- 容量新版本root用相同PermissionError注入重驗，已從錯誤回傳0改為StorageCapacityPreflightError；讀取失敗保護成立。新lock設計尚未接受：Windows os.kill(pid,0)有終止程序風險，stale rename仍有競爭，已要求OS檔案鎖；本機Python3.11.9缺isjunction API，須補reparse屬性辨識。未執行有風險的PID探測。參考https://docs.python.org/3/library/os.html#os.kill。
- 容量lock已改OS持有；root在Windows/Python3.11以TEMP與真實子程序驗證：parent持鎖時child=False，釋放後child=True，lock檔穩定保留。尚待wrapper共用路徑、程序退出釋放與junction完整驗證。月營收provider最新10 tests passed（1.38秒），包括追加mapping revision後歷史decision不變；正式更新仍待exact plan。
- 容量tests最新13 passed／2 skipped（3.61秒）。root追查junction skip實為cmd引號語法錯誤，非已證明平台不支援，已退回修測試。wrapper需取得鎖後重驗free，並保護真正maintainer存活期（包含既有owner／外層提前結束），不只鎖住短命launcher。
- 月營收六組合併測試最新53 passed／1 failed（2.47秒）：新prior_source_version保全測試缺apply函式import，已退回修正；備份／rollback實作仍在改動，正式D尚未更新。
- 後續重驗：backfill＋CLI13 passed（1.51秒），缺import已修；備份改SQLite API，仍待WAL/失敗回滾證據及Windows open-handle cleanup修正。容量14 passed／1 skipped（3.64秒），真junction已通過，僅symlink fixture權限skip，取代先前junction未驗狀態。
- root最新定向mypy使用explicit-package-bases，容量POSIX fcntl分支5個Windows stub錯誤、Direct numeric store line585因optional觀測值產生2個型態回歸，已交回修正；備份負例另要求保留backup後獨立commit，而非僅驗backup前資料。
- root獨立隔離負例：backup後另一connection commit值after-backup，apply注入寫入失敗，查回仍after-backup，rollback保全成立。該腳本exit1在TEMP清理（backup.db WinError32），不是交易assert失敗；backup verification使用sqlite connection context但未close，已要求顯式關閉並重驗，不將本次腳本算全通過。
- 上述連線占用修正後root重跑相同負例，after-backup保留、TEMP清理完成、exit0。容量／wrapper／月營收共7檔explicit-package-bases mypy通過。容量仍需child maintainer自身持有shared reservation，補wrapper退出而child續跑的生命期空窗測試。

## 後續輪次的具體接線

- 最新 root 跨檔恢復審查：月營收 recovery／backfill／CLI／mapping merge／provider 共37 tests通過（2.16秒），但現有 coordinator 僅於結尾寫 evidence，不能證明程序中斷後可恢復；失敗時無條件還原 mapping 也可能覆蓋其他 writer。正式套用前須補持久 phase journal、並行寫入保全、DB commit 後 evidence 失敗辨識及 crash/retry 測試。partial scope 另須綁定完整 snapshot 與 accepted/excluded 實際鍵集合，不只核對自填筆數。
- 正式月營收 apply 的 sandbox auto-review 已拒絕，理由為未辨識到正式資料變更授權；正式 D 資料未因該命令更新。保留具體預演結果並繼續不受影響的實作，不以其他寫入途徑繞過拒絕。
- 人工門檻接線審查：`formal_input_owner_packet.py` 的姓名只影響 packet 狀態；`inspect_program_readiness.py` 與 `program_readiness_projection.py` 僅呈現該狀態。替代流程必須呼叫正式 ledger／Rule history／sector consumer 驗證，保存發布與 custody receipt 後再產生機器驗證狀態；不得只修改 `owner_reviewer_required` 或既有 pending 文案。既有 prospective publisher 可供定位契約，但不可直接改名為歷史正式證據。

- ML fixture工程交付後已轉入真實derived release：h5 ridge／3 packs，重用parent final heads與fold001..004 OOF；新manifest保留full parent hash，重訓57欄Meta。預估OOF58.9MB、final meta約200273rows、校準84609rows；root設定新持久<=1GiB、temp<=1GiB、memory<=4GiB，D僅唯讀、新產物repo output。fold004 withheld評估須使用當時因果模型，不可拿看過目標標籤的final base當OOS。
- 月營收正式計畫允許1849筆有明確scope的partial增量，持續保留1851分母與2缺件，不以等待全數作人造卡關。正式apply前需修既有SQLite裸copy備份及rollback後整檔copy覆蓋風險；改一致性backup與transaction rollback，使用任務唯一備份且不清理舊備份。

- 來源裁決第一階段已交付 validator＋CLI＋registry metadata，子代理42 tests及mypy通過；尚未完整驗收producer。root核對capture／audit scripts未輸出新validator要求的producer／producer_code_sha256，須另接真audit轉換／生產，不能以fixture持有程式hash宣稱真來源鏈完成。該子代理已轉接容量缺陷與跨程序保護，下一輪再回producer。

- 來源自動裁決驗收後，下一條人工依賴是 `app_module/formal_input_owner_packet.py`：目前 packet_status 只因 owner／reviewer 兩字串而變化，並固定 owner_reviewer_required=true；需以三項真實 consumer 驗證、發布與 custody 機器紀錄取代名字門檻，不能只更改 projection。
- 週期證據目前由 `scripts/collect_v2_2_weekly_evidence.py`、`app_module/evidence_weekly_collection_repository.py`、`app_module/evidence_weekly_approval_input.py` 固定 pending_human_review 路徑；後續需保存歷史 pending rows 並追加機器審核事件，驗證真實期間與資料來源，不改寫自然經過時間。
- 月營收已有 `scripts/backfill_monthly_revenue_fundamentals.py` 與 `apply_mops_snapshot_monthly_revenue_backfill`；新流程應重用既有交易／備份／availability 驗證，先驗隔離 DB，再評估正式可逆更新。CLI 的明確 apply 旗標可由既有使用者授權執行，不需將它解讀成每次重新要求人工批准。

### 2026-09-07 根代理接續驗收

- 財報初始八家公司中，七家公司已形成可讀回的隔離資料：1101、1301、2303、2603、3105、3293、6547，共 1,070 筆。root 唯讀 SQLite `quick_check=ok`，主表與來源 sidecar 各 1,070 筆；首次／重跑 evidence 為新增 1,070／0，9/7 不可見、9/8 可見。1301 新版 candidate 的八個檔案雜湊均由 root 核對；2881 僅確認 step=2 可取得正確資產負債表，尚未完成整套 candidate／consumer，不計入完成。
- 姓名門檻改造：root 獨立執行 owner packet、machine consumer integration、formal readiness、program projection 四組，共 28 passed（1.94 秒）。實際三個 loader 的 TEMP artifact 可無姓名達到 3/3；同日尚未可得 Rule 快照拒絕，date-only ledger 採台北日期保守截止。這是隔離工程證據，不代表實際正式來源已達 3/3。
- ML confirmatory runner：root 最新 16 passed（0.94 秒）。覆蓋 request／parent／policy 變更阻擋、來源讀取失敗保留未知 exposure、讀完後發布失敗保留已讀狀態，以及 KeyboardInterrupt 後 started receipt 保留、重跑不得再次呼叫 reader。尚未讀取 fold-005；Direct 主 builder 的跨年及斷點恢復整合仍待驗收。
- v7 大小疑慮已排除：comparison.json 為 50,309,548 bytes，加 latest_comparison.json 842 bytes，整個 output 為 50,310,390 bytes；不是主結果檔被修改。不要因此重跑研究或重發布歷史結果。
- automatic_gate_review 已轉接實際日常 Rule／ledger／PIT producer；data_recovery 持續金融業與 universe 擴展；ml_release_completion 持續 Direct 恢復及 confirmatory 接線。正式 D 月營收 apply 的先前 auto-review 拒絕仍未解除，不以替代途徑繞過。

### 2026-09-07 後續驗收更正與未決項

- 本節更新前節的待驗收狀態，不改寫歷史產物。2881 的 `v4-quarterly-browser-2881-r13-sii-2881-2026q2` 已由根代理核對全部 11 個檔案雜湊。隔離 DB `quick_check=ok`，資產負債表 56、損益表 51、現金流量表 82，共 189 筆，來源 sidecar 189 筆；9/7 查詢為 0、9/8 為 189。首次與重跑紀錄分別新增 189 與 0 筆。初始八家公司因此完成隔離恢復；公告來源明確保留 browser DOM observation，不能當作 HTTP raw custody 或正式 D 寫入。
- Direct 跨年 carry 的真實 builder／resume／adoption 與定向測試已由根代理驗收，共 5 passed。fold-005 亦已執行且已讀取，不再稱為未見資料：28 個決策日、12 條比較路徑的整數權益／成本重新核算一致。研究 ML 路徑均無成交，Rule 為 +9 bp、Equal Weight 為 +66 bp；不據此提高 ML 權重或調整既有實驗後重跑。fold-006 以後未授權讀取。
- 新 60 特徵 v3 release 的 8 項定向測試通過，但根代理發現歷史市場差值可能以決策同日收盤計算，且相鄰觀測未證明為連續官方交易日。已交回實作者釐清時間語意、修正並新增防未來資訊測試；通過現有測試不代表時序安全。
- v3 release 另待補強強制共用鎖、執行中容量／記憶體觀測，以及原子更新 latest pointer 與發布失敗保全。preflight 的估計量不能稱為實測峰值或硬限制。
- 日常 PIT producer 已開始分開 capture eligibility 與 trading decision eligibility，方向符合收盤後仍可捕捉公司現況；尚待定向測試與實際來源讀回。真實 Paper fill 生產及正式三項輸入仍未完成，V4 不予結案。

### 2026-09-07 官方 PIT 與 Paper 時序接續驗收

- 官方 PIT 實際產物位於 TEMP `technical_analysis_pit_live_20260907_a1`。根代理已重新呼叫 `validate_machine_pit_publication` 與 `validate_machine_pit_receipt`，包含原始回應重建及來源驗證，兩者均為 `machine_verified`、1,984 筆。發布、receipt、operational 三檔雜湊亦與交付紀錄一致。仍是 current-day candidate，不具正式歷史 PIT 信用。
- 日常 PIT producer 的 12 項測試由根代理獨立通過，包含交易資格未知或休市時仍能完成公司資料擷取、發布與 consumer 讀回；不得以交易日門檻阻止現況資料擷取。
- Paper 已改接 T+1 開盤價、前一決策日成交量限制及 append 冪等。最新 14 項定向測試由根代理獨立通過（1.39 秒），包含成交當日全日量變動不改成交、盤中 10:00 不讀 EOD 行情／持倉而等待、15:00 後才進入保守延遲模擬。此路徑不代表盤中行情 custody 或即時成交。
- 日常運作尚未完成：新 EOD 排程仍依賴固定推薦檔環境變數、預設只產候選。已要求實作者補自然日待執行決策選取、持久處理紀錄與可觀測缺設定狀態，避免每日人工改路徑；正式帳本與整體 3/3 不因定向測試而自動通過。
- v3 ML 最新 13 項測試已驗收發布指標失敗後重試恢復；新版 preflight 記錄實際盤前時序及訓練／校準資料列不重疊。但目前觀察的輸出仍只有 preflight，尚無實際 release，不能宣稱模型交付完成。

### 2026-09-07 最新模型與 Paper 定向審核

- 根代理重跑新版線性 release 定向測試：16 passed（1.17 秒）。真實 release 已存在，取代前節「僅 preflight」現況；但 build_result 仍記錄推論時間契約失敗，不宣稱日常推論完成。
- 真實 training manifest 的父資料品質排除量為 fit 1,430 / 145,977、calibration fold-003 3 / 57,342、fold-004 859 / 57,666。程式對非有限、負值或非整數品質狀態採排除，未把 stale 改為 observed；仍須披露排除造成的覆蓋偏差。
- 容量 metadata 明載 sampling_and_stage_checkpoints，暫存範圍僅 producer_owned_temp_root_only；此證據不能推廣成程序硬記憶體上限或所有第三方暫存皆受控。
- 根代理重跑 Paper producer：21 passed（1.60 秒）。盤前既有 snapshot 已可作為首次盤後候選的輸入，週日推薦也改綁前一個已證明的交易日。但新 scheduler 測試仍以手造 state fixture 開始，未驗真盤前 producer、重試與隔日持倉承接；已要求補完整流程及現金／股數守恆。snapshot_transition_policy 舊文案亦需同步修正。

### 2026-09-07 真實研究推論與第十四家公司驗收

- 新 release `v3-linear-h5-67e0b583037dda60` 已由根代理使用正式 loader 獨立載入；identity 為 `sha256:904450b10bd131b225217f53f1148e1921318aa6d73fa54ec4475da9cc98039e`，模型 hash 為 `sha256:4efd05a6b84e0d2c6bf841703ecfb305eeef8aad30bf6725773aef784729a257`。舊 clock 失敗紀錄保留，不改寫歷史。
- 根代理僅載入凍結輸入並呼叫 `infer_research_shadow`，未重訓。11 列決策時間保留 `2026-09-07T18:00:00+08:00`；`payload_hash(result.audit_payload())` 完整匹配發布紀錄 `sha256:7e3070540453aabc9e7a69d0c1a32fdc1d925e7965c1faa8bdc33c41b9c6adc2`。輸出 cash_weight_bp=10000、正式 alpha=0、formal OOS=false；這證明研究推論可重播，不證明投資有效性或日常正式流程完成。
- adapter／inference service 的新研究入口正反例由根代理獨立重跑，共17 passed（13.55秒），含正式08:30限制、研究時鐘、target-free及晚到特徵／混合時間拒絕；僅loky核心查詢回退警告。真實 build 的RSS抽樣峰值769,716,224 bytes，仍非硬記憶體上限。
- 1259 的 `v4-quarterly-continuation-r3-1259-browser-xbrl-r2-otc-1259-2026q2` 已由根代理核對13個manifest檔案雜湊；隔離DB quick_check=ok，主表／sidecar各149筆，available_date均為2026-09-08。首次新增149，重跑新增0／既有149。累計14家公司隔離恢復，正式D資料與全市場coverage仍未完成。

### 2026-09-07 持久重播與部分成交接續驗收

- 根代理已使用內容定址 readback bundle `1f119043742d32976c206eed9b63220bc5c4c4002d35981f1684bc37ab9eadbf` 完成真實推論；以 Path.open guard 禁止原 TEMP input 讀取，觸碰為0。11列／33個expert輸出及完整audit hash均與既有發布一致。bundle邏輯檔案合計50,144 bytes，不包含已存在的模型release；此結果不代表全歷史訓練資料已去重。
- Bundle定向測試3 passed（0.33秒），驗證相同內容重用、移除fixture來源後可載入、可處理中斷與並行發布。KeyboardInterrupt測試不是硬程序終止證據，不據此宣稱硬中斷殘留均會自動清理。
- Paper真盤前producer→EOD candidate→append→retry→隔日snapshot及下一execution狀態承接已由根代理核對，兩檔31 passed（1.81秒）。後續新增委託級partial/rejected與現金結算處理後，producer／daily／ledger三檔37 passed（2.13秒）。仍要求補不依賴生產property的固定手算現金案例，且真實日常正式帳本與來源發布尚未完整驗收。
- 1264與1268 HTTP XBRL候選已由根代理分別核對11個檔案雜湊、隔離SQLite quick_check、主表／sidecar與重跑；筆數142與124，available_date均9/8，重跑新增均0。累計16家公司隔離恢復，不等同正式D或全市場完成。

### 2026-09-07 共享容量競爭測試審核

- 根代理獨立重跑 `tests/test_immutable_ml_block_store.py`：8 passed（1.15 秒）；pytest cache 寫入權限警告不影響測試結果。
- 新版 publisher 已在容量核對至發布完成期間持有 OS reservation。但目前不同物件競爭案例的第二份 bytes 較大，可能單獨即超出 probe 預算；測試通過尚不足以證明競爭保護。已要求兩份等長不同內容各自可發布，再同步競爭只能容納一份的配額，並確認失敗方在物件寫入前拒絕。
- 接入 PIT 時仍須保證同一 store 使用一致鎖，避免 caller 自訂不同 lock path 使總量保護失效。此片尚未驗收為完整共享容量保障。

### 2026-09-07 容量鎖與公開重試接續驗收

- 根代理獨立重跑 immutable block store 與 formal daily producer：28 passed（3.10 秒），其中 store 9 項、formal producer 19 項。
- 容量競爭案例已改等長不同 bytes，publisher 拒絕偏離 store canonical lock 的 caller 路徑；可接續 PIT 實際 builder 整合。測試仍可補雙程序 ready 握手，不能把 process is_alive 當成已同時到達競爭點。
- 正式輸入公開入口已可在原 TEMP Paper 來源移除後，驗證並重用持久 ledger publication；新增 ledger receipt 寫入失敗恢復亦通過。這取代前輪公入口被原來源缺失先行阻擋的現況；正式輸入 3/3 與自然日排程持續運作仍未因此完成。

### 2026-09-07 財報 r20 批次獨立讀回

- 根代理唯讀核對 1570、1580、1584、1586、1591、1593、1595、1599 八家隔離資料庫：batch manifest 與 DB SHA 全部符合交付摘要，SQLite quick_check 全為 ok，主表與來源 sidecar 分別為 126、135、155、125、110、145、146、143 筆，共 1,085 筆；available_date 全為 2026-09-08。
- r20 摘要 SHA 為 bf3af0ac42566731d00c352e6a4b0aff630601813c182a884e7428292e75d58d，綁定 universe plan hash 已核對。清單累計 29 / 1,974 家，仍有 1,945 家待處理；不代表正式 D 資料或全市場恢復完成。下一批八家已交原代理接續。


### 2026-09-07 財報 r21 與共享 ML 接線驗收

- 根代理獨立唯讀核對 r21 summary-r2 綁定的隔離資料庫：SHA-256 符合、SQLite quick_check=ok，主表與來源 sidecar 各 833 筆。1742、1781、1784、1785、1788、1796 分別為 134、131、146、153、141、128 筆，available_date 全為 2026-09-08。此結果不代表正式 D 寫入；1777 與 1780 延後處理仍應計入未完成母數。
- 共享 PIT 至公開 Direct builder 與 OOC consumer 的 bounded 接線已完成先前獨立驗收：Direct 4,588 rows／62 features／6 folds，OOC 18 experts／5 meta folds，manifest 與來源 lineage 相符。年度 numeric 與 OOC 產物仍是 run-local，跨次直接重用尚待下一片驗收；正式 alpha 維持 0，不據此宣稱投資有效性。
- 官方 PIT 持久 candidate archive 已完成先前獨立讀回：1,984 rows、consumer_verified=true、candidate_only=true、formal_consumer_compatible=false。排程已註冊與正式三項來源完成是不同證據；Rule 合法時窗、causal ledger 與正式 sector source 仍未全數完成。
- 本輪以 shutil.disk_usage 實查 D 槽剩餘約 310.7 GiB，總容量約 931.5 GiB；這是當下觀測，不是未來容量保證。持續使用 200 GiB 保留門檻與受控增量，不變更原始資料。


### 2026-09-07 三面向清查後的根代理驗證

- 根代理重新核對完整 Direct target 診斷：3,347,662 列、2,840 日期，配置目標全零／現金 10,000 bp，PIT sector 全缺。此為資料 eligibility 阻擋造成的 teacher 退化，不能解讀為模型學會避險；已交原 ML 代理實作訓練前語意檢查與未來正式輸入接續，並唯讀追查 h20 超額報酬極值來源。
- 根代理獨立執行 target diagnostics、statement factor pack、ML all-field snapshot、PIT year shard 四檔測試：23 passed（2.38 秒）；僅 pytest cache 權限 warning。不據此宣稱正式全市場資料或 ML 投資有效性完成。
- UI 現行 `_suggest_profile_for_regime` 在 confidence >= 0.7 時優先 high-risk Profile，已交既有 UI／formal 代理修正風險政策歸屬與信心語意，尚待交付及獨立驗收。
- 唯讀磁碟清查：D 剩餘 310.70 GiB、C 剩餘 234.06 GiB；D 正式資料根目錄 output 檔案邏輯大小 294.745 GiB，其中 release_v4 289.277 GiB／108,049 檔。邏輯大小不等同可回收空間，本輪未刪除、搬移或改寫 D 原始資料。現行研究授權仍為持久與暫存各 1 GiB、reserve 200 GiB；清查建議的較大配額尚未套用。
- 新 report_basis 接線定向測試通過；但 legacy 缺欄／空值預設 consolidated 的來源語意仍須確認，已要求資料代理避免未知範圍被默認成合併報表。


### 2026-09-07 r24／r26 隔離財報消費端獨立驗收

- r24 staging：根代理核對 consumer.db SHA 與交付相符，SQLite quick_check=ok，fundamental_statement_items／mops_statement_consumer_metadata 各 403 筆。
- r26：根代理核對摘要綁定的 batch、universe、三個 candidate／manifest、DB、marker、first／retry receipt 共 12 檔 SHA 全符合；SQLite quick_check=ok，主表／sidecar 各 361 筆，全部 available_date=2026-09-09。
- r26 綁定的 r27 universe 記錄 eligible 1,974、verified 54、unfinished 1,920；此為該版產物狀態，不代表後續批次現況。隔離 consumer 驗收不等於正式 D 資料已恢復，原始資料未改寫。三位既有代理執行中，持續處理資料缺漏、ML 語意 eligibility 與 UI／formal 日常流程。


### 2026-09-07 Profile 風險政策修復獨立驗收

- 原先 UI 以 Regime confidence >= 0.7 優先 high-risk Profile 的邏輯已移除，建議由 RecommendationProfileService 擁有。根代理發現的 selected early-return 預算繞過亦已修正：high selected + low budget、invalid budget、預算存在但缺 risk policy 均 blocked，保留 selected identity；Regime 不相容明示 incompatible。
- 根代理獨立重跑 Profile policy 與 UI profiles 測試共 16 passed（1.71 秒），僅 pytest cache 權限 warning。此接受範圍為研究 Profile 建議及 UI 原因呈現，不等同個人適配、績效或正式交易批准。
- 原代理接續自然 PIT／Rule／Paper 正式來源驗證，尚未以本片結果宣告 Formal 3/3 或 V4 完成。


### 2026-09-07 ML teacher gate 與價格極值審核

- 根代理重跑 target diagnostics／label extreme audit 共 13 passed（1.12 秒），並核對完整 teacher gate 與 h20 audit 兩份交付報告的 file SHA，均符合。
- 完整 parent 的配置 teacher 資料缺件拒絕已接在 OOC fit 前；尚須持續驗證完整正式輸入接續，不以阻擋本身代表 V4 完成。
- 3017 2026-05-20 h20 極值可按既有價格重算，但來源價格尺度異常尚未解決；已交 ML 代理追查原始來源與受影響範圍，修復解析根因或隔離不可信資料，不截斷、不猜比例、不修改 D 原始或舊 immutable artifacts。

## Root 補充審核：teacher 收據內容綁定仍未完成（2026-09-07）

Root 直接檢視 `data_module/portfolio_ml_target_diagnostics.py` 的 `_validated_teacher_input_provenance`：現行版本驗證 readback 檔案 hash，但尚未解析收據內容。`available_before_decision`、`readback_verified`、`read_only` 仍依 manifest 布林宣告；source identity／manifest hash 只驗格式，日期與候選數未核對來源實際內容。因此本批正向 teacher custody 尚未驗收，先前定向測試通過不可替代此要求。

已交付 ML 代理修補：驗證收據 schema 與實際來源綁定、逐日 availability／decision cutoff、實際候選涵蓋；加入任意內容搭配正確 hash、晚到來源搭配 true flags、來源 identity／日期不一致的拒絕案例。本次為程式審核發現，不宣稱已執行 exploit，也未變更正式資料或 ML 授權。三位既有代理皆經 live agent 查詢確認仍執行中。

## 2026-09-07 根代理驗收帳追加

- r53 bounded research recovery 目前為 `189/1,974` verified／eligible；其隔離 consumer
  與 receipt 已由根代理核對，仍不代表正式 D 全市場恢復。
- ML partial readback 由根代理完成 5 項定向驗收；這是受控 partial 產物的內容與
  custody readback，不代表完整模型 release、投資有效性或正式啟用。
- `baldr-paper-portfolio-daily` 已由根代理以 elevated readonly query 核對為
  `Enabled`／`Ready`，trigger 已更新為 Pacific 16:30；前後 XML、action、principal
  與 settings 保留證據見
  `output/scheduler_backups/baldr-paper-portfolio-daily_20260907_160825_comparison.json`。
  Last Run／Last Result 仍是既有觀測；尚未宣稱本次自然排程已成功執行或已形成正式
  Paper／Formal credit。

## 2026-09-08 持續目標啟動：自然累積與工程並行

使用者要求排妥真實累積的排程，工程持續迭代至 V4；root 只負責規劃與獨立審核，大量實作交給 Luna MAX。延續原完成條件，不改成工程版 V4 結案。本輪起點 `cc8dc787`、dev 乾淨；維持 main／dev，不新增 branch 或 worktree。

### 本輪分工與驗收責任

| Owner | 範圍 | 必須交付的實證 |
|---|---|---|
| v4_schedule_ops | 現有排程、自然窗口、重試與 weekly／shadow／Exit 累積入口 | live query、變更前後 XML、明確時區、輸入／輸出／逾時／回復契約、下一執行時間及實際產物讀回；不能只驗註冊成功 |
| v4_formal_paper | Formal 三來源 consumer、Paper 成交／對帳／跨日承接 | 真實發布路徑與受控設定一致；現金／股數／費稅守恆、冪等、crash retry、決策當時可得性；不能造出非現金交易或回填歷史 |
| v4_ml_evidence | teacher／來源內容綁定、實驗凍結、有效性、drift／回退 | 最高優先工程缺陷修補、獨立 oracle；先凍結後評估；沒有增益時限制模型，不強制非零權重 |
| root | 中央規劃、Scoped SSOT、跨 owner 接口與獨立驗收 | 逐項讀回 source／consumer／時鐘／SHA；將工程通過、自然等待、資料缺失、失敗與完成分開 |

### 即時觀測與下一動作

- 本輪首次正式 readiness 於 `2026-09-08T09:29:59Z` 驗證為 `0/3`；三個受控 path 都指向 `clock-20260819` 且 `prospective_output_not_published`。HMAC 與 store identity 已配置，沒有輸出秘密。證據：`output/v4_next_root/formal_readiness_baseline.json`。
- 第二次自然流程稽核讀到 19 份 Paper receipts，仍缺 terminal receipt；formal ledger／Paper fill source 缺檔，PIT 缺正式 sidecar／history 起點且同日多份 distinct capture。根稽核尚未提供 scheduler query，該條不得誤當排程未註冊；須由 ops 的即時查詢補足。證據：`output/v4_next_root/operational_baseline.json`。
- 已將上述實際缺口交給相應 owner；先查活躍程序與當日產物，避免重複啟動。新 clock／正式派生產物／受控設定須有明確發布計畫與回滾；原始 D 資料不修改。
- D 可用 `333659115520` bytes 為當下觀測；200 GiB reserve、既有持久新增／暫存預算與單一 heavy owner 維持。大訓練前由 root 驗收輸入充分性與預先凍結的實驗，不以容量足夠取代資料 Gate。
- fold-005 已在本文件前節記錄曝光，任何其他文件的「尚未讀取」皆不能用作新盲測依據；fold-006+ 讀取前須先確立新的凍結範圍與授權。不得重跑已曝光區間挑結果。

### 持續完成判準

自然時間工作必須留下實際交易日／週期、producer 與 consumer 收據，不把補跑或 historical replay 算成 elapsed credit。所有可客觀驗證的缺件都轉成有 owner 的修復／生產步驟；缺憑證、自然時間或正式來源時精確揭露並繼續其他獨立工程。最終仍逐條驗證版本路線圖第 6 節八項成熟度，未取得充分證據即維持目標 active。

### 本輪根代理審核追加

- root 於 `2026-09-08T09:35:11Z` 獨立 elevated query 確認 17／17 Windows 任務存在且 action 正確；Paper EOD 00:05 Pacific 早於行情更新 04:20 Pacific，對應目前台北 15:05／19:20，今天的缺源退出不能當成行情更新失敗。已交 ops 改為更新後處理、同日依賴驗證與有界冪等重試，保留 principal 與變更前 XML；06:00 Pacific 在目前時差是台北同日 21:00，部署後需驗 live NextRun 與 DST 邊界，不提前宣告成功。
- Formal owner 即時唯讀回報 `twstock.db` 最新行情為 20260907、20260908 尚無資料；Paper 為 27 snapshots／81 positions 且正式 trade ledger 尚缺。先查官方當日資料是否已可取得，不將自訂排程時間當成官方發布限制，也不造出缺源成交。
- teacher v2 source manifest 漏驗 schema／storage_mode 的修補方向已接受；root 獨立重跑 `tests/test_teacher_input_source_producer.py` 為 4 passed（`output/v4_next_root/teacher_review_1.log`）。此為契約修補，不代表正式來源已達 3/3。ML owner 下一步轉自然 shadow 特徵缺口、成熟結果消費及有效性／回退接線。

### 2026-09-08 Root 接續驗收與工作區異常

- Root 以實際當下 UTC 時鐘獨立執行 Paper legacy queue 完整 resolver，`output/v4_next_root/paper_queue_actual_now_review.json` 為 exit 0：選回 `scheduled_rec_20260907_051003`、reason=`pending_execution_retry`，19 份來源收據 hash 不變。跨日情境明確回報 `pending_execution_session_missed:2026-09-08`。此為佇列讀回，不是成交或自然期間信用。
- Scheduler retry reviewer 發現 any-marker 判斷可能讓缺源與 identity/schema 混合錯誤被重試；另 receipt 日期只驗不早於 target，尚缺未來時間拒絕。已要求 owner 補 terminal 優先、精確日期與負例；尚未准許據此部署。
- 本輪 live status 發現 21 個根目錄 tracked 檔案實際消失，包括 `.gitignore`、`AGENTS.md`、requirements 與測試設定。原因尚未確認，已通知全部 owner 暫停相關清理、提交及部署；不得把缺檔當成授權清理或順手 stage。先保全現況並查明來源，再依已知基線與 owner 回報決定精確恢復。未修改 D 原始資料。

- 接續 root 審核 `formal_controlled_handoff.py` 發現總 blockers 包含 current_readback_blockers；即使 proposed consumer/custody 完整，舊設定缺檔仍可能阻止 ready_for_root_review。已交 Formal owner 分離 current 診斷與新來源切換條件，補舊 0/3、新 3/3 正例及新缺件負例；此為靜態程式發現，尚待測試證實及修補驗收。
- 根檔恢復方案已授權 ML owner：限定 21 檔，HEAD 固定 cc8dc787，先備份 bytes/SHA，再確認 index 等於 HEAD、resolved parent 為 repo root 且目標不存在，以 exclusive-create 恢復。仍待執行結果與 root 獨立讀回，不以授權方案當成恢復完成。

### 2026-09-08 Root 恢復讀回及定向驗證

- 21 個根檔已實際恢復；root 逐檔確認 worktree bytes = HEAD blob = 任務備份 bytes，21/21 相符。獨立報告：`output/v4_next_root/root_files_restore_readback.json`。原因仍未查明，不覆蓋其他 dirty files，不把 Git stat/換行差異當成需重寫檔案的理由。
- root 對 retry runner、dependency gate、scheduler health CLI 三檔重跑：12 passed（1.54 秒）。Formal handoff、Paper ledger 與 append CLI 三檔：13 passed（0.93 秒）。前者仍缺來源 CSV→DB 同一性與完整時間拒絕驗收；後者 handoff 正例 mock consumer，只證明分類修復，不是正式 3/3。
- ML wrapper 已出現 PIT operational path 參數接線，尚待語意整合測試與真實有界 consumer 讀回。盤後05:20 Pacific排程不能冒充台北08:30前瞻決策，已要求跨 owner 分開盤前準備與決策捕捉，檢查實際完成時間。

- Root 真實唯讀 2026-09-07 source→SQLite helper 讀回：TWSE、TPEx 各 256/256 開盤價吻合，無解析錯誤；`output/v4_next_root/source_db_readback_20260907.json`。此為前 256 筆抽樣，不能推廣為待成交股票全部已驗或今日行情就緒，已交 ops 改覆蓋實際執行範圍。
- Formal handoff 新 consumer 缺件負例已加入；root 三項 tests 通過（0.54 秒）。實際新 plan 尚未提供 proposed paths/clock/identity，只是現況診斷；已要求 owner 交合法 producer 建立順序與精確輸出/命令，不能反覆產出空計畫代替來源生產。
- Root 確认既有 allocation 排程 caller 為 `run_daily_ml_allocation_orchestration.py --auto-catch-up`，不是 derived-shadow wrapper。已要求 ops/ML 對齊新 release、PIT 參數與 forward consumer；單純調整05:20 trigger不足以證明新推論接通。

- Ops 全檔 source→DB 修補經 root 真實唯讀重驗：2026-09-07 TWSE 1,095/1,095、TPEx 875/875 開盤價一致，無解析/讀回錯誤；`output/v4_next_root/source_db_full_readback_20260907.json`。這是昨日資料一致性，不是今日排程成功。Root 三檔 gate/retry/health CLI 再跑14 passed（1.47秒）。
- 已明確核准 ops 執行既存 Paper EOD task 的06:00 trigger及受測wrapper action限定修改，保留principal/settings並交XML與NextRun讀回。先前『已部署』回報已釐清為待執行，沒有以措辭代替部署證據。9/8 bounded quick updater 的執行計畫改由現有ops owner負責，不再交給不存在的data owner。

- Root elevated live `schtasks /Query` 已確認 Paper EOD Enabled/Ready、NextRun=2026-09-08 06:00 Pacific、正確 isolated cmd action；Interactive only、電池限制與1h timeout保留。LastResult=2仍是00:05舊執行，不能算新排程結果。
- Root 真實 loader `load_verified_rule_champion_snapshot_history` 以當下 cutoff讀取 `output/formal_daily_publications/rule_history/2026-09-08/manifest.json` 成功；SHA=f71a3e40a138570d25ed51bcf0f14cd57d21322acb1ae30afed6498128ac8f49。這是明確候選路徑的正式custody驗證，未更新受控三路徑、未取得3/3。
- ML wrapper 新fixture第一次root重跑為4pass1fail（缺output mkdir）；修正後root完整重跑derived shadow、daily orchestration、PIT publisher三檔26 passed（1.27秒）。真consumer在合成資料驗證available_at/effective_from及candidate權限，尚不代表自然forward已累積。

- Root 七個受影響來源檔的 explicit-package-bases mypy 发现11 errors：ops dependency/retry共10項object狹化、變數型別衝突；ML wrapper1項Path optional assignment。已交owner修補，未以pytest通過替代型態驗證。
- Root 檢查quick updater確認單日start/end不涵蓋技術計算範圍：technical caller仍start_date=None、120日lookback、全市場，另含broker/market/industry更新。已要求ops具體列範圍與容量，或交prices-only受測方案且標明partial scope，不直接假設单日參數即可安全執行整鏈。

- Root 同日未來收據隔離重現：observed=2026-09-08T13:00Z，quick checked_at=2026-09-08T23:59+08，gate仍ready=true、blockers=[]。`output/v4_next_root/future_receipt_probe.json`。已要求完整aware timestamp<=observed而非僅日期相等，未來/naive/malformed收據為terminal；不能以同日日期修補當時間安全已完成。
- Root 七檔mypy重驗：ML optional Path問題消除，目前排程兩檔仍10 errors，保持待驗收。根檔目前無deleted；三位代理持續處理中，不因單次等待timeout重啟。

- Root 釐清跨owner執行責任：Formal owner新增非scheduled PIT capture/publication、formal producer與identity/設定handoff範圍，ops持有scheduler與quick updater。不得將所有source生產推給ops或不存在的data owner。Root仍先審核具體有界命令再執行。
- ML owner實際TEMP舊PIT候選讀回回報publisher code hash mismatch，且capture晚於當日08:30。此尚為owner回報，不冒充root獨立驗證；已要求Formal以current code建立新真實來源，保留舊immutable artifact。優先準備下一合法決策日的available_at/effective_from，不能回填當日盤前信用。

- Root未來收據修補重驗：同樣23:59收據在21:00檢查已ready=false且含quick_update_receipt_checked_at_after_observed，保存`output/v4_next_root/future_receipt_fixed_readback.json`。真實D quick/freshness收據皆有aware checked_at，尚待fixture/整組驗收。
- Root最新mypy僅剩retry runner兩項list(object)狹化；另health CLI發現只改DATA_ROOT時output fallback仍固定D，已要求沿TWStockConfig語意推導resolved_data_root/output並補單一覆寫測試。

- Root跨三線13檔整合pytest為101 passed（5.21秒），七個受影響來源檔explicit-package-bases mypy全部通過；本輪已清除前述11項型態回歸。這是所列範圍驗證，不代表完整repository全測。
- Root已直接核准Formal執行現有capture CLI的具體步驟：全新系統TEMP目錄、--live --confirm-live-readonly、每官方endpoint最多4MiB、timeout30秒，兩個既有官方endpoint、實際時鐘、完整current scope，不寫D。不再等待重複空plan；取得publication/receipt/raw後先獨立讀回再接持久archive與下一合法日consumer。

- Root最新health CLI/gate/retry三檔18 passed（1.57秒）；已要求ops同步Manual排程段，保留Interactive only與電池條件的實際限制。
- ML owner釐清前一日盤後PIT捕捉可供下一日08:30，effective_from保留真實capture日，無需每日強迫同日capture；已轉Formal建立current-code publication/receipt/operational。現consumer只接受TEMP路徑，存在長期累積持久性缺口；已要求ML重用受控archive設計持久consumer並保持custody/時間驗證，不能任意放寬路徑或改寫舊artifact。

- Root elevated Win32_Process唯讀query未找到capture_pit_sector_membership_machine.py程序，已建立的v4_pit_current TEMP目錄仍空；已要求Formal讀回原exec結果，不能以agent running當capture仍在跑或以空目錄當成功。
- Root找到既有formal_daily_input_producer的archive/readback機制並交ML重用；同日盤前reuse入口的日期政策不可直接套用前日可見ML consumer，須保留明確manifest與decision cutoff。

- Ops bounded updater plan 已由root讀取：未批准額外手動full quick chain，因market/industry canonical與120日技術範圍尚無對應backup/容量驗收；引用ML raw配額不能代表此CLI已具備同等執行中guard。既存04:20task維持，避免重複；ops改做官方availability唯讀探測及自然run後驗證，失敗再按step修復。
- Root核准ML受控archive adapter，要求明確manifest＋受控root containment、兩來源branch互斥、archived_at<=decision與hashfreeze。拒絕把archive自述producer_code傳回expected hash來接受所有舊code的設計；未知code保持fail closed。先驗current-code新產物的持久讀回，未宣稱5份舊archive可用。

### 2026-09-08 官方 PIT 新捕捉 root 獨立驗收

- Root讀回Formal原命令結果：首輪WinError10013，下一輪TPEx回應不是UTF-8 JSON；後續新批次成功。舊空TEMP目錄不代表後續批次仍失敗，已校正觀測對象。
- 成功目錄為系統TEMP `v4_pit_current_20260908_102736862`；root實際重跑publication validator、receipt validator、operational consumer皆通過，1,984 rows，available_at=2026-09-08T10:28:09.898861Z、effective_from=2026-09-08，五檔SHA保存於`output/v4_next_root/pit_current_capture_readback.json`。
- current候選仍candidate_only=true、formal_oos_allowed=false、production_action_allowed=false；不能回填今日08:30信用。已交Formal持久archive、ML以此新產物驗consumer，避免重抓或修改舊raw/hash。

- Root持久PIT archive獨立讀回成功：`pit_candidate_archive/2026-09-08/85f71a355f707404-284d54b9ccedbfea/archive_manifest.json`，fileSHA=c2b838d9d79b794bc13b934c83f5f36f18c1b5828dead20ded9112de6745178f，1,984 rows，archived_at=2026-09-08T10:34:49.359908Z。報告`output/v4_next_root/pit_durable_archive_readback.json`。
- Root進一步用唯讀隔離probe阻止原capture TEMP的read_bytes：archive readback仍成功、原TEMP存取嘗試0、未移動刪除原檔。證據`output/v4_next_root/pit_archive_original_temp_unavailable.json`。此驗證Formal持久reader不依賴原TEMP，ML新adapter仍待TOCTOU/clock與公開接線驗收。

- Root 重新 live query 確認 Paper Portfolio 已改為 Pacific 16:15、Ready／Enabled；既有 action、Interactive only、電池條件與 72 小時 timeout 保留。獨立重跑 scheduler／registration／task names 共 24 passed；LastResult=0 屬舊 16:30 執行，不授予新排程成功信用。
- Root 實際呼叫新版 ML archive consumer，於 2026-09-08T10:49:34Z 讀回 1,984 rows，current-code／source custody／raw rebuild 通過，報告 output/v4_next_root/ml_archive_actual_readback.json；adapter 與 clock planner 的 mypy 2 files 通過。此為盤後 candidate 驗證，公開 forward caller 接線及 TOCTOU 負例仍待驗收，不計正式前瞻信用。

- Root 官方 calendar 新候選驗收：從 exact TWSE／TPEx response.bin 與 metadata 重建 2026-09-09 至 09-30 全部 22 日，days／source_responses 與 bundle 完全相等，bundle、manifest、兩份 raw 與 metadata 雜湊通過。9/9 兩市場均交易日。報告 output/v4_next_root/calendar_raw_rebuild_20260908.json；持久 clock 接線待續，不授予 formal credit。
- Root 重跑 official calendar 與 ML archive consumer 共 12 passed；已檢視 archive 驗證後替換 rows 的實際負例，以及刪除 fixture 原 TEMP 後成功讀取的正例。TOCTOU 修補在此範圍驗收通過，公開 forward 流程仍需整合驗收。

- Root 公開 ML wrapper 審查發現前瞻完成時間仍待補：目前 decision_clock 使用開始 capture_at，daily orchestration 可在耗時推論後先寫 shadow observation。已要求 owner 在實際 observation emission 邊界驗證 08:35 deadline，逾時保留 research 但不可取得 natural forward credit；不能只改 wrapper 最終 status。Ops 可準備 caller，待此驗收再部署。
- Root 最新 derived wrapper／orchestration／archive 三檔測試為 29 passed、1 failed：新增 archived-after-decision 負例因 Windows write_text CRLF 先觸發 noncanonical JSON，尚未驗到目標時間條件。已交 owner 修正 fixture canonical bytes 與時間次序，不放寬錯誤比對掩蓋問題。

- Root 已驗收 calendar durable archive 的 6 files hash／size 與 archive content／file hash；阻止原 TEMP read_bytes 後 custody inspector 仍 verified，原 TEMP 存取 0。證據 output/v4_next_root/calendar_durable_temp_unavailable.json。Formal 可繼續 clock／identity 準備。
- Ops 已獲 root 核准實作未註冊的 forward scheduler 準備件：Pacific 16:15 喚醒、真實台北 08:30 等待、明確 frozen config、TEMP operational 與 durable archive 來源互斥、逾時不補 forward。部署仍待 ML emission deadline 與 exact configuration 整合驗收；既有 05:20 catch-up 不變。

- Root 最新 ML shadow evidence／daily orchestration／derived wrapper／archive consumer 四個 suite 共 45 passed（2.28秒），四個來源檔 mypy 通過。前次 canonical fixture 失敗已修復。已確認慢 inference 在 collector 前阻擋，以及真 collector／repository post-INSERT 跨 deadline 引發 rollback、observations 為空。此完成時間防線在上述範圍驗收通過；Ops 可進入 frozen args 與 on-time 接線驗收，尚未授予自然 forward credit。
- 9/9 v4 clock candidate actual loader 與 file SHA 通過，報告 output/v4_next_root/clock_candidate_v4_readback.json；模型／特徵／policy 來源映射仍待查核。舊 v3 manifest 路徑實為 planning report，不得交 clock loader 或當正式來源。

- Root source mapping v2 已逐一核對八筆檔案引用全部匹配，證據 output/v4_next_root/clock_source_mapping_v2_readback.json。candidate_model／feature 原檔明確 disabled、training_performed=false、features=[]；9/9 clock 僅 Rule-only simulation，歷史 owner acceptance 不授予新 universe 或 ML 身分。
- Root 前瞻排程真 parser 接線已通過；修正 nested completion 與保留 outer wrapper safety status 後，wrapper／derived／orchestration 最新 38 passed。daily source hash mismatch 實際比對拒絕，不以 inner completed 蓋過 outer blocked_capacity。
- 每日 config producer 已在施工，尚待來源 age policy、已驗 hash 綁定、create-only 每日選擇與 actual frozen release／repo output 的整合驗收。首日 date-bound config 不代表長期累積已完成；新 forward task 尚未註冊。

- Root 9/8 quick 更新讀回校正：SQLite 日期為 YYYYMMDD，先前用 ISO 日期查到零筆是查詢格式錯誤。實際 20260908 共 1,961 筆；Ops 全量來源對帳的 1,958 筆有效開盤價全部吻合，freshness 排程尚未到時。保存 `output/v4_next_root/quick_20260908_market_date_format_correction.json`，不將舊零筆觀察當成入庫失敗。
- Root 已執行 forward Python wrapper `--preflight`：九項路徑存在、V2 release manifest SHA 符合固定 pin，沒有等待、建立日 config 或啟動 child。排程契約／wrapper／child 24 tests 通過；加入 preflight 後 wrapper／registration／feature diagnostic 另一組 24 tests 通過。批准 Ops 按 16:15 Pacific、InteractiveToken、IgnoreNew、PT2H 的已審 XML 新增 task，仍待 Windows 實際註冊讀回；不提前執行自然日前瞻推論。
- Root 重現 feature-gap diagnostic 的 compact date 驗證漏洞：20261399 被解析為 2026-13-99，已退回 ML owner。市場兩日 close 的數值存在只證明可計算，尚需官方相鄰交易日與 available_at 證據才能進入前瞻特徵；技術方向欄不得以補零或修改既有 frozen release 處理。
- Forward task 已於 9/8 11:43:54 UTC 建立，首次 XML encoding 不一致失敗後修正重試。Root 獨立 live XML 讀回確認 daily 16:15 Pacific、正確 repo action、原使用者 SID／InteractiveToken、PT2H、IgnoreNew 與電池限制；這是註冊驗收，不是自然執行成功。Root 另以真 CMD 注入錯誤模型 hash，JSON 正確 blocked 但 exit code 為 0，已要求修正括號內 ERRORLEVEL 提前展開及新增實際 CMD 負例。
- 後續 root 真 CMD 負例已回傳 exit 2、blocked、child_started=false；XML UTF-16 測試改用 XML 語意解析後通過。Formal producer 原本將尚未閉合區間的尾端 fills 全部拒絕，現改保留完整 custody、只發布已閉合區間。root 已檢視多日正例：首日讀兩筆成交、使用一筆且保留一筆 pending；次日使用兩筆、發布兩個 transitions。Formal／Paper source chain／forward registration／wrapper 四組共 45 passed（2.96 秒），三個改動來源 mypy 通過。此為隔離跨日工程證據，未增加自然交易日或正式輸入信用；21:25 Rule／Formal 時窗保持不變。
- ML compact date 修補已由 root 重驗：20261399、20260229 拒絕，20260908、20240229 正確解析，feature diagnostic 四項測試通過。後續仍需市場衍生值的官方相鄰日與可得時間接線。
- Root 實際 Windows task action 查詢與 caller 程式審查確認：既有 Formal task 只消費／驗證 Rule bundle，尚未排入每日 Rule source producer。已交 Formal owner 優先串接合法時窗內的 producer→consumer，不以 candidate runtime config 檔案存在當成已接線。
- Root 另發現每日 Rule clock 重置與帳本累積起點衝突：Rule producer 每日設定 activation_trading_day=target_day，ledger 卻要求 activation_day <= snapshot_day < observed_day；若直接採當日 clock，區間必然為空。已要求分離每日來源更新與固定 portfolio clock 起算日，補實際 scheduler resolver→producer→ledger 的跨日整合；不能只依固定 fixture 的 45 項測試宣稱日常累積成立。
- 9/8 freshness 自然排程於 05:00:01 Pacific 通過，行情／技術日期均 20260908、errors／warnings 空。Root 05:01:48 重新執行唯讀 Paper dependency gate，ready=true、blockers=[]、exit 0，保存 `output/v4_next_root/paper_gate_after_freshness_root.json`；06:00 EOD 尚待自然執行，不能先計成交。
- ML feature repair 新增雙年官方快取與讀取中 custody 變更保護，root 最新 10 tests 通過；實際 9/8→9/7 相鄰日再讀回使用官方快取、mid_read_revalidation=true、db_fallback_allowed=false，兩個快取檔案雜湊已綁定。此證明日曆來源接線，不代表當日前瞻輸入或新模型已發布。
- 今日 05:05 Raw PIT 自然任務由 Running 轉 Ready／LastResult=1，root live task 與 PID 查詢确认已終止。當次 log 為 DailyPriceSourceQualityError、4,476,508 candidate rows、builder exit 2；不是先前 log 內的成功 publication。本輪沒有手動重跑。
- Root 單日兩檔唯讀 probe（9/7、2330／6488）確認品質 guard 的兩個缺陷：all-universe caller 只傳 TWSE daily_price，6488 被判 canonical_daily_row_missing；改讀 daily_price_tpex 後，SQLite 990.0／1015.0／966.0／971.0 與 CSV 990.00／1015.00／966.00／971.00 被字串比較判為四欄不同，成交股數同為 8,393,000。程式第 454 行直接比較 payload 值，支持精度格式誤報根因。證據 `output/v4_next_root/raw_quality_market_route_probe.json`；已交 ML 修復市場路由與 Decimal 等值比較，Ops 補有界失敗分類摘要。此小樣本不能解釋全部 4,476,508 筆，仍須修後分類查核，不刪原始資料或 blanket 放行。

### 2026-09-08 Root 雙市場品質修補驗收

- Root 於 12:28 UTC 後獨立執行 quality／builder CLI／scheduled Raw／runtime config 四組測試：34 passed；quality、builder、scheduled Raw 三個來源檔 mypy 通過。這是定向驗證，不代表全域整合完成。
- 真實 9/7 單日唯讀雙市場 consumer：2330／6488 均 source_quality_pass，路由分別為 daily_price／daily_price_tpex，小數表示法誤報已解除。證據 `output/v4_next_root/raw_quality_dual_market_readback.json`。
- 擴大到同日全市場後，1,970 筆全部唯一匹配（TWSE 1,095、TPEx 875），missing／ambiguous／conflict 均 0；仍保留 1 筆 quarantine：6949 的 previous_close=1490.0、current_open=81.9，分類為單側尺度不連續，DB／canonical differing_fields 空。已交 ML owner 查核原始日期、市場及單位，不調低 guard 或推論全部歷史候選已修好。證據 `output/v4_next_root/raw_quality_dual_market_full_day.json`。未重跑 Raw builder、未寫 D 原始資料。
- Root 接續重驗 Formal runtime wiring／Rule producer：15 passed；Rule producer、runtime config、scheduled Formal 三檔 mypy 通過。新測試證明 exact predecessor paths 接線與盤前首建／盤中重用，但價格 loader／ranker 仍使用替身，不能算真實完整來源鏈；固定 portfolio clock 跨日 identity 仍待驗。已要求 owner 補真 SQLite fixture consumer 與 receipt 同次 bytes 解析／hash，避免將路徑接通誤認為正式 3/3。
- Root 查核長期排程依賴：forward config 的交易日／前一交易日判定均為 allow_online_probe=False；目前年度快取實際 captured_at_utc=2026-09-07T12:20:27.355937-07:00、expires_at_utc=2026-09-14T12:20:27.355937-07:00、max_age_seconds=604800。scripts/scheduled 尚無 capture_official_trading_calendar_cache／build_twse_calendar_cache／write_twse_calendar_cache 呼叫。已交 operations owner 核對及補有界日曆刷新前置流程，保持 immutable capture 與 expiry 拒絕，不以首日成功代表長期可運作。
- Root 審查雙市場路由新增效能風險：每筆 SQLite row 都呼叫當日／前日 route helper，而 helper 每次重建完整市場 symbol 字典，CSV cache 僅省去檔案解析。隔離三筆跨日 probe 共呼叫六次，5/19 與5/20各重建兩次；已交 ML owner 改按日期重用完整路由且限制快取範圍，避免全歷史處理乘上市場股票數。證據 `output/v4_next_root/raw_route_rebuild_probe.json`。首輪 fixture 連線延後釋放造成 TEMP cleanup 失敗，釋放後重驗 exit0；不把它解讀為正式 DB 問題。
- Root 更正前筆『未找到日曆刷新 caller』的範圍：搜尋漏掉 refresh_twse_calendar_cache；實際 Paper EOD isolated wrapper 在 scope preflight 後會呼叫 _refresh_calendar_cache，且使用同一 repo cache。仍有可重現時窗缺口：真實快取以假設 9/14 06:00 Pacific 讀取通過、同日16:15讀取因過期拒絕；既有refresh只在已過期時抓取，因此早上通過不能保障傍晚forward。唯讀 probe `output/v4_next_root/calendar_expiry_forward_gap_probe.json`，不算自然執行證據。已交 Ops 優先補涵蓋下次決策窗口的刷新或盤前前置，避免重複新增 task。
- Raw 雙市場工程後續 root 驗收：quality／builder CLI／scheduled Raw 三套共32 passed（4.14秒）；正式 caller 已預設明示 daily_price 與 daily_price_tpex。路由結果採8日期滾動快取，CSV層同步淘汰；root獨立走12日期後route8／CSV16（兩市場），保存 `output/v4_next_root/raw_route_cache_bound_probe.json`。此範圍解除重複重建及無界快取缺口；未手動重跑全歷史Raw，6949與其他歷史候選仍待來源查核。
- Formal 首建來源測試已進一步補齊：root 重跑 Rule source／runtime wiring／runtime config 三套22 passed（1.38秒）。新增案例使用真SQLite T-1 window與ranker，25個sessions／3個symbols，盤前首建與盤中重用重新驗consumer及source_window_hash；政策與日曆仍隔離注入。此取代前述價格loader替身缺口的現況，固定portfolio clock跨日identity及正式controlled handoff仍未驗收。
- 6949來源調查：root逐檔讀回8/26與9/7官方CSV保存檔，SHA均匹配且各唯一1row；close1490→open81.9及名稱增加星號與owner evidence一致。證據 `output/v4_next_root/raw_6949_csv_evidence_readback.json`。此僅確認原始觀測，不證明公司行動或調整比率；已交ML owner取得有界官方公司行動／面額變更證據，再做隔離candidate驗證，保留真實available_at，不回填歷史PIT信用。
- Root 最新controlled handoff／daily producer共27 passed（2.12秒），包含固定common clock與獨立daily lineage驗證。覆蓋限制：split lineage正例直接呼叫identity validator；data_module/scripts搜尋daily_rule_lineage目前僅handoff reader命中，尚無真producer manifest寫出證據。已交Formal owner優先接三项已驗receipt→固定common identity＋每日lineage→受控consumer，以及每日rolling config caller，不以手造identity測試當正式交付。
- 新forward日曆刷新前置已有五項隔離tests通過，但root實際CLI --preflight遭blocked：capture_script被錯套repo output containment，實際scripts路徑必然拒絕。已交Ops修正程式／輸出路徑各自驗證，並補跨年previous-session年度cache及刷新後expires>forward horizon檢查；此片尚未驗收，五項fixture通過不代表真CLI可用。未發網路、未建立cache或改Windows task。
- 日曆前置修補後root真CLI --preflight已ready、blockers空、writes=false、network_attempts=0，七項定向tests通過。程式檔錯套output containment已解除；新增按forward horizon選年度及新capture expiry覆蓋檢查。整體CMD／自然執行驗收尚待Ops交付，不能以preflight當成功刷新或forward信用。
- Root 真run_ml_allocation_forward_daily.cmd preflight整鏈exit0，日曆前置與forward兩段均ready/blockers空；release manifest pin仍c306c1ea…，無wait/config/child/network或資料寫入。
- Root品質全量digest probe通過：sample_limit=0與None的candidate_count/digest一致；未保存樣本的價格5→6改動會改變digest，count仍1、samples仍0。證據 `output/v4_next_root/raw_candidate_digest_probe.json`。最新quality／builder／scheduled Raw共33 passed（4.11秒）；正式exporter預設candidate sample上限64。已要求ML owner交具體有界全歷史唯讀分類執行，不觸發fit或Raw發布。
- Root 對日曆刷新前置、品質guard、PIT exporter、builder CLI、scheduled Raw五個來源檔重跑explicit-package-bases mypy全部通過。三位owner仍active，接續等待真producer identity與全歷史分類交付；未因等待timeout重啟任何工作。
- Root 獨立讀TWSE TWTB7U變更股票面額預告表，確認6949於115/08/27停止買賣、115/09/07恢復，變更前10.00、後0.50、換股率20.00000000；與ML candidate吻合。來源 https://www.twse.com.tw/exchangeReport/TWTB7U?date=undefined&response=html&selectType=undefined 。這是當下官方頁觀測，未證明9/7決策前可得；已要求ML保存原始bytes／metadata／hash與版本receipt，再做受影響symbol/window隔離及新來源契約，避免用價格比18.19當換股比或回填歷史PIT。
- 全歷史品質分類已實際啟動：root elevated CIM確認PID56572／子33128存活，開始12:52:36UTC，命令audit_ml_daily_price_source_quality.py、2014-01-01至2026-09-07、雙source roots、ingest_guard、sample_limit64、repo output摘要；不跑Raw publication／fit。子程序當下working126,615,552、peak127,762,432、private603,070,464 bytes、CPU164.515625秒，屬觀測非硬上限。後續等待同process結果，不因timeout重啟。
- 6949官方receipt持久證據root驗收：兩份HTTP response＋metadata共4個SHA皆匹配；直接解析TWTB7U換股率20＝10/0.5，MI_INDEX唯一6949開81.90／收67.10；receipt file SHA 0e8800dd…吻合。證據 `output/v4_next_root/raw_6949_official_receipt_readback.json`，不授予歷史availability。
- 全歷史品質稽核已終止，log END12:56:09 UTC／exit2（quarantine），原兩PID已missing。Root讀回2014-01-01至2026-09-07共5,295,781 routed rows、17,830候選：SQLite invalid16,892、CSV mismatch827、missing55、both-scale33、canonical-scale23。64樣本、621,045 bytes報告，全分類/日期總和與candidate_count一致，report hash重算通過；摘要 `output/v4_next_root/raw_full_history_readback.json`。原自然Raw失敗使用不同截止日，不據此直接計算修復率；下一步分類正常不可交易缺值與真錯誤，不補零、不blanket放行。
- 06:00 Paper自然排程已由root live查核：LastRun=2026-09-08 06:00:01 Pacific、LastResult=0、NextRun=9/9 06:00。新receipt recorded13:00:06.868388UTC，使用9/7凍結推薦、9/8執行日；root真SQLite唯讀逐欄匹配8筆委託紀錄（6全成、1部分、1拒絕，7筆非零股數），candidate檔案SHA吻合，獨立Decimal重算cash161,526.11與projection相等。證據 `output/v4_next_root/paper_natural_eod_20260908_readback.json`。這是自然工作產生的delayed EOD Paper replay，不是券商成交或盤中custody；event_time_proven=false/research_only=true，尚不授予Formal 3/3，9/9固定clock也不能回溯採認9/8。
- Root Paper政策範圍審查：今日receipt宣告weekly_turnover_cap_bp2000，但post_execution_projection.turnover_bp7457；producer僅將config投影，未見PaperPortfolioPolicy.evaluate／weekly_turnover_used接入。cooldown另明示research不套用。本次帳務驗收不代表風控全通過；證據 `output/v4_next_root/paper_natural_policy_scope_review.json`。已交Formal owner在common identity收尾後補正式paper風控及enforced/diagnostic政策揭露，保留今日immutable research receipt。原始fill gross計算的換手與reference逐筆bp口徑不同，不把數值差異直接判為帳務錯誤。
- Common identity producer已加入，但root隔離負例證實generic source receipt驗證層仍接受observed_at=2099及錯誤result.file_hash全0（當下observed為2026）；證據 `output/v4_next_root/formal_identity_receipt_binding_probe.json`。此只測receipt層，不代表完整三source consumer通過。已交Formal補receipt實際時間／source hash與ledger portfolio clock／Rule window匹配後再形成common identity，不能僅對傳入clock重新貼標。
- Root依owner全量分類調整修復順序：16,892 invalid分成15,445筆literal --與1,447筆NULL／空價格。用途限制可直接依observed price_unavailable成立，不要求先推定每筆停牌／掛牌原因；已交ML實作保留原始列/日期/missing mask、排除受影響feature/label窗口的新研究contract，嚴禁drop後錯接相鄰日期、補零或放行真正mismatch。分佈報告為owner產物，root未重跑全量SQL，不冒充獨立全量查核。
- Operations日曆前置已完成root定向驗收；後續分工改由Ops在app_module獨立實作Paper policy adapter及tests，Formal owner保留daily execution producer接線。兩者須先對齊真ledger週換手／冷卻／sector contract，避免讓Formal common identity與風控完全串行；今天immutable Paper receipt不改寫。

### 2026-09-08 收據與政策接續審核

- Root 已重驗 common identity 的收據時間與來源雜湊修補：正常收據接受，2099 未來收據與錯誤來源 file hash 均拒絕，隔離探測 exit 0。證據 `output/v4_next_root/formal_identity_receipt_binding_recheck.json`；這只涵蓋 receipt helper，真實三來源、共同 clock 與跨日受控接線仍待整鏈驗收。
- Root 獨立重現 Paper policy adapter 的未來資料干擾：同一 9/8 context 原為 ready，追加 9/9 fill 後因日曆缺少未來日期而變 blocked。證據 `output/v4_next_root/paper_policy_future_row_probe.json`；已要求先依決策可見性限制資料，再驗證當下狀態。另待同一 SQLite transaction 的內容 digest（含 WAL 可見列）、官方日曆完整區間與批次 cash／turnover／sector reservation，不能以單一候選各自通過取代整批風控。
- Root 重跑價格可用性契約與來源品質兩套測試，19 passed。另獨立重現只提供 feature window、label window 未提供時，horizon_expansion_required 卻為 false；證據 `output/v4_next_root/price_window_partial_contract_probe.json`。已要求分開兩類窗口完整性並驗證真正下游消費，不以診斷旗標宣稱缺價窗口隔離已完成。
- Operations 05:15 自然 evidence dry-run 的 portfolio_alert／risk_prompt sections 仍缺來源，已排入 policy adapter 後續 producer 接線；不把 exit 0 或 degraded 當成正式 evidence ready。Direct maintainer PID 44380 本輪 Get-Process 確認仍存活，未停止或重啟它；存活本身不代表訓練已開始或完成。
- Root 最新三線定向測試曾為16 passed（Formal receipt四項、Paper adapter七項、price availability五項），涵蓋未來列先隔離、batch turnover reservation及部分window完整性。另真SQLite WAL探測確認主DB檔SHA不變時，新增已提交列0→1仍改變transaction rows digest；證據 `output/v4_next_root/paper_policy_wal_digest_recheck.json`。
- Formal 新增三來源build/read整合測試後，root本輪結果為4 passed／1 failed，失敗為Rule Champion history store identity mismatch。已交owner釐清producer／consumer store配置與runtime根目錄，不能放寬identity guard解決；先前helper通過不代表整鏈可用。Paper另須驗partial/rejected sell不替後續buy提供未實現現金。
- Formal 三來源整鏈修補後 root 重跑5 tests全部通過：PIT測試helper覆寫Rule store環境，恢復正確producer store後，三source producer→identity build/read→controlled handoff plan成功，且future identity拒絕；未放寬正式consumer。此為隔離工程驗收，非真實正式輸入3/3或受控環境已切換。
- Paper adapter／原policy／CLI root最新18 passed，涵蓋批次換手與產業額度、不提前釋放未成交賣款、重複symbol及WAL。執行producer尚待接線；實際partial/rejected sell後的現金與產業曝險必須依成交重验，不能靠預期賣出降低曝險便放行後續買入。
- Operations owner已交付穩定Paper policy adapter，root交付後重跑adapter／原policy／CLI為18 passed（2.69秒）；owner另報20項含其交付範圍，兩數不混用。Formal owner承接execution接線，Ops轉入05:15 Evidence缺portfolio_alert／risk_prompt真來源與Direct外層狀態投影修補，維持三線平行且不重啟現有Direct流程。
- Root缺價整鏈測試由33 passed／1 failed修復為35 passed（1.41秒）；原測試以ISO字串匹配YYYYMMDD來源導致gap未注入，修正後通過。另source品質新負例尚未修復：SQLite open95/highNULL、CSV open195/high'--'時canonical整列被丟棄，missing-only研究豁免錯誤成立。root重跑已完整清理TEMP、exit0；證據 `output/v4_next_root/raw_partial_missing_mismatch_probe_clean.json`。不能以35項既有測試授予這項新路徑完成狀態。
- Direct live查核已穿透venv launcher：實際builder PID34224持續CPU計算，OOC helper等待Direct store，release等待OOC；未新發布store manifest。當輪D可用313,038,200,832 bytes（約291.54 GiB）；屬當下可用量觀測，不是全流程峰值或額外heavy啟動授權。證據 `output/v4_next_root/direct_live_process_readback_20260908.json`。
