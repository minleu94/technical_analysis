# Prompt B：架構、冗餘與測試治理（LUNA MAX）

以下全文可貼入獨立 worktree 的新對話。模型選 `gpt-5.6-luna`、`max`。

---

你是本專案的首席架構／品質工作線 B。我授權你在以下範圍持續實作與整併，完成約 10–12 小時工作量的工程包。不要只盤點或提出未執行建議；也不要為湊時間重寫系統。驗收達成即可交付。

先讀 AGENTS.md 所列必讀文件、`docs/07_guides/LUNA_PARALLEL_PLAN_2026_09_07.md`、本輪 project consolidation review、data cleanup／testing QA／documentation agent 規則。以目前程式與測試核對文件，使用繁體中文。每批清理前做精確回滾表與備份、直接／間接／動態引用檢查，不因函式文字相似就刪獨立 oracle。

**目標：** 讓專案能由少數清楚入口理解、在隔離環境驗證，並能對新增檔案／依賴／測試／文件漂移提出可執行的檢查結果。保留現有分層與公開契約，不進行 framework 遷移或全 repo 大改名。

**所有權：** `analysis_module/` 的可證明重複、QA／測試治理工具、依賴環境文件、`requirements*`、核心導航與分類摘要為你所有。`data_module/`、`ml_module/`、`ui_qt/` 與 `app_module/` 既有產品服務只讀；對其拆分提出具體 seam／契約／測試方案，不與 A、C 同時修改。交易帳本與金融核心不在本線實作範圍。Manual 由 C 所有。

只在自己的 worktree 操作；記錄基線、git status、Python 路徑與套件版本。保護其他任務變更。不要在共用 venv 安裝套件。所有新資料與暫存在 `output/luna_B/`，不刪 D 資料或其他任務產物。

## B1：可重跑的 repo 地圖（約 1 小時）

沿用本輪盤點與 graphify 查詢，建立 tracked／untracked／ignored 的不同清單。程式、docs、tests、scripts 分開計數；package marker、compatibility façade、manual script、正式測試、QA evidence 不混為一談。

對候選重複做 SHA／AST、呼叫者、測試、文件連結及 dynamic import 查核。列出每筆 keep／merge／remove／defer 的理由。禁止裸用「零 rg 結果」證明 unused；入口、plugin registry、pytest fixture、subprocess 字串也要核對。既有 graph、log、output 不重新納入 Git。

## B2：測試去重與可攜性（約 2.5 小時）

本輪已把兩個 SignalCombiner 的相同分析流程共用、兩個欄位測試參數化，已補69份清冊缺漏；不得還原成重複兩份。不同可靠性／回測政策仍需各自測試。

優先處理測試檔互相 import builder／fixture 與 `pytest_plugins` 指向整份 test module 的耦合。先查引用圖，再把真正共用的 fixture 移至專用 support 模組；避免將預期結果也改為呼叫被測函式。參數化同一契約的多入口／多政策，保留獨立邊界與負例的辨識度。

修復「小型 ML fixture 必須有200 GiB實體空間」的測試環境依賴：本輪 C 約176 GiB時，`bounded_e2e` 在 raw_before_output 被中央 reserve 拒絕。只在明確的 synthetic／tmp_path fixture 注入可控容量探針；禁止降低 production reserve、全域 autouse 永遠回傳容量足夠或跳過所有容量測試。真正的容量單元測試仍驗證低空間拒絕、跨磁碟、並行承諾、watchdog 與未寫入副作用。

同時修正 `tests/test_inspect_fubon_shadow_decision_cli.py` 對硬編碼 D formal root 的假設：使用隔離、明確的 DATA_ROOT，仍須驗證 configured formal root 被拒絕，不能改弱產品 path guard。

先建立可重現失敗，再修 fixture；新增驗證必須證明 mock 只覆蓋隔離測試範圍，且 fixture 結束後恢復。對未固定 seed 的共用市場資料，改為可重現且符合 OHLC 關係的資料；保留原測試意圖，不讓所有測試變成單一單調樣本。

## B3：有邊界的分析程式整併（約 1.5 小時）

選下一組具有明確收益的共用流程；至少做到可量測的重複減少或消除一個語意歧義。可優先檢查 signal column／date、analysis helper；先做舊版與新版 parity。金融核心、新模型／UI行為不可順手改。

同名但不同算法不強行合一。既有 SignalCombiner 兩份 legacy backtest 包含同日成交、float 與不同輸出契約；若要移除只能先證明現行產品不依賴，再做 deprecation／compatibility 方案，不能默默切換成另一份回測。把正式回測唯一入口與研究分析邊界記清楚。

## B4：依賴與環境可重現（約 1.5 小時）

盤點直接依賴、實際匯入、測試依賴與平台依賴。`requirements.txt` 的 pandas>=1.3、sklearn>=0.24.2 等寬鬆下限不是經驗證的現行環境；不要只 pip freeze 把所有私人／無關套件當正式需求。

建立最小直接需求與經驗證版本 constraints／lock 的清楚關係；對 Python／Windows／TA-Lib／PySide6 支援條件給出真實測試證據。新增下載或安裝只在自己的隔離 venv，先查本機空間與估算依賴量，不任意全量升級。不夠空間就交付可重現安裝計畫與未驗狀態，不假稱乾淨環境已通過。

對引用但漏列的 runtime 套件、已不用的依賴逐一查明；只有確定無呼叫／可選入口且已有替代的依賴才移除。

## B5：防止文件與清冊再膨脹（約 1.5 小時）

沿用現有 `scripts/audit_test_inventory.py` 與 docs coverage 流程，補最有價值的機器檢查：未登錄／失效測試、support 分類、明確本地 Markdown 連結、重複 current 區段與正式入口引用。檢查器要有小型正負 fixture，不要求「整個 repo AST 一樣就全部刪」。產出 JSON 與短摘要，不把每次掃描輸出追加成新的永久文檔。

Snapshot／roadmap／architecture 的 mutable facts 重複是維護風險。將導航保持為入口，架構保持為責任與契約，執行紀錄留 dated QA report；不能丟失仍用於來源追溯的歷史。`docs/05_phases` 與 `docs/superpowers` 有價值且有引用的內容保留，不按年代全刪。

## B6：整合入口與驗收（約 2 小時）

你是最終 inventory／核心導航整合 owner，但不主動合併尚未交付的 A、C 分支。若 A、C 尚未完成，先完成自己的分支，提供可執行整合清單；不得等待數小時空轉。

取得 A、C handoff 後，檢查同一基線、所有權、新增測試條目聯集與 source contracts；只在有交付且使用者指定的整合範圍處理。計數來自真實 filesystem／collection，不手改數字消除 drift。共享檔不能直接選 ours／theirs 丟棄另一線新增條目。

執行：本線 targeted tests、inventory audit、全部 Python parse、變更檔 mypy／py_compile、docs link check、Git diff check；依共同排程跑完整 pytest。若有既有失敗，留下重現、是否修改前即存在、根因與修復範圍；禁止 xfail／刪斷言換綠燈。UI mandatory checks 由 C 執行，整合後仍須再驗證。

交付 `docs/06_qa/LUNA_B_HANDOFF_2026_09_07.md`，至少包含：

- before／after 程式／測試／docs 數量、移除／整併精確檔案與淨行數，不把新增交付文檔排除後宣稱整 repo 已變小。
- 已確認邏輯衝突、已修復項、仍保留的技術債及理由；大型檔案拆分提案須有 seam、介面、風險與對應 oracle。
- 新測試支援模組與容量 fixture 的隔離證據；現行200 GiB production policy仍生效。
- 環境重建命令、依賴驗證狀態、每個實際測試命令／exit code、完整 suite結果。
- 自己變更的精確回滾、A／C整合步驟與衝突處置、下一個可執行動作。

各里程碑更新 checkpoint。提早完成即交付；若需後續多日證據，標 waiting-for-time。只提交自己的受控程式／測試／文件，不 push、不啟動 production、不清理他人的 output。
