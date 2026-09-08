# Prompt C：投資研究 UI／UX（LUNA MAX）

以下全文可貼入獨立 worktree 的新對話。模型選 `gpt-5.6-luna`、`max`。

---

你是本專案的資深投資產品 UI／UX 工程工作線 C。我授權你完成以下約10–12小時工作量的設計、實作與真實 UI 驗證。請持續做到可操作與可審查，不只給設計建議或新畫面草稿。時間是規劃容量，達到驗收即可結束，不用增加無關功能湊時數。

先讀 AGENTS.md 要求的文件、APPLICATION_MANUAL、`docs/07_guides/LUNA_PARALLEL_PLAN_2026_09_07.md`、本輪 project consolidation review、ui-ux-pro-max 技能及 repo UI／QA規範。採繁體中文，保留既有 PySide6 主入口與設計系統。若 available UI工具不能操作 native app，使用 repo 已有 offscreen smoke／screenshots 實際渲染，不把只讀 QSS 當視覺驗收。

**目標：** 讓日常研究者能回答「目前資料能用嗎、今天先看誰、這個建議為什麼、接著做什麼」，並可看懂不可用／研究限定／證據不足的狀態。優先完成三個現有流程，不另開大型 dashboard。

**所有權：** `ui_qt/`、UI測試、UI QA腳本與 `docs/07_guides/APPLICATION_MANUAL.md`。`app_module/` 僅 `workbench_source_service.py`、`workbench_read_only_composer.py` 為既有 Workbench 契約修復例外，其餘服務／DTO、data、ML與金融領域均只讀。不能把計算／查DB／動態掃來源檔加到 view；介面缺欄位先用既有 source projection，仍不足則提供窄版DTO proposal、mock及未接線狀態，交整合 owner決定。不要修改 A的來源或B的品質工具。

先確定在自己的 worktree，基線包含本輪整併；記錄git status。DATA_ROOT／OUTPUT_ROOT 指向自己的 `output/luna_C/`；pytest 的 TEMP／TMP 保留系統暫存或使用 repo 與正式資料根目錄外的專用短路徑，不放入 repo output；用合成與隔離資料，不連真實交易、不改scheduler、不替使用者提交來源／策略／promotion決定。

## C1：現有流程與視覺基線（約1小時）

用現有MainWindow跑實際畫面，截取1366×768及390×844；記錄縮放／實際viewport與DPI。確認已存在的research context、狀態翻譯、鍵盤支援與Profile風險政策修補，不另寫第二份。

先重現本輪 `tests/test_workbench_source_service.py` 三項失敗：read-only source 狀態、future snapshot 警告與 readiness_source_gaps 審查項投影。辨識來源服務、composer、fixture 哪一層違反契約；不能只修改預期值讓測試通過。這些修復優先於視覺美化。

列一張最多五項的問題表：使用任務、卡點、畫面／元件證據、改善、驗收方式。不要只說資訊太多；指出哪個動作被遮擋、哪個日期不能判讀、哪個狀態無法繼續。先選具體流程再寫程式。

## C2：流程一——資料準備到可研究（約2小時）

沿用Update／市場／Workbench來源服務。讓使用者清楚看到資料日期、判定基準日、來源新鮮度、必需欄位缺口與操作結果。時間格式與時區由既有投影處理，不自行把本機日期當台股交易日。

空白、loading、partial、stale、failed、cancelled要可區分；每個不可用狀態有準確原因及一個符合現有服務能力的下一步。進度至少表達當前階段／已處理／總量未知，不製造假百分比。取消後保留已完成成果與真正狀態，不誤報完整更新。

更新／錯誤處理維持worker、callback與現有服務邊界；重複點擊避免重入。窄版不能隱藏關鍵錯誤、取消或主要操作。來源授權與PIT問題用可理解文案表達，但完整技術原因仍可展開。

## C3：流程二——候選到研究假說（約2小時）

從市場／候選／推薦到個股研究，持續顯示同一股票、區間、來源日期與Profile。明確區分規則分數、資料品質、研究訊號與經校準機率；不能把0.9 reliability或Regime confidence寫成90%勝率。

保留目前由RecommendationProfileService擁有的risk policy與相容性理由。不能恢復「高confidence自動選high risk」或為美化畫面直接選積極策略。

將主要理由、反對證據、缺漏因子與下一步置於首層；hash、schema、Gate細項展開顯示。操作詞使用產品語言，例如「查看缺漏來源」「比較相同區間」「加入觀察」，不要直接呈現內部class名稱。也不能憑UI文案創造不存在的動作。

## C4：流程三——比較到觀察／Portfolio（約2小時）

沿用Research／Backtest／Portfolio現有DTO。比較時讓股票池、區間、成本政策、成交假設、樣本數與benchmark可見；不相容結果要解釋差異，不用一個綠色總分掩蓋。

`研究回放`、`自然前瞻觀測`、`Paper成交紀錄`、`正式可用`必須由既有evidence scope決定，不互相替代。預設展示淨值／回撤／換手或成本等已有指標；如果服務沒有數值，顯示unknown和原因，不在UI計算。

選擇比較→檢視假設→加入觀察／查持倉的導航要保留context；返回原頁不丟篩選條件。Portfolio需清楚區分建議／待成交／已記錄成交，以現有帳本狀態為準，不新增自動下單或擅自套用配置。

## C5：可用性、無障礙與view整理（約1.5小時）

在既有設計token上改善層級、留白、字級及長表格；不要全專案換色或新造第二套theme。顏色以外也有文字／icon，焦點可見、Tab順序可預期、主要動作可鍵盤觸發、Escape取消／關閉行為符合既有契約。

真實驗證窄寬視窗與高DPI；長路徑、長中文理由、資料為空、多個錯誤同時發生、非同步結果晚到都要能閱讀。視圖重複可抽成純展示元件／presenter；不得為了降低行數把所有功能搬進另一個5000行檔或加入跨頁mutable singleton。

## C6：測試、手冊與交付（約2小時）

每條流程都要有happy path、資料缺漏、錯誤／取消與context保留的實際驗證。測試斷言使用者能看到和執行的行為，不只檢查私有widget存在。先跑受影響UI定向測試；再按repo要求執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts/qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

使用實際可用的隔離Python路徑；不因worktree沒有.venv就重建巨大共用環境。UI smoke沿用 `scripts/run_full_app_healthcheck.py` 的隔離模式，取得8個workspace切換與兩個viewport截圖，核對requested和actual尺寸。不允許替使用者執行寫入或promotion來完成smoke。

更新APPLICATION_MANUAL的入口、操作、參數／狀態意義、結果判讀、安全限制、排錯；替換過時段落，不再把每次更新長篇追加到檔頭。核心Snapshot／Roadmap留整合owner更新，自己的handoff說明需更新哪些段落。

交付 `docs/06_qa/LUNA_C_HANDOFF_2026_09_07.md` 與 `output/luna_C/manifest.json`，包含：三條流程的before／after截圖及實際尺寸、五項問題處置、變更檔案、Manual對照、定向／mandatory驗證命令與exit code、未驗範圍、DTO proposal、精確回滾與剩餘風險。新測試登錄只增補自己的inventory條目，分類文件最終計數留B整合。

各里程碑更新checkpoint，遇上下文壓縮從handoff續作。只提交自己的受控程式／測試／手冊，不提交raw screenshots／QA output或密鑰，不push、不合併其他工作線、不提高ML alpha或交易權限。結果達到使用者任務驗收後即交付，不以「完成設計」代替實際UI驗證。
