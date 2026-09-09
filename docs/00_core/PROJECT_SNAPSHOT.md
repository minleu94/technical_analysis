# PROJECT_SNAPSHOT（必讀｜目前狀態）

## 2026-09-08 Luna 交付整合收尾

目前是工程整合與自然證據建立階段，**V4 尚未完成**。以下是目前狀態；先前逐輪測試、失敗與中途進度已移到歷史封存，不再把「早期待啟動」與「後續已中止」同列為現況。

|工作線|目前可採認範圍|仍待完成|
|---|---|---|
|每日資料更新|新handoff提供9/8 TWSE／TPEx／SQLite／market／industry／broker／technical對帳；root更新頁81項及QA25項通過|月營收正式apply、季報來源與availability、尚未啟用的candidate資料路由|
|Direct|新namespace已交付2014–2020年度manifest／carry驗證|2021因容量hold停止，2022–2026未完成；須重新核對live headroom，不能重複盲啟動|
|Formal／Paper|跨日與跨月工程、真producer隔離整鏈已交付；既有Paper自然執行曾獨立核對|自然0/3；9/9 capture仍卡9/8過期pending，須修caller選擇與同日合法來源，再驗共同時間證據。隔離3/3不折抵正式信用|
|持倉Health|政策→candidate→Paper entry proof→Decimal metrics→evaluator正例已交付；root相關整合套件通過|新版每日自然持倉證據；不回填舊三筆缺lineage持倉、不自動核准|
|Exit|producer與read model已修正mtime污染、實際／假設結果分離及扣成本計算；已接入既有每日Evidence caller，root相關36項通過|row-level可得價格證據及自然成熟結果；不自動交易|
|個股研究報告|持倉／觀察清單共用下鑽介面、唯讀服務、來源週期freshness與Manual已整合；root個股20項通過|可用資料覆蓋與合格ML provider；缺ML保留unavailable、不造結果|
|ML投資效果|自然前瞻與成熟審查框架存在|最近獨立採認26筆觀測、成熟0；不能以fixture或資料建置授予alpha／promotion|

## 本輪驗證與工作區

- root已通過：個股／UpdateView合計101 passed；更新QA25 passed／4 skipped；mypy585檔；Quant及ML shadow boundary；Exit／policy／candidate40 passed及Exit／caller相關36 passed（集合有重疊，不加總）。
- 完整pytest首輪5,031 passed／7 failed／4 skipped；7個失敗已全部修正並定向重驗通過。最新清冊／MCP／Paper隔離／Direct guard合計32 passed，Direct實際build／resume單項1 passed。保留首輪失敗紀錄，不把定向重驗改稱全套重跑全綠。
- 兩批共刪除2,469個快取／舊QA暫存、50,254,082 bytes。保留原始資料與持久證據；正式Manual已整併中繼補丁，現況與歷史文件入口已整理。
- canonical freshness已備份舊receipt並在實際時間重跑唯讀probe，24來源為7 current／2 stale／14 not_applicable／1 unknown。UI實際個股讀回可取得新版狀態；不是只有QA副本。
- 檔案說明／prompt提交 `31efeaa3`；資料、Direct、Formal、Health及排程核心工程提交 `c8dc5a7d`。個股介面提交 `9e25fc90`；手冊與整合驗收記錄另以文件提交保存；不stage output、DB、raw或工具產物。
- 保留main/dev與既有單一worktree；原始資料不得刪除，Direct與D磁碟持續保留200 GiB reserve。OOC／fit／fold-006+尚未啟動，券商交易與正式promotion未開放。

## 權威入口

- [本輪整合驗收](../06_qa/V4_LUNA_REVIEW_AND_WORKSPACE_CLOSEOUT_2026_09_08.md)
- [資料更新交付](../06_qa/V4_DATA_FRESHNESS_HANDOFF.md)
- [Direct交付](../06_qa/V4_DIRECT_RELEASE_HANDOFF.md)
- [個股報告交付](../06_qa/V4_STOCK_RESEARCH_REPORT_HANDOFF.md)
- [工作區分類與整理](../07_guides/WORKSPACE_FILES_AND_CLEANUP.md)
- [V4完成計畫](../07_guides/V4_COMPLETION_PLAN_2026_09_07.md)
- [版本成熟度](VERSION_ROADMAP_V2_1_TO_V4_0.md)
- [操作手冊](../07_guides/APPLICATION_MANUAL.md)
- [完整歷史封存](../09_archive/PROJECT_SNAPSHOT_HISTORY_2026_09_08.md)

本頁只維護目前狀態；詳細驗收命令、過程與限制保留在專項QA，歷史數字不改寫為本次結果。
