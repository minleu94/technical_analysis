# Luna A：資料與 ML 有效性 handoff（2026-09-07）

> 整合補註（2026-09-08）：以下保留本線交付當時的數字與 Git 狀態；整合修補、全域測試及 main／dev 收尾以 [三線整合驗收](LUNA_INTEGRATION_CLOSEOUT_2026_09_08.md) 為準。

狀態：**incomplete / fail-closed**。本輪完成 A1 依賴邊界、teacher gate 順序、唯讀真實資料稽核、既有研究比較的獨立整數／Decimal 重算，以及 A6 定向回歸；沒有把缺來源的 all-cash targets 當成 teacher，也沒有 fit、promotion、broker 或正式資料寫入。

可重驗的機器封裝在 [output/luna_A/manifest.json](../../output/luna_A/manifest.json)。診斷與獨立比較稽核分別在 `output/luna_A/target_diagnostics_real.json` 與 `output/luna_A/base_comparison_independent_audit.json`；這些 output 被 `.gitignore` 排除，不應提交。

## 基線與邊界

- checkout：`C:\Projects\PythonProjects\technical_analysis`；baseline branch 是 `dev`，baseline commit 是 `71500ef6fc834da285c19255e5c03f1846412329`。
- 交接時觀測到 branch 已被外部並行工作切為 `codex/luna-c-uiux`；本輪保留該現況，沒有切回、reset 或覆寫並行變更。
- Python：3.11.9；本輪環境重點套件：numpy 2.3.5、pandas 2.3.3、scikit-learn 1.8.0、pytest 9.0.2、mypy 2.1.0、PySide6 6.10.1。完整 `pip freeze` hash 在 manifest。
- consolidation 前已有 dirty paths；本輪只改 A ownership 的 ML／data 相關檔案及本 handoff，沒有 restore/reset 其他人的變更。
- 正式來源仍依 `TWStockConfig` 指向 `D:\Min\Python\Project\FA_Data`；D 槽 SQLite、raw CSV、availability mapping 都以唯讀方式查詢。新的診斷、比較稽核、暫存與 manifest 只寫 `output/luna_A`。

## A1 fact matrix

| 面向 | 已確認證據 | 判定 |
|---|---|---|
| Teacher diagnostics | `data_module/portfolio_ml_target_diagnostics.py:1456,1749`；實際讀取 13 年 Direct manifest，`3,347,662` rows，target 的 `cash_bp=10000`、其餘五個 target field 全為 0 | 已有 machine-readable diagnosis；真實結果為退化 all-cash |
| Teacher eligibility | 同一診斷的 gate schema `allocation-teacher-eligibility-gate.v1` 回傳 `allowed=false`，三個 blocker 為 PIT sector、formal Rule Champion history、causal non-cash portfolio ledger | fit 前拒絕 |
| Cross-year carry / resume | `data_module/portfolio_ml_direct_numeric_store.py:56-67,601-1077,1254-1264,1526-1612`；carry `portfolio-ml-direct-carry.v2`、distinct causal price events、年度 checkpoint／resume | 已有契約與定向測試 |
| Freeze / confirmatory | `ml_module/allocation_base_expert_comparison_freeze_gate.py:84-98,294-383`、`ml_module/allocation_confirmatory_runner.py:595-684`；先驗證 code／policy／parent／request，再允許 source reader | freeze gate 存在；本輪未開啟 fold-005 source rows |
| Storage / shared blocks | `data_module/ml_storage_capacity.py:39-54,1910-2035`、`ml_module/allocation_out_of_core_training_service.py:900-964`；canonical reserve 200 GiB、default persistent/temp 各 1 GiB、heavy lock／shared artifact store | gate 與容量政策均保留；C 槽 preflight 阻擋 |
| Price / statement / monthly revenue adapters | 真實 MOPS monthly candidate、隔離 quarterly SQLite、正式 SQLite read-only observation 均完成 hash／identity／available date 觀察 | intake／materialization 尚未升正式 lane |
| ML producer boundary | 新增 `ml_module/allocation_release_loader.py:15-64`；v3 producer 改依中立 loader，application adapter 在 `app_module/allocation_release_adapter.py:38,358` 註冊；guard 僅放行精確 versioned rank/family contract 與中立 loader | 原有兩條反向 import 衝突已修正；未刪 guard |

## A2 真實 source observation matrix

這是有限、可重驗的 observation scope，不宣稱全市場或正式 backfill 已完成。

| source | identity／period／basis | 數量與 hash | available／revision／late-data 行為 |
|---|---|---|---|
| Direct numeric store | `run_id=direct-ooc-0f731f46b29c0b146fa20145`；2014–2026 年度；整數 bp targets／labels；manifest source hashes 綁定 daily price、market／industry index、technical、corporate-action sidecar | `3,347,662` rows；manifest hash 與各年度 artifact hash 見 manifest；diagnostic output hash 也保留 | `target_available_future_count=0`、`max_label_available_future_count=0`；`sector_observed_count=0`；benchmark labels 有變化，不能解讀成 teacher 有效 |
| MOPS monthly revenue | official TWSE `t187ap05_L`、TPEx `mopsfin_t187ap05_O`；period `2026-07`；source version 由 market／period／body hash 組成 | candidate `1,851` rows（TWSE 992、TPEx 859），SHA-256 `585ddfcae282030f66459abd997b58294fb4b7a3e0dff3045d7c6540a3b67336`；official API full rows 1,085/890，natural-key intersection 990/859 | capture `2026-09-07T07:17:53Z`；保守 available date `2026-09-08`；`2850|2026-07`、`2883|2026-07` 無公告日證據，保留於 full denominator 並排除；accepted isolated scope `1,849`，重跑為 existing，未寫正式 DB |
| MOPS quarterly statements | isolated consumer DB；period `2026-Q2`；`report_basis` 明分 `consolidated`／`individual`；`period_basis` 明分 `period_end_snapshot`／`quarter_single`／`year_to_date`；value unit／scale 為 TWD×1000 或 TWD/share×100 | `26,139` rows、`197` stocks；basis：consolidated 24,251、individual 1,888；period basis：9,563／6,135／10,441；available dates 2026-09-08／09-09；DB hash 在 manifest | metadata 保存 stock／statement／item／candidate source version、content／row／availability hashes、announcement event 與 numeric available timestamp；首次／重跑 idempotence 保留 |
| Rejected official source | MOPS t164 response for company `2035`, `2026-Q2` | 98 bytes，SHA-256 `54112594858a0455d96e7a520f6c4b07c3f4af6bfac128a0628084e32ba6fa61` | 官方「資料不存在」頁，沒有 numeric candidate；不以空 response 補值或猜 report basis |
| Formal SQLite observation | `D:\Min\Python\Project\FA_Data\sqlite\twstock.db`，只讀 aggregate | `fundamental_monthly_revenues`: 246,331 rows／1,849 stocks／2014-04–2026-06；`fundamental_statement_items`: 1,645,555 rows／1,567 stocks／2014-Q2–2024-Q1 | formal monthly 2026-07 尚未 materialized；statement raw／mapping 的舊 available date 不能回填新 PIT |

Quarterly sample row 另保存 `announcement_event_timestamp`、`numeric_available_at`、`period_end=2026-06-30`、`value_unit=TWD`、`value_scale=1000`、`item_code_source=mops.t164sb01.xbrl.row_code` 與 candidate／row／availability hash。這讓 flow／stock（例如 `quarter_single`、`year_to_date`、`period_end_snapshot`）不會被同一個數字欄位混淆。

## A3 teacher eligibility 結果

診斷明確回報：

- `allowed=false`、`status=blocked_missing_formal_teacher_inputs`、`outcome_research_allowed=true`、`formal_oos_allowed=false`、`production_alpha_bp=0`。
- 三個固定 blocker：`missing_formal_teacher_input:formal_rule_champion_snapshot_history_missing_formal_replay_blocked`、`missing_formal_teacher_input:pit_sector_membership_missing_teacher_new_positions_disabled`、`missing_formal_teacher_input:portfolio_ledger_missing_cash_only_fallback_turnover_and_cooldown_not_learned`。
- all-cash fallback 只代表缺正式 ledger 的保守狀態；它不代表模型學會持有現金。sector candidate 為全缺，不能從該 target 產生可學習的 non-cash allocation。
- 已有負例回歸：outer hash-only tamper、source identity/date、late source、partial decision-date coverage、row count、cash-only fallback、unknown sector、target summary tamper，以及 OOC 在任何 capacity preflight 前即拒絕 teacher gate。
- 因此本輪沒有 fit、沒有產生新的 shared ML block、沒有把候選或事後標籤升格正式 teacher。缺來源清單與修復方式已寫入 diagnostic／manifest。

## A4 causality、跨年與 freeze

Direct manifest 的 `training_as_of=2026-08-28T08:30:00+08:00`；全年度 `target_available_future_count=0` 與 `max_label_available_future_count=0`。carry 使用 `direct-replay-volume20-cross-year-carry.v1`，每年以 bounded distinct causal price events 更新，checkpoint identity 綁 carry schema／policy；沒有使用未來年度資料回填前一年度。

既有 fold-004 comparison 的 `method_freeze_version=base-expert-comparison-method.v7`、parent／policy／request hashes 均保存。fold-005 的 gate／runner 本身保證 source reader 只能在 gate 後呼叫；本輪只讀取既有 artifact metadata 做稽核，`future_fold_005_source_rows_opened_this_run=false`。探索過的 range 保持 exploratory，沒有重新調參或把結果當 promotion evidence。

## A5 bounded research comparison

本輪不在 C 槽容量不足時重跑 OOC fit；使用既有 immutable fold-004 research comparison 做 read-only verification，並以 Decimal／整數 minor unit 獨立重算 final equity、return、MDD 與成本 drag。所有 lane 共用同一 investment pool、decision-date scope、T-1 liquidity policy、lot／fill／cost policy；strict sector lane 因 PIT sector 全缺而 blocked。

| lane（research_no_sector_cap） | trades | final net minor | net return bp | net MDD bp | gross return bp | cost drag bp | 判讀 |
|---|---:|---:|---:|---:|---:|---:|---|
| base data quality | 4 | 49,880,209 | -24 | 79 | -12 | 12 | research-only |
| base price/liquidity/technical | 2 | 50,486,605 | 97 | 8 | 106 | 9 | research-only |
| causal Rule | 7 | 50,563,395 | 113 | 43 | 134 | 21 | causal research；非 formal Rule Champion |
| T-1 liquidity-pool equal weight | 11 | 49,708,936 | -58 | 268 | -32 | 26 | baseline；不可與 blocked lane 勝負比較 |

四個選定 lane 的獨立重算均與 comparison JSON 相符；`base_comparison_independent_audit.json` 保存每個整數／Decimal assertion。結果只證明 bounded historical research chain 可重驗，不證明 ML 優勢、forward effectiveness 或 promotion readiness。

## A6 驗證與限制

通過的定向檢查：

- `tests/test_portfolio_ml_target_diagnostics.py tests/test_portfolio_ml_direct_volume_carry.py tests/test_allocation_base_expert_comparison_freeze_gate.py tests/test_ml_storage_capacity.py`：**62 passed, 1 skipped**。
- `scripts/check_ml_shadow_boundary.py`：**459 inspected, violations=[]**；shadow dependency tests **9 passed**。
- v3 release tests（含 neutral loader fail-closed regression）：**17 passed**。
- release adapter **7 passed**、inference **10 passed**、rank **4 passed**、freeze gate **16 passed**、OOC release builder **7 passed**、teacher source producer **3 passed**。
- changed Python `py_compile`：pass；受影響 6 個 source files 的 mypy：`Success: no issues found`。
- OOC pipeline 的單一失敗測試在新隔離暫存根目錄重跑為 **1 passed**。完整 pipeline setup 另受同一台 Windows 上既有 Python 任務造成的 shared fixture file-lock 影響；沒有把該環境錯誤誤判成 ML data correctness。
- dataset assembler：**27 passed, 6 blocked**，六個均在 `raw_before_output` 因 C 槽 reserve policy fail-closed。

容量觀測（整數 bytes）：default persistent/temp 各 1 GiB、中央 reserve 200 GiB，所需 headroom `216,895,848,448` bytes。C 槽當時 free `189,196,177,408`，所以 `output/luna_A` preflight 阻擋；D 槽唯讀 probe free `333,659,115,520`，但本任務禁止把新 output 寫到正式 D 根目錄。Direct 已有 manifest 宣告的 peak RSS 是 `252,198,912` bytes，peak temporary 是 `24,524,313,888` bytes；本輪沒有在容量不足時啟動新 fit。

## 變更與 rollback

變更集中於：

- `ml_module/allocation_release_loader.py`：中立 callable protocol、唯一註冊、未註冊時 RuntimeError。
- `ml_module/allocation_v3_linear_release.py`：producer 只 import neutral loader，保留 application adapter readback parity。
- `app_module/allocation_release_adapter.py`：import 時註冊真實 hash／artifact／inference adapter。
- `ml_module/shadow_boundary_guard.py`：只新增精確的 versioned integer contract 與 neutral loader allowlist；未移除 guard。
- `ml_module/allocation_out_of_core_training_service.py`：teacher eligibility 在 capacity preflight、output、RSS monitor、shared block、fit 之前執行。
- `scripts/build_ml_allocation_v3_linear_release.py`：CLI 啟動 application adapter bootstrap，避免 producer 在未註冊時誤發布。
- 兩個既有測試檔：neutral loader 與 teacher gate precedence regression。

Rollback 前先重新檢查 `git status --short` 並保留 consolidation／其他 agent dirty paths；只對上述 tracked A files 套用本輪反向 patch，確認無共享變更後再移除新 loader。不要使用整個 checkout 的 `git reset --hard` 或 broad restore。manifest 已保存 baseline 與目前 status。

## 未完成與下一步

未完成項目是正式 causal non-cash ledger、同日期 formal Rule Champion history、PIT sector membership、formal 3/3 input credit，以及符合 reserve 的新 OOC fit。下一步必須先取得三個來源並以 source／row／availability hash 綁定，逐決策日重新跑 teacher gate；只有 gate 通過且專用 output filesystem 通過 capacity reservation 後，才可建立 shared block、重跑 bounded fit 與 future confirmatory read。這些條件滿足前，production alpha 維持 0、formal OOS 維持 blocked、broker 維持 false。
