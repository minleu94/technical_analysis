# V4 ML release bounded QA（2026-09-07）

本次交付包含兩條可審核的 linear shadow slice：bounded fixture 的 minimal
producer，以及從 immutable Direct parent 選出的 derived h5 producer。兩者均經過
`allocation-ooc-training.v5` → release builder →
`AllocationReleaseAdapter` → daily inference consumer。沒有重建正式 D 產物、全市場訓練、資料 fetcher、中央 Snapshot 或 Manual，也沒有把結果標成 promotion。
另依 frozen gate 核准執行一次 fold-005 bounded research comparison；其實際 source
exposure、結果與獨立核對列於下方，仍維持 research-only。

## owner 與交付檔案

- `ml_module/allocation_ooc_release_builder.py`：讀取已完成且 formal source-only 的 OOC manifest，驗證 store、fold、artifact、head coverage 與 maturity custody；建立 immutable model artifact、preprocessor、實際整數 bp calibrator、calibration evidence 與 daily 相容 wrapper；另以 parent hash/selection lineage 建立 derived h5，重訓 57 欄 raw OOF meta 並保存 fold-004 withheld replay。
- `scripts/build_ml_allocation_release.py`：bounded release producer CLI。
- `scripts/build_ml_allocation_derived_release.py`：真實 Direct parent 的 derived h5 producer CLI；`--preflight-only` 只讀查核，正式執行持有 release_v4 共用 heavy lock。
- `app_module/allocation_release_adapter.py`：hash-bound release loader、calibrator attachment 與 frozen row parity。
- `app_module/ml_allocation_inference_service.py`：OOC `predict_numeric` boundary、classifier contract，以及 raw/calibrated meta input 分流。
- `scripts/audit_ml_allocation_v3_linear_release.py`：只讀載入 v3 release、重播 research readback，逐 expert 驗證 attached calibrator，並可持久化完整 inference audit。
- `ml_module/allocation_out_of_core_training_service.py`：將 `minimal_linear_shadow` 與 complexity policy 寫入 OOC run identity/manifest；既有 OOC fit 流程未改資料來源。
- `ml_module/allocation_family_weight_contract.py`、`ml_module/allocation_rank_contract.py`：版本化 family policy/status 與 V1/V2 rank contract。
- `ml_module/allocation_base_expert_comparison.py`：固定 fold-004 的 base expert／causal Rule／T-1 流動性池等權成本後研究比較；v7 綁定只讀跨年 volume sidecar。
- `ml_module/allocation_replay_causal_volume_sidecar.py`：從 immutable `replay_source.sqlite` 逐 symbol 重建跨年 20 個 distinct price event 的 causal median，並對 Direct stored median 做同年 parity。
- `data_module/portfolio_ml_direct_numeric_store.py`：正式年度 producer 以 `portfolio-ml-direct-carry.v2` 保存每個 symbol 最多 20 個跨年 causal volume events；checkpoint/resume 與 atomic year adoption 會驗證 carry schema，舊 carry fail closed。
- `ml_module/allocation_base_expert_comparison_freeze_gate.py`、`ml_module/allocation_confirmatory_runner.py`、`scripts/validate_ml_allocation_confirmatory_gate.py`：在任何 future fold source read 前驗證完整 code／policy／parent／request freeze；runner 在同一程序建立含 lineage 的 immutable bound request 後才呼叫 source reader。
- `scripts/run_ml_allocation_confirmatory_comparison.py`：同一程序執行 gate、bound request、shared heavy lock 與 read-only fold-005 comparison；`--preflight-only` 不開啟 future source。
- `scripts/audit_ml_allocation_confirmatory_result.py`：只讀已發布 comparison、stable exposure 與 parent/store manifest，獨立重算整數 closing equity、net/gross return、MDD、共同 pool 與缺 bar source evidence。
- `tests/test_allocation_ooc_release_builder.py`：由 fixture 建立的實際 bounded store/run、獨立 OOC numeric batch replay、逐 head/vector/meta/bp parity、derived heldout replay 與負例。
- `tests/test_allocation_base_expert_comparison.py`、`tests/test_allocation_replay_causal_volume_sidecar.py`、`tests/test_allocation_base_expert_comparison_freeze_gate.py`、`tests/test_portfolio_ml_direct_volume_carry.py`：比較、跨年 sidecar、availability/parity/identity 負例、同程序 confirmatory reader 與 Direct carry/resume 契約測試。

## 校準來源與防洩漏條件

minimal builder 只接受 `training_profile=minimal_linear_shadow`、單一
`ridge_logistic`、單一 horizon，以及明確綁定的 complexity policy；derived builder
則只接受已完成的 formal source-only parent，並在 selection lineage 明確綁定
`h5/ridge_logistic` 與四個 selected folds。兩條路徑的校準 mapping
由 `base_oof_expert` 的 outer-fold test rows 建立，來源 fold 的 label 必須在下一
個 fold `test_start` 前成熟；最後一個 target fold 不進 fit。校準不讀 final model
fit rows，也不讀 teacher target 作為 probability input，且至少需要兩個有成熟標籤
的 fit folds 與兩個 label classes。

目前 minimal release 對所有 frozen feature packs 產生一個明確宣告的 shared
mapping；evidence 會保存 `feature_pack_ids`、每個來源 artifact hash、fit fold
cutoff、fit/positive/negative row counts，以及
`shared_mapping_across_feature_packs`。pack coverage 不完整時 builder 直接拒絕，
不會靜默丟掉 pack。

`model.joblib` 額外綁定 `meta_probability_input=raw_oof`、profile 與 complexity
policy。daily inference 的 calibrated downside bp 會保留在 row audit、risk
output 與 horizon aggregate；final meta 仍收到與 OOC fit 相同的 raw expert vector。
沒有此 metadata 的 legacy artifact 維持原本的 calibrated meta input，避免跨版本
改變既有模型語意。

## daily 接線與權限邊界

Builder 寫入同一個 release root 的 `release_manifest.json`、`model.joblib`、
`preprocessor.json`、`calibrator.json`、`calibration_evidence.json` 與
`training_manifest_v2.json`。既有 daily orchestration 先讀 wrapper，再因
`release_manifest.json` 存在而進入 `AllocationReleaseAdapter`；adapter 會驗證
release identity、artifact/preprocessor/calibrator hash、feature order、model
lineage 與 missing policy，最後才建立 inference service。

所有 publication 與 parity 結果固定為 `formal_oos_allowed=false`、
`production_alpha_bp=0`、`production_action_allowed=false`、
`broker_order_allowed=false`。校準器可供 shadow inference 使用，不代表正式
OOS 證據或 promotion authorization。

## 真實 Direct 路徑與容量界線

目前只讀檢查到的 Direct numeric store 是 3,353,096 rows、62 features、3
feature packs、41 outer folds；其 store manifest hash 為
`sha256:e053aaf32bf978834eaf158791ad1170cf0d2909fea0f3a207bbe801150f0689`。
既有 allocation OOC parent run 是 4 horizons × 2 algorithms，不能把 parent
manifest 改寫成 minimal。其 temporary preflight peak 約為
16,073,466,555 bytes，memory cap 為 4,096 MB。

成本最低且保持數學語意的 derived 路徑是挑選單一 horizon（h5）與
`ridge_logistic`：沿用 parent 的 3 個 final ridge heads 與相同 3 packs 的
prior-fold ridge OOF，重新以選取後的 57 寬 raw expert vector 訓練 causal meta
heads，再用同一批 OOF test rows 建立 shared integer-bp calibrator。完整選取量
是 123 個 OOF artifacts、8,693,127 個 pack-row、約 661,801,889 bytes；若先
做有界驗證，可固定 fold-001…fold-004（3 packs 共 773,817 個 test-row；校準
前 3 folds 的成熟 rows 為 84,609，正／負類別分別為 64,554／20,055，並排除
fold-004）。heldout fold-004 cutoff 前，fold-001/002 的 test labels 均已成熟，
fold-003 成熟 5,943 rows，實測 final meta fit rows 為 148,874；不能沿用 parent
的 full final meta。derived manifest 必須保存 parent manifest
hash、選取的 fold/head、source artifact hashes 與新的 meta/calibration hashes；
容量 guard 通過前不得啟動 Direct 訓練，也不得以 metadata 變更冒充 minimal。

2026-09-07 對真實 parent 的唯讀 preflight 已通過：parent hash 為
`sha256:314f29f16037572854d0561f08f52716c29ce6f1c848b68b46d1e6e9f729d118`，
store hash 為
`sha256:e053aaf32bf978834eaf158791ad1170cf0d2909fea0f3a207bbe801150f0689`，
derived identity 為
`sha256:37d0e9ecd047a0634a1dedbb6f1293d5026ffc045ed4c86d28629e3da591a58b`。
repo output C: 的 free bytes 為 249,907,875,840，Direct source D: 的 free
bytes 為 354,755,321,856；兩邊均以 214,748,364,800-byte safety reserve、各
1 GiB persistent/temp 上限通過。真實 derived 寫入已在 shared
`D:\\Min\\Python\\Project\\FA_Data\\output\\release_v4\\.ml_heavy_chain.lock`
下完成；preflight 與 execution 均未修改 parent/full manifest。

真實 derived output 位於 `output/v4_ml_derived_h5_20260907_real`，實際目錄
bytes 為 4,187,004，derived manifest hash 為
`sha256:081fc02abc310d2b5564ba4e8ed23174a4a2b6b687f2162e90e0a4c871d72b38`，
release identity 為
`sha256:6aeef07f1c8d06f55402cbda9dd61f0e786f8cec9417ab2b600ee5f1066e18be`，
model artifact hash 為
`sha256:5c851d94b4a9385b30317b345ff084cdc47cdc165394e5463061272fbad67a52`。
calibrator 為 `ooc-isotonic-ce786befb883f0f1`，fit folds 為
`fold-001..003`、fit rows 為 84,609（positive 64,554、negative 20,055）。
`heldout_evaluation.json` 的 file hash 為
`sha256:97304b7b6f1a8ab17a3d13dfb4a5abd3c66414249c416efc43181f8d8f3508a2`；
fold-004 的 57,666 rows 由三個 parent base OOF 與 derived fold-004 meta OOF
獨立 frozen replay 均 matched，target label reads 為 0。

### rank 與 Meta target 可識別性

V1 的 `allocation-rank-v1:ordinal_symbol_tiebreak` 保留既有 symbol tie-break
語意；新的 derived 版本可明確選用
`allocation-rank-v2:dense_value_tiebreak`，同一 decision date 的相同數值會得到
相同 rank，並在 parent V1 OOF 上依 date 重建 rank。rank contract、family weight
policy 都寫入 request、selection lineage、derived identity 與 model artifact，
不會由 rank 版本隱含切換另一個 family policy。

對 Direct frozen store 的完整 3,353,096 rows target custody 檢查顯示：
`target_weight_bp`、`delta_weight_bp`、`risk_contribution_bp`、
`risky_budget_bp`、`rebalance_worthwhile` 均為 min=max=0 且 nonzero=0；
`cash_bp` 為 min=max=10,000。這代表五個 numeric Meta target 都是常數，
目前沒有可識別的 Meta 配置訊號；根因需連回正式輸入 blockers
`pit_sector_membership_missing_teacher_new_positions_disabled`、
`portfolio_ledger_missing_cash_only_fallback_turnover_and_cooldown_not_learned`
與 `formal_rule_champion_snapshot_history_missing_formal_replay_blocked`。

因此新增 `family_weight_policy=degenerate-equal-v1`：只有五個 numeric target
全常數時才使用 deterministic eligible-family equal weight，狀態標為
`degenerate_unidentified_equal`，不把約 1e-9 的 ridge 求解殘差當作 feature
importance。既有 V1 及先前已寫出的 V2 coefficient artifact 保持 immutable；
它們的既有權重只可標作 legacy coefficient/unknown。新的 builder/consumer
會驗證 policy/status binding，並把 `target_summary` 與狀態寫入 audit。由於
真實 Direct target 全常數，本輪依 root 指示不再花費 3,353,096-row derived
fit 來重做同一退化 Meta；新 policy 已由 bounded V2 整合測試驗證，待正式 PIT
membership、ledger 與 Rule replay 產生非退化 labels 後，才增量重建正式相關
blocks。

真實 parent 的新 policy 唯讀容量預演亦通過：derived identity
`sha256:a43296fbd90cf5421df85596ac1492ca9694aa0fd76954e27a1dbad6326e3280`，
C: free bytes `261,122,293,760`、D: free bytes `354,755,313,664`，
200 GiB reserve 與 persistent/temp 各 1 GiB budget 均通過；這是 preflight
證據，不是一次新的 derived fit 或 promotion 證據。

此前的 V2 rank 實跑位於 `output/v4_ml_derived_h5_20260907_real_v2`，derived
manifest hash 為 `sha256:c2b295b63e9a08d27920922197a72b6331111f8bf4ac8e1524731480481ea9a7`，
並已完成 daily research shadow；該產物依當時的 coefficient policy 保存，現在
視為 immutable historical experiment。新的 `degenerate-equal-v1` policy 有
獨立 identity，不能由這個既有 V2 bytes 重新標籤或宣稱已產生新模型。

## base expert、causal Rule 與 Equal Weight 成本後比較

本次新增 owner 檔案為 `ml_module/allocation_base_expert_comparison.py`、
`scripts/build_ml_allocation_base_expert_comparison.py` 與
`tests/test_allocation_base_expert_comparison.py`。Producer 只讀 immutable
parent 的三個 h5 `ridge_logistic` base OOF 與 Direct
`replay_source.sqlite`／labels，沒有讀 `targets.i32`、沒有重訓 Meta，也沒有
修改 parent 或 D: source。selected scope 固定為 `fold-004`、h5、三個完整
feature packs、57,666 rows、63 個決策日，日期為 2015-11-16 至 2016-02-22；
h5 `benchmark_excess_return_bp` label 57,666 rows 全部已觀測。

這個 fold 在設計與執行週轉步進前已被檢視，因此 v1 至 v3 的輸出只作為探索與
除錯證據，不能稱為未觸碰的 confirmatory OOS。v4/v5 才凍結目前方法與 lane
名稱；
要作確認性結論仍須事先選定另一個未檢視 fold。這次結果不支持 ML 優勢，也不以
收益改善作為交付條件。

v5 同時保存兩個明確情境。`strict_sector` 完整沿用正式 PIT sector gate 與
sector cap；`research_no_sector_cap` 只在研究 overlay 中移除缺失 sector 的
gate/cap，仍保留價格事件、流動性、可交易狀態、現金、lot、費用、cooldown
與週轉限制，不建立虛構 sector id，也不具 promotion 資格。研究 overlay 在
呼叫 replay 前按剩餘每週 turnover 以整數 bp 逐步靠近 signal target，所有
研究 lane 使用同一規則。`equal_weight_symbol_first8` 是依 symbol 排序取前
8 檔的明確基準，policy 標示為 `not_full_universe`，不應解讀為完整股票池的
普遍等權基準。

實際結果如下；`gross` 是同一實際持倉加回累計交易成本的估計，不是獨立的
無成本組合。總報酬與 MDD 直接以每日整數 minor-unit closing equity 計算，
沒有先將每日 bp 四捨五入後再 compound；`execution_helper_after_cost_return_bp`
只保留 replay helper 的 open-to-close 診斷值。

| lane | strict status / trades | research status / trades | research net / gross bp | net MDD / gross MDD bp | cost minor |
|---|---:|---:|---:|---:|---:|
| data_quality base | blocked / 0 | no fills / 0 | 0 / 0 | 0 / 0 | 0 |
| market_sector_cross_section base | blocked / 0 | no fills / 0 | 0 / 0 | 0 / 0 | 0 |
| price_liquidity_technical base | blocked / 0 | executed / 48 | -33 / 11 | 188 / 176 | 220,882 |
| base mean | blocked / 0 | no fills / 0 | 0 / 0 | 0 / 0 | 0 |
| causal Rule research | blocked / 0 | executed / 6 | 64 / 70 | 2 / 0 | 31,805 |
| symbol-first8 equal weight | blocked / 0 | no fills / 0 | 0 / 0 | 0 / 0 | 0 |

strict 六個 lane 的 status 都是 `blocked_missing_pit_sector_id`，其 57,666
個 selected row 的 `sector_id` 全缺，故不能把零報酬當成正式策略表現。研究
lane 的零成交也沒有被寫成成功交易：data quality、market、base mean 與
symbol-first8 equal weight 分別保留 `no_fills_after_replay_constraints`、
requested/unfilled counts 與每日 `execution_requested_weights`。原始 target
會受到每週 2,000 bp turnover 上限而不能一次建滿，v5 的逐步規則解除整批
target 拒絕；在相同 1,000-share lot、價格、成交量、現金、cooldown 與費用
政策下，剩餘的 target 仍有未滿足 lot／volume／cash／cooldown 約束，因此
不能把這些零成交 lane 與有成交 lane 作勝負解讀。Rule lane 的來源是
`replay_source.rule_score_bp`，`formal_rule_champion_history_available=false`，
所以它只是 causal research Rule，不能代替正式 Rule champion。

source quality 實測 missing counts 為 `sector_id=57,666`、
`median_volume_20d_shares=16,668`、`price_event_at=9`、`rule_score_bp=642`；
完整 blocker 仍包含 PIT sector membership、Rule champion history 與缺失的
price event。這些缺件以 lane status 與 source blocker 分開保存，沒有降低
正式 coverage threshold。

實際持鎖 bounded producer 命令如下（v5）：

```powershell
.\.venv\Scripts\python.exe scripts\build_ml_allocation_base_expert_comparison.py `
  --parent-training-manifest D:\Min\Python\Project\FA_Data\output\release_v4\portfolio_ml_direct_ooc_training_production_v4_v5\runs\allocation-ooc-868b7e805f5c03c65dc303e4\manifest.json `
  --output-root C:\Projects\PythonProjects\technical_analysis\output\v4_ml_base_oos_comparison_fold004_20260907_v5 `
  --fold-id fold-004 --horizon 5 `
  --persistent-new-bytes-budget 268435456 `
  --temporary-peak-bytes-budget 268435456 `
  --memory-budget-mb 4096 `
  --safety-reserve-bytes 214748364800 `
  --heavy-lock-path D:\Min\Python\Project\FA_Data\output\release_v4\.ml_heavy_chain.lock
```

output 為 `output/v4_ml_base_oos_comparison_fold004_20260907_v5/runs/`
`base-compare-e6e8b6ad4a3b86ff2b1173a7/comparison.json`；整個 output directory
bytes 為 1,795,263，`comparison.json` bytes 為 1,794,421，file hash 為
`sha256:6c9f3fa5feecd01c9ca0fdb03727b1dfd5653fc3ce656c214c5a1defd24eb4be`；
logical comparison hash 為
`sha256:9fc95e4cda1286fc5dd597d5c77c387c83a88e1e633f034652945b534701dc2e`。
latest pointer 在同一 output root。locked recheck 的 C: free bytes 為
260,972,544,000，D: source free bytes 為 354,755,313,664；兩者均保留
214,748,364,800 safety reserve，persistent/temp 新增上限各 268,435,456
bytes，preflight 通過。publication flags 維持
`formal_oos_allowed=false`、`production_alpha_bp=0`、
`broker_order_allowed=false`、`research_only=true`。
artifact 同時保存 `performance_capital.initial_capital_minor=50000000`、
`initial_capital="500000.00"`、`currency="TWD"` 與 `minor_unit="TWD_cent"`，
讓外部重算不依賴當前程式碼的初始資金常數。

### v6 與 v7 真實 fold-004 比較

v6 是先凍結的 fold-004 探索比較，output 位於
`output/v4_ml_base_oos_comparison_fold004_20260907_v6/runs/`
`base-compare-03ec8dc05f9dbdcbc1129db2/comparison.json`。它使用舊 stored
median，63 個決策日中只有 44 天形成 8 檔流動性池，另外 19 天為空；根因是
Direct writer 每年重置 volume history，2016 年 1 月沒有跨年 window seed。v6
保留為 immutable historical experiment，研究 lane 的 net 結果為 price expert
`+97 bp`（2 trades）、causal Rule `+138 bp`（4 trades）、T-1 liquidity-pool
equal weight `-85 bp`（7 trades），不能把少量交易或這些探索結果當作 ML 優勢。

v7 以新的只讀 sidecar 修復研究比較的跨年 window，沒有改寫 Direct parent、
stored median、labels 或任何正式 D 產物。實際 producer 在 shared
`D:\\Min\\Python\\Project\\FA_Data\\output\\release_v4\\.ml_heavy_chain.lock`
下完成，output 位於
`output/v4_ml_base_oos_comparison_fold004_20260907_v7/runs/`
`base-compare-18bb157241a439ff08105225/comparison.json`。comparison logical
hash 為
`sha256:a844b0db95607c30a7cdb72e5e388a2090ff9acc9f6e264c51b0a0642a639963`，file
SHA-256 為
`sha256:262b7762c7be21aeb3c83326639b02bf7cae89111c23e31e30c4624167944073`，
`comparison.json` 單檔為 `50,309,548` bytes；同一 output root 的
`latest_comparison.json` pointer 為 `842` bytes，兩者合計的整個 output 為
`50,310,390` bytes。這是檔案與 output directory 總量的差異，沒有原地補寫
既有 comparison。parent/store hashes 分別維持
`sha256:314f29f16037572854d0561f08f52716c29ce6f1c848b68b46d1e6e9f729d118` 與
`sha256:e053aaf32bf978834eaf158791ad1170cf0d2909fea0f3a207bbe801150f0689`。

sidecar policy 是 `causal-volume20-cross-year-carry.v1`，讀取 2014–2016
的 source years，對每個 symbol 以決策時間排序、去除重複 `price_event_at`、
接受零 volume、取最近 20 個 distinct event 的 lower-pair median。v7 實際
選取 57,666 rows：16,488 rows 從跨年 window 恢復 stored median 缺件，40,998
rows 的 stored median 同年 parity 全部吻合，mismatch 為 0；仍有 180 rows
沒有可重建的 causal median，故不把它們隱含轉成零或可用值。63 個決策日全部
形成 8 檔池（504 selected pool rows），這個 coverage 改善來自跨年 source
carry，不是放寬 pool 條件。sidecar evidence 的 source scope hash 為
`sha256:2357be7ff0d46f521bd9a7948e676af6d6f54181079c28020fcf50344fb80595`，
並保存 `read_only=true`。

`price_available_at` 的既有契約是欄位缺值時可使用同一筆
`price_event_at` 作為 availability fallback。availability audit 位於
`output/v4_ml_base_oos_comparison_fold004_20260907_v7_qa/source_availability_audit.json`，
hash 為 `sha256:0e77f3f8fb2f33912f56bf2f4e517ef3e093531b4d8ada25fe31bac405a82e22`：
selected rows 中有 9 rows 同時缺 `price_available_at` 與有效
`price_event_at`；482,662 筆有效 non-negative event 中，缺 availability 的
為 0，實際使用 fallback 的 distinct event 亦為 0。這表示本次 v7 結果沒有
因 availability fallback 擴張可得資料；sidecar 對缺 event 的 180 rows 仍
維持 missing。零 volume 是合法 observed event，負 volume／無法解析 event
則 fail closed 或跳過並留下計數。

v7 研究 lane 的完整成本後摘要如下；gross 是同一實際持倉加回累計成本的
估計，不是獨立無成本組合；net total return 與 MDD 直接從每日整數 closing
equity 計算。

| lane | status | trades / unfilled | net / gross bp | net MDD / gross MDD bp | turnover bp | cost minor |
|---|---|---:|---:|---:|---:|---:|
| data_quality base | executed | 4 / 16 | -24 / -12 | 79 / 76 | 2,996 | 59,791 |
| market_sector_cross_section base | executed | 4 / 16 | -24 / -12 | 79 / 76 | 2,996 | 59,791 |
| price_liquidity_technical base | executed | 2 / 27 | +97 / +106 | 8 / 6 | 2,118 | 43,395 |
| base mean | no fills | 0 / 7 | 0 / 0 | 0 / 0 | 0 | 0 |
| causal Rule research | executed | 7 / 230 | +113 / +134 | 43 / 42 | 5,232 | 106,605 |
| T-1 liquidity-pool equal weight | executed | 11 / 512 | -58 / -32 | 268 / 255 | 6,644 | 131,064 |

strict sector 六個 lane 均為 `blocked_missing_pit_sector_id`，因 selected rows
的 57,666 個 `sector_id` 全缺；strict 零報酬不具績效意義。causal Rule 仍是
`replay_source.rule_score_bp` 的研究 lane，`formal_rule_champion_history_available=false`。
v7 所有 publication flags 維持 `formal_oos_allowed=false`、
`production_alpha_bp=0`、`broker_order_allowed=false`。

實際 v7 producer 命令如下：

```powershell
.\.venv\Scripts\python.exe scripts\build_ml_allocation_base_expert_comparison.py `
  --parent-training-manifest D:\Min\Python\Project\FA_Data\output\release_v4\portfolio_ml_direct_ooc_training_production_v4_v5\runs\allocation-ooc-868b7e805f5c03c65dc303e4\manifest.json `
  --output-root C:\Projects\PythonProjects\technical_analysis\output\v4_ml_base_oos_comparison_fold004_20260907_v7 `
  --fold-id fold-004 --horizon 5 --algorithm ridge_logistic `
  --batch-size 8192 --memory-budget-mb 4096 `
  --persistent-new-bytes-budget 268435456 `
  --temporary-peak-bytes-budget 268435456 `
  --safety-reserve-bytes 214748364800 `
  --heavy-lock-path D:\Min\Python\Project\FA_Data\output\release_v4\.ml_heavy_chain.lock
```

locked recheck 的 C: free bytes 為 `252,821,065,728`、D: source free bytes 為
`354,755,309,568`，兩邊保留 `214,748,364,800` safety reserve；persistent/temp
新增上限各 `268,435,456` bytes，實際 producer output `50,310,390` bytes，
preflight 與 execution 均通過。

### confirmatory gate 狀態

v7 method freeze version 是 `base-expert-comparison-method.v7`，method freeze
hash 為
`sha256:f34ce984a6ebe7bfab4ba661ce6b1d90503f1b592f90bd0df0de656b0c8cc25e`，
包含 comparison、replay input builder、replay policy owner、causal sidecar 四
個 code hashes，並綁定 immutable parent/store hash 與獨立 future request hash
`sha256:6f8c25a35ddb4fb6bd2f10db9ca250cbbdc6360f403555756bd30418d23a1701`。

對 v7 receipt 執行 `scripts/validate_ml_allocation_confirmatory_gate.py` 的
實際結果為 `status=validated_before_confirmatory_read`、`fold_id=fold-005`，
`price_data_read=false`、`label_data_read=false`、`result_data_read=false`。
實際執行 `scripts/run_ml_allocation_confirmatory_comparison.py --preflight-only`
的結果同樣為 `status=preflight_passed_before_confirmatory_read`，並保存於
`output/v4_ml_confirmatory_runner_preflight_20260907/validation.json`（2,541
bytes；`sha256:ef6a7fc10748051e134172f15d4e0460def22562f66a0ca25b27f7f3d43fb44a`）。
其中 bound request 綁定 runner file hash
`sha256:15ab98d72e925885aada9f518030231adb5ef717505b2b339b6a3c83fc882236`、
parent/store hashes、四項 policy、`fold-005/h5/ridge_logistic` 與 256 MiB
persistent/temp、200 GiB reserve；heavy lock 為既有 release_v4 共用
`D:\Min\Python\Project\FA_Data\output\release_v4\.ml_heavy_chain.lock`，
binding hash 為
`sha256:ab126ed3d063d8632196f29fb80a3ee3d6e6cf00ba0156910049379b05a34757`；
三個 source read flags 均為 false。

正式 runner 只有在同一程序完成 `authorize_confirmatory_scope`、建立上述
immutable bound request、取得 shared heavy lock 並在 lock 內重新檢查 exposure
與 publication 後，才呼叫既有 read-only
`_build_comparison_payload` 開啟 fold-005 source。lock 內會先以 durable
exclusive 寫入 `source_read_started` receipt；source 完成或失敗另寫
append-only outcome。若程序在 reader 中斷，重跑會讀取 stable exposure identity
並阻擋，不會換 output root 重新當成未讀；source 中途失敗的 data flags 保留
`null`，publish 失敗但 source 已完成則標記為 true。上述 preflight receipt
建立時尚未讀取 fold-005，因此當時 fold 是
`registered_not_read`；preflight 不是人工批准、正式 OOS 或 promotion。實際
核准後的單次讀取與其 exposure／結果，見下方 bounded confirmatory research run。

### 實際 fold-005 bounded confirmatory research run

root 核准後只以已凍結 v7 receipt 執行一次 fold-005/h5/ridge_logistic，命令為：

```powershell
.\.venv\Scripts\python.exe scripts\run_ml_allocation_confirmatory_comparison.py `
  --published-comparison output\v4_ml_base_oos_comparison_fold004_20260907_v7\runs\base-compare-18bb157241a439ff08105225\comparison.json `
  --output-root output\v4_ml_confirmatory_fold005_20260907
```

首次沙盒呼叫在 source read 前因無法開啟既有 D: lock 而退出，沒有讀取 fold-005；
之後以同一參數取得精確升權，未換 output root、policy、model、feature 或 fold。
正式 bounded run 在
`D:\Min\Python\Project\FA_Data\output\release_v4\.ml_heavy_chain.lock`
內完成 locked recheck，CLI 回傳
`status=confirmatory_comparison_completed`、`idempotent=false`，並保存
`source_read_completed_published` exposure。C: free bytes 為
`252,847,886,336`，D: source free bytes 為 `354,756,079,616`；兩者均保留
`214,748,364,800` safety reserve，persistent/temp 上限各為 `268,435,456`
bytes，4,096 MB memory budget 與 locked capacity check 均通過。

實際 comparison 位於
`output/v4_ml_confirmatory_fold005_20260907/runs/confirmatory-compare-df009decf1fad1243cb03178/comparison.json`，
單檔 `33,469,152` bytes，file SHA-256 為
`sha256:081545791bf148d93524a256cd3cd50c9e5d961aebe1ab84f6b3032229d94041`，
logical comparison hash 為
`sha256:548300c582ffbfdb1bb1e7bba34d34f5d9f271f497a8e1e24e80760cbf5b76d3`。
完成後 output root（含 pointer、local exposure 與 QA）共 `33,486,443` bytes，
仍低於 256 MiB。stable outcome 位於 v7 receipt 的
`runs/.confirmatory-exposures/a844b0db95607c30a7cdb72e5e388a2090ff9acc9f6e264c51b0a0642a639963.outcome.json`，
與 local outcome bytes/hash 均為 `1,499` /
`sha256:cfcfdde3a28323bdd62900ead2c85d82bc25479498b08af77e6cbb3836aae646`；
stable started receipt 仍保留，證明 source phase 先 durable started 再完成 outcome。

此 run 的 selected OOF row 為 `39,025`，決策日 `2016-03-02` 至
`2016-04-12` 共 28 日；每一日均形成 8 檔同一流動性池，共 224 pool rows。
12 個 lane 的 pool symbols 逐日一致，pool scope hash 為
`sha256:40dd0836058cc0f4c924a2ea9feec601b3292230e673bf5b46077830ef37dee6`。
parent/store、`fold-005/h5/ridge_logistic`、三項 policy、runner hash
`sha256:15ab98d72e925885aada9f518030231adb5ef717505b2b339b6a3c83fc882236`
與 binding hash `sha256:ab126ed3d063d8632196f29fb80a3ee3d6e6cf00ba0156910049379b05a34757`
均與 frozen request 相符；`formal_oos_allowed=false`、`production_alpha_bp=0`、
`broker_order_allowed=false`。

獨立核對命令為：

```powershell
.\.venv\Scripts\python.exe scripts\audit_ml_allocation_confirmatory_result.py `
  --comparison output\v4_ml_confirmatory_fold005_20260907\runs\confirmatory-compare-df009decf1fad1243cb03178\comparison.json `
  --stable-exposure output\v4_ml_base_oos_comparison_fold004_20260907_v7\runs\.confirmatory-exposures\a844b0db95607c30a7cdb72e5e388a2090ff9acc9f6e264c51b0a0642a639963.outcome.json `
  --output output\v4_ml_confirmatory_fold005_20260907\qa\independent_audit.json
```

audit 回傳 `status=independent_audit_passed`，JSON 為 `13,459` bytes，SHA-256
`sha256:d98c05cca05bb8da1754688ff42fa754b845b312400b0aca7e413a12cce1f66c`。
它以 Decimal/整數 minor unit 直接從每日 closing equity 重算 12 lanes 的
net/gross return 與 MDD，並核對每日 cost sum、parent/store logical/file hash、
local/stable exposure identity 及共同 pool；結果與 comparison summaries 全部
一致。研究 lane 的摘要如下：

| lane | status | requested / unfilled | executed trades | net return / MDD bp |
|---|---|---:|---:|---:|
| research data_quality base | no_orders_requested | 0 / 0 | 0 | 0 / 0 |
| research market_sector_cross_section base | no_orders_requested | 0 / 0 | 0 | 0 / 0 |
| research price_liquidity_technical base | no_fills_after_replay_constraints | 22 / 22 | 0 | 0 / 0 |
| research base mean | no_fills_after_replay_constraints | 12 / 12 | 0 | 0 / 0 |
| causal Rule | executed_with_replay_constraints | 175 / 174 | 4 | +9 / 34 |
| T-1 liquidity-pool equal weight | executed_with_replay_constraints | 226 / 224 | 4 | +66 / 41 |

四個 research ML lanes 沒有可成交交易，不能與 Rule/EW 的已成交報酬作 ML
優勢比較。data quality 與 market lane 沒有正的 basic signal；price 與 mean
分別有 22、12 個 requested orders，但完整 lot/現金/turnover replay 最終沒有
fill。兩個 ML lane 合計 32 個 `target_below_one_lot_retain_cash`（price 21、
mean 11），反映 1,000 股 lot 與資金限制，沒有事後放寬權重。

兩個 ML `execution_bar_missing_retain_current_state` 發生在同一筆
`2016-03-31 / 2317`；source 是 year=2016 的
`replay_source.sqlite`，source row hash 為
`sha256:2ac62788258aeb1c9028a70855e40430299f38987afea31bf158fd8d032e8805`。
`open_int`、`open_scale`、`close_int`、`close_scale` 四個
`replay_source.open_close_integer_components` 欄位皆為 NULL；
`price_event_at` 與 `price_available_at` 均為 `2016-03-30T14:30:00+08:00`，
volume `0` 是合法 observed value，median volume 為 `25,975,687`。因此該筆
保留現金狀態只能歸因於 source 欄位缺失，不能區分官方停牌／無成交與 ETL
遺漏，也不是可解讀的 ML 負報酬；同一缺件也影響 EW 該日一筆 requested order。
完整 source evidence 位於
`output/v4_ml_confirmatory_fold005_20260907/qa/independent_audit.json`。

strict sector lanes 仍受 `sector_id` 缺失阻擋；Rule 仍是
`replay_source.rule_score_bp` 的 causal research lane，沒有 formal Rule
champion history。這次 fold-005 是已執行的 frozen historical research，未來
forward effectiveness、正式 OOS 與 promotion 仍未成立。

## 驗證證據

以下均為「由 fixture 建立的實際 bounded store/run」，沒有使用正式全市場訓練：

- `tests/test_allocation_ooc_release_builder.py::test_minimal_ooc_release_attaches_calibrator_and_matches_direct_consumer`：以實際 `_NumericStore.read_feature_batch`、原始 final base/meta joblib 和獨立 quantization 重播逐 head、raw/calibrated downside bp、rank、expert vector、final meta 與 horizon aggregate；再以獨立 row audit 通過 adapter parity。
- 同一測試確認 calibrator 掛載前後 `meta_output` 相同，且 raw OOF vector 與 calibrated bp 分離。
- `tests/test_allocation_ooc_release_builder.py`：minimal profile、calibrator coverage、immutable release、maturity/pack/head contract 與 `predict_numeric` classifier 負例。
- 同一檔案的 derived 測試證明 57 欄 causal meta、fold-004 base/meta frozen replay、raw/calibrated meta 分流、parent/selection lineage、empty algorithm/partial OOF coverage 與容量 fail-closed；這些均是由 fixture 建立的實際 bounded store/run。
- `tests/test_allocation_base_expert_comparison.py`：11 tests passed，包含缺失 replay sidecar 在 preflight fail closed、strict default contract 回歸、研究週轉步進、兩日持倉 close-to-close／隔夜 gap、整數 equity summary、兩情境 fixture comparison、完整 pack scope 與 idempotence。
- `tests/test_allocation_replay_causal_volume_sidecar.py`：5 tests passed，覆蓋跨年 carry、同年 stored median parity、duplicate event、zero volume 與 target identity mismatch；實際 v7 sidecar evidence 額外確認 16,488 rows recovered、40,998 parity matches、0 mismatch、180 rows missing。
- `tests/test_allocation_base_expert_comparison_freeze_gate.py`：16 tests passed，確認 code/policy/parent/future request/fold mutation 均在 future source read 前 fail closed；另以 source failure、publish failure、`KeyboardInterrupt` 驗證 exposure flags、durable started receipt、stable identity 與同／不同 output root retry 均不會重新開啟 source。v7 CLI 實際返回 `validated_before_confirmatory_read`，runner preflight 實際返回 `preflight_passed_before_confirmatory_read`，均未讀 fold-005。
- `tests/test_portfolio_ml_out_of_core_pipeline.py::test_direct_annual_numeric_store_has_no_full_period_spool_or_jsonl`：bounded 三年度實際 Direct builder 走 annual assembly、第一年度 carry、下一年度 seed、完整 resume 與 finalized-year adoption；最新定向執行 1 test passed（17.87s）。每個年度 replay manifest 的 `volume_history_max_event_count_per_symbol <= 20`，非初始年度 `volume_history_seed_event_count > 0`，並驗證 checkpoint 重載後 hash/manifest 不變。
- `tests/test_portfolio_ml_direct_volume_carry.py`：4 tests passed，覆蓋 carry serialize/reload、跨年 median、duplicate/zero volume、future seed/event 與舊 carry schema fail closed。
- 真實 output 已由 `AllocationReleaseAdapter` 成功載入；兩筆以 Direct frozen numeric rows 建立的 daily inference audit 中，raw artifact 與 attached calibrator 的 `meta_output` 完全相同，且每個 base expert 均滿足 calibrated downside bp 對應 uncalibrated bp 的 calibrator mapping。
- 獨立 heldout replay 逐一重建三個 parent fold-004 base `oof.i32` 與 derived fold-004 meta `oof.i32`：`base_oof_all_matched=true`、`meta_oof_matched=true`、`row_count=57,666`、`target_label_reads=0`；這個 expected path 不使用 daily consumer，也不代表 2026 forward effectiveness。
- 上述真實執行的可讀 JSON sidecar 為 `output/v4_ml_derived_h5_20260907_real_qa/daily_inference.json`（evidence hash `sha256:c407f94ca23666626ae398fe7515871ce235fb536e1d3c7b2ea17361f57bf5d5`）與 `output/v4_ml_derived_h5_20260907_real_qa/independent_heldout_replay.json`（evidence hash `sha256:cba7a12b23a8de7ba324742ed4a5e7334167e9be7991baa6af058b6854ec6a31`）。daily sample 使用 Direct frozen numeric rows 轉成 inference contract，row id 是 QA sample identity；它證明 consumer wiring，不替代自然日 producer 或 forward effectiveness。
- `tests/test_ml_allocation_inference_service.py`：8 tests passed，包含 legacy artifact 維持 calibrated meta vector 的回歸檢查。
- `pytest tests/test_allocation_rank_contract.py tests/test_allocation_ooc_release_builder.py tests/test_daily_ml_allocation_derived_shadow.py -q -o addopts=`：16 passed；只有既有 pytest cache permission warning。
- `mypy --explicit-package-bases` owner 10 files（family policy/rank、OOC trainer/builder、inference、derived/daily CLI/orchestration、PIT exporter、inference CLI）：Success。
- 變更 Python 檔 `py_compile`：通過。

本切片的結論是「可載入、可驗證的 calibrated shadow release producer/consumer
路徑已具 bounded 證據」。正式 promotion 仍被證據門檻阻擋，不能由本次 bounded
run 推導 promotion。

## root 同步與審核清單

1. 審查上述 owner 檔案，確認 shared mapping evidence 與 raw/calibrated meta 分流。
2. 在隔離雙根重跑 builder 測試及 source acceptance machine review，保留各自輸出與 hash。
3. 由 root 決定是否將 bounded release root 納入後續 shadow observation；不得把本次 publication 當成正式 promotion input。
4. 後續若要擴展多 horizon、challenger 或 full OOC，需另行補齊其 profile、head coverage、calibration 與逐輸出 parity 證據。

## v3 60-feature linear shadow release（本輪）

本輪新增的 owner 路徑是 `ml_module/allocation_v3_linear_release.py`、
`scripts/preflight_ml_allocation_v3_linear_release.py` 與
`scripts/build_ml_allocation_v3_linear_release.py`。它只接受
`allocation-inference-input-v3` 的 frozen contract，保留兩個 legacy
technical sign 欄位排除，並以 official `market_indices` TAIEX close 在
Decimal 邊界推導兩個 market change features；舊 v2 artifact 不會被載入或
改寫。base heads 的 fit scope 是 `fold-001.train`，只以最多 100,000 rows
作 deterministic sample；`fold-002.test` 只用來檢查 target scope，
`fold-003.test` 與 `fold-004.test` 才是新 base 的雙 fold downside calibration
source。這樣 calibration labels 不會落在 base fit scope 內，也沒有讀
fold-005/006。

唯讀 preflight 已由實際 D/C 路徑執行並保存於
`output/v4_ml_allocation_v3_linear_20260907/preflight.json`：檔案 25,438
bytes，file SHA-256 為
`sha256:7d01abb4f4a522e96b8f6bf91e01e0854494510929948fca85115a0fba314ef`。
輸入是 11 rows、60 features，v3 input compressed hash 為
`sha256:fdda4d32c54d4509781ac0597c4b6e8b6709cfd2da0bc526e893759cfee5c735`，
contract hash 為
`sha256:2ccf5ed7043829d8cac15e509e7a73ef78365f72495c6257f99fa0de756011f6`。
parent Direct manifest hash 為
`sha256:e053aaf32bf978834eaf158791ad1170cf0d2909fea0f3a207bbe801150f0689`。

preflight 以 `rows.sqlite` 的完整 `decision_at` 做分離核對：base fit
sample 與 calibration fold-003/fold-004 的 row identity 無重疊，兩個
calibration fold 依 decision timestamp 嚴格排序；base fit row identity hash
為 `sha256:6bd13f0f7bee962cd69d37d132eb844aea91b90395cd6bb9840609ffa87a640a`，
fold-003 為
`sha256:0bf2d3c9127f6de6c1ede1e53164029634f064dc08a1caaaa6a303026770a200`，
fold-004 為
`sha256:4f7cc5255505b3b7e57de9511fa2c9f9ccc658ed229b682d87d761017dd4badc`。
兩個 calibration fold 的 h5 label `available_at` 均晚於各自 decision_at，
因此這裡的 calibration 不是同一 rows 的 in-sample replay。

market source 是唯讀 `twstock.db` 的 `market_indices/TAIEX`；該既有日期表沒有
事件 timestamp，v3 沿正式 assembler 的 source contract 將每筆 close 綁定為
`Asia/Taipei 14:30:00` 的 event/availability，並用
`official-consecutive-close-before-decision.v2` 選擇決策 timestamp 以前的
兩個官方連續 session。例：`2014-01-06T08:30:00+08:00` 只使用
2014-01-02 與 2014-01-03 close，不使用 2014-01-06 同日 close；fit 有 11 個、
meta 有 6 個、fold-003/004 各有 4 個 pair 不可證明，這些 row 會保留 missing
mask，不能以任意舊日 close 補值。

fold-001 sample 的 h5 labels 均可用（benchmark excess return
`-3,193..3,957 bp`、downside classes `32,638/67,362`、fill classes
`731/99,269`）；sector excess label 仍是 `100,000/100,000` missing。
fold-003/004 calibration source 的 downside classes 分別是
`23,391/33,951` 與 `21,014/36,652`，因此 calibrator 具備正負 class。
fold-002 target check 確認六欄全常數：`target_weight_bp`、`delta_weight_bp`、
`risk_contribution_bp`、`risky_budget_bp`、`rebalance_worthwhile` 均為 0，
`cash_bp` 為 10,000。基於這個實際資料事實，本 release 不 fit Meta；只放
`degenerate_constant_targets_adapter_neutral` 的 schema-compatible neutral
Meta，不能把它當配置器、績效或 alpha 證據。

preflight 的 C output free bytes 為 `252,452,909,056`，D source free bytes
為 `343,977,132,032`；兩邊均通過新增/暫存各 `1,073,741,824` bytes、memory
`4,096 MB` 與 `214,748,364,800` bytes safety reserve。shared lock 明確是
`D:\Min\Python\Project\FA_Data\output\release_v4\.ml_heavy_chain.lock`。
此前的 lock、feature order、DQ projection 與 inference clock 失敗均保留為
獨立的 blocked receipts，沒有把失敗路徑寫成成功。lock 釋放後，依相同
output、input、fold、policy 與 parent 取得同一個 shared lock 完成 bounded
build；沒有改用其他 output、fold、policy 或 parent，也沒有重新讀取
fold-005/006。

定向驗證已通過：

```text
tests/test_allocation_v3_linear_release.py
13 passed

mypy --explicit-package-bases
  ml_module/allocation_v3_linear_release.py
  scripts/preflight_ml_allocation_v3_linear_release.py
  scripts/build_ml_allocation_v3_linear_release.py
  tests/test_allocation_v3_linear_release.py
Success: no issues found

py_compile：上述 4 個 Python 檔通過
```

上述 preflight 後的實際 bounded build、release readback 與獨立 audit 詳見下節；
所有 publication 仍不具 formal OOS、production、broker 或 promotion 權限。

## v3 真實 bounded build 與 readback（2026-09-07）

正式 CLI 仍由 shared
`D:\Min\Python\Project\FA_Data\output\release_v4\.ml_heavy_chain.lock`
保護，唯讀 `D:` Direct parent/SQLite，新增檔案只落在 repo 的
`output/v4_ml_allocation_v3_linear_20260907`。實際命令為：

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts\build_ml_allocation_v3_linear_release.py `
  --v3-input C:\Users\archi\AppData\Local\Temp\technical_analysis_postfreeze_feature_repair_k7dq\post_freeze_shadow_feature_repair.json.gz `
  --parent-store-manifest D:\Min\Python\Project\FA_Data\output\release_v4\portfolio_ml_direct_numeric_production_v4_v2\runs\direct-ooc-505c6adaf3f71a0c8f0a274e\manifest.json `
  --market-database D:\Min\Python\Project\FA_Data\sqlite\twstock.db `
  --output-root output\v4_ml_allocation_v3_linear_20260907
```

實際 `build_result.json` 為 60,120 bytes，SHA-256 為
`sha256:a5f9b6d5e2542b3beafbfca200f16f23dac9a97c7590bc2e928763f5c27c1916`，
狀態是 `v3_linear_shadow_release_published`。release ID 為
`v3-linear-h5-67e0b583037dda60`，root 是
`output/v4_ml_allocation_v3_linear_20260907/runs/v3-linear-h5-67e0b583037dda60`，
release identity 為
`sha256:904450b10bd131b225217f53f1148e1921318aa6d73fa54ec4475da9cc98039e`。
該 release directory 實際為 4,517,696 bytes；publish 回報含 pointer 為
4,518,164 bytes。最新 pointer `latest_manifest.json` 為 468 bytes，SHA-256
為 `sha256:0af8f0f794fc356b614b591d96401b6eca5c2f29425f259a66ca1a0a2676ead0`，
指向同一 release identity。

release 內檔案與 hash 如下：

- `model.joblib`: 4,435,486 bytes，
  `sha256:4efd05a6b84e0d2c6bf841703ecfb305eeef8aad30bf6725773aef784729a257`
- `calibrator.json`: 50,482 bytes，
  `sha256:8ed3fb8dd8e5b034f9d2e9f110213fd54ff7f3358968b836696abe4119a846b9`
- `preprocessor.json`: 294 bytes，
  `sha256:68e137c5178722a39f2bfb31082fe39ca85a4e2fcb4f97bbd69d3406d532ad5b`
- `release_manifest.json`: 5,546 bytes，
  `sha256:be3d1f98fff78057cbf9bb4043964e48e52c03cf32aa7bfe6a89cb809911ad1e`
- `training_manifest.json`: 25,888 bytes，
  `sha256:eeb12343fb84fe0c4cb8ca21fca141e13109dc8e6dfac26deb7d9691fe95fb96`

這次 fit sample 是 100,000 rows，neutral Meta validation 使用 53,992 rows，
兩個 calibration fold 共 114,146 rows（fold-003 57,339、fold-004 56,807）。
parent aggregate DQ projection 明確排除 fit `1,430/145,977`、meta `0/53,992`、
fold-003 `3/57,342`、fold-004 `859/57,666`；排除列保留為排除，不被清成
observed 或零值。這是完整 rows 的可證明性選擇，帶有 coverage 與 selection bias
限制；它不支持將該 sample 外推成完整 parent 的績效證據。market pair 仍保留
fit 11、meta 6、fold-003/004 各 4 個無法證明官方連續 session 的日期，依
missing mask fail closed。

calibrator 為 `v3-isotonic-b0814761c2f681aa`，contract hash 為
`sha256:fe0179199b7d864cd5cd33dc5a622bdf2f45a555398aee3bf86bd5d9a13c1e94`，
mapping hash 為
`sha256:46a6730b3aa7335f90ee4feb0422ea24660bb7a19244de35ba5f916fa1f15724`。
fit 使用 fold-001，校準只用 withheld fold-003/004；target maturity、row identity
與時間順序在 preflight/build 中驗證，沒有用 calibration row 當 base fit。Direct
targets 仍為全常數，因此 `target_summary_status` 是
`degenerate_constant_targets_adapter_neutral`，release 沒有把 neutral Meta 當
可識別配置器。

readback 輸入保留真實 `2026-09-07T18:00:00+08:00` capture timestamp，沒有倒填
08:30；`build_result` 的 `inference_readback_mode` 是
`post_freeze_research_shadow`、`inference_readback_status` 是
`verified_after_publish`。獨立 audit 位於
`output/v4_ml_allocation_v3_linear_20260907/qa/independent_audit.json`，1,823
bytes，SHA-256 為
`sha256:71644a5bc53a4293cfa87fb9e10db420a1569a24ac50a6a32c1899789d87131f`；
狀態 `independent_v3_release_audit_passed`，11 rows 的 33 個 expert outputs
逐一核對 attached calibrator mapping，audit inference mode 同為
`post_freeze_research_shadow`，inference audit hash 為
`sha256:7e3070540453aabc9e7a69d0c1a32fdc1d925e7965c1faa8bdc33c41b9c6adc2`。
這證明 `AllocationReleaseAdapter.load()` 與實際 service inference/readback
成功；它仍是 research shadow，不是 formal daily decision。

完整 consumer audit 已持久保存於
`output/v4_ml_allocation_v3_linear_20260907/qa/inference_readback.json`，大小
24,965 bytes，file SHA-256 為
`sha256:503bdcffa0e2f7158cf44c7f158df55a3c43db864c2446b11172ea651f6e5af0`。
其中保留 11 rows、實際 `2026-09-07T18:00:00+08:00`、proposal hash
`sha256:44ee653a955ea9b49e8b74cc815b4254d685db2c1abf74dda8b408a187d3942e`、
replay hash
`sha256:7ea5c8ab2ed4a607a03ddba544c5521982c421d86262fa5540e7ae1835999ca1`、
三個 pack 的逐列 expert output 與 calibrated/uncalibrated bp。可重播的最小
只讀命令如下；它只 load release、讀 frozen v3 input、執行 inference 與
calibrator audit，不 fit 或寫入 D:

```powershell
.\.venv\Scripts\python.exe scripts\audit_ml_allocation_v3_linear_release.py `
  --release-root output\v4_ml_allocation_v3_linear_20260907\runs\v3-linear-h5-67e0b583037dda60 `
  --v3-input C:\Users\archi\AppData\Local\Temp\technical_analysis_postfreeze_feature_repair_k7dq\post_freeze_shadow_feature_repair.json.gz `
  --output output\v4_ml_allocation_v3_linear_20260907\qa\independent_audit_with_readback.json `
  --readback-output output\v4_ml_allocation_v3_linear_20260907\qa\inference_readback.json
```

audit CLI 會先解析並檢查兩個輸出路徑：輸出不得位於 immutable release
root、不得與 frozen v3 input 或其既有 hard-link/same-file alias 相同，摘要與
完整 readback 也必須是不同檔案。負例測試位於
`tests/test_audit_ml_allocation_v3_linear_release.py`；因此 audit 重播不會以
輸出路徑覆寫 release、model 或 input bytes。

`independent_audit_with_readback.json` 為 2,061 bytes，file SHA-256 為
`sha256:b4297966d1db0bdb1e788e4c5171602d2febc504b53baaf39e0e580755adb01b`。
其 `inference_audit_hash` 與 build result 相同。該 hash 使用
`payload_hash`：JSON 以 `ensure_ascii=False`、`sort_keys=True`、
`separators=(",", ":")` 編碼為 UTF-8 後取 SHA-256；外部對
`inference_readback.json` 的 canonical payload 重算值為
`sha256:7e3070540453aabc9e7a69d0c1a32fdc1d925e7965c1faa8bdc33c41b9c6adc2`。

`training_manifest.json` 的 `readback_inference_mode` 與 nested
`inference_readback.mode` 同為 research mode，但 status 固定為
`planned_before_publish`，因 training manifest 在 publish 前寫入；它本身不
宣稱 inference 成功。只有 build result 的 `verified_after_publish` 與上述
獨立 audit 才是成功證據。此欄位也納入 training identity：本輪新 training hash
為 `sha256:0a1f923b182c3beedfc575e3af40cfa361d06d32864e03e9909be5a908c248e3`。
先前 readback 失敗的 `v3-linear-h5-e1073e8c81d0e80a` 仍保留 immutable；其
release identity 是
`sha256:1486d56d1d3546b3056b59eee31a987fd8ff2c367bca35859d2695a400a13cbe`，
training hash 是
`sha256:a4bd5064b2d32b3428f33b7a02a955435e99016c268879da8132cdbc4066509f`，
沒有被 retry 覆寫。新的 identity 反映 readback status 綁定範圍改變；
`_publish_release` 只在既有 identity 完全相同時重用 release directory，並以
atomic replace 修復 latest pointer，不修改既有 artifact bytes。

容量紀錄是在 shared lock 內取得：C: free bytes `252,322,021,376`、D:
source free bytes `333,611,454,464`，兩邊均保留 200 GiB reserve；persistent
與 producer temporary budget 各 1 GiB。執行期間取樣 peak RSS 為
`769,716,224` bytes，producer-owned temporary root peak 為 `0` bytes。memory
欄位的 enforcement 是 sampling/checkpoints，temporary 觀測範圍只涵蓋 producer
自己的 temp root，因此不宣稱作業系統硬上限或所有第三方暫存均已量測。

正式安全欄位全部維持 `formal_oos_allowed=false`、`production_alpha_bp=0`、
`production_action_allowed=false`、`broker_order_allowed=false`、
`promotion_eligible=false`。先前的
`build_result_blocked_lock.json`、`build_result_blocked_lock_race.json`、
`build_result_blocked_feature_order.json`、`build_result_blocked_dq_projection.json`、
`build_result_blocked_inference_clock.json` 與
`build_result_blocked_inference_clock_retry.json` 均保留；clock blocked receipt
只記錄失敗旗標，沒有被覆寫成成功。此 v3 release 目前可 load/infer 的範圍是
research shadow；沒有正式 promotion、alpha 或 broker 授權。

## v3 持久 readback bundle（2026-09-07）

為避免研究 readback 依賴已清理的 TEMP frozen input，建立了小型
content-addressed bundle：

- manifest：`output/v4_ml_allocation_v3_linear_20260907/qa/readback_bundle/manifests/1f119043742d32976c206eed9b63220bc5c4c4002d35981f1684bc37ab9eadbf.json`，file SHA-256 為 `sha256:ed80321d2b57912a405945de287a3b1690e193f017228a12d564980f0d1548b1`，bundle identity 同為 `sha256:1f119043742d32976c206eed9b63220bc5c4c4002d35981f1684bc37ab9eadbf`。
- bundle 總大小 `50,144` bytes；其中保存原始 gzip input bytes `35,254` bytes，SHA-256 為 `sha256:fdda4d32c54d4509781ac0597c4b6e8b6709cfd2da0bc526e893759cfee5c735`，另保存 release manifest 與不含 capacity/TEMP path 的 training lineage snapshot。沒有複製 model、Direct/PIT store、SQLite 或全量資料。
- 第二次以同一 input／release 重跑回報 `readback_bundle_reused`、`new_bytes_written=0`，manifest 與 object bytes 不變。object 使用同目錄 temp + fsync + create-only atomic link；一般 exception（包含 `KeyboardInterrupt`）會在 finally 清理 partial temp，硬終止仍可能留下 `.partial`，該檔不會被當成 hash object，會由共用 scanner 計入 bundle 容量，需由受控清理流程另行移除。

bundle 內容定址 loader 接入 audit CLI；以下命令不傳原 TEMP 路徑，仍由
`AllocationReleaseAdapter.load()` 完成 11 rows／33 experts 的實際 calibrated
readback。輸出放在 bundle 外，避免改寫 bundle：

```powershell
.\.venv\Scripts\python.exe scripts\audit_ml_allocation_v3_linear_release.py `
  --release-root output\v4_ml_allocation_v3_linear_20260907\runs\v3-linear-h5-67e0b583037dda60 `
  --readback-bundle output\v4_ml_allocation_v3_linear_20260907\qa\readback_bundle\manifests\1f119043742d32976c206eed9b63220bc5c4c4002d35981f1684bc37ab9eadbf.json `
  --output output\v4_ml_allocation_v3_linear_20260907\qa\independent_audit_from_bundle.json `
  --readback-output output\v4_ml_allocation_v3_linear_20260907\qa\inference_readback_from_bundle.json
```

實際結果為 `independent_v3_release_audit_passed`；summary 為 `2,596` bytes，
SHA-256 `sha256:88238a43b5ff68ccdf4a7d9c76874b8cb59fb43ea9b2f07fd90b8ae20ac36674`。
bundle readback 的 canonical `inference_audit_hash` 仍為
`sha256:7e3070540453aabc9e7a69d0c1a32fdc1d925e7965c1faa8bdc33c41b9c6adc2`，
與原 TEMP input readback 相同；完整 readback file SHA-256 為
`sha256:503bdcffa0e2f7158cf44c7f158df55a3c43db864c2446b11172ea651f6e5af0`。
bundle manifest、object 與 audit output 均受 path traversal／source overlap／
same-file 檢查保護。所有安全旗標仍為 formal false、alpha 0、broker false；
bundle 可重播性不等於 formal OOS 或 promotion 證據。

## Direct 全現金 target 根因診斷（2026-09-07）

本次對 immutable Direct parent 做了完整唯讀 bounded 掃描，沒有重建資料或
修改 D。來源 manifest 是
`D:\Min\Python\Project\FA_Data\output\release_v4\portfolio_ml_direct_numeric_production_v4_v2\runs\direct-ooc-0f731f46b29c0b146fa20145\manifest.json`，
manifest hash 為
`sha256:72940efe98ad3c7bbd76b858125f4e183d0dce8312c1275ef14db067ddd36ebb`。
診斷報告位於
`output/v4_ml_target_degeneracy_diagnostic_20260907/diagnostic_full.json`，
大小為 78,401 bytes，SHA-256 為
`sha256:5bd180defa9fc6042bd104ca4740ec928e4579a3cb9a9350e8dfc83b06d68f06`。
實際命令為：

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_ml_allocation_target_degeneracy.py `
  --manifest D:\Min\Python\Project\FA_Data\output\release_v4\portfolio_ml_direct_numeric_production_v4_v2\runs\direct-ooc-0f731f46b29c0b146fa20145\manifest.json `
  --output output\v4_ml_target_degeneracy_diagnostic_20260907\diagnostic_full.json `
  --chunk-rows 65536
```

報告涵蓋 2014--2026 共 13 年、2,840 個 decision dates、3,347,662 rows；
target `target_weight_bp`、`delta_weight_bp`、`risk_contribution_bp`、
`risky_budget_bp`、`rebalance_worthwhile` 的 min/max 都是 0，`cash_bp`
則每列都是 10,000。這不是 label 全零：四個 horizon 的
`benchmark_excess_return_bp` 都有非零且有正負變化；例如 h20 範圍是
-11,287 至 726,792，非零 3,345,932 列。`target_available_at` 與
`max_label_available_at` 均在 training cutoff 前成熟，兩者 future count 都是
0，因此全 cash 退化不是由尚未成熟的 label 造成。

eligibility 的來源證據同樣明確：replay source 的 sector 欄位
3,347,662 列全部缺失，沒有任何 observed PIT sector candidate。manifest 同時
記錄 `pit_sector_membership_missing_teacher_new_positions_disabled`、
`portfolio_ledger_missing_cash_only_fallback_turnover_and_cooldown_not_learned`
與 `formal_rule_champion_snapshot_history_missing_formal_replay_blocked`。
因此診斷分類是
`data_blocked_no_eligible_sector_candidates`：teacher 因 PIT sector 不可證明而
fail closed，ledger 缺失則使 state 採 cash-only fallback。這份證據不能回答
修復 sector 後策略是否仍選 cash，也不能把全 cash target 當成已學會的配置
政策；完整報告仍保留 price、volume、Rule score 與 sector 的 observed/missing
計數供後續查源。報告的 provenance 也固定標示 label 由
`PortfolioMLDatasetAssembler._build_label_spool` 先於 teacher target 產生，maturity
取自 `rows.sqlite` 的兩個 availability timestamp，eligibility 取自
`replay_source.sqlite.sector_id` 與 Direct blocker；因此這次 label 的變化不能被
全 cash target 反向解讀成 teacher 已辨識出可交易配置。

程式在 `portfolio_ml_dataset_assembler.py` 與
`portfolio_ml_direct_numeric_store.py` 新增 bounded
`teacher_target_diagnostics` provenance counters；既有 immutable parent 沒有這個
欄位時診斷讀取保持相容，不會回寫或重算舊 artifacts；但 OOC teacher gate
會對缺少 provenance 的新訓練 fail closed。新年度可記錄 decision／label
列數、候選／eligible／UNKNOWN sector 數、teacher incomplete、non-cash target
與 cash-only state 數，讓下一個正式來源完整的 run 能區分策略結果與資料阻擋。

後續修復只允許 future formal-input handoff：由
`run_formal_input_producer_daily.py` 產生 candidate，待具備 decision-time
`available_at/effective_from` 的 PIT sector membership、append-only causal
non-cash portfolio ledger、以及同日期範圍且 hash 驗證的 formal Rule champion
history，再由 `maintain_ml_direct_v3_refresh_chain.py` 綁定來源 hash 與
training cutoff 消費。candidate artifact 不會被當成歷史 formal input，也不做
歷史零值回填、promotion、alpha 或 broker action。

## Teacher target eligibility gate 與 h20 極值唯讀 audit（2026-09-07）

本輪把全現金診斷落成 `allocation-teacher-eligibility-gate.v1`。OOC
`train()` 先以 bounded chunk scan 讀取六個整數 target 欄位，再驗證 Direct／
dataset manifest 的 `assembly_blockers` 與 `teacher_target_diagnostics`；尚未
建立 output、shared artifact 或啟動任何 fit 前即停止。gate 不讀取成熟後的
label 值，`uses_future_labels=false`；缺 PIT sector、causal non-cash ledger、
formal Rule history、UNKNOWN sector 或 incomplete teacher provenance 都不能
訓練 allocation teacher。只有完整候選、狀態與決策計數都可核對時，全 cash
才會標成 `allowed_strategy_cash_only_with_candidates`，而且仍固定
`formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false`。

assembler 現在保存 bounded `teacher_target_diagnostics`，OOC numeric store
沿用該欄位，讓未來正式輸入可以區分「有候選但策略選 cash」與「資料阻塞導致
cash-only」。不依賴 teacher 的 base expert outcome research 仍走既有
`allocation_base_expert_comparison.py`，不讀 teacher targets、不重訓 Meta，
不能把 gate 通過或阻擋解讀成投資優勢。現有 Direct parent 是舊 immutable
manifest，仍保留原 bytes；更新後的唯讀診斷報告位於
`output/v4_ml_target_degeneracy_diagnostic_20260907/diagnostic_full_teacher_gate.json`，
大小 `79,716` bytes，file SHA-256 為
`sha256:a962d808e46d9044748e24358406cb7d66b1c84b5f6e0608b890245fdef58c2a`。
報告對 `3,347,662` rows 的 gate 結果是
`blocked_missing_formal_teacher_inputs`，原因為 PIT sector、cash-only
ledger 與 formal Rule history 三項缺件；這不是 promotion 或正式輸入授權。
在加入正向 provenance 驗證後，最新唯讀重播報告為
`output/v4_ml_target_degeneracy_diagnostic_20260907/diagnostic_full_teacher_provenance.json`
（79,821 bytes，file SHA-256=
`sha256:982b5e9d55e96e53aeefac57bdb888ae481964f1aa0304af21ff1f6385124809`）。
其中 `teacher_input_provenance_present=false`；因此即使舊 manifest 的 aggregate
counter 存在，也不會被標為可 fit。此檔與舊 gate 報告並存，沒有覆寫 Direct parent。

同一 parent 的 h20 `benchmark_excess_return_bp` 最大值以 chunked memmap
找出 `726,792bp`，對應 `row:2026-05-20:3017`（local index `136,478`），
h20 終點為 `2026-06-16`。唯讀 audit 位於
`output/v4_ml_label_extreme_audit_20260907/label_extreme_2026.json`；它保存
Direct rows/replay、原始 `twstock.db`、PIT shard 與 official corporate-action
canonical hash；報告大小 `7,666` bytes，file SHA-256 為
`sha256:74cc971d649d077619e7878889b35207c1fa2ebd977f4fb040a744acba3e0295`，
並以 Decimal 重算 `stock_return=728,318bp`、
`TAIEX=1,446bp`、扣 `80bp` 後的 `726,792bp`，與 label 完全相等。原始
`daily_prices` 顯示 3017 在 `2026-05-19` close `2390`、`2026-05-20`
open `32.1`、`2026-05-21` open `2445`；PIT encoded values 同樣是
`24550000`、`321000`、`24450000`（scale `10000`），因此標記
`source_price_scale_anomaly_unresolved`；該 2026 PIT shard file hash 為
`sha256:139f8972650b0f8995b309713f1181d5ab13721a2043394569f1eac7424537b1`。
官方 corporate-action canonical
hash 為 `sha256:fc34c1db2ec06d3e2123dd927d2681ef6c194093563923385b72a7c867e2b36a`，
該 label interval 內沒有 3017 事件；`2026-08-19` 的 ex-right result 在
h20 之後，不能用來替五月價格異常背書。這份 audit 只保存證據，不截斷、
補值、修 label 或重跑 parent；該極值不可用作績效有效性結論。

執行 h20 audit 的最小唯讀命令如下，輸出必須在 repo `output` 且不得覆蓋
任何 D 槽來源：

```powershell
.\.venv\Scripts\python.exe scripts\audit_ml_allocation_label_extreme.py `
  --manifest D:\Min\Python\Project\FA_Data\output\release_v4\portfolio_ml_direct_numeric_production_v4_v2\runs\direct-ooc-0f731f46b29c0b146fa20145\manifest.json `
  --source-db D:\Min\Python\Project\FA_Data\sqlite\twstock.db `
  --raw-shard D:\Min\Python\Project\FA_Data\output\release_v4\ml_pit_year_shards\runs\pit-f62b6b24b4c2f32331fc92a5\all_field_enriched\year=2026.jsonl.gz `
  --corporate-action-manifest D:\Min\Python\Project\FA_Data\output\release_v4\official_market_events\runs\official-market-events-f82f468e0016146d40b3c596\manifest.json `
  --output output\v4_ml_label_extreme_audit_20260907\label_extreme_2026.json
```

## 2026-05-20 daily price source quarantine 與 teacher provenance gate（2026-09-07）

本次新增的來源稽核只讀 `D:\Min\Python\Project\FA_Data\sqlite\twstock.db`，並以
canonical `D:\Min\Python\Project\FA_Data\daily_price` 的日期 CSV 交叉核對；
沒有寫入 SQLite、D 槽 raw/PIT 或既有 Direct／label artifact。固定 detector
`two-sided-price-scale-discontinuity.v1` 只標記前一筆收盤、當筆開盤、下一筆開盤
相差超過 10 倍的 source row，不猜 corporate action，也不做價格校正。

稽核範圍為 2026-05-01 至 2026-06-30。實際找到 2026-05-20 的 33 個 symbol：
1514、1519、2059、2308、2345、2360、2364、2368、2383、2404、2449、2454、
2467、2486、2603、3017、3037、3167、3443、3533、3535、3583、3653、3661、
6139、6196、6442、6531、8021、8033、8046、8210、8996。每一列 SQLite 的
open／high／low／close／volume 均與同日 canonical TWSE CSV 不同；canonical 檔
SHA-256 是 `sha256:1fdbe6f5f9d539d59144115586b90768593be0ffca71558454e72a0205780385`，
可解析列 1,084，另有 4 列本身不是數值而保留 invalid-row sample。TPEX 檔不含
3017。SQLite anomaly 因此分類為
`sqlite_row_mismatch_against_canonical_daily_csv`，表示 persisted SQLite row
相對 canonical daily source 過時或被錯誤選入；不是把 canonical source 當作已修好。

對 3017 的具體 evidence 仍與 h20 audit 一致：SQLite／PIT 在 2026-05-20 是
32.1/31.9、scale=10000，而 canonical CSV 是 2425/2340、同一
`price_1e4` unit。PIT shard 的 `source_row_hash` 與 SQLite row 一致，故 exporter
的 Decimal scaling 沒有造成這次偏差；既有 label 仍 immutable，沒有補值、截斷或重訓。
完整 quarantine report：
`output/v4_ml_daily_price_source_quality_20260907/source_quality_20260520_v3.json`
（87,752 bytes，file SHA-256=`sha256:d45cc45195e5f7fe90553c1db3d126711a23d3f2c258da02e4e4014180268140`）。
v3 另外保存了 canonical CSV 的前一日／下一日 symbol context，供人工判讀
來源尺度斷裂；這些 context 只依日期檔案，不宣稱週末或缺檔已通過官方交易日
連續性驗證。v2 仍保留為前一版本的逐列 invalid sample 報告。
原先 parser 把同檔其他 4 個非數值 row 視為整檔 invalid 的初版也保留在
`source_quality_20260520.json`；v2 起改為逐列保留 invalid sample，不影響 33 個
受影響 symbol 的 canonical row 比對。

未來 PIT ingest 可在 `PITYearShardBuildRequest` 提供
`daily_price_source_dir`；exporter 會在建立 output/staging 前執行同一唯讀 guard，
遇到候選即停止，並可將 quarantine report 寫到 source root 以外的 repo output。
`scripts/scheduled/run_ml_raw_pit_refresh.py` 已把 data root 的 canonical daily
directory 傳入 builder command；此次沒有執行 scheduled rebuild，也沒有用該 guard
回寫 D。最小 CLI：

```powershell
.\.venv\Scripts\python.exe scripts\audit_ml_daily_price_source_quality.py `
  --sqlite D:\Min\Python\Project\FA_Data\sqlite\twstock.db `
  --daily-price-dir D:\Min\Python\Project\FA_Data\daily_price `
  --start-date 2026-05-01 --end-date 2026-06-30 `
  --output output\v4_ml_daily_price_source_quality_20260907\source_quality_20260520_v3.json
```

該 CLI 對這個真實範圍以 exit code `2` 表示「稽核完成但有 33 筆 quarantine
候選」；這是預期的 fail-closed gate，不代表命令執行失敗。報告自身的
`report_hash` 為
`sha256:c1faeb7ec5dd4cf771155d9376c6e6cc374830ca10b5c78d621078fa4b0b758c`。

同時收窄 `evaluate_allocation_teacher_eligibility`：只有 counters 的 manifest 現在
會回報 `blocked_missing_teacher_provenance`，不再標成策略可用。正向 gate 必須
附 `allocation-teacher-input-provenance.v1`，含 PIT sector、causal non-cash ledger、
formal Rule history 三個 source；每個 source 都要有實際 readback receipt path／file
hash、source manifest／identity hash、schema、row count、read-only、
available-before-decision 與完整決策日集合。decision rows 另逐日核對 candidate、
eligible、target mode，並與 diagnostics 的 candidate、non-cash/cash-only、label row
count 及 target summary observed row 數一致；任何 partial-date 或 zero-eligible day
都 fail closed。gate 不讀未來 label，也不把 counter positive 當來源 custody。

此 gate 的測試在
`tests/test_portfolio_ml_target_diagnostics.py`：
`test_teacher_gate_blocks_counter_only_candidates_without_source_readback`、
`test_teacher_gate_allows_only_hash_bound_complete_source_readback`、
`test_teacher_gate_rejects_partial_decision_date_candidate_coverage`、
`test_teacher_gate_rejects_target_row_count_mismatch`。本輪 source quality 測試在
`tests/test_ml_daily_price_source_quality.py`，涵蓋 canonical mismatch、canonical
raw anomaly、clean pass、source-root write protection 與 PIT builder 在 staging 前
停止。現有 Direct parent 沒有 positive provenance，故仍是
`blocked_missing_formal_teacher_inputs`／不可 fit；任何 future formal input 必須先
產生上述三來源的 durable readback，再由 OOC store 傳遞同一 provenance 欄位。

## 2026-05-20 mismatch root cause、ingest timing 與隔離 overlay（2026-09-07）

本輪把 2026-05-20 的 33 筆 mismatch 由 quarantine 擴充成可重播的唯讀
根因證據與 candidate-only consumer。實際 root-cause report 位於
`output/v4_ml_daily_price_source_quality_20260907/source_mismatch_root_cause_20260520_v1.json`
（24,538 bytes，`report_hash=sha256:db5ea6c92699673176e51d216ebbcc0404451c5af7802d51fc259939183a0767`）。
它逐筆保存 SQLite、當前 canonical CSV、歷史 backup 與 3017 的值，33/33
筆 SQLite 都與檔名含 `corrupt` 的
`D:\Min\Python\Project\FA_Data\meta_data\backup\daily_price_20260520_corrupt_20260624_152726.csv`
一致；backup file SHA-256 是
`sha256:4046a5cd48eb99c9e700610660980914840b4d6e8059f4b37596db9ffe2587fa`。
當前 canonical `daily_price/20260520.csv` SHA-256 是
`sha256:1fdbe6f5f9d539d59144115586b90768593be0ffca71558454e72a0205780385`，
SQLite file SHA-256 是
`sha256:5954d9d0901fdd2654ab6eff93898fe584d0ecc608d87783030e554f2e48bda0`。
3017 的 SQLite／歷史 backup 是 open `32.1`、close `31.9`、volume `4105026`，
canonical 是 open `2425.0`、close `2340.0`、volume `3568975`，兩邊都標示
`price_1e4`，所以不是代碼補零或價格尺度轉換造成。證據指向舊 daily CSV／
`meta_data/stock_data_whole.csv` 經 `UpdateService._upsert_sqlite_rows` 以
`(證券代號, 日期)` 寫入 persisted SQLite；`update_data_normalization` 只做
日期／代碼及欄名正規化。當前 CSV 由 `DataLoader.download_from_api` 的 TWSE
MI_INDEX contract 產生，但資料目錄沒有保存該次 HTTP response receipt，故
報告把 canonical 標為 candidate，沒有把它宣稱成官方真值或自動修復。

隔離 consumer 位於 `data_module/ml_daily_price_overlay.py`，CLI 是
`scripts/build_ml_daily_price_overlay.py`。實際 33 筆 overlay 為
`output/v4_ml_daily_price_source_quality_20260907/canonical_overlay_20260520_v1.json`
（24,287 bytes，`overlay_hash=sha256:af5b7d0bc15d1d6a7087cb49774c497e55ca9734fa8cbd3ed0a20ef4f353f7c2`）。
`load_daily_price_overlay()`／`overlay_rows()` 只讀 overlay 內的 canonical
candidate，並驗證內容 hash；原 SQLite 與 daily CSV bytes 在執行前後相同。
overlay 的 `formal_training_allowed=false`、`labels_mutated=false`、
`official_raw_response_receipt_present=false`，只能用來隔離重算／核對樣本，
不能用來更新 label、重訓或 promotion。

PIT source timing 現在明確分兩種模式：

* `retrospective_audit`（`two-sided-price-scale-discontinuity.v1`）可讀前一筆、
  當筆與下一筆，只能產生事後 quarantine evidence；報告的
  `uses_future_source_rows=true`，`historical_retroactive_filtering_allowed=false`。
* `ingest_guard`（`one-sided-price-scale-discontinuity.v1`）只讀當筆、前一筆與
  當筆 canonical evidence，SQL 不選 `next_open`，CSV 不讀下一個日期；沒有
  source receipt 時 `quality_known_at=null`，不以 mtime 或本次執行時間代替。

PIT `PITYearShardExporter` 已固定傳入 `quality_mode="ingest_guard"`，遇到
 mismatch／null／invalid row 會在建立 staging 前 fail closed，不會用事後雙側
 結果回溯排除 historical decision row。實際 33 檔 guard report 位於
 `output/v4_ml_daily_price_source_quality_20260907/source_quality_20260520_ingest_guard_33_v1.json`
（68,687 bytes，`report_hash=sha256:4da85edc65898240bc71a3d1637e5d56bfbef19b9d7a94acc7d71a5521a1ce39`），
`candidate_count=33`、`quality_mode=ingest_guard`、`uses_future_source_rows=false`，
CLI exit code `2` 僅表示完成稽核但 gate 有候選。此前全 universe guard 另發現
canonical 缺列／非法 SQLite rows；它們保留在廣域 audit，不與本次 33 檔 overlay
混為同一範圍。

Teacher provenance 也由宣告式 flags 提升為內容驗證。正向 receipt 目前支援
既有 v1 相容格式與新的 `allocation-teacher-input-provenance.v2`。v2 由
`data_module/teacher_input_source_producer.py` 實際唯讀解析 PIT sector sidecar、
causal ledger SQLite 與 signed Rule history，將逐 source、逐決策日的實體 rows
寫入 durable readback receipt；source manifest 綁 source bytes、schema、semantic
identity、row count 與 rows hash。gate 會重讀 source artifact，不接受只改 outer
hash／flags 的自洽 JSON；每列 `available_at <= decision_cutoffs[decision_date]`，
無法證明可得時間的來源回報 `teacher_source_availability_unproven`。read-only
custody 需有 `access_mode=read_only`、`query_only=true`、`write_performed=false`、
`source_rows_rebuilt_from_artifact=true` 及 manifest 的 read-only storage mode。
外層 `readback_verified`、`available_before_decision` 與 `read_only` 的 `true`
不再單獨構成證據。`tests/test_portfolio_ml_target_diagnostics.py` 新增任意 bytes
正確 outer hash、晚到 source、identity/date mismatch 負例；
`tests/test_ml_daily_price_source_quality.py` 新增 ingest guard 不讀 late next
row 與 aware `quality_known_at` 負例；實體 source-row producer、assembler bridge
與 gate 的整合測試在 `tests/test_teacher_input_source_producer.py`，目前
`3 passed`，包含 source bytes tamper rejection 與缺 ledger availability 的
blocked gate。此段未改 D、未讀新 fold、未重訓，亦不提升
任何 formal／alpha 權限。

Assembler 在三個正式 source path 都存在時，會呼叫
`build_teacher_source_row_provenance_for_assembly()`，把 v2 provenance 持久化在
`output_root/teacher_input_provenance/<storage-key>/`，再將同一份 mapping 寫入
publication manifest；沒有完整三來源時保留既有 v1／missing 語意，不能以 assembler
自己的 counters 補造來源。測試的正例使用實際 sidecar、Rule HMAC history 與
唯讀 ledger SQLite，並由 gate 重讀三個 artifact；這是 source rows→receipt→
assembler→gate 的可重跑小 fixture 證據。當前 Direct parent 仍沒有三個可證明
`available_at` 的 production source，因此真實 OOC 正式 fit 仍維持 blocked。

### 每日價格來源選擇防線（2026-09-07）

`data_module/daily_price_source_guard.py` 與 `app_module/update_service.py` 現在
對 daily price source fail closed：TWSE 日期檔存在時只讀檔名可驗證且檔內日期／schema
一致的日期檔，不再靜默 fallback 到 stale `meta_data/stock_data_whole.csv`；任何
非法日期檔名或檔內日期不一致都阻擋同步。正式 `prod` profile 只有具內容 SHA、日期集合、
row count、source path、quality 與版本綁定的 `stock_data_whole.csv.source.json` 才可
走 aggregate fallback；舊測試 profile 保留明示的相容降級狀態。`tests/test_daily_price_source_guard.py`
與既有 UpdateService 測試共 `69 passed`。這只修正 consumer/source-selection 防線，
沒有回寫正式 SQLite 或重建 D 歷史。

## 2026-05-20 TWSE 官方 response evidence 與更正候選（2026-09-07）

在受控網路讀取下，以既有 `DataLoader.download_from_api` 的 TWSE MI_INDEX
contract 對 `20260520` 發出一次 `type=ALL&response=json` 請求。官方 endpoint
回 HTTP 200；wire response 以 gzip 原始 bytes 保存，解壓後以同一個 stock table
parser 重新取出指定 33 symbols。此次 response 完成擷取時間為
`2026-09-07T19:24:00.737021+00:00`，這是 historical backfill 的
`quality_known_at`，不是 2026-05-20 盤前可得時間。

capture 目錄為
`output/v4_ml_daily_price_source_quality_20260907/twse_official_capture_20260520_v2/runs/twse-mi-index-20260520-all-f185b2e953836028/`：

* `response.json.gz`：823,208 bytes，wire SHA-256
  `sha256:f185b2e953836028b9c2ed70c380f41155f68abc6357843a33bed1afe1345cea`；
  解壓 JSON 為 4,293,884 bytes，SHA-256
  `sha256:c0d5739decee9efba163cbde2a238b35e8ee3b1b64300bc89717711c5ec3e866`。
* `receipt.json`：receipt hash
  `sha256:82183af8f848c52ac8a7b4321d4771f0a8d517eb00b74ba90d249169f0c5737b`；
  保存 endpoint、query、request/response headers、HTTP status、開始／完成時間、
  wire／decoded bytes 與 hash。
* `comparison.json`：comparison hash
  `sha256:edc6c029d76a3fa280002dd67deb1a75542d5b2da858c11e61a17519a9a5a741`；
  33/33 官方 rows 可重解析，33/33 與 current canonical 數值相符，0/33 與
  persisted SQLite 相符，0/33 與 named corrupt backup 相符，故 33 筆均只建立
  `isolated_candidate_not_applied` 更正候選。

以 3017 為例，官方 response 與 current canonical 都是
open `2425`、high `2435`、low `2325`、close `2340`、volume `3568975`，
而 SQLite／歷史 backup 是 open `32.1`、high `32.4`、low `31.8`、close `31.9`、
volume `4105026`；兩邊同為 `price_1e4`。比較使用 Decimal 數值等值，保留官方
原始小數格式，不把 `2340.00` 與 `2340.0` 誤判為差異。

官方 receipt 已綁入新的隔離 overlay：
`output/v4_ml_daily_price_source_quality_20260907/canonical_overlay_20260520_official_v1.json`
（30,620 bytes，`overlay_hash=sha256:5b8542725775a3f062f47f8e49d4f5e47f9b60bbce8ea96c9e3baac243b8c326`）。
它驗證 33 筆 official→canonical row binding，並保存 comparison／receipt／response
hash；`historical_decision_time_available=false`、`formal_training_allowed=false`、
`promotion_eligible=false`。overlay consumer 只讀該 artifact，沒有回寫 SQLite、
daily CSV、PIT 或 label。

capture／comparison／overlay 都是事後來源證據。因官方 response 沒有保存原始
2026-05-20 當日 HTTP receipt，這次結果不能把 canonical 或官方回補資料升格成
歷史決策時間的正式 PIT source，也不授權重建既有 label 或 promotion；原有
`source_mismatch_root_cause_20260520_v1.json`、SQLite、D backup 與 parent artifact
均保持不變。

root-cause v3 另以唯讀串流掃描
`D:\Min\Python\Project\FA_Data\meta_data\stock_data_whole.csv` 的 2026-05-20
目標日期／33 symbols：檔案 486,228,553 bytes、SHA-256
`sha256:a47ec6ee14856c15e04ff34f5baa246034267436df09d3a622aabe119460ed90`，
讀取 5,226,219 rows 後找到 33 筆，33/33 的 open／high／low／close／volume
與 SQLite 數值相符。v3 report 位於
`output/v4_ml_daily_price_source_quality_20260907/source_mismatch_root_cause_20260520_v3.json`
（48,181 bytes，`report_hash=sha256:f82dda543cbc2e5132d6d9178ff6edb1e5ebc6dd9f2cbe5733b0e53161ad191f`）。
此結果支持 `stock_data_whole.csv` 經既有 `daily_data`／
`UpdateService._upsert_sqlite_rows` writer-selection 或 stale-input 路徑進入
persisted SQLite，但沒有保存該次 writer 執行 receipt，故仍不能把確切 mutation
cause 稱為已證實；backup 的檔案 mtime 也只作診斷 metadata，不作可得時間證據。

### 官方 overlay 隔離 feature／label impact（2026-09-07）

`scripts/consume_ml_daily_price_overlay.py` 只讀取上述官方 overlay 與 D 槽
SQLite，在記憶體中建立兩個明確分離的結果：同日官方 OHLC／成交量只放在
`raw_price_diagnostic`，真正的 `decision_time_features` 僅使用決策日前一交易日
及其前一收盤。這修正了舊 v1 artifact 雖標示
`future_rows_used_as_features=false`、實際卻把 2026-05-20 同日收盤／成交量放進
`features` 的語意缺口。新入口固定使用
`post_capture_historical_research.v2`，同日 raw 值有
`feature_role=post_close_raw_price_diagnostic_only`，不宣稱可作 08:30 model
input；若找不到兩個嚴格早於決策日的 source sessions，consumer fail closed。

新 v2 impact artifact 位於
`output/v4_ml_daily_price_overlay_impact_20260907/impact_20260520_h20_v2_corrected.json`
（307,473 bytes，`impact_hash=sha256:30a54cfabcd1c0be9e158956b224619d33bb45aab9d29abc02e65116fb9a2f18`）。
artifact 實際消費 33/33 官方 rows；`raw_diagnostic_changed_feature_count=198`
（6 個 raw／衍生欄 × 33 列），這個數字不是全模型 feature impact，
`decision_time_feature_changed_count=0` 且 `model_feature_impact_claimed=false`。
原 SQLite 仍保留，v1 artifact 與先前 v2 初版 artifact 都未覆寫；本次
`v2_corrected` 是將通用 `features` key 改為盤前 input 後的新 immutable identity，
`overlay_selection` 明確記錄官方 receipt-bound candidate 只供事後研究。輸出保留每列的
`source_date=2026-05-19`、`available_before_decision=true` 與無 intraday timestamp
聲明，避免把事後 mtime／擷取時間冒充盤前 custody。

h20 labels 仍由 Decimal 逐列獨立重算，`return_evidence` 保存 entry open、20th
session exit close、TAIEX benchmark entry／exit、`buy_cost_bp=25`、
`sell_cost_bp=55`、`transaction_cost_bp=80` 及整數 bp 公式。3017 的既有
`benchmark_excess_return_bp=726792` 與 extreme audit 一致，官方 candidate
重算為 `-1753`；`downside_observed` 由 0 變 1。其餘 32 筆 h20 excess 也有
變化，但仍是事後研究 evidence，不能把 candidate label 宣稱為 2026-05-20
決策時可得，也不能用它重訓或 promotion。原 v1 artifact
`impact_20260520_h20_v1.json`（68,479 bytes，hash
`sha256:ad9b4d89db8bd4722d8338a3c282320d9c29ca8d21d4e475315447b1c5185532`）保留作
歷史相容證據，不與 v2 的盤前 feature 語意混用。

定向測試為 `tests/test_ml_daily_price_overlay_consumer.py`（6 passed），其中
`test_consumer_rejects_same_day_or_late_feature_source` 驗證同日／晚到資料不能
成為 model input；`tests/test_daily_price_source_guard.py` 另直接呼叫真正的
`scripts.merge_daily_data.merge_daily_data`，驗證非法檔名與檔內日期在寫入前拒絕，成功
writer 產生內容 SHA 綁定的 aggregate receipt。

為讓 arithmetic verification 與 consumer implementation 分離，另以
`scripts/audit_ml_daily_price_overlay_impact.py` 只讀 v2 artifact 的 evidence，
獨立用 Decimal 重算 33 列 entry／exit／TAIEX benchmark 與成本公式。實際 audit
位於 `output/v4_ml_daily_price_overlay_impact_20260907/decimal_audit_20260520_h20_v2_corrected.json`
（832 bytes，file SHA-256
`sha256:b158b40db686e935f1131122757a440537e6585a302ef26b671e40219b7a3d6d`），
`audit_hash=sha256:00b95cc988fc4c06b85c60fd9e62b2de66f716e411f82908ca10710dd4f7a4ab`、
`rows_verified=33`。可重播命令為：

```powershell
.\.venv\Scripts\python.exe scripts\audit_ml_daily_price_overlay_impact.py --impact output\v4_ml_daily_price_overlay_impact_20260907\impact_20260520_h20_v2_corrected.json --output output\v4_ml_daily_price_overlay_impact_20260907\decimal_audit_20260520_h20_v2_corrected.json
```

### 官方 overlay 接入既有 research label pipeline（2026-09-07）

原先官方 overlay 只被 impact consumer 讀取，未能進入既有 feature／label
組裝路徑。本輪新增 `data_module/ml_daily_price_research_pipeline.py` 與
`scripts/replay_ml_daily_price_overlay_labels.py`：它只在記憶體 bounded spool
選入官方 receipt-bound entry，實際呼叫既有
`data_module.portfolio_ml_dataset_assembler._build_label_spool`，分別重播
`sqlite_original` 與 `official_response_bound_overlay` 兩個 research 情境。
決策日同日官方 OHLC／成交量只會進 corrected supervised label；feature 選擇
固定為決策日前一交易日，SQLite 沒有 intrinsic availability timestamp 時保留
`source_available_at=null`、`availability_timestamp_proven=false`，並將晚到的
官方擷取時間獨立保存為 `observed_at_utc`，不把它冒充盤前 custody。原 SQLite
保持唯讀，overlay 沒有複製回 SQLite、PIT 或 training shard，`research_only`／
`formal_training_allowed=false`。

實際 33 筆 bounded replay 已完成：
`output/v4_ml_daily_price_overlay_impact_20260907/research_label_replay_20260520_h20_v3.json`
（67,193 bytes，file SHA-256
`sha256:3f1a1432697551d18beecd82463f283b9ca033f31a889d3843d12b4e1bc09b08`，
`replay_hash=sha256:eabaf3ecc55bf9944ea72c9848d4d1697801014352d65239cd1bb86f9e98269e`）。
先前同一 scope 的 v2（62,587 bytes）保留為 immutable prior output；v3 只增加
可獨立重播的 prior-session feature values，沒有改寫 v2、overlay 或 source。
原始與 corrected pipeline 都輸出 33/33；以既有獨立 impact reference 逐
symbol／逐 8 個 label heads 比對，原始 33/33、corrected 33/33 全部吻合，
changed label heads 合計 157。3017 的原始 excess `95617bp` 與 corrected
`-1000bp` 均由 assembler label spool 重算；這是事後研究 label，不能回填
2026-05-20 決策時點、不能訓練新 fold 或 promotion。

可重跑命令（只 load／讀取官方 overlay 與 D 槽 SQLite，不重訓）：

```powershell
.\.venv\Scripts\python.exe scripts\replay_ml_daily_price_overlay_labels.py `
  --overlay output\v4_ml_daily_price_source_quality_20260907\canonical_overlay_20260520_official_v1.json `
  --sqlite D:\Min\Python\Project\FA_Data\sqlite\twstock.db `
  --reference-impact output\v4_ml_daily_price_overlay_impact_20260907\impact_20260520_h20_v2_corrected.json `
  --output output\v4_ml_daily_price_overlay_impact_20260907\research_label_replay_20260520_h20_v3.json
```

這個 research replay 的 `feature_source` 保存每一列 prior-session source date；
官方 candidate 的 `available_at` 只寫入 corrected label 的 capture observation
時間。它沒有把 33 筆修正版升格成 Formal source，也沒有改寫既有 v1／v2
impact artifact。

### source rows → assembler → teacher gate 正例 artifact（2026-09-07）

為保留可直接審核的 bounded 正例，使用一次小型隔離 fixture 執行
`test_real_source_rows_flow_through_assembler_producer_and_gate`。它實際建立
sector sidecar、Rule HMAC history 與唯讀 ledger SQLite，經
`build_teacher_source_row_provenance_for_assembly()` 讀回實體 source rows，
再交給 `evaluate_allocation_teacher_eligibility()`；結果允許研究 assembly，
但 `formal_oos_allowed=false`、`broker_order_allowed=false`。

正例摘要保存於
`output/v4_teacher_source_producer_qa_20260907_v2/source_rows_assembler_gate_positive.v2.json`
（17,824 bytes，file SHA-256
`sha256:f1b6d36fabe8bade2d75f3228a7807ca944068d57df609b40e4bafe321f22fca`）。
artifact 明確標示 `source_nature=synthetic_test_fixture`、
`formal_source=false`、`production_formal_custody=false`；它是合成 fixture 的
assembler→producer→gate QA，不是 Direct/Formal production custody。其中三個
source 的 readback／manifest 位於 storage key
`sha256:5b63d5d2c6244e27e64997f9e1ba4ca66c02a5e7cf1e13d422ebb91b9f7f6e15`，
`source_availability_proven=true`、gate `allowed=true`，每個 source 都有一筆
實體 readback row。此 artifact 是 bounded QA fixture 證據，不是 Direct parent
的 production custody；Direct 缺正式三來源時仍維持 blocked。

可重跑命令（只寫 repo output，不碰 D）：

```powershell
$env:TEACHER_SOURCE_QA_OUTPUT_ROOT = "C:\Projects\PythonProjects\technical_analysis\output\v4_teacher_source_producer_qa_20260907_v2"
.\.venv\Scripts\python.exe -m pytest tests\test_teacher_input_source_producer.py::test_real_source_rows_flow_through_assembler_producer_and_gate -q -o addopts=
```

### bounded ResearchShadowUnion v2 與公開 readback（2026-09-07）

前一個 bounded 建置在 session `18023` 以 Ctrl+C 結束，exit code=1；失敗目錄
`output/v4_ml_research_shadow_union_bounded_20260907` 保留作診斷證據，不視為已發布。
當時曾觀測到該目錄 `.tmp/assembly.sqlite` 約 `1,790,472,192` bytes，超過本輪
1 GiB 暫存上限；事後以精確程序查詢沒有同名 live process。沒有刪除這個失敗目錄，
也沒有以它作為成功容量證據。

受控重跑使用 session `16521`，只處理預先指定的 33 symbols、`years=(2025, 2026)`、
`minimum_train_dates=20`、`test_date_count=10`、purge=60、embargo=5，沒有重建全歷史
Direct 或訓練模型。D 槽 SQLite 以唯讀 snapshot 讀取；snapshot bytes 為
`71,364,608`，source identity 為
`sha256:3a4eb60118ffb51e3d4de3b57f1e1071ea5075ad27b1b2e4f333b8cee9a4fc32`，
snapshot file hash 為
`sha256:46c09cae38dd56d1182d53ce20a9e52e9d0cd6b0a3d1e54a7d735d93b9ca26b7`。
`fundamental_statement_items` 因 D 沒有明確 `report_basis` 而 fail-closed 排除，沒有猜測
或改寫來源。

v2 實際發布摘要為
`output/v4_ml_research_shadow_union_bounded_20260907_v2/bounded_run_summary.json`，
其中 PIT publication `pit-7ddb13a798ef5da35edfa323`、row count 252,484、6 shards；
PIT observed temporary peak `102,050,080` bytes。Assembler base publication
`portfolio-ml-a23201d6dd968afc49a67537` 有 7,836 samples／18 folds，實際 callback
observed temporary peak `411,557,888` bytes。Union publication
`research-union-8521935985bcf1c60a1a049b` 有 7,836 samples，最後 C 槽 bounded output
directory bytes 為 `276,071,889`，新增持久上限與暫存上限各 `1,073,741,824` bytes，
reserve `214,748,364,800` bytes；成功時沒有殘留 TEMP。summary 內的 source、PIT、base、
Union manifest hash 與 D read-only／research-only／alpha=0 狀態均保留。

為讓既有 public readback 直接消費這個 v2 PIT，另外以 shared immutable store 發布兩個
既有 gzip shard；沒有重開 D SQLite。shared PIT manifest 為
`output/v4_ml_research_shadow_union_bounded_20260907_v2/shared_pit_publication/runs/pit-shared-4392435e587e2b895e07f5fe/manifest.json`，
manifest hash `sha256:1be8c03238acdcc5dd4bc9b7010f4e435c54b53e41aee6cfcc19f9a625b8c6dd`，
shared store 新增 `33,897,821` bytes。該發佈使用 immutable store 自己解析出的
canonical lock；API 會拒絕把外部 D heavy lock 冒充 store canonical lock，故沒有繞過
鎖或另建替代 lock。所有 shared object 仍以語意 key、compressed/content SHA 與
`raw_observed_only.v1` 綁定。
加入 shared publication、readback 與 coverage QA 後，v2 bounded root 目前實際
directory bytes 為 `311,128,086`，仍沒有殘留 TEMP；其中原 bounded chain 的
`276,071,889` bytes 與 shared/readback QA 的新增內容分開保存。本輪新增的
final overlay／frozen inference readback 是另存的 QA evidence，沒有改寫原有
immutable PIT、base、Union、shared object 或 release artifact。

shared PIT 的實際唯讀發布命令為：

```powershell
.\.venv\Scripts\python.exe scripts\build_ml_pit_shared_block_publication.py `
  --dataset-manifest output\v4_ml_research_shadow_union_bounded_20260907_v2\pit\runs\pit-7ddb13a798ef5da35edfa323\all_field_enriched\manifest.json `
  --shared-store output\v4_ml_research_shadow_union_bounded_20260907_v2\shared_pit_store `
  --output-dir output\v4_ml_research_shadow_union_bounded_20260907_v2\shared_pit_publication `
  --max-store-bytes 268435456 `
  --maturity-policy raw_observed_only.v1 `
  --lane research_shadow
```

公開唯讀 readback 命令為：

```powershell
.\.venv\Scripts\python.exe scripts\build_ml_research_shadow_overlay_direct_readback.py `
  --overlay output\v4_ml_daily_price_source_quality_20260907\canonical_overlay_20260520_official_v1.json `
  --label-replay output\v4_ml_daily_price_overlay_impact_20260907\research_label_replay_20260520_h20_v3.json `
  --research-union-manifest output\v4_ml_research_shadow_union_bounded_20260907_v2\union\runs\research-union-8521935985bcf1c60a1a049b\manifest.json `
  --pit-manifest output\v4_ml_research_shadow_union_bounded_20260907_v2\shared_pit_publication\runs\pit-shared-4392435e587e2b895e07f5fe\manifest.json `
  --pit-shared-store output\v4_ml_research_shadow_union_bounded_20260907_v2\shared_pit_store `
  --direct-manifest output\v4_ml_direct_shared_consumer_20260907_bounded\runs\direct-ooc-415dba364b4dacbe583b9284\manifest.json `
  --output output\v4_ml_research_shadow_union_bounded_20260907_v2\qa\overlay_readback_20260520_v3.json
```

實際 readback 為
`output/v4_ml_research_shadow_union_bounded_20260907_v2/qa/overlay_readback_20260520_v3.json`，
136,600 bytes，file SHA-256
`sha256:9d22b05fe9202a3737b83dac1d49ed46941780fbdd255adb8c29193d3dc7d031`，
`integration_hash=sha256:0bf81806c601cbf2622eb5ae934022138f20cd2302769d76e11645d5f498089e`。
官方 overlay／label replay 仍是 33 筆；shared PIT 找到 33 symbols、99 observation
rows，但在 `2026-05-20T08:30:00+08:00` 前可得 rows 為 0；Direct 既有 11-symbol
numeric scope 只匹配 `2454` 1 筆。所有旗標保持 `research_only=true`、
`formal_training_allowed=false`、`formal_oos_allowed=false`、`promotion_eligible=false`、
`production_alpha_bp=0`。

Union 的 2026-05-20 sample 實際只有 9 symbols：`2059, 2364, 2383, 3017, 3535,
3661, 6139, 8033, 8996`。其餘 24 symbols 並非被 readback 補成 33/33；每一筆都在
2026-05-20 至 2026-08-13 的 60-trading-day supervised horizon 內有官方
`ex_right_dividend_result` result-only event，assembler 會排除受影響 horizon，且
`_labels_for_decision` 要求完整四 horizon 才輸出 sample，因此沒有 Union sample row。
逐 symbol 的 event type、effective／available time、source id 及 Union/readback hash
保存在
`output/v4_ml_research_shadow_union_bounded_20260907_v2/qa/union_coverage_20260520_v2.json`
（11,680 bytes，file SHA-256
`sha256:6f690ba0806332ac33bff7b70c5add0585c0d18e1592ebcb37d716fa13aa8d38`）。這是成熟度／
corporate-action exclusion 的 coverage diagnosis，不是原始 daily price 缺失證明，也
不能宣稱 33/33 已接通或形成正式 PIT。

本片定向驗證：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ml_research_shadow_union_bounded.py tests\test_ml_research_shadow_overlay_integration.py::test_bounded_union_nested_sample_records_are_counted_by_public_readback -q -o addopts=
```

結果為 `6 passed`（僅 pytest cache 無寫入權限 warning）。其中 growth case 使用獨立
TEMP，先通過 schema 與首個 raw batch，再由實際 `_capacity_checkpoint` 在 256 KiB
temporary budget 後因 spool 增長停止並清理；nested sample regression 則證明公開
readback 會讀 v2 envelope 內實際 row，得到 9/33 coverage。原 v2 bounded artifact、
shared PIT、readback 與 coverage diagnosis 均為 research evidence，不提高 alpha、不讀
新 fold、不重訓、不改 D 原始資料。

## 最終獨立驗證與 frozen inference readback（2026-09-07）

本節只重用既有 v2 publication、shared PIT object、官方 overlay、label replay、Direct
numeric row 與既有 frozen v3 release；沒有重跑 immutable block、PIT publication、官方
價格 overlay、bounded union、live fit 或 D 槽 writer。

### 33 檔 coverage 與事件排除

公開 readback 另存於
`output/v4_ml_research_shadow_union_bounded_20260907_v2/qa/overlay_readback_20260520_final_v4.json`，
大小 `136,600` bytes，file SHA-256 為
`sha256:9d22b05fe9202a3737b83dac1d49ed46941780fbdd255adb8c29193d3dc7d031`，
`integration_hash` 為
`sha256:0bf81806c601cbf2622eb5ae934022138f20cd2302769d76e11645d5f498089e`。
獨立重新核對結果如下：

| 層次 | 結果 | 可宣稱範圍 |
| --- | --- | --- |
| 官方價格 overlay | `33/33` | 33 檔 corrected price overlay 已讀回；capture 晚於歷史 cutoff，`historical_decision_time_available=false` |
| PIT publication | `33 symbols / 99 rows` | 99 rows 可被 hash-bound 讀回，但 `available_at <= 2026-05-20T08:30:00+08:00` 為 `0`，不能當歷史決策 feature |
| ResearchShadowUnion | `9/33` | 可用 sample 為 `2059, 2364, 2383, 3017, 3535, 3661, 6139, 8033, 8996` |
| Direct numeric | `1/33` | 只有 `2454` 與 33 檔 overlay 的決策 row 交集；不代表 Union sample eligibility |

其餘 24 檔為
`1514, 1519, 2308, 2345, 2360, 2368, 2404, 2449, 2454, 2467, 2486, 2603,`
`3037, 3167, 3443, 3533, 3583, 3653, 6196, 6442, 6531, 8021, 8046, 8210`。
逐檔 coverage／reason 保存在
`output/v4_ml_research_shadow_union_bounded_20260907_v2/qa/union_coverage_20260520_v2.json`；
該檔為 `11,680` bytes，file SHA-256 為
`sha256:6f690ba0806332ac33bff7b70c5add0585c0d18e1592ebcb37d716fa13aa8d38`。
獨立掃描確認 24/24 都是 `event_type=ex_right_dividend_result`、
`result_only=true`、`formal_label_ledger_allowed=true`，effective date 落在宣告的
`2026-05-20..2026-08-13` 60-trading-day exclusion interval 內（實際事件日期範圍
`2026-05-24..2026-08-04`），沒有事件型態或 symbol set 差異。

這條規則是合理且保守的 label-integrity policy：
`_build_label_spool` 只將事件命中的 horizon 寫入
`corporate_action_effective_within_label_horizon` exclusion，
`_labels_for_decision` 只有在 5／10／20／60 四個 horizon 全部存在時才回傳 symbol。
因此一個事件命中任一 horizon 會移除完整四-horizon sample tuple，並非宣稱原始價格
row 不存在。程式與 manifest 同時證明 post-event corporate action 沒有作為 decision
feature；這是研究資料的保守排除，不是歷史可交易性、正式 OOS 或投資有效性證據。

### frozen inference 最終 readback

既有 release `v3-linear-h5-67e0b583037dda60` 以 content-addressed frozen input bundle
由公開 audit CLI 重播；新摘要另存為
`output/v4_ml_research_shadow_union_bounded_20260907_v2/qa/frozen_inference_audit_final_v4.json`，
大小 `2,612` bytes，file SHA-256 為
`sha256:4fb68c157acaa9f45e59d2daf7c2076f14991b16390eafdce2da8de0390091cd`。
狀態為 `independent_v3_release_audit_passed`，實際 inference `11 rows / 33 experts`，
`inference_readback_mode=post_freeze_research_shadow`、
`inference_readback_status=verified_after_publish`。

完整 frozen readback 為
`output/v4_ml_research_shadow_union_bounded_20260907_v2/qa/frozen_inference_readback_final_v4.json`，
大小 `24,965` bytes，file SHA-256 為
`sha256:503bdcffa0e2f7158cf44c7f158df55a3c43db864c2446b11172ea651f6e5af0`；
`inference_audit_hash` 為
`sha256:7e3070540453aabc9e7a69d0c1a32fdc1d925e7965c1faa8bdc33c41b9c6adc2`。
readback 顯示所有 formal／production／broker 權限仍為 false、alpha 為 `0`；其
`target_summary.status=degenerate_constant_targets_adapter_neutral`，meta targets
全部為常數（cash `10000bp`，其他配置 target `0bp`），所以本次完成的是 frozen
consumer wiring/readback，不是 model investment efficacy evaluation。

### 獨立 hash、容量與清理盤點

- bounded summary 的 `summary_hash` 可由內容重算一致；PIT、base、Union、shared PIT
  四個 publication manifest 的 canonical `manifest_hash` 也全部重算一致，latest
  pointers 與 publication identity 對上。v2 原 chain 的 `337` 個 capacity preflight
  全部 `within_budget=true`；最高 persistent projection `683,670,938` bytes、最高
  temporary observed `411,557,888` bytes，低於各 `1,073,741,824` bytes 上限。
- 為防止下一輪再出現舊 over-capacity 行為，assembler 現在會在 raw／label SQLite
  batch callback 前先 commit，讓 callback 量到實際 spool bytes；bounded wrapper 會在
  最後 `bounded_run_summary.json` atomic write 前做精確 encoded-size projection，並在
  寫後再 checkpoint。這是未來執行的 guard hardening；v2 immutable chain 沒有因本 patch
  重建。
- 舊失敗目錄 `output/v4_ml_research_shadow_union_bounded_20260907` 保留作診斷：目前
  `2,397,262,965` bytes，其中精確的 `.tmp/…/assembly.sqlite` 為 `1,790,472,192`
  bytes。這只是 owner review／後續受控 cleanup 候選，本輪沒有刪除；v2 root 目前
  `311,128,086` bytes，`.tmp` file count 為 `0`。建議未來依 cleanup manifest、依賴
  closure、rollback／tombstone 與 owner confirmation 逐項處理，不能直接以 glob 刪除。

本節的程式回歸為：

```text
pytest tests/test_ml_research_shadow_union_bounded.py tests/test_portfolio_ml_dataset_assembler.py tests/test_ml_storage_capacity.py -q -o addopts= --disable-warnings
63 passed, 1 skipped

pytest tests/test_ml_research_shadow_overlay_integration.py tests/test_infer_ml_allocation_copilot_cli.py tests/test_audit_ml_allocation_v3_linear_release.py tests/test_allocation_release_adapter.py tests/test_ml_research_shadow_union_bounded.py tests/test_ml_storage_capacity.py -q -o addopts= --disable-warnings
50 passed, 1 skipped

mypy --explicit-package-bases data_module/portfolio_ml_dataset_assembler.py data_module/ml_research_shadow_union_bounded.py data_module/ml_storage_capacity.py
Success: no issues found in 3 source files

pytest <Task 2 staged test closure> -q -o addopts=
407 passed, 1 skipped
```

所有結果仍屬 research／shadow；官方 overlay 的事後 capture、PIT 歷史可得性 `0`、24
檔 label exclusion、Direct target degeneracy 與 formal input `0/3` 都不能被轉寫成
正式通過或投資績效。
