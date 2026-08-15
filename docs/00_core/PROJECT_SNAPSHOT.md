# PROJECT_SNAPSHOT（必讀｜每次開新對話先看）

## 2026-08-14 Prospective formal simulated portfolio decision

- Owner 已確認現有持倉是功能測試資料、不是實際券商持倉，且截止時間前沒有真實保存的正式 Portfolio transitions／HMAC-signed Rule snapshots；因此不回填、不把 research/history 改名 Formal，改採 **prospective-only、受治理但非實盤** 的模擬持倉 clock。完整順序、契約邊界與驗收見 [Prospective Formal Simulated Portfolio Execution Plan](../06_qa/PROSPECTIVE_FORMAL_SIMULATED_PORTFOLIO_EXECUTION_PLAN_2026_08_14.md)。
- 正式起算日尚未指定；只有 clock contract、Portfolio／Rule producer、合法 prospective PIT source 與 capture readiness 通過 QA 後，才選當時仍在未來的台灣交易日。`2014–2026` 既有 Direct／OOC 與 research artifacts 保留為 history，不取得 full-history Formal credit；prospective-only 也不豁免每日 sector source／license／publication／hash lineage。
- `PFS-01`～`PFS-10` 已完成：clock／Portfolio producer／clock-bound HMAC Rule publisher／prospective PIT sector custody／inference-level calibration policy／capture-only readiness／frozen activation contract／shadow maturity gate／frozen-candidate OOS evidence／promotion review contract 均通過 focused QA；PFS-10 新增 5 個 tests，固定 10 個 machine gates、owner review boundary 與永不自動 promotion。PFS-04～PFS-10 仍只產生受控 fixture 的 prospective sidecar／shadow audit／readiness／activation contract／maturity report／OOS evidence／review package，不設定正式 path、不寫 `D:`、不啟動 watcher；程式面下一步已完成，執行面等待 owner 以受控環境提供未來 activation decision。預設仍把 cutoff=`2026-08-13T08:30:00+08:00` 的現有 candidate 綁為未來 clock 的 frozen challenger；clock 啟動後不得用已消費的 Formal OOS 期間重訓或替換 model／calibration，重型 watcher 維持停止。
- `PFS-01`～`PFS-10` 已完成：clock／Portfolio producer／clock-bound HMAC Rule publisher／prospective PIT sector custody／inference-level calibration policy／capture-only readiness／frozen activation contract／shadow maturity gate／frozen-candidate OOS evidence／promotion review contract 均通過 focused QA；PFS-10 新增 5 個 tests，固定 10 個 machine gates、owner review boundary 與永不自動 promotion。PFS-04～PFS-10 仍只產生受控 fixture 的 prospective sidecar／shadow audit／readiness／activation contract／maturity report／OOS evidence／review package，不設定正式 path、不寫 `D:`、不啟動 watcher；程式面下一步已完成，執行面等待 owner 以受控環境提供未來 activation decision。預設仍把 cutoff=`2026-08-13T08:30:00+08:00` 的現有 candidate 綁為未來 clock 的 frozen challenger；clock 啟動後不得用已消費的 Formal OOS 期間重訓或替換 model／calibration，重型 watcher 維持停止。另新增 `scripts/capture_prospective_shadow_observation.py --fixture-only`，可在 activation 後把已驗證的五條 producer lineage、T-1 與 matured outcome rows 寫成單日 create-only observation；它不會抓歷史、補日、產生 target 或解除任何 gate。
- 目前 execution handoff 的唯讀 preflight 已加入：`scripts/inspect_prospective_activation_environment.py` 只讀 Windows controlled environment、不輸出 HMAC secret；2026-08-15 實際結果為三個 `BALDR_ML_*_PATH` 缺失，shared reader 的 controlled store／HMAC configured flag 已存在，但 activation launch／heavy rebuild／Formal OOS 仍全部 false。設定合法 paths 後必須重新跑 preflight，不能以 configured flag 直接宣稱正式 clock 已啟動。另新增 `inspect_prospective_capture_readiness.py --controlled-environment` 與 PFS-07 `activate_prospective_formal_clock.py --fixture-only --controlled-environment`，可在 owner 明確 opt-in 後以同一 shared reader 驗證並凍結三個 manifest／sidecar paths；兩者仍是 capture-only／create-only、fail-closed，不設定環境、不讀 secret、不啟動 watcher／Direct／OOC。
- 這項產品決策不放寬既有 Gate；目前仍為 `formal_oos_allowed=false`、production alpha=`0`、broker disabled，calibration `quality_pass=false` 與 `rebalance_worthwhile` class 1 缺失仍需分別修正與重新驗證。

## 2026-08-14 Formal watcher post-refresh custody correction

- 唯讀重驗現行 readiness 後，`RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY` 與 `RULE_CHAMPION_CONTROLLED_STORE_ID` 已可由 controlled runtime handoff 使用；秘密值未讀出或寫入任何 command line、status 或 log。真正仍缺的是三個正式 artifact path：causal non-cash portfolio ledger、formal Rule Champion snapshot history 與 PIT sector membership，因此 `formal_oos_allowed=false`、production alpha=`0`、broker disabled 不變。
- 發現 `maintain_ml_direct_v3_refresh_chain.py --watch-formal-inputs` 在一次成功的 Direct/OOC continuation 後會直接正常結束，沒有回到 formal-input polling；這是 watcher custody 的退出缺口，不是 ML training crash 或重複 MCP。已修正為成功 continuation 後保留 instance lock 並繼續 polling，且新增 regression test 覆蓋此路徑。修正不建立 formal artifact、不重跑訓練、不改寫 SQLite，也不放寬任何 promotion gate。
- 本輪 focused maintainer／scheduled wrapper regression=`26 passed`、calibration／teacher／OOS replay 相關 regression=`28 passed`、`py_compile` 通過；mypy 以 package-base 模式檢查 `scripts/maintain_ml_direct_v3_refresh_chain.py` 與其測試為 `0 issues`。Windows watcher 尚待以這個修正版本重新啟動後才會恢復長駐 heartbeat。
- 重啟前的唯讀 dry-run 已確認 current Direct cutoff=`2026-08-13T08:30:00+08:00`，但最新 raw PIT candidate cutoff=`2026-08-14T08:30:00+08:00`。因此立即啟動 watcher 會開始完整 immutable Direct → OOC rebuild，而不是單純等待 formal input；為避免未經 owner 明確確認就消耗大量 CPU，relaunch 暫停等待指示。

## 2026-08-14 Daily Workbench UX / desktop responsive follow-up

- 主 UI 的預設「決策工作台」首頁已由工程狀態優先，調整為「今日行動中心」優先：依既有 `WorkbenchDashboardDTO` 只讀投影資料狀態、市場待判讀、Advice／候選與持倉覆盤四項，並依資料缺口、既有持倉 Action Item、待判讀與 Advice 是否存在，選出一個下一步導覽。這些按鈕只切換至既有數據更新、市場總覽、推薦分析或持倉管理，不觸發更新、策略、寫入、持倉變更或交易。
- `AdaptiveWorkspaceStack` 改為只讓目前可見工作區提供主視窗最小尺寸；先前 1024×768 會被隱藏工作區的最大 hint 強制放大為 1881×1014，現在真實 offscreen MainWindow smoke 的 1440×900 與 1024×768 都 `matched`。寬度不大於 1120 時左側導覽自動收為 icon-only，僅在此自動收合情況下於寬度回到 1240 時展開；使用者手動收合不會被覆寫。
- focused UI／read-only boundary 驗證為 `85 passed`，資料更新頁 QA 為 `23 passed / 0 failed`；另以隔離 `DATA_ROOT` 的 8-workspace MainWindow smoke 驗證所有工作區仍可切換、沒有發出任何禁止動作。此變更不改變 Advice／ML／Evidence／Data Gate，`formal_oos_allowed=false`、production alpha 0 與 broker 禁用狀態不變。

## 2026-08-14 Windows WER／Qt native crash follow-up

- 重新以唯讀方式盤點 `C:\ProgramData\Microsoft\Windows\WER\ReportArchive` 後，修正先前「沒有 Python Application Error」的過度結論：目前可讀取的 `python.exe` archive report 中，有 `59` 筆 fault module=`Qt6Core.dll`、exception code=`c0000409`、event type=`BEX64`，最新一筆為 `2026-07-27`；代表性報告的 `AppPath` 是 Python 3.11 base interpreter，但 loaded modules 明確包含本專案 `.venv\Lib\site-packages\PySide6\` 下的 `Qt6Core.dll`、`Qt6Gui.dll`、`Qt6Widgets.dll`、Shiboken，以及本專案環境的 numpy／pyarrow。這支持歷史上確實有本專案 Python／PySide6／Qt environment 的 native crash 線索，但沒有 command line 或 dump，不能鎖定是哪個 entrypoint、不能單獨證明唯一觸發點，更不能推論為 SQLite lock。
- 同一輪事件稽核也把干擾項分離：`2026-08-14` 兩筆 `Application Error 1000` 的 faulting application/module 都是 Codex 內建 `rg.exe`；`2026-08-10` 的另一筆是 `RemoteMouseCore.exe`。目前沒有可歸因於 `technical_analysis`／`ui_qt` 實際 session 的新 Application Error；`RADAR_PRE_LEAK_64` 仍是記憶體壓力預警，不等於 crash。WER archive 有部分 `Report.wer` 因權限無法讀取，因此上述 Python report 統計是可讀子集，不冒充完整總數。
- 目前 production code 的 `QThread.terminate()` call site 仍為零；worker 只做 cooperative cancel，並新增 native `QThread.finished()` alias、執行中 strong reference 與延後 `deleteLater()`，避免 task-result queued cleanup 在原生 thread return 前釋放 QThread。App close 仍會在 worker 或 TPEX background process 尚未安全結束時阻止關閉。`DATA_ROOT/logs/ui_qt_crash.log` 的每個 `SESSION_START` 現在另記錄 executable、argv0、cwd、parent PID 與 DATA_ROOT（不記錄完整環境或秘密），下一次實際 UI 啟動／中斷可直接把 WER 對回 entrypoint；仍需與 WER、dump（若有）交叉定位。
- 新增 lifecycle regression 後，第一次把 worker 測試與 report-export 測試放在同一個 pytest process 時，`2026-08-14 03:18:53` 與 `03:20:09` 各產生一筆相同的 `python.exe`／`Qt6Core.dll`／`BEX64`／`c0000409` WER；單獨跑各檔案不重現，根因定位為測試先建立 `QCoreApplication`、後續 QWidget 測試再取得同一 instance 的 harness contamination，不是 production App 證據。測試已改用 offscreen `QApplication`，修正後 worker／crash／shutdown／report export／research save／Update Workbench 合計 `70 passed`，03:20 後沒有新增 Python WER。這個結果修正了測試證據鏈，但不把歷史 production-like Qt native crash 宣稱已完全解因。
- 真正呼叫 `ui_qt.main.main()` 的 offscreen entrypoint smoke 另發現 Windows cp1252 console 會在第一個繁中啟動 `print()` 前拋 `UnicodeEncodeError`，程序尚未建立 `QApplication` 即退出；`ui_qt/main.py` 現已在直接／間接 entrypoint 以 UTF-8、`backslashreplace` fail-soft reconfigure stdout/stderr。修正後同樣 cp1252 條件下 MainWindow 完整建立、事件循環正常退出（return code=`0`），暫存 diagnostics 留下 `SESSION_END clean_shutdown=true exception_observed=false`；這是 console encoding 問題，不是 DB lock 或 Qt native fault。

## 2026-08-14 Promotion preflight revalidation

- 以共享 operational root `D:/Min/Python/Project/FA_Data/output` 重新執行 promotion evidence preflight；`upstream_data_update_proof_state=ready`、`latest_core_feature_date=2026-08-13`，並由官方日曆自動 catch-up 至 decision=`2026-08-14`、strict T-1=`2026-08-13`。最新 status hash=`sha256:b9065af7a56d5c4c00cd90c121b0505b765e25bd9537bcdb2581a9f317279960`。
- 最新唯一 replay blocker 為 `formal_ooc_dataset_full_market_not_ready:causal_non_cash_portfolio_ledger_present,formal_rule_champion_snapshot_history_present,pit_sector_membership_present`；evidence 未發布、authority 未簽章，`formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false`。這次驗證只更新 fail-closed status，不重跑既有 3,335,023-row OOC，也未改寫正式 SQLite。
- 另以 `scripts/audit_existing_ooc_calibration.py` 對既有 984 個 base OOF artifact 做完整唯讀 hash 重驗與 expanding cross-fitted calibration；audit=`D:/Min/Python/Project/FA_Data/output/scheduled/ml_calibration_audit/latest.json`，最新 audit hash=`sha256:9da29ba447f9e65536bccca18a71971923d3cf36089c0f1078b30620469bb1d5`、file hash=`sha256:adea83d13eb9167de4c0bc2366dc043c6b2202a4055807de4291c6a6fd36bb4e`。結果 `cross_fitted_calibration=true` 但 `quality_pass=false`：最大 ECE=`2,627 bp`、最大 calibrated Brier=`3,175 bp`（threshold=`500 bp`）；每個 horizon 已明列 `5/10/20/60` 日，仍是 shadow diagnostic、未改寫 OOC manifest，`promotion_pass=false`、`production_eligible=false`。
- calibration 另做了唯讀 algorithm scope split：ridge 與 HGB 各 492 個 base OOF experts，在 5／10／20／60 日均 `quality_pass=false`；ridge 最大 ECE=`2,668 bp`、HGB 最大 ECE=`2,683 bp`。這排除了單純跨模型混合造成報告失真的解釋，維持 calibration threshold 與 formal blocker 不變。
- 新增 `scripts/inspect_ml_formal_input_readiness.py` 並以 current Direct `training_as_of=2026-08-13T08:30:00+08:00` 執行唯讀 custody check；readiness=`D:/Min/Python/Project/FA_Data/output/scheduled/ml_formal_input_readiness/latest.json`，logical hash=`sha256:52c5bec669834107e669682965d45f5059620f78e63ec0c3af610c3db965b82b`、file hash=`sha256:aa79419e4be878a7e62d649255ec9c5888e4f4468a7f050a865ae2be4a1ada2e`。三項 input 均為 `missing`，三個 path env 與 Rule HMAC/store id 都未配置；此報告只提供 deposit readiness，不會建立或升格任何研究／candidate 資料。
- readiness inspector 現已與長駐 maintainer 共用 controlled Windows environment handoff；若 owner 在 readiness process 啟動後才完成 deposit，獨立檢查也只會把 path／HMAC／store id 接到當前唯讀 process memory，絕不寫入 artifact、source DB、status 或 log，並維持 formal gate fail-closed。
- 另以目前 `D:/Min/Python/Project/FA_Data_candidate/phase3c_candidate.db` 做 fresh read-only revalidation：`institutional_flows=21,122`（`2026-08-13`）、`credit_transactions=2,212`（`2026-08-13`）、`tdcc_shareholding=4,026`（官方最新週 `2026-08-07`），三個 checkpoint 均 `100.0%`；UI `UpdateService.check_decision_data_status()` 已改用 SQLite `mode=ro`／`PRAGMA query_only=ON`，仍回傳 `formal_records=0` 與候選 disclaimer，不會把 Candidate DB 帶入正式評分或決策。
- formal downstream wiring 也以現有 fixtures 做回歸：OOS replay／promotion pipeline `30 passed`、promotion evidence/reference/validation `53 passed`、copilot／portfolio consumer `31 passed`；三項 formal custody 到位後的本機順序仍是 `build_allocation_oos_replay_inputs()` → primary／verification identical result hash → promotion evidence，未把測試 fixtures 當成正式證據。
- 以目前 immutable Direct identity 實際執行一次 maintainer `_auto_refresh_candidate` read-only dry-run，結果 `candidate_detected=false`、reasons 為空，且沒有 sector／ledger／Rule history candidate；配合 watcher target process=`0`，證明分批或缺件時不會觸發 partial Direct/OOC retrain。
- 本次唯讀盤點發現本機已有 `output/release_v4/ml_research_causal_ledger_full_v4_official_events` 的 causal ledger，但其 latest pointer 與 run manifest 明確標示 `research_only=true`、`formal_consumer_compatible=false`、`promotion_eligible=false`，且 blocker 包含 `research_causal_ledger_not_formal_source`。它只作為排除證據，未寫入 formal path env、未改寫 Direct/OOC、未進入正式 OOS 或 promotion。

## 2026-08-14 Formal continuation watcher custody

- 發現舊長駐 watcher 在 release follow-up 邊界仍把 `output/release_v4` 傳作 operational root；已在 `scripts/continue_ml_direct_v3_refresh_chain.py` 加入 legacy `release_v4` → shared `output` 正規化，並以 `tests/test_ml_direct_chain_maintenance.py`／`tests/test_continue_ml_release_after_ooc.py` focused suite `28 passed` 驗證。既有 raw／Direct／OOC artifact 路徑不變。
- 已先核對並停止五個已確認命令列的舊 watcher／launcher，確認沒有 Direct build、OOC helper 或 release follow-up 執行中，再以 venv 啟動修正版 `baldr-ml-direct-chain-maintainer`。本次 readiness handoff 修正後已再次滾動重啟，目前 lock file owner=`33756`，maintainer 以 `--watch-formal-inputs` 等待；未重跑 Direct／OOC、未寫入正式 SQLite。
- 共享-root promotion preflight 已重新落盤，`upstream_data_update_proof_state=ready`、`status=blocked`，唯一 formal blocker 仍為 `causal_non_cash_portfolio_ledger_present`、`formal_rule_champion_snapshot_history_present`、`pit_sector_membership_present`；`formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false` 維持不變。
- 外部 source audit 已確認 TWSE `TWT58U` 產業分類檔為每日 22:00 產製、資料起始日 `2019-12-23`、按月訂閱；本機沒有授權下載／publication lineage，且它不能覆蓋 current Direct 的 `2014–2026` 全期間。因此未建立 partial sidecar，也未用現行 company registry、產業指數成分或研究 artifact 回填；`pit_sector_membership_present` 維持 blocked。來源契約詳見 `EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md`。
- 進一步官方來源盤點找到較完整的候選組合：TWSE `T97` 每日產業別檔自 `2014-01-06` 起，TPEX `T30` 每日漲跌幅度檔自 `2008-11-01` 起；兩者仍需訂閱／授權與逐檔 publication timestamp、格式版本、SHA-256 及 license lineage。現場沒有任何合法 raw deposit，因此尚未建立 sidecar 或觸發 Direct/OOC refresh；正式 sector blocker 維持不變。
- Ledger／Rule history 也沒有可安全自動推導的替代物：formal loader 需要 append-only causal transition chain、T-1 input state、feature hash，以及 controlled-store HMAC-signed Rule-only snapshots；現有 foreground producer 只會在實際交易時段與明確 confirmation 下產生觀測 artifact，不會由 scheduler 或 paper portfolio 回填正式歷史。另已新增 `scripts/publish_prospective_simulated_portfolio_ledger.py --fixture-only`，可在 activation-bound clock 與合法 SQLite transitions 已存在時產生 prospective wrapper manifest，但不設定 formal path、不改變 `formal_oos_allowed=false`。
- 本次另修正 scheduled wrapper 的長時間 custody 可觀測性：`run_ml_direct_chain_maintenance.py` 改以受監督 child polling 定期重驗 instance lock，並原子更新 `heartbeat_at`、`maintenance_lock_state` 與 `maintenance_owner_process_id`；wrapper 結束時再重驗一次。修正後 focused wrapper QA=`5 passed`、mypy=`0 issues`、`py_compile` 與 `git diff --check` 通過。舊 owner=`26972`、後續舊 owner=`8920` 均已安全停止，現行 watcher lock owner=`33756` 且 status=`running`／`maintenance_lock_state=verified`；target Direct/OOC/release process=`0`，未重訓、未寫入正式 SQLite，三項 formal input 仍待 owner deposit。
- calibration audit 的 horizon report 已補上明確 `horizon_trading_days` 欄位，避免 5／10／20／60 日 metrics 只能靠陣列位置解讀；這只改善 audit observability，不改既有 calibration 數值、training manifest 或任何 gate。
- maintainer 現已補上 Windows controlled environment 的長駐 process handoff：每輪 polling 重新讀取使用者／系統 registry，僅在 process memory 更新 formal ledger path、Rule history path、PIT sector path、HMAC key 與 store id；不寫 secret、不放入 command line／status／log，且 watcher 自己採用的 registry value 移除時會清除 adopted process value。新增回歸後 maintainer／scheduled wrapper focused suite=`25 passed`、mypy=`0 issues`、`py_compile` 通過；仍未有正式三項 deposit，formal gate 狀態不變。

## 2026-08-13 Current Autonomous Chain（live state）

- 最新 immutable raw PIT 已自動更新至 publication=`pit-a2f236fefac769e7346e04be`；publication manifest=`sha256:d02871a55781ed074b0145dffd2d624daf1d3486f99fafc078b0dfc5e1991fe6`、`all_field_enriched` dataset=`sha256:3aa668d542ddd0532563d03dc419f6a25e2afbac7ea08c7863efbb1078472183`、15,938,679 rows、52 features、decision_at=`2026-08-13T08:30:00+08:00`。raw publication 由 SQLite `ro/query_only` 建立，沒有寫回來源 DB。
- Direct run=`direct-ooc-6ff7650245ffea99ced5bf21` 已於 `2026-08-13T21:05:01Z` 完成 2014–2026；checkpoint、13 個年度 manifest/carry、41 個 fold index 與 canonical pointer 均已通過，`latest_manifest.json` 已原子切換且與 run manifest 完全一致。Direct manifest=`sha256:b52b1211e8bc61c591b0eb4b83ba2877701f7ca4fb1fbd4dff891e57b660d676`、3,335,023 rows、62 features、41 folds，peak temporary bytes=`24,522,523,967`。
- 新 Direct safety 已重驗：`source_shards_hash_verified=true`、`t_minus_1_contract_revalidated_per_row=true`、`pit_contract_revalidated_per_row=true`、`post_event_corporate_action_used_as_feature=false`、`trade_restriction_unknown_row_count=0`、purge=`60`／embargo=`5` trading days；正式 blocker 仍為 `causal_non_cash_portfolio_ledger_present`、`formal_rule_champion_snapshot_history_present`、`pit_sector_membership_present`，因此 `promotion_eligible=false`、`formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false`。
- OOC 已由既有 helper 自動接續並完成：run=`allocation-ooc-9750e409b0622fb4472a1a0f`、manifest=`sha256:9faa8ec2d873d2b46efc23c8dbc42cfeb555bd1d9eeb8697ab24c7aa2d07c498`，3,335,023 rows／62 features／41 outer folds／40 meta folds／984 base experts／24 final experts；`store_manifest_hash=sha256:b52b1211e8bc61c591b0eb4b83ba2877701f7ca4fb1fbd4dff891e57b660d676`，latest pointer 已原子切換。`future_prefix_violation_count=0`、`pit_violation_count=0`、`constraint_violation_count=0`、purge=`60`／embargo=`5`、peak RSS=`3,451 MB`／budget=`4,096 MB`、`within_memory_budget=true`。
- 新 OOC 的 calibration 為 Brier=`2,315 bp`、ECE=`187 bp`（門檻 `500 bp`），但仍是 `measured_uncalibrated_oof`、非 cross-fitted；正式 portfolio ledger 缺件也使 `rebalance_worthwhile` final head 沒有正例。因此這次代表可重現訓練與安全驗證完成，不代表模型已具生產 alpha；`promotion_eligible=false`、`formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false`。
- 上一輪對應的 Direct run=`direct-ooc-09dabea3b84115b2d5e4b753` 與 OOC run=`allocation-ooc-2416e7265c6f3c15072173c6` 已完成且安全切換；OOC manifest=`sha256:57a5dbcf68c499697c6cb8205863ff891ca5079104e7b9fa4fa35e8f779e8d42`，41 outer folds／40 meta folds／3,333,845 rows，`store_manifest_hash` 綁定 Direct=`sha256:0eacf05adc856e51d63d8f59bd31a60bf0b8b18cff5fcd1a5b040e483947621d`。`future_prefix_violation_count=0`、`pit_violation_count=0`、`constraint_violation_count=0`、峰值 RSS=`3,566 MB`／budget=`4,096 MB`，`within_memory_budget=true`。
- 本輪發現並自動修復 maintenance supervisor 被 Windows 中止後留下 dead-owner lock 的營運狀態：既有子程序未被碰觸，watchdog 重新取得 lock 後繼續監督；`baldr-ml-direct-chain-maintainer` 重新 query 為 `Last Result=0`，status 明列 `execution_disposition=existing_owner_lock`、`maintenance_lock_state=verified`、owner PID=`14508`，未產生平行 chain。新增 dead-owner lock regression test。
- Release follow-up 曾因 Direct/OOC chain 將 `output/release_v4` 誤當共同 `output` root，使 upstream quick-update proof 被查到不存在的巢狀路徑；coordinator 已依 training custody 正規化 operational root，並固定傳入 `--auto-catch-up`。重跑後 proof=`ready`、latest core feature date=`2026-08-13`，真正 replay blockers 回到 `causal_non_cash_portfolio_ledger_present`、`formal_rule_champion_snapshot_history_present`、`pit_sector_membership_present`；沒有以 current company registry、cash-only ledger 或 research artifact 代替正式來源。
- 正式 SQLite `D:/Min/Python/Project/FA_Data/sqlite/twstock.db` 已以 query-only 驗證 `PRAGMA quick_check=ok`，不是 lock／WAL 卡住。Phase 3C 缺日期的根因是未設定 Candidate DB、正式 acceptance gate 保持關閉，以及 TPEX 現行 24／15 欄 schema 漂移；解析器已修正並 fail-closed 驗證回應日期，隔離 Candidate DB 已重建切換，舊庫保留為 `phase3c_candidate_pre_schema_fix_20260813_1747.db`。目前三大法人=`2026-08-13`（21,122 rows）、信用交易=`2026-08-13`（2,212 rows）、TDCC 官方最新週=`2026-08-07`（4,026 rows），三者 checkpoint coverage=`100%`；Candidate 資料不參與評分或正式決策。
- App 中斷排查的較新 WER archive evidence 顯示歷史 `python.exe`／`Qt6Core.dll` BEX64 crash（詳見上方 2026-08-14 follow-up），但沒有 command line 或 dump 可定出唯一根因；近期 `rg.exe` 與 `RemoteMouseCore.exe` 事件已排除為本 App。UI 已移除強制 `QThread.terminate()` 路徑、改為合作式取消與安全關閉阻擋，新增 `DATA_ROOT/logs/ui_qt_crash.log` 的 native／main-thread／worker 持久診斷；FileHandler 權限／鎖定失敗改為 console-only。真實 MainWindow smoke 與 Update bridge healthcheck 均通過。
- 本輪 QA 基準已更新為 inventory=`595/595`、`3186 collected`、`0` collection／machine blockers；補登 4 個既有 formal ML／portfolio 測試檔並加入 entrypoint encoding regression 後，完整 pytest=`3185 passed, 1 skipped, 24 warnings`。Update Workbench=`39 passed`、Update Tab QA=`23 passed / 0 failed / 4 skipped`，受影響 mypy／py_compile 均為 0 issues。Warnings 僅為既有 recommendation backtest 的研究假設提示。

## 2026-08-12 Current Autonomous v4 Refresh（新的 Direct → OOC 執行中、下游證據仍 fail-closed）

### 2026-08-12 自動 bootstrap 與 live chain 現況

- 最新 immutable raw PIT publication 已由自動 refresh 完成：publication=`pit-29505ceb0005d068610dde01`、top-level manifest=`sha256:4639ab78282cd85016064bd6f7397874ac00965665a2f9b9b0761e76f1824406`、`all_field_enriched` dataset=`sha256:90ea99f71d689060123c187bba8db5335d6aa106620f130d325e2a3dbbcc04d3`、15,932,713 rows、52 features、13 shards、decision_at=`2026-08-12T08:30:00+08:00`。raw safety 與 all-universe scope 已重驗，來源 SQLite 維持 `ro/query_only`。
- 已新增 `scripts\scheduled\run_ml_direct_chain_maintenance.py`／同名 `.cmd`，每日自動解析並重驗最新 raw pointer、dataset canonical hash、`all_universe=true`、official market-event custody 與 Direct identity，再啟動既有 `maintain_ml_direct_v3_refresh_chain.py --watch-formal-inputs`。wrapper 不建 raw、不寫來源 DB、不建立未受控 sector sidecar；輸入不合法只寫 `blocked_invalid_bootstrap_input`，不猜測續跑。
- Windows Scheduler 已實際註冊 `baldr-ml-direct-chain-maintainer`（每日 05:30）；唯讀 query 已確認 13/13 tasks 為 `Enabled`／`Ready`，新 task 實際觸發 `Last Result=0`。bootstrap status 位於 `D:\Min\Python\Project\FA_Data\output\scheduled\ml_direct_chain_maintenance\latest_status.json`，最近一次 status=`completed`、returncode=`0`；`Logon Mode=Interactive only` 的限制仍保留。
- 目前新的 Direct run=`direct-ooc-09dabea3b84115b2d5e4b753`，綁定 raw dataset hash=`sha256:90ea99f71d689060123c187bba8db5335d6aa106620f130d325e2a3dbbcc04d3`。最新觀測 heartbeat 已完成 2023 label spool、進入年度 assembly（`year_labels_complete`），`completed_years=[2014,2015,2016,2017,2018,2019,2020,2021,2022]`、`current_year=2023`；checkpoint 仍為 `complete=false`。這是實際進度，不把 processed rows 或 heartbeat 當成完成證明。
- OOC helper 狀態為 `waiting_for_direct_store`，release follow-up 狀態為 `waiting_for_ooc_helper`；兩者都由既有 supervisor 持續監看，沒有重複啟動或人工續接。Direct 完成後會自動進行 custody 驗證、OOC 訓練與下游 follow-up。
- readiness 仍 fail-closed，blockers=`causal_non_cash_portfolio_ledger_present`、`formal_rule_champion_snapshot_history_present`、`pit_sector_membership_present`；正式狀態固定為 `formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false`，未把現行 company registry、cash-only ledger 或研究 artifact 冒充正式來源。
- QA 已完成本輪完整驗證：inventory=`589/589`、`3139 collected`、`0` collection／machine blockers；完整 pytest=`3138 passed, 1 skipped, 24 warnings`，scheduled／Direct chain focused suite=`47 passed`，stale-lock regression=`14 passed`，wrapper／maintainer `py_compile` 與 mypy 均為 0 issues。Warnings 僅為既有 recommendation backtest 的研究假設提示。

## 2026-08-12 Previous Autonomous v4 Refresh（歷史完成 custody，非目前 live run）

### 2026-08-12 自動 raw PIT refresh handoff（歷史紀錄）

- 已補上 `scripts\scheduled\run_ml_raw_pit_refresh.py` 與同名 `.cmd` wrapper：它只在 `data_update_quick` terminal status 證明 daily／technical core date 就緒時，以 SQLite `ro/query_only` 建立全市場 immutable raw PIT；既有合法 cutoff 會自動跳過，失敗或上游未就緒只寫機器狀態，不刪除舊 publication、不改正式 gate。
- 新增 Windows task `baldr-ml-raw-pit-refresh-daily`，排程為每日 05:05；本機唯讀 query 已確認 12/12 tasks 為 `Enabled`／`Ready`，`Logon Mode=Interactive only` 的限制仍保留。首次針對 core date `2026-08-12` 的 refresh 已由背景 builder 執行，完成前 latest raw pointer 保持 `pit-edfff7906a0c27861b602ef0`（decision `2026-08-11T08:30:00+08:00`）。
- refresh 完成後，`maintain_ml_direct_v3_refresh_chain.py --watch-formal-inputs` 會依 pointer、canonical hash、dataset safety 與 training identity 自動判斷是否重建 Direct/OOC；正式 custody 不完整時仍固定 `formal_oos_allowed=false`、alpha=`0`、`broker_order_allowed=false`。
- 首次自動 refresh 已完成並通過驗證：publication=`pit-29505ceb0005d068610dde01`、top-level manifest=`sha256:4639ab78282cd85016064bd6f7397874ac00965665a2f9b9b0761e76f1824406`、`all_field_enriched` dataset=`sha256:90ea99f71d689060123c187bba8db5335d6aa106620f130d325e2a3dbbcc04d3`、15,932,713 rows、52 features、13 shards；raw safety `formal_dataset=true`、`raw_float_persistence_allowed=false`，且 staging 已清空。
- handoff 中發現並修正 `sector_membership_file_hash=null` 被誤轉成字串 "None" 的 watcher bug；修正後 raw-only candidate 已自動啟動 Direct run=`direct-ooc-09dabea3b84115b2d5e4b753`，heartbeat 目前在 discovery，OOC helper 受控等待。未建立或採用未受控 sector sidecar，既有三項 formal blocker 與 alpha=0 不變。

- 最新 immutable raw PIT dataset 為 `ml-pit-year-shard-dataset.v1`：dataset manifest=`sha256:739026b63bfd5a7780baa1714ebd53a5cc5662ef620518ebe3f0b024df2d98e6`、manifest file=`sha256:7d99b826d7599eeb96993de5acb9964c128a53492a0bc90f18ee56197d545bb7`、decision_at=`2026-08-11T08:30:00+08:00`、15,926,733 rows、52 features。官方 market-event custody manifest=`sha256:c7634707cd00a0e4796c18a8b9b57837e0cfbb05da07b54b4856df8351621b4f`，file=`sha256:dc0cfcb60a0582c58c9bb458048f231dc5e73699fb84d70d39502d586b9852ea`。
- 新版 immutable direct numeric v4 已完成：run=`direct-ooc-94355ffac5a541dbd9cb7282`、canonical manifest=`sha256:0bd97a301a1367ca3a8378cb45c4c9250eebc0dd6e49ced7c313ec39ad655639`、2014–2026 13 個年度、3,332,662 rows、62 features、41 folds。checkpoint、年度 artifact／carry hash、fold index 與 raw／official-event custody 均已驗證；`latest_manifest.json` 已原子切換至此 run。
- Direct manifest 的執行安全欄位為 `direct_store_complete=true`、`annual_atomic_checkpoint=true`、`memory_budget_enforced=true`、`peak_rss_bytes=327708672`、`source_shards_hash_verified=true`、`t_minus_1_contract_revalidated_per_row=true`；label 產生未使用 teacher target，post-event corporate action 不作為 feature。
- OOC 已由既有 helper 自動接續新 Direct run 並完成：run=`allocation-ooc-05fd4dd6515cddfdf6e0228d`、training manifest=`sha256:07cf93b6f707641e37fce791603f354f20099132df004a93099faec388feefe2`、41 outer folds、40 meta folds、984 base experts、3,332,662 rows；`store_manifest_hash` 綁定新 Direct canonical manifest，OOC pointer 已原子切換，舊 run 與歷史輸出保留不動。
- OOC 執行安全與 look-ahead 驗證已完成：`memory_budget_mb=4096`、`peak_rss_bytes=3740839936`、`within_memory_budget=true`、`future_prefix_violation_count=0`、`pit_violation_count=0`、`constraint_violation_count=0`；但 replay／formal promotion 仍不允許，未啟用任何 production alpha。
- 本次 chain 同時由 `scripts\maintain_ml_direct_v3_refresh_chain.py` 監督；它以完整命令列、同一 run identity、checkpoint／hash custody 與 instance lock 自動防重複並在 Windows worker／supervisor 中斷後恢復，不直接寫 SQLite、不手動發布 pointer。
- readiness 仍 fail-closed，blockers=`causal_non_cash_portfolio_ledger_present`、`formal_rule_champion_snapshot_history_present`、`pit_sector_membership_present`；沒有把 cash-only fallback 偽裝成非現金 ledger，也沒有用 current company registry 回填歷史 PIT sector。正式狀態固定為 `formal_oos_allowed=false`、alpha=`0`、`broker_order_allowed=false`。
- chain follow-up 的 evidence、authority、daily orchestration 命令均正常返回；本次自動執行 data-update quick 已將正式 core feature date 推進至 `2026-08-12`，strict T-1 已 ready。Evidence 現在只因 `formal_ooc_dataset_full_market_not_ready:causal_non_cash_portfolio_ledger_present,formal_rule_champion_snapshot_history_present,pit_sector_membership_present` blocked，authority=`skipped_evidence_unavailable`，daily consumer=`passed_rule_only`／`insufficient_evidence`，未發布 compatible promotion evidence、未建立授權、未啟用交易。

## 2026-08-12 Previous OOC / Promotion Closeout（歷史紀錄，已由上方 v4 refresh 取代）

- 本輪 immutable direct numeric v4 已完成：run=`direct-ooc-73f491054fdfac318cb5c1f2`、manifest=`sha256:48859425625266092b2ab70447982bfd1362615a7a1307a043b8cda32935b61d`、2014–2026、62 features、3,299,839 rows；direct heartbeat／checkpoint／年度 artifact 與 fold custody 已驗證。
- OOC 已從既有 direct store 證據自動續接並完成：run=`allocation-ooc-99c60a4209d58e58bc28bc48`、training manifest=`sha256:e425a466e0cec3e5280e553f0b330f6e2dc071f68cbba66400f9de556b42a528`、41 folds、40 meta folds、984 base experts、final meta 已發布；final meta 使用 bounded streaming，未建立完整 wide dense matrix。
- OOC replay-input build 已完成 hash-bound 嘗試，但依 readiness fail-closed，blockers=`causal_non_cash_portfolio_ledger_present`、`formal_rule_champion_snapshot_history_present`、`pit_sector_membership_present`；沒有讀取 teacher target，也沒有把 cash-only fallback 偽裝成非現金 ledger。
- Windows status-file `os.replace` transient lock 已在 OOC、release、promotion 與 continuation orchestrator 全部加入 bounded retry；另加入 `--resume-after-direct-store`，可在 direct PID 已退出但 immutable store 已完成時安全續接，不捏造 live PID custody。
- Promotion evidence gate 已修正：若 official market-event publication 只重新發布相同 `canonical_events_hash`，只變更 wrapper manifest／duplicate metadata，不再要求重建整個 direct store；canonical timeline hash 改變仍會輸出 `formal_ooc_corporate_action_custody_stale` 並阻擋。此修正已通過 promotion pipeline `8 passed`、py_compile 與 mypy。
- 本輪 follow-up 已依序執行 evidence、authority、daily orchestration；evidence 的實際 blocker 已收斂為上述三項 readiness gate，authority=`skipped_evidence_unavailable`，daily consumer 保持 `formal_oos_allowed=false`、alpha=`0`、broker=`false`。因原先在台北 08:30 後執行而落到尚未收盤的 2026-08-13 窗口，已自動 catch-up 2026-08-12 08:30：T-1=`2026-08-11`、raw PIT／post-freeze／inference／shadow observation 全部完成，`shadow_day_credit_allowed=false`，沒有補值或使用未完成交易日資料。
- remaining source audit：institutional／credit／TDCC candidate 均為 `source_not_ingested`；現有當期 company registry、research causal ledger、current snapshot 與 scheduled shadow artifact 均不得替代歷史 PIT sector membership、因果非現金 ledger 或正式 Rule Champion snapshot history。官方 TWSE「證券及產業別對照表」頁面已確認商品 `TWT58U` 每日 22:00 產製、資料起始日為 `2019-12-23`，且需訂購；它仍無法單獨覆蓋 direct store 的 2014–2019 缺口。現有環境沒有已授權下載與 publication lineage，因此不自動把它升格成 formal sidecar。正式 gate 維持關閉，等待可驗證 source/publication lineage 或自然累積的正式 evidence。

### 2026-08-12 Current Scheduler Revalidation

- promotion evidence 排程已同步自動選日：唯讀使用 `data_update_quick` 的 `check_overview_after` core-date proof；若下一個決策日的 strict T-1 尚未到位，最多向後掃描 31 個曆日並保存 `requested_decision_at`、`decision_selection_mode`、attempts 與 `latest_core_feature_date`。本次自動 data-update quick 已成功完成，core date=`2026-08-12`，因此 requested=`2026-08-13`、strict T-1=`2026-08-12` 維持 requested mode；formal OOC blockers 仍維持 blocked／alpha=0。Evidence status 已升級為 schema v3；upstream status 遺失、failed、破損或未來日期會在選日前直接 fail-closed，並記錄 `upstream_data_update_proof_state` / `upstream_data_update_proof_reason`。

- 本次 daily allocation orchestration 已完成 post-freeze input、inference 與 shadow observation（revision=`2`），但因 compatible promotion evidence 不存在保持 `operation_mode=rule_only`、`selected_alpha_bp=0`、`production_action_allowed=false`；shadow evidence 仍為 `insufficient_evidence`，沒有寫入 source database。

- allocation copilot 排程已加入 --auto-catch-up：只有下一個候選日是未來日且完整 orchestration 實際證明該日 strict T-1 尚未完成時，才會依 hash-bound raw publication／post-freeze proof 向後重試最近已過交易日；資料庫／日曆未知、明確指定決策日或非 T-1 問題均維持原有 fail-closed。

- `scripts\\scheduled\\query_baldr_scheduled_tasks.cmd` 已重新唯讀查詢：12/12 個每日／週期 task 均為 `Enabled`、`Ready`；ML promotion evidence、authority、allocation copilot、raw PIT refresh 與資料更新鏈均已註冊。
- 目前 task 的 `Logon Mode` 仍為 `Interactive only`，因此這只證明目前互動式帳號下的排程註冊與最近成功結果，不宣稱已完成無人登入執行；沒有擅自變更帳號、憑證或電源政策。
- 最新 deterministic test inventory audit：`588` filesystem test files／`588` inventory entries／`3,135` collected tests，`0` machine-checkable blockers；另有 3 組精確重複測試函式被列為非阻塞診斷，未被靜默忽略。

## 2026-08-11 Autonomous Continuation Audit

- 最新自動續接狀態：上一輪 recovery chain 已在 `direct-ooc-73f491054fdfac318cb5c1f2` 的 `year=2024` raw spool 期間因 Windows `PermissionError` 原子替換 heartbeat 退出；checkpoint 仍完整保存 2014–2023，沒有年度資料被刪除或回退。direct store 已補上短暫檔案鎖定的 bounded atomic-replace retry，下一輪會直接從既有 checkpoint 續跑；相關 OOC／release helper 維持等待，不會沿用 stale blocked 狀態。
- OOC trainer 的 final meta 現在逐 prior fold／batch 串流讀取 OOF，median 只取 deterministic bounded sample，mean／variance、Gram 與 logistic IRLS 均重複掃描 bounded batches，不再配置完整 wide `train.meta.f32`；pipeline QA `21 passed`、mypy `0 issues`。
- 目前新的 checkpoint-resume chain 已通過 custody 啟動：supervisor launcher PID `5504`、direct launcher PID `32056`、direct worker PID `32060`、OOC helper PID `32092`、release helper PID `32112`；direct 正在全量 discovery，heartbeat `run_initialized`、checkpoint 仍保存 2014–2023，OOC／release 狀態分別為 `waiting_for_direct_store`／`waiting_for_ooc_helper`。所有 gate 仍維持 `formal_oos_allowed=false`、alpha=0、broker=false。
- 後續 direct build 已補上 discovery heartbeat：每個 raw shard 在 hash／row／feature custody 掃描期間會按 100,000 rows 或 30 秒沉默上限發布 `discovery_source_shard_<year>_rows_<n>_processed`，完成後發布對應 `_complete`；這只增加可觀測性，不改變 checkpoint、manifest 或 fail-closed 完成權威。
- Direct discovery 成功後會寫入 hash-bound `discovery_cache.json`；後續 resume 會重驗 raw manifest identity 與每個 compressed shard hash 才重用 feature registry／calendar／fold／source digest，任何不一致都回到完整 fail-closed scan。focused cache regression `1 passed`、mypy `0 issues`。

- 最新 live custody：`direct-ooc-73f491054fdfac318cb5c1f2` 的 checkpoint 已安全保存 2014–2023；2023 `row_count=218198`、`feature_values_shape=[218198,62]`、`teacher_incomplete_decision_count=0`、`trade_restriction_unknown_row_count=0`，年度 artifact／manifest／carry hash 全部通過；direct heartbeat 目前為 `building_year`、`current_year=2024`、`year_ordinal=10`、`pid=3164`，OOC／release helper 仍受監督等待 direct 完成。這代表年度 checkpoint／hash-bound custody 已持續前進，不代表整個 direct store、OOC 或 promotion 已完成；`formal_oos_allowed=false`、alpha=0、broker=false 維持不變。

- 產業 PIT sidecar 來源稽核已完成：raw PIT shards 與正式 SQLite 都沒有歷史公司產業歸屬表；現行 `companies.csv` 只能代表當期 registry，不得回填 2014–2026。TWSE 公開的現行基本資料與每日歷史「證券及產業別對照表」是不同來源；官方 Data E-Shop 的 TWT58U 說明顯示該日檔自 2019-12-23 起、每日 22:00 產製，提供 TEXT／CSV，但屬訂閱商品，現有環境沒有已驗證的授權／下載 publication lineage。因此 `pit_sector_membership_present` 仍 fail-closed，不建立偽造 sidecar（來源：[TWSE 證券及產業別對照表](https://eshop.twse.com.tw/zh/product/detail/000000006e0bbe8d016f18269c59032c)）。
- supervisor operational log 已補上可寫路徑路由：自訂 `--status-path` 時，direct／OOC／release log 會寫到 heartbeat 同層，避免資料目錄 log 權限阻斷自動續接；正式資料、manifest 與 fail-closed gate 不受影響。相關 focused QA `10 passed`、mypy `0 issues`。
- release follow-up 已改為逐命令受監督子程序，會持續發布目前命令、PID、序號與 return code heartbeat；focused QA `6 passed`、mypy `0 issues`，不會因此放寬 promotion 或 broker gate。
- OOC handoff 現在會先發布 `store_custody_validation_starting`，再於訓練前自動重驗 direct canonical manifest、complete checkpoint、每個年度 artifact／carry hash 與 fold index；任一 custody 不一致即 fail-closed。相關 focused QA `7 passed`、mypy `0 issues`。
- OOC trainer 已補上 bounded final-meta streaming：deterministic causal row sample 只用於 median，mean／variance 仍掃完整 train stream，wide memmap 以短生命週期 mapping 讀寫；OOC pipeline QA `20 passed`、mypy `0 issues`。
- 本輪已修正 `continue_ml_direct_v3_refresh_chain.py` 的 legacy PID sequential-wait race 與失敗後 orphan child 清理：正常模式會先一次驗證 direct／OOC／release 三個命令列，另提供 fail-closed 的 `--resume-after-legacy-chain` 恢復入口；focused continuation QA `11 passed`、mypy `0 issues`。舊鏈與孤兒 helper 已清理，新的 recovery chain 以 process custody 與 checkpoint 為準。

> 歷史註記：本段原先記錄的「11/11 個 Windows tasks 均未註冊」已被上方 2026-08-12 current revalidation 取代；下方 2026-07-30 的「Production Scheduler 實證」仍只代表當時證據，不取代目前的唯讀 Scheduler query。`production_scheduler_allowed=false` 仍維持，不能把已保存的 scheduled status artifact 單獨當成 Windows Scheduler 已啟動的證明。

- 官方 market-event publication 已由排程 wrapper 自動 recovery 至 2014–2026，canonical events=`28,464`，`active_sqlite_written=false`、`manual_prompt_required=false`。
- 官方 company registry updater 已完成 JSON→官方 CSV fallback；2026-08-11 dry-run／apply 均為 `2,343 rows`、`0 diagnostics`，正式 `companies.csv` 已先備份至 `companies_company_registry_20260811_081412.csv`。這只更新當期 registry，不把它當成歷史 PIT sector membership。
- ML OOC training custody 已存在但 promotion 仍 fail-closed；目前正式 readiness blocker 為 `causal_non_cash_portfolio_ledger_present`、`pit_sector_membership_present` 與 `formal_rule_champion_snapshot_history_present`。官方 halt/resume timeline 已在 direct numeric v4 實作逐 row as-of 綁定；新的 direct run `direct-ooc-73f491054fdfac318cb5c1f2` 已由年度驗證與 checkpoint/hash custody 保存 2014–2023，目前正在建置 `year=2024`，OOC／release helper 正等待整個 direct store 完成。研究 causal ledger 與 current company snapshot 不得轉作正式來源。
- 既有 legacy direct numeric v2 checkpoint 已完成 2014–2026，但其 pointer 仍不是目前 direct builder v4 contract；舊 OOC 產物只留存供審計，current continuation 不會採用，完成前不得宣稱 v4 direct／OOC custody 已一致，alpha 維持 0。
- Direct run 另會在 `runs/<run_id>/heartbeat.json` 原子發布目前 stage、PID、已完成年度與 UTC `updated_at`；OOC continuation 等待時只會鏡像 PID 與受監督 direct process 相符的最新有效 heartbeat，進入長時間訓練後則以 `portfolio-ml-ooc-heartbeat.v1` 的 `training_running` 狀態持續發布 OOC process custody 與 store manifest hash。兩種 heartbeat 僅供長時間重建觀測，完成仍以 checkpoint、年度 manifest 與 hash-bound `latest_manifest.json` 為準。
- 後續 direct numeric build 會在每個來源 shard 至少每驗證 100,000 筆，或連續 30 秒沒有進度事件時，發布 `raw_spool_source_shard_<year>_rows_<n>_processed`，完成 shard 後再發布 `raw_spool_source_shard_<year>_complete`、`year_raw_spool_complete` 與 `year_labels_complete`；label spool 會先發布 `label_spool_starting_<symbols>_symbols_<dates>_dates`，在單一 symbol 長時間計算時以 30 秒節奏發布 `label_spool_symbol_<n>_of_<total>_decision_<n>_of_<total>_processed`，並在 symbol 邊界發布 `label_spool_symbols_<n>_of_<total>_processed` 與 `label_spool_complete`；年度 assembly 期間會在每個 sample row 內以相同列數／時間節奏發布 `assembly_decision_<date>_rows_<n>_processed`，因此單一大型 decision date 也不會讓 heartbeat 長時間沉默，接著是 `year_assembly_complete`、`year_artifacts_complete` 與 `year_directory_finalized`；`processed` 只反映真實讀取或組裝進度，不會被當成完成或 checkpoint。
- OOC heartbeat custody 已補上 Windows venv launcher／worker PID 邊界：只有 heartbeat PID 等於受監督 launcher，或仍存活且位於 launcher 子孫鏈，才會被 continuation 鏡像；stale／unrelated PID 會被忽略。focused QA `6 passed`、mypy `0 issues`。
- Annual raw spool 於 source-shard 邊界提交，降低長交易的 I/O／恢復成本；這只影響 ephemeral work SQLite，年度目錄仍須完成 hash、checkpoint 與 latest-pointer 驗證後才可發布。
- 目前受控 recovery chain 已啟動 direct PID `12060`、OOC PID `28008` 與 release PID `27472`；最新檢查時 direct heartbeat 為 `building_year/running`、`completed_years=[2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023]`、`current_year=2024`，已進入第十一年度實際建置，OOC／release 分別等待 direct／OOC 完成。v3 supervisor 以 `portfolio-ml-direct-v3-refresh-chain-heartbeat.v1` 原子鏡像受監督 PID、命令列與等待階段，release helper 則以 `portfolio-ml-release-followup-heartbeat.v1` 鏡像 OOC helper custody，並在後續 follow-up 命令執行時發布逐命令 heartbeat，避免長時間狀態無法區分健康等待與失聯。三者只會執行既有 fail-closed 命令並保存結果，不會啟用 alpha、下單或寫入正式 SQLite。
- `continue_ml_direct_ooc_after_store.py` 現在啟動等待時先寫入 `continuation_status.json` 的 `waiting_for_direct_store`，避免沿用歷史 `blocked` 造成誤判；完成或失敗才寫入 terminal 狀態，相關測試與 inventory audit 已通過。

## 2026-08-06 Owner Production Readiness

- Legacy direct manifest 若沒有 PIT sector sidecar 而以 `null` 記錄，schema refresh 會自動正規化為「無 sidecar」並繼續發布 immutable v4；`pit_sector_membership_present` 仍維持 readiness blocker，不會因此放寬 formal replay、alpha 或 broker gate。

> **最新可操作狀態**：Owner 可日常使用 Rule 驅動 Decision／Advice、推薦、日常資料更新、Paper Portfolio、證據保存與 Runtime 只讀監控；不連接券商。正式 DB `quick_check=ok`，核心市場表截至 2026-08-06 可讀；本輪 raw／SQLite／PIT 對帳後，沒有可無歧義安全新增至正式 DB 的剩餘 records。缺口是來源 acceptance／PIT／provenance，不是未匯入檔案數量。

- Runtime UI 已改為「日常營運 artifact」與「治理 Runtime」雙平面，核心 scheduled artifact 實測 `6/6` 正常；`evidence degraded`、ML `blocked`／`passed_rule_only` 以 guarded 顯示，不能當 promotion。Scheduler 真實 registered／running／`Last Result` 仍只能用專用 query script 判定。
- UI 的受管背景工作改為非阻塞合作式取消：若資料更新、推薦／回測匯出、每日決策或主力流向仍在執行，關閉視窗會暫停，直到 worker／TPEX 子程序自然結束；不得以 `QThread.terminate()` 截斷 SQLite 或檔案操作。
- ML 仍固定 `production_blend_alpha_bp=0`、`formal_oos_allowed=false`。2026-08-07 已在同一 custody 下完成 OOC v5 resume，並原子發布 `latest_manifest.json`（120 base、24 final-base、4 meta、1 final-meta；manifest=`sha256:312df8744b81e8cadb3bc8c06b57dc416fd055ee5de9a081faf00e94ae1f3d0b`）。最新 promotion evidence 仍以 `formal_ooc_dataset_full_market_not_ready` fail-closed；不得手動 promotion 或以完成訓練誤稱為可用 alpha。
- 本輪 QA：Runtime core focused `26 passed`、Full App Healthcheck（full）11 個 bridge suites／`120 passed`、UpdateView `38 passed`、Update Tab QA `23/0/4`、月營收／季報 provenance `122 passed, 1 skipped`、月營收 live read gate `29 passed`、OOC pipeline `19 passed`、UI 合作式關閉與相鄰 UI `43 passed`、mypy `478 source files / 0 issues`、test inventory `582/582/3,051` 且 0 machine blockers、MainWindow 8 workspace offscreen smoke 通過。完整 pytest 因 process 使本機 commit 接近上限而為保護正式環境中止，須在資源充足環境補跑。
- 完整表格、邊界與 Owner 操作順序見 [OWNER_PRODUCTION_READINESS_2026_08_06.md](../06_qa/OWNER_PRODUCTION_READINESS_2026_08_06.md)；逐來源正式 DB 對帳與禁止捷徑見 [FORMAL_DATA_RECONCILIATION_2026_08_06.md](../06_qa/FORMAL_DATA_RECONCILIATION_2026_08_06.md)。

## 2026 年 7 月 Gate Review（Terra Forward Clock）

> **補登時間：2026-08-01 23:34 America/Los_Angeles**。本節只結算 `terra-forward-clock-12` 的 Development clock 與 Formal evidence clock，不改寫本頁其他 scoped 現況，也不把 repository scheduler／production sidecar 的執行次數轉成此 Formal clock 的 elapsed days 或 evidence credit。

- **Maturity**：Development 在 7 月完成兩個真實、bounded、research-only MOPS numeric PIT candidates（2330／2317，皆為 2025 Q1）；截至月末合計 2 symbols、230 matching decision rows、76 PIT-eligible rows，占 canonical 179,271 rows 的 4 bp。DEV-71 parent 仍未完成 feature materialization，且不具 training、source acceptance 或 Formal 資格。Formal clock 在 7 月新增 snapshot=`0`、outcome revision=`0`、matured denominator=`0`、formal credit=`0`；既有 1 筆 shadow `manual_observed` 不納入 Formal。
- **Source incidents**：2317 capture 首次查詢遇到 `doc.twse.com.tw` 暫時 DNS 解析失敗；staging 已清理且未發布半套 artifact，唯讀 DNS 恢復後的一次重試成功。MOPS numeric／listing SHA-256 lineage 均通過；未發生正式 DB、registry 或 prior TEMP artifact mutation。numeric feature 的具名 source owner／reviewer acceptance 仍未建立。
- **Drift**：Rule-only formal path 未變；`formal_oos_allowed=false`、`formal_evidence_credit_authorized=false`、`production_blend_alpha_bp=0`。7 月沒有自然成熟 outcome、沒有合法 promotion input，也沒有 training／retraining／promotion／unblind／blend。
- **Open blockers**：缺少綁定 2026-07-29 session 的真實 decision-time Rule-only `manual_observed` artifact；DEV-71 coverage 僅 4 bp；numeric source owner／reviewer acceptance 缺失。Formal Week 3（2026-07-27 至 2026-08-02）在 7 月月末尚未自然結束，週報只可於週期結束後 append。

> **V4.0 Operational Production 收尾（2026-07-30）**：決策、結構化 Advice、Rule 配置、風控投影、Daily Decision Desk、Evidence Capture 與 append-only Paper Portfolio 已可日常運作；券商送單仍明確不存在。ML 已改為「全欄位 PIT feature packs → base experts → OOF Meta Allocator → 整數 bp 權重提案 → Rule/ML 同單位混合 → deterministic risk projection」的 Production Co-pilot。`0 / 2000 / 3500 / 5000 bp` 四條 lane、逐 horizon frozen calibration/PSI reference、unsigned Evidence Builder、獨立 DPAPI Authority 與每日 consumer 重驗均已接通；最新 reference hash=`sha256:8ee81ae9c5691c6e10d95f14eac293b2ecd121a53877f0d0de73e20b514dd5b0`，outcome contract hash=`sha256:95172f7d8678fd6ecde83c1c166b56878b0d3b769750290acb5b0b3753c96a11`。目前機器 blockers 是全市場 formal OOC publication 尚在建立、Formal replay 尚未由獨立 verifier 從官方交易日曆／production Rule Champion／完整六頭 Meta OOF 重建，以及 5／10／20／60 日各 `0/20` 個可計入 promotion 的成熟 shadow 決策日；真實狀態因此仍為 `production_blend_alpha_bp=0`、`formal_oos_allowed=false`，ECE／兩種 Brier／PSI 與成本後 lane 結果均為 **`NOT EVALUATED`**，不得填 0 或人工硬改。

> **全欄位治理現況（2026-07-30 08:30 Asia/Taipei freeze）**：正式 SQLite 共 22 tables／408 columns，所有欄位均有 disposition；11 張 ML source tables 的 `unreviewed=0`，其餘 operational/evidence 欄位 fail closed。檔案型 raw/sidecar inventory 掃描 34,970 個候選檔、去重為 313 sources／9,619 fields，disposition coverage `10,000 bp`、未處置 0。全市場 immutable raw PIT publication=`pit-4a860a5fa18add4e0e15f2aa`，共 34,447,843 raw rows／28 年度 shards；`all_field_enriched` 有 15,876,434 rows、52 formal features、214,058,770 feature values（manifest `sha256:e6fcfa6c19e5ab2c453096e1db165744972100eec29d2321e2715b77ecebae37`），另有 2,694,975 rows／32 features 的 research-shadow publication。prediction、model、replay、outcome、backtest、pickle 與無公告時間快照均隔離；新增欄位不得 wildcard 進模型。

> **PIT／官方回補實況**：決策時間固定 08:30；價格與技術只接受 T-1，公告資料只接受 `available_at <= decision_at` 的可證明 vintage。歷史 `daily_prices` 約 524 萬列／2,202 symbols，自 2014 起可用；歷史 P/E 約 295 萬筆。ATR／ADX 已由每檔 T-1 OHLC prefix 因果重算 Wilder(14)。官方 market-event ledger 已保存 28,397 個 append-only vintages（halt 7,949、resume 7,890、ex-right 12,230、reduction 328），canonical hash=`sha256:40436b531ce2832f46869d287ee47ff58cde3b06902620b357b7d558a7dad3f3`；只有 publication-time 可證明的事件可進特徵，result-only 除權息／減資不得反推公告時間。月營收、財報、TDCC、信用與 flow 候選若缺歷史公告／修訂／授權鏈，仍只供 Shadow；現有 `companies.csv` 也不得冒充歷史產業歸屬。

> **資料集與模型邊界**：`core_long_history`、`all_field_enriched` 與 `research_shadow_all_fields` 分開發布年度 gzip JSONL + immutable manifest；缺值、staleness、quality 與 provenance 都是顯式 mask。正式 official-event dataset 有 22,093 rows／62 features／4 expanding folds，dataset identity=`sha256:f7ed2fa9530529a2448157e3b6128cb2ad18eb945a29c10b436520b891cf3ca1`；A/B 重訓的 model=`sha256:92668aa574967990fa560aef8a48e595296eb22f3fef2a4264cff08210d78b6d`、replay=`sha256:ba0eb2456569d55d5981d97b612f109818c4acc01881e07ca9d1d6bf2042092d` 均逐位元一致。獨立 Research lane 則把 150 features／8 packs 與 2,533 日 T-1 causal ledger 接入同一配置學習，產生 1,137,664 base OOF／12,984 meta OOF，model=`sha256:dd512d6d32d853db151e971e816d514cd81c6b1cbf143289fc719ae41009a705`；它固定 `research_only=true`，不可取得 Formal credit。全市場 15,876,434-row raw publication 已完成；先前 direct numeric／OOC v5 artifact 已發布，但截至本次快照的新 direct custody refresh 仍在建置，`latest_manifest.json` 尚未切換到該 run。這代表既有訓練 custody 可追溯，不代表目前 refresh、formal replay、PIT completeness 或 promotion 已通過。公開契約只輸出 int bp／股數／縮放整數／`Decimal`，sklearn float 只存在隔離數值邊界。

> **配置與 Promotion 安全契約**：非零 alpha 不是 request flag，而是 05:17 unsigned Evidence Builder、05:18 獨立 Windows user-scope DPAPI Authority 與 05:20 consumer 三層重驗後的有效值。Builder 不簽章，Authority 不訓練／不選權重，consumer 只讀固定 authority pointer，並要求授權 model／dataset 與本次實際 inference release 完全相同；registry revision、決策有效窗、freeze 時序、custody root/id 及 evidence、model、dataset、OOF、shadow 實體 SHA-256 任一缺件或不一致即原子回退 `alpha=0`。Formal replay 即使帳務、成本與報酬可逐日重算，只要 `formal_semantic_validation.verified` 不是 true、少於 4 個 Meta OOF folds，或 requested/projected holdings 未由正式 Rule／完整 Meta OOF 獨立重建，便固定 `promotion_eligible_input=false`。現行 daily Shadow observation 可保存但 `promotion_day_credit_allowed=false`，不會用 current holdings 冒充 Rule baseline 累積 20 日門檻。配置執行另要求 hash-bound `CausalPortfolioState`：`as_of_date` 必須嚴格早於 decision date、完整列出所有 T-1 持倉，且 context weights、cash 與 10,000 bp 守恆一致；缺漏時回 `NO_NEW_POSITION`、`executable_weights=null`，不把未知 current 當成 0。

> **Production Scheduler 實證**：10 個 daily tasks 加 `baldr-v2-2-weekly-collection` 共 11 個 Windows tasks。ML 鏈順序固定為 `baldr-ml-promotion-evidence-daily`（05:17）→ `baldr-ml-promotion-authority-daily`（05:18）→ `baldr-ml-allocation-copilot-daily`（05:20）；三者均已實際觸發且 `Last Result=0`。目前 Evidence task 明確回報 OOC manifest 尚未發布，Authority 回報 compatible pointer missing，Co-pilot 則以逐 horizon reference 正常完成 `passed_rule_only`，不是排程失敗。Decision date 為 2026-07-31 08:30 Asia/Taipei、可用市場資料截止 T-1=2026-07-30；Decision/Evidence run 保存 7/7 sections 與 1,580 events（failures=0；degraded 1,569／estimated 3／observed 8），Paper run 保存 3 檔持倉、`cash=341000.00`、`total_value=484200.00`，市場 DB 固定 `mode=ro/query_only`，且每筆 mark 都證明 `price_date < decision_date`。Scheduler process-level 成功不等於資料來源全數 observed 或 Formal ML promotion 通過；所有排程皆不讀 UI state、不送券商單。

> **Gate 2–7 新判讀**：weekly sidecar 只保存 `pending_human_review`，不得自動計入 Gate 或視為 accepted；具名 owner 核准的 `approved-weekly-history-projection.v1` 目前為 3/3，僅供 UI 進度揭露。`formal_credit_authorized=false` 與 `production_scheduler_allowed=false` 維持不變；forward、paper elapsed、exit outcome、shadow days 與 nonzero-alpha formal gates 仍須各自累積可接受 evidence。完整狀態見 [Gate 2–7 External Validation Register](../06_qa/GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md)。

> **最終 QA 與 registry（2026-07-30）**：完整 pytest 為 `2,969 passed / 1 skipped / 0 failed / 32 warnings`（2,970 collected，513.51 秒）；Update Workbench `38 passed`、Update Tab QA `23 passed / 0 failed / 4 skipped`、指定 mypy scope `472 source files / 0 issues`、UI py_compile、金融 float guard 與 look-ahead guard 全數通過。Test Inventory 為 571 filesystem files／571 entries／2,970 tests，0 machine blockers。append-only registry 現有 33 rows，`ml:revalidation` 最新為 revision 6；該 revision 明記 Formal semantic replay 與 Shadow day-credit blockers，並維持 alpha 0。

> 下方 2026-07-27 以前內容是歷史稽核紀錄；若與上述 V4.0 區塊衝突，以本區塊及 append-only registry 的最新 revision 為準。

> **MOPS 季報秒級 PIT availability（2026-07-27）**：新增 MOPS 公告快易查 F26–F29 唯讀 adapter 與 TEMP-only CLI；live capture 取得上市 12、上櫃 24，共 36 個官方秒級事件，36 個 event hash／projection keys 均唯一，statement availability validator accepted 36、diagnostics 0。M31 因混合「預計召開董事會」與「已通過財報」語意而排除。owner=`archi` 已 limited 核准 `mops.ezsearch.statement_publication` 供內部 research PIT availability 與 development shadow projection；`candidate_artifact_not_supplied`、`mops_candidate_artifact_not_supplied` 與季報 blanket publication-time blocker 已解除。正式 mapping／DB／scheduler 未寫入，歷史 coverage、correction/revision evidence 與 formal lane 尚未核准；`formal_oos_allowed=false`、`formal_credit_authorized=false`、`production_blend_alpha_bp=0`。

> **Gate 2 Data Governance Consolidation（2026-07-22）**：已完成全量 SQLite、13 個 P0 資料源、PIT 與排程的唯讀工程稽核（詳見 [GATE_2_DATA_GOVERNANCE_CONSOLIDATION_AUDIT_2026_07_22.md](../06_qa/GATE_2_DATA_GOVERNANCE_CONSOLIDATION_AUDIT_2026_07_22.md) 與 [SCHEDULER_HEALTH_OBSERVABILITY_REPORT.md](../06_qa/SCHEDULER_HEALTH_OBSERVABILITY_REPORT.md)）。`DataQualityFirewall` 非破壞性捕捉 `daily_prices` 的 6 筆 NULL 代碼、8,226 筆週末資料與 3 筆重複主鍵，並將 `market_indices` 缺口標記為 `degraded`；月營收與財報因公告日 provenance 大量缺失，該次稽核結果均為 `DEGRADED_ANNOUNCED_DATE_PROVENANCE_MISSING`，正式 provider 在歷史讀取時 fail-closed，不可把回填可得日當成 PIT-safe。排程健康檢查會讀取日期型 weekly collection sidecar，並將其 `pending_human_review` 與每日更新分開呈現。該次 Gate 2 三層模型為 Weekly Collection（pending）、External Approved Projection（2/3）與 Formal DB Credit（0/3），13 個 P0 源全數 `deferred`／downstream `none`；季報來源的最新 limited research-only 覆寫狀態見上方 2026-07-27 註記。正式 DB SHA-256 未變，`production_scheduler_allowed=false`，`formal_credit_authorized=false`，無自動下單、交易或正式 DB 寫入。

> **Parallel system engineering integration（2026-07-13）**：A～F 的 committed handoff 已完成 SHA／ownership／focused-suite 核對，G 的 temp SQLite chain 與 pure verifier 已驗證跨流契約。`engineering_integration=verified`；`historical_ml_shadow=continue_shadow` 且 `formal_oos_allowed=false`；市場總覽與 Broker latency 工程 Gate 已通過。這不改寫外部真相：A 只有 `engineering_real_e2e_complete`；E1 source／license 尚未 accepted、scheduler=false；E2 official monthly／quarterly rows=0、corporate coverage=unknown；F 無真實 frozen artifact smoke，production blend alpha 固定 0。Forward evidence、source acceptance、production automation 與 ML promotion 全部維持 pending。

> **Evidence rehearsal engineering closeout（2026-07-14）**：唯讀 replay / source shadow / ML shadow / lineage 工程底座狀態為 `engineering_rehearsal_complete`，可重跑 coverage、quality、missingness 與 lineage disclosure，Workbench 只顯示結果而不 apply / promote。詳細邊界與 forward handoff 見 [Evidence Rehearsal Engineering Closeout](../06_qa/EVIDENCE_REHEARSAL_ENGINEERING_CLOSEOUT_2026_07_14.md)；External Validation Register 不因本工程收口變為 complete。

> **Terra Development Dataset V0（2026-07-14）**：owner 已決議 2025 永久為 `seen_oos`／development-only。Canonical external generation 已用 2025-01-02～07-16 的 120 個 decision dates 產生 179,271 fit rows；完整 Rule development baseline／ML challenger purged walk-forward comparison 產生 53,559 OOF samples，並由 sanitized Research Console projection 唯讀呈現。Producer／consumer 現會驗 generation identity、row counts、semantic content hash、training cutoff、exact development scope、canonical false apply flags與整數 alpha 0；report/projection 成對 atomic publish。正式 DB SHA-256／mtime 未變，`formal_oos_allowed=false`、production alpha=0，且不改 Rule-only、Score、Recommendation、Portfolio、Exit 或 scheduler。這仍是 `research_only_degraded` development evidence，不是 formal OOS、model promotion 或投資有效性證據。

> **Gate 2–7 pure engineering closeout（2026-07-12）**：35 個必要 artifact/commit pairs 已涵蓋 Evidence/V3、13-source P0 contracts/adapters、Paper Portfolio 日更閉環、Position Health/Exit、9-slice structured traditional ML shadow challenger，以及 append-only human/time/ML control center。工程證據見 [Gate 2–7 Pure Engineering Closeout](../06_qa/GATE_2_TO_7_PURE_ENGINEERING_CLOSEOUT_2026_07_12.md)；後續人工／時間工作從 [External Validation Register](../06_qa/GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md) 與 [Engineering Control Center](../06_qa/GATE_2_TO_7_ENGINEERING_CONTROL_CENTER.md) 接手；ML 更新與重驗見 [Gate 7 ML Shadow Engineering](../06_qa/GATE_7_ML_SHADOW_ENGINEERING.md)。這不是 formal product closeout：P0 仍 `requires_human_acceptance`、ML 仍 shadow-only、production scheduler/broker/auto promotion/auto exit 仍禁止。

> **工程終態**：`V3.3 Engineering Complete`，進入 `V4.0 Evidence Accumulation Track`；15 capability、lineage 與 operations 入口見 [V3.3 Engineering Closeout](../06_qa/V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)。正式 V4.0 與投資有效性尚未成立。

> **開場 30 秒內讀完** - 只放今天可驗證的狀態與入口，不放完整歷史細節
> **最後稽核**：2026-07-12；證據矩陣見 `docs/06_qa/PROJECT_SNAPSHOT_AUDIT_2026_07_12.md`。

> 2026-07-11 安全重構續作：`UpdateService` normalization import 已改為明確 submodule dependency，並由 fresh-interpreter package re-export oracle 保護；`BacktestService` 已透過 `WalkForwardResultContract` 移除對 `walkforward_service` 的反向型別依賴。Walk-forward T-1 fold 邊界、degradation／summary golden 數值契約與 overfitting regression 均已納入 focused tests；金融公式與公開 runtime entrypoint 未變。
>
> 同輪 UI 薄殼化已建立五個可測試委派邊界：Backtest／Recommendation presenters、Update worker coordinator、Workbench DTO presenter 與 MainWindow workspace coordinator。現有 widget ownership、signal wiring、公開 helper、更新工作順序與 Workbench read-only 規則不變；下一個 Application 切片是移出 MainWindow 的 Decision Desk service composition。
>
> Decision Desk service composition 已移至 `app_module/decision_desk_composition.py`；MainWindow 不再直接包含各 provider/service 的 try/fallback 組裝流程。Composition 仍透過注入的既有 constructors 維持測試替身與 fail-soft 行為，共用 market-frame loader identity 不變；Regime confidence / score adapter 已改用 `Decimal` 轉整數 bp。
>
> UI 大型 presenter 續作：BacktestView 原 143 行績效摘要已縮為 presenter delegate；RecommendationView 的 profile advanced summary、權重與篩選格式鏈亦已移出。SOP／fixed／quantile／profile 顯示契約由 focused tests 保護，未修改回測或推薦計算。
>
> UpdateView 原 113 行 `_run_update_all` 已移至非 Qt `update_all_coordinator.py`；view 只注入日期、service operations 與 progress callback。快速／安全更新步驟、SQLite sync、TPEX soft failure、一般失敗 fail-fast 與結果 payload 契約均由 direct + widget tests 保護。
>
> Workbench 的 review/evidence/action/operating-loop DTO 狀態與 degraded 判讀已集中至 presenter；MainWindow 的八個 workspace key、label、icon 與註冊順序已集中為 immutable workspace plan。Read-only boundary、導航順序、widget ownership 與 signal wiring 不變。
>
> MainWindow 的 Smart Money semantic/common-loader 組裝與 Runtime controller/bridge/view/timer wiring 已分別移至 Application composition root 與 Qt composition coordinator。Smart Money 與 Decision Desk 共用 loader identity、Runtime 1 秒 polling、signal targets 及既有降級 UI 契約均由 direct/integration tests 保護。
>
> BacktestView 單檔執行已使用 immutable request 統一 service kwargs 與 `current_run_params`，消除兩份市場限制、風控、部位與成本參數 mapping。此 request 只傳遞既有值，不新增金融計算，也不改 signal context／T-1／look-ahead 邊界。
>
> RecommendationView 執行已使用 immutable request 集中圖形／技術指標必選驗證、`max_stocks=200`、`top_n=50` 與 10→100 progress contract。View 僅收集既有 config 並管理 worker/result；推薦排名、分數與 universe 邏輯未變。
>
> RecommendationView 原大型 reason formatter 與 Explain panel builder 已移至純 presenter；keyword/tag、觸發來源、score breakdown、ranking metadata 與風險提示輸出由 golden tests 保護。搬移過程的中文 encoding regression 已由 RED 捕捉並修復。
>
> Recommendation Why Not 的子分數、filter、Regime 與總分差距/severity HTML 已完整移至 presenter，View 僅委派既有 DTO/config。UI gate audit 顯示仍有 Backtest optimization/worker、Update action orchestration 與 Recommendation save/context-menu 等非純 widget construction，故 UI 薄殼階段尚未宣告完成。
>
> UpdateView 單一資料源更新已改用 immutable request；daily 的 TWSE/TPEX/SQLite/indicator 順序與 warnings/result aggregation，以及 market/industry/broker mapping 均由 direct contracts 保護。View 仍負責 radio/date widgets、log/progress widgets 與 worker lifecycle。
>
> BacktestView 的 grid-search 與 batch 執行已分別改用 immutable requests，集中 objective/top_n、20+ 回測欄位、save_runs、parallel threshold、research mode、progress 與 cancellation mapping。View 保留 ParamRange/parallel widgets、preflight、QTimer UI progress 與 worker lifecycle；回測／最佳化核心未改。
>
> Walk-forward UI 執行已使用 immutable request 集中 Train-Test/Walk-forward mode 與 service kwargs；fold/T-1 邏輯仍由既有 service/golden contracts 管理。Recommendation 保存已使用 immutable request 建構 result DTO、Profile/Regime/negative-evidence snapshot 與 watchlist payload；實際寫入仍只在使用者保存動作中發生。
>
> UI 薄殼 gate 已完成：五個 UI shell 不再直接呼叫核心 execution entrypoints，並由 AST contract 防止回流。Recommendation save coordinator 已提升至 Application layer，`persist()` 管理必要 result write 與 soft-failure watchlist write；View 只觸發使用者動作並呈現 outcome。下一階段為 Application orchestration／依賴反轉。
>
> Application DI 第一片：RecommendationService 的 market-history stage 已改由 injected provider；default adapter 原樣保留 SQLite-first、SQL join、CSV fallback、60 日窗口、日期/數值 normalization 與例外語意。ranking、recomputation、V1.7 negative-evidence 與 provider tests 保護 snapshot-equivalence；推薦 score/ranking pipeline 未改。
>
> Application DI 第二片：推薦市場資料欄位正規化已成為不突變來源 DataFrame 的具名純步驟；IndustryMapper 與 MarketRegimeDetector 已新增 frame-provider ports。MainWindow 的 Screening／Regime／Recommendation concrete graph 已移至 `app_module/decision_service_composition.py`，由 Application-owned SQLite-first/CSV-fallback providers 注入，共用 IndustryMapper、保留兩個獨立 regime detector；產業與 regime 金融算法未改。
>
> Wave 4 ownership closeout：`IndicatorParameterRegistry` 已移至 analysis domain；Flow/Broker DTO 已由 decision domain 擁有。2026-07-12 經使用者明確核准後，舊 decision registry 與 Application DTO shim 已移除；靜態 audit 未發現 Flow DTO pickle/joblib persistence，dataclass payload shape、broker flow、Smart Money 與 UI contracts 均保持。
>
> Wave 5 第一個金融／分析 kernel：技術指標價格清理已抽成純 `clean_price_values()`。正常與內部缺值 golden、float64 numeric boundary、prefix/T-1 契約已固定；移除前導缺值的 `bfill()`，改為只使用當下以前觀測值，修正前導價格讀取未來資料的 look-ahead，RSI/MACD 公式與參數不變。
>
> ScoringEngine 的 10,000 bp 最大餘額正規化已抽成 Decimal／整數 pure kernel，既有 tie-break、zero-weight default、TotalScore golden 與 prefix oracle 不變。StockScreener 的 recent stock/industry reads 已新增 provider ports，Application composition 注入 adapters 並把 StockScreener 一併移出 MainWindow service graph；非 UI constructor fallback 保留相容。
>
> BrokerBranchUpdateService 已完成第一輪責任分離：registry 文字解碼／mojibake／總公司判定、MoneyDJ URL request builder、E/B lots/amount merge plan 與 daily/merged CSV write coordinator 均已成為可獨立測試的 Application components。Service 保留原 private façade、HTTP→Selenium fallback、日期順序、重試、備份與 CSV schema；驗證僅使用記憶資料與 temp path，未寫正式資料。
>
> UpdateService 的 daily subprocess output parser 已抽成具名純步驟，固定 summary、逐日成功／跳過／失敗、空輸出 fail-closed 與 diagnostic code 契約。`update_daily()` 保留缺日掃描、subprocess 命令、暫存 log lifecycle 與公開 payload，只移出 170+ 行解析／聚合分支。
>
> RecommendationService final ranking 已改為純 ranking plan：輸入僅有 stock code／score、mode、top_n 與 ranking config，輸出 immutable ordered/selected codes、percentile bp 與 universe metadata；DTO 與 screening matrix mutation 留在 façade。fixed tie 維持輸入順序，quantile tie 維持 stock code 次排序，既有 ranking／negative-evidence／DTO tests 保持。
>
> MarketRegimeDetector 的 MA slope 與 Bollinger bandwidth 已抽成 causal analysis kernels；short-history、數值 golden 與全 prefix invariance 由 direct tests 固定，detector 保留 façade、hysteresis 與 persistent-history ownership。
>
> Wave 5 金融核心 closeout：TechnicalIndicator price normalization、Scoring bp normalization、MarketRegime slope/bandwidth 均已依 golden→prefix/T-1→numeric→pure kernel→façade 完成；BrokerSimulator、performance metrics、Portfolio core 與 RecommendationPortfolioBacktest 沿用既有 `financial_module.units`、ledger/metrics/result supports。92 項 timeline／Decimal／numeric governance 測試通過；已知 recommendation portfolio 同日收盤成交研究假設仍明示 warning，未被包裝成實盤等價。
>
> Wave 6 已獲使用者明確核准並完成移除：三個 compatibility shim、`recommendation_module_legacy`、舊 example 與兩個 legacy manual checks 已在 consumer 歸零後刪除；test inventory、導航、migration history 與架構文件已同步。Dynamic import 與 pickle/joblib audit 未發現隱藏 consumer；完整證據與回滾方式見 [SHIM_LEGACY_REMOVAL_AUDIT_2026-07-12.md](../06_qa/SHIM_LEGACY_REMOVAL_AUDIT_2026-07-12.md)。
>
> Wave 6 刪除後 release closeout：Full App Healthcheck `20260712_025311` passed；完整 pytest 1676 passed、Update Qt 38 passed、Update QA 23/0/4、mypy 364 files、financial checker 37 passed，compileall 與 diff check 亦通過。24 個 pytest warnings 均為既有 recommendation portfolio 同日收盤成交研究假設的明示揭露。
>
> Commit-readiness review follow-up：修正 Application provider 注入後 raw `market_indices.收盤指數` 未 canonicalize 為 `收盤價`，以及 industry CSV `YYYY-MM-DD` 被 strict `%Y%m%d` 轉為 `NaT` 的兩個 default-path regression；兩者均先有 reproducing RED。新增 market-frame canonical contract，同時支援 SQLite `YYYYMMDD` 與 ISO 日期。Recommendation、save、composition、Broker write 等新 DI seams 已改用 named Protocol，不再以 `Any` 隱藏 port contract。Master Report 已轉為 current-program closeout；Graphify ghost/duplicate node 問題另行處理，不作 commit gate。

## 系統定位（一句話）

baldr 是一套可觀察台股市場、產生有條件且可追溯的結構化投資建議、建立建議 Portfolio、追蹤持倉健康與退出條件，並持續驗證自身建議是否有效的投資決策系統；它不保證獲利、不自動下單。

## 文件權威判讀

本專案已改採 **Scoped SSOT（分範圍單一真相來源）**：

- **現在狀態 / 本週優先事項 / 高風險區**：以本文件為準。
- **重構完成後產品方向**：以 `docs/00_core/PRODUCT_ROADMAP_POST_REFACTOR.md` 為準。
- **未來 6 個月工程路線**：以 `docs/00_core/ROADMAP_6M_ENGINEERING.md` 為準。
- **產品北極星與 bounded advice / evidence 邊界**：以 `docs/01_architecture/system_vision_specification.md` 為準。
- **目前架構與模組邊界**：以 `docs/01_architecture/system_architecture.md` 為準。
- **理想目標架構**：以 `docs/01_architecture/target_system_architecture.md` 為準；不得用 Target capability 推論目前完成。
- **文件導航**：以 `docs/00_core/DOCUMENTATION_INDEX.md` 為準。
- **舊 Phase 與歷史 Done**：只看 `docs/09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md`，不作目前狀態依據。
- **舊 Roadmap 未完成事項移交**：以 `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md` 為準。
- **目前完整操作方式**：以 `docs/07_guides/APPLICATION_MANUAL.md` 為準。
- **外部專案參考與 V1.5-V2.0 版本形狀**：以 `docs/00_core/EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md` 作 companion 參考；它不取代 Vision、6M Roadmap 或 Version Roadmap。
- **V2.0 之後的長期版本階梯**：以 `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md` 作 companion 參考；它只把 6M Roadmap Phase 與 Vision 成功標準映射為 V2.1-V4.0，不取代 6M Roadmap 或 Vision。

`docs/00_core/DEVELOPMENT_ROADMAP.md` 現在是 Roadmap Hub，只負責指向上述權威文件，不再保存完整歷史長文。

## 當前狀態

**目前產品 Gate**：Gate 0 Safe Refactor 已由 `ae83740` closeout；[SAFE_REFACTORING_MASTER_REPORT_2026_07_12.md](../09_archive/SAFE_REFACTORING_MASTER_REPORT_2026_07_12.md) 已歸檔為完成工程的證據與 rollback companion，不再是 active product work。V2.1 / Gate 1 Daily Usable Advice 已於 2026-07-12 14:51:42 -07:00 獲 release owner `approve`，狀態為 `formal_closeout_complete`（證據見 `docs/06_qa/V2_1_ENGINEERING_READINESS_2026_07_12.md` 與 `docs/06_qa/V2_1_FORMAL_CLOSEOUT_2026_07_12.md`）。`592d3db` 已確認 Guided 僅接受 `promoted`、已鎖定參數且 disclosure 完整的策略；`max_positions` 僅可為 `1..8`；Professional candidate 僅作 `RESEARCH` 並與正式 Advice 分區。它是唯讀、可拒絕、可回溯的 Advice Contract，不代表 Portfolio Coach、Exit Engine、P0 formal ingestion、production scheduler、ML production 或投資有效性已完成。

**V2.4 / V2.5 / V3.0 真實資料起點（2026-07-12）**：已由 `scheduled_rec_20260712_051002` 建立第一個 research-only paper baseline，3 筆 allocation 紙上可執行總額 NT$159,000、殘餘現金 NT$341,000；同一 artifact 產生 3 筆 fail-closed `WATCH` health baseline，未捏造 thesis / invalidation。V3.0 對 Week 1 working-copy 的唯讀人工驗證顯示 3 筆 score events 的 12 個 outcomes 全為 missing，另有 1,134 個事件缺 `score_bp`，故決議 `DEFER_ALL_PRUNING_DECISIONS`。這些結果不寫持倉 DB、不下單、不改 score / lifecycle，且仍缺真實 forward / paper 時間證據。

專案已超出早期線性 Phase 規劃；截至 V1 release readiness closeout，實際產品主線已形成四個可操作產品閉環，並補上 Strategy Lifecycle / Portfolio Feedback 與 release QA 的治理閉環。V1 完成只代表工程入口、資料契約、操作流程與 release gate 已可用，不代表任何推薦、警示或策略已被證明具備投資有效性。

截至 2026-07-07，Post-V1 evidence-driven 增量已建立 Evidence Event Store v1、Forward Outcome Calculator v1、Evidence Importers / Capture Pipeline v1、E2E smoke、Forward Performance Read Model v1、Evidence Source Persistence v1、Forward Performance Dashboard read-only UI v1、Evidence Pipeline Runner dry-run v1、working-copy DB smoke v1、scheduler approval checklist v1、Live vs Research Gap linkage v1、Signal Decay Monitor v1、Decision Quality Review v1、Evidence Review Dashboards read-only UI pack v1、Evidence Operations weekly review v1、Evidence Review History v1、V1.5 Data Credibility & Corporate Action Gate v1、V1.6 Cross-sectional Factor Pipeline v1、V1.7 Screening Matrix & Negative Evidence v1、V1.8 Portfolio Construction & Execution Trace Sandbox v1、V1.9 Read-only Agent / MCP Evidence Access v1、Pre-V2 non-schedule readiness inspector、Evidence Review manual smoke checklist、multi-day dry-run record scaffold、safe scheduled dry-run wrappers、Historical Evidence Replay v1、V2.0 Workbench Phase 1 read-only prototype CLI、Workbench formal read-only source adapter 與 Phase 2 Qt read-only Workbench MVP shell。實際 commit / closeout 已落在 2026-07-01 至 2026-07-07。

Post-V1 部分文件檔名沿用 2026-07-05 至 2026-07-12 的里程碑命名；時間判讀請回到本 Snapshot 與 6M Roadmap，不以檔名推論交付日。

2026-07-09 已完成不改行為的重複計算消除：推薦流程的最新 `漲幅%` / `成交量變化率%` 改由單一 Decimal helper 計算，StrategyConfigurator、推薦 DTO 與 negative evidence 共用同一結果；推薦與回測對已 join 的預存技術指標，只有在 `IndicatorParameterRegistry` 正規化後等於標準預設參數且欄位完整時才重用，自訂參數、缺欄位、全無效欄位與 ATR / ADX 仍依原流程計算或 fail-closed。Daily Decision Desk 的 Market Breadth、Relative Strength / Liquidity 與 Smart Money 在單次 snapshot 內共用 read-only `DecisionMarketFrameLoader`，每次新 snapshot 都 reset，不跨執行保存 cache。此變更不改推薦、回測、更新、Decision Desk 公開入口，不改 DTO / scoring / threshold / SQLite schema / scheduler 命令與 dry-run / confirm gate。

Evidence layer 可 append-only 保存 Recommendation、Watchlist Trigger、Portfolio Alert、Risk Prompt、Why Not / Liquidity exclusion、Screening Matrix 等事件，並以 SQLite `daily_prices` 計算 5 / 10 / 20 / 60 交易日 close-to-close forward research outcome。Recommendation importer 可從 persisted `RecommendationResultDTO` 擷取；V1.7 後新保存的 Recommendation result 會保存 `screening_matrix_json`，完整保留 pass / fail / degraded / skipped / missing，以及由 matrix 衍生的 why-not / liquidity payload；importer 會產生 `screening_matrix_pass`、`screening_matrix_fail`、`screening_matrix_degraded`、`screening_matrix_skipped`、`screening_matrix_missing`、`why_not_excluded` 與 `liquidity_gate_excluded` 事件。舊結果若缺 matrix 或 exclusion payload，仍只回 `source_missing_screening_matrix` / `source_missing_exclusion_payload` diagnostic，不回補、不重算。Daily Decision Desk 類來源已新增 durable snapshot repository 與 capture / inspect CLI，`capture_evidence_events.py` 可從 durable snapshot 匯入 Watchlist Trigger、Portfolio Alert、Risk Prompt；若缺 snapshot 會回 `source_missing_snapshot`，不讀 UI state、不偽造事件。V1.5 已新增 read-only Data Source Capability Registry、corporate action / adjusted price policy inspection、governed microstructure preflight metadata 與 `EvidenceSourceCoverageService`；source coverage 現在將 persisted recommendation / durable snapshot section 缺口列為 blocking gaps，將 why-not / liquidity / screening matrix payload 缺口列為 warnings / `dry_run_only`，不把 partial payload 包裝成 production readiness。V1.6 已新增 cross-sectional factor snapshot DTO / repository / pipeline / attribution summary CLI，可把既有 `FactorRecord` 經 `FactorGate` 後保存為 daily factor snapshot，包含 integer rank / quantile、sector / concept metadata、quality 與 diagnostics；這是研究治理與 attribution 底座，不改 `ScoringEngine`、不自動推薦、不啟用 scheduler。V1.7 已把推薦候選的入選、未入選、歷史不足、無訊號、例外降級與低流動性排除保存到同一 evidence layer；這只補研究追溯，不改推薦分數、不自動降級策略、不啟用 scheduler。V1.8 已新增 research-only portfolio construction DTO / service 與 virtual execution trace service，可用等權、分數權重、inverse-volatility 候選、max position cap、整數 bp 權重、Decimal 金額與整股 lot sizing 產生 allocation result，並輸出 Created / Submitted / Partially Filled / Filled / Rejected 虛擬事件；`scripts/inspect_portfolio_sandbox.py --sample` 只輸出內建樣本，不讀正式資料、不下單、不啟用 scheduler。V1.9 已新增 `AgentEvidenceAccessService` 與 `mcp_servers/evidence_access_server.py`，以 read-only SQLite URI / `PRAGMA query_only=ON` 或既有 read-only repository 查詢 Evidence / Forward Summary / Research Run / Portfolio Review saved evidence，並輸出 Agent permission model 與 AI report template；缺 DB 或缺 table 只回 diagnostics，不建立 schema、不寫 DB、不改策略、不下單、不套用 lifecycle action。`scripts/inspect_pre_v2_readiness.py` 可唯讀彙總 weekly history、multi-day record、source gaps 與 read-only Agent report sample，狀態分為 `ready`、`waiting_for_time`、`action_required`，且 `production_scheduler_allowed=false`；`waiting_for_time` 不可用 fixture、單次 smoke 或手動改文件取代。Read model 可依 event_type、event_family、source_type、regime、sector、profile_id、score_percentile_bucket、liquidity_state、data_quality 彙總 ready / pending / missing、return / excess return、quality 與 warning counts；Research Lab 已新增 `Evidence Review` 分頁，內含 `Forward Evidence`、`Live vs Research Gap`、`Signal Decay`、`Decision Quality` 與 `覆盤歷史` 五個唯讀 evidence inspection 子頁；`scripts/run_evidence_pipeline.py` 可手動串接 source coverage、snapshot capture、event capture、outcome calculation、summary 與 diagnostics report，預設 dry-run，只有 explicit `--confirm --db-path` 才寫 working-copy DB。`scripts/build_evidence_operations_weekly_review.py` 可用 `--save-history` append-only 保存 weekly review history，並以 `--list-history` 唯讀檢查；保存 history 必須指定 explicit DB，疑似正式 DB 仍需額外 gate。`scripts/smoke_evidence_pipeline_working_copy.py` 可複製 source DB 至 working-copy DB 並重複 confirm smoke 檢查 idempotency；`scripts/evaluate_evidence_scheduler_readiness.py` 會彙總 source coverage、smoke report 與 dashboard availability，且固定 `production_scheduler_allowed=false`。`POST_V1_EVIDENCE_REVIEW_UI_SMOKE_CHECKLIST_2026_07_12.md`、`POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md` 與 `POST_V1_EVIDENCE_SCHEDULER_APPROVAL_SOP.md` 目前作為人工 UI smoke、多日 dry-run 穩定性觀察與未來 scheduler approval stage 管理的 scaffold，不代表 production scheduler 已啟用。這仍只是 research evidence aggregation、scheduler dry-run design、人工核准準備、gap observation、decay observation、流程覆盤、weekly review history、資料可信度治理、factor attribution / negative evidence / portfolio sandbox / read-only AI evidence access / Pre-V2 readiness inspection 底座、唯讀檢查 UI 與 QA scaffold；正式 production scheduler、外部資料源 ingestion、樣本累積、完整實帳歸因、人工 smoke 實際 closeout、多日 dry-run 實際記錄與投資有效性結論尚未完成。

**Evidence 時間型 Gate 狀態校正（2026-07-12）**：multi-day dry-run record 已為 `3/3 ready`；Week 1 已使用 2026-07-06 至 2026-07-12 真實週期、隔離 working-copy、repeat=2 idempotency smoke 與 append-only history 完成，weekly evidence operations history 為 `1/3 waiting_for_time`。review ID 為 `eor_e584e6a164a66c09`；Week 1 backup / restore recovery 副本均通過 SQLite quick check 且保留相同 review hash。正式 DB 未寫入，`production_scheduler_allowed=false`；Week 2 / Week 3 與 explicit production approval 仍未完成。證據見 `docs/06_qa/V2_2_WEEK1_REVIEW_2026_07_12.md`。

**隔離 weekly history 的 UI 揭露（2026-07-21）**：決策工作台可選擇讀取具名 owner 提供的 `approved-weekly-history-projection.v1`，以顯示隔離 working-copy 中已核准的 weekly review 累積數；UI 不掃描 `C:\Temp`、不寫入或合併正式 DB。projection 固定 `formal_credit_authorized=false`，因此此功能不改變 formal clock、source acceptance、scheduler、Recommendation、Portfolio、Exit、Score 或交易資格。

**V2.2 Engineering Readiness（2026-07-12）**：weekly review CLI 的 `--save-history`、`--list-history`、`--action-owner` 操作契約已完成 focused 測試；`--list-history` 在 config 初始化前做純 path 解析，對缺 DB / table 只回 diagnostics、不建立 DB parent、log directory 或 SQLite 物件，combined `--confirm-action-items --save-history` 將 owner / action plan 封存至 history snapshot。固定三週人工紀錄格式與含既有 copy/guard 的 working-copy runbook 已建立（見 `docs/06_qa/V2_2_ENGINEERING_READINESS_2026_07_12.md`、`docs/07_guides/V2_2_WEEKLY_REVIEW_RUNBOOK.md`）；production-like DB 對 confirm / save 強制拒絕，沒有繞過旗標，且 canonical DB guard 同時檢查 configured／環境／預設正式 root，`--data-root` 不可放行正式 DB。目前 weekly 仍為 `0/3 waiting_for_time`，multi-day 為 `3/3 ready`，scheduler 尚未獲明確核准且 `production_scheduler_allowed=false`。本次是 engineering readiness 記錄，不得建立 formal closeout；真實三週 history、manual review / action-item rhythm、backup / rollback / recovery 演練與明確 scheduler approval 仍為必要條件。

**V2.2 週日 sidecar collection（2026-07-12）**：`baldr-v2-2-weekly-collection` 僅於每週日 18:00 執行 collection wrapper，將來源週期資料以 idempotent sidecar record 保存為 `pending_human_review` 或 `collection_failed`。`pending_human_review` 不等於 manual review、不會確認 action item、不會寫入 weekly history，不能折抵真實三週 history Gate；task 不改 source DB、沒有 production write mode，`production_scheduler_allowed=false` 維持不變。若須回復，只能停用或解除註冊該週日 task，禁止自動 drop sidecar table，以保留既有 record 與錯誤診斷。

**V2.3 P0 原則核准（2026-07-12）**：使用者已核准全部 13 個 P0 source 的導入方向，但這不是 formal source acceptance。各列仍為 `requires_human_acceptance`、`downstream eligibility=none`；工程可補齊 manifest、PIT / available-date、coverage、retry、evidence 與公開來源 metadata，但不得假定授權、不得啟用 ingestion / Scoring / Advice / Portfolio / scheduler。正式逐列 `accepted` / `limited` / `rejected` / `deferred` 決議仍須在證據完成後取得。

**V2.4 開工核准（2026-07-12）**：使用者已核准以平衡風險方向進行 Portfolio Coach Foundation 的工程實作與 paper-only 驗證；範圍包含中等現金緩衝、持倉上限、整數 bp target/current/gap、Equal Weight、交易限制與可追溯 paper execution。此核准不包含 broker、真實下單、自動再平衡或 formal closeout；工程完成後仍須人工確認風險政策數值、paper baseline / cost assumptions、限制情境與 `NO_NEW_POSITION` 行為。

**V2.4 Engineering Readiness（2026-07-12）**：research-only portfolio construction、virtual execution trace、condition / alert / feedback / review service 與數值治理 focused suite 已驗證 `31 passed`。allocation / trace 全部維持 `research_only=true` / `research_basis=true`，不改實際持倉、不下單、不套用 lifecycle。V2.4 尚缺平衡風險政策的實際數值、真實時間 paper observation、成本 / 滑價與 execution feasibility review、decision journal，以及 target/current/gap / `NO_NEW_POSITION` 的人工情境驗收；因此僅為 engineering readiness，不是 formal closeout。

**V2.4 紙上政策檢查器（2026-07-12）**：已將核准的平衡型 paper-only 數值接入 `PaperPortfolioPolicy`，可用 `scripts/inspect_paper_portfolio_policy.py --sample --format json` 產出唯讀 policy / candidate / 拒絕理由報告。它不讀取實際持倉、不寫正式或 working-copy DB、不產生訂單；此工程接線不取代真實時間 paper evidence，也不建立 V2.4 formal closeout。

**V2.5 Position Health Engineering Readiness（2026-07-12）**：`PositionHealthService` 與 `scripts/inspect_position_health.py --sample --format json` 已把既有 condition、feedback 與 source trace 轉為可解釋的 HEALTHY / WATCH / EXIT_CANDIDATE 狀態；缺條件或來源追溯時 fail-closed 為 WATCH，所有輸出固定 `auto_action_allowed=false`。它不讀持倉、不寫 DB、不自動減碼或平倉；尚無真實 thesis、人工 state transition 或 decision journal，不能 formal closeout。

Historical Evidence Replay v1 新增 `HistoricalEvidenceReplayService` 與 `scripts/replay_historical_evidence_pipeline.py`，可把 source SQLite DB 複製成 replay DB，依歷史交易日逐日呼叫 Evidence Pipeline Runner，並在事件 metadata / source payload 標示 `historical_replay`、`simulated_scheduler`、`replay_run_id`、`replay_decision_date` 與 `replay_data_as_of_date`。Replay 只選擇 `created_at` 日期不晚於當日的 persisted Recommendation result；若當日以前沒有 result，會記錄 `recommendation_asof_result_missing`，不使用未來 result 補值。Forward outcome 計算新增 `data_as_of_date` 上限，避免重放到半年前時提早看到未來價格。此工具只作 working-copy / replay DB research evidence，不寫正式 evidence DB，不取代真實 weekly history、多日 dry-run record、manual approval 或 production scheduler gate。

2026-07-06 Phase 0A Historical Replay Evidence Quality Audit 已完成 reference return closeout：`6eb7f8e fix: fill replay reference returns` 修正 `ForwardPerformanceService` 的 reference lookup，missing benchmark 會預設使用 `TAIEX`，`market_indices` 可從未命名市場序列與 `收盤價` fallback 取得 close，industry 只在 event payload 有 sector 且可保守映射時填入。新 `_reference_fix` replay 產物涵蓋 2026-01-06 至 2026-07-06 共 118 個交易日、118,056 events、472,224 outcomes；ready outcomes `380,520` 全部已有 benchmark return / excess，industry return / excess 只有 `2,029`，其餘 `378,491` ready rows 保持 `DEGRADED` + `missing_industry_benchmark`。`source_missing_screening_matrix` 仍為 118/118 days，屬舊 recommendation payload gap，不回補、不重算。此結果可支持 V2.0 Phase 1 的 source gap / evidence maturity / quality boundary 設計，但仍不代表策略有效、Phase 0 真實時間 gate 完成或 production scheduler 可啟用。

2026-07-12 Gate 1 / V2.1 將 Advice 接入既有 Workbench 唯讀 DTO 路徑；engineering readiness 後，release owner 已於 2026-07-12 14:51:42 -07:00 明確 `approve`，正式版本化 closeout 為 `formal_closeout_complete`：`AdviceComposer` 僅消費注入的 Recommendation / Portfolio / Evidence payload，保留 `decision_date`、`data_as_of_date` 與 source trace，拒絕 future input；`AdvicePolicy` 對無效模式、未 promoted／未 locked／disclosure 不完整策略、資料缺漏 / 降級、不可成交與風險限制 fail-closed。`592d3db` 進一步限制 `max_positions` 必須為 `1..8`，並要求 Professional candidate 只能 `RESEARCH`、標記為 `PROFESSIONAL_CANDIDATE`，在 Qt 與正式 Advice 分區。Qt 只由 `WorkbenchDashboardDTO.advice_dashboard` 呈現 action、理由、quality、可成交性與 target/current/gap，不執行 policy、不寫 DB、不重算 scoring / portfolio / backtest / lifecycle。平衡風險檔固定最低現金 `2000 bp`、單檔最多 `1500 bp`；權重為整數 bp，金額為 `Decimal`。2026-07-12 focused suite 為 `94 passed in 2.91s`；人工 UI 文案 smoke 確認安全 action 不被描述為交易指令。`NO_NEW_POSITION`、`RESEARCH` 與 `AVOID` 是正常安全輸出，不是 UI 例外或交易指令；這不代表投資有效性、broker execution 或 production scheduler 已完成。

2026-07-07 V2.2 simulated phase progress 與 Phase 5 approval rehearsal package 已完成：`SimulatedPhaseProgressService` 與 `scripts/inspect_simulated_phase_progress.py` 可唯讀讀取 historical replay summary、scheduled dry-run latest status 與 Pre-V2 readiness，將 replay 標註為 `historical_replay` / `simulated_scheduler` / `official_gate_credit=false` / `requires_real_world_validation=true`。Reference-fix replay 可支援 simulated Phase 0-5 到 `simulated_ready`，但 official Phase 5 仍是 `blocked`，`production_scheduler_allowed=false`。不得標為已完成、必須等待正式資料的項目包括：weekly history `3/3`、multi-day dry-run `3/3`、真實 manual review note rhythm、真實 action item rhythm、Phase 3 source candidate acceptance、Phase 4 execution realism acceptance、backup / rollback / recovery evidence 與 explicit manual approval。

2026-07-08 V3.0 engineering candidate 已完成為「工程候選」：V3 effectiveness read model、gap classifier、sample sufficiency / confidence disclosure、review scaffold 與 readiness inspector 已可產生 read-only engineering closeout；closeout/readiness report 已完成，工程狀態為 `ready_for_manual_validation`，人工驗證仍是 `PENDING_MANUAL_VALIDATION`。使用者批准的 `V3 score effectiveness audit + ML readiness bridge` 工程輸入也已完成：`2bd08f6` 建立 `TotalScore` raw bucket audit，`b5ec05d` 建立 fixed threshold robustness、component ablation readiness 與 ML shadow-only contract，`d4526c9` 補上三大法人 / 信用交易 / TDCC source candidate readiness dry-run。下一步是完成樣本門檻、signal / alert / gate 文案與 dashboard disclosure 的人工驗證，並累積真實 weekly evidence operations history；這不代表投資有效性、V4 readiness、production scheduler approval 或自動交易，不得開新 ML production、不得改 `ScoringEngine` / threshold / portfolio / lifecycle、不得寫 production DB 或啟用 production scheduler。

**V3.0 Automated Readiness（2026-07-12）**：effectiveness、threshold robustness、component ablation、ML readiness 與 source candidate focused suite 已重新驗證 `26 passed`；readiness inspector 的 required artifacts 均存在且 `blocking_gaps=[]`。同次 sample report 仍揭露 recommendation 樣本不足、產業 benchmark 缺口與舊 screening-matrix payload 缺口，因此狀態維持 `ready_for_manual_validation`，不建立 formal closeout。完整自動驗證見 `docs/06_qa/V3_0_AUTOMATED_READINESS_2026_07_12.md`。

2026-07-12 V2.3 P0 Data Credibility 已建立 engineering readiness 與完整 Gate 3 逐來源人工接受台帳：除權息 / 除權與未登錄的減資 / 分割 / 面額變更、停牌 / 復牌、處置、分盤、全額交割、漲跌停鎖死、三大法人、信用交易、TDCC 與 PIT fundamentals 全數保留 `requires_human_acceptance`，`downstream eligibility=none`。每列現已明示 source version、as-of / available date、quality、license、rate limit、freshness / coverage、missing / outage、quarantine / retry、evidence / review / rollback，以及分離 owner / date；未記錄欄位不推定為可用。`decision_ready_candidate` 只表示候選列通過可得日 / 必填欄位診斷，不等於 accepted feature；既有 `corporate_action.ex_dividend_timeline` 僅涵蓋除權息 / 除權，不能被擴寫為減資 / 分割 / 面額變更 capability。`scripts/inspect_source_candidate_readiness.py --help` 已確認為 read-only dry-run，沒有 `--confirm`、評分寫入或 scheduler enablement。V2.3 formal closeout 仍缺逐來源真實人工決議（accepted / limited / rejected / deferred）、授權與品質 / PIT 審核；不得把本工程台帳解讀為正式 ingestion、`ScoringEngine` 接線、Advice / Portfolio eligibility、production scheduler、投資有效性或交易功能。

2026-07-08 Pre-V2 evidence closeout follow-up：`PreV2ReadinessService` 可用同一觀察日 scheduled evidence dry-run `latest_status.json` 作為 source-gap 修正後歷史觀察證據；採信條件固定為 `dry_run=true`、`writes_evidence_db=false`、source coverage / pipeline blocking gaps 皆為空且 `scheduler_readiness_after=ready_for_manual_confirm`。此 fallback 只讀 scheduled output，不寫 formal evidence DB、不觸發 confirm、不啟用 scheduler。實際對正式 DB 跑 `inspect_pre_v2_readiness.py --decision-date 2026-07-08` 時，source gaps 為 `ready`、read-only Agent report sample 為 `ready`，multi-day dry-run record 補入 2026-07-08 後為 `3/3 ready`；weekly evidence operations history 仍為 `0/3 waiting_for_time`，因此 overall 仍是 `waiting_for_time`，`production_scheduler_allowed=false`。

- **閉環 1：資料與市場狀態閉環** ✅ V1 已建立
  - Update → SQLite 狀態 → Market Watch / Smart Money（市場觀察子 Tab）→ 候選池
  - Phase 1 ✅ / Phase 2 ✅ / Phase 2.5 快速/安全更新分流 ✅ / Phase 2A/2B/2C SQLite DB-first ✅ / Phase 3 CSV 手動匯出 ✅
  - 數據更新工作台（Dashboard + 快速/安全更新分流）✅ / SQLite 儲存升級 ✅ / Smart Money Terminal MVP ✅ / 券商分點長碼解密與總公司判定 ✅ / MoneyDJ HTTP fast path 與交易日預檢 ✅ / Full App Healthcheck flow model 覆蓋 ✅

- **閉環 2：研究驗證閉環** ✅ V1 已建立
  - Recommendation Profile → Research Lab / Backtest / Replay / Walk-forward → Research Run Registry → Promote
  - Phase 3.1 ✅ / Phase 3.2 ✅ / Phase 3.3a ✅ / Phase 3.3b ✅ / Strategy Scoring Governance (增量 A & B) ✅
  - Research Lab 多模式實驗室 ✅ / Recommendation Portfolio Backtest credibility v1 ✅ / Backtest chart fast renderer ✅ / Research Run Registry M2-B 基礎保存 ✅ / Registry Cross-run 比較子頁 C2 ✅ / Registry-based Promote Gate C3 ✅
  - AI Runtime Subsystem MVP ✅ / Codex / Antigravity Agent 指引 ✅ / 回測 fixed-quantile 雙模式與 Expanding T-1 歷史門檻 ✅ / 推薦 eligible universe 橫斷面百分位排名與門檻限制 ✅
  - V1.1 workflow bridge v1 ✅：推薦分析已揭露 Profile 權重 / 技術分類 / 型態預覽 / 主要篩選條件；推薦回放文案明確區分「今日名單批次回測」與「Profile / Config 歷史重播」；`ProfileReplayComparisonService` 可在相同 replay 假設下比較多個 Profile 並輸出 promote / hold / demote_candidate / retire_candidate 候選標籤。這些標籤只作 Research Run / Evidence 後的人工 lifecycle 判讀，不會自動降級、退休或刪除策略版本。
  - V1.2 Research Credibility & Execution Model v1 ✅：`ProfileReplayComparisonService` 支援訓練 / 獨立驗證期間，驗證期結果主導 lifecycle candidate；推薦組合 replay 已補 rolling Sharpe / Sortino、VaR / CVaR、drawdown duration、turnover approximation、台股微結構 preflight 與 benchmark / industry / concept relative attribution。這些結果只用來揭露研究可信度與缺口，不會改交易、PnL、cash ledger、策略權重或自動升降級。

- **閉環 3：持倉檢查閉環** ✅ V1 已建立
  - Recommendation / Backtest → Portfolio → Condition Monitor / Chip Monitor → Journal / Lifecycle Review → 回到研究
  - Phase 4.1 Portfolio MVP 與深化 ✅：domain/service/test、Portfolio Tab、來源追溯 metadata、ConditionMonitor 複合警告與停損停利已實作
  - 策略版本與推薦來源追蹤視圖、目前價格對比、未實現損益計算已深化完成，且已修正 float 邊界合規漏洞與三層防禦策略版本串接 (2026-06-11)
  - Phase 4.2 Portfolio 籌碼監控與下鑽 ✅：新增籌碼監控 Tab 與追蹤分點表格，依淨買賣、集中度及連續天數評估風險（bullish/neutral/bearish），並實作🔍 下鑽主力流向按鈕與自動高亮定位功能 (2026-06-11)

- **效能與研究輸出（Phase 5）** ✅ SQLite 檢視器分頁與規格化 Excel 報告匯出已完成 (2026-06-14)
  - 圖表渲染優化 ✅ / 批次回測並行化 ✅ / SQLite 檢視器穩定分頁 ✅ / 規格化 Excel 報告匯出 ✅

- **閉環 4：每日決策工作台（Daily Decision Desk）** ✅ V1 已建立
  - Market Intelligence → Daily Decision Desk → Watchlist Trigger / Portfolio Alert / Research Input。
  - 目前主 UI 已接上「每日決策」工作區，各 section 已具備 snapshot 顯示框架；Market Regime、Market Breadth v1、Sector Rotation v1、Relative Strength / Liquidity Ranking v1、Watchlist Trigger v1 與 Portfolio Alert v1 已接主 UI。Market Breadth v1 由 SQLite `daily_prices` 推導多方 / 空方 / 持平、成交量擴散與新高新低等 metadata；Sector Rotation v1 由 SQLite `industry_indices` 推導領先 / 落後產業、5 / 20 日變化與輪動強度；Relative Strength / Liquidity Ranking v1 由 SQLite `daily_prices` 推導 5 / 20 日相對強度與平均成交金額，並揭露低流動性代碼；Watchlist Trigger v1 由 `WatchlistService` 與 SQLite `technical_indicators` 共同推導，可計算出個股強度 score_bp (RSI * 100) 與風險警示 risk_alert (偏離 RSI > 80 / < 20 或跌破 lowerband)。若指定日無資料或歷史不足（如 20 日相對強度未滿 21 個交易觀測值），會採用最近可用交易日或降級（quality 降級為 `DEGRADED`，並輸出 `relative_strength_liquidity_insufficient_history`）。Portfolio Alert v1 已接 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService`，可把條件監控與籌碼風險彙總成每日持倉警示；若籌碼資料缺失、估算或不可用，會透過 `quality / warnings` 降級揭露，不補值。Portfolio Alert Attribution v1 已將每筆持倉警示拆為來源標籤、condition status、chip risk level、reason tokens 與 data quality flags，使 Daily Decision Desk 能辨識警示來自進場假設失效、籌碼風險或資料品質缺口。Why Not / 風險提示 v1 由 `DecisionDeskRiskPromptService` 從既有 section DTO 的 quality、warnings、低流動性、相對弱勢、watchlist risk alert 與 portfolio alert 推導，不在 UI 層重算 scoring、screening、portfolio 或 liquidity。Month 4 收尾已新增 UI boundary contract test，確認 Daily Decision Desk UI 不直接 import domain 計算模組；2026-07-02 已完成第一輪 Midnight Analyst 全 UI 低風險視覺 polish，修缺字 icon、統一 token / 表格 / 按鈕 / 空狀態，且不改資料抓取、推薦、回測、每日決策 snapshot 或持倉計算語意。

- **治理閉環：Strategy Lifecycle / Portfolio Feedback** ✅ Month 6 v1 已建立
  - Research Run Registry → Month 6 lifecycle gate → promote / hold / demote / retire evidence → Portfolio Feedback → Portfolio Review → 回到 Research。
  - 已建立 `StrategyLifecycleService`、`LifecycleEvidenceRepository`、`PortfolioFeedbackService` 與 `PortfolioReviewService`；promotion 成功後保存 applied evidence，demote / retire 先保存 proposed evidence；持倉管理「生命週期回顧」可判讀 thesis 狀態、來源追溯、執行落差、訊號 / 市場 / 資料品質歸因。

- **交付治理閉環：V1 Release / Full App Healthcheck** ✅ V1 release gate 已通過
  - Full App Healthcheck → flow diagnostics → tab full bridge → MainWindow UI smoke → 人工 UI smoke → V1 checklist → `main` / clean clone gate。
  - `docs/06_qa/V1_RELEASE_CHECKLIST_2026_06_30.md` 已記錄 quick healthcheck、逐 tab full bridge、MainWindow UI smoke、人工 8 工作區 smoke、文件一致性、`main` 合入後 release gate 與 clean clone / install gate 均通過。此閉環屬工程交付信心，不代表投資訊號有效性。


- **文件治理與 Manual** ✅ 本輪完成
  - Roadmap Hub、6M Roadmap、V2.1-V4.0 Roadmap、Legacy Carryover、Architecture、Index 與 Agent 指引已採 Scoped SSOT。
  - 已建立 8 個頂層工作區的完整操作手冊；Daily Decision 嵌入主要工作流，不另計為頂層工作區。
  - 舊 Roadmap 工程欠項已全部取得「已完成 / Month X 移交 / 被取代」唯一處置；實作進度仍依 6M Roadmap 執行。

## 現在的工作模式（你每天要用的流程）

1. Update 使用「快速更新（跳過大型合併）」或「安全更新（完整 CSV + SQLite）」補齊資料，必要時用 SQLite Inspector 唯讀確認 freshness。
2. 每日先看 `決策工作台` 的中文優先 status strip、今日待判讀、背景證據流、依 severity / queue group / source 排序的只讀 Action Items、操作節奏、Evidence mode / data quality、Daily Checklist 與 warnings；操作節奏會把今天要看、人工處理、weekly history、多日 dry-run、manual review note 與 scheduler gate 區分清楚。需要細節時用 Workbench 的 read-only drill-down 切到 Daily Decision Desk、Evidence Review 或 Portfolio，或再進 Market Watch / Smart Money。
3. Recommendation 用 Profile 出名單 + 看 Why / Why Not / Profile 進階摘要 → 加入候選池，或送 Research Lab 批次回測 / 推薦回放；批次回測是測今日名單，推薦回放是重播 Profile / Config，Profile 比較應用訓練期提出候選，再看獨立驗證期結果。
4. Research Lab / Backtest 可跑單股、候選池批次、固定組合或推薦回放；推薦回放結果需同時讀 rolling risk、microstructure preflight 與 relative attribution，成功結果可保存到 Research Run Registry，只有通過 Registry 與 Month 6 lifecycle gate 才能升級策略版本。
5. Portfolio 用來追蹤實際或模擬持倉來源、條件監控、籌碼風險與生命週期回顧；警示與失效原因應回到 Research Lab / Registry 比較 / 覆盤日誌確認。

## Tech Lead 的預設任務（開場要先做什麼）

- 給出「下一步最合理的工程行動」與原因（不寫 code）
- 如需看程式碼：先提出要 review 的檔案清單與目的，等我授權 scope

## 本週優先事項（只列 3 個）

1. **Gate 2 真實 Evidence Operating Loop**：累積 weekly history、manual review note 與 action-item rhythm；Week 1 已完成，目前 weekly history 為 `1/3 waiting_for_time`，不可用 replay、fixture 或人工改表補足 Week 2 / Week 3。
2. **Gate 3 P0 Data Acceptance**：依 source-by-source diagnostics / shadow / acceptance 處理資料可信度；candidate source 不得接入 `ScoringEngine` 或 formal Advice。
3. **Gate 4 Portfolio Coach 與後續 effectiveness**：以 Gate 1 已完成的 read-only Advice 為契約基礎，先建立可驗證的 paper / evidence 流程；不串 broker、不宣稱投資有效或自動交易。

## 歷史優先事項（不作目前狀態依據）

> 此節內的 `1/3` 是當日歷史觀察，已由目前 multi-day `3/3 ready` 取代；weekly history 目前仍為 `0/3 waiting_for_time`，兩者均不構成 scheduler approval。

1. **V1 release baseline 已完成**：四個產品閉環、Month 6 Strategy Lifecycle / Portfolio Feedback v1、Full App Healthcheck / MainWindow UI smoke / clean clone gate 已形成可交付基準。下一步不是宣稱投資有效，而是進入 evidence-driven 驗證。
2. **下一階段主線：Evidence-Driven baldr + V1.1 / V1.2 / V1.3 / V1.4 / V1.5 / V1.6 / V1.7 / V1.8 / V1.9 v1 已完成**：Evidence Event Store v1 / Forward Outcome Calculator v1 / Evidence Importers v1 / E2E smoke / Forward Performance Read Model v1 / Daily Decision Desk durable snapshot source / source coverage inspection v1 / Forward Performance Dashboard read-only UI v1 / Evidence Pipeline Runner dry-run v1 / working-copy DB smoke v1 / scheduler approval checklist v1 / Live vs Research Gap linkage v1 / Signal Decay Monitor v1 / Decision Quality Review v1 / Evidence Review Dashboards read-only UI pack v1 / Evidence Review UI smoke checklist / multi-day dry-run record scaffold / safe scheduled CMD wrappers / V1.3 weekly evidence operations package / V1.4 weekly review history / V1.5 data credibility gate / V1.6 cross-sectional factor pipeline / V1.7 screening matrix negative evidence / V1.8 portfolio construction sandbox / V1.9 read-only Agent MCP evidence access / Pre-V2 非排程 readiness inspector / Phase 2 Workbench MVP 已建立；每日 05:30 Codex read-only 摘要、Evidence Review UI smoke 與 multi-day dry-run evidence 可開始背景累積。V1.1 已補推薦 Profile 可見性、推薦回放語意與 Profile replay comparison service；V1.2 已補 replay 訓練 / 驗證分離、rolling risk、microstructure preflight 與 relative attribution；V1.3 已補 manual approval summary、weekly review CLI、signal decay manual lifecycle candidate 與 action item planning；V1.4 已補 weekly review history repository、CLI save/list 與 Research Lab `覆盤歷史` 唯讀子頁；V1.5 已補 Data Source Capability Registry、corporate action / adjusted price policy、governed microstructure source metadata 與 centralized Evidence Source Coverage Service；V1.6 已補 daily factor snapshot DTO / repository / pipeline、concept basket available-date gate、integer factor rank / quantile 與 read-only attribution summary CLI；V1.7 已補 `RecommendationResultDTO.screening_matrix_json`、pass / fail / degraded / skipped / missing matrix、Why Not / Liquidity payload 保存、screening matrix evidence events 與 source coverage `screening_matrix_missing` warning；V1.8 已補 research-only portfolio construction service、整數 bp / Decimal / lot sizing allocation result、virtual order lifecycle trace 與 sample inspection CLI；V1.9 已補 read-only evidence access service 與 `twstock-evidence-access` MCP server；Pre-V2 檢查器已補 weekly history / multi-day record / source gaps / read-only Agent report sample 的唯讀彙總；Workbench 已在 Qt 呈現中文優先 status strip、今日待判讀、background evidence feed、read-only Action Items、read-only Operating Loop、Evidence mode / data quality、Daily Checklist、warnings / degraded source 與舊 Daily Decision / Evidence Review / Portfolio read-only drill-down。若預設 `_reference_fix` replay JSON summary 存在，Workbench 會自動以 summary 揭露 replay-derived source gap coverage、benchmark coverage 與 industry benchmark coverage；時間型 gate 仍會維持 `waiting_for_time`。Action Items 僅顯示人工待處理事項，Operating Loop 只顯示 daily first-look、manual queue、weekly history、multi-day dry-run、manual review note 與 scheduler gate；兩者都不建立 repository、不寫 DB、不標記完成、不套用 lifecycle。舊 recommendation 缺 matrix / payload 時仍只診斷、不回補、不重算；watchlist / portfolio 仍需真實 workflow 與樣本累積。Phase 2 UI / read-only operating loop 可收口；Phase 0 weekly history `0/3`、multi-day dry-run `1/3` 不能用 replay、fixture 或手動改表取代。V2.2 真實 evidence operating loop 與 production scheduler implementation 仍需 durable source coverage、人工 approval 與明確設計後才可進行。
   - Historical Evidence Replay v1 + Phase 0A reference fix 已可用 replay DB 逐日重放半年前至今日的 source coverage、snapshot capture、recommendation evidence 與 forward outcome maturity；新 `_reference_fix` 產物已解除 benchmark 全缺，仍揭露 industry / screening matrix payload gap。V2.0 Phase 1 prototype CLI 與 Phase 2 Qt Workbench shell 現可透過 `WorkbenchSourceService` 以 read-only adapter 讀取受控 DB path 的 Pre-V2 readiness、Daily Decision durable snapshot、AgentEvidenceAccess summary 與可選 replay JSON summary；它能提前暴露 source payload / no-look-ahead / Workbench 問題，但不把 weekly history `0/3` 或 multi-day dry-run `1/3` 視為已完成。
3. **維持 V1 安全邊界與資料治理**：Month 5 retroactive baseline / statement baseline 多數仍為 `degraded`，P/B / P/S 仍只接受 governed external observations 或後續明確 backfill records；策略、回測、推薦、factor 與 portfolio 改動仍需 no-look-ahead、Decimal / 整數單位與 release healthcheck 防線。

## 高風險區（改動需謹慎）

本節先列目前仍適用的高風險邊界；其後以日期開頭的里程碑段落均為歷史證據，不作目前 Gate 或時間型比例的權威。遇到 `1/3` 等舊觀察值，一律以本文件「Evidence 時間型 Gate 狀態校正」的目前值為準。

Month 6 v1 狀態（2026-06-17）：策略生命週期判斷只讀 Research Run Registry metadata、benchmark results、factor snapshot / contribution、regime breakdown 與 Portfolio 來源追溯。Promotion 不能只靠單次正報酬；run 必須通過交易次數、總報酬、Sharpe、回撤、勝率、benchmark excess return、factor quality 與 regime compatibility gate。Lifecycle evidence 採 append-only SQLite table 保存 decision snapshot / gate reasons / version id，可投影 latest state；demote / retire 會先形成 proposed evidence，不會自動刪除策略版本。Portfolio feedback 只輸出 post-trade attribution / live-vs-research gap，不會自動下單、平倉、改寫持倉或刪除歷史策略證據。

V1 release 狀態（2026-06-30）：`main` 已通過 release gate、quick healthcheck、MainWindow UI smoke 與 clean clone / install gate。這只代表 repo 可乾淨 clone、安裝、啟動、切換 8 個頂層工作區並完成主要非破壞式驗證；不得解讀為推薦、警示、策略或基本面 diagnostics 已通過投資有效性驗證。

Post-V1 evidence 增量狀態（2026-07-03）：`app_module/evidence_event_*`、`app_module/evidence_capture_service.py`、`app_module/evidence_event_importers.py`、`app_module/forward_performance_service.py`、`app_module/forward_performance_read_model.py`、`app_module/forward_performance_dashboard_*`、`app_module/evidence_pipeline_runner.py`、`app_module/evidence_scheduler_readiness.py`、`app_module/live_research_gap_*`、`app_module/signal_decay_*`、`app_module/decision_quality_*`、`app_module/evidence_operations_*`、`app_module/evidence_operations_history_*`、`app_module/*_dashboard_*`、`app_module/decision_desk_snapshot_*`、`data_module/evidence_event_migration.py`、`ui_qt/views/evidence_review_view.py`、`ui_qt/views/evidence_operations_history_view.py`、`ui_qt/views/forward_performance_view.py`、`ui_qt/views/live_research_gap_view.py`、`ui_qt/views/signal_decay_view.py`、`ui_qt/views/decision_quality_view.py` 與 CLI 已建立，可在受控 SQLite schema 下保存 evidence events / outcomes / Daily Decision Desk durable snapshot / live research gap observation / signal decay observation / decision quality review / weekly review history，於 Research Lab `Evidence Review` 分頁唯讀檢查 Forward Evidence、Live vs Research Gap、Signal Decay、Decision Quality 與覆盤歷史的樣本、pending / missing、benchmark / industry 缺口、source trace、match confidence、lifecycle candidate、process score、weekly status、scheduler readiness、quality 與 warnings，並用 `scripts/run_evidence_pipeline.py` 手動模擬每日 evidence pipeline。`scripts/build_evidence_operations_weekly_review.py` 可彙總 scheduler readiness、Decision Quality、Signal Decay 與 action item，產生 V1.3 weekly review / manual approval package；V1.4 可用 `--save-history` 保存 weekly review history，並以 `--list-history` 檢查。樣本不足時只輸出 `coverage_only` 與資料品質缺口。CLI 預設 dry-run，只有 explicit confirm 才寫 working-copy DB 或 append-only action item；history 保存也需要 explicit `--db-path`；`scripts/evaluate_evidence_scheduler_readiness.py` 與 weekly review package 都固定 `production_scheduler_allowed=false`。此狀態不代表任何事件類型已累積足夠樣本，也不代表 alpha 成立；scheduler readiness 最高只到 `ready_for_manual_confirm`，production scheduler 仍未啟用，完整實帳歸因與投資有效性結論尚未完成。

2026-07-06 Historical Evidence Replay v1 已完成：`app_module/historical_evidence_replay.py`、`scripts/replay_historical_evidence_pipeline.py` 與 focused tests 可在 replay DB 重放指定日期區間；`EvidencePipelineRunRequest` / `EvidenceCaptureRequest` 已可傳遞 replay context，`EvidenceCaptureService` 會把 replay metadata 保存到 payload metadata，`ForwardPerformanceService.calculate(data_as_of_date=...)` 會限制 outcome price search。此功能不修改既有 scheduled dry-run wrapper，不建立新 Windows task，不寫正式 DB。

2026-07-06 Phase 0A replay quality audit 已完成：初版半年度 replay 的 ready outcomes 全部缺 benchmark / industry reference return，根因是 replay events 無 `benchmark_id` / `industry_benchmark_id`，且 `market_indices` 實際 close 位於 `收盤價`；修正後 benchmark return / excess 在 ready outcomes 全部填入，industry 只在 sector payload 可映射時填入。`docs/06_qa/POST_V1_HISTORICAL_EVIDENCE_REPLAY_QA_2026_07_06.md` 已記錄 root cause、tests、look-ahead check 與 rerun summary。

2026-07-06 Pre-V2 非時間型 closeout 已完成：Git unreachable loose objects 已由 `count=6657` 清為 `count=0`，10 個 unreachable commits 先保留於 `refs/recovery/unreachable-*`；RecommendationService 已補成交量門檻造成空結果時的 `liquidity_volume_ratio_below_min` / Liquidity payload；ignored working-copy DB + output mirror 已驗證 2026-07-03 all-source source coverage `blocking_gaps=[]`，Recommendation / screening matrix / why-not / liquidity / watchlist / portfolio / risk prompt 皆 capture-ready；all-source working-copy confirm smoke repeat=2 idempotency passed（events 3049、outcomes 12196 第二輪穩定）；Evidence Review UI smoke passed；read-only Agent report sample ready。`inspect_pre_v2_readiness.py` 對該 working-copy 的整體狀態仍為 `waiting_for_time`，因 weekly history 目前 `0/3`、multi-day dry-run record 目前 `1/3`；formal evidence DB 未寫入，production scheduler 仍未啟用。

2026-07-07 Phase 4 Execution Model Realism Extension 已完成：Portfolio Sandbox 中實作台股跳動單位 (Tick) 滑價模型，並完整閉環零股限制 (Lot Sizing) 與拒絕原因 (Rejected Taxonomy)。
2026-07-07 Phase 3A / 3B Corporate Action & Trading Restriction Candidate Dry-run 已完成：新增 `CorporateActionPolicy` 與 `TradingRestrictionPolicy`，將 corporate action (ex-dividend) 與 trading restriction (處置股、分盤、全額交割、漲跌停鎖死、停牌) 狀態提升至 `CAPABILITY_PARTIAL`。實作安全降級 (missing db / table)，將 forward outcome data quality 標示為 `DEGRADED` 並附加 `gap_detected` warning。Sandbox 可透過 policy 查詢將限制轉譯為 `rejected_price_limit_locked` 或 `rejected_trading_restricted`，完善 Phase 4 的 rejected taxonomy。此為 candidate-only 觀察層，不改分數、不改價格。
2026-07-08 Phase 3C Source Candidate Readiness Dry-run 已建立：新增 `SourceCandidateReadinessService` 與 `scripts/inspect_source_candidate_readiness.py`，可對三大法人、信用交易與 TDCC / 集保庫存輸出 candidate readiness。並且已實作 `official_phase3c_fetcher.py` 直連證交所、櫃買中心與集保所官方 API。該爬蟲腳本已擴充 `update_phase3c_candidates_range` 為 **manual-only candidate ingestion groundwork**。缺 DB、缺 table、缺 `available_date` 會 fail-closed / degraded，`available_date > decision_date` 會標示 `future_data_blocked`。此層固定 `writes_allowed=false` (除非帶 token)、`production_scheduler_allowed=false`、`scoring_engine_write_allowed=false`、`investment_effectiveness_claim=false`；這不屬於 V3.0 closeout gate，沒有掛載入一鍵更新，沒有接 `ScoringEngine`、沒有改推薦 threshold、沒有啟用 scheduler。
2026-07-07 Phase 2 Workbench UI / read-only operating loop 已完成並可進入 closeout：Qt 主 UI 新增 `決策工作台`，資料只經 `WorkbenchSourceService` / `WorkbenchDashboardDTO`，中文優先呈現 status strip、今日待判讀、background evidence feed、read-only Action Items、read-only operating loop、Evidence mode / data quality、Daily Checklist、warnings / degraded source，並提供舊 Daily Decision / Evidence Review / Portfolio 的 read-only drill-down。Background evidence feed 彙整 Daily Decision snapshot、Evidence Review readiness、Portfolio alerts 與 replay summary diagnostics；Action Items 僅列人工待處理事項，每列帶 source trace、degraded reason、drill-down target、queue group、source label 與 `write_intent=false`，並依嚴重度 / 佇列 / 來源排序以利人工掃描。Operating Loop 只從既有 DTO payload 推導每日先看、人工處理佇列、weekly review history、multi-day dry-run、manual review note 與 scheduler gate，不寫 DB、不標記完成、不套用 lifecycle。Action Items 與 Evidence Feed 的空狀態 / 降級狀態文案會提醒「DTO payload 為空不代表 gate 通過」、「降級來源不補值」、「不是買賣建議」。若預設 `_reference_fix` replay JSON summary 存在，UI 會自動傳入 `WorkbenchSourceService`，但不直接讀 replay DB 或執行 replay；目前 summary 顯示 118 天、118,056 events、472,224 outcomes，成熟 outcomes 380,736，pending future-data 91,488，market benchmark coverage 380,736/380,736，industry benchmark coverage 2,245/380,736，`source_missing_screening_matrix` 為 118/118 days。這代表方向性 evidence pipeline 正在變好，但仍不構成 production readiness 或投資有效性。此 Workbench closeout 不重算 scoring、portfolio、backtest、lifecycle，不產生買賣建議，不建立 action item repository，不寫 DB，不解除 weekly history `0/3`、multi-day dry-run `1/3` 或 scheduler approval gate。

2026-07-07 UI IA closeout：Qt 主 UI 已由上方主 tab 改為左側主導覽，預設主工作區為 `決策工作台`，主工作區順序為 `決策工作台`、`市場探索`、`推薦分析`、`策略回測`、`觀察清單`、`持倉管理`、`數據更新`、`Runtime`。左側 rail 已從兩字母縮寫升級為自製線條 SVG icon，並保留 icon-only 收合模式，以支援小螢幕掃描與橫向空間。`每日決策` 不再是頂層主工作區，已嵌入 `決策工作台 > 決策來源`；原 `市場觀察` 重新定位為 `市場探索`，內部仍保留大盤指數、強弱勢、強弱產業與主力流向子頁，弱勢個股 / 弱勢產業的 `跌幅%` 以正數顯示下跌幅度並用紅色呈現。Workbench 內部子頁為 `總覽`、`決策來源`、`Evidence`、`持倉追蹤`、`操作節奏`；總覽頂部新增四個指揮台摘要 block，顯示今日待判讀、人工待處理、等待真實時間與 Warnings，並保留一致上 / 左 gutter。今日待判讀佇列為空時會顯示空狀態並引導前往市場探索，雙擊 queue row 只在本次 UI session 標記已查看，不寫 DB、不標記完成、不改 lifecycle。Evidence / 持倉追蹤 / 操作節奏目前是摘要與下鑽入口 / 預留深挖區，不代表完整功能或正式資料 gate 已完成。Runtime Observatory 已改為緊湊 scope note + 上移狀態面板，避免大片空白。此 UI closeout 未修改 scheduled wrappers、scheduled output schema、morning report、Pre-V2 readiness 或 simulated phase progress contract；Phase 0 weekly history `0/3` 與 multi-day dry-run `1/3` 仍必須等正式資料與真實時間累積後才能標示完成。

Post-V1 safe scheduled wrapper 狀態（2026-07-04）：`scripts/scheduled/` 已新增 CMD wrapper + Windows `schtasks.exe` 註冊路徑，以避開 PowerShell `.ps1` 被 local execution policy 擋住的問題；不得使用 `Set-ExecutionPolicy`。Windows Task Scheduler 已建立 `baldr-data-update-quick-daily`（每日本機時間 04:20，非 UI 快速資料更新）、`baldr-data-freshness-check-daily`（每日本機時間 05:00，只讀 freshness）與 `baldr-evidence-pipeline-dry-run-daily`（每日本機時間 05:15，只跑 dry-run report）。`baldr-evidence-working-copy-smoke-manual` 只保留 manual-only script，不建立每日自動 task。Codex app 已另建 `baldr scheduled evidence morning report` automation（約 05:30），只讀 Task Scheduler 狀態、latest status、最新 report 與必要 log，產生繁體中文摘要；它不重新執行 data update / freshness / evidence pipeline、不建立或修改 Windows task。這些 wrapper 會寫 `<OUTPUT_ROOT>/scheduled/...` 的 status / log / report；data update quick task 會寫市場資料 CSV / SQLite，但不寫 production evidence DB、不跑 UI、不讀 UI state、不做 portfolio / lifecycle action。Production write-mode evidence schedule 仍未啟用，後續仍需 multi-day dry-run record 與 explicit approval。

2026-07-06 更新補充：data update quick / UI 更新流程已修正 TPEX 缺日判讀；若 TPEX 當日或窗口內日期抓取失敗，即使先前日期已有 CSV 被 skipped，也會回報 `TPEX 每日股價缺少日期：YYYYMMDD`，UI 結果標示未完整，scheduled data update status 會是 `passed_with_warnings`。data freshness probe 也會在 SQLite 最新日反查 `daily_price/YYYYMMDD.csv` 與 `daily_price_tpex/YYYYMMDD.csv`，若 TPEX 原始日檔缺失則標示 `degraded`。

2026-07-02 scheduled evidence manual run 已記錄到 multi-day dry-run record：`baldr-data-freshness-check-daily` 與 `baldr-evidence-pipeline-dry-run-daily` 的 manual trigger 均成功且 Last Result = 0；freshness `passed`、latest date `20260702`、無 warnings / blocking gaps；evidence dry-run `passed` 但 `overall_status = degraded`，blocking gaps 為 `decision_desk_snapshot_missing`、`why_not_exclusion_payload_missing`、`liquidity_gate_payload_missing`。整體仍維持 `dry_run = true`、`confirm = false`、`writes_evidence_db = false`，沒有 production DB write、沒有 auto trading、沒有 lifecycle action、沒有買賣建議。

2026-07-03 weekly evidence operations + history working-copy run 已完成第一個 operating-cycle：期間 2026-06-29 至 2026-07-03，使用 ignored `tmp/evidence_ops_20260703/evidence_ops_working.db`，weekly review status 為 `coverage_only`、scheduler readiness 為 `not_ready`、`production_scheduler_allowed=false`；history record `eor_8d1643ae9fc02bd8` 已保存且重複 `--save-history` 後仍只有 1 筆。初始 blocking gaps 為 `decision_desk_snapshot_missing`、`recommendation_persisted_missing`、`working_copy_confirm_smoke_missing_or_failed`；warnings 為 `why_not_payload_missing`、`liquidity_gate_payload_missing`。同日 follow-up 已修正 batch / CLI snapshot wiring，working-copy snapshot 可看到 `market_regime`、`market_breadth`、`sector_rotation`、`relative_strength_liquidity` 與 `risk_prompt`，`risk_prompt_capture_ready=true`，DDD working-copy confirm smoke 重跑 `repeat=2` 後 idempotency passed（895 events / 3580 outcomes，不新增 duplicate events）。後續受控 tmp run 保存 `rec_working_copy_20260703_regime_default`（20 筆 recommendation），`recommendation,risk-prompt` requested runner 重跑後 `events_inserted=0`、`events_skipped_duplicate=915`；final working-copy count 為 `evidence_events=915`、`evidence_outcomes=3660`。2026-07-05 V1.7 後，新保存的 Recommendation result 會保存 screening matrix 與 Why Not / Liquidity payload；舊 recommendation 若缺 matrix / payload，source coverage 會列 `screening_matrix_missing`、`why_not_payload_missing`、`liquidity_gate_payload_missing` warnings / `dry_run_only`，capture 只回 diagnostic，不回補、不重算。2026-07-05 V1.8 後，portfolio sandbox 只建立研究配置與虛擬 execution trace，不寫 production evidence DB、不建立實帳 order、不改 Portfolio position。durable source blocking gap 仍以 persisted recommendation、Daily Decision Desk snapshot section、working-copy smoke 與真實 watchlist / portfolio workflow 為主。production scheduler 仍未啟用。

Month 5 Revenue Factor Pack 最新覆寫註記（2026-06-16）：正式 `fundamental_monthly_revenues` 已回填 1,848 筆 2026-05 MOPS records，不再是缺月營收狀態。新增 `scripts/inspect_fundamental_factors.py` 唯讀檢視入口後，以 `decision_date=2026-06-30` 掃描全月營收股票得到股票數 1,848、factor records 4,464、diagnostics 3,696；月營收可產生 `fundamental.revenue_3m_trend` 1,848 筆與 `fundamental.revenue_new_high` 1,848 筆，YoY / MoM 因正式 DB 目前只有 2026-05 單月而回 `fundamental_revenue.baseline_missing` diagnostics。此流程不寫資料、不接 `ScoringEngine`；後續仍須補更多月份的 governed monthly revenue baseline，不應把不足資料期間的 YoY / MoM 視為可用高信心訊號。

Month 5 retroactive baseline 最新補充（2026-06-16）：新增 `scripts/build_monthly_revenue_retroactive_baseline_mapping.py`，可從 MOPS snapshot 產生 `manual.retroactive_baseline_mapping` 候選 mapping；此 source 只代表「導入日後可使用的歷史 baseline」，不是官方歷史公告日，quality 為 `degraded`，不得用於導入日前回測。以 `2014-04..2026-04`、`available_date=2026-06-17` 產生候選時，candidate / validator accepted / dry-run normalized 均為 242,651 筆、diagnostics 0。依人工確認正式 apply 後，`fundamental_monthly_revenues` 為 244,499 筆、期間 `2014-04..2026-05`、股票數 1,848、period 數 146、0 duplicate，quality 分布為 242,651 筆 `degraded` 與 1,848 筆 `observed`，DB 備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_mops_monthly_revenue_backfill_20260616_224147.db`；Revenue Factor Pack 可產生 YoY 1,843、MoM 1,842、3M trend 1,848、new high 1,848，剩餘 diagnostics 11 筆。

Month 5 季度財報 gate 最新補充（2026-07-27）：季度財報 availability loader / validator / normalized parser / backfill workflow 的正式 mapping 預設路徑為 `DATA_ROOT/meta_data/fundamental_statement_availability.csv`。允許來源新增 limited research-only `mops.ezsearch.statement_publication`；其官方秒級 timestamp 轉成 date-only mapping 時採次一曆日，具官方 timestamp 的延後申報採實際公告日，不受 120 天推定窗口誤殺。既有 `manual.statement_available_date_mapping`、`tej.statement_announcement_pit` 與 `manual.retroactive_statement_baseline_mapping` 仍保留，raw statement CSV source 仍會被拒絕。2026-06-17 retroactive apply 的正式資料現況未被本次改寫：`fundamental_statement_items` 期間 `2014-Q2..2024-Q1`、股票數 1,567、period 數 40、0 duplicate，quality 全為 `degraded`；本次 MOPS artifact 只在 TEMP/shadow，未寫正式 mapping 或 SQLite。EPS / 毛利率 / 營益率 / ROE / 業外損益仍只接 factor records / diagnostics，不接 `ScoringEngine`。

Month 5 基本面 factor layer 收尾（2026-06-17）：季度財報已接入 `FundamentalSQLiteProvider` 與 `FundamentalFactorService`，新增 EPS、gross margin、operating margin、ROE、non-operating income ratio factor adapters；各指標只輸出 factor records / diagnostics，不輸出 score、不接 `ScoringEngine`。正式 DB `decision_date=2026-06-30` inspection 結果為 factor records 14,840、diagnostics 812；statement factors 分別為 EPS 1,411、gross margin 1,368、operating margin 1,374、ROE 1,277、non-operating income ratio 1,261。P/B / P/S source policy inspection 已改為 guarded ready：只接受 governed external observations 或後續明確 backfill records，不在系統內推導估值分子 / 分母，也不接 ScoringEngine。

Month 5 月營收 availability mapping 最新補充（2026-06-17）：已新增 `data_module/monthly_revenue_availability_history.py` 與 `scripts/build_monthly_revenue_availability_history.py`，支援 `--start-period 2020-01`、`--end-period 2026-05`、`--markets twse,tpex`、`--stock-code`、`--mops-html-dir`、`--mops-static`、`--pit-csv` 與候選 CSV output。TWSE `/opendata/t187ap05_L` 與 TPEX `/openapi/v1/mopsfin_t187ap05_O` 最新月來源都有 `出表日期`，樣本 `2330`、`9935`、`3207` 已驗證；但 OpenAPI 未提供歷史 period query。MOPS historical static report 可透過新版 `/mops/api/redirectToOld` 取得 `mopsov.twse.com.tw/nas/t21/...` HTML，`113/04` 上市/上櫃彙總表可解析到 `2330`、`9935`、`3207` rows，但頁面 `出表日期` 是查詢當日重新出表日，不是原始公告日；builder 與 validator 已用 `as_of_date + 45 days` 合理揭露窗口擋下這類過晚日期。免費官方來源目前仍未找到可批次追溯原始歷史公告日的路徑；TEJ point-in-time 月營收公告日列為授權匯出候選來源，`--pit-csv` 必須搭配非空 `--pit-source-version`，且只產生 candidate mapping。`--mops-html-dir` 可讀人工保存且含 `出表日期` 的 MOPS 官方 HTML，source 為 `mops.monthly_revenue_announcement`，缺 `出表日期` 或公司列時 fail-closed diagnostics。本機 raw 月營收期間為 `2014-04..2024-04`，與最新月 `2026-05` 來源無交集；`2020-01..2026-05` OpenAPI dry-run 結果為 `requested_periods=77`、`fetched_periods=1`、`matched_raw_monthly_revenue_rows=0`、`missing_availability_rows=76902`、`duplicate_mapping_rows=0`。正式 mapping 寫入與 `fundamental_monthly_revenues` apply 仍需人工確認。

Month 5 月營收候選資料抓取補充（2026-06-16）：新增 `scripts/fetch_mops_monthly_revenue_snapshot.py` 與 `scripts/fetch_finmind_monthly_revenue_create_time.py`。前者抓 MOPS 完整市場月營收 snapshot，保存 raw HTML 與營收值 candidate CSV，不推定官方公告日；若自某日開始每日保存 MOPS snapshot，該日可作本機 first-seen observation candidate，並以 `first_seen+1 calendar day` 作保守 candidate mapping。後者以 FinMind token 逐檔抓 `TaiwanStockMonthRevenue.create_time`，輸出 create_time 分組與候選 `available_date_candidate=create_time+1 calendar day`，但 create_time 只代表 FinMind 觀測 / 入庫日，目前退為備用 / 交叉檢查與每月分批更新依據。MOPS snapshot 已補齊 `2014-04..2026-05`、twse/tpex 共 292 個 raw HTML，候選 CSV 244,499 rows、0 duplicate `(market, period, stock_code)`；2026-05 MOPS first-seen candidate validator accepted 1,848 筆，`--mops-snapshot-file` backfill dry-run 為 `ready_for_apply=true`、normalized 1,848 筆、diagnostics 0，且 normalized source 保留 `mops.monthly_revenue_static_snapshot`。依使用者確認後，正式 `DATA_ROOT/meta_data/monthly_revenue_availability.csv` 已寫入 1,848 筆 MOPS first-seen mapping，`fundamental_monthly_revenues` 已回填 1,848 筆 2026-05 records，期間 `2026-05..2026-05`、股票數 1,848、0 duplicate `(stock_code, period, source_version)`，DB 備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_mops_monthly_revenue_backfill_20260616_203031.db`。主 UI「資料更新」頁已新增「月營收」分頁，可從 MOPS snapshot 執行 dry-run 或確認後正式寫入 SQLite。毛利率屬 MOPS 季度財務比率 / 財報資料，不納入今晚月營收流程。

- 金融核心數值計算與邊界（如交易成本、手續費、PnL、持倉 average_cost）：改動需極度謹慎，且必須通過 `scripts/check_financial_float_boundaries.py` 及 pytest repository gate 的自動防回歸掃描。
- `app_module/backtest_service.py` / `backtest_module/*`
- `app_module/recommendation_service.py`
- `decision_module/scoring_engine.py` / `decision_module/strategy_configurator.py`
- `decision_module/factors/*`（Factor Contract、available_date gate、fundamental adapter 邊界）
- `app_module/strategies/*`（fixed / quantile 門檻、確認天數與 Look-ahead 契約）
- `app_module/recommendation_replay_service.py` / `app_module/recommendation_portfolio_backtest_service.py`
- `app_module/portfolio_construction_service.py` / `app_module/portfolio_execution_trace_service.py`（V1.8 research-only allocation / virtual execution trace；不得解讀為 broker order）
- `app_module/agent_evidence_access_service.py` / `mcp_servers/evidence_access_server.py`（V1.9 read-only Agent evidence access；不得寫 DB、不得改策略、不得下單、不得套用 lifecycle action）
- 推薦 / 固定組合回放的現金帳、再平衡、Liquidity / Gap 標記、rolling risk、微結構 preflight 與 relative attribution（Month 3 / V1.2 v1 已完成；零股、買賣價差、完整撮合與 Gap 實際成交模型仍屬高風險 residual）
- `app_module/research_run_service.py` / `app_module/research_run_repository.py`（Research Run Registry metadata、Parquet hash、archive / promoted guard）
- Strategy registry / preset / promotion 相關服務
- UI ↔ service contract（DTO）
- `runtime/` 核心子系統與 FSM 狀態機
- `ui_qt/widgets/fast_chart_widget.py` / `ui_qt/widgets/chart_payloads.py`（回測圖表 renderer 與資料 payload contract）
- `ui_qt/views/update_view.py` / `app_module/update_service.py`（數據更新工作台與安全更新流程）
- `portfolio_module/core.py` / `app_module/portfolio_condition_monitor.py`（Portfolio domain 與條件監控）
- Daily Decision Desk / Market Breadth / Sector Rotation / Watchlist Trigger / Portfolio Alert 聚合層（`MISSING` / `DEGRADED` / `ESTIMATED` 可降級，實作時不得在 UI 複製 domain 計算）

分位數治理的額外風險：

- 回測 T 日門檻只能使用 T-1 以前的分數，禁止使用完整期間分布。
- 推薦橫斷面排名必須先固定當日 eligible universe。
- 舊策略未提供 `threshold_mode` 時必須維持 fixed，確保歷史回測可重現。

## 指定權威文件（需要細節再看）

- `DEVELOPMENT_ROADMAP.md` - Roadmap Hub，指向目前狀態、6 個月路線、架構與 archive。
- `ROADMAP_6M_ENGINEERING.md` - 未來 6 個月可執行工程路線。
- `VERSION_ROADMAP_V1_1_TO_V2_0.md` - V1 release 後至 V2.0 的版本化交付節奏，說明 V1.1 workflow bridge 與 V2.0 Unified Decision Workbench 邊界。
- `VERSION_ROADMAP_V2_1_TO_V4_0.md` - V2.0 之後的長期版本階梯，將 Workbench MVP、Evidence operating loop、資料源 dry-run、execution realism、scheduler approval、evidence-validated decision system 與 investment effectiveness maturity 對應為 V2.1-V4.0 companion。
- `EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md` - 外部開源專案參考、資料源補強優先序、V1.5 至 V2.0 版本形狀與 deferred 技術邊界；不取代 Vision 或 6M Roadmap。
- `../01_architecture/system_vision_specification.md` - baldr 產品北極星、目前邊界、Gap Register 與投資有效性驗證框架；不作為目前可用功能依據。
- `LEGACY_ROADMAP_CARRYOVER.md` - 舊 Roadmap 未完成事項的逐項移交與結案 Gate。
- `DOCUMENTATION_INDEX.md` - 文檔索引。
- `DOCUMENTATION_STRUCTURE.md` - docs 資料夾歸屬、生命週期、刪除/歸檔規則。
- `DOC_COVERAGE_MAP.md` - 文檔覆蓋矩陣與 scoped authority 規則。
- `../01_architecture/system_architecture.md` - 目前系統架構與模組邊界。
- `../07_guides/APPLICATION_MANUAL.md` - 目前 8 個工作區的完整操作手冊。
- `../../PROJECT_NAVIGATION.md` / `../../PROJECT_INVENTORY.md` - 專案導航與盤點。
- `../09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md` - 舊完整 Roadmap，僅供歷史追溯。
- `../superpowers/specs/2026-06-13-strategy-scoring-governance-design.md` - fixed / quantile 雙模式與分位數安全契約。
- `../06_qa/WALK_FORWARD_COMPARISON_REPORT.md` - Fixed / quantile OOS 實證、Regime 分層與 Gate 證據。

---

**注意**：此 Snapshot 是目前狀態入口；未來方向請看 6 個月工程 Roadmap，架構細節請看 system architecture，完整歷史請看 archive。

## 歷史完成紀錄（依實際完成順序）

> 本節以 Git 提交日與 closeout 證據為排序依據，採「由舊到新」。同日多項成果視為同一批次，不再以章節先後暗示更細的完成先後；跨日工作以完成區間標示。下方保留既有成果全文供查證；日期與先後一律以本表為準。

| 實際完成日 | 成果 |
|---|---|
| 2026-05-27 | Recommendation Portfolio Backtest 穩健性、圖表、SL/TP 與 research run 補強 |
| 2026-05-30 | SQLite 儲存、日期／大盤 Bug 修復、全量技術指標重算與讀取加速 |
| 2026-06-02 | 安全更新 Phase 1 CSV → SQLite 同步補強 |
| 2026-06-03 | SQLite DB-first／Inspector、CSV 匯出、Smart Money UI 與 UpdateView 重構 |
| 2026-06-04 | Research Lab 工作流重整 |
| 2026-06-09 | Roadmap Rebaseline（歷史基線） |
| 2026-06-10～2026-06-11 | 金融數值邊界、回測時間軸、Portfolio 4.1／4.2、券商分點單位契約與更新分流 |
| 2026-06-12 | 券商分點 Ranked Metric 治理、批次回測並行化與 Strategy & Scoring Governance 機制 closeout |
| 2026-06-13～2026-06-14 | Walk-forward OOS 修正／實證、舊測試治理、SQLite Inspector 分頁與 Excel 匯出 closeout |
| 2026-06-24 | 券商分點 MoneyDJ HTTP fast path |
| 2026-07-02 | V1.1 Workflow Bridge 與 V1.2 Research Credibility / Execution Model v1 |
| 2026-07-04 | V1.5 Data Credibility & Corporate Action Gate v1 |
| 2026-07-05 | V1.6 Cross-sectional Factor Pipeline v1 |

### 成果明細

## 2026-06-14 舊測試治理與模組責任確認

- repo 根目錄已建立正式 `pytest.ini`，預設只收集可重現的自動測試；
  `tests/manual/` 與 `tests/scripts/` 明確排除。
- 早期測試引用的 `DataConfig`、`DataProcessor` 並非被移除後遺失功能的正式
  API。現行責任由 `TWStockConfig`、`DataLoader`、
  `TechnicalIndicatorCalculator` 與各領域 service 分工承接。
- `PatternAnalyzer`、`TechnicalAnalyzer` 仍為現行功能，正式路徑分別位於
  `analysis_module.pattern_analysis` 與 `analysis_module.technical_analysis`。
- 固定真實路徑、外部網路、互動輸入、繪圖與長時間訓練腳本已移至
  `tests/manual/` 並標示棄用，不再阻塞 pytest collection。
- 設定、DataLoader 與技術分析測試已改寫為現行 API、正式資料 schema 與
  `tmp_path` 隔離契約；完整 pytest 為 `344 passed`。

## 2026-06-09 Roadmap Rebaseline（歷史記錄）

- 當時 Roadmap current section 從舊線性 Phase 敘事重寫為三個產品閉環（資料與市場狀態、研究驗證、持倉檢查）+ Backlog + 技術治理 Next。
- Phase 4.1 已標記為「Portfolio MVP 已建立，深化仍在進行」；Phase 5 圖表渲染已標記完成，其餘項保留。
- 當時本週優先事項改為 Rebaseline → 回測時間軸契約 → 金融核心數值治理。
- Blockers / Risks 新增回測時間軸未定義、金融核心裸 float、文檔不一致三項。
- 高風險區新增 `portfolio_module/core.py` 與 `app_module/portfolio_condition_monitor.py`。
- 指定權威文件新增 `NEXT_ACTION_PLAN.md`。

## 2026-07-02 V1.1 workflow bridge v1 成果

- **推薦 Profile 可見性補齊**：推薦分析的 Profile 說明區已揭露權重、技術分類、型態預覽與主要篩選條件，明確指出三個內建 Profile 不只是 buy / sell score 門檻不同。
- **推薦回放語意補齊**：推薦頁後續操作文案與 tooltip 已區分「送 Research Lab 批次回測」測今日名單，以及「送 Research Lab 推薦回放」重播 Profile / Config 歷史決策。
- **Profile replay comparison service**：新增 `ProfileReplayComparisonService` / DTO，可在共用 replay 假設下比較多個 Profile 結果並輸出 lifecycle candidate label；service 只消費注入 runner 的結果，不重算策略、不寫 DB、不自動升降級。
- **驗證**：已通過 focused pytest、UI update workbench pytest、Update Tab QA、py_compile 與 mypy。此成果只完成 V1.1 workflow bridge v1，不代表推薦、Profile 或策略具備投資有效性。

## 2026-07-02 V1.2 Research Credibility & Execution Model v1 成果

- **Profile replay 訓練 / 驗證分離**：`ProfileReplayComparisonRequest` 支援 `validation_start_date` / `validation_end_date`，且驗證期必須晚於訓練期；比較列保留 training / validation metrics，lifecycle candidate 以獨立驗證期為主，不用同一段資料同時調參與宣稱有效。
- **推薦組合 rolling risk 指標**：`RecommendationPortfolioBacktestService` 會在 result details 輸出 `rolling_risk_metrics`，包含 rolling Sharpe / Sortino、VaR / CVaR、max drawdown duration observations 與 turnover approximation；這些指標只讀已產生的 equity curve / holdings，不改交易、現金帳或 PnL。
- **台股微結構 preflight**：推薦回放會檢查歷史資料中可選的處置股、分盤交易、全額交割、漲跌停鎖死與除權息欄位；缺欄位時以 `missing_optional_sources` 揭露，不偽造、不補值、不寫資料。
- **Relative attribution v1**：推薦回放會在 `relative_attribution` 中揭露 benchmark / industry / concept 的相對歸因與缺失來源；僅使用 replay 期間 history 中可選參考欄位，不重抓目前資料。
- **驗證與邊界**：已通過推薦組合回放與 Profile replay comparison focused pytest、py_compile、targeted mypy、金融 float boundary 掃描與 diff check。V1.2 v1 仍不是實盤撮合模型；零股、買賣價差、完整委託簿撮合、Gap 實際成交價格調整與正式處置股 / 分盤 / 全額交割資料源接入仍是 residual。

## 2026-07-04 V1.5 Data Credibility & Corporate Action Gate v1 成果

- **Data Source Capability Registry v1**：新增 `data_module/data_source_capability_registry.py` 與 `scripts/inspect_data_source_capabilities.py`，以 read-only registry 記錄 price / evidence / corporate action / microstructure source 的欄位、status、available-date policy、quality policy、missing policy、license / rate-limit note 與 warnings。
- **Corporate action / adjusted price policy**：新增 `data_module/corporate_action_policy.py` 與 `scripts/inspect_corporate_action_policy.py`，明確標示 raw price 是目前 decision layer 預設；full hindsight adjusted price 不得進決策特徵；decision-date adjusted candidate 必須等正式 source capability 與 `available_date <= decision_date` 後才可設計接入。
- **Governed microstructure preflight metadata**：推薦組合 replay 的 `microstructure_preflight` 會輸出 governed source metadata、source capability status 與 missing source policy；不改 PnL、成交價、cash ledger、sizing 或 Research Run lifecycle。
- **Evidence Source Coverage Service**：新增 `EvidenceSourceCoverageService`，讓 CLI、pipeline runner 與 scheduler readiness evaluator 共用同一份 source coverage 分級。Durable source 缺口仍是 blocking gaps；why-not / liquidity / screening matrix payload 缺口是 warnings / `dry_run_only`，舊 recommendation 不回補、不重算。
- **限制**：V1.5 沒有抓取外部 corporate action / 處置股資料、沒有建立新正式資料表、沒有改 `ScoringEngine`、沒有啟用 production scheduler、沒有產生投資有效性結論。

## 2026-07-05 V1.6 Cross-sectional Factor Pipeline v1 成果

- **橫斷面 snapshot 儲存**：新增 `CrossSectionalFactorSnapshot` / row DTO、SQLite schema migration 與 `CrossSectionalFactorRepository`，以 snapshot hash idempotency 保存 `cross_sectional_factor_snapshots` 與 `cross_sectional_factor_rows`。
- **Daily factor pipeline**：新增 `CrossSectionalFactorPipeline`，先走既有 `FactorService` / `FactorGate`，再於同一決策日、同一 factor、已固定 universe 內計算穩定 rank 與 integer quantile bp；skipped / neutralized / look-ahead diagnostics 保留在 snapshot。
- **Sector / concept governance**：pipeline 可接受 sector mapping 與 `ConceptBasketDefinition`；concept basket 只有 `available_date <= decision_date` 時才指派，否則輸出 `concept_basket_unavailable` diagnostic，不回補未來題材成分。
- **Attribution summary CLI**：新增 `scripts/inspect_cross_sectional_factor_snapshot.py`，可唯讀輸出 snapshot coverage、quality counts、rank bucket、sector / concept 分布與 diagnostics；missing DB 不會被 CLI 建檔。
- **限制**：V1.6 沒有改 `ScoringEngine`、沒有把 factor rank 當推薦結果、沒有啟用 production scheduler、沒有產生投資有效性結論。2026-07-08 Phase 3C 已補三大法人 / 信用交易 / TDCC source candidate readiness dry-run，但仍只是 candidate-only diagnostics，不是正式 ingestion，也不進核心 score。

## 2026-06-12～2026-06-14 Strategy & Scoring Governance（增量 B：推薦橫斷面排名）成果

- **橫斷面百分位排名元件實作**：實作 `calculate_score_percentiles` 函式，採用 empirical CDF 計算公式，並以 `bisect_right` 保證同分時取得相同百分位，徹底鎖定排名演算法之統計一致性與輸入順序無涉。
- **策略推薦服務與 metadata 追溯**：整合 `RecommendationService`，在合格母體大小不足時拋出 `RecommendationUniverseTooSmallError` 且拒絕降級；在符合百分位門檻下注入 `score_percentile_bp` 等元數據，並使用 total_score 降序與 stock_code 升序進行穩定化排序。
- **DTO 與儲存庫 round-trip 還原**：於 `RecommendationDTO` 擴充 metadata 欄位，實作相容英文、中文 key 且向後相容歷史 JSON 數據的 `from_dict` 方法，並經 `RecommendationResultDTO` 還原驗證。JSON 檔案自動落盤，不破壞 SQLite schemas。
- **推薦 UI 欄位與控制項整合**：重構 `RecommendationView` 於進階模式下提供門檻模式、最低百分位、最小母體數及排名方法控制項，且隨 fixed/quantile 動態隱藏與顯示；在結果表格中顯示百分位與母體，並於母體不足時發出友善警示與調整建議。
  - **測試驗證**：新增單元測試 `tests/test_recommendation_percentile_ranker.py`、`tests/test_recommendation_ranking_service.py` 與 `tests/test_recommendation_dto_roundtrip.py`，並納入 UI workflow 與推薦組合回測重播驗證。

## 2026-06-12～2026-06-14 Strategy & Scoring Governance（增量 A：回測雙模式門檻）成果

- **純門檻評估元件實作**：實作 `ScoreThresholdPolicy`，支援 `fixed` 與 `quantile` 雙門檻模式。在 `fixed` 下完全向後相容舊策略；在 `quantile` 下，基點範圍採 0-10000 整數以符合量化防禦條款，並實作單股 Expanding 歷史分位數計算（暖機期 60 天），徹底排除未來函數 (Look-ahead bias)。
- **策略執行器與回測整合**：將 `ScoreThresholdPolicy` 成功接入 `BaselineScoreExecutor`、`MomentumAggressiveExecutor` 與 `StableConservativeExecutor`。擴充 `BacktestService` 診斷，在 quantile 下從訊號中安全提取動態門檻、暖機狀態與命中天數等指標，不再在 service 重算分位數。
- **UI 與最佳化表單對齊**：
  - 更新正常參數表單，支援 `threshold_mode` 等 choice 下拉選單（`QComboBox`），並在模式切換時動態隱藏/顯示對應欄位。
  - 重構最佳化參數表單 `_update_optimization_params_form`，將每一行包裹在 `row_widget` 中以支援最佳化面板的行動態顯示/隱藏。Choice 參數不再生成數值範圍，僅能作為固定值進行參數掃描。
- **無交易診斷與 Preset 存取**：更新無交易診斷文案，若採用 quantile 模式，會動態顯示暖機進度與命中次數，不再建議降低 `buy_score`；完成 5 個新參數在 Preset & StrategyVersion 的 100% round-trip 一致性驗證。
  - **測試驗證**：新增單元測試 `tests/test_score_threshold_policy.py`、`tests/test_strategy_threshold_modes.py`，並在 `tests/test_ui_qt_research_workflow.py` 新增下拉選單載入、顯示切換及無交易診斷測試。

## Strategy & Scoring Governance 驗證限制

- 功能與機制回歸已完成。
- 2026-06-14 已完成 10 檔股票、每檔 8 個 OOS fold 的比較；fixed 57 筆、quantile 79 筆交易與 100% Regime coverage 均通過 Gate（詳見 [WALK_FORWARD_COMPARISON_REPORT.md](../06_qa/WALK_FORWARD_COMPARISON_REPORT.md)）。
- Quantile 平均 OOS Sharpe 未優於 fixed，因此維持 opt-in，不宣稱改善績效或穩健度。

## 2026-06-11 券商分點擴充與數據更新流程分流成果

- **券商分點擴充、長碼解密與總公司判定**：在 `BrokerBranchUpdateService` 中實作 Unicode 長碼解密 `_decode_unicode_hex` 與總公司判定邏輯，自動在載入 registry 時將 16 進位 Unicode hex 長碼（如 `003800380038004b`）解密為真實短碼（如 `888K`），並在符合條件時動態判定為總部。已完成 37 個分點的擴充。
- **資料更新流程分流（快速更新 vs 安全更新）**：將 `UpdateView` 一鍵更新按鈕重構分拆為「快速更新（跳過大型合併）」與「安全更新（完整 CSV + SQLite）」。當 SQLite 啟用時，快速更新會略過大 CSV 合併重寫以提升日常更新速度，安全更新則強制執行 CSV 合併以備份資料庫。
- **測試與驗證 100% 綠燈**：新增單元測試 `tests/test_broker_branch_decode.py` 覆蓋解密與總部判定。單元測試、mypy 型態檢查、py_compile 與 QA 驗證腳本皆順利通過。

## 2026-06-11 持倉管理籌碼面監控與下鑽 (Phase 4.2 Portfolio Chip Monitor & Drill Down) 成果

- **籌碼監控服務實作**：實作 `PortfolioChipService`，支援 SQLite 和 CSV 雙軌，計算主力淨買賣超、集中度、連續流向天數，並評估結構化籌碼風險級別（`bullish`/`neutral`/`bearish`）。
- **持倉籌碼監控 UI Tab**：在右側面板新增「籌碼監控」Tab，呈現籌碼風險警告卡片與追蹤分點近 5 日買賣明細表格。
- **雙向下鑽與定位連動**：新增「🔍 下鑽詳細主力流向」按鈕，程式化切換至「市場觀察 -> 主力流向」子 Tab；主力流向 View 實作 `select_stock` 以自動定位並高亮該股，完成下鑽閉環。
- **測試與驗證全綠**：新增 `tests/test_portfolio_chip_monitor.py` 測試。mypy、py_compile 與 `qa_validate_update_tab.py` 驗證皆綠燈通過。

## 2026-06-11 持倉管理深化 (Phase 4.1 Portfolio Deepening) 成果

- **策略版本與推薦來源追蹤視圖**：在持倉管理 UI 右側 `QTabWidget` 中，新增專屬的 **「策略與價格監控」分頁**。若持倉來自策略版本升級，會自動載入 `StrategyVersionService` 以展示其版本號、升級時間、回測績效（總報酬、Sharpe、MaxDD）及參數細節；若來自推薦引擎，則展示對應推薦 Profile 與 Regime 假設。
- **價格對照與未實現損益顯示**：在庫存持倉列表中，新增展示「目前價格」、「未實現損益」與「未實現損益%」。最新收盤價支持 SQLite 直查與 CSV 降級載入，損益計算嚴格遵循 `Decimal` 金額邊界治理。
- **持倉層複合風險提示**：重構 `PortfolioConditionMonitor.evaluate`，結合 Regime 變化、Score 退化與最新價格相對於進場平均成本的偏離度。新增支援固定百分比的 **停損（stop_loss_pct）** 與 **停利（take_profit_pct）** 監控判定。當觸發停損/停利時會自動標示為 `假設失效 (invalid)`，並提供詳細的文字與配色複合警告。
- **型態檢查與 QA 驗證全部綠燈**：Pytest 新增單元測試 `tests/test_portfolio_deepening.py` 完整覆蓋最新價格計算與 SL/TP 警告機制；mypy 零型態錯誤、py_compile 全部成功，UI 與數據庫同步測試 `qa_validate_update_tab.py` 21 項全部 passed！
- **金融數值邊界治理修補與白名單擴展**：補齊 `portfolio_service.py` 與 `portfolio_condition_monitor.py` 缺失的 `# numeric-boundary: dto`，並將 monitor 納入白名單，徹底通過靜態邊界合規門禁（Repository Gate）。
- **策略版本與回測深度串接**：實作了三層防禦查找機制（`source_summary` ➔ `BacktestRunRepository` ➔ `StrategyVersionService`），解決從 Backtest 匯入持倉時 UI 無法直接關聯策略版本資訊的 Gap，並為未升級的回測 run 持倉提供專屬 UI Fallback 展示。

## 2026-06-11 技術治理進展

- 金融 float 邊界與防回歸掃描治理已完成：建立固定金融核心白名單（6 個核心檔案），利用 AST 靜態解析掃描未標記的 `float` 邊界，實行 `dto` / `analytics` / `visualization` 註解分類管制（`# numeric-boundary: <category>`），並加入 pytest repository gate 以防回歸。
- 回測時間軸契約治理已建立初版防線：`BrokerSimulator` 的 `next_open` 帳務錯位已修正，T 日訊號不再提前反映 T+1 成交；`close` 模式與推薦組合回測同日收盤成交假設已加入 warning / metadata。
- 金融核心數值治理核心金額邊界已完成：以 `Decimal`、整數股數與基點處理交易成本、整股邊界與金額量化。`BrokerSimulator`、`portfolio_module/core.py`、`backtest_module/performance_metrics.py`、`app_module/recommendation_portfolio_backtest_service.py` / DTO、`app_module/portfolio_service.py` 的核心金額與持倉平均成本等皆已改用 Decimal 計算，已徹底排除裸 `float` 帶來的精準度風險。

## 2026-05-27 補充狀態

- Recommendation Portfolio Backtest 已開始補強穩健性分析：早期已加入 Sharpe Ratio、Sortino Ratio 與 Monte Carlo P05/P50/P95 模擬報酬；V1.2 v1 已進一步補上 rolling Sharpe / Sortino、VaR / CVaR、drawdown duration、turnover approximation、microstructure preflight 與 relative attribution。這些仍屬 research credibility diagnostics，不代表可成交實盤績效。
- Recommendation Portfolio Backtest 的 portfolio value 已改為每日 mark-to-market，Backtest「推薦組合」結果頁新增 Portfolio Value / Drawdown 圖表，並會嘗試載入大盤基準線做比較；目前停損/停利與策略學習閉環尚未納入推薦組合路徑。
- Recommendation Portfolio Backtest 已接入停損 (%) / 停利 (%) 提前出場，並在結果總覽顯示出場原因統計、虧損交易占比與最拖累股票；策略版本儲存與自動學習閉環仍待下一步。
- Recommendation Portfolio Backtest 已新增獨立 research run 保存庫，可保存/載入/刪除推薦組合回測結果，產生 rule-based 改善建議，並可將通過最低條件的推薦組合 run 升級為策略版本；此保存模型與一般單股 BacktestRunRepository 分離。

## 2026-05-30 SQLite 儲存、Bug 修復與全量技術指標重算升級成果

- **SQLite 資料庫儲存升級與全量遷移 (research/sqlite-storage) 圓滿完成**：已成功在分支上完成 CSV 到 SQLite 升級與無縫向後相容層重構。
- **大盤指數與日期標準化 Bug 完美修復**：修復了西元年無補零被民國年錯誤加 1911 的解析大 Bug（產業指數結束日期完美修正為 `2026-05-29`，無任何髒數據）；修復了大盤指數 KeyError Bug，成功導入 **3,008 筆** 歷史加權指數記錄（覆蓋 `2014-01-02` 至 `2026-05-29`）。
- **技術指標全量重新計算並高速寫入 SQLite**：重構了指標計算腳本與 UI 服務層，成功執行一鍵全量指標重新計算（1,157 檔個股，僅耗時 1 分 51 秒），成功將 **2,802,159 筆新重算的技術指標資料** 同步批次寫入 SQLite 資料庫的 `technical_indicators` 表，數據對比 100% 精準吻合。
- **322 倍回測資料載入加速**：回測載入單股價格歷史時間由大 CSV 的 **8.37 秒** 直降至 SQLite 複合索引查詢的 **0.025 秒 (25 毫秒)**，效能飆升 **322.9 倍**！
- **UI 狀態加載毫秒級「秒開」優化**：重構 `check_data_status` 等數據狀態統計方法，當 SQLite 啟用時 100% 改由 SQL 極速聚合統計，徹底避開幾百 MB 的 CSV 硬碟掃描。
- **UI ↔ Service 合規性 100% 通過**：通過 `test_ui_qt_update_view_workbench.py` (7/7 passed) 與 `qa_validate_update_tab.py` (21 passed, 0 failed)，系統完好無損，穩定性極佳。

## 2026-06-02 安全更新 Phase 1 DB 同步補強

- **安全更新補上 CSV → SQLite 同步鏈**：日常「安全更新所有數據」仍保留既有 CSV 下載、合併與人工檢查習慣，但會在每日股價、大盤、產業、合併每日資料與合併券商分點成功後，同步寫入 `daily_prices`、`market_indices`、`industry_indices` 與 `broker_flows`，降低 UI 狀態 DB-first 與更新流程 CSV-first 之間的分岔風險。

## 2026-06-03 SQLite DB-first 讀取改造與視覺化 Table 檢視 (Phase 2A, 2B & 2C) 成果

- **SQLite 視覺查詢資料表 (Phase 2C) 實作完成**：實作了 `SqliteInspectorService` 與 `SqliteInspectorWidget` 並將其整合至數據更新工作台中。支援資料表 Preview、欄位定義 (Schema) 檢視、自訂唯讀 SQL 執行展示、錯誤輸出、以及非同步載入防止 UI 假死，並配備嚴格的安全防禦機制（僅允許唯讀的 SELECT 查詢且強制進行 Limit 限制，防範 SQL Injection 與大數據崩潰）。
- **數據讀取 SQLite 優先 (DB-first) 圓滿完成**：重構了強勢股篩選 (StockScreener)、市場狀態偵測 (MarketRegimeDetector)、產業映射器 (IndustryMapper) 及推薦服務 (RecommendationService)，數據載入 100% 實現 SQLite 優先與 CSV 備用降級，徹底消除遍歷讀取磁碟小 CSV 的 I/O 毒瘤。
- **一鍵安全更新效能 Hotfix 完美修復**：優化了 `_date_key` 日期格式解析函數，避免在百萬行資料中因逐行呼叫 `pd.to_datetime` 造成的嚴重的 CPU 與 I/O 開銷。產業指數日期轉換由 13.19 秒縮短至 **0.136 秒** (提速 100 倍)，286 萬筆每日股價同步寫入 SQLite 僅需 **59.35 秒**。所有單元測試與 QA 驗證全部通過。

## 2026-06-03 CSV 手動匯出與更新流程優化 (Phase 3) 成果

- **停止日常更新大型 CSV 重寫**：當啟用 SQLite 時，日常安全更新直接將新下載的單日 CSV 同步寫入 SQLite 庫（包含個股價格與主力分點），跳過重寫 `stock_data_whole.csv` 與主力分點大合併 CSV 等大型檔案，避免磁碟 I/O 重擔。
- **技術指標增量同步優化**：增量計算技術指標時，略過保存 `all_stocks_data.csv`，並在同步 SQLite `technical_indicators` 表時，改為只針對有更新的 `(證券代號, 日期)` 組合進行舊記錄刪除後追加寫入，不執行全表 `DELETE`。
- **各 subtab 加入「匯出 CSV」**：在數據更新工作台的五大數據 subtab 中新增「匯出 CSV」按鈕，支援非同步匯出指定範圍或全量 SQLite 記錄至 CSV 備案，檔名與日期格式（`YYYY-MM-DD`）符合人工檢查需求，且使用 UTF-8 with BOM 避免 Excel 亂碼。
- **測試與驗證 100% 綠燈**：Pytest 與 QA 驗證全部安全通過，mypy 零新增錯誤。

## 2026-06-03 主力流向 (Smart Money Flow) 視覺重構與排版優化成果

- **UI 左右分欄與架構重構**：將主力流向 Tab 重構為左右分欄布局（左側主表佔 65%，右側詳情面板佔 35%）。右側面板新增「選中股雷達摘要卡片」與「訊號原因解析」，改善籌碼流向的可讀性與解釋性。
- **中文化玻璃擬態卡片**：將頂部四張小卡片（市場趨勢、熱度、多空個股數、異常警示）完全繁體中文化，並放大標題（11px）與數值（15/16px）字型，提升視覺質感與操作清晰度。
- **Sparklines 漸層與 ToolTip 懸浮提示**：為 Sparkline 微型圖表實作漸層面積填色（`QLinearGradient`），並收緊為顯示「最近 5 筆交易明細」，解決不同週期切換導致空白或不規律的問題。實作全列 `Qt.ToolTipRole` 強制觸發，使滑鼠懸停於表格任何單元格時皆能顯示詳細的最近交易明細。
- **排序功能與 Bug 修復**：
  - 修復點擊表格標頭無法排序的問題（在 `TerminalTableModel` 與 `BranchTrackerTableModel` 中實作 `sort()` 方法）。
  - 修復多空個股數中「偏空個股數恆定為 0」與「市場熱度恆定為 100%」的 Bug（改由 unfiltered 數據重新統計多空家數，並收緊偏多異常判定至 `score >= 80` 且 `net_qty >= 500`）。
  - 完整重構說明對話框（InfoButton），提供功能說明的繁體中文對齊。

## 2026-06-03 數據更新工作台 (UpdateView) 視覺重構與架構優化成果

- **主看板升級與狀態卡片 (`StatusCard`)**：將「全部資料」頁面重構為極簡數據看板，移除了所有手動配置與雜亂按鈕。設計了 StatusCard 元件（圓角、Hover 漸變與陰影效果），整合四色狀態指示燈（🟢/🟡/🔴/⚪）顯示最新日期與筆數，與原 `QTextEdit` 介面相容度 100%。
- **進階與手動操作配置歸位**：解耦原有界面，將下載日期範圍、手動下載與合併按鈕搬移至個別專屬分頁（每日股價、大盤、產業、券商分點、技術指標）。每日股價分頁中，以紅色警示邊框封裝了 **Danger Zone (高風險區)** 存放強制重新合併按鈕。
- **全域底部日誌 Console 與進度條共享**：將 QProgressBar、進度 Label 以及 Terminal 日誌輸出框移至最外層佈局的最下方，實作分頁切換時日誌與進度的全域共享。Console 採用深色背景、Consolas 等寬 11px 字型與微型清除按鈕。
- **日期聯動同步與委派更新**：在 `UpdateView` 中實作了日期聯動邏輯，任何分頁修改日期皆會透過 blockSignals 同步更新其他分頁元件。手動更新按鈕透過 `_dispatch_update()` 自適應設定隱藏的對應 RadioButton 狀態，實現 UI 與原 Service 業務代碼的無縫相容。
- **自動與 QA 測試 100% 綠燈**：通過 mypy 無新增錯誤，`tests/test_ui_qt_update_view_workbench.py` (9 passed) 與 `scripts/qa_validate_update_tab.py` (21 passed, 0 failed) 順利通過。

## 2026-06-04 Research Lab 工作流重整

- Research Lab 第一階段開始將回測頁定位為多模式研究實驗室，區分單股回測、批次股票回測、固定組合回測、推薦系統回放與策略研究。
- 觀察清單在研究流程中重新定位為候選池 / 實驗 Universe，用於回答「我要測哪一批」。
- Recommendation / Backtest 記錄到 Portfolio 時將保留來源 metadata，讓交易紀錄可追溯到推薦結果或回測 run。

## 2026-06-11 券商分點單位契約修正

- 既有爬蟲固定使用 MoneyDJ `c=B`，其數值是仟元，不是張數。
- 更新流程改為同時抓取 `c=E` 張數與 `c=B` 仟元並分欄保存。
- 舊 B-only 資料保留，但不再進入 Phase 4.2 張數判斷；重新抓取 E 後才具備有效籌碼訊號。

## 2026-06-12 券商分點 Ranked Metric 資料品質治理

- MoneyDJ `c=E` 張數與 `c=B` 金額確認為各自獨立 Top 50 榜單，資料層採 union 並保存 observed 狀態、方向與 rank。
- Smart Money 與 Portfolio Chip Monitor 使用 observed / estimated / unavailable 三態，單筆不可用不再污染同股票其他事件。
- 正式 `broker_flows` 已由既有 daily 檔無破壞重建為 104,986 筆、158 天，rank 範圍 1 至 50，唯一鍵與 NULL 契約檢查均通過。

## 2026-06-24 券商分點 MoneyDJ HTTP fast path

- MoneyDJ 券商分點更新改為先使用 HTTP fast path 抓取 Big5 HTML，正常頁面不再先啟動 Selenium；HTTP 失敗或解析不到資料時才退回 Selenium fallback。
- 預設請求間隔由 4.0 秒調整為 0.5 秒，仍維持序列更新，暫不啟用多 worker 併發。
- 更新日期會先以每日股價日檔或 SQLite `daily_prices` 作交易日預檢；沒有行情證據的日期會整天跳過 MoneyDJ，避免 40 個分點各自重試非交易日。
- 小樣本 live 驗證：`1440_1440` / `2026-05-29` 在暫存資料根目錄中不啟動 Selenium，約 1.62 秒寫出 141 筆 daily CSV。


## 2026-06-12 批次回測並行化與安全軟取消成果

- **批次回測並行化實作**：實作 ProcessPoolExecutor 並行處理機制，當回測個股數大於 threshold 時自動並行，並支援 `max_workers=None` 自適應調整 CPU 核心數。
- **合作式軟取消**：實作非暴力 cooperative 取消機制，取消時停止向進程池提交新任務，且 Worker 等待 active 子行程清空後才發送 `cancelled` 信號並恢復 UI 按鈕，避免 UI 提前解鎖造成新舊任務重疊。
- **唯一性 run_id 寫入**：在循序與並行路徑皆引入 UUID 來生成唯一 `run_id`，避免 SQLite 與 parquet 同秒覆寫衝突。
- **TaskWorker 軟取消回歸防護**：保留 `TaskWorker` 取消時的 legacy `terminate()` 行為，並將新合作式軟取消限制在回測專用 Worker，維持 Update、Recommendation 與 SQLite Inspector 等既有頁面的行為相容；legacy 強制終止風險列為後續技術債。
- **測試與驗證**：新增單元測試 `tests/test_backtest/test_parallel_safety.py`，覆蓋 UUID 唯一性、軟取消、自適應循序分流、非法股票處理、真實 `BrokenProcessPool` 異常重現及 `max_workers=None`。

## 2026-06-14 SQLite 檢視器穩定分頁與規格化 Excel 報告匯出成果

- **SQLite 檢視器資料庫層分頁**：
  - 於 `SqliteInspectorService` 實作 count 與 offset 穩定分頁，共用 filter builder。
  - 設計 `日期 DESC, 證券代號 ASC` 搭配 `rowid ASC` 穩定排序，保證跨頁無重複與遺漏。
  - UI 介面整合「上一頁/下一頁/跳頁/當前與總頁碼」控制列，並在篩選變更時自動重設回第一頁，且快取 schema 避免重複拉取。
  - 實作單調遞增 `request_id` 防 stale 異步查詢覆蓋最新結果；快速連續查詢會保留各執行中 worker 至自然結束，避免斷開或提前銷毀 `QThread`。
- **四種規格化 Excel 報告背景匯出**：
  - 定義防禦性複製 payload DTO 快照 (`report_export_dtos.py`)：單股、批次、組合回放、目前推薦結果。
  - 於 `ReportExportService` 實作 Excel workbook 的資料格式化 (金額/百分比/天數/日期)、自適應欄寬上限與凍結/自動篩選。
  - 開闢「資料完整性」專用區域，在缺少追溯元數據時明確標註 `N/A` 並列出缺失欄位清單。
  - 整合 Pyside6 `TaskWorker` 於背景線程寫入暫存檔，完成後採原子替換 (`os.replace`)，保障 UI 介面不假死且不破壞原有報告。
  - 匯出 payload 直接使用正式 `BacktestReportDTO` / `BatchBacktestResultDTO` 欄位與推薦回放執行快照；缺失 metadata 不以 UI 當前值或預設常數偽裝。
  - equity curve 支援 `日期`、`date` 欄位與日期 index，批次排行榜由正式 `stock_results` 建構。
  - **測試與 QA 覆蓋**：包含原檔替換失敗保留、快速連續分頁、正式 DTO、equity curve 真實形狀等回歸案例；完整 gate 以本次 commit 驗證記錄為準。
### 2026-08-12 Direct/OOC 自動 custody 續跑補強

- OOC continuation 現在會在 current Direct v4 沒有 sector sidecar 時，自動探測受控環境變數 `BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH` 或 output lineage 下固定命名的 PIT sidecar；只有 canonical manifest、accepted/license/source hash、可得時間與 training cutoff 全部通過才會啟動新的 immutable Direct → OOC rebuild。沒有來源、當期 company registry、研究檔或多個合格候選時，沿用目前 publication 並維持 `formal_oos_allowed=false`、alpha=`0`、broker=`false`。
- `scripts\maintain_ml_direct_v3_refresh_chain.py --watch-formal-inputs` 可跨 worker／supervisor 中斷持續等待合規 sidecar；不會重複訓練、改寫舊 run、寫正式 SQLite 或放寬三項 formal blocker。Rule Champion controlled artifact 與 causal non-cash ledger 仍須真實受控來源，沒有偽造或自動降級替代。
### 2026-08-12 QA append

- Direct/OOC 自動 custody 續跑測試補齊後，最新 deterministic test inventory 為 `587/587/3125`，collection errors 與 machine-checkable blockers 均為 `0`；`3120` 為本輪 watcher regression 補入前的中間基準，`3119` 與 `3114` 保留作前序歷史基準。
### 2026-08-13 Asia/Taipei scheduled revalidation

- OOC training path 已補上 expanding outer-fold 的 cross-fitted calibration 診斷；每個 target fold 只用更早且已成熟的 OOF blocks，metrics 以整數 bp 計算，並在 manifest 標記 `oof_diagnostic_only=true`、`production_eligible=false`。這不會改寫目前已發布的 OOC run，也不會解除正式 custody gate。
- 下一個 OOC run 若通過此 gate，promotion blocker 會由 `classifier_calibration_not_cross_fitted` 轉為 `classifier_calibration_not_attached_to_ooc_model`；目前實際三項正式 custody blocker 與 `formal_oos_allowed=false`、alpha=`0` 不變。

- Evidence pipeline 已重新執行：`status=blocked`，strict T-1=`2026-08-12`、upstream proof=`passed/ready`；唯一 blocker 仍為 `causal_non_cash_portfolio_ledger_present`、`formal_rule_champion_snapshot_history_present`、`pit_sector_membership_present`。
- Authority=`skipped_evidence_unavailable`，copilot=`passed_rule_only`、`selected_alpha_bp=0`、`formal_oos_allowed=false`、`broker_order_allowed=false`；本次沒有重訓，因為正式輸入 custody 未改變，且沒有合法新 sidecar。

### 2026-08-13 自動 catch-up 回歸修正

- 全量 pytest 首輪只發現 1 個失敗：`--auto-catch-up` 在 scheduler 實際日期漂移時，沒有進入第二次 hash-bound 的已過交易日重試。已將 Taipei scheduler clock 收斂到可測試的單一邊界，保留原有「只在 runtime 證明 strict T-1 未就緒時才回溯」的 fail-closed 條件；相關測試 `15 passed`，promotion／Direct/OOC chain 聚焦測試合計 `52 passed`。
- 修正後完整回歸為 `3124 passed, 1 skipped, 24 warnings`（`3125` collected），financial float boundary、`py_compile`、受影響 script 的 `mypy` 均通過；formal ML 輸入 custody 未改變，沒有啟動重訓，watcher 持續等待合法輸入。

### 2026-08-13 最終自動重驗

- 實際每日 orchestration 已完成：`status=passed_rule_only`、`orchestration_status=completed`、`operation_mode=rule_only`、decision=`2026-08-13T08:30:00+08:00`、strict T-1=`2026-08-12`；`selected_alpha_bp=0`、`formal_oos_allowed=false`、`production_action_allowed=false`、`broker_order_allowed=false`、`writes_source_database=false`。
- Evidence 仍只因三項正式 custody blocker blocked；Authority=`skipped_evidence_unavailable`（compatible pointer 不存在）。Direct/OOC formal-input watcher 的 parent／child worker 仍在執行並等待合法 PIT sidecar，沒有誤觸發重訓。

### 2026-08-13 Direct/OOC formal input 自動探測補強

- `scripts\\maintain_ml_direct_v3_refresh_chain.py --watch-formal-inputs` 現在會自動驗證最新 raw PIT pointer、publication／dataset canonical hash、formal safety、`decision_at` 與現行 Direct identity；較新的 publication 或同一 cutoff 但內容 hash 改變時，會以新的 immutable Direct → OOC chain 續跑，不再只等待 sector sidecar。
- 同一輪會驗證最新 official market-event publication，保留既有已綁定且仍符合 cutoff 的 sector sidecar；只重發 wrapper、canonical events hash 未變時不會觸發重複重訓。沒有建立或採用未受控的 causal non-cash ledger／Rule Champion artifact，formal gate 仍固定 `formal_oos_allowed=false`、alpha=`0`、`broker_order_allowed=false`。
- 新增 raw／refresh override 與 pointer tamper 回歸案例後，maintenance focused QA 為 `11 passed`；`py_compile`、`mypy` 與 financial float boundary 均通過。現行 release pointer 的 raw decision 仍為 `2026-08-11T08:30:00+08:00`，沒有新的合格 refresh input，因此本輪沒有重訓；背景 watcher 持續運作。

### 2026-08-14 正式輸入消費端 custody 接線

- 已新增唯讀 `causal-portfolio-ledger.v1` loader：驗證 manifest／SQLite file hash、append-only transition schema、每列 `CausalPortfolioState` hash、recursive chain、T-1 對齊與 non-cash state；研究 ledger、Teacher／same-day Advice 回灌與 cash-only fallback 不會被升格。
- 已新增 signed `rule-champion-snapshot-history.v1` loader，並將其逐日 Rule score 接到 formal OOS replay input；history 需通過 controlled-store HMAC、immutable snapshot hash、rank／timestamp／coverage 驗證。
- Direct、OOC、training 與 OOS replay input 現已傳遞並 hash-bind 兩項 custody；OOS replay consumer 會再次驗證 ledger／Rule history，不會在消費端靜默丟棄。這是工程接線完成，不是來源已到位：目前實際三項 blocker 仍為 `causal_non_cash_portfolio_ledger_present`、`formal_rule_champion_snapshot_history_present`、`pit_sector_membership_present`，因此 `formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false` 不變。
- Direct-chain maintainer 現可由受控 Windows 使用者環境變數 `BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH`／`BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH` 自動發現兩項來源；先做唯讀 ledger／cutoff／HMAC 驗證，再與 PIT sector sidecar 一起 hash-bind。三項來源未同時合法到位時只等待，不因分批 deposit 觸發 partial Direct/OOC 重訓；目前本機未設定這兩個路徑，故沒有新 chain。
