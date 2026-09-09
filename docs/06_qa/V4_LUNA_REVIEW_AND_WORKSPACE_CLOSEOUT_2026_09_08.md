# V4 Luna 交付複核與工作區收尾

本文件記錄 root 對三個新 Luna 任務及既有 V4 工程的整合驗收；不以工程通過代替自然前瞻成熟或 V4 正式完成。

## 本輪已獨立取得的證據

- 最新個股報告／導航／UpdateView整合：101 passed（6.42秒），其中個股報告20項、UpdateView81項。
- 更新頁QA：25 passed、4 skipped、0 failed。
- 指定全範圍mypy：585 source files，無錯誤；另有兩個既有 untyped-function 提示。
- 量化精度／未來函數靜態檢查：通過。靜態檢查不是全部策略行為的證明。
- ML shadow boundary：475 files、無違規。
- Exit producer／read model、forward policy／candidate：root 40 passed（2.28秒），含完整producer測試。
- 全pytest首輪：5,031 passed、7 failed、4 skipped、27 warnings（1435.47秒）。原始日誌 `output/v4_next_root/integration_pytest_20260908.log`。此為修補前首輪結果，不改寫成全綠。
- 修補後root重驗：清冊／MCP／Paper隔離／Direct dependency guard合計32 passed（118.36秒）；Direct年度實際build／resume／隔離OOC單項1 passed（131.03秒）。Exit producer／read model／scheduled caller／唯讀AST guard／CMD五套36 passed（1.63秒）。首輪7個失敗全部解除；未把定向重驗宣稱為重新跑完一次全套。
- 測試清冊：777／777，missing／stale／documented count drift皆零。
- 變更Python語法：190檔py_compile通過，使用獨立TEMP並清除位元碼。Direct已凍結15個dependency檔案位元組全部相符。
- Exit public CLI另以獨立TEMP實際執行缺來源負例：exit 2、blocked、research_only=true、formal_credit=false；只有receipt產生，未建立任何缺失來源DB。這不是自然Exit成熟證據。
- Assembler全檔：root 38 passed（23.39秒），包含拆出的進度回呼測試；1個既有loky實體核心數偵測fallback warning。
- 正式freshness接線：備份canonical舊receipt後，以當下時間唯讀重跑probe並寫回UI實際使用位置；exit 0、degraded、24來源、errors為空，7 current／2 stale／14 not_applicable／1 unknown。台北2026-09-09個股2330讀回價格／技術／分點fresh，月營收／季報stale，未修改原始行情或SQLite。

## 審查找到的整合缺口

1. 已修正個股報告把所有早於cutoff資料視為過期的問題。只採用同日、同data root／SQLite的來源週期證據，再比對個股自身資料期；無有效證據回報unknown。月／季、舊receipt、錯DB、全表current但個股落後及YYYYMMDD等情況均有測試。
2. 31個新增V4測試未登錄中央清冊與當前文件計數漂移已修正，歷史測試數字保留。
3. 三個新handoff的完成範圍不同：UI交付介面、Data交付daily閉環及基本面候選、Direct交付已完成年度與capacity hold。不得合稱全部V4完成。
4. Exit研究producer已接入既有05:15 Evidence排程caller，120秒timeout、子程序失敗可見，不新建排程、不回填歷史、不開啟自動賣出。單機ML registration XML／plan保留既有主機身份與重新查核條件，屬部署契約而非跨機通用模板。
5. Direct測試不再修改正式progress常數或替換會被fingerprint檢查的builder函數；以原始production constants驗證完整年度、carry、checkpoint及resume，並以discovery cache bytes／mtime核對重用。測試所用synthetic teacher與TEMP OOC只屬隔離fixture，不是正式D資料的新fit。
6. 財報排序已修正：先按資料所屬期，再按可得日取bounded rows；晚匯入的舊期不能擠掉新期，未來可得資料仍排除。2330實際讀回由誤選2014年底回到2023-Q4，直接唯讀SQL確認這是該股目前最新合法資料期，不以全表最新期冒充個股日期。
7. 新probe最初只有QA副本，UI仍讀canonical舊receipt的接線缺口已補齊。前後receipt與實際個股讀回分別保存在 `output/v4_next_root/freshness_canonical_before_integration.json`、`freshness_canonical_after_integration.json`、`stock_report_canonical_freshness_readback.json`。

## 必須保留的資料與未完成範圍

- Direct handoff記錄2014–2020完成、2021容量中止、2022–2026未完成；須核對live容量與版本後才決定安全恢復，不降低200 GiB reserve。
- 月營收正式表及季報尚未完成更新；PIT mapping候選、正式DB apply與官方公告來源是不同步驟。
- 個股ML結果只有合格provider存在時才能顯示；不能用UI佔位當模型完成。
- 自然Formal／Paper／Health／Exit與ML成熟樣本須用實際時間產物驗收，不能以fixture折抵。
- 台北9/9自然Paper capture仍回報 `pending_execution_session_missed:2026-09-08`；後續須在caller隔離過期pending並取得同日合法frozen recommendation，再驗證自然整鏈。這是實際操作缺口，不應全部歸類成單純等待天數；不回填舊event-time。
- `.venv`、原始資料、帳本、有效checkpoint與immutable evidence不作一般暫存刪除。

## 提交與清理

已分批提交交接／檔案說明 `31efeaa3`、核心工程 `c8dc5a7d`（199檔）、個股介面 `9e25fc90`（10檔）。手冊、清冊與本整合摘要另以文件提交保存。output raw、DB及工具目錄沒有加入Git；保留main/dev與單一worktree。最終遠端ref／工作樹讀回保存於本機 `output/v4_next_root/git_final_closeout.json`，並在本輪終局回覆報告。清理具體檔數／容量由 `V4_WORKSPACE_CLEANUP_CLOSEOUT.md` 記錄。

Root逐筆核對第二批manifest的145個路徑均位於指定 `output/qa/full_app_healthcheck_tmp` 且已不存在，對應666,244 bytes，越界0。第一批2,324個快取加第二批145個暫存，共2,469檔、50,254,082 bytes；不以仍在生成的全目錄總數差異推算刪除量。

另將20個經Git diff確認無內容差異的檔案刷新索引，消除換行／metadata造成的假變更；刷新前後staged檔案清單相同，未覆寫檔案或引入額外提交內容。
