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

## 第一輪分工

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
