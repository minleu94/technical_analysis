# Prompt A：資料科學與 ML 有效性（LUNA MAX）

以下全文可貼入新對話。模型請在新對話選 `gpt-5.6-luna`、`max`。

---

你是本專案的資料科學／ML 工作線 A。我授權你依下面範圍長時間實作、修復、執行隔離測試與整理交付，不要只寫建議或完成第一小段就停。工作包估計 10–12 小時；以驗收完成為終點，不用刻意耗滿時間。遇到可自行解決的實作選擇就繼續；必須等真實來源／自然時間的項目記錄原因，轉做仍可推進的項目。不得捏造完成證據。

請先讀 repo AGENTS.md 要求的文件、`docs/07_guides/LUNA_PARALLEL_PLAN_2026_09_07.md`、`docs/06_qa/PROJECT_CONSOLIDATION_REVIEW_2026_09_07.md` 及現有 V4 completion plan。遵守 Traditional Chinese、Decimal／整數金融邊界、未來函數自查、資料與未提交變更保護。Graphify 已有圖譜時只先查詢，不為讀程式重建大型圖譜。

**最終目標：** 用既有系統做出一條「真實來源可用時間 → 特徵／teacher 資格 → 小型研究輸入 → 可解釋比較」的可重現閉環；具體說明哪些資料可研究、哪些能學習、哪些尚不能支持投資結論。先修資料語意與驗收，沿用已有模型、容量與凍結機制。

**起始檢查：** 必須在自己的 worktree；記錄共同基線 commit、Python／套件版本與 git status。確認基線含本輪清冊整併。資料根目錄以 config 為準，但本線持久 QA 產物只放在本 worktree 的 `output/luna_A/`；DATA_ROOT／OUTPUT_ROOT 明確隔離。pytest TEMP／TMP 保留系統暫存或使用 repo 與正式資料根目錄外的專用短路徑；合成 tmp_path 資料不放入 repo output，仍須遵守實際目的磁碟容量預檢。來源可唯讀，不可修改正式 D 資料、既有 immutable artifacts、scheduler 或其他任務正在產生的檔案。

**所有權：** 可以修改以下問題涉及的 `data_module/`、`ml_module/` 與相應資料／ML CLI、各自測試；不要順手重構全目錄。`app_module/` 僅 `allocation_release_adapter.py`、`ml_allocation_inference_service.py` 為依賴邊界修復例外，其餘服務、Domain、UI 與 B 的 QA tooling 為唯讀。若必須改共享介面，交付窄範圍 proposal，不自行修改另一線所有權。新測試只增補自己的 inventory 條目；分類文件的合併計數留 B 最後刷新。B 擁有既有 shared fixture 與 `tests/test_portfolio_ml_out_of_core_pipeline.py` 的 fixture 拆分；你在自己的新增測試檔補反例，不搬動這些 fixture。不要變更全域 conftest 來掩蓋容量／金融／洩漏失敗。

## 里程碑 A1：建立不重做的事實矩陣（約 1 小時）

逐項比較程式、測試與交付，而非只看 Snapshot 開頭：

- `data_module/portfolio_ml_target_diagnostics.py`：teacher 收據內容、identity、dates、cutoffs、candidate coverage、cash fallback 已有驗證，檢查是否全鏈消費。
- `data_module/portfolio_ml_direct_numeric_store.py`：跨年 volume carry 已有實作與測試，核對 resume／舊 checkpoint 失效條件。
- `ml_module/allocation_base_expert_comparison_freeze_gate.py`、`allocation_confirmatory_runner.py`：方法凍結／來源曝光收據已存在，核對所有真實讀取入口。
- `data_module/ml_storage_capacity.py`、immutable／shared block store：central reserve、reservation、共享鎖與重用已存在，不另做第二套。
- daily price guard／overlay、statement semantic mapping、月營收與財報 candidate adapter：研究回補和真正歷史 PIT 不可混淆。

先處理本輪全量測試確認的三項依賴規則衝突：ML release producer 反向 import app release adapter，以及 app inference import family_weight／rank contract 尚不符 guard。先判斷應移至中立契約／loader 或經證據接受的窄邊界，必須保留 artifact readback parity、整數尺度與 fail-closed；禁止只刪 guard 斷言或無條件加 allowlist。這項修復優先於新增模型。

產出 `implemented / tested / real-data-verified / missing / blocked` 矩陣與檔案行號。把已完成的項目從本輪實作清單移除，仍需獨立驗證的項目保留。

## A2：真實來源的有限範圍驗收（約 2 小時）

沿用既有官方來源 candidate／manifest，選包含 TWSE、TPEx、不同財報期間／報表範圍、至少一個被拒絕來源的有限集合。先用既有產物；缺公開證據時可小批次讀取既有官方 adapter 支持的公開端點，遵守重試上限，不做全市場無上限抓取。

每個來源驗證：原始檔 hash、公司／期別、合併／個別／unknown、幣別與單位、期間流量／時點存量、公告／抓取／可用時間、修訂版本、重跑冪等。保留異常原文與拒絕理由，不猜倍數、不截斷極值、不把 unknown 自動當 consolidated。用隔離 SQLite／sidecar 讀回核對，晚到資料在較早決策日必須不可見。

產出 observation matrix，分母明確：本批公司數、eligible、verified、rejected、unavailable。不可用兩家公司通過宣稱全市場已恢復；資料數字須綁當次版本。

## A3：teacher／標籤可學習性（約 2 小時）

將來源缺件、全現金 fallback、合理不交易與真實可調整配置分開，檢查正例／負例／變異度、horizon 成熟、交易限制與來源完整性。已知舊 3,353,096 列全現金 teacher 不能重訓成「更好配置模型」。

用現有 diagnostics 與 producer 建立小型、真實來源支持且時點正確的候選 teacher；候選仍只屬研究驗收。反例至少包括：任意內容配正確外層 hash、來源日期／identity 不符、late source 配 true flags、候選只覆蓋部分日期、缺 sector membership、缺非現金 ledger、target row count 不符、價格尺度異常、標籤未成熟。檢查拒絕發生在 fit、輸出發布或 shared block 寫入之前。

若真實 teacher 尚無法成立，完成可重現拒絕證據及來源補件清單；接著做獨立於 teacher 的既有 base expert 研究比較，不產生假陽性 teacher、不降低 Gate。

## A4：因果、跨年與方法一致性（約 1.5 小時）

跑現有 volume carry、freeze gate、target diagnostics 測試，再新增真正未覆蓋的負例。驗證相同事件去重、跨年20筆視窗、晚到事件／決策日當下不可讀、noninitial year 缺 carry 不能 resume、政策改版不能借舊 checkpoint。

panel 資料按決策日切分所有股票；train/calibration/test 不重疊未成熟 labels，任何 fit 只能看 train。保留既有 scaler 與數值尺度契約。未曝光 fold（包括在實際 exposure ledger 仍 unread 的 fold-005）不得為這次診斷而讀取。已看過的區間始終標 exploratory。

## A5：有資源上限的小型研究比較（約 2 小時）

預設 persistent／temporary 各 1 GiB，reserve 不低於中央200 GiB；每次採實際 output、TEMP、cache 的磁碟判定。先 estimate，取得現有 heavy-chain lock 與 capacity receipt，任何預算／空間不符就停止該密集步驟。不得重跑多年全量 PIT、複製多份 Direct/OOC 或提升配額。

在已曝光的研究範圍，沿用既有線性／base expert 比較流程，和 Rule、Equal Weight、Cash 使用相同股票池、時點、成交與成本政策。至少輸出淨報酬、最大回撤、換手／成本、成交覆蓋、分期穩定性、模型校準／排序品質以及樣本限制。預先選定判準，不能比較完才換 benchmark 或刪不利期間。

重用 immutable features／shared blocks；驗證二次執行的 hash、rows、預測相容與實際新增 bytes。若為降低成本選部分輸入，清楚標記 partial，不冒充 full release。沿用 release adapter 的數值單位，不把模型 float 直接放入金額／股數／風控運算。

## A6：驗證與交付（約 1.5 小時）

至少按實際修改跑以下相關集合，不能只重跑自己新增的測試：

```powershell
python -m pytest tests/test_portfolio_ml_target_diagnostics.py tests/test_portfolio_ml_direct_volume_carry.py tests/test_allocation_base_expert_comparison_freeze_gate.py tests/test_ml_storage_capacity.py -q -o addopts=
```

再按修改範圍加入來源、pipeline、release parity、shared reuse、teacher 與 CLI 測試。金融／ML 邏輯寫出 look-ahead selfcheck；執行受影響模組型態／語法檢查。完整套件依共同計畫的資源排程執行，不與另兩線同時大量跑。

驗收不只看 pytest：獨立用 Decimal／整數重算至少一筆資料尺度、一個 label、一組可用時間、一個成本後結果；輸入／輸出 hash 綁定並可讀回。任何實際環境失敗和產品失敗分開記錄，不修改 production reserve 讓 fixture 過關。

交付 `docs/06_qa/LUNA_A_HANDOFF_2026_09_07.md` 與 `output/luna_A/manifest.json`：列變更／回滾、執行命令與 exit code、驗證結果、真實來源範圍、未讀 OOS 狀態、actual bytes／peak／剩餘空間、未完成項與下一個最小動作。只提交本線受控程式／測試／文檔，raw output、venv、密鑰不提交；不合併其他分支、不 push、不開啟交易或正式 promotion。

每個里程碑後更新 handoff 的 checkpoint。上下文壓縮或使用量中斷後，從 checkpoint 續作，不從頭重訓。若全部驗收提早完成就交付；若真實天數不足，清楚列 waiting-for-time，不把工程完成等同 ML 有效或 V4 正式完成。
