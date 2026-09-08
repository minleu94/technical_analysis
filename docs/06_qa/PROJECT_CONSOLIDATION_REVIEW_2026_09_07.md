# 專案整併、架構判斷與後續交付（2026-09-07）

> 歷史查核補註（2026-09-08）：以下保留三線開工前的查核、數量與失敗紀錄；後續修補及最終全域驗證請看 [LUNA 三線整合驗收](LUNA_INTEGRATION_CLOSEOUT_2026_09_08.md)，不要將下列舊失敗數直接當成目前狀態。

本輪已完成全 tracked tree 的結構／重複掃描，並實際整併可證明冗餘；**不建議整套重寫，但需要優先修資料／ML 方法、依賴邊界與測試隔離。** 清理相關驗證通過，不代表整個專案健康：全量 pytest 仍有41失敗與31初始化錯誤，詳見下方分類。

這是基於 `dev`、commit `71500ef6fc834da285c19255e5c03f1846412329` 的查核；開始時工作樹乾淨。本輪沒有 commit／push，正式 D 原始資料、既有模型及 scheduler 未修改。

## 1. 已完成的專案整理

| 項目 | 清理前 | 清理後／處置 |
|---|---|---|
| 全 tracked tree | 2,268檔；docs433、tests775、scripts333、app275、data139、UI83、ML55 | 掃描所有 tracked 檔的路徑與可解析 Python；局部深讀高風險責任鏈 |
| 整檔重複 | 只有一組五個相同小型 `__init__.py`；沒有>15行的整檔 AST 重複 | 保留必要package marker，沒有用相同hash當作刪除理由 |
| 函式重複 | 37組至少15行的相同AST候選 | 先整併確認相同的三個SignalCombiner分析方法；其餘須分辨獨立契約／oracle |
| 分析程式 | 兩份SignalCombiner各自複製組合／volume／合成流程 | 抽至 `analysis_module/signal_combiner_support.py`，兩條舊入口與不同政策保留 |
| 測試程式 | 兩份相同欄位契約測試 | 合成一份參數化測試，仍覆蓋兩入口；增加多空、volume、ADX差異、缺值與不修改原輸入驗證 |
| 失效診斷 | 七份固定路徑／外部API／失效runner，加重複README | 移除8檔；準確檔名及回滾見本報告末段 |
| 測試納管 | filesystem748／inventory679，漏69檔 | filesystem740／inventory740；support含既有ml_teacher_fixture；缺漏／失效／計數漂移均0 |
| 預設pytest測項 | 4,639 | 4,645；少8個Python檔但沒有犧牲雙入口覆蓋 |
| 文件 | 分類文件約480行，包含多輪重複current與過時清單 | 收斂為單一目前摘要，逐檔清單交由registry維護；舊全文可從baseline或精確備份還原 |
| 導航／架構 | 導航複製舊空間／preflight狀態，架構複製舊scheduler／ledger狀態 | 保留責任／入口，將可變狀態導回當次證據；同步Inventory、Navigation、Index、coverage map |

精確總數：**刪除9檔、新增6檔（共用程式1、查核與交接文件5）、修改13檔**；有效專案檔案由2,268變2,265，Git尚未提交所以 `git ls-files` 本身仍含待刪除路徑。修改範圍內Python淨減 **432行**，包含清冊補登與新增回歸案例；大型輸出不在這個數字內。這次主要收益是責任與清冊正確，並非釋放大量D槽空間。

保留：`ui_app/`明示legacy相容入口、兩種SignalCombiner的不同回測、14份manual／6份外部scripts的隔離邊界、`docs/05_phases/`／`docs/superpowers/`有引用的歷史、所有原始資料與既有evidence。未刪除使用者的ignored cache／output／venv；未檢查到直接引用不等於動態使用不存在。

### 驗證結果與實際限制

- 定向：雙入口分析與清冊治理 **20 passed**。
- 舊／新 parity：兩模組各20組seeded DataFrame，**40組輸出完全一致**；留下的initializer、可靠性、回測、圖表方法逐AST一致。
- 機器清冊：**passed，740／740，4645 collected**，missing／stale／documentation drift／collection error全部0。這個passed只代表清冊，不代表測試行為全部通過。
- 型態：本輪四個變更來源檔mypy通過；六個變更Python檔py_compile通過。全有效tracked／新增Python共1,720檔，AST parse錯誤為 **0**。
- 文件與變更：388個本地Markdown連結全部存在，精確28個planned changes皆符合檔案存在／刪除狀態，git diff --check通過。
- 全量：**4,570 passed、41 failed、31 errors、3 skipped、67 warnings，411.41秒**。隔離DATA_ROOT／OUTPUT_ROOT，Qt offscreen；沒有UI程式修改。
- 獨立重跑非容量問題集合：12 passed、5 failed；確認Workbench三項、dependency guard一項及固定D路徑測試一項仍可重現，非只由全量測試執行順序造成。

| 全量未通過分類 | 數量 | 證據與處置 |
|---|---:|---|
| 實體容量依賴 | 35 failed +31 setup errors | 小型ML fixture在C磁碟要求200GiB保留量，實測C約176GiB；raw/ooc preflight拒絕。production保護正常工作，測試缺可控探針；交B修測試隔離 |
| 固定路徑測試假設 | 1 failed | Fubon CLI測試假設D永遠是formal root，本輪DATA_ROOT已隔離；應驗configured root拒絕，不放寬path guard；交B |
| ML依賴規則衝突 | 2 failed、對應3條邊 | producer反向依賴app adapter；inference新rank／family contract不符已定義邊界。交A檢查共享契約／loader方向，不直接豁免guard |
| Workbench來源／審查投影 | 3 failed | expected source status／future snapshot警告／readiness_source_gaps不符現行輸出；已獨立重現，根因尚待契約級定位；交C |

上述失敗涉及本輪未修改的產品／測試路徑；依賴違規也在未修改的ML／app檔案中。未在另一個完整baseline環境重跑全部suite，因此不把所有失敗都無條件宣稱為「與本次整理完全無關」。本次抽取的輸出parity與定向測試提供較窄且可審查的無回歸證據。

本機證據：`output/qa/project_consolidation_20260907/` 的 `inventory_before.json`、`inventory_after.json`、`tests_before.json`、`tests_after.json`、`signal_combiner_parity.json`、`pytest_full.log`、`non_capacity_failures.log`、`mypy_changed.log`、`rollback_manifest.json`。原始QA輸出保持ignored，不當作長期文檔複製保存。

## 2. 是否需要重大改變

**不需要推翻PySide6／服務／Domain／SQLite／OOC底座。需要的是有範圍的架構修正，以及把開發重心從「更多功能」轉為「可用資料、可驗證決策與穩定操作」。** 現有容量治理、immutable lineage、release adapter、Decimal／bp、PIT及方法凍結已投入實作；重寫會重付成本，也無法解決缺來源或失真的target。

以首席架構／資料科學家與股票分析師的共同角度，最重要的五個問題如下。

| 優先度 | 問題與依據 | 為什麼影響投資／工程 | 改進與完成標準 |
|---|---|---|---|
| P0 | **資料可用性與可學習target。** 既有紀錄的3353096列配置teacher全現金；價格尺度／PIT／candidate接受程度會改變可用輸入 | 訓練程式能跑不代表在學投資判斷；缺資料回落不能變成正確配置標籤 | 驗收現有teacher gate／收據內容，按來源和決策日列涵蓋分母；小型真實鏈路先通，再考慮放大 |
| P0 | **研究有效性與工程通過分離。** 舊fold-004比較曾受撮合／跨年視窗問題影響，新增guard也不會讓舊結果自動有效 | 修程式後重跑已曝光區間仍是探索，不能當新OOS；模仿Rule不等於超越Rule | 既有freeze／exposure ledger前置，panel按日切分和label maturity；同成本同股票池比較Rule／Cash／Equal Weight，獨立重算 |
| P1 | **依賴方向與大型責任集中。** 真實guard報3條違規；UpdateView5628、OOC trainer5284、UpdateService5001行 | 同名入口／跨層依賴增加修改擴散；一條修補很難判斷影響哪些流程 | 修正窄版共享契約／loader邊界；逐個責任seam拆分並保留facade／oracle，避免整套重構 |
| P1 | **測試／文件治理追不上提交。** 缺69份登錄，重複current，且全量現在未通過 | 大量test與長文檔不等於可靠；新agent容易重做已完成工作或把局部綠燈當整體成功 | 本輪已修清冊與分類文件；下一輪建立fixture隔離、依賴環境constraints、單一摘要與機器校驗 |
| P1 | **日常研究到行動的資訊成本。** Workbench三項投影契約未通過，數據／研究／formal狀態散落多頁 | 使用者要自己拼「資料能不能用、這個比較是否相容、接著做什麼」；風險是誤讀結果 | 先修來源投影，再串資料準備→候選假說→比較／觀察三流程，狀態有理由和可執行下一步 |

本輪特別避免重做三項已存在但文件仍有「待完成」敘述的工作：Direct volume carry、confirmatory freeze runner、teacher receipt內容綁定。程式與測試已存在，不代表全量正式輸入驗收已完成；下一輪先判定實作／定向測試／真實鏈路各自完成程度。

### 從股票分析師角度的開發方向

先讓每個研究結論能回答五件事：當時可知的來源是什麼、候選池與交易限制是什麼、優勢是否超過成本與簡單基準、失效情境是什麼、下一次觀測何時能推翻假說。優先改善資料與比較證據，暫緩新策略數量、深度模型／大型搜尋、更多dashboard與自動交易。

SignalCombiner的0.5／0.7／0.9是手設分數，其中一版還受ADX乘數影響，不能呈現為50%／70%／90%成功率。兩份legacy回測使用不同策略語意與輸出，存在同日訊號成交及float等歷史邊界；這次只消除重複，不暗中替換投資算法。

### UI／UX五項下一步

1. 修來源狀態／缺口投影後，讓資料日期、基準日及scope在跨頁保持一致。
2. 以資料準備、候選研究、比較／觀察三條流程組織資訊和主要動作。
3. 把hash／schema／Gate技術細項放可展開層；首層保留投資理由、反例、缺漏與下一步。
4. 比較表固定揭露股票池、期間、費用／成交假設和benchmark；不可比較時指出差異。
5. 在真實窄版／DPI／鍵盤流程驗證loading、失敗、取消、context保留，沿用現有theme而非另做一套。

這五項是本輪來源／程式查核後的設計方向；本輪沒有重新操作全部native UI，因此不宣稱已完成逐畫面視覺驗收。C工作包明確要求實際渲染與截圖。

### D槽與ML接入

D本輪剩餘333659123712 bytes，約 **310.744GiB**。現行central reserve是200GiB；scheduled新增持久35GiB加暫存40GiB，要求275GiB。因此觀察時只比此門檻多約35.744GiB，**不適合讓三個agent同時各開一條大型ML鏈**。

採已有OOC／shared immutable block、小型線性release與有界base comparison；先修teacher／特徵／split，按同卷承諾量及實際暫存峰值做reserve檢查。standalone仍使用既有1GiB持久／1GiB暫存預設，不為此報告提高配額。C也不足200GiB，不能用搬去C來繞過保護。

時間切分與train-only preprocessing的外部方法核對，以及可重現ML發展階段，統一放在[三線計畫](../07_guides/LUNA_PARALLEL_PLAN_2026_09_07.md#建議的-ml-發展順序)。模型本身小不代表整條資料鏈占用小；沒有執行期容量探針／reservation不能保證未來空間。

## 3. 可以直接開新對話的完整規劃

先審閱並將本輪清理保存為共同commit，再開三個獨立worktree：

| 工作線 | Prompt | 最先處理的問題 |
|---|---|---|
| A：資料與ML | [完整Prompt A](../07_guides/LUNA_PROMPT_A_DATA_ML_2026_09_07.md) | 三條依賴衝突、現有資料／teacher／freeze驗收、小型真實研究閉環 |
| B：架構與QA | [完整Prompt B](../07_guides/LUNA_PROMPT_B_ARCHITECTURE_2026_09_07.md) | 容量／路徑fixture隔離、重複治理、可重現依賴與清冊／文件整合 |
| C：UI／UX | [完整Prompt C](../07_guides/LUNA_PROMPT_C_UX_2026_09_07.md) | Workbench三項失敗與三條研究流程、真實UI測試、Manual同步 |

每份是約10–12小時的工作容量，不是保證模型連續執行的時數。Prompt含所有權、真實初始問題、里程碑、時間預算、不可讀OOS／正式寫入界線、驗收與checkpoint。只跑兩線時先A+B，C後接；跑三線時A為唯一資料密集worker，完整QA分時執行。

共同啟動／契約／容量／整合規則見[總計畫](../07_guides/LUNA_PARALLEL_PLAN_2026_09_07.md)。完成後帶回三份handoff、branch／commit、test summary及manifest，再做獨立審查；不只看agent自己的完成宣告。

## 清理前標準回滾清單


於 repo 根目錄執行各列 PowerShell 指令。若刪除檔案的父目錄也已不存在，先用 `New-Item -ItemType Directory -Force` 建立該父目錄。不得未比對就還原後續他人修改。逐檔原始 SHA-256 與備份保存在 `output/qa/project_consolidation_20260907/rollback_manifest.json`；備份不提交。

| 檔案路徑 | 變更類型 | 原因 | 可執行回復步驟 | 風險 |
|---|---|---|---|---|
| `tests/manual/legacy_diagnostics/README.md` | 刪除 | 淘汰固定路徑的一次性診斷／整併重复測試 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/tests/manual/legacy_diagnostics/README.md' -Destination 'tests/manual/legacy_diagnostics/README.md' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `tests/manual/legacy_diagnostics/check_columns.py` | 刪除 | 淘汰固定路徑的一次性診斷／整併重复測試 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/tests/manual/legacy_diagnostics/check_columns.py' -Destination 'tests/manual/legacy_diagnostics/check_columns.py' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `tests/manual/legacy_diagnostics/check_processed_file.py` | 刪除 | 淘汰固定路徑的一次性診斷／整併重复測試 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/tests/manual/legacy_diagnostics/check_processed_file.py' -Destination 'tests/manual/legacy_diagnostics/check_processed_file.py' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `tests/manual/legacy_diagnostics/check_saved_file.py` | 刪除 | 淘汰固定路徑的一次性診斷／整併重复測試 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/tests/manual/legacy_diagnostics/check_saved_file.py' -Destination 'tests/manual/legacy_diagnostics/check_saved_file.py' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `tests/manual/legacy_diagnostics/check_signals_file.py` | 刪除 | 淘汰固定路徑的一次性診斷／整併重复測試 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/tests/manual/legacy_diagnostics/check_signals_file.py' -Destination 'tests/manual/legacy_diagnostics/check_signals_file.py' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `tests/manual/legacy_diagnostics/run_market_index_test.py` | 刪除 | 淘汰固定路徑的一次性診斷／整併重复測試 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/tests/manual/legacy_diagnostics/run_market_index_test.py' -Destination 'tests/manual/legacy_diagnostics/run_market_index_test.py' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `tests/manual/legacy_diagnostics/run_technical_calc_test.py` | 刪除 | 淘汰固定路徑的一次性診斷／整併重复測試 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/tests/manual/legacy_diagnostics/run_technical_calc_test.py' -Destination 'tests/manual/legacy_diagnostics/run_technical_calc_test.py' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `tests/manual/legacy_diagnostics/run_tests.py` | 刪除 | 淘汰固定路徑的一次性診斷／整併重复測試 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/tests/manual/legacy_diagnostics/run_tests.py' -Destination 'tests/manual/legacy_diagnostics/run_tests.py' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `tests/test_pattern_analysis/test_signal_combiner_column_support.py` | 刪除 | 淘汰固定路徑的一次性診斷／整併重复測試 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/tests/test_pattern_analysis/test_signal_combiner_column_support.py' -Destination 'tests/test_pattern_analysis/test_signal_combiner_column_support.py' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `analysis_module/pattern_analysis/signal_combiner.py` | 修改 | 共用完全相同的分析流程、補正測試納管、收斂文件權威與導航 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/analysis_module/pattern_analysis/signal_combiner.py' -Destination 'analysis_module/pattern_analysis/signal_combiner.py' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `analysis_module/signal_analysis/signal_combiner.py` | 修改 | 共用完全相同的分析流程、補正測試納管、收斂文件權威與導航 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/analysis_module/signal_analysis/signal_combiner.py' -Destination 'analysis_module/signal_analysis/signal_combiner.py' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `tests/test_analysis/test_signal_analysis_column_support.py` | 修改 | 共用完全相同的分析流程、補正測試納管、收斂文件權威與導航 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/tests/test_analysis/test_signal_analysis_column_support.py' -Destination 'tests/test_analysis/test_signal_analysis_column_support.py' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `tests/test_full_app_healthcheck_test_inventory.py` | 修改 | 共用完全相同的分析流程、補正測試納管、收斂文件權威與導航 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/tests/test_full_app_healthcheck_test_inventory.py' -Destination 'tests/test_full_app_healthcheck_test_inventory.py' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `qa/full_app_healthcheck/test_inventory.py` | 修改 | 共用完全相同的分析流程、補正測試納管、收斂文件權威與導航 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/qa/full_app_healthcheck/test_inventory.py' -Destination 'qa/full_app_healthcheck/test_inventory.py' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `tests/manual/README.md` | 修改 | 共用完全相同的分析流程、補正測試納管、收斂文件權威與導航 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/tests/manual/README.md' -Destination 'tests/manual/README.md' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `docs/07_guides/tests_readme.md` | 修改 | 共用完全相同的分析流程、補正測試納管、收斂文件權威與導航 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/docs/07_guides/tests_readme.md' -Destination 'docs/07_guides/tests_readme.md' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md` | 修改 | 共用完全相同的分析流程、補正測試納管、收斂文件權威與導航 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md' -Destination 'docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `PROJECT_INVENTORY.md` | 修改 | 共用完全相同的分析流程、補正測試納管、收斂文件權威與導航 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/PROJECT_INVENTORY.md' -Destination 'PROJECT_INVENTORY.md' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `PROJECT_NAVIGATION.md` | 修改 | 共用完全相同的分析流程、補正測試納管、收斂文件權威與導航 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/PROJECT_NAVIGATION.md' -Destination 'PROJECT_NAVIGATION.md' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `docs/00_core/DOCUMENTATION_INDEX.md` | 修改 | 共用完全相同的分析流程、補正測試納管、收斂文件權威與導航 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/docs/00_core/DOCUMENTATION_INDEX.md' -Destination 'docs/00_core/DOCUMENTATION_INDEX.md' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `docs/00_core/DOC_COVERAGE_MAP.md` | 修改 | 共用完全相同的分析流程、補正測試納管、收斂文件權威與導航 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/docs/00_core/DOC_COVERAGE_MAP.md' -Destination 'docs/00_core/DOC_COVERAGE_MAP.md' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `docs/01_architecture/system_architecture.md` | 修改 | 共用完全相同的分析流程、補正測試納管、收斂文件權威與導航 | `Copy-Item -LiteralPath 'output/qa/project_consolidation_20260907/backup/docs/01_architecture/system_architecture.md' -Destination 'docs/01_architecture/system_architecture.md' -Force` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `analysis_module/signal_combiner_support.py` | 新增 | 共用實作與本輪查核／三線交付計畫 | `Remove-Item -LiteralPath 'analysis_module/signal_combiner_support.py'` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `docs/06_qa/PROJECT_CONSOLIDATION_REVIEW_2026_09_07.md` | 新增 | 共用實作與本輪查核／三線交付計畫 | `Remove-Item -LiteralPath 'docs/06_qa/PROJECT_CONSOLIDATION_REVIEW_2026_09_07.md'` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `docs/07_guides/LUNA_PARALLEL_PLAN_2026_09_07.md` | 新增 | 共用實作與本輪查核／三線交付計畫 | `Remove-Item -LiteralPath 'docs/07_guides/LUNA_PARALLEL_PLAN_2026_09_07.md'` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `docs/07_guides/LUNA_PROMPT_A_DATA_ML_2026_09_07.md` | 新增 | 共用實作與本輪查核／三線交付計畫 | `Remove-Item -LiteralPath 'docs/07_guides/LUNA_PROMPT_A_DATA_ML_2026_09_07.md'` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `docs/07_guides/LUNA_PROMPT_B_ARCHITECTURE_2026_09_07.md` | 新增 | 共用實作與本輪查核／三線交付計畫 | `Remove-Item -LiteralPath 'docs/07_guides/LUNA_PROMPT_B_ARCHITECTURE_2026_09_07.md'` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |
| `docs/07_guides/LUNA_PROMPT_C_UX_2026_09_07.md` | 新增 | 共用實作與本輪查核／三線交付計畫 | `Remove-Item -LiteralPath 'docs/07_guides/LUNA_PROMPT_C_UX_2026_09_07.md'` | 須整組還原；先比對後續修改，避免覆寫其他工作。 |

## 文件覆蓋計畫

| 範圍 | 文件 | 本輪處理 |
|---|---|---|
| 程式邊界 | system_architecture.md | 記錄 SignalCombiner 共用流程與差異 |
| 測試 | tests_readme.md、分類清冊、manual README | 移除失效路徑，保留非破壞執行規則 |
| 導航 | PROJECT_INVENTORY、PROJECT_NAVIGATION、DOCUMENTATION_INDEX、DOC_COVERAGE_MAP | 登錄查核與交付入口 |
| 使用者功能 | APPLICATION_MANUAL | 本輪未變更 UI、參數或金融算法，不需改寫操作步驟 |
| 產品／工程方向 | 既有 Scoped SSOT + 本輪 companion | 不另造版本完成宣告；後續工作驗收後才更新 current |

## 先驗影響檢查

- 共用三個逐 AST 完全相同的方法；不改訊號日期、評分、回測、金融計算或決策時點。兩條舊匯入路徑均保留。
- 七份診斷檔僅由清冊／文件與治理測試提及，非 pytest 收集或產品呼叫；四份固定 CSV 印欄位、兩份外部／正式目錄診斷、一份已不存在 test_data_module 的 runner。
- 合併欄位測試以參數化覆蓋兩個入口；不得只保留單一入口的測試。
- 69 份清冊缺漏先依職責登錄；write-risk 與 UI candidate 不得因此自動進 direct bridge。
- 驗證：定向測試、全量 pytest、機器清冊與 collection、Python 語法、diff 與新增／修改 Markdown 連結檢查。
