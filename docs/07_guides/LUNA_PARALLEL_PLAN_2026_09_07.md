# LUNA MAX 三線平行交付計畫

> 使用者要求的下一輪工作包，為 [V4 Completion Plan](V4_COMPLETION_PLAN_2026_09_07.md) 的執行 companion。它不覆寫目前狀態、產品方向或版本 Gate。查核基線與本輪清理見[專案整併報告](../06_qa/PROJECT_CONSOLIDATION_REVIEW_2026_09_07.md)。

## 目標與主要判斷

保留現有 PySide6、應用服務、資料領域、ML 與交易帳本分層；進行局部結構修整與資料／實驗方法修復。下一輪的成功是「可以驗證一個真實投資問題的完整閉環」，不是再增加頁面、模型數或狀態 JSON。

工作分為三條各約 10–12 小時的規劃容量。時間是工作量估計，無法保證模型持續運行時數；提早達到驗收條件即可結束，不用 sleep、重跑無變更測試或擴張範圍來湊時間。使用模型 `gpt-5.6-luna`、reasoning `max`；此組合受[官方模型文件](https://developers.openai.com/api/docs/models/gpt-5.6-luna)支持。長任務應提供目的、相關檔案、約束與完成判準，參考[官方 prompting 指引](https://learn.chatgpt.com/docs/prompting)。

| 工作線 | 可直接貼入的新對話 Prompt | 主要交付 | 估計容量 |
|---|---|---|---|
| A：資料與 ML 有效性 | [Prompt A](LUNA_PROMPT_A_DATA_ML_2026_09_07.md) | 真實來源到可學習標籤的有限範圍閉環；可信度與容量證據 | 10–12 小時 |
| B：架構與測試治理 | [Prompt B](LUNA_PROMPT_B_ARCHITECTURE_2026_09_07.md) | 依賴與重複治理、測試隔離、可重現環境、最終合併清單 | 10–12 小時 |
| C：投資研究 UX | [Prompt C](LUNA_PROMPT_C_UX_2026_09_07.md) | 三條日常研究流程，清楚的資料日期、理由與下一步 | 10–12 小時 |

## 啟動與隔離

1. 先把本輪整理結果審閱後保存為共同 Git commit。三線必須從**包含本輪新增檔案與清理結果的同一基線**開始，不能直接以報告中的清理前 commit 開工。本輪未代替使用者提交。
2. 三個新對話各使用獨立 Codex worktree，分支可命名 `luna/data-ml-evidence`、`luna/architecture-quality`、`luna/research-ux`。不要三個對話直接操作同一 checkout，也不要共用可寫 venv、測試 SQLite 或 QA output。
3. 每線先核對是否仍有其他既有 V4 任務在執行。以實際 Git diff／任務交付為準；本機 shared_state 可能是歷史狀態。若同一檔案另有在途工作，先完成不重疊部分，將依賴列入 handoff，不覆寫別人。
4. 持久 QA 產物置於該 worktree 的 `output/luna_A/`、`output/luna_B/`、`output/luna_C/`，DATA_ROOT／OUTPUT_ROOT 明確隔離。pytest 的 TEMP／TMP 保留系統暫存，或使用 repository 與正式資料根目錄之外的短路徑專用目錄；不可一律指向 repo output，否則會觸發研究輸出路徑防護。tmp_path 仍是合成、可寫資料，正式來源只讀。可唯讀使用現有 Python 執行檔，但不可對共用環境 pip install／upgrade。
5. A 是唯一可執行 ML／資料密集處理的工作線；B、C 使用小型 fixture。完整 pytest 與大型 mypy 最後依 A → C → B 順序排程，避免三份完整 suite 搶記憶體與暫存。平行開發不等於平行重訓。
6. 每線產出自己的 `docs/06_qa/LUNA_<A|B|C>_HANDOFF_2026_09_07.md`，每個里程碑更新完成項、證據路徑／hash、下一個最小動作及未完成原因。不得另外建立互相競爭的 Snapshot／Roadmap。

## 所有權與交接契約

| 邊界 | A | B | C |
|---|---|---|---|
| `data_module/`、`ml_module/` | 僅本 Prompt 列明資料／ML 功能 | 唯讀；提出拆分建議 | 唯讀 |
| `analysis_module/`、`requirements*`、QA tooling | 唯讀 | 主要 owner | 唯讀 |
| `ui_qt/`、操作 Manual | 唯讀 | 唯讀 | 主要 owner |
| `app_module/` 既有服務、Domain／帳本 | 僅 release adapter／ML inference 邊界例外，其餘唯讀 | 唯讀；不重寫交易模型 | 僅 Workbench source／composer 契約修復例外，其餘唯讀 |
| 測試與 test inventory | 自己領域的測試與只新增自己的登錄 | 自己測試；整合清冊與分類文件 | UI 測試與只新增自己的登錄 |
| 核心導航／目前架構文件 | 自己 handoff，不直接改共用核心文件 | 整合 owner | 自己 handoff；Manual 由 C 同步 |

`qa/full_app_healthcheck/test_inventory.py` 是唯一允許三個 worktree 都新增登錄的共用檔；只能增補本線測試條目，不重排他人的部分。各線自己的 inventory JSON 由 `scripts/audit_test_inventory.py --skip-pytest-collection` 產生；分類文件的整合計數由 B 最後刷新，A／C 必須明示本地文件 count drift，不將其冒充全量通過。所有本線缺漏／失效路徑必須為零。合併時以 B 為 owner 取三份新增條目聯集並重新計算，不能選整份 ours／theirs。

測試 fixture 拆分由 B 擁有：`tests/test_portfolio_ml_out_of_core_pipeline.py` 的 builder／fixture 及現有 shared fixture 只由 B 修改。A 可讀取、執行這些測試；新增反例放自己的測試檔，避免和 B 同時搬動同一段 fixture。

跨線只交付 artifact manifest，不互相匯入另一 worktree 的未提交程式。Manifest 至少記錄 schema version、source commit、資料實際涵蓋期間、decision cutoff、available_at 定義、source hashes、觀測／缺漏筆數、evidence scope、輸出相對路徑及檔案 SHA-256。未知值維持 unknown。既有正式 schema 優先，這份欄位要求是交付摘要而非要求再發明產品 schema。

UI 不得從 A 的任意檔案路徑自行掃描資料；仍透過現有 source service、DTO 與明確 reference。若缺少必要 DTO 欄位，C 在 handoff 提交窄範圍介面 patch 與 fixture，由整合階段接受後接線。

## D 槽與 ML 預算

2026-09-07 本輪唯讀量測 D 剩餘 `333,659,123,712 bytes`，約 `310.744 GiB`。這是時間點觀察，不是未來工作可用空間保證。現有 `data_module/ml_storage_capacity.py` 的 heavy-chain reserve 為 **200 GiB**；scheduled persistent 35 GiB + temporary 40 GiB，使該配置啟動所需空間為 **275 GiB**，觀察時僅比此門檻多約 35.744 GiB。

本輪不調高任何配置。A 初始遵守 standalone persistent／temporary 各 1 GiB 的既有預設，小型 fixture／bounded canary 先行。每次執行以實際目的磁碟重新量測；200 GiB 不只檢查 D，也要核對實際 TEMP、cache、checkpoint 所在卷。C 槽本輪全量測試時約 176.48 GiB，已低於正式 reserve，不能假設「搬到 C 就安全」。

容量判準：`可用空間 >= 中央保留量 + 同卷所有已承諾新增持久量 + 同時存在的暫存峰值`。必須計入失敗重試、atomic replace／checkpoint 共存、Windows 已開啟檔案及其他任務占用。使用現有共享 OS lock、reservation、watchdog、checkpoint 與 immutable block reuse，不另外設一套門檻。不能只量測模型檔大小，也不能以 Parquet／Zstd 宣稱固定壓縮率。

三線均不得刪除 D 原始資料、舊模型證據、未讀 OOS、共享 cache 或其他任務 output。若需要更大工作量，先交付估算與能重現的容量 receipt，列為下輪有明確配額的任務；不得為達到時數降低 reserve。

## 建議的 ML 發展順序

1. 驗收現有 teacher eligibility／收據內容綁定、價格尺度隔離、跨年 volume carry 與方法凍結 Gate；程式已存在，先重現正反例，不另做平行實作。
2. 將「缺來源而回落全現金」與「政策合理選擇現金」拆開。歷史 3,353,096 列配置 target 全現金是已知特定產物問題，不是目前所有新資料都已重新檢查的結論。
3. 先做經過成本的股票相對排序／風險過濾實驗，沿用既有 base expert 與小型線性 OOC release。只有完整、可學習且時間因果正確的 teacher，才研究配置模仿；模仿規則準確率不等於投資增益。
4. 同一決策日跨股票共用 split，以標籤 horizon 與 available_at 做 purge／embargo；所有 scaler／feature selection 只 fit train。`TimeSeriesSplit(gap=...)` 提供時間切分，但不能直接把 panel rows 的 gap 當交易日間隔；需依實際標籤重疊驗證。[scikit-learn 時間切分](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)、[資料洩漏規則](https://scikit-learn.org/stable/common_pitfalls.html)。
5. 用小模型／分批 partial_fit 避免重建全量矩陣；若採 scaler，先在 train-only 流式估計後固定，再訓練或使用已驗證的線上方案，不能每批任意改座標後沿用舊模型係數。[SGDClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.SGDClassifier.html)、[StandardScaler](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html)。是否替換既有實作須先比較，這不是新增依賴／模型的必做清單。
6. 在已曝光研究區間，以同股票池、成交限制、費用、時點比較 Rule、Equal Weight、Cash 與候選模型；報告淨報酬、最大回撤、換手、成交覆蓋率、分期穩定性與不確定性。確認性區間先凍結方法，不讀尚未曝光 fold 來選參。
7. 通過研究驗證後走現有 paper／自然 prospective capture。真實成熟天數不能用一晚的程式執行補齊；alpha、Formal credit、production／broker 的變更不由這三份 Prompt 授權。

## 整合與我下一次的審查

三線完成後，把三份 handoff、分支與 commit、測試摘要及 artifact manifest 帶回這個對話。我會按以下順序審查：

1. 比較三線共同基線與 changed-file ownership，排除覆寫、未登錄測試與無關大量格式變動。
2. 先接 A 的資料／ML 契約及反例，再接 C 的 DTO 消費與 UI，最後由 B 整合 inventory、導航、依賴與剩餘重複。共用工具的前置變更可以先合入，但不能據此提前宣告整線驗收。
3. 獨立重算一組資料可用時間／label、一組成交現金守恆、一個壞來源拒絕案例；不能只相信 agent 的 passed 摘要。
4. 用乾淨整合環境跑整合後完整 pytest；UI 必跑 UpdateView 測試、`qa_validate_update_tab.py` 與 repo 規定 mypy。若環境阻擋，記錄具體未驗範圍，不用降低 production Gate 換綠燈。
5. 比對重複／匯入／文件連結與容量清冊，更新 Scoped SSOT；保留研究、工程完成與正式可用的不同結論。

每線必交付：執行過的命令與 exit code、測試 passed／failed／skipped、未執行項、產物大小／hash、精確回滾、已知風險、下一步。缺一份可讀回的 handoff，不算完成交接。
