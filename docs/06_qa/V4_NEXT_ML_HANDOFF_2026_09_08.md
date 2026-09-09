# V4 Next ML／Effectiveness handoff — 2026-09-08

本輪 ML owner 的第一個可重現缺陷是前瞻輸入與自然有效性 clock 沒有形成同一條可驗證鏈：舊 derived CLI 不接受 scheduled caller 傳入的 deadline／operational file hash，orchestration 只記錄 start capture，collector 在 inference 後仍可能跨 08:35 append；另外 archive readback 第二次讀 publication 時沒有以 raw bytes hash 綁定回傳 rows。這些缺口已各自補上並有正負測試。現有 2026-09-07 盤後 shadow 仍是研究證據，不能改算 forward credit，也沒有重讀 fold006+ 或啟動 heavy fit。

## Ownership

本輪實作及驗證範圍如下：

- `ml_module/pit_archive_consumer.py`：受控 Formal `pit_candidate_archive` 的 ML consumer adapter；只接受 caller 指定的 exact manifest、archive root 與 frozen manifest file hash。
- `data_module/portfolio_ml_dataset_assembler.py`、`scripts/build_ml_allocation_post_freeze_shadow_input.py`：把已完成 custody readback 的 archive rows 以 memory spool 接到 post-freeze input；archive 與 operational branch 互斥，不複製或改寫 Formal archive。
- `scripts/run_daily_ml_allocation_orchestration.py`、`scripts/run_daily_ml_allocation_derived_shadow.py`：傳遞 archive／operational source、實際驗 operational bytes hash、嚴格驗 deadline 等於 `decision_at + 5 分鐘`，並保留完整 outer status。
- `app_module/ml_allocation_shadow_evidence.py`：在 post-inference、collector append 前及 SQLite INSERT 後檢查真實 emission clock；逾時 transaction rollback，不留下 observation 或日 credit。
- `data_module/ml_daily_price_source_quality.py`、`data_module/ml_pit_year_shard_exporter.py`、`scripts/build_ml_pit_year_shards.py`、`scripts/audit_ml_daily_price_source_quality.py`、`scripts/scheduled/run_ml_raw_pit_refresh.py`：明示 TWSE/TPEX source roots、以 Decimal 語義比對、拒絕跨市場 duplicate、以 bounded route/CSV cache 執行 source-quality guard；scheduled trigger 仍由 Ops 管理，ML wrapper 定義雙 root argv contract。
- `data_module/ml_price_availability_contract.py`、`data_module/portfolio_ml_dataset_assembler.py`、`ml_module/historical_feature_builder.py`、`ml_module/historical_label_builder.py`、`scripts/train_ml_allocation_copilot.py`：把 shard 內的 `price_unavailable` contract 綁到 bounded assembler／feature／label consumer；source-quality 研究豁免不會升級為 formal training input。
- `ml_module/model_lifecycle_registry.py`、`ml_module/shadow_monitoring_service.py`：以既有 lifecycle registry 的單一交易寫入 drift decision／rollback evidence pair，支援 crash rollback、精確 prefix recovery、重跑冪等及矛盾 suffix 拒絕。
- `ml_module/natural_shadow_pruning_evidence.py`、`scripts/inspect_ml_natural_shadow_pruning_evidence.py`：以既有 shadow sidecar 建立 bounded evidence-only natural maturity／pruning projection；不建立第二 registry、不執行 pruning 或 promotion。
- `output/v4_next_ml/official_sources/twse_20260908/`：保存 6949 的 TWSE raw response、HTTP metadata、SHA 與 versioned receipt，僅作隔離 source-quality candidate。
- source manifest schema／custody 的窄修補與 ML 專屬測試亦在本 owner 範圍。

排程 `scripts/scheduled/` 的 trigger／config 產生器仍由 Ops owner 管理；Formal archive writer 與 Paper consumer 不在本輪改動範圍。

## 本輪 ML integration QA（2026-09-08）

以本輪 owned source 的 explicit pytest 清單執行 exporter → assembler → feature／label → training／inference → shadow／lifecycle → archive／natural consumer 的定向回歸；命令完整輸出在
`output/v4_next_ml/ml_integration_targeted_suite_20260908.log`；完整 explicit file 命令保存在
`output/v4_next_ml/ml_integration_targeted_suite_20260908.command.txt`。結果為 **429 passed、1 skipped、2 warnings**。
skip 是 `test_ml_storage_capacity.py` 的 Windows junction／symlink fixture 無法建立，並非功能失敗；warnings 為 loky physical-core 探測與既有 pytest cache 權限。

另以 `tests/test_ml_forward_scheduled_wrapper.py`、`tests/test_ml_allocation_forward_child_contract.py`、
`tests/test_ml_forward_task_registration_plan.py`、`tests/test_scheduled_ml_raw_pit_refresh.py`、
`tests/test_scheduled_ml_direct_chain_maintenance.py`、`tests/test_scheduled_forward_calendar_refresh.py`
做跨 owner daily boundary 回歸，結果為 **60 passed、1 pytest cache warning**，log 在
`output/v4_next_ml/ml_forward_cross_owner_suite_20260908.log`，完整命令保存在
`output/v4_next_ml/ml_forward_cross_owner_suite_20260908.command.txt`。

owned source 的 explicit-package-bases mypy 為 **28 files、0 errors**，命令輸出在
`output/v4_next_ml/ml_owned_sources_mypy_20260908_v2.log`；同一 28 files 的 `py_compile` 為 exit 0，輸出在
`output/v4_next_ml/ml_owned_sources_pycompile_20260908_v2.log`。`git diff --check` 對 owned tracked files 無 whitespace error。

跨模組檢查確認：source-quality 的 Decimal／雙市場路由結果可被 exporter 與 assembler 消費；`price_unavailable` 研究列不會升級成 formal training source；feature／label 缺價 gap 不 bridging；inference／shadow identity 與 emission deadline contract 維持；natural consumer 只保留 pending，沒有成熟 effectiveness、pruning 或 promotion evidence。

## 已驗證的 durable archive

Root 的 current-code 正向 readback 為 [ml_archive_actual_readback.json](../../output/v4_next_root/ml_archive_actual_readback.json)。目前可重用的受控 archive 是：

```text
archive_root = C:\Projects\PythonProjects\technical_analysis\output\formal_daily_publications\pit_candidate_archive
manifest = C:\Projects\PythonProjects\technical_analysis\output\formal_daily_publications\pit_candidate_archive\2026-09-08\85f71a355f707404-284d54b9ccedbfea\archive_manifest.json
manifest_file_hash = sha256:c2b838d9d79b794bc13b934c83f5f36f18c1b5828dead20ded9112de6745178f
```

這份 archive 為 1,984 rows，`current_code_hash_match=true`、`source_custody_verified=true`、`rows_rebuilt_from_raw=true`、`candidate_only=true`。`captured_at=2026-09-08T10:28:09.898861Z`、`archived_at=2026-09-08T10:34:49.359908Z`，已晚於 2026-09-08 台北 08:30，因此不授予 9/8 forward credit；它可在 9/9 decision 前以同一 frozen manifest 供自然 shadow 使用。原 TEMP candidate 消失後，adapter 仍能從固定 archive root bounded readback。

Adapter 的檢查包括：manifest exact path／root containment、junction／reparse rejection、frozen manifest bytes hash、archive `available_at`／`archived_at` 不得晚於目標 decision、current producer／publisher code hash、receipt／operational／publication raw file hash 與內容 hash、HMAC／source identity，以及 archive rows 重建。publication 第二次讀取若被替換但保留宣告 content hash，會因 raw file hash 不符而拒絕；這是本輪 TOCTOU 回歸。

## Ops 可直接採用的 ML argv contract

下一個自然日（例如 2026-09-09）使用已驗收的 V4 rank-v2 frozen release；不可改用同名但仍是 ordinal-symbol-tiebreak 的 V1 目錄：

```text
release_root = C:\Projects\PythonProjects\technical_analysis\output\v4_ml_derived_h5_20260907_real_v2
release_manifest_file_hash = sha256:c306c1ea53ccef112204a8412a605b575e4d107b4503b2b5be5d6d5ee50910ea
training_manifest_v2_file_hash = sha256:8a765c682c6c838befad12701c396de975a70aedc669a090d033f009c5e42409
training_manifest_hash = sha256:c2b295b63e9a08d27920922197a72b6331111f8bf4ac8e1524731480481ea9a7
model_id = baldr-ml-allocation-derived-h5-v4-rank-v2
model_artifact_hash = sha256:aa152ebb8e8d7913a6a2274a0526620d8b8ce151a5f667d8de446df9724c895c
dataset_identity_hash = sha256:3fba3292db228577f91fb652d74d4bcfbed124e98e4fb8e48de92eb9554209f8
release_identity_hash = sha256:2a4a149076b69f9ad48f056821e696ad0c3cfc7cebbd5b655f7ce9d37ff83613
rank_contract = allocation-rank-v2:dense_value_tiebreak
```

上述 `release_manifest_file_hash` 的十六進位字串中間不含空白，完整值為 `sha256:c306c1ea53ccef112204a8412a605b575e4d107b4503b2b5be5d6d5ee50910ea`。

```text
\.venv\Scripts\python.exe scripts\run_daily_ml_allocation_derived_shadow.py --mode forward_natural_date --decision-at 2026-09-09T08:30:00+08:00 --natural-forward-deadline-at 2026-09-09T08:35:00+08:00 --database D:\Min\Python\Project\FA_Data\sqlite\twstock.db --paper-state-db C:\Projects\PythonProjects\technical_analysis\output\paper_execution_eod_replay\paper_portfolio\paper_portfolio.sqlite --output-root C:\Projects\PythonProjects\technical_analysis\output\v4_ml_daily_derived_shadow_real_v2 --release-root C:\Projects\PythonProjects\technical_analysis\output\v4_ml_derived_h5_20260907_real_v2 --pit-machine-archive-root C:\Projects\PythonProjects\technical_analysis\output\formal_daily_publications\pit_candidate_archive --pit-machine-archive-manifest C:\Projects\PythonProjects\technical_analysis\output\formal_daily_publications\pit_candidate_archive\2026-09-08\85f71a355f707404-284d54b9ccedbfea\archive_manifest.json --pit-machine-archive-manifest-file-hash sha256:c2b838d9d79b794bc13b934c83f5f36f18c1b5828dead20ded9112de6745178f --lock-path D:\Min\Python\Project\FA_Data\output\release_v4\.ml_heavy_chain.lock
```

Operational source 是另一個互斥 branch；它必須同時傳 `--pit-machine-operational-publication <exact path>` 與 `--pit-machine-operational-publication-file-hash sha256:<64 hex>`。orchestration 會對實際 bytes 重算並比對，forward operational source 沒有 frozen hash 會 fail closed。archive branch 不得同時傳 operational path；archive branch 也不得只傳 root 或依檔名自動選 latest。

`--natural-forward-deadline-at` 可省略時由 derived 固定計算 decision 後 5 分鐘，但 scheduled wrapper 若傳入，值必須完全相同；這個 deadline 是 observation emission／append 的完成上限，不是以 start time 借用 credit。完整 derived stdout 保留 outer wrapper status；`daily_orchestration.natural_forward_completion_clock` 位於 nested payload，完成 record 亦保存同一 clock。Ops 必須以 outer status 判斷，inner completed 遇到 outer capacity／read-only block 仍應 exit non-zero。

目前 05:20 Pacific 的 `baldr-ml-allocation-copilot-daily` 是盤後 catch-up，不能作 forward caller。合法 prepared caller 由 `scripts/scheduled/run_ml_allocation_forward_daily.py` 在真實 Asia/Taipei 08:30 等鐘；Pacific 16:15 wake 在 PDT 是台北隔日 07:15、在 PST 是 08:15。它的 config 以 `load_schedule_config(... expected_run_date=local_now.date())` 綁定自然日，故 Ops 必須每天以 create-only 方式產生含當日 `run_date` 與台北 08:35 deadline 的新 config；不可沿用固定 2026-09-08 config，也不可原地改寫既有 config。config 的 `source` 仍只能選 operational 或 archive 一支。

## 雙市場 source quality 與 6949 隔離 candidate

ML raw source guard 現在要求 production caller 明示兩個 canonical roots，並以 symbol 路由：

```text
--daily-price-source-dir D:\Min\Python\Project\FA_Data\daily_price
--daily-price-source-dir D:\Min\Python\Project\FA_Data\daily_price_tpex
```

`daily_price` 固定標為 TWSE、`daily_price_tpex` 固定標為 TPEX；同一 symbol 只在一個 root 出現才選取。兩 root 同值重複列為 `ambiguous`、數值不同列為 `conflict`，兩者都 quarantine，不能以目錄順序覆蓋。價格用 Decimal 值比較，`990.0` 與 `990.00` 相等，但真正價差仍拒絕；每個 selected row 保存 source path、market 與 file SHA。Root 的 2026-09-07 全市場雙 root 唯一路由 read-only 結果為 1,970 rows（TWSE 1,095、TPEX 875、missing／ambiguous／conflict 均 0），證據在 [raw_quality_dual_market_full_day.json](../../output/v4_next_root/raw_quality_dual_market_full_day.json)。

source guard 的 full-history 邊界是 `candidate_sample_limit=64`：`candidate_count`、`classification_counts`、`affected_date_counts` 和長度框架的 `candidate_digest` 累計全量，report 只保留 64 個 evidence samples，並列 `candidate_sample_count` 與 `candidate_samples_truncated`。digest 綁定每一列的日期、代號、分類、detector 關鍵值、SQLite/canonical 關鍵原值、context 與 source file identity，因此 sample limit 不會改變候選集合身份。route cache 最多 8 個日期，兩市場 CSV cache 最多 16 個 date/root entries；不把 4.4m 候選列寫成完整 JSON，也不讓候選列表無界留在記憶體。bounded 回歸包含 sample-limit、digest、同日 route reuse 與 >8-date cache eviction。

全歷史 read-only 分類已啟動，精確命令如下；它只開 SQLite `mode=ro`／`query_only`、使用 `ingest_guard`（不讀 next row）、不建立 PIT publication：

```text
\.venv\Scripts\python.exe scripts\audit_ml_daily_price_source_quality.py --sqlite D:\Min\Python\Project\FA_Data\sqlite\twstock.db --daily-price-dir D:\Min\Python\Project\FA_Data\daily_price --daily-price-dir D:\Min\Python\Project\FA_Data\daily_price_tpex --start-date 2014-01-01 --end-date 2026-09-07 --quality-mode ingest_guard --candidate-sample-limit 64 --output output\v4_next_ml\raw_quality_full_history_ingest_guard_20260908.json --pretty
```

程序於 `2026-09-08T12:52:36.1602195Z` 啟動，於 `2026-09-08T12:56:09.2565722Z` 結束，exit code 為 2（只表示 source gate 有 quarantine candidate）。log 為 [raw_quality_full_history_ingest_guard_20260908.log](../../output/v4_next_ml/raw_quality_full_history_ingest_guard_20260908.log)，報告為 [raw_quality_full_history_ingest_guard_20260908.json](../../output/v4_next_ml/raw_quality_full_history_ingest_guard_20260908.json)，report SHA 為 `sha256:2405da2dc4d34f284494fc2b05feec22c318b154139b1df1d6bf44644c950660`。2014-01-01 至 2026-09-07 的 SQLite scope 有 5,295,781 rows；全量候選 17,830，保留 sample 64，`candidate_digest=sha256:1065040e9faa677fed4c64963b6ddd61d86c4d7050c9deb3ba4950519ebcd276`。分類為 invalid 16,892、CSV mismatch 827、canonical row missing 55、both-sources one-sided scale 33、canonical one-sided scale 23；route selected 5,278,839、missing 16,942、ambiguous/conflict 0。這些數字是 9/7 cutoff 的新 read-only scope，不能與舊 9/8 run 的 4,476,508 candidate 直接計算修復率。process 觀測到約 127.8 MB working set、約 603 MB private bytes；這是該次 bounded read-only run 的觀測，不宣稱硬性上限。此程序不使用 200 GiB reserve 以外的重型 chain，不持有 Raw publish lock，也不讀 fold006+。

同一 bounded source route 仍發現 6949 在 2026-09-07 的一側尺度斷裂，不能 blanket 放行。隔離證據為 [raw_quality_6949_source_evidence_20260908.json](../../output/v4_next_ml/raw_quality_6949_source_evidence_20260908.json)，其 previous close `1490.0`（2026-08-26）與 current open `81.9`（2026-09-07）在 SQLite／TWSE CSV 逐值相等，故問題不是 DB/CSV mismatch。TWSE 官方 TWTB7U raw response 明示 6949 於 2026-08-27 停止、2026-09-07 恢復，面額由 `10.00` 變更為 `0.50`，換股率 `20.00000000`；官方 2026-09-07 MI_INDEX raw response 亦保存當日 6949 的 volume `24,486,488`、open `81.90`、close `67.10`。raw bytes、HTTP metadata、SHA 與 receipt 在 [official_sources/twse_20260908](../../output/v4_next_ml/official_sources/twse_20260908)；隔離 candidate 是 [raw_quality_6949_official_action_candidate_20260908.json](../../output/v4_next_ml/raw_quality_6949_official_action_candidate_20260908.json)（SHA `sha256:d98416129df084412d4c3e0033cc8cc6854b10c92964d7c9cbdf9539c0224724`）。

官方換股率可解釋該尺度斷裂，但不等於觀測價格比 `1490.0 / 81.9 = 18.192918...`；這個比值不能反推或自動修正 corporate action。receipt 的 `receipt_available_at=2026-09-08T12:54:46.3715768Z` 是本次 custody 完成時間，`source_available_at` 保持 unknown，不能把事後取得時間回填成 2026-09-07 decision 前可得。6949 維持 `quarantine_required`、`adjustment_authorized=false`、`historical_pit_rewrite_allowed=false`、`formal_training_allowed=false`、`forward_credit_allowed=false`；只有在新版本化 source contract 綁定官方 receipt、unit semantics 及適用 cutoff 後，才能產生隔離 research candidate 供新 contract 驗證。

## `price_unavailable` contract 的 shard→feature／label 消費

source-quality report 的 candidate count 仍是全量 gate；只有 SQLite 與 canonical CSV 四個 OHLC 欄位都明確不可用、每欄 raw 值一致，才可將該列保留為 `research_only`。literal `--`、空值與正 volume 都不能推斷停牌原因；負值、NaN、亂碼、部分 canonical mismatch、雙市場歧義與尺度跳動維持 quarantine。Root 的實際正向 probe [raw_matching_missing_positive_probe.json](../../output/v4_next_root/raw_matching_missing_positive_probe.json) 已驗 sample limit=0 下 candidate 仍完整計數、matching missing 可進研究豁免、TEMP 清理完成；這不授予 formal 或 forward credit。

`data_module/ml_price_availability_contract.py` 的 v1 payload 保存 symbol、日期、原始 row、逐欄 `missing_mask`、`available_at`（未知時保持 unknown）、feature／label 受影響日期與分開的 `feature_window_complete`／`label_window_complete`。`historical_feature_builder` 對不完整 OHLC row 將整列視為 gap，清除價格／成交量衍生值，所有涉及 gap 的 return、MA、波動與 volume window 回傳 missing；`historical_label_builder` 同時消費序列化 contract 與自動從缺價 row 建立的 contract，label window 觸及 gap 即排除，不把前後交易日壓縮成相鄰日。

`ml_pit_year_shard_exporter` 將 contract 寫入 daily-price raw observation；`portfolio_ml_dataset_assembler` 逐行驗證 contract 的 symbol／日期與內容 hash，使用只保留目前 symbol 的 gap lookup，並把 contract schema、gap count、digest 寫入 training header／manifest。label spool 對 benchmark 與 stock 的每個 horizon path 都要求四價完整且不得命中 gap；partial row 因此不會沿用 open／close 產生 outcome。raw dataset 的 `source_quality.research_only=true` 或 `formal_training_allowed=false` 會在 assembler 入口拒絕，不能藉 child dataset manifest 改寫用途；training loader 接受 provenance 欄位但同樣對 research-only source fail closed。

真 shard→assembler→feature／label bounded regression 是 synthetic raw shard（2330 在 2024-01-10 缺 high）：shard 內 contract 可讀，assembler manifest `gap_count=1`，2024-01-06 至 2024-01-10 的 5/10/20/60 日 label sample 不產生；2024-01-11 的 T-1 feature 保留 `daily_prices.最高價` missing，四個成熟 label 仍可讀。測試 log 為 [ml_shard_feature_label_e2e_20260908.log](../../output/v4_next_ml/ml_shard_feature_label_e2e_20260908.log)，1 passed（僅 pytest cache permission warning）。

## 自然 shadow 與有效性判斷

現有真實輸入狀態在 [latest_status.json](../../output/v4_ml_daily_derived_shadow_real_v2/scheduled/ml_allocation_copilot/latest_status.json)：2026-09-07 decision 時 capture 為 17:22 台北，release 首次可見晚於 decision，`fallback_reason=feature_pack_missing_or_partial_missing_mask`，coverage 8,504 bp、`selected_alpha_bp=0`、matured 0、`shadow_day_credit_allowed=false`。這是盤後研究 observation，不是新的自然前瞻 credit。

77 個缺值是 2026-09-07 舊 run 的 11 rows，仍保留作歷史研究證據：

- `industry_indices.收盤指數`、`industry_indices.漲跌百分比`、`industry_indices.漲跌點數`：33 個。Root 最新隔離 post-freeze TWSE 11-symbol readback 已驗 33/33 observed；這三欄不再列為當前 source blocker。
- `market_indices.漲跌百分比`、`market_indices.漲跌點數`：22 個。這兩欄在舊 input 以及 2026-09-08 D bounded read-only probe 仍為 NULL，但同日／前一交易日 TAIEX `收盤指數` 都可取得；可用既有 `market-index-change-derivation.v1` 產生 candidate，`available_at` 取兩個 close 的較晚可見時間，不能寫回 SQLite 或舊 PIT。
- `technical_indicators.涨跌`、`technical_indicators.漲跌(+/-)`：22 個。2026-09-08 D bounded read-only probe 仍為 NULL，而 `technical_indicators.漲跌價差` 與 `daily_prices.漲跌(+/-)` 已有來源值；兩欄是方向／legacy 欄，沒有合法 numeric mapping，必須在下一個 feature contract 排除，不能以價差、符號或 0 填補。

四欄語義與真實來源證據見 [ml_feature_gap_diagnostic_20260908.json](../../output/v4_next_ml/ml_feature_gap_diagnostic_20260908.json)。診斷只查 2026-09-07／08 TAIEX 與 11 個 symbol，SQLite 以 read-only URI 開啟，並明確記錄 `sqlite_source_write=false`、`zero_fill=false`、`historical_backfill=false`。這個 candidate diagnosis 不改現行 V2 release；市場 derived values 要到明確支援該 contract 的新 release 才能消費，technical legacy 欄則持續 missing／excluded。

`feature_pack_missing_or_partial_missing_mask` 必須繼續作 fail-closed diagnostic；不以改 `promotion_day_credit_allowed` 為 true 或製造非零 alpha 解決。collector 的 promotion credit 目前明確被 `formal_rule_champion_weight_snapshot_missing`、`formal_sector_thesis_health_context_missing` 等 blockers 擋住。

有效性目前依 consumer／policy 的 5、10、20、60 個交易 session horizons，要求至少 20 個自然 shadow days、每 horizon 至少 20 個 matured observations、兩種 outcome class，並通過至少 4 outer folds 中 3 勝及 calibration／PSI／coverage／risk／turnover 門檻。當前 matured=0，故 effectiveness、promotion 與非零 alpha 都應保持等待。

Teacher source 的 manifest／receipt 已由 [v4_teacher_source_producer_qa_20260907_v2](../../output/v4_teacher_source_producer_qa_20260907_v2) 取證：schema 為 `allocation-teacher-source-manifest.v2`、storage mode 為 `read_only`，3/3 是 synthetic contract cases，receipt content／artifact／row count／identity hash 有綁定且 tamper case 會拒絕。V2 release 的 base/meta lineage 仍是 cross-fitted raw OOF：fit／meta／calibration 僅 fold-001..003，heldout 是 fold-004，final base/meta 不參與 heldout，target fold label reads=0，parent final meta 未重用；這是 lineage evidence，尚未形成 effectiveness evidence。

價格異常規則依 release manifest 固定為 `missing_is_not_zero`、`unknown_feature_action=reject`、`train_fold_exact_median_indicator_standard_scale`；官方 close 非有限或非正值 fail closed，future price prefix 也會被拒絕。這些規則已在 release／repair contract 取證，沒有以填 0 或未來資料掩蓋當前 source gap。

Pruning 目前只有 review service，尚無自然 shadow → pruning → promotion 的有效性產物；drift／rollback monitor 的 pair append 已補成同一 lifecycle registry 交易，但目前仍沒有自然成熟的 drift／rollback evidence。兩者都是 V4 maturity gap，不能用 synthetic QA 或 fold005（已曝光）代替。

## Drift／rollback lifecycle pair durability

真實 consumer 路徑是 `scripts/run_ml_shadow_inference.py` 的
`simulate_rollback_reason` → `ShadowModelMonitoringService.simulate_rollback`，以及同一
service 的 `apply_drift_review` major-drift 分支；兩者原本都由
`_append_events` 逐筆呼叫 `ModelLifecycleRegistry.append`，每筆各自 commit。現在
`ml_module/model_lifecycle_registry.py` 提供 `append_pair`，兩筆同一 model／時間／reason
的 decision 與 disabling evidence 在單一 `BEGIN IMMEDIATE` SQLite transaction 中驗證並寫入，
仍使用既有 `ml_model_lifecycle_events` registry，沒有新增 registry；同 registry 的單筆
`append` 也使用相同 write lock，避免以舊 lifecycle state 寫入新 pair commit 之後的 transition。

pair replay 會以兩個 event id 與完整 payload 做 idempotent readback；若舊 caller 已留下精確的
第一筆 decision，重跑只允許補上同一 pair 的第二筆並回報 `recovered`。第二筆先存在、
payload／reason／版本矛盾，或 lifecycle state 已在 pair 後推進時，會 fail closed，不改寫既有
event。任何中途 write exception 由 SQLite context rollback，兩筆都不會對外可見。

隔離回歸命令與結果：

```text
\.venv\Scripts\python.exe -m pytest tests/test_ml_model_lifecycle_registry.py tests/test_ml_shadow_monitoring_service.py tests/test_ml_shadow_inference_cli.py tests/test_ml_shadow_inspect_cli.py -q -o addopts=
```

結果為 17 passed；另有一個 pytest cache permission warning。新增測試覆蓋 pair 中途故障後
全 rollback、精確 prefix recovery、重跑 idempotency、矛盾 payload／非可恢復 suffix 拒絕、
pair 與單筆 writer 的確定性交錯，並由 rollback service 真實 caller 驗證同一交易邊界。這些是隔離 engineering evidence，沒有
改 production champion、D、fold006+ 或授予自然 forward／promotion credit。

## Natural shadow → pruning 缺口盤點

依目前 consumer／policy 的實際門檻，下一片工程需要補下列接線；pair durability 已不再是
阻塞原因：

1. `scripts/scheduled/run_ml_allocation_forward_daily.py` 必須以當日 date-bound config，在
   Asia/Taipei 08:30 前讀到前一晚 frozen release／PIT archive，並在 08:35 前完成
   observation emission。現有 2026-09-07 capture 為 17:22 台北、`matured=0`、credit
   false，只能留作研究 evidence。
2. `app_module/ml_allocation_shadow_evidence.py` 目前把 observation 的
   `promotion_day_credit_allowed` 固定保守為 false，因為 formal Rule Champion weight
   snapshot 與 sector/thesis/health context 尚未有合法同日 custody。要取得自然日 credit，
   必須由既有 source producer 提供同一 decision identity 的三項輸入；不能改旗標或製造 alpha。
3. `data_module/prospective_shadow_maturity.py` 及 collector 的現行 maturity consumer 要求
   5／10／20／60 trading-session outcomes、至少 20 個自然 shadow days、每 horizon 至少
   20 個 matured observations，且每 horizon 同時有 current outcome contract 的
   `actual_downside` 0／1。collector 另要求至少 4 筆完整 matured OOS observations 才
   進入正式 reference metrics；目前所有 matured count 仍為 0。
4. 成熟後才可計算 calibration ECE／Brier、feature PSI、coverage、drawdown／CVaR、
   turnover／liquidity 與 block-bootstrap excess-return；`ProspectivePromotionReview` 的
   ten machine gates（含 OOS identity、calibration、PSI、class coverage、lookahead、
   custody、cost、risk、turnover）及 owner authority 仍未有自然輸入。
5. `app_module/v3_pruning_decision_service.py` 仍是 review-only proposal（
   `apply_action=false`、`review_required=true`），其 CLI 仍只消費手動 metrics；本輪已由
   `ml_module/natural_shadow_pruning_evidence.py` 建立 bounded read-only adapter，將現有
   shadow sidecar 的 matured lane／slice identity 與實際提供的 pruning metrics 投影成
   `pending_maturity`／`pending_pruning_metrics`／`ready_for_pruning_review`。adapter 不
   呼叫 pruning service、drift pair 或 promotion；Formal／policy owner 仍須決定何時把
   review input 接入人工流程。
6. pair append 已由既有 lifecycle registry 原子化，但目前沒有自然 drift result 觸發
   `apply_drift_review`／`simulate_rollback` 的成熟資料。任何 major drift／rollback 都須綁定
   frozen model／dataset identity、完整 drift decision 與 pair event ids，且在 evidence
   不足時維持 rule-only。

## Natural shadow → pruning evidence-only consumer

本輪把自然 shadow 的成熟度與 pruning 前置證據接成單一 ML consumer：
`ml_module/natural_shadow_pruning_evidence.py` 只讀既有
`shadow_observations`／`shadow_outcomes` SQLite sidecar，以 `mode=ro`、
`PRAGMA query_only=ON` 讀取兩表，重算 record hash／row metadata，並在 readback 前後重算
sidecar file hash。它不建立第二 registry、不寫 source sidecar、不呼叫
`v3_pruning_decision_service` 或 promotion action。

consumer 的 `as_of_date` 是 Asia/Taipei 日界的 inclusive end-of-day；每個 decision date／
outcome identity 只採用在該日界前已由 `emitted_at`／`available_at`（outcome 也取每個
downside row 的 availability）證明可得的最高 revision。若同時存在多個 availability clock，
取較晚者，避免較早的 emitted 欄位掩蓋晚到的可用內容。晚到 revision 不會回填舊日期；沒有
可證明時間的 record 保留為 pending。

只有 `promotion_day_credit_allowed=true`、沒有 replay／backfill／synthetic flags、source
custody 含唯一 `model_hash`、`dataset_identity_hash`、`policy_hash`，且 outcome 真正覆蓋
5／10／20／60 horizons，才會進 matured count。不同 frozen identity 不可湊成一個 20-day
cohort；未指定 expected identity 時仍要求整批只有一個 cohort。label class 明示為
current outcome contract 的 `actual_downside` 0／1；不從缺值或 lane 結構推導 class。

成熟後若 observation 沒有 pruning lanes、lane metrics 不完整或 sample count 不足，狀態維持
`pending_pruning_metrics`，只列 pending slice；只有 sidecar 已提供完整 metrics 才輸出
`pruning_review_inputs`，仍保留 `apply_action=false`、`promotion_eligible=false`、
`formal_oos_allowed=false`、`production_action_allowed=false`。adapter 不計算或臆造
effectiveness（ECE／Brier／PSI／coverage／drawdown／turnover／bootstrap），這些仍等待
成熟資料與既有 promotion policy。

公開入口為：

```text
\.venv\Scripts\python.exe scripts\inspect_ml_natural_shadow_pruning_evidence.py --shadow-sidecar <exact-shadow-sidecar.sqlite> --as-of-date <YYYY-MM-DD> --expected-model-hash sha256:<64-hex> --expected-dataset-identity-hash sha256:<64-hex> --expected-policy-hash sha256:<64-hex> --output output\v4_next_ml\natural_shadow_pruning_evidence_<YYYYMMDD>.json
```

`--shadow-sidecar` 必須由既有 collector／Ops 傳入 exact path；CLI 不搜尋 latest、不接受
固定 basename bypass，也不從目前 JSON promotion summary 反推或合成 SQLite。output 是
create-only；完全相同 evidence 重跑回同一 bytes，變更 as-of／source 後寫入同一路徑會拒絕。
目前 tracked 的 real v2 output snapshot 沒有隨 repo 提供 durable shadow SQLite；本輪另外以
既有 scheduled collector 的受控 D sidecar 做 bounded read-only readback，沒有寫入或清理來源。
精確來源為
`D:\Min\Python\Project\FA_Data\output\scheduled\ml_allocation_copilot\shadow_evidence_collector\shadow_evidence.sqlite`，
readback 時 sidecar file hash 為
`sha256:b86c91afad16b5d0a07a1382fbb42d9075cd037dea962ca5bc6e38815470a9e8`，總列數為
`shadow_observations=47`、`shadow_outcomes=394`；以 `2026-09-08` Asia/Taipei 日界選出
26 個 observation／26 個 outcome，26 個仍 pending、matured=0，結果為
`pending_maturity`。來源的 `promotion_day_credit_allowed`／可用時間條件沒有形成自然
forward credit，這份盤後 readback 不能當成盤前信用。

readback evidence artifact 為
`output/v4_next_ml/natural_shadow_pruning_evidence_20260908_v2.json`，artifact file hash
為 `sha256:81aedee8aa54fcdcc12c4017933bc9e057fac712d5baf03d4e5e2a33939368f9`，
evidence hash 為 `sha256:8b0745be457e71c83149e442f08750cc741f78b93add481380e673d62fc90e9f`；
readback summary 為 `output/v4_next_ml/ml_natural_shadow_pruning_evidence_actual_summary_20260908.json`，
CLI 完整輸出 log 為 `output/v4_next_ml/ml_natural_shadow_pruning_evidence_actual_readback_20260908_v2.log`；
同一 artifact 的 exact replay log 為
`output/v4_next_ml/ml_natural_shadow_pruning_evidence_actual_replay_20260908.log`。
實際命令為：

```text
$env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe scripts\inspect_ml_natural_shadow_pruning_evidence.py --shadow-sidecar D:\Min\Python\Project\FA_Data\output\scheduled\ml_allocation_copilot\shadow_evidence_collector\shadow_evidence.sqlite --as-of-date 2026-09-08 --output output\v4_next_ml\natural_shadow_pruning_evidence_20260908_v2.json
```

這些是 evidence-only 讀回，不能把 fixture 的 complete lane metrics 當成自然 evidence，
也不會產生 pruning／promotion action。

隔離測試：

```text
\.venv\Scripts\python.exe -m pytest tests\test_ml_natural_shadow_pruning_evidence.py -q -o addopts=
```

結果為 13 passed；覆蓋 partial／research-only pending、latest revision dedup、late
revision 不回填、同 instant 不同 offset、Taipei 午夜晚到、較晚 availability clock、
混 frozen identity、缺 lane、完整／不完整 pruning metrics、tamper、read-only 與 CLI
create-only replay，以及 zero-sample lane metrics 的 pending 邊界。`mypy --explicit-package-bases`
與 `py_compile` 均通過；最新 log 為
`output/v4_next_ml/ml_natural_shadow_pruning_evidence_suite_20260908_v2.log`。

## 驗證與待辦

本輪 bounded suite 與命令記錄在 [ml_bounded_suite_20260908.log](../../output/v4_next_ml/ml_bounded_suite_20260908.log)，摘要為 122 passed、2 個環境 warning；archive consumer 6、shadow evidence 14、orchestration 21、derived 7、scheduled wrapper 9 另有 focused pass。source-quality／exporter／historical feature／label／assembler／raw-shard CLI 的 combined 定向 suite 為 95 passed、2 個環境 warning；assembler 真 shard→feature／label 回歸另為 1 passed，training loader research-only 負例也已覆蓋；`py_compile` 與 explicit-package-bases mypy 已通過 assembler、exporter、training loader 及六個核心 ML source。新增 feature-gap 隔離 fixture／CLI suite 為 3 passed。

On-time 正例使用 real collector append 並保存 `observation_emitted_at`；slow inference 在 append 前 fail closed，slow collector 在 INSERT 後跨 deadline 時 rollback 且 observations 為空。archive TEMP 清除後正向 readback 與 publication rows TOCTOU 負例均通過。

下一個自然日需要 Ops 產生新的 date-bound config、Formal 提供盤前可見或前一晚 durable archive manifest，並以完整 outer payload 檢查 post-inference／emission clock。market close-pair candidate 可供下一個明確支援 contract 的 release；technical legacy 欄在此之前維持 blocked／excluded。沒有成熟證據就記為等待，不啟動重訓或 fold006+。

## Paper policy producer integration QA（2026-09-08）

本輪另完成 Paper EOD consumer 的 ML／policy 接線，範圍限於
`data_module/paper_daily_execution_producer.py`、
`app_module/paper_portfolio_policy_adapter.py`、
`scripts/scheduled/run_paper_execution_daily_isolated.py`、
`ml_module/pit_archive_consumer.py` 及其隔離測試；沒有修改 Formal archive writer、
Ops trigger、正式 champion、D 槽資料或任何 Paper 真執行。`PaperExecutionPaths` 現在必須攜帶
append-only ledger path、官方 bounded calendar，以及明確的 PIT sector sidecar 或 durable
`archive_manifest.json` 和其 file hash。scheduled wrapper 只在受控
`output/formal_daily_publications/pit_candidate_archive` 下選取 custody-verified exact manifest，
不以 basename、環境變數或「最新檔」繞過 hash；producer 再以 frozen recommendation time
重驗 archive consumer、availability、effective date、官方 source identity 與 rows。

政策 adapter 在 liquidity simulator 前一次評估整批 target，保留整數 bp 的 weekly turnover、
official trading-day cooldown、PIT sector mapping 與 minimum cash gate。被拒絕的 target 回到
目前持倉，不會流入 fill builder。fill builder 完成後，producer 以實際
`filled`／`partially_filled` rows 重算 cash、turnover、position 與 sector exposure；
`rejected` sell 不會先釋放 proceeds 或 sector。相同自然日的其他 recommendation fill 會以
`include_decision_date_rows=true` 進入下一批 policy state，只有同一 recommendation 的 exact
immutable fill IDs 在 retry 時排除，因此部分成交 retry 與同日第二候選不會借用昨日 state 或重複
計算週額度。explicit append 後會執行 ledger policy readback；candidate／retry 仍保持
`research_only=true`、`formal_credit=false`、`broker_execution=false`。

真實 durable archive 的跨午夜 readback 已保存於
[paper_archive_policy_readback_20260908.json](../../output/v4_next_ml/paper_archive_policy_readback_20260908.json)：
9/8 capture 的 archive manifest file hash 為
`sha256:c2b838d9d79b794bc13b934c83f5f36f18c1b5828dead20ded9112de6745178f`，1984 rows，
`available_at=2026-09-08T10:28:09.898861Z`，在台北 9/9 00:05 的實際 consumer clock 仍回讀成功，
resolver 也回傳同一 exact path/hash。以 9/8 18:00 台北作為 frozen as-of 時 archive 尚未持久化，
producer 明確 blocked。9/9 是下一自然日的模擬目標，這份 readback 不授予 9/8 或 9/9 的
natural forward credit。

Paper policy／archive／queue／Formal chain 定向回歸命令保存在
[paper_policy_integration_commands_20260908.txt](../../output/v4_next_ml/paper_policy_integration_commands_20260908.txt)，
結果為 **114 passed、1 pytest cache warning**（其中 Paper 12 檔為 107 passed，archive consumer
為 7 passed）。四個 owned source 的 explicit-package-bases mypy 為 **0 errors**，
`py_compile` 為 exit 0；完整摘要與 log 在
[paper_policy_integration_qa_20260908.json](../../output/v4_next_ml/paper_policy_integration_qa_20260908.json)。
這些是 bounded engineering／readback evidence，並不把 synthetic policy matrix、盤後 archive
或成熟度為 0 的 shadow outcome 當成 effectiveness、promotion 或正式交易能力。後續跨午夜與
hash compatibility follow-up 的最新測試與 QA 封套見下節。

### 跨台北午夜 readback 與 machine code hash compatibility（2026-09-08 follow-up）

跨午夜缺口已在 shared machine validator／ML archive consumer 修正：Formal readback 現在仍以
實際 consumer wall clock 驗證 `captured_at`、`archived_at`、receipt evaluation 與 future custody；
只有 first-seen builder 的 `effective_from` 驗證改用不可變 `captured_at`，因此 9/8 capture 在台北
9/9 readback 不會被錯判成今日 capture。合法的 capture 23:59、receipt／archive 於翌日 00:01
完成時也保留實際持久化時間，晚到 archive 仍依 `archived_at <= decision_at` fail closed。

此 readback-only 修正會改變 machine module 的整檔 hash。為避免合法 durable archive 因 validator
修補而被錯誤丟棄，`data_module.pit_sector_membership_machine` 只接受一個程式外可追溯的 audited
legacy hash：
`sha256:a84c39142e89fd771f38d9179d7da243b9c0a58c55772810bdf6bf59d886b546`。它是 HEAD
`cc8dc7874f74e7ce541b802e223b5a35a799230d` 的 machine module LF bytes
`sha256:6f8c33ddcb816e19348b4cb5180c46f7e4a6f0a93350b83064cb010841d03a93` 轉成既有 Windows
CRLF bytes 後的精確 hash，並與 85f71 archive manifest 對讀；不是由 archive 自述值動態建立
allowlist。舊 hash 只有在 `formal-input-pit-candidate-archive.v1`、
`pit-sector-membership-machine-publication.v1`、receipt／input v1、producer version、官方
TWSE／TPEx source identity、raw custody、rows rebuild、first-seen policy 與 envelope code hash
精確一致時才接受；未知 hash、producer／receipt 混合版本與 schema／semantic 不一致一律拒絕。
新產物仍寫入當前整檔 hash `sha256:fbf06b87f68a8e6687a81f5023464307ea5cdb5c24fcb66bae2e1efea1c2edab`。

consumer 結果明示 `code_hash_compatibility=current|audited_legacy`、
`current_code_hash_match` 與 `legacy_code_hash_compatibility_verified`；不再硬編 current=true。
forward config 的 selection projection 會傳遞並驗證這組互斥狀態，legacy 模式可通過明確 audited
compatibility gate，沒有以「不等於 current」作為單獨拒絕條件。Paper source projection 與
scheduled resolver 也保留同一 mode，供下游 audit 判讀。

最新實際 read-only resolver／consumer readback：
[paper_archive_policy_readback_20260908_v2.json](../../output/v4_next_ml/paper_archive_policy_readback_20260908_v2.json)，
output hash=`sha256:6d0da60836fa1c90412439353a9231a3c6c3c3359490b725123d6ed8bc508760`；actual
consumer clock=`2026-09-08T16:27:13.685516+00:00`（台北 9/9 00:27），精確 manifest hash
`sha256:c2b838d9d79b794bc13b934c83f5f36f18c1b5828dead20ded9112de6745178f`，1984 rows，
`source_code_hash_compatibility=audited_legacy`、current match=false、legacy verified=true、
source custody／raw rebuild=true。resolver 選回相同 exact path/hash；以 9/8 18:00 台北作
as-of 的 late archive 仍 blocked（`archive was not persisted before consumer decision`）。9/9
只是 simulated target session，沒有 natural forward、formal、effectiveness 或 promotion credit。

Follow-up archive／validator／forward projection 命令：

```text
\.venv\Scripts\python.exe -m pytest tests/test_ml_pit_archive_consumer.py tests/test_pit_sector_membership_machine.py -q -o addopts= --tb=short
```

結果為 **16 passed、1 pytest cache permission warning**，覆蓋 capture-before-midnight、
actual-now readback、future／late archive、TOCTOU、audited legacy positive、unknown hash、
schema／code mode projection。完整 Paper＋archive＋machine PIT 定向 suite（同樣新增前）為
**122 passed、1 pytest cache warning**，log 為
[paper_policy_integration_suite_20260908_v2.log](../../output/v4_next_ml/paper_policy_integration_suite_20260908_v2.log)。
更新 forward config selection projection 並修正兩個 fake consumer contract 後，
`tests/test_ml_forward_scheduled_wrapper.py` 與
`tests/test_ml_forward_task_registration_plan.py` 再通過 **21 passed、1 pytest cache warning**；
真 archive 的 projection readback 也確認 `current_code_hash_match=false` 搭配
`code_hash_compatibility=audited_legacy`、`legacy_code_hash_compatibility_verified=true` 可沿
既有 config consumer 通過，沒有把 legacy 當成 current。其餘下游仍依 consumer 的 accepted
status、source custody、PIT 時間與 candidate-only flags 判讀，不授予自然 forward credit。
其完整 log 為
[paper_forward_config_compatibility_suite_20260908.log](../../output/v4_next_ml/paper_forward_config_compatibility_suite_20260908.log)。
六個 owned source 的 `mypy --explicit-package-bases --follow-imports=skip` 為 0 errors，
`py_compile` 為 exit 0；之後以相同六個 source 執行未加 skip 的
`mypy --explicit-package-bases` 也為 0 errors，沒有修改 Formal owner 檔案。 follow-up log 為
[pit_archive_cross_midnight_compatibility_suite_20260908.log](../../output/v4_next_ml/pit_archive_cross_midnight_compatibility_suite_20260908.log)。
最新 QA 封套為
[paper_policy_integration_qa_20260908_v2.json](../../output/v4_next_ml/paper_policy_integration_qa_20260908_v2.json)，
其 file hash=`sha256:86afa0c77902e43cbc1c65ae2772e3514d2430ad5544ed9281e12a8f873dfa03`。

## Deadline 外 maturity 後處理與 ML 整合 QA（2026-09-08）

本輪把自然 forward child 的 observation emission 與既有成熟評估拆成兩個時段。`scripts/scheduled/run_ml_allocation_forward_daily.py` 仍以 `subprocess.run(timeout=remaining_to_08:35)` 限制 inference child；child 返回（成功、非零、payload gate 失敗或 timeout）後，父 wrapper 才呼叫公開的 `run_shadow_maturity_refresh`。因此慢的 maturity／pruning readback 不會佔用 08:35 emission deadline，也不會把 child 的完整 stdout 或原始 outer status 攤平成內層成功。後處理 payload 綁定 frozen config 的 `output_root`、market database、exact lane sidecar，保留 `source_binding`、`child_result_available`、實際 cutoff 與完整 nested result；所有結果仍是 read-only、`natural_day_credit_granted=false`、`forward_credit_granted=false`。

父 wrapper 不再把成功 child 缺少 maturity cutoff 當成普通 pending。缺少必要 cutoff、無法載入官方日曆、日曆未知、日期格式錯誤或與 decision 日的 strict official T-1 不一致，均形成 `post_deadline_maturity.status=blocked`、outer degraded／exit marker。child 若提供 cutoff，仍由同一官方日曆重新解析並比對，不能以任意過去日期或 `<= today` 取代交易日證據；timeout 沒有 child payload 時才由 scheduled environment 的 verified calendar cache 解析 cutoff。共用 `scripts/run_daily_ml_allocation_orchestration.py` public/lower maturity entry 另拒絕 future cutoff，並以實際 runtime clock 限制 available-at readback。

本輪 owned source／tests：

- `scripts/scheduled/run_ml_allocation_forward_daily.py`：deadline 外 maturity 接線、strict T-1／calendar source binding、成功與失敗 child 的完整 outer contract。
- `tests/test_ml_forward_scheduled_wrapper.py`：更新 child fixture 的 maturity contract，新增缺 cutoff／任意 T-1 負例、real subprocess child、1.1 秒跨 deadline slow maturity、timeout child 後官方 T-1 refresh。
- 既有 `app_module/ml_allocation_shadow_evidence.py`、`scripts/run_daily_ml_allocation_orchestration.py` 與其 tests 維持 post-inference emission／actual availability cutoff／common degraded marker 契約；沒有新 fit、fold006+、D 槽寫入或 promotion。

定向驗證命令與結果：

```text
\.venv\Scripts\python.exe -m pytest tests\test_ml_forward_scheduled_wrapper.py tests\test_ml_allocation_forward_child_contract.py tests\test_ml_forward_task_registration_plan.py -q -o addopts=
28 passed, 1 pytest cache permission warning (2.30s)

\.venv\Scripts\python.exe -m pytest tests\test_ml_allocation_shadow_evidence.py tests\test_daily_ml_allocation_orchestration.py tests\test_daily_ml_allocation_derived_shadow.py tests\test_ml_forward_scheduled_wrapper.py tests\test_ml_allocation_forward_child_contract.py tests\test_ml_forward_task_registration_plan.py tests\test_ml_natural_shadow_pruning_evidence.py tests\test_natural_shadow_pruning_evidence_runner.py tests\test_ml_pit_archive_consumer.py tests\test_portfolio_ml_dataset_assembler.py tests\test_ml_price_availability_contract.py tests\test_ml_historical_feature_computation.py tests\test_ml_historical_label_builder.py tests\test_ml_model_lifecycle_registry.py tests\test_ml_shadow_monitoring_service.py tests\test_ml_daily_price_source_quality.py tests\test_ml_pit_year_shard_exporter.py -q -o addopts= --tb=short
209 passed, 2 warnings (29.25s; loky physical-core probe and pytest cache permission)

\.venv\Scripts\python.exe -m mypy --explicit-package-bases --follow-imports=skip scripts\scheduled\run_ml_allocation_forward_daily.py scripts\run_daily_ml_allocation_orchestration.py app_module\ml_allocation_shadow_evidence.py
Success: no issues found in 3 source files

\.venv\Scripts\python.exe -m py_compile scripts\scheduled\run_ml_allocation_forward_daily.py scripts\run_daily_ml_allocation_orchestration.py app_module\ml_allocation_shadow_evidence.py tests\test_ml_forward_scheduled_wrapper.py tests\test_daily_ml_allocation_orchestration.py tests\test_ml_allocation_shadow_evidence.py
exit 0
```

Root 隨後以 `--follow-imports=silent` 對三個 source 做 shared-tree typecheck，結果為 0 errors；本輪沒有修改 Formal owner 檔案。若使用完全 dependency-following 的預設 mypy 行為，shared `data_module/formal_daily_input_producer.py:4984,4986` 仍有兩個既有 `object`／`Decimal` 型別錯誤，應由 Formal owner 處理。其餘 209 項跨 exporter／assembler／training／inference／natural consumer 回歸均通過。wrapper 的 real subprocess slow maturity 測試證明父層後處理可在 child timeout 邊界外完成，但結果仍保留 evidence-only，沒有把 `matured=0` 或 fixture 成熟資料宣稱為 effectiveness、pruning、promotion 或 natural forward credit。

Root 的同片跨檔驗收再以 `tests/test_daily_ml_allocation_orchestration.py tests/test_ml_allocation_shadow_evidence.py tests/test_ml_forward_scheduled_wrapper.py tests/test_ml_allocation_forward_child_contract.py` 執行 **72 passed**。Forward CMD preflight 亦已唯讀 exit 0：calendar refresh preflight、V2 release hash、repo Paper state、D market DB、archive、calendar cache 與 repo output 皆存在；未發 network、child、config producer 或資料庫寫入。這只是 runtime／path readiness，不是自然 forward run 或 calendar 內容續期證據。

QA 摘要亦保存於 `output/v4_next_ml/ml_forward_deadline_external_qa_20260908.log`。目前未解項是 shared Formal producer 的上述 mypy 型別錯誤，以及自然 sidecar 仍 `matured=0`；兩者都應維持可見 blocked／pending，不以測試資料或改 clock 補足。

## Direct chain 停滯唯讀診斷與同 run 恢復 gate（2026-09-08）

本次 Direct run 的唯讀讀回已保存於
`output/v4_next_ml/direct_chain_failure_readback_20260908.json`。run identity 為
`direct-ooc-3cec102bc9f96e2219319560`，raw manifest hash 為
`sha256:d55879c6d4bfae7c8fbb095330b0732eb1c5c80ecd2e0a0b5b79ee617b2eddc9`；
`checkpoint.json` 仍是 `complete=false`，已通過 custody 的年度為 2014--2019，
heartbeat 最後停在 2020 的 `raw_spool_observations_batch_written`，時間為
`2026-09-08T17:33:36.563146Z`。`.work-year-2020/assembly.sqlite` 仍存在，
大小為 10,272,763,904 bytes；未刪除工作目錄，也未重建或覆寫任何已完成年度。

`store_output_dir\logs\direct_v3_refresh.log` 最後寫入時間是
`2026-09-06T18:32:28.5740993Z`。其中的
`sqlite3.OperationalError: database or disk is full` 發生在舊輸出，不能作為
9/8 的本次 terminal 原因。9/8 maintainer log 只到
`2026-09-08T12:30:07.731552Z` 的 `starting_checkpoint_recovery`，沒有
`continuation_exited`；root 的唯讀 process probe 也確認 Direct、OOC、release 與
maintenance owner PID 均已不存在。Task 的 `LastResult=3221225786`
（`0xC000013A`）及既有事件查詢不足以辨識確切外部原因，因此目前原因保持
`unknown`，不把它歸因於容量、電源、登出或特定操作者。checkpoint 當時的容量證據仍為
free 331,398,438,912、required 295,279,001,600、temporary peak
22,840,995,789 bytes，四項 budget/headroom/reserve 判斷均為 true。

同一 run 只有在能取得原程序實際 loaded source snapshot 並通過 source-version gate 時才可恢復；
目前沒有該 snapshot，因此不把 HEAD 等同於原程序版本，也不混用現行 assembler 重建未完成年度。
Direct builder、Direct
CLI、continuation、OOC、release、out-of-core、capacity、PIT resolver 與 allocation
training source 在 working tree 均與 HEAD 相同；但 `data_module/portfolio_ml_dataset_assembler.py`
目前 hash `3fdbc87157c5c7eb125ca5a67c5f2b3494ba7888`，HEAD hash
`326d11aa4f2e63f5ae49b6154a7bba87bb2b77dc`，且檔案最後寫入
`2026-09-08T13:59:18.561Z`，晚於本 run 的 discovery cache
`2026-09-08T12:52:00.922Z`。此改動把 label path 改為每一日完整 OHLC 檢查並加入
price availability gap；即使目前 raw manifest 沒有 `source_quality`、取樣 8 rows
沒有 `price_availability_contract`，仍不能假設 2020 重建與已完成年度語意相同。
checkpoint 沒有記錄 runtime source hash，因此未通過此 gate 前不應混用現行 assembler
重建 2020。這項缺口也不能靠把磁碟 HEAD hash 回填進歷史 checkpoint 解決。

若日後尋回精確 loaded snapshot，原 run 才可使用既有 Direct-only request；它使用既有
run identity、預設 `resume=true`，會驗證並重用 `year=2014..2019`，再由 builder 自己處理
不完整的 `.work-year-2020`，不需要手動清理，也不啟動 OOC、release、fit 或 fold006+：

```text
C:\Projects\PythonProjects\technical_analysis\.venv\Scripts\python.exe C:\Projects\PythonProjects\technical_analysis\scripts\build_portfolio_ml_direct_numeric_store.py --raw-manifest D:\Min\Python\Project\FA_Data\output\release_v4\ml_pit_year_shards\runs\pit-6874d65ee70d4f84cf41f5d1\all_field_enriched\manifest.json --output-dir D:\Min\Python\Project\FA_Data\output\release_v4\portfolio_ml_direct_numeric_production_v4_v2 --training-as-of 2026-09-07T08:30:00+08:00 --benchmark-entity TAIEX --minimum-train-dates 252 --test-date-count 63 --purge-trading-days 60 --embargo-trading-days 5 --batch-size 8192 --workers 2 --memory-budget-mb 4096 --corporate-action-manifest D:\Min\Python\Project\FA_Data\output\release_v4\official_market_events\runs\official-market-events-189a6e1401c0396ff8cd353a\manifest.json --temporary-storage-budget-bytes 42949672960 --persistent-storage-budget-bytes 37580963840 --safety-reserve-bytes 214748364800
```

執行前仍須重新確認 matching process 全部不存在、heavy-chain lock 由既有 builder
protocol 取得、checkpoint 與六個年度 manifest/carry hash 未變，以及同一 assembler
語意已被明確接受。Direct 完成並重新讀回 manifest/checkpoint custody 後，才可另行考慮
下游 continuation；本次恢復本身不給 formal OOS、effectiveness、promotion 或自然
成熟度 credit。

### 無法證明舊 loaded 版本時的 Direct-only 隔離重建方案

既有 run、六個完成年度與 2020 工作目錄先保全為 read-only evidence。若 root 無法取得原
程序的 loaded source snapshot，唯一可供審核的替代方案是另建新的 output namespace 與
computation dependency identity，使用 fresh process 在建構開始凍結 15 個 Direct 依賴的
loaded function fingerprint／typed constants，並於年度邊界重驗磁碟 source custody。這個
方案不採用舊 run 的 labels、carry 或年度 numeric outputs；保守將 assembler 影響範圍
manifest shards 的 2014--2026 共 13 年全部重建。raw PIT blocks 只按既有 content-addressed immutable resolver
唯讀共用，不複製 raw bytes，也不把共用 raw 的 reuse 當成 label 等價證據。

具體但尚未執行的方案與完整命令在
`output/v4_next_ml/direct_chain_rebuild_plan_20260908.json`。計畫使用新的 output root
`portfolio_ml_direct_numeric_production_v4_v2-source-rebuild-79dccf8b7f0b`，最大 temporary
budget 40 GiB、persistent new bytes 35 GiB，並保留 200 GiB safety reserve；raw manifest
實際有 13 個 shard（2014--2026、16,039,958 rows、compressed 10,253,813,568 bytes）。
此 raw manifest 的 canonical content hash 為
`sha256:d55879c6d4bfae7c8fbb095330b0732eb1c5c80ecd2e0a0b5b79ee617b2eddc9`，實體 manifest
file SHA 為 `sha256:6ecc7b26040e00b5c9f70f77b22a7bc9dd976a38453a88c1d1d9865a1eb4e5bc`；兩者
分開綁定，任一不符即拒絕，不能把 canonical hash 當成檔案 bytes hash。
以 production `_estimate_persistent_new_bytes`（feature_count=52、四個
`SUPPORTED_HORIZONS`）計算，全 13 年保守 persistent estimate 為 15,333,023,892 bytes；
年度 temporary estimate 最大為 15,953,216,418 bytes（2024），均低於 request 上限，仍須
由 live preflight 驗證實際 headroom。舊六年已完成年度輸出合計 2,186,927,227 bytes，
僅作 bounded 外推 evidence，不替代全 13 年估算；未完成 2020 workspace
10,272,763,904 bytes 仍保留在舊 namespace，raw copy 增量為 0。

Direct builder 的 `mkdtemp` 與 atomic JSON temp 都明確使用 D 上的 run directory／path
parent；Direct-only path 沒有顯式寫入 system TEMP。計畫不硬加未證明的 C reserve gate，
但若 fresh process 的實際 dependency／library trace 顯示 system TEMP 有寫入，才把該 root
納入同一 preflight。歷史 checkpoint 容量曾在 D 槽通過，不能代替 live 檢查。新 namespace
失敗時保留新 checkpoint／log，絕不刪除舊 run 或 raw。只有新 Direct manifest／checkpoint
完成並重新驗證後，才可另行審核 OOC／release；本計畫沒有啟動新 run、fit、fold006+ 或
D 寫入。

### Direct dependency freeze 與啟動 custody（2026-09-08）

canonical code identity 已由不穩定的 `marshal.dumps(payload)` 改為 typed canonical JSON：
基本值保留型別、bytes 以 hex、tuple／list／set／frozenset／dict 以明確標記且固定排序。
同一份 source/live code 在 module 執行前後的欄位與 instructions 相同時，fingerprint 維持
相同；source bytes 在年度邊界變更、loaded module code 變更、constant 新增／刪除／改值，
以及 resume snapshot 不一致都 fail closed。15 個 Direct 計算依賴的完整 path、source
SHA、loaded code fingerprint／constants 與 snapshot hash 保存在
`output/v4_next_ml/direct_dependency_freeze_qa_20260908.json`；本輪 freeze hash 為
`sha256:79dccf8b7f0b30a19334c10563fc1766e9e1c15dad59c7bd22fb448dc5e60da3`。

freeze 清單為：

```text
data_module/portfolio_ml_direct_numeric_store.py
data_module/portfolio_ml_dataset_assembler.py
data_module/portfolio_ml_out_of_core_store.py
data_module/ml_storage_capacity.py
data_module/ml_pit_shared_block_resolver.py
data_module/ml_direct_shared_block_resolver.py
data_module/formal_portfolio_ledger.py
data_module/rule_champion_snapshot_service.py
data_module/teacher_input_source_producer.py
ml_module/allocation_training_service.py
ml_module/allocation_contracts.py
ml_module/allocation_teacher.py
ml_module/immutable_ml_block_store.py
ml_module/purged_walk_forward.py
data_module/ml_price_availability_contract.py
```

其中 `teacher_input_source_producer.py` 在本次 fresh process 尚未載入，故 snapshot 保留
source custody、loaded 欄位為 absent；lazy import 不能被誤報成 drift，若日後載入則仍以
source hash／code compatibility 驗證。這份 freeze 的 QA log 為
`output/v4_next_ml/direct_dependency_guard_qa_20260908.log`：guard／真正年度發布後容量
中斷再 resume、constant add／delete／change、old loaded module mismatch 共 **9 passed**；
capacity checkpoint／command regression **2 passed**；forward wrapper／registration
跨 ML import 回歸 **25 passed**；Direct source mypy 與 py_compile 均 exit 0。root 另獨立
驗證真 shared/OOC **9 passed** 及相同 interruption builder resume **1 passed（77.03s）**。

root 的唯讀容量 readback `output/v4_next_root/direct_rebuild_capacity_readback.json` 已
確認 D 實際 Direct roots free `321,123,573,760` bytes、required
`295,279,001,600` bytes、四項 budget／headroom／reserve 均通過；接著以同一 freeze hash、
exact raw manifest content/file hash、無 matching process／lock、fresh process loaded identity
及既有 builder capacity protocol 啟動新 namespace。launcher PID `2220` 在
`2026-09-08T19:42:58.5116562Z` 建立隱藏 process，實際 builder child PID `23028`；啟動後
heartbeat 已讀到新 run `direct-ooc-3cec102bc9f96e2219319560` 的 discovery，狀態為
`running`。完整 command vector、stdout、stderr、heartbeat 與 hash 綁定保存在
`output/v4_next_ml/direct_rebuild_launch_receipt_20260908.json` 及
`output/v4_next_ml/direct_rebuild_actual_launch_readback_20260908.json`；root 的獨立
launch readback 為 `output/v4_next_root/direct_rebuild_actual_launch_readback.json`。

這是 Direct-only 13 年重建；OOC、release、fit、fold006+ 與 promotion 均未啟動，舊 run／
raw 保全不變。執行期間不重啟、不清理舊 namespace、不高頻輪詢；只有 Direct 自身的新
output namespace 可寫入。

## Exit 自然成效 producer／consumer（2026-09-08）

本片先修正一個可重現的 read-model 缺陷：舊版
`app_module/exit_effectiveness_read_model.py` 只用 `reason_code` 聚合，且把所有
`ready` row 的 `post_exit_return_bp` 都放進避損／後悔統計。因此同一理由的
proposal（反事實 -800 bp）與真正 closed（+500 bp）會被錯算成一個實際退出樣本。
現在 slice 以 `reason_code`、固定 outcome horizon 與 `policy_id` 分層；closed 的
ready 指標只接受完整 Paper sell 與無限制的 verified lineage，proposal／human-approved
則只進入明示的 `counterfactual_*` 欄位。

新增 `app_module/exit_effectiveness_producer.py` 與
`scripts/run_exit_effectiveness_daily.py`。producer 以 read-only、hash-before/after 的
方式讀既有 `position_health_transitions` 與 `paper_trade_ledger`，用 Paper entry row
hash 驗證 `paper:<portfolio>:<symbol>:entry-<hash24>` lineage；只有累積賣出後持倉歸零
才轉成 `closed`。partial、rejected、同日無序成交、未知 source type、lineage 不符或
未人工核准的 proposal 均保留為研究 evidence，不會產生 broker order 或 auto exit。
transition row hash、ledger row hash、market source hash、calendar evidence hash、entry／
exit fill id 與 observation hash 都寫進 immutable payload；來源 SQLite 永不由此 producer
建立或改寫。

outcome policy 固定為 **5 個官方交易日**，這是第一個版本化的研究 outcome window，與
既有 Position Health 的 20-day holding horizon／5-day review cadence 分開，也不是從已看
到的績效值調參。transition policy 另以既有
`position_health_transition_evaluator.DEFAULT_POLICY_HASH` 綁定。anchor 僅取 decision
日前最近官方交易日，outcome 僅取官方 calendar 的 ordinal future date；日曆未知、價格
缺失／非正／未來來源、anchor row-level PIT 可得性不明、公司行動來源缺件或 window 受公司行動影響
時，row 會保持 `pending` 並列出精確 `limitation_codes`。價格 SQLite 的 container mtime
不再替代 anchor 的歷史可得證據：若 `daily_prices` 有
`available_at`／`data_available_at`／`資料可得時間`／`availableAt` 欄位，anchor 必須在
決策日 08:30 Asia/Taipei 前可得；若沒有 row-level 欄位，proposal 不能取得自然
counterfactual credit。成熟後的 outcome 可用當次 read 的 file mtime 作來源可得性
fallback；已驗證 closed fill 不會因缺少無關的 anchor timestamp 被阻擋。成熟度沿用
`OutcomeMaturityService`，不以 weekday 推定交易日，也不以歷史資料回填自然 credit。

closed 的 `realized_return_bp` 使用 Decimal cash settlement 計算，買入端加入
commission/tax、賣出端扣除 commission/tax；`slippage_cost` 已反映在 fill price，
不會被重扣。payload 以 `realized_return_basis=net_cash_after_commission_tax_bp`
明示 basis，proposal 仍只使用 `counterfactual_price_return_bp`。

每日入口的 exact interface 為：

```text
\.venv\Scripts\python.exe scripts\run_exit_effectiveness_daily.py --transition-db <position_health_transitions.sqlite> --paper-ledger-db <paper_trade_ledger.sqlite> --market-db <twstock.db> --calendar-cache <official-calendar-cache-root> --temporary-closure-cache <optional-cache-root> --output <controlled-derived-output.json>
```

CLI 不接受歷史 `--as-of` 或 `--now` 覆寫；每次 output 使用 create-only 寫入，完全相同
payload 可 `reused`，不同 payload 會旁置 hash-suffixed artifact，不覆寫舊 evidence。輸出
固定 `research_only=true`、`formal_credit=false`、`auto_exit_allowed=false`、
`broker_order_allowed=false`、`historical_backfill=false`；blocked 會以 exit code 2 並在
payload 的 `blockers` 留下原因。

隔離驗收：

```text
\.venv\Scripts\python.exe -m pytest tests\test_exit_effectiveness_producer.py tests\test_exit_effectiveness_read_model.py -q -o addopts=
18 passed（pytest cache permission warning only）

\.venv\Scripts\python.exe -m mypy --explicit-package-bases --follow-imports=silent app_module\exit_effectiveness_read_model.py app_module\exit_effectiveness_producer.py scripts\run_exit_effectiveness_daily.py
Success: no issues found in 3 source files

\.venv\Scripts\python.exe -m py_compile app_module\exit_effectiveness_read_model.py app_module\exit_effectiveness_producer.py scripts\run_exit_effectiveness_daily.py
exit 0
```

測試涵蓋真 producer→read model 的 full close 正例、proposal-only counterfactual、同理由
分離、partial/rejected sell、成熟／未成熟 horizon、future transition、缺公司行動來源、
row-level anchor 可得／未提供／未來 timestamp、container mtime 不得污染既有 row 的
PIT、closed 不依賴 anchor timestamp、commission/tax net basis、hash-bound lineage、
重跑冪等與 immutable conflict。現有來源唯讀 readback 已保存於
`output/v4_next_ml/exit_effectiveness_actual_readback_20260908_3901a84171c21790.json`：transition SQLite 0 rows、Paper
ledger 8 rows、market price bounded read 491 rows；結果為 `degraded` 且 warning
`no_exit_transition_rows`，沒有任何自然 closed 或 counterfactual credit。這次 readback
也明示 market SQLite 沒有 row-level availability 欄位，因此目前資料只能供成熟 outcome
的 read-time fallback，不能替 proposal 建立 anchor PIT credit。calendar 與 market、ledger
皆是 `query_only/read_only`，此 probe 沒有寫 D 或改來源。實際自然 caller
仍需由 Ops 將上述參數接到既有每日任務；本片沒有改 Ops source／health／caller 檔案。
