# baldr 完整操作手冊

## 2026-08-15 prospective-only formal simulation（PFS-07）

Owner 已選擇「正式、但 prospective-only 的非實盤模擬持倉 clock」。既有
`2014–2026` Direct／OOC 與 research artifacts 只保留 history，不回填成 Formal
evidence；目前 `formal_oos_allowed=false`、production alpha=`0`、broker disabled。

PFS-07 的 activation contract 已可用於受控 fixture preflight：

- `scripts\publish_prospective_formal_clock.py --fixture-only` 可把 owner 已核准、仍在未來的 activation trading day 與官方 calendar evidence 寫成 planned clock manifest。呼叫端必須明確提供 clock／owner decision、cash seed、strategy／policy／universe／source identities、frozen candidate training cutoff、calibration／evaluation hashes 與 `--now`；命令不會自行選日期、查找或回填歷史、設定任何 `BALDR_ML_*` path、讀取 HMAC secret 或啟動 watcher。輸出 parent 必須先存在，manifest 採 canonical JSON create-only。
- `scripts\plan_prospective_formal_clock.py` 是新的唯讀日期 preflight。它只接受呼叫端提供的 `official-trading-calendar-bundle.v1`（每個候選日同時含 TWSE／TPEX `is_trading_day`、官方 `source` 與 `sha256:` response hash），以帶時區的 `--now`、owner decision timestamp、至少一個準備日與 lookahead window 選出第一個尚未使用的共同交易日。輸出是 `candidate_ready` proposal，不是 clock manifest；不下載日曆、不採用 same-day override、不自動切換 `BALDR_ML_*` path、不寫正式資料。選不到合格日期時回 `blocked`，不猜日期。
- `scripts\capture_official_calendar_bundle.py` 可將已由官方 TWSE 年度 `holidaySchedule` 與 TPEX 月度 `mktCalendar` 取得的 raw JSON 正規化成上述 bundle；fixture 可重複指定，缺少的年度／月份只有在明確加上 `--confirm-network` 時才各發一次 bounded GET。輸出只能寫入作業系統 TEMP 且 create-only，artifact 永遠標示 `candidate_only=true`、`formal_clock_created=false`；它不寫市場 SQLite、不改 `BALDR_ML_*` path，也不會自動建立或啟動 clock。TPEX 缺少平日明確 row、TWSE／TPEX 年月不符或回應格式錯誤時均 fail closed。
- `scripts\activate_prospective_formal_clock.py --fixture-only` 在 strict 模式只於三個 PFS-06 input 都 ready、candidate／calibration／evaluation identities 與 file hashes 都一致、owner activation timestamp 已發生、activation trading day 仍在未來時建立 create-only manifest。Owner handoff 可改用 `--fixture-only --controlled-environment`，由 shared Windows reader 取得三個 formal paths、非秘密 store identity 與 HMAC configured flag；此模式不讀／輸出 secret、不設定環境，缺件即 blocked。
- `scripts\record_prospective_daily_capture.py --fixture-only` 只建立低 CPU daily capture 的 `started` record，固定 PIT publication → Rule snapshot → T-1 Portfolio transition → frozen inference → heartbeat 順序；`elapsed_day_credit=0`、`formal_credit=0`，不能隔日補寫。
- `scripts\run_prospective_rule_only_decision.py` 只在實際台北 09:00–13:30 盤中，以 prospective clock owner acceptance、frozen universe 與 T-1 `daily_prices` 產生 TEMP owner-bound Rule source；它不寫 market DB、Recommendation、Portfolio、evidence ledger 或 broker，且 HMAC secret 只由受控 runtime 驗證，絕不輸出。
- `scripts\run_prospective_formal_activation_once.py` 是一次性低 CPU handoff：驗證 activation day 與 T-1、建立官方 PIT、publish Rule history、append simulated Portfolio，再於三份 input 都存在後寫 strict readiness。它拒絕既有 formal output、只 create/append、不註冊 continuous scheduler，不啟動 watcher、Direct/OOC、training、promotion 或 broker。若要執行，需由 owner 將 v3 clock、source custody、controlled store 與正式輸出父目錄以明確參數提供；任何缺件都 fail closed。

### Prospective Formal Restart：官方公司基本資料 PIT staging

Restart 第一階段的官方產業來源固定為 [TWSE `t187ap03_L`](https://openapi.twse.com.tw/v1/opendata/t187ap03_L)、[TPEX `t187ap03_O`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O)；只有 clock universe 明確含興櫃標的時才可加入 TPEX `t187ap03_R`。操作入口
`scripts\capture_prospective_official_pit_sector.py` 不會自行下載來源，必須由呼叫端提供每個 endpoint 的 raw JSON bytes、sorted symbol universe、license id／URL 與明確的 publication timestamp。它會驗證官方欄位、民國／西元出表日期、兩位數產業代碼、重複／缺列、raw／canonical hash、available／effective time 與 clock／universe lineage；任何不成立都 fail closed。這條路徑禁止 `companies.csv`、current snapshot、research output 與歷史回填。

activation 前的 source fixture 可用 `--preactivation-staging`，只產生標示為 `staged`、formal consumer 不可直接消費的 create-only package：

```powershell
.\.venv\Scripts\python.exe scripts\capture_prospective_official_pit_sector.py `
  --fixture-only --preactivation-staging `
  --clock-manifest <PLANNED_CLOCK> `
  --now <TAIPEI_NOW> `
  --decision-timestamp <FUTURE_DECISION_TIMESTAMP> `
  --available-at <SOURCE_AVAILABLE_AT> `
  --effective-from <CLOCK_ACTIVATION_DATE> `
  --symbols-json <SORTED_CLOCK_SYMBOLS_JSON> `
  --source-metadata-json <OFFICIAL_SOURCE_METADATA_JSON> `
  --twse-raw-json <TWSE_RAW_JSON> `
  --tpex-raw-json <TPEX_RAW_JSON> `
  --output <STAGING_PACKAGE>
```

clock 到達 activation day 後，移除 `--preactivation-staging` 才會把同一 producer 的 rows／registry 交給既有 `pit-sector-membership-prospective-manifest-v1` sidecar writer；輸出 parent 必須先存在且既有檔案不會覆寫。這個入口不註冊 scheduler；後續低 CPU daily capture 仍依 PIT publication → Rule snapshot → T−1 Portfolio transition → frozen inference 的既有順序，由 owner 在 strict readiness 全部通過後另行啟用。任何 readiness、calibration、shadow maturity、Formal OOS、promotion 或 broker gate 未通過時，仍固定 `formal_oos_allowed=false`、alpha=`0`、promotion=`false`、`broker_order_allowed=false`。

### 先預約 clock，再於未來累積正式輸入

prospective-only 的三份輸入在 activation 前尚不存在是合法狀態；若 strict readiness
現在就要求 `non_cash_state_day_count>0`，會形成「沒有 activation 就不能有
transition、沒有 transition 就不能 activation」的循環。因此可先用明確的 staging
模式預約未來 clock：

日期 preflight 先用獨立的官方日曆 bundle 選出候選日（只產生 proposal）：

```powershell
.\.venv\Scripts\python.exe scripts\plan_prospective_formal_clock.py `
  --now <TAIPEI_NOW> `
  --owner-decision-timestamp <OWNER_DECISION_TIMESTAMP> `
  --calendar-evidence <OFFICIAL_TWSE_TPEX_CALENDAR_BUNDLE> `
  --minimum-preparation-days 1 `
  --lookahead-days 31 `
  --existing-clock-id <ELAPSED_CLOCK_ID> `
  --output <PLANNING_PROPOSAL_JSON>
```

Bundle 最小格式如下；`source_hash` 必須是保存過的官方 response bytes hash，不能填
文件 hash、猜測值或只給單一市場：

```json
{
  "schema_version": "official-trading-calendar-bundle.v1",
  "days": [
    {
      "date": "YYYY-MM-DD",
      "twse": {"is_trading_day": true, "source": "TWSE ...", "source_hash": "sha256:<64 lowercase hex>"},
      "tpex": {"is_trading_day": true, "source": "TPEX ...", "source_hash": "sha256:<64 lowercase hex>"}
    }
  ]
}
```

若手上只有官方 raw 回應，可先用候選-only capture（命令不會自動連線）：

```powershell
.\.venv\Scripts\python.exe scripts\capture_official_calendar_bundle.py `
  --start-date <START_DATE> --end-date <END_DATE> `
  --twse-fixture <TWSE_ANNUAL_JSON> `
  --tpex-fixture <TPEX_MONTH_JSON> `
  --output <TEMP_CANDIDATE_BUNDLE_JSON>
```

若缺少某年度／月份，確認來源可用且允許 bounded GET 後才加上
`--confirm-network`；網路失敗不會建立半成品輸出。fixture／network 混合結果仍只
是日曆候選證據，必須先 owner review source hash，再交給日期 planner。

`candidate_ready` 只表示日期與日曆證據通過；仍須由 owner 審閱 proposal hash，接著
再以 `publish_prospective_formal_clock.py --fixture-only` 建立新的 planned clock。若
看到 `blocked`，應更新官方 bundle 或延長 lookahead；不得把已過 activation day 的
clock 改日期、重跑 one-shot、用 replay／fixture 補日，或以 proposal 直接供 Formal
consumer 使用。所有輸出固定 `formal_oos_allowed=false`、alpha=`0`、
`promotion_eligible=false`、`broker_order_allowed=false`。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_prospective_capture_readiness.py `
  --fixture-only --defer-until-activation `
  --clock-manifest <CLOCK_MANIFEST> `
  --calibration-policy <CALIBRATION_POLICY> `
  --decision-timestamp <FIRST_FUTURE_DECISION_TIMESTAMP> `
  --now <NOW> `
  --symbols-json <SORTED_SYMBOLS_JSON> `
  --output <DEFERRED_READINESS_OUTPUT>

.\.venv\Scripts\python.exe scripts\activate_prospective_formal_clock.py `
  --fixture-only --controlled-environment --defer-inputs `
  --clock-manifest <CLOCK_MANIFEST> `
  --calibration-policy <CALIBRATION_POLICY> `
  --readiness-report <DEFERRED_READINESS_OUTPUT> `
  --owner-activation-id <OWNER_ACTIVATION_ID> `
  --owner-activation-timestamp <OWNER_APPROVED_TIMESTAMP> `
  --now <NOW> `
  --output <ACTIVATION_MANIFEST>
```

`--defer-until-activation` 與 `--defer-inputs` 只建立「等待未來資料」的受控
activation manifest：三個 controlled path 會以 `deferred=true`／`path=null` 保存，
不會給 non-cash day、Formal OOS、promotion 或任何交易 credit；controlled store
identity 與 HMAC configured flag 仍必須存在，且 secret 永不輸出。clock 到達第一個
未來決策日後，owner 才設定三個正式 path，重新執行不帶 defer 的 strict readiness，
並只接受當日實際產生的 T-1 transition、Rule snapshot 與 PIT lineage；不可用歷史、
paper／cash-only ledger 或補日填入 deferred 期間。

### 唯讀 CPU／MCP process custody

若要判斷背景 CPU 或 MCP 是否重複，使用：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_runtime_process_custody.py --sample-seconds 1
```

預設只取樣 Python／MCP／ML 程序，輸出角色分組、PID、CPU／記憶體、duplicate MCP 與單核心 busy warning；`--all-processes` 才會擴大到其他程序。工具不輸出原始 command line、環境變數或 secret，也沒有停止／終止程序功能；`attention_required` 只是要求 owner 人工判讀，不是自動修復或 ML gate。

### 單一 execution-plan handoff

若要一次看完整個 prospective-only 專案目前卡在哪一層，以及下一步要執行的
安全命令，可使用唯讀 execution-plan inspector：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_prospective_execution_plan.py `
  --now <OWNER-SUPPLIED-ISO-TIMESTAMP>
```

它會把受控環境、clock、PFS-06 readiness、owner activation、daily capture、20
個自然 shadow trading days、frozen OOS／calibration／PSI 與 promotion review
列成八個階段，並輸出目前 blockers 與 owner actions。`--now` 必須由呼叫端明確
提供，repo 不會自行選 formal clock 日期；命令不寫三個正式 path、不建立 transition／
Rule／PIT artifact、不啟動 watcher／Direct／OOC，也不輸出 HMAC secret。若要保留
狀態快照，可另加已存在的 parent 與 create-only `--output <PLAN_JSON>`；重複路徑
會拒絕覆寫。

當三個 path 尚未存在時，`next_actions` 會明確列出
`--defer-until-activation` → `--defer-inputs` 的預約分流；這只讓未來 clock
可被 owner 受控排程，不會把缺件變成 ready，也不會啟動 heavy watcher。

2026-08-15 的目前結果是 `waiting_for_owner_inputs`：
`BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH`、
`BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH`、
`BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH` 尚未提供；controlled store identity 與
HMAC secret store 的 configured flag 已可見，但 `formal_oos_allowed=false`、
`heavy_rebuild_launch_allowed=false`、`promotion_eligible=false` 仍維持。

另外，legacy `scripts\maintain_ml_direct_v3_refresh_chain.py` 已加入 prospective
schema guard：若任一受控 path 宣告 `mode=prospective_formal_simulation`、
`scope=prospective_only` 或 `prospective-formal-*` schema，legacy one-shot 會回傳
blocked；`--watch-formal-inputs` 只低 CPU 等待，不會啟動 Direct/OOC。這個 guard
只記錄 schema／mode blocker，不輸出檔案路徑、環境值或 HMAC；prospective data
必須交給獨立 capture lane。

clock manifest 只是起算邊界與 identity custody，不會產生任何 transition。若 activation 已到達且 SQLite 內已有合法 prospective transitions，可先用
`scripts\publish_prospective_simulated_portfolio_ledger.py --fixture-only` 產生
`prospective-formal-simulated-portfolio-ledger-manifest.v1`。它會重新驗證 recursive
chain、T-1、non-cash day、clock identity、relative child path 與 SQLite file hash，並
以 create-only 寫入；不會設定 `BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH`，也不會把
research／fixture ledger 升格成正式歷史證據。

Readiness 通過不等於 Formal OOS 或 promotion permission。完成 PFS-07 後，下一階段是只累積真實經過的交易日、PIT／Rule／Portfolio chain 與 matured outcomes；任何 Gate 失敗都維持 alpha=`0`。

Controlled activation 的命令仍需 owner 明確提供 clock、policy、readiness、activation id、
已發生的 owner activation timestamp、`--now` 與 create-only output；不會自行選 activation
trading day，也不會啟動 watcher／Direct／OOC：

```powershell
.\.venv\Scripts\python.exe scripts\activate_prospective_formal_clock.py `
  --fixture-only --controlled-environment `
  --clock-manifest <CLOCK_MANIFEST> `
  --calibration-policy <CALIBRATION_POLICY> `
  --readiness-report <READINESS_REPORT> `
  --owner-activation-id <OWNER_ACTIVATION_ID> `
  --owner-activation-timestamp <OWNER_APPROVED_TIMESTAMP> `
  --now <NOW> `
  --output <ACTIVATION_MANIFEST>
```

PFS-08 maturity inspector 可用於受控 fixture 的唯讀檢查：

- `scripts\capture_prospective_shadow_observation.py --fixture-only` 可把單日、已由 PIT／Rule／Portfolio／inference producers 產生的 lineage hashes 與已成熟 outcome rows 組成一筆 immutable observation；它只接受 activation 後日期與 T-1 input state，任何 future target、replay、backfill 或 unsafe flag 都由 PFS-08 validator 拒絕。
- `scripts\inspect_prospective_shadow_maturity.py --fixture-only` 讀取 activation-bound complete observations，只接受已發生的 decision／outcome timestamp、T-1 input 與 canonical hashes；缺少 5／10／20／60 horizon 時保持 waiting，不以 replay 或補日填入。
- maturity gate 固定要求至少 20 個 unique shadow days、每個 horizon 至少 20 個 matured observations，且 `rebalance_worthwhile` class 0／1 都是自然觀測；`future_teacher_target_used`、`same_day_advice_used`、replay、backfill 或 synthetic outcome 任一為 true 都會 fail-closed。
- 輸出 `maturity_gate_ready_shadow_only` 仍不解除 `formal_oos_allowed=false`、alpha=`0` 或 broker disabled。下一階段 PFS-09 才能對 frozen candidate 產出 matured Formal OOS replay、calibration 與 PSI evidence。

PFS-09 frozen-candidate evidence inspector 可用於受控 fixture 的 hash custody：

- `scripts\inspect_prospective_frozen_oos.py --fixture-only` 只讀 PFS-08 maturity report、primary／verification replay wrappers、inference calibration audit 與 integer-bp PSI report；兩個 replay 必須綁同一 frozen model／dataset／feature／policy identity，`result_identity_hash` 與 `replay_result_hash` 必須相同。
- 缺 primary／verification、maturity、calibration 或 PSI，或 quality／identity 不通過時，輸出 `waiting_for_frozen_oos_evidence` 與 blockers；不會呼叫現有重型 replay engine，不會 fit／retrain／事後選 calibration method。
- 即使輸出 `ready_for_formal_review`，仍固定 `formal_oos_allowed=false`、production alpha=`0`、promotion=`false`、broker disabled。PFS-10 才負責 promotion review 與人工／機器 Gate authority。

PFS-10 promotion review inspector 可用於受控 fixture 的最後 machine-gate aggregation：

- `scripts\inspect_prospective_promotion_review.py --fixture-only` 讀取 PFS-09 package 與 10 個 machine-gate 布林值；缺件或任一 false 都輸出 blockers，所有 true 時才輸出 `ready_for_owner_review`。
- `ready_for_owner_review` 不等於 promotion。review package 永久固定 `owner_review_required=true`、`owner_review_received=false`、`owner_authorization_received=false`、`promotion_eligible=false`、`formal_oos_allowed=false`、alpha=`0`、broker disabled。
- 這個命令不選 activation 日期、不設定 Windows path／secret、不啟動 watcher／Direct／OOC；下一步必須由 owner 在受控環境另行決定是否開始未來 clock。若要 retrain／recalibrate，先關閉本 clock，建立新 candidate 與新 clock。

### Activation handoff preflight

設定 owner-controlled paths 後，先執行：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_prospective_activation_environment.py
```

它只回報三個 formal path 的 configured／exists／file hash、controlled store 是否配置，
以及 HMAC secret store 的 configured 布林值；不會輸出 secret、不會設定環境、不會啟動
任何 ML 程序。若任一路徑缺失，狀態是 `waiting_for_controlled_environment`；即使全部
ready，也仍要由 owner 提供未來 activation decision，才可使用 fixture-only activation
command。當前 preflight 的三個 formal path 都是 missing，這是預期的 fail-closed 狀態。

Owner 設定三個 path 後，可用下列明確 opt-in 的唯讀模式把同一份 controlled
environment 直接交給 PFS-06 readiness；這個模式不會把 path 寫回 process、repo 或
任何正式 artifact，也不會讀出 HMAC secret：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_prospective_capture_readiness.py `
  --controlled-environment `
  --clock-manifest <CLOCK_MANIFEST> `
  --calibration-policy <CALIBRATION_POLICY> `
  --decision-timestamp <DECISION_TIMESTAMP> `
  --now <NOW> `
  --symbols-json <SORTED_SYMBOLS_JSON> `
  --output <READINESS_OUTPUT>
```

`--controlled-environment` 與 `--fixture-only` 互斥；任何 path missing、非檔案或
PFS-06 ledger／Rule／PIT custody 驗證失敗都會回傳 blocked。即使 readiness ready，
`capture_only=true`、`heavy_rebuild_launch_allowed=false`、`formal_oos_allowed=false`、
alpha=`0` 與 broker disabled 仍不變，後續仍需 owner 的 future activation manifest。

## 2026-08-14 自動鏈 current state

### 正式 ML 輸入接線狀態（2026-08-14）

正式 Direct／OOC 路徑現在可以消費三種受控輸入，但本機目前仍沒有合法來源，不能把這段「已接線」解讀成 gate 已通過：

- `--formal-portfolio-ledger` 必須指向 `causal-portfolio-ledger.v1` manifest；loader 會以唯讀 SQLite 驗證 append-only transition schema、每列 state hash、recursive chain、T-1 calendar 對齊與 non-cash state，拒絕 research-only、Teacher 回灌或 same-day Advice。
- `--formal-rule-champion-history` 必須指向 `rule-champion-snapshot-history.v1` manifest；每列都必須來自 controlled-store HMAC、immutable snapshot hash、連續 rank 與正式 Rule-only proof。執行環境必須提供受控的 `RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY` 與 `RULE_CHAMPION_CONTROLLED_STORE_ID`，不得寫入 repo、命令列、status 或 log。
- `--sector-membership` 仍只接受 `pit-sector-membership-sidecar-v1` 的 accepted／license／source hash／available_at／effective range custody；不可用當期 company registry 回填歷史產業歸屬。

若要讓每日 `baldr-ml-direct-chain-maintainer` 自動接收外部正式來源，可在 Windows 使用者環境設定 `BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH` 與 `BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH`；兩者只接受明確檔案路徑，維護器會先唯讀驗證 ledger chain／training cutoff 與 Rule history HMAC，才把路徑交給 immutable Direct/OOC chain。這兩個環境變數不包含 HMAC secret，secret 仍只由 `RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY` 提供。

若 owner 在 watcher 已啟動後才設定或更換上述 ledger／Rule path、`BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH` 或 Rule runtime environment，長駐 maintainer 會在每次 polling 重新讀取 Windows 使用者／系統環境登錄值，並只在目前 process memory 內更新受控 path、HMAC key 與 store id。它不會寫出 secret，也不會把任何 value 放入命令列、status 或 log；登錄值移除時，watcher 自己採用的 process 內值也會清除，後續正式驗證回到 blocked。這只是環境交接，不會取代三項正式輸入的 schema、hash、cutoff、HMAC 或 promotion gate。

三份輸入會以 file hash、logical manifest hash 與 dataset identity 傳遞到 Direct、OOC store、training 與 OOS replay input；OOS consumer 會再次驗證 ledger／Rule history custody，缺件或 tamper 只會 blocked。沒有合法三項來源時，`formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false` 維持不變；不可用 cash-only ledger、research artifact、current snapshot 或 heartbeat 代替。

可用 `scripts\inspect_ml_formal_input_readiness.py --output-root <OUTPUT_ROOT> --training-as-of <TRAINING_AS_OF> --output <READINESS_JSON>` 做唯讀 readiness check。`TRAINING_AS_OF` 必須是含時區的 ISO 8601 時間（例如 `2026-08-28T00:00:00+08:00`，不可只給 `2026-08-28`），避免 cutoff 時區歧義。它會實際呼叫三個 production validator，記錄每項 input 的 `missing`／`invalid`／`ready`、file hash 與原因，並在報告與 CLI 摘要提供 `ready_input_ratio`（例如 `0/3`）；即使三項皆 ready，也只表示可以進入受控 Direct/OOC refresh，不會直接解除 formal OOS、alpha 或 broker gate。當前 scheduled report 位於 `OUTPUT_ROOT\scheduled\ml_formal_input_readiness\latest.json`。報告另會提供 `prospective_output_observation`，以固定深度列出同一 output root 下已觀察到的 `clock-*` staging／prospective marker；這只是解釋「為何看得到檔案卻仍是 0/3」的診斷，不會自動 discovery、替換 owner-controlled `BALDR_ML_FORMAL_*` path，也不會把 prospective bytes 當成正式 input。此 CLI 在解析參數前設定 UTF-8 stdout/stderr，Windows 預設 CP1252 主控台也能正常使用 `--help`；指定的 readiness output 仍是明確路徑的受控 artifact，不會寫正式資料庫。

若需要回答「候選目錄裡是否其實有檔案」而不改變正式接線，可另用
`scripts\inspect_formal_input_candidates.py --candidate-root <CANDIDATE_ROOT> --output <INVENTORY_JSON>`。
這個盤點器只讀 bounded 的 `manifest.json`（預設最多 512 份），以固定 allowlist 投影 schema／日期／安全旗標並計算 manifest hash；會將檔案分為 `research_only`、`prospective_only`、`formal_schema_candidate` 或 `other`，也會明示 invalid／超過上限的項目。它不讀資料列、不執行 formal loader、不改環境變數，且報告必須寫在候選根目錄之外；`formal_ready_input_count` 永遠不由此工具升格，仍須由 owner-controlled publisher 產出三份正式 manifest，再重跑本節的 readiness check。

若需要把上述 bounded inventory 交給具名 owner／reviewer 逐項處理，可再執行下列唯讀 packet
builder（輸出 JSON／Markdown 的 parent directory 必須先存在，且不可位於 candidate root）：

```powershell
.\.venv\Scripts\python.exe scripts\build_formal_input_owner_packet.py `
  --inventory-path <FORMAL_CANDIDATE_INVENTORY_JSON> `
  --output-json <TEMP_OWNER_PACKET_JSON> `
  --markdown-output <TEMP_OWNER_PACKET_MD> `
  --owner-role <NAMED_OWNER_ROLE> `
  --reviewer-role <NAMED_REVIEWER_ROLE>
```

它只讀取 `ml-formal-input-candidate-inventory.v1`，為 causal portfolio ledger、formal
Rule Champion history、PIT sector membership 三項 expected schema 建立 review record，
並保留 bounded candidate path／manifest hash／lane／原因。即使填入 owner／reviewer 角色，
`owner_decision`、selected／published path 與 custody 仍須人工處理；packet 固定
`formal_ready_input_count=0`、`formal_oos_allowed=false`、`candidate_only=true`、
`write_performed=false`，不會寫正式 path、改名／複製 research／prospective artifact 或
授予 Formal／promotion／broker credit。完成外部出版後，才可用本節 readiness CLI 重新驗證。

Readiness inspector 也會在每項結果標示 `expected_schema_version`。若明確 path 指向
`prospective-formal-*`、`*-prospective-*`、`consumer_mode=prospective_formal_simulation` 或
`scope=prospective_only` 的 wrapper，結果會是
`prospective_manifest_requires_formal_consumer_publication`、`source_lane=prospective_formal_simulation`
與 `formal_consumer_compatible=false`；它不會把 prospective-only bytes 強行轉成正式
`causal-portfolio-ledger.v1`／`rule-champion-snapshot-history.v1`／歷史 PIT input。明確設定的
`BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH` 具有權威性：即使旁邊另有可 discovery 的 sidecar，
只要指定檔案沒有通過 hash-bound production validation，結果仍是 invalid，不會靜默改用另一份檔案。

若 configured path 位於 `formal_prospective/clock-YYYYMMDD/` 且檔案尚未發布，結果會額外揭露
`configured_clock_id`、`configured_clock_date`、`training_as_of_date` 與
`configured_clock_date_before_training_as_of`；日期較舊時 diagnostic 會提示 owner 更新明確受控
path。這只是 handoff 診斷，readiness 不會掃描或自動改接同一輸出根下的其他 clock，也不會把
prospective wrapper 轉成 Formal input。

最新 raw PIT publication 已自動更新至 `pit-a2f236fefac769e7346e04be`（decision
`2026-08-13T08:30:00+08:00`、15,938,679 rows、52 features）。Direct
`direct-ooc-6ff7650245ffea99ced5bf21` 已於 `2026-08-13T21:05:01Z` 完成 2014–2026；
checkpoint、13 個年度 manifest/carry、41 個 fold index 與 `latest_manifest.json` hash custody
均已通過。Direct manifest=`sha256:b52b1211e8bc61c591b0eb4b83ba2877701f7ca4fb1fbd4dff891e57b660d676`，
共 3,335,023 rows、62 features、41 folds，peak temporary bytes=`24,522,523,967`。

OOC 已由既有 helper 自動以該 Direct manifest hash 啟動 current run
`allocation-ooc-9750e409b0622fb4472a1a0f` 已完成，manifest hash=
`sha256:9faa8ec2d873d2b46efc23c8dbc42cfeb555bd1d9eeb8697ab24c7aa2d07c498`；共
3,335,023 rows、41 outer folds、40 meta folds、984 base experts 與 24 final experts，且
`store_manifest_hash` 綁定上述 Direct manifest。OOC 的 future／PIT／constraint violations
均為 0，peak RSS=`3,451 MB`／budget=`4,096 MB`。但正式 replay-input 仍因
`causal_non_cash_portfolio_ledger_present`、`formal_rule_champion_snapshot_history_present`
與 `pit_sector_membership_present` 缺件而 blocked；release follow-up 不會把中間 artifacts
或 heartbeat 當成可升級證據。所有 formal／production／broker gate 仍固定
`formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false`。上一輪 OOC
`allocation-ooc-2416e7265c6f3c15072173c6` 僅作歷史完整產物保存。

若 Windows 將長時間 supervisor 中止，系統會保留既有 child chain、清理已死亡 owner 的
stale lock，並由下一次 maintainer invocation 自動重新取得唯一 lock；不需要人工停止、刪除
run 或重訓。2026-08-13 已實際完成此 recovery，Scheduler query 的
`baldr-ml-direct-chain-maintainer` `Last Result=0`，沒有平行 chain。正式 gate 仍固定
`formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false`。

> **最後更新：2026-08-13｜適用 V4.0 Operational Production**。Decision／Advice／Rule 配置／Paper Portfolio 與 evidence loop 已可正式日常運作；不連接券商。ML 為 Production Co-pilot，非零 alpha 完全由自動 promotion artifact 決定；目前證據不足時顯示 `alpha=0` 是正確 fallback，不需要也禁止人工解除。

## V4.0 每日操作

### ML Co-pilot 排程自動補跑

ML allocation 排程入口會自動使用 --auto-catch-up。當沒有明確指定
ML_ALLOCATION_DECISION_AT、排程選到下一個台北曆日，且完整 orchestration
實際證明該候選日的 strict T-1 尚未就緒時，系統會依既有 hash-bound raw
publication 與 post-freeze T-1 proof，向後重試最多 31 個曆日。它不寫入
來源資料庫、不使用未來資料，也不把回溯日偽裝成原始候選日。

若資料庫、價格欄位或官方交易日曆狀態未知，系統不猜測、不改日期，依原
候選日繼續既有 fail-closed 流程；若由環境指定明確決策時間，則完全不會
自動改選。可在
OUTPUT_ROOT/scheduled/ml_allocation_copilot/latest_status.json 查看
decision_selection_mode、requested_decision_at、
decision_selection_reason 與 decision_selection_attempts。

本輪 direct store refresh 另由 `scripts\continue_ml_release_after_ooc.py` 受控等待；OOC helper 完成且 continuation status 與最新 training pointer 的 manifest hash 完全一致後，它會自動接續 evidence → authority → copilot，並寫入 `post_ooc_followup_status.json`。這只是 fail-closed 的營運銜接，不代表 promotion 授權，也不會解除 alpha=0、broker order disabled 或正式 SQLite 唯讀邊界。

若 direct process 已完成但 supervisor 因 Windows launcher／custody race 中斷，可由受控流程使用 `scripts\continue_ml_direct_ooc_after_store.py --resume-after-direct-store` 重新驗證 immutable direct manifest 後續接 OOC；這個模式不捏造 direct PID 存活，仍要求 checkpoint、年度 manifest、fold index 與 hash custody 完整。Promotion evidence 對 official market-event custody 以 `canonical_events_hash` 判定事件內容；相同 canonical timeline 的 wrapper／duplicate metadata 重發布不要求重建 direct store，canonical hash 改變仍 fail-closed。

### 資料更新後 raw PIT 自動發布

`baldr-ml-raw-pit-refresh-daily` 會在 data-update quick 之後自動檢查
`OUTPUT_ROOT/scheduled/data_update_quick/latest_status.json`。只有 status 為
`passed`／`passed_with_warnings`，且 `check_overview_after` 證明 daily 與
technical core date 都已就緒時，才會以 SQLite `mode=ro/query_only` 建立全市場
immutable raw PIT publication。它使用當日 08:30 Asia/Taipei 作為 decision cutoff，
不寫回來源 SQLite、不建立 promotion evidence，也不改變 formal gate。

使用者不需要手動重建或手動觸發 ML。相同 cutoff 已有較新的合法 publication 時，
runner 會寫入 `skipped_current`；更新完成但上游 proof 尚未就緒時寫入
`blocked_upstream_not_ready`，下一個排程會自動重試；新 publication 完成後，
Direct/OOC maintenance watcher 依 raw pointer、canonical hash、dataset safety 與
training identity 自動接續，缺少正式 custody 時仍保持 `formal_oos_allowed=false`、
`alpha=0` 與 `broker_order_allowed=false`。

2026-08-12 首次自動 refresh 已發布 publication
`pit-29505ceb0005d068610dde01`：decision cutoff=`2026-08-12T08:30:00+08:00`、
`all_field_enriched`=`15,932,713 rows / 52 features / 13 shards`，dataset hash=
`sha256:90ea99f71d689060123c187bba8db5335d6aa106620f130d325e2a3dbbcc04d3`。
Watcher 隨後自動啟動 Direct immutable run；若 Direct/OOC 尚未完成，應以 heartbeat、
checkpoint 與 latest manifest 判斷進度，不把 processed rows 當成完成。此次 handoff
也修正了合法 `sector_membership_file_hash=null` 被誤判為字串 hash 的問題；沒有 sector
sidecar 時仍維持 formal gate 關閉。

Raw publication 完成後不需要人工啟動 Direct 或 OOC。每日 05:30 的
`baldr-ml-direct-chain-maintainer` 會自動重驗最新 raw pointer、全市場 scope、
dataset safety、official market-event custody 與目前 Direct identity，接著啟動或
維持 `maintain_ml_direct_v3_refresh_chain.py --watch-formal-inputs`。既有 chain lock、
checkpoint、年度 manifest 與 hash-bound pointer 會防止重複訓練並在 worker／supervisor
中斷後續接；無效輸入只留下 `blocked_invalid_bootstrap_input`，不會以人工輸入或猜測
sidecar 繼續。狀態位於：

`OUTPUT_ROOT/scheduled/ml_direct_chain_maintenance/latest_status.json`

OOC 訓練器的 calibration gate 也已改為 expanding outer-fold 的 cross-fitted
OOF 診斷：每個 target fold 只使用更早、且在下一 fold 開始前已成熟的 OOF
blocks，probability 與 metrics 均以整數 bp 保存。結果會標記
`oof_diagnostic_only=true`、`production_eligible=false`；不會把未校準的
base vector 靜默改寫成校準後 vector。若 training manifest 出現
`classifier_calibration_not_attached_to_ooc_model`，代表 cross-fitted 診斷
已完成但尚未形成可供 OOC inference 使用的 production calibration artifact，
不得據此解除 formal OOS、alpha 或 broker gate。

該 status 的 `completed` 也包含「已有合法 owner 持有 lock、此次安全跳過」的正常情況；
此時會明列 `execution_disposition=existing_owner_lock`、
`maintenance_lock_state=verified` 與經命令列驗證的 `maintenance_owner_process_id`，且
owner 命令列必須與同一個 `training_output_dir` 完整相符。若 Windows 暫時拒絕讀取
live owner 命令列，wrapper 會標記 `execution_disposition=owner_lock_unverifiable`、
`maintenance_lock_state=owner_lock_unverifiable`，維護器會保留 lock 並等待下一輪驗證，
不會把未知 owner 當 stale lock 刪除。這不代表 Direct/OOC 已完成，長鏈進度必須看 heartbeat、checkpoint 與 immutable
latest manifest。整條自動鏈固定維持 `database_mode=ro`、`query_only=true`、
`writes_source_database=false`、`formal_oos_allowed=false`、`production_alpha_bp=0`、
`broker_order_allowed=false`。

可觀測路徑：

- `OUTPUT_ROOT/scheduled/ml_raw_pit_refresh/latest_status.json`
- `OUTPUT_ROOT/scheduled/ml_raw_pit_refresh/refresh.log`
- `OUTPUT_ROOT/release_v4/ml_pit_year_shards/latest_manifest.json`
- `OUTPUT_ROOT/release_v4/ml_pit_year_shards/runs/<publication_id>/`

1. 開啟 `ui_qt/main.py`，從市場總覽確認 Market Breadth、Sector Rotation、Relative Strength/Liquidity、Watchlist Trigger 與 Portfolio Alerts。Workbench 的「決策來源」仍導向同一個 Decision Desk，不建立第二份狀態。
2. Advice 必須含 action、Why／Why Not、Risk Prompt、target/current/gap/executable。`current` 不明時會保留 unknown，不能猜成 0，也不能產生可執行 gap。
3. 可見 action 為 `ADD_CANDIDATE`、`HOLD`、`REDUCE_CANDIDATE`、`EXIT_CANDIDATE`、`NO_NEW_POSITION`、`AVOID`。它們是配置與硬限制後的決策建議，不是券商委託。
4. 檢查 `OUTPUT_ROOT/scheduled/ml_allocation_copilot/latest_status.json`：`selected_alpha_bp=0` 表示 Rule-only；只有可信 promotion custody、consumer re-verification 與所有 thresholds 都通過，才可能出現 2000／3500／5000。`shadow_day_credit_allowed=false` 代表本日 observation 已正常保存，但因正式 Rule/context custody 不足而不計入 20 日 Promotion 門檻，不是 runner 失敗。request 中自行填入非零 alpha 不會生效。
5. 檢查 `OUTPUT_ROOT/scheduled/decision_evidence_capture/latest_status.json` 與 `OUTPUT_ROOT/scheduled/paper_portfolio_daily/latest_status.json`。前者應揭露 snapshot/event counts；後者應揭露 T-1 diagnostics、cash、total value 及 market DB `ro/query_only`。
6. Gate 2 weekly history 不得由 scheduler sidecar 自動計入 Gate：Windows weekly collection 只產生 `pending_human_review`，不代表人工核准或 formal credit。若未設定具名 owner 核准的 `approved-weekly-history-projection.v1`，目前 UI／readiness 會如實顯示 `0/3 waiting_for_time`；若日後提供 projection，也只供 UI 進度揭露，不能改變 `formal_credit_authorized=false`、`production_scheduler_allowed=false`。forward、Paper elapsed、Exit outcome、ML shadow days 與非零 alpha 仍由各自的 evidence maturity 決定。

### ML Promotion Reference 與 Shadow Evidence

凍結 reference 必須由正式 training model／manifest／dataset manifest 產生，不能拿 daily observation 自建 baseline：

```powershell
.\.venv\Scripts\python.exe scripts\build_ml_allocation_promotion_reference.py `
  --model-artifact <RELEASE>\allocation_model_v3.joblib `
  --training-manifest <RELEASE>\training_manifest_v2.json `
  --dataset-manifest <PORTFOLIO_TRAIN_RUN>\manifest.json `
  --promotion-policy-hash sha256:<POLICY_HASH> `
  --output-root <OUTPUT>\ml_promotion_reference_v4
```

Canonical reference v2 為 22,093 rows、62 features／3 formal families，reference hash=`sha256:8ee81ae9c5691c6e10d95f14eac293b2ecd121a53877f0d0de73e20b514dd5b0`、file hash=`sha256:d02ab09f8cfa19449b7524d4ca12139a9e27e55b2f4d78f70cbc1be15821800f`，並綁定 outcome contract=`sha256:95172f7d8678fd6ecde83c1c166b56878b0d3b769750290acb5b0b3753c96a11`。每日排程會自動載入此 reference，分別保存 5／10／20／60 日 calibrated／uncalibrated downside probabilities 與 current feature/family distribution；使用者不需也不能手工填 calibration 或 PSI。

每日結果位於：

- `OUTPUT_ROOT/scheduled/ml_allocation_copilot/shadow_evidence_collector/shadow_evidence.sqlite`：append-only observation／outcome revisions。
- `.../observations/`、`.../evidence/`：immutable 四 lane observation 與彙總。
- `.../reference_metrics/<hash>.json` 與 `latest_reference_metrics.json`：逐 horizon immutable calibration／drift metrics custody。
- `.../production_advice/<date>_alpha_0.json`：目前合法 Rule-only Advice，不是券商委託。
- `OUTPUT_ROOT/scheduled/ml_promotion_evidence/latest_status.json`：05:17 unsigned evidence preflight；blocked 不代表 Rule 失敗。
- `OUTPUT_ROOT/release_v4/ml_promotion_authority/latest_status.json`：05:18 DPAPI Authority 是否簽章及 machine blockers。

同日同 custody 重跑必須顯示 `idempotent=true`；同日新 custody 只追加 revision，成熟天數仍只算該日最新 revision一次。任一 horizon 未滿 20 個唯一成熟交易日時，ECE、calibrated／uncalibrated Brier、feature/family PSI 都應是 `null / NOT EVALUATED`，reference maturity blocker 格式為 `matured_shadow_days_insufficient:h<horizon>:<n>/20`。看到 `0` 指標、缺 hash custody、future/PIT violation 或 reference tamper 都應視為錯誤並保持 `alpha=0`。

2026-07-31 最新 canonical reference-v2 接線驗證已保存 observation revision=7、fully matured outcome=0；shadow evidence hash=`sha256:82332fb24eb62dcf2018e8d940d9f7e4faa21dd83a5e9bd48990dbd2d6d36669`，metrics hash=`sha256:607adf7b48f4210809ee2f31d355d3adfef56027cb0d7d6322db3fd02dda750d`。該 observation 明確為 `promotion_day_credit_allowed=false`，所以 5／10／20／60 日 promotion 計數均為 `0/20`；全市場 OOC 與正式 semantic replay 亦尚未形成 compatible evidence，reference baseline／feature distribution 則為 `ready`。

## V4.0 排程

| 本機時間 | Task | 寫入範圍 |
|---|---|---|
| 04:20 | `baldr-data-update-quick-daily` | 既有市場 raw/SQLite 更新 |
| 04:50 | `baldr-official-market-events-daily` | append-only 官方 market-event vintages |
| 05:00 | `baldr-data-freshness-check-daily` | status/log only |
| 05:05 | `baldr-ml-raw-pit-refresh-daily` | full-market immutable raw PIT publication；僅讀取來源 SQLite |
| 05:10 | `baldr-recommendation-snapshot-daily` | research recommendation snapshot |
| 05:15 | `baldr-evidence-pipeline-dry-run-daily` | dry-run report |
| 05:17 | `baldr-ml-promotion-evidence-daily` | unsigned formal OOC／雙 replay／Shadow／metrics evidence |
| 05:18 | `baldr-ml-promotion-authority-daily` | DPAPI machine authorization；不足即不簽 |
| 05:20 | `baldr-ml-allocation-copilot-daily` | immutable lane sidecar/promotion status |
| 05:25 | `baldr-decision-evidence-capture-daily` | durable DDD snapshot + evidence events |
| 05:28 | `baldr-paper-portfolio-daily` | isolated append-only Paper ledger |
| 05:30 | `baldr-ml-direct-chain-maintainer` | 自動 bootstrap／維持 Direct → OOC watcher；只使用 hash-bound immutable input |
| 週日 18:00 | `baldr-v2-2-weekly-collection` | append-only weekly evidence sidecar + machine revalidation |

官方 market-event task 平時只抓前一年度與當年度的增量；若 `latest_manifest.json` 的 verified publication 歷史起點不是 2014，排程會自動改抓 2014–當年度做 recovery，成功後下一輪恢復兩年增量。這個 recovery 只追加 raw／canonical publication 與 status，不寫 active SQLite、不改 Rule／Portfolio、不授權 ML alpha。

查詢：

```powershell
scripts\scheduled\query_baldr_scheduled_tasks.cmd
```

目前 12 個 daily tasks 加 1 個 weekly task 共 13 個 Windows tasks。ML evidence／Authority／Co-pilot 三段與 Direct chain maintainer 已實際觸發且 `Last Result=0`；raw PIT refresh 與 Direct chain 各有獨立 immutable／bootstrap status，若 OOC／replay 尚未完整仍只輸出 `blocked` 或維持等待，Authority 可輸出 `skipped_evidence_unavailable`，這些都是成功的 fail-closed 營運狀態。Scheduler process-level 成功不表示資料來源全數 observed 或 ML promotion 已通過。所有 tasks 都不得送單；只有經成熟度、交易日、雙 replay、簽章與 inference-release identity 全部驗證的 evidence 才能影響 alpha。

2026-08-12 本機唯讀 query 顯示 13/13 tasks 均為 `Enabled`／`Ready`；raw PIT refresh 與 Direct chain maintainer 的實際觸發結果均為 `Last Result=0`，執行結果分別以 `ml_raw_pit_refresh/latest_status.json` 與 `ml_direct_chain_maintenance/latest_status.json` 判定。目前 `Logon Mode=Interactive only`，因此證明的是互動式帳號下的排程註冊與最近成功結果，不代表已完成無人登入執行。`production_scheduler_allowed=false` 仍是正式 production evidence／交易授權邊界，不能因 task 已註冊而放寬。

Windows task 的註冊、正在執行與 `Last Result` 必須以以上 query 命令判定；Runtime 頁只讀已保存 status artifact，不能取代此查詢。

補充：handoff supervisor 若使用自訂 `--status-path`，會自動將三個 child process 的 operational log 寫到 heartbeat 同層的 `logs` 目錄；這是為了在正式資料目錄無法寫入 log 時仍能自動續接，並不改變正式 manifest、SQLite 或 fail-closed gate。未指定自訂 status path 時，仍使用既有 direct/training `logs` 位置。

## 全欄位資料稽核與年度 shards

```powershell
.\.venv\Scripts\python.exe scripts\inspect_ml_all_field_readiness.py `
  --decision-at 2026-07-30T08:30:00+08:00 `
  --history-start-date 2014-01-01 `
  --output-dir D:\Min\Python\Project\FA_Data\output\release_v4

.\.venv\Scripts\python.exe scripts\inspect_ml_file_field_inventory.py `
  --data-root D:\Min\Python\Project\FA_Data `
  --output D:\Min\Python\Project\FA_Data\output\release_v4\ml_file_field_inventory.json

.\.venv\Scripts\python.exe scripts\build_ml_pit_year_shards.py `
  --database D:\Min\Python\Project\FA_Data\sqlite\twstock.db `
  --output-dir D:\Min\Python\Project\FA_Data\output\release_v4\ml_pit_year_shards `
  --decision-at 2026-07-30T08:30:00+08:00 `
  --history-start-date 2014-01-01 `
  --all-universe
```

正式 train 只讀 manifest 中 `formal_backfill`，以及未來通過來源／授權／publication lineage 驗證後才可能出現的 `first_seen_only`。本次 freeze 的 disposition summary 為 `formal_backfill=52`、`first_seen_only=0`、`research_shadow=32`；月營收／財報／估值的 4 個數值候選與其他 28 個新資料欄位都只能留在 `research_shadow_all_fields`。legacy pickle/predictions/replay/outcomes、現在公司快照及缺 provenance 欄位不能被搬進正式 manifest。ATR/ADX 由 shard builder 依 OHLC prefix 重算；不要把原表 NULL 以 0 補值。

2026-07-30 全市場 publication 與 2026-08-07 舊 direct／OOC artifact 仍保留為歷史 immutable 輸出。2026-08-12 自動 refresh 已完成新的 raw PIT publication：dataset manifest=`sha256:739026b63bfd5a7780baa1714ebd53a5cc5662ef620518ebe3f0b024df2d98e6`、15,926,733 rows、52 features；Direct run=`direct-ooc-94355ffac5a541dbd9cb7282`、canonical manifest=`sha256:0bd97a301a1367ca3a8378cb45c4c9250eebc0dd6e49ced7c313ec39ad655639`，OOC run=`allocation-ooc-05fd4dd6515cddfdf6e0228d`、training manifest=`sha256:07cf93b6f707641e37fce791603f354f20099132df004a93099faec388feefe2`；兩個 `latest_manifest.json` 均已原子切換。Direct numeric v4 將官方 halt/resume event 以 `effective_at`／`available_at` 綁定至每個 replay row；任何舊 run 都不回溯改寫。這代表新的 training custody 已發布，**不代表** full-market readiness、formal replay、ML promotion 或非零 alpha 已通過。應檢查：

- `OUTPUT_ROOT/release_v4/portfolio_ml_direct_numeric_production_v4_v2/latest_manifest.json`
- `OUTPUT_ROOT/release_v4/portfolio_ml_direct_ooc_training_production_v4_v5/latest_manifest.json`

`continuation_status.json` 會在 OOC helper 啟動等待時先寫入 `waiting_for_direct_store`，並在等待期間只鏡像 PID 與受監督 direct process 相符的最新有效 heartbeat（若存在）；進入長時間 OOC 訓練後，會以 `portfolio-ml-ooc-heartbeat.v1` 的 `training_running` 持續發布訓練 PID、啟動／心跳時間、store manifest hash 與命令列 custody；完成或失敗後才寫入 terminal 狀態。新版 waiting、custody、training heartbeat、complete 與 blocked status 都會明列 `formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false`；若舊版 helper 已結束但 terminal status 缺少欄位，release coordinator 會自動補寫這些 fail-closed 欄位，明確 true／非零值則阻擋後續 release。它仍不是 OOC 發布權威，必須以 `latest_manifest.json` 指向的完整 manifest 和 promotion evidence status 判讀。Direct numeric store 的每個 run 另會寫入 `runs/<run_id>/heartbeat.json`，揭露目前 stage、PID、已完成年度與 UTC `updated_at`；兩種 heartbeat 只供進度觀測，完成仍必須由 checkpoint、年度 manifest 與 hash-bound `latest_manifest.json` 驗證，不得以 heartbeat 單獨宣告完成。現況 OOC replay-input 與 promotion evidence 都因 `causal_non_cash_portfolio_ledger_present`、`formal_rule_champion_snapshot_history_present`、`pit_sector_membership_present` blocked；strict T-1 已由 data-update quick 證明至 `2026-08-12`，因此不是 freshness blocker。`formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`broker_order_allowed=false` 仍是唯一有效值。

若一輪舊 direct run 已在背景執行，不需要人工停掉或重跑；受控 handoff supervisor `scripts\continue_ml_direct_v3_refresh_chain.py` 可等待既有 direct／OOC／release PID 與命令列完整結束，然後自動建立新的 immutable direct v4、綁定新的 OOC 與 release helper。它會寫入 `v3_refresh_chain_status.json` 與各階段 log；等待期間另以 `portfolio-ml-direct-v3-refresh-chain-heartbeat.v1` 原子鏡像受監督 PID、命令列與等待階段，避免長時間 `waiting_for_legacy_chain` 被誤判為失聯。release helper 的 `post_ooc_followup_status.json` 也會以 `portfolio-ml-release-followup-heartbeat.v1` 鏡像 OOC helper custody。舊 run 保留不動，任何 custody、hash、readiness 或後續 promotion gate 不通過時仍固定 `formal_oos_allowed=false`、alpha 0，不會改寫正式 SQLite。

若 supervisor 自身在 legacy chain 停止後中斷，恢復入口 `--resume-after-legacy-chain` 會先掃描完整命令列；只要仍有相符的 direct／OOC／release process 就 fail-closed，不會重複建置，確認全部停止後才從既有 checkpoint 接續。恢復失敗會寫入獨立 recovery status，不會覆蓋仍在運作中的 primary supervisor status。

若要讓長時間 refresh 在 Windows worker 或 supervisor 因 sleep／process 中斷後自動
恢復，可由背景程序執行 `scripts\maintain_ml_direct_v3_refresh_chain.py`，並傳入
同一組 raw manifest、training-as-of、database、store output 與 training output
參數。維護器會先掃描完整命令列；任何 Direct／OOC／release target 存活時只等待，
不會平行啟動第二條 chain。全部 target 停止且 `v3_refresh_chain_status.json` 尚未
`complete` 時，才會自動呼叫 `--resume-after-legacy-chain`，沿用同一 immutable run
identity，讓 checkpoint 驗證後重建未完成年度。training output 另有 instance lock
防止重複維護器競爭；lock owner 必須同時符合 maintainer 腳本與同一個 training output
路徑的 process custody。這個程序只做 custody／retry orchestration，不寫正式 SQLite、
不直接改 latest pointer，也不放寬 `formal_oos_allowed=false`、alpha 0 或 broker
disabled。

OOS replay 由 `build_ml_allocation_oos_portfolio_replay.py` 產生 primary／verification 兩次獨立結果。它只接受 training run 內的 `allocation-ooc-replay-inputs.v1` execution ledger、Rule baseline 與 realized daily returns；缺件時會在 `ml_allocation_oos_replay_production_v4/<role>/blocked/` 留下精確 blocker，且不建立／覆寫 `latest_replay.json`。禁止用 Teacher target 或 horizon label 合成一份看似通過的 replay。

即使帳務 replay 完成，也必須查看 `formal_semantic_validation`。目前工程 artifact 固定 `verified=false`、`promotion_eligible_input=false`，因為尚未由獨立 verifier 從官方交易日曆、production Rule Champion、完整六頭 Meta OOF 與 retro raw derivation 重建每日 requested／projected holdings。Promotion Builder 另要求至少 4 個 Meta OOF folds；少一項就維持 `alpha=0`。Cash-only 訓練 state 不得在 replay 階段事後改造成非現金 state。

`build_portfolio_ml_training_shards.py --sector-membership` 只接受 `pit-sector-membership-sidecar-v1` 封套。每列必須是 `status=accepted`，並含 `source_id`、`license_id`、`source_hash`、`available_at` 與 effective range；manifest 必須帶可重算的 canonical rows／manifest hash。舊式裸 JSON array、non-accepted row、缺欄、hash tamper、cutoff 後才可得的 mapping 與 `meta_data/companies.csv` 當期快照都會使 build blocked。不要把 2026 公司清單改寫成較早 `available_at` 或歷史產業 sidecar。

Portfolio ML dataset assembler 會按 decision time 先選可適用的最新 event period，再在該 period 內選當時已可得的最新 revision；較舊 period 的晚到修訂不得覆蓋較新的適用 period。輸入 manifest 與 raw observation 的 JSON boolean 欄位只接受真正的 `true`／`false`，`0`、`1` 或字串一律 fail-closed。

正式 assembler 必須明示 portfolio state policy 與 transition custody；沒有 canonical recursive ledger 的 publication 不得宣稱已學到 turnover 或 cooldown。全種類 research 流程須接續執行下方 causal ledger overlay，Teacher target 只作 supervised label，不會回灌成下一決策日 state。Teacher 的 `cvar_loss_bp` 使用 20 日路徑最差 20% session loss 的平均 tail loss，不再以 MAE 代替。

### 建立並訓練全種類 Research Challenger

下列流程把正式配置列與所有 `research_shadow` 欄位在相同 `symbol + decision_at` 做 PIT as-of join。它會實際進入配置型 Ridge／Logistic／HGB experts 與 Meta Allocator，但永遠不能供正式 orchestrator、Promotion 或非零 alpha 使用：

```powershell
.\.venv\Scripts\python.exe scripts\build_ml_research_shadow_union.py `
  --formal-raw-manifest <PIT_RUN>\all_field_enriched\manifest.json `
  --shadow-raw-manifest <PIT_RUN>\research_shadow_all_fields\manifest.json `
  --base-training-manifest <PORTFOLIO_TRAIN_RUN>\manifest.json `
  --corporate-action-manifest <OFFICIAL_EVENT_RUN>\manifest.json `
  --output-dir <OUTPUT>\ml_research_shadow_union

$pointer = Get-Content <OUTPUT>\ml_research_shadow_union\latest_manifest.json |
  ConvertFrom-Json
$unionManifest = Join-Path <OUTPUT>\ml_research_shadow_union $pointer.manifest_path

.\.venv\Scripts\python.exe scripts\build_ml_research_causal_ledger_overlay.py `
  --research-union-manifest $unionManifest `
  --output-dir <OUTPUT>\ml_research_causal_ledger

$ledgerPointer = Get-Content <OUTPUT>\ml_research_causal_ledger\latest_manifest.json |
  ConvertFrom-Json
$ledgerManifest = Join-Path <OUTPUT>\ml_research_causal_ledger $ledgerPointer.manifest_path
$ledgerRoot = Split-Path $ledgerManifest
$trainArgs = @(
  'scripts\train_ml_research_shadow_challenger.py',
  '--dataset-manifest', $ledgerManifest
)
foreach ($shard in Get-ChildItem $ledgerRoot -Filter 'year=*.jsonl.gz') {
  $trainArgs += '--input'
  $trainArgs += $shard.FullName
}
$trainArgs += @(
  '--artifact-output', '<OUTPUT>\research_model.joblib',
  '--audit-output', '<OUTPUT>\research_audit.json',
  '--manifest-output', '<OUTPUT>\research_training_manifest.json'
)
& .\.venv\Scripts\python.exe @trainArgs
```

官方事件 manifest 只允許 publication-time 可證明且 `result_only=false` 的停復牌／交易限制事件進特徵；除權息、減資等 result-only 事件不得反推公告時點。Causal ledger overlay 會逐 decision date 只讀 T-1 價格 prefix 與前一日 state，以整數 bp 遞迴 Rule／Risk Budget／Inverse Volatility baseline，並套用現金、檔數、單檔、週轉、band、minimum trade、cooldown 與成本限制；Teacher target 與同日 Advice 都不會餵回 state。

必須檢查 union 的 `dataset_id=research_shadow_challenger_all_fields`、causal overlay 與 training manifest 的 `dataset_id=research_shadow_causal_allocation_ledger`，且三者都維持 `research_only=true`、`formal_oos_allowed=false`、`production_alpha_bp=0`、`promotion_eligible=false`、`formal_consumer_compatible=false`。專用 trainer 沒有 alpha、Promotion 或 Formal OOS 的命令列開關；訓練 manifest schema 為 `allocation-research-training-manifest-v1`，正式 release loader 會直接拒絕。

缺值不能補成 0。某欄位若在決策時尚未 `first_seen`、已 stale、品質被阻擋或沒有 PIT provenance，樣本會保留 `value_int=null`、`observed=false` 及 data-quality mask。這代表欄位種類已進入研究訓練契約，不代表其歷史數值已被合法回補。

2026-07-30 的 final research dataset 為 22,093 rows、150 features／8 packs、4 folds。官方事件 overlay 只納入可證明 publication time 且 `result_only=false` 的停復牌／交易限制資料；`corporate_microstructure` 有 44,186／88,372 個 feature values observed、coverage 5,000 bp。Causal ledger 有 2,533 個決策日，其中 2,493 日為非現金 state，累積 792 次 add、754 次 reduce；它只讀 T-1 價格 prefix 與前一日 state，不讀同日 Advice，也不把 Teacher target 餵回下一日。

Final A/B 兩次獨立訓練完成 1,137,664 筆 base OOF 與 12,984 筆 meta OOF；model hash 均為 `sha256:dd512d6d32d853db151e971e816d514cd81c6b1cbf143289fc719ae41009a705`，audit hash 均為 `sha256:8a95519bd0f20b2cfabe119f0b91d3a160262f9f02b307ab13d114f370b6eefa`，training manifest file hash 均為 `sha256:ae511983a486317bd8c412934f280ed09e6df0aa3278e9d8ab1183d5d8337d19`，replay hash 均為 `sha256:b7dce1751da79b2269228f6c16b93615a309b3b6b4d173087de3e08392b9764a`。Family weights 是 `corporate=123`、`data_quality=2,893`、`flow_chip=123`、`fundamental=0`、`market_sector=2,118`、`price_technical=1,771`、`rule_portfolio_health=2,972`、`valuation=0 bp`，合計 10,000 bp；整個 dataset 沒有 observed 值的 family 固定為 0。Canonical research artifact 是 `ml_research_shadow_challenger_causal_official_events_a`，B 只作 deterministic 證據；兩者都不能供 Formal orchestrator 或非零 alpha 使用。

## ML revalidation 與推論安全

```powershell
.\.venv\Scripts\python.exe scripts\build_ml_revalidation_runbook.py `
  --run-id release-v4-prod `
  --trigger production_promotion `
  --dataset-id frozen-v4-dataset `
  --owner release_owner `
  --output runbook_prod.json
```

Runbook、dataset/model/policy hash、calibration、PSI、OOF lane comparison、bootstrap、coverage、drawdown/CVaR、turnover、shadow days 與 rollback 缺一不可。歷史回放只可作 development/OOS portfolio replay，不能替代 freeze 後 Formal OOS 或 20 個真實 elapsed trading days。

訓練器 artifact schema 為 `allocation-model-artifact-v2`。每個 feature pack／5、10、20、60 日／Ridge-Logistic 或 HGB expert 會輸出 9 個 head（benchmark／產業超額報酬、downside、MAE、MFE、realized volatility、max drawdown、tail loss、fill feasibility）、1 個 benchmark rank 與 9 個逐 head missing masks；Meta Allocator 的每個 expert input 因此固定為 19 維。缺 PIT-safe label 的 head 必須帶 missing reason/mask，不得補成已觀測的 0。

Full-market OOC 訓練會以 deterministic causal row sample 估計 median，並以完整 train stream 計算 mean／variance；final-meta 的寬 memmap 以 bounded batch 開關讀寫，避免 working set 超過 4 GiB gate。這只改變記憶體配置與可續接性，不放寬 fold cutoff、OOF custody、future-prefix 或 promotion gate。

Direct numeric store 的 heartbeat 會在每個來源 shard 驗證至少每 100,000 筆 raw row，或連續 30 秒沒有進度事件時，發布 `raw_spool_source_shard_<year>_rows_<n>_processed`；完成 shard 後再發布 `raw_spool_source_shard_<year>_complete`、`year_raw_spool_complete` 與 `year_labels_complete`。進入年度 assembly 後，會以相同的列數／時間節奏發布 `assembly_decision_<date>_rows_<n>_processed`，接著是 `year_assembly_complete`、`year_artifacts_complete` 與 `year_directory_finalized`；`processed` 狀態只表示已讀取驗證或組裝的進度，不是完成或 checkpoint，所有狀態都不能取代年度 manifest 或 hash-bound `latest_manifest.json`。因此長時間重建可由受控 continuation 自動判斷目前真實階段，無須人工猜測或手動標記進度。

Windows 若由 venv launcher 啟動另一個 Python worker，heartbeat 的 PID 可能與 supervisor 保存的 launcher PID 不同。OOC continuation 只接受完全相同的 PID，或仍存活且位於該 launcher 子孫鏈中的 worker PID；無法證明 parent-chain 的 heartbeat 會被忽略，不會因此放寬完成、hash 或 custody gate。

目前 canonical official-event post-policy training 已涵蓋 11 symbols、22,093 rows 與 4 個 expanding folds，產生 426,624 筆 base OOF predictions、12,984 筆 meta OOF predictions。這代表訓練／OOF／Meta 流水線已實際執行，不代表 Formal OOS promotion 通過。正式 compact model artifact hash 為 `sha256:92668aa574967990fa560aef8a48e595296eb22f3fef2a4264cff08210d78b6d`，replay hash 為 `sha256:ba0eb2456569d55d5981d97b612f109818c4acc01881e07ca9d1d6bf2042092d`。

目前 Formal calibration ECE／Brier、PSI、成本後 alpha OOS lane comparison、bootstrap、promotion coverage、MDD／CVaR、turnover 與 20 個真實 shadow trading days 均為 **`NOT EVALUATED`**。Engineering 4-fold training 與測試通過不等於模型績效已通過；在正式 promotion evidence 齊備前，正確狀態是 `formal_oos_allowed=false`、有效 alpha 0。

### 非零 alpha 的可信 custody

每日正式鏈不接受人工作業環境變數提供 promotion artifact path：

1. 05:17 `baldr-ml-promotion-evidence-daily` 從固定 full-market OOC、雙 replay、Shadow 與 metrics custody 建立 unsigned evidence；缺件時只寫 blocked status，不發布 compatible pointer。
2. 05:18 `baldr-ml-promotion-authority-daily` 只讀固定 evidence pointer，以 Windows user-scope DPAPI 保護的 issuer secret 驗證 machine Gate；只有 evaluator 已證明最小非零 lane 合格時才簽發 authorization。
3. 05:20 `baldr-ml-allocation-copilot-daily` 只讀 `OUTPUT_ROOT/release_v4/ml_promotion_authority/latest_authorization_pointer.json`，並再次核對 authorization 的 model／dataset 與本次真正推論 release 完全相同。

若正式 OOC store 尚未達 full-market readiness，Evidence 與 replay status 的 blocker 會保留可機器解析的 `formal_ooc_dataset_full_market_not_ready:<readiness_check,...>`；例如 `pit_sector_membership_present` 或 `causal_non_cash_portfolio_ledger_present`。Direct numeric v4 的官方 halt/resume timeline 會在每 row 保存 `officially_tradable`／`officially_blocked`，as-of 不可證明時維持 `unknown_*` 並阻擋 replay。Evidence 會驗證 official market-event pointer、manifest 與 canonical event file；若只是相同 `canonical_events_hash` 的 wrapper／duplicate metadata 重發布則視為 no-op，若 canonical hash 改變才輸出 `formal_ooc_corporate_action_custody_stale:<field,...>` 並不消費舊資料。排程會在下一輪自動重試；在這些資料具備完整 PIT custody 前，不得以重訓、研究 shadow 或目前公司快照取代，compatible pointer 不會更新，alpha 維持 0。

舊版 CLI 的 promotion artifact path 參數僅為相容 parser 形狀，在正式 orchestration 中會被忽略，排程 wrapper 也不傳入。issuer key 不得寫入 repo、文件、command line、status 或 log。Verifier 會檢查 issuer HMAC、custody root/id、registry revision、decision validity/freeze time，並重新計算 evidence、model、dataset、OOF、shadow 與 registry 實體檔 SHA-256；驗證不通過即 alpha 0。顯式部署 trust 設定只能替換或縮小可信邊界，不能注入 artifact、繞過固定 pointer 或直接授權 alpha。不得手改 `formal_oos_allowed`，也不得把 authorization JSON 本身當成已驗證能力。

### ML promotion evidence automatic catch-up

快速資料更新在長時間工作開始前會先寫入 `status=running`、`run_id`、`process_id` 與 `started_at`；完成後才寫入 terminal status 及 `completed_at`。下游 freshness／evidence 只接受完成且未過期的 `passed`／`passed_with_warnings`，因此不會消費半完成的更新。

05:17 的 Promotion Evidence runner 會唯讀檢查
`OUTPUT_ROOT/scheduled/data_update_quick/latest_status.json` 的
`check_overview_after`。若 `daily_data` 或 `technical_indicators` 的最晚日期尚未涵蓋
原始下一個決策日的 strict T-1，系統會依官方交易日曆向後掃描最多 31 個曆日，
自動選擇最近一個已具備 T-1 證據的決策日；若資料已完整，則維持下一個預備決策日。
這是選日同步，不是 promotion 授權：不讀未來資料、不寫正式 SQLite、不更新 compatible
pointer，正式 OOC／PIT／replay／shadow／authority 任一缺件仍維持 blocked、alpha 0。

Evidence runner 會先驗證 upstream `data_update_quick` status 為 `passed` / `passed_with_warnings`，且 `daily_data` 與 `technical_indicators` 的 latest date 不得超過當前台北日。status 遺失、failed、格式破損或出現未來日期時，runner 在選日前直接寫 `blocked`，不會猜測或使用未證明的未來決策日。

Evidence `latest_status.json` 使用 schema v3，並保存
`requested_decision_at`、`decision_selection_mode`、`decision_selection_reason`、
`decision_selection_attempts`、`latest_core_feature_date`、
`upstream_data_update_proof_state` 與 `upstream_data_update_proof_reason`，可直接稽核是否發生自動補跑和 upstream proof 是否完整。

### T-1 causal portfolio completeness

正式配置投影必須提供 `CausalPortfolioState`：`as_of_date` 嚴格早於 decision date、`AllocationWeightContract` 連同現金總和 10,000 bp、完整列出所有現有持倉 symbol，並帶可重算的 `state_hash`。每個 symbol 的 context `current_weight_bp` 與 request cash 必須和該 state 完全一致。缺 state、漏持倉、日期／hash／cash／context 不一致時，系統不猜 current=0：結果會是 `NO_NEW_POSITION`、`executable_weights=null`，但保留 target 與 diagnostics 供排錯。

> Gate 2–7 最新狀態統一在 `docs/06_qa/GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md` 查看；weekly machine Gate 已為 `4/3 complete`，其餘項目由 append-only machine evidence／policy revision 更新，不再使用 blanket human acceptance。禁止覆寫歷史或把工程完成解讀成模型績效通過。

> Daily / Weekly / Monthly / Maturity / Failure 的完整操作契約見 [V3.3 Engineering Closeout](../06_qa/V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)。`verify_artifact_lineage.py` 只做唯讀工程驗證，fixture 不得冒充 forward/paper/live evidence。

> 下方日期標示為 2026-07-13 或更早的 Gate 數字是歷史操作紀錄；若與本頁頂部 V4.0 區塊衝突，以 V4.0 區塊及 External Validation Register 最新 append-only revision 為準。

## V3 pruning review package（唯讀提案）

執行 `scripts\build_v3_pruning_package.py --input <metrics.json> --output <package.json>`，可把已成熟的 effectiveness metrics 轉成 `retain`、`restrict`、`downweight`、`retire` 或 `defer` 審查提案。樣本不足、必要指標缺失或人工驗證未完成時必定 `defer`。所有 proposal 固定 `apply_action=false`、`review_required=true`，package 固定 `auto_trading=false`；不得用此輸出直接修改推薦權重、threshold、production scheduler 或交易狀態。

> **最後更新**：2026-07-13
> **適用版本**：目前主要 PySide6 UI，入口為 `ui_qt/main.py`。
> **範圍**：本手冊涵蓋目前左側主導覽的 8 個主工作區與跨工作區流程。開發中或 Roadmap 規劃功能不會描述成已可用。

## 2026-07-13 系統工程整合判讀

這次整合必須拆成六個狀態判讀，不可用單一「完成」取代：

1. `engineering_integration=verified`：A～F committed handoff、跨流 contract、唯讀 smoke 與 pure verifier 已通過工程驗證。
2. `historical_ml_shadow=continue_shadow`：只顯示 dataset／model／prediction identity 與 shadow diagnostics；`formal_oos_allowed=false`，不參與 ranking、Score、Advice、Portfolio 或 Exit。
3. `dashboard_visibility=verified`：Daily Decision Desk 唯一實例位於「市場探索 > 市場總覽」；Workbench「決策來源」只做導覽。
4. `forward_evidence=pending`：唯讀 replay 或 working-copy rehearsal 不等於真實週期 evidence。
5. `source_acceptance=pending`：source／license 尚未逐項 accepted；official monthly／quarterly row count 為 0、corporate-action coverage unknown 時，必須顯示缺口，不得解讀為業務數值為零。
6. `production_automation=pending`：scheduler、auto promotion、broker action 均未啟用；ML production blend alpha 固定為 0，且目前沒有通過 real frozen artifact smoke。

### 市場總覽與資料可見性

1. 從左側進入「市場探索 > 市場總覽」。這是唯一 Decision Desk instance；從 Workbench 進入只會導向同一畫面。
2. 檢查月營收、三大法人、信用交易、TDCC 與券商分點等來源卡。卡片的 status、row count、available date 與 warning 是資料可見性，不是推薦分數。
3. `row_count=0`、MISSING、DEGRADED 或 coverage unknown 都代表來源缺漏／受限；不可補成中性值，也不可當作「指標為零」。
4. 更新時保留 loading；若較早查詢晚於新查詢返回，stale-result guard 會忽略舊結果。錯誤只降級該來源並保留 warning，不改 action、focus 或 Score。
5. 券商查詢採背景載入；week／month 與股票明細應在畫面恢復互動後判讀，勿以 loading 中的暫態內容做結論。

### Evidence 模式與 ML shadow

- `projection_only` 只投影與驗證輸入，不建立 working copy。
- `working_copy_e2e` 只允許明確指定、位於 `DATA_ROOT` 之外的 working-copy DB 與輸出目錄；正式來源必須唯讀，完成後應比對正式 DB hash／mtime 未改變。
- `degraded` 是成功保留缺口的安全結果，不是正式 closeout。缺 market、Advice、paper、health、outcome、weekly、signal、ML adapter 或 lineage parent 時不得升級狀態。
- ML shadow 畫面只供研究診斷。看到 `continue_shadow`、prediction 或 challenger metadata，不代表 formal OOS、promotion、production alpha 或投資有效性。

排錯時先看來源卡與 warnings：缺來源／row count 0 回到對應 source acceptance；working-copy 路徑落在正式資料根目錄時改用外部暫存路徑；frozen artifact 不存在或驗證被擋時維持 alpha 0，禁止用 fixture 冒充真實 artifact。

### Terra Development Dataset V0（開發者／研究操作）

這是 CLI-only、development-only 的資料集生成工具，不會出現在主 UI，也不會改變 Score、Recommendation、Advice、Portfolio、Exit 或 scheduler。2025 已永久標記為 `seen_oos`，只可作 development；它不再是 formal OOS。2026 成熟 outcomes 只供離線 evaluation，永不進 fit。

1. 將 `--development-output-root` 指向 `DATA_ROOT` 外部的資料夾，例如 `C:\Temp\technical_analysis_development_output`；工具拒絕正式資料根與正式 SQLite 檔。
2. 指定尚未使用的 `--generation-id`。同 ID 的第二次執行會停止，不覆寫既有 artifact。
3. 只允許四類 core source：daily price、technical indicators、market indices、industry indices。fundamental／broker 不會讀取，也不會補成 0。
4. 每筆 feature 只用前一交易日（T-1）資訊，且可得日不晚於 decision date；universe 使用最少 252 日的 `conservative_observed_history`，並將 listing／delisting metadata 缺口列入 diagnostics。
5. corporate-action coverage 在 V0 未提供時，輸出仍可供研究，但必定顯示 `research_only_degraded`；不得把它解讀成 clean dataset 或 formal OOS。
6. 讀取 `generations/<generation-id>/manifest.json`：確認 `fit_row_count` 只對應 2025、`evaluation_row_count` 只對應 2026、`formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`formal_rule_only_path_unchanged=true` 及 `zero_formal_write=true`。

7. 執行 `scripts/run_terra_development_research.py` 時，`--manifest` 與 `--dataset` 必須來自同一 generation directory；工具會在 fit 前重算 row counts 與 semantic content hash。`--output-root` 必須在 `DATA_ROOT` 外且尚不存在，report／projection 會成對 atomic publish。
8. 若要在 UI 查看，將 `RESEARCH_CONSOLE_PROJECTION` 指向該 run 的 `ResearchConsoleProjection.json` 後啟動 UI；畫面只呈現 frozen DTO，不重算 Rule／ML 或讀取正式 DB。

若 CLI 回報 source schema、output root、T-1、日期範圍或 generation already exists 錯誤，停止操作；不要改動正式 DB、不要覆寫 artifact，也不要以 2025 結果調參後重新宣稱 formal OOS。

Corporate-action availability history 是 Terra V0.1 前置的 staging-only 輔助工具，不是正式資料 apply。執行 `scripts/build_corporate_action_availability_history.py` 時，必須提供 `--evidence-json`、`--coverage-json`、`--as-of-date` 與明確的 `--output-root`；CLI 會先驗證 `--as-of-date`，日期無效時不讀取任何 evidence／coverage JSON。兩個 JSON 根都必須是 object rows 的 list，否則分別以 `corporate_action_evidence_rows_invalid` 或 `corporate_action_coverage_rows_invalid` 停止，且不建立輸出。JSON 語法／編碼不合法時回報 `corporate_action_<label>_json_invalid`，檔案不存在或無法讀取時回報 `corporate_action_<label>_read_failed`，`--as-of-date` 不是有效 ISO 日期時回報 `corporate_action_as_of_date_invalid`；三者都在建立 output root 前 fail closed。`--output-root` 應使用 `DATA_ROOT` 外的 TEMP／development 路徑；若環境已設定 `DATA_ROOT`，CLI 會拒絕該 root 與其子路徑。三個 canonical output 任一已存在時會以 `corporate_action_output_exists` 停止，不覆寫既有 bytes；新輸出先寫入同 root 的唯一 staging directory，完成後才逐檔發布並清理 staging。這降低半套輸出風險，但不代表三檔具單一 filesystem transaction，也不構成 corporate-action coverage 已接受、Formal evidence 或 forward credit。

### 富邦行情 PIT-Safe Shadow Decision Pipeline CLI（開發者／研究操作）

這是 CLI-only、shadow-only 的 Fubon 行情決策評估工具，不會影響正式 Rule-only 決策結果，也不會取得 Formal Evidence Credit。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_fubon_shadow_decision.py `
  --authorization <path-to-authorization-json> `
  --input <path-to-fubon-observation-json> `
  --universe <path-to-universe-json> `
  --strategy-config <path-to-strategy-config-json> `
  --decision-timestamp "2026-07-26T00:00:00+00:00" `
  --output-root $env:TEMP\technical_analysis_fubon_shadow `
  --candidate-db $env:TEMP\technical_analysis_fubon_shadow\fubon_candidates.sqlite
```

- `--authorization` 可省略並載入預設 shadow 授權；`--input`、`--universe`、`--strategy-config` 與 `--decision-timestamp` 必須明確提供。
- `--output-root` 可省略為只輸出 stdout；`--candidate-db` 可將驗證後資料寫入獨立 development SQLite。兩者均拒絕正式資料根、正式 DB 與 repository 內路徑。
- 嚴格驗證 `available_at <= decision_timestamp`；缺少可得時間不會猜測，hash 不符或 identity 衝突會隔離。
- `formal_decision_influence_allowed=false`、`formal_evidence_credit_authorized=false`、`production_blend_alpha_bp=0` 固定不可覆寫。
- 在建立明確的 Fubon 欄位到既有規則輸入映射前，Score、Recommendation、Portfolio、Exit 一律回傳 typed `not_computable`，不得以未改變的 baseline 假裝已完成 shadow 計算。

### MOPS 每日研究用財報發布 Freshness、Outage 與 Revision 診斷 CLI（開發者／人工研究操作）

這是人工可執行的 MOPS EZSearch 季報公告發布時間（F26–F29）每日 Freshness、Outage、與 Revision/Correction 診斷工具。僅供研究與 shadow 投影，不會寫入正式 SQLite 或 FA_Data，也不取得 Formal Evidence Credit。

```powershell
.\.venv\Scripts\python.exe scripts\fetch_mops_daily_research_freshness.py `
  --start-date 2026-07-27 `
  --end-date 2026-07-28 `
  --output-root C:\Temp\technical_analysis_development_output\mops-daily-freshness `
  --prior-artifact C:\Temp\technical_analysis_development_output\mops-daily-freshness\runs\<prior-run-id>.json `
  --prior-artifact-sha256 <prior-artifact-64-hex-sha256> `
  --live --confirm-live-readonly
```

- **離線與連線模式**：預設可用 `--fixture-file` 做離線測試與診斷比對；若要連線 MOPS 官方 HTTPS 介面，必須明確帶入 `--live --confirm-live-readonly` 旗標。兩種模式互斥，單獨提供 confirm flag、同時提供 live 與 fixture，或 `timeout <= 0` 都會拒絕執行。提供 `--prior-artifact` 時必須同時提供該檔案真實 bytes 的 `--prior-artifact-sha256`；hash 不符即 fail closed。
- **查詢邊界**：僅允許 MOPS 官方 HTTPS 介面、僅查詢 F26–F29、單次查詢窗口上限 31 天、單一查詢回傳滿 1000 筆觸發 1000-row cap 失敗封閉；M31 永久排除。
- **輸出路徑**：`--output-root` 嚴格通過 `validate_development_output_root` 檢查，拒絕 `DATA_ROOT`、正式 DB、repo 根目錄、路徑穿越與 symlink escape。
- **Immutable Run Artifacts 與 Atomic Projection**：
  - 每次執行之 raw/research diagnostic 會以不可變且包含 SHA-256 Hash 的檔名寫入 `<output_root>/runs/<run_id>.json`。
  - 最新 sanitized 投影會以 atomic write 寫入 `<output_root>/latest_sanitized_projection.json`。
- **Freshness / Outage / Revision 狀態判讀**：
  - `observed`：16 個不重複的 market × item key 完整成功、每筆 `source_status=success`、response SHA-256 合法、Schema 與 Row Conservation 無誤；不能以重複 key 補足遺漏 key。
  - `observed_empty`：16 組 query 完整成功，但當期事件數為 0（此非 Outage）。
  - `capture_failed`：網路/HTTP/JSON/格式錯誤，會寫入 append-only failure diagnostic artifact 並以 non-zero (exit 1) 結束，不偽造空成功或 mapping。
  - `baseline_missing`：未提供 prior artifact 時無法宣稱多日證據。
  - `stale`：當指定 `--expected-through` 且查詢 end_date 早於 expected-through 時標示。
  - `multi_day_evidence_ready=true`：prior 與 current 必須是同一 query window、兩者 query matrix 完整，且實際 capture 發生在不同的台北曆日；同日重跑永遠不能換算成多日證據。
- **Research Console 唯讀投影**：在啟動 UI 或 Research Console 時以 `RESEARCH_CONSOLE_PROJECTION` 設定顯式投影路徑（如 `latest_sanitized_projection.json`），即可唯讀呈現 diagnostics。`capture_failed`、`stale`、matrix incomplete、baseline missing 與不可比較 window 都會成為 blocker，使整體狀態 degraded；未知 MOPS projection schema、治理欄位不一致、artifact hash 不合法或含 raw／credential-like forbidden keys 時 fail closed。安全邊界旗標 `formal_oos_allowed=false`、`formal_credit_authorized=false`、`production_blend_alpha_bp=0`、`fubon_shadow_usable=true`、`fubon_formal_credit_allowed=false` 固定保留。

### P0-13 機器稽核工具 CLI（GEMINI-P0-13-MACHINE-AUDIT-AND-BLOCKER-REDUCTION-V1）

這是 CLI-only 的唯讀 P0-13 機器稽核工具，對全部 13 項 P0 候選資料源執行高效率、可重跑的機器驗證，將 machine-verified、degraded 與缺 artifact／probe 的狀態分開呈現，並產出極簡 Owner Decision Packet 與 audit JSON：

```powershell
.\.venv\Scripts\python.exe scripts\run_p0_candidate_audit.py `
  --decision-date "2026-07-25" `
  --output $env:TEMP\technical_analysis_p0_audit\p0_audit_results.json
```

- `--decision-date` 必須明確提供 ISO 日期。
- 輸出 JSON 包含 13 項 P0 來源完整驗證矩陣與 `machine_verified_sources`、`degraded_sources`、`unavailable_sources` 統計。缺官方公告時間、probe 未回傳或 MOPS artifact 未提供時會保留 blocker；不得因 owner 問題存在而將它們計為已解除。
- 自動寫入 audit packet 至 `%TEMP%\technical_analysis_gemini_handoffs\GEMINI-P0-13-MACHINE-AUDIT-AND-BLOCKER-REDUCTION-V1.json`；其 `status=audit_generated_not_validation_handoff`，不宣稱已完成 Git、型別或完整 pytest 驗證。真正交接必須在獨立驗證後補齊終態。
- 嚴格守護 `downstream_eligibility=none`、`human_decision=requires_human_acceptance`、`production_scheduler_allowed=false` 與 `formal_oos_allowed=false`；絕不寫入正式 DB 或影響推薦與交易決策。
- Windows 主控台若仍使用 CP1252，CLI 會先將 stdout／stderr 切到 UTF-8；因此直接執行 `--help` 也能顯示完整繁中說明，不會因編碼錯誤中止。

### P0-13 官方證據與就緒度強化 CLI（GEMINI-P0-13-OFFICIAL-EVIDENCE-AND-READINESS-HARDENING-V1）

這是 CLI-only 的唯讀 P0-13 官方證據與就緒度 (Readiness) 稽核工具，對全部 13 項 P0 候選資料源執行非破壞性、可重跑的機器驗證，產出「Machine Evidence Matrix」與「5 大群組化 Owner 決策包」：

```powershell
# 預設非連線模式（不發網路請求；未提供 artifact 的來源維持未探測／缺件）
.\.venv\Scripts\python.exe scripts\run_p0_source_evidence_audit.py `
  --decision-date "2026-07-26" `
  --output $env:TEMP\technical_analysis_p0_audit\p0_evidence_hardening.json

# Live 探測模式（必須同時帶入 --live 與 --confirm-live-readonly）
.\.venv\Scripts\python.exe scripts\run_p0_source_evidence_audit.py `
  --decision-date "2026-08-27" `
  --live --confirm-live-readonly `
  --mops-quarterly-artifact <MOPS_STATEMENT_AVAILABILITY.json> `
  --output $env:TEMP\technical_analysis_p0_audit\p0_evidence_hardening_live.json
```

- `--decision-date` 必須明確提供 ISO 日期。
- 預設模式不發起任何網路請求；Live 探測模式未提供 `--confirm-live-readonly` 時會立即拒絕執行。
- `--output` 輸出路徑目前嚴格受限於 OS TEMP；尚未定義受治理的 candidate-safe 根目錄，因此也拒絕寫入 repository、正式 DB 或正式 Evidence DB。
- 稽核會同時附上 `p0-source-acquisition-routes.v1`：固定 13 個 P0 source denominator 與目前 27 條受治理候選 route，每個來源至少有 2 條 route。route registry 只說明可取得路徑與 provenance，不會因存在 alternate route 而自動授予 source acceptance。
- 現行 live probe 已接上五條 fallback：TWSE 三大法人／信用交易 → TPEx OpenAPI、TDCC legacy CSV → TDCC OpenAPI `1-5`、TWSE 月營收 OpenAPI → MOPS `t187ap05_L.csv`、TPEx 月營收 OpenAPI → MOPS `t187ap05_O.csv`。輸出會保存實際 route、前一路徑失敗原因與 fallback lineage；官方明確無事件會標示 `official_no_data`，不再與 schema mismatch／network failure 混為同一個 `unavailable`。
- 13 項 P0 來源自動收斂為 5 大群組化 Owner 決策（除權息/減資分割、交易限制 Preflight、三大法人/信用交易、TDCC 集保持股、月營收/季報 Artifact），僅要求 Owner 判斷內部研究意圖/條款接受度，完全無需審視逐列 raw data。
- `twse_microstructure` 群組另提供五個 source 的逐項 machine recommendation；目前全部固定為 `deferred`，且 `ready_for_owner_review=false`。這只是可重算的機器建議，不是 owner/reviewer 決議，也不會寫入 source acceptance registry。
- Timestamp semantics 會分開投影官方公告 timestamp／date-only、有效期間、交易日觀測、decision-time observation、first-observed、capture time 與 HTTP headers。HTTP `Date`／`Last-Modified`、capture time 與 first-observed 均不得升格或回填為官方公告時間。
- `microstructure.full_delivery` 與 `microstructure.limit_lock` 的現有官方 probe 只證明交易日狀態／行情觀測；limit-lock 已改讀符合 daily limit／quote schema 的 TWSE `TWT84U`，不再用 `MI_INDEX`。若 `TWT84U` 有正常行情列但鎖死事件為 0，輸出仍保留 `probe_outcome=observed` 與完整 raw／blocked conservation，語意是「官方 payload 可讀、當日沒有符合鎖死條件的 event」，不是 endpoint 或 parser 失敗；`official_no_data` 則保留給 endpoint 明確回傳 no-data status。limit-lock 本來就不是公告來源，因此 blocker 是 `decision_time_availability_not_proven`，不是 `official_publication_timestamp_missing`。停復牌、處置與分盤目前仍缺可引用的 row-level 官方公告時間。
- MOPS numeric PIT candidate 的 artifact identity 固定為 `mops.statement.publication`；validator 只透過版本化 `p0-candidate-source-alignment.v1` 將 normalized row 對齊 P0 contract `pit.quarterly_financials`，並保留 `artifact_source_id`。未知 candidate source ID 會 fail closed。這只是 identity mapping，不會套用 source acceptance、降低 coverage 門檻或改變 `downstream_eligibility=none`。
- `--mops-quarterly-artifact` 除了接受原始 `mops.statement.publication` wrapper，也接受 `scripts/validate_mops_quarterly_artifact.py` 輸出的 normalized JSON row list。normalized 入口會逐列重驗 P0 source identity、consolidated／uncorrected、hash、revision、publication→available date 順序與 numeric lineage；缺欄、錯 source 或不合法 hash 會 fail closed。它只是重用已驗證的 candidate evidence，不會把 normalized rows 當成新的官方抓取、也不會授予 license／owner acceptance／Formal credit。
- 富邦只可作相符 microstructure source 的 shadow corroboration；輸出會分開顯示 `fubon_shadow_usable` 與固定 `fubon_formal_credit_allowed=false`、`production_blend_alpha_bp=0`，不得用富邦補造 TWSE 官方公告時間。
- 產出稽核草稿 handoff JSON 至 `%TEMP%\technical_analysis_gemini_handoffs\GEMINI-P0-13-OFFICIAL-EVIDENCE-AND-READINESS-HARDENING-V1.json`；其 `status=audit_generated_not_validation_handoff`，不宣稱 pytest、mypy 或 Git 終態已通過。
- 嚴格守護 `downstream_eligibility=none`、`human_decision=requires_human_acceptance`、`production_scheduler_allowed=false` 與 `formal_oos_allowed=false`；所有 formal clock zeros 維持 0。

### P0 官方條款／授權候選證據擷取（只讀、候選）

`scripts/capture_p0_license_evidence.py` 用來把「可取得的官方條款／OpenAPI 頁面」變成可交給 Owner／Reviewer 的候選證據，不會把 URL 存在 route registry 就當成已授權。它只從 `p0_source_acquisition_routes.py` 的 allowlist 取出 3 個唯一 URL（TWSE、TPEx、TDCC），保存 response status、HTTP header 摘要、內容 SHA-256 與有限關鍵詞 flags；不保存頁面全文，也不寫正式資料庫、source acceptance registry、Score、Advice、Portfolio 或排程。

```powershell
# 預覽：不發網路請求，只列出預計擷取的 3 個官方條款／OpenAPI URL
.\.venv\Scripts\python.exe scripts\capture_p0_license_evidence.py `
  --decision-date "2026-08-28" `
  --output $env:TEMP\technical_analysis_p0_license_evidence\preview.json

# 受控候選擷取：只有精確 token 才會做 bounded GET；仍不代表 license accepted
.\.venv\Scripts\python.exe scripts\capture_p0_license_evidence.py `
  --decision-date "2026-08-28" `
  --confirm capture-p0-license-evidence `
  --timeout-seconds 15 `
  --max-bytes 65536 `
  --output $env:TEMP\technical_analysis_p0_license_evidence\capture.json
```

- `--output` 必須位於 OS TEMP；工具拒絕 repository、`DATA_ROOT` 與正式 SQLite 路徑。
- 預覽的 `capture_executed=false`、`confirmation_required=true`，不呼叫網路。確認後每個 URL 仍有 bytes／timeout 上限，失敗會保留 typed error，其他 URL 繼續診斷。
- `license_accepted=false`、`source_acceptance_granted=false`、`downstream_eligibility=none` 固定不變。Owner／Reviewer 必須另外提供具名決議、使用範圍、quality／PIT／coverage、rate limit 與 rollback；本 artifact 不能單獨解除 `legal_and_license_acceptance_required`。

若要把已保存的 audit 交給 Owner／License reviewer，可用下列唯讀 renderer；它只整理既有 13-source machine evidence 與 5 組 owner question，不重新抓資料、不寫 registry，也不會推導 `accepted`／`limited`：

```powershell
.\.venv\Scripts\python.exe scripts\render_p0_owner_decision_packet.py `
  --input $env:TEMP\technical_analysis_p0_audit\p0_evidence_hardening_live.json `
  --output $env:TEMP\technical_analysis_p0_audit\p0_owner_decision_packet.md
```

輸入必須是既有 `p0-source-evidence-audit.v1` artifact；輸出路徑不得位於正式 `DATA_ROOT`。packet 會在每個群組列出 actual／candidate route、fallback 是否嘗試、probe／availability、PIT／timestamp、raw／accepted／blocked 計數與 license URL 線索；這些仍是 machine evidence，不是授權或 acceptance。人工欄位（具名 Owner／reviewer、license／quality／PIT evidence、用途與 rollback）仍須由實際權責人填寫，完成前下游資格固定為 `none`。

### Gate 3 P0 Data Source Control Center（唯讀）

`scripts/inspect_p0_source_control_center.py` 將 13 個 authoritative P0 source contract、候選／官方證據稽核與選擇性人工 decision revision 收斂成同一份可稽核 read model。它不建立 decision registry、不寫正式 SQLite、不執行網路抓取，也不會因 row count 或 machine status 足夠而自動接受來源：

```powershell
# 沒有稽核 artifact 時仍輸出完整 13 列，明示 contract-only 與待補證據
.\.venv\Scripts\python.exe scripts\inspect_p0_source_control_center.py `
  --format markdown `
  --output $env:TEMP\technical_analysis_p0_audit\p0_source_control_center.md

# 讀取既有候選稽核（只讀）
.\.venv\Scripts\python.exe scripts\inspect_p0_source_control_center.py `
  --audit-json $env:TEMP\technical_analysis_p0_audit\p0_audit_results.json `
  --format json
```

- `p0-candidate-audit.v1` 與 `p0-source-evidence-audit.v1` 都會驗證完整 13 項 source denominator 與安全旗標；缺列、重複、未知 source 或 boundary 不符會 fail-closed。
- 每列分開顯示 `governance_status`、`machine_status`、`audit_status`、`decision_status`、row 數、blockers、owner actions 與 evidence requirements；`contract_only` 只表示尚未注入 audit，不是資料可用，`research_shadow` 也不是 formal accepted。
- 2026-08-28 host-context 實測例子：未載入 audit 時會看到 13 列 `contract_only`；載入完整 live audit 後同一組來源成為 `0 contract_only / 12 blocked_provenance / 1 research_shadow`，machine=`1 verified / 12 degraded / 0 missing`；12/13 路徑實際 observed，13 個 payload hash 均存在。這個變化只修正「是否已有機器證據」的顯示；13 筆具名 decision 仍為 `not_supplied`，`accepted=0`、`limited=0`、`downstream_eligibility=none`。
- 總覽固定顯示 `accepted/limited`、`downstream_eligible` 與安全邊界。即使輸入 decision revision 是 `limited`／`accepted`，本控制中心仍強制 `downstream_eligibility=none`、`formal_oos_allowed=false`、`production_scheduler_allowed=false`、`auto_accept_allowed=false`；要變成 accepted feature 必須另有完整、具名 owner/reviewer 與授權／品質／PIT 證據流程。
- 總覽統計不是可任意覆寫的摘要：DTO 建構時會從 13 筆明細重新計算並驗證 governance／machine／decision counts 與各狀態 totals，任何不一致或試圖打開 safety boundary 的輸入都會 fail-closed。
- Workbench → Evidence → Research Console 會自動顯示同一份 P0 Control Center；頁面沒有 Accept／Apply／Promote／Retrain／Trade 控制。若沒有稽核投影，畫面仍保留 13 列並列出 `candidate_audit_not_supplied`、`source_acceptance_decision_missing` 與 `downstream_eligibility_none`。
- 若要讓主 UI 顯示某份既有稽核 artifact，可在啟動前設定 `P0_SOURCE_CONTROL_CENTER_AUDIT=<絕對路徑>`；程式只讀取該明確路徑，不會掃描 `output`、QA 或正式資料目錄。artifact schema 不合法或邊界不符時，整個 Research Console 會 fail-closed 為 degraded。
- 若要讓主 UI 同步顯示具名 owner decision，可設定 `P0_SOURCE_CONTROL_CENTER_DECISIONS=<絕對路徑>`。輸入可以是 canonical `source-acceptance-decision-revision.v1` 的單筆／清單，也可以是外部 `source-acceptance-owner-review-decision.v1`；後者只允許 `deferred`／`rejected`／`disabled` 正規化，`accepted`／`limited` 會 fail-closed，絕不從外部 attestation 或 evidence URL 推導授權。這個入口只接受 13 個 canonical P0 source ID；`fubon.marketdata` 是獨立的 research shadow provider，必須用 Fubon dossier／shadow inspector，不能硬映射進 P0 denominator。UI 只做 read-only projection，不會因載入 decision 而建立 registry 或改變 `downstream_eligibility=none`。
- 若要讓主 UI 同步顯示條款候選證據，可設定 `P0_SOURCE_CONTROL_CENTER_LICENSE_EVIDENCE=<絕對路徑>` 指向 `p0-license-evidence-capture.v1`。Data Update 與 Research Console 會在每列 license 欄顯示 `captured_candidate`、`capture_partial`、`preview_not_captured` 或 `capture_transport_error` 等狀態，並保留 URL／hash／限制提示數；`capture_partial` 表示同一來源的多個官方條款 URL 只有部分取得，仍須逐一複核，絕不代表授權通過。artifact schema、allowlist 或安全旗標不符時整體 fail-closed。這只改善「條款是否已觀測」的可見性，`license_status=requires_review`、`license_accepted=false` 與 `downstream_eligibility=none` 不會改變。
- Data Update → 全部資料也會在執行「檢查數據狀態」時載入上述兩個明確路徑，顯示 13 列 `P0 官方來源證據` 表格。欄位包含實際 route、可用 route 清單、fallback 來源／原因、PIT／公告與 availability、**解析通過率（accepted／observed）與 accepted／observed／blocked rows**、license、owner decision 與下游資格；這個比例只表示已觀測 payload 的 parser row-conservation，不代表官方市場 universe 或日期完整覆蓋率，沒有獨立分母時不可解讀成「來源 100% 完整」。表格是 candidate／shadow 的治理觀測，不是更新按鈕，也不會寫入 SQLite。未設定 artifact 會顯示 `contract_only`，路徑遺失或 schema／boundary 錯誤會顯示 `audit_unavailable` 與讀取原因，避免沿用上一輪或假綠。
- P0 audit 的 route registry 只是候選取得目錄；`acquisition_route_probe_summary` 會另外顯示每條 route 是否真的 `observed`、`failed`、官方無資料、日期不符、解析／接受列缺漏或 `not_attempted`，並保留 selected／fallback lineage。未嘗試的 alternate route 不會被誤標成可用來源；此資訊只供候選 evidence 與 Owner review，不改 source acceptance、PIT 或 production ingestion。
- Data Update → 排程狀態頁的初始預覽會讀取明確的 `data_freshness/latest_status.json` 路徑，並以中文狀態、原始 token、檢查時間、日價／技術指標最新日與 warnings／errors 摘要呈現；它只代表這一個 freshness 工作，不是整體 Scheduler。按「檢查此資料源狀態」後才會讀取明確 `scheduled/*/latest_status.json` 並彙整核心／受控／需處理／不可用工作。每日資料更新 task 的註冊／執行不等於 Evidence／ML 生產寫入授權；`production_scheduler_allowed=false` 固定保留，頁面不提供手動觸發或 Task Scheduler 修改。
- 更新時間軸的步驟／歷史表格與 freshness／TPEX 摘要會同時顯示中文狀態與原始 machine token（例如 `完成（passed）`）；原始 token 仍保留供排錯，不代表任何正式治理或交易授權。
- 更新時間軸的 freshness 摘要會另外顯示 artifact 內的日價／技術指標最新日、對應 quick-run 的檢查／預期日，以及 TWSE／TPEx 最新日檔是否存在；這些欄位只來自明確 freshness artifact 的 allowlist，未提供或格式不符時顯示未知／缺漏，不會由狀態 token 推導。
- 當 freshness artifact 已提供上述觀測時，時間軸也會與 quick-run 目標資料日比對；日期不一致、quick status 不是成功狀態或原始日檔缺漏，整體狀態會顯示 `freshness 異常（degraded）` 並列出診斷。舊版 artifact 沒有 optional checks 時不會被自動回填或推導。
- 時間軸也會翻譯 `in_progress`、`schema_mismatch`、`blocked_provenance` 等排程／治理 token；未知 token 仍原文顯示，避免把未辨識狀態誤當成功。
- Portfolio → Paper Portfolio 的 readiness／weekly 摘要也會以中文說明包住原始狀態（例如 `成本帳：尚不可計算（成本帳缺漏）（not_computable_cost_ledger_missing）`）；這只是可讀性改善，缺少真實 fills 時仍不會計算成本後週報。

### P0 Source Intake Validator（唯讀候選輸入）

`scripts/inspect_p0_intake_readiness.py` 是把外部 P0 治理資料交給程式檢查的第一個接入口。它只接受明確的 `p0-source-intake.v1` JSON，要求完整 13 個 `source-acceptance-dossier.v1`，逐列驗證欄位型別、source denominator、license／PIT／quality checklist 與安全旗標；不會建立 decision registry、不會寫正式資料，也不會自動接受來源。

若已經有 `p0-source-evidence-audit.v1`，不必人工抄寫每個 machine row。可用下列唯讀轉接器建立一份 candidate intake；每列 dossier 只帶入 audit 的 raw／accepted／quarantine／blocked 計數、payload hash 與 machine status，另外在 intake envelope 的 `machine_evidence_by_source` 保留 allowlist 內的實際 route、fallback lineage、schema／probe outcome、timestamp semantics 與 acquisition route 清單。若 audit 內的 MOPS verified-artifact 分支已通過 validator，這些 row counts 會如實保留到 dossier，不會把有效 artifact 變成 `0/0`；所有 source owner、license、publication、available-date、PIT、revision 與 reviewer 欄位仍標成 `unverified`／`requires_review`，所以結果一定維持 `deferred`：

```powershell
.\.venv\Scripts\python.exe scripts\build_p0_intake_from_audit.py `
  --audit $env:TEMP\technical_analysis_p0_audit\p0_evidence_20260828_live_tpex_fallback_v2.json `
  --output $env:TEMP\technical_analysis_p0_audit\p0_candidate_intake_from_audit_20260828.json

.\.venv\Scripts\python.exe scripts\inspect_p0_intake_readiness.py `
  --input $env:TEMP\technical_analysis_p0_audit\p0_candidate_intake_from_audit_20260828.json `
  --format markdown `
  --output $env:TEMP\technical_analysis_p0_audit\p0_candidate_intake_readiness_20260828.md
```

`build_p0_intake_from_audit.py --help` 與阻擋診斷會先將 stdout／stderr 設為 UTF-8；在 Windows CP1252 主控台也應維持可讀並以 exit code 表示成功或阻擋。這只改善 CLI 可觀測性，不改候選資料或任何 acceptance gate。

此轉接器的輸出只允許位於 OS TEMP，且明確保留 `auto_accept_allowed=false`、
`downstream_eligibility=none`；它可以縮短 owner review 的資料整理工作，但不能
替代官方 publication／PIT／license 證據或具名決議。`machine_evidence_by_source`
只是一份安全投影，不屬於 `source-acceptance-dossier.v1` 的治理欄位，也不會被
intake validator 解讀成 acceptance authority。

```powershell
# 先產生 13 列候選範本；路徑必須明確且位於 DATA_ROOT 之外
.\.venv\Scripts\python.exe scripts\inspect_p0_intake_readiness.py `
  --template-output $env:TEMP\technical_analysis_p0_audit\p0_source_intake_template.json

# 填入 owner／license／PIT／quality 證據後，產生 JSON 或 Markdown 診斷
.\.venv\Scripts\python.exe scripts\inspect_p0_intake_readiness.py `
  --input $env:TEMP\technical_analysis_p0_audit\p0_source_intake.json `
  --format markdown `
  --output $env:TEMP\technical_analysis_p0_audit\p0_source_intake_report.md
```

- `status=deferred`：13 列格式正確，但仍有 checklist 或 authority blocker；可繼續補件。
- `status=ready_for_owner_review`：13 列 checklist 均完成，只代表可以交給具名 owner／reviewer 審查，`decision_preview` 仍固定為 `deferred`、`allowed_use_cases=[]`、`downstream_eligibility=none`。
- `status=invalid_input`：缺列、重複、未知 source、欄位型別／schema／secret-like 欄位或不安全旗標；CLI 以 exit code `2` fail-closed。格式有效但 deferred 時 exit code 為 `0`，因為「稽核完成」不等於「Gate 通過」。
- 範本與報告的寫入都是明確指定的候選 artifact；程式拒絕寫入 `DATA_ROOT`，不會掃描或覆寫既有正式 output。完成 intake validator 後，仍須透過既有的 source acceptance review／append-only decision 流程，不能直接把報告餵給 `ScoringEngine`、Advice、scheduler 或 broker。

### P0 Source Acceptance Decision CLI（預覽／明確確認）

`scripts/append_source_acceptance_decision.py` 將 intake 後的 owner／reviewer 決議接到既有 `SourceAcceptanceDecisionRegistry`。預設永遠是 preview，不開啟 registry；只有操作者同時提供 `--registry` 與 `--confirm-append` 才會建立／append SQLite。`accepted`／`limited` 必須提供 intake artifact，且三類 evidence id 必須能回溯到該 dossier；`deferred`／`rejected`／`disabled` 仍可先保存為非套用決議。

```powershell
# 預覽；不會建立 registry.sqlite
.\.venv\Scripts\python.exe scripts\append_source_acceptance_decision.py `
  --decision $env:TEMP\technical_analysis_p0_audit\decision.json `
  --intake $env:TEMP\technical_analysis_p0_audit\p0_source_intake.json `
  --format markdown

# 明確確認後才 append；registry 必須位於 DATA_ROOT 之外
.\.venv\Scripts\python.exe scripts\append_source_acceptance_decision.py `
  --decision $env:TEMP\technical_analysis_p0_audit\decision.json `
  --intake $env:TEMP\technical_analysis_p0_audit\p0_source_intake.json `
  --registry $env:TEMP\technical_analysis_p0_audit\source_acceptance.sqlite `
  --confirm-append `
  --format json
```

- append 是 append-only 且具 idempotency；相同 revision 第二次執行會顯示 `already_present`，不覆寫歷史列。registry 寫入成功不代表 downstream eligibility、formal OOS、scheduler 或 broker 開啟；控制中心仍固定揭露 `downstream_eligibility=none`。
- `accepted`／`limited` 若缺 intake、dossier 尚未 `ready_for_owner_review`、evidence id 未綁定、decision schema 不符或 registry 位於 `DATA_ROOT`，CLI 會以 exit code `2` fail-closed；preview／append 報告都會保留 decision content hash 與 dossier hash 供稽核。
- 外部 owner-review decision 若仍是 `deferred`／`rejected`／`disabled`，CLI 也可直接 preview（或在明確 `--confirm-append` 下保存為非套用 revision）；它的 `active_blockers` 只會成為 registry blockers，不會被當成 license／quality／PIT evidence。外部 owner-review 的 `accepted`／`limited` 必須改用 canonical revision 並重新通過 intake／evidence binding。

## 1. 系統能做什麼

目前系統提供：

1. 更新每日股價、大盤、產業、券商分點與技術指標。
2. 用市場 Regime、強弱個股、強弱產業與 Smart Money 觀察市場。
3. 用 Profile 或進階參數產生推薦候選，查看 Why、Why Not 與分數拆解。
4. 建立觀察清單（候選池）與可重用選股清單。
5. 執行單股、批次、固定組合、推薦回放與策略研究。
6. 保存研究結果、比較既有結果，並在符合 Registry 與 Month 6 lifecycle Gate 時升級策略版本。
7. 記錄交易、持倉、覆盤日誌、停損停利、籌碼監控與生命週期回顧。
8. 唯讀觀察 Runtime 狀態、治理健康與事件流。

目前不能保證：

- 推薦股票一定上漲或策略一定獲利。
- quantile 一定優於 fixed；2026-06-14 的 10 檔 OOS 實證未顯示 quantile 優於 fixed，因此仍為 opt-in。
- 推薦回放等同可成交的實盤績效；V1.2 新增的 rolling risk、microstructure preflight 與 relative attribution 只是可信度診斷，不會把 replay 變成實盤撮合。
- Forward Evidence / Forward Performance 的 close-to-close forward return 等同實盤可執行績效，或能證明任一訊號有效。
- Daily Decision Desk 是主 UI「市場探索 > 市場總覽」的唯一實例；「決策工作台 > 決策來源」只保留導覽入口，不再嵌入第二份畫面。市場總覽保留 answer-first dashboard：先顯示今日主結論、研究模式註記、優先 / 風險產業與股票焦點，再保留各模組細節；股票焦點可下鑽至「市場探索 > 主力流向」。Market Breadth v1 已由 SQLite `daily_prices` 接線，Sector Rotation v1 已由 SQLite `industry_indices` 接線，Watchlist Trigger v1 已由 `WatchlistService` 與 SQLite `technical_indicators` 接線，Portfolio Alert v1 已由 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService` 接線，Relative Strength / Liquidity Ranking v1 已由 SQLite `daily_prices` 接線，Why Not / 風險提示 v1 已由 `DecisionDeskRiskPromptService` 對接，並可呈現 fundamental diagnostics 來源的基本面風險提示。缺口會以 MISSING / DEGRADED / ESTIMATED 顯示，並保留 warnings。
- Runtime Observatory 會自動修復問題或自動下單。
- 觀察清單等同實際投資組合。

## 2. 安裝與啟動

### 2.1 建立環境

在專案根目錄執行：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

若專案已經有可用的 `.venv`，不需要重新建立。

### 2.2 資料位置

預設正式資料根目錄：

```text
D:/Min/Python/Project/FA_Data
```

可在啟動前覆蓋：

```powershell
$env:DATA_ROOT = "D:\your\data\root"
$env:OUTPUT_ROOT = "D:\your\data\root\output"
```

SQLite 主資料庫位於：

```text
<DATA_ROOT>/sqlite/twstock.db
```

### 2.3 啟動主程式

推薦：

```powershell
.\.venv\Scripts\python.exe ui_qt\main.py
```

若目前 shell 已啟用正確虛擬環境：

```powershell
python ui_qt/main.py
```

`ui_app/main.py` 是 Legacy Tkinter UI，不是目前主要入口。

### 2.4 第一次啟動檢查

1. 左側主導覽預設停在「決策工作台」；若是第一次啟動或要先檢查資料，切到「數據更新」。
2. 點擊「檢查數據狀態」。
3. 確認每日股價、大盤、產業、券商分點與技術指標有日期與筆數。
4. 若顯示待更新，依需求執行快速或安全更新。
5. 完成後回到「決策工作台」查看今日待判讀；需要研究時再進入「市場探索」、推薦與回測。

### 2.5 介面呈現一致性

主 PySide6 UI 採用金融研究工作台風格：深色背景、緊湊表格、狀態色、清楚的主要 / 危險 / 次要按鈕，以及無資料時的空狀態提示。這些設計 token、表格樣式與缺字 icon 清理只影響畫面呈現與操作可讀性，不改變資料抓取、SQLite 同步、推薦、回測、每日決策 snapshot、持倉計算或任何 service / domain 運算語意。

### 2.6 左側主導覽與決策工作台

主視窗目前使用左側主導覽切換 8 個主工作區，預設第一屏為「決策工作台」：

1. 決策工作台
2. 市場探索
3. 推薦分析
4. 策略回測
5. 觀察清單
6. 持倉管理
7. 數據更新
8. Runtime

左側主導覽每個主工作區都有自製線條 SVG icon，協助快速辨識工作區意義；可用導覽列頂部的收合按鈕切換為 icon-only 模式以釋放橫向空間，也可以在目前已選取的主工作區按鈕上再點一次直接收合 / 展開。收合後仍可用 tooltip 辨識完整工作區名稱，並且只影響畫面空間，不改變任何資料載入、排程、報告或 service 行為。

主視窗會只以目前可見的工作區決定最小尺寸，避免隱藏的圖表或設定頁把整個 App 撐大。當視窗寬度不大於 1120 px，左側導覽會自動收成 icon-only；若這次是系統自動收合，視窗回到 1240 px 以上時才會自動展開。使用者手動收合的選擇不會被這個規則覆寫。

「每日決策」不再是頂層主工作區；唯一畫面位於「市場探索 > 市場總覽」。決策工作台內部子頁仍包含「總覽」、「決策來源」、「Evidence」、「持倉追蹤」與「操作節奏」，其中「決策來源」只提供「開啟市場總覽」導覽，不持有 Decision Desk widget，也不啟動第二次背景刷新。今日待判讀佇列清空時會顯示空狀態，提示可前往「市場探索」研究。這只代表目前 DTO payload 沒有待判讀項目，不代表 Phase gate 已完成，也不是買賣建議。

「總覽」現在先顯示「今日行動中心」：四張卡依序整理資料狀態、市場判讀、Advice／候選與持倉覆盤；上方唯一主要按鈕會依既有 DTO 選出下一個應檢查的工作區。它只會切換至數據更新、市場總覽、推薦分析或持倉管理，不會更新資料、執行策略、產生或套用 Advice、寫入持倉或交易。資料待確認時先看數據更新；有持倉 Action Item 時先看持倉管理；再依待判讀與 Advice DTO 狀態導向市場總覽或推薦分析。

行動中心下方保留四個指揮台摘要 block：今日待判讀、人工待處理、等待真實時間、Warnings。等待真實時間 block 會明確顯示 weekly history 與 multi-day dry-run 比例，讓使用者掃描重點後再往下看表格。「Evidence」子頁已替換為唯讀 Research Console；「持倉追蹤」與「操作節奏」仍是摘要與下鑽入口。Research Console 的可見性不代表 formal evidence、source acceptance 或 promotion 已完成。

Workbench 仍只透過 `WorkbenchSourceService` / `WorkbenchDashboardDTO` 讀取既有資料；不寫 DB、不啟用 production scheduler、不執行 replay、不補 lifecycle gate、不產生買賣建議。Phase 0 weekly history 的目前 live 值以 `inspect_pre_v2_readiness.py` 為準：本機未設定 projection 時，正式 DB legacy history 為 `0/3 waiting_for_time`；若載入具名 owner 的 approved projection，UI 只展示 projection 累積（目前外部 projection 為 `3/3`），不授予 formal credit。歷史 working-copy 的 Week 1 `1/3` 僅供追溯；multi-day dry-run record 已為 `3/3 ready`，但 Week 2 / Week 3 與真實 manual review / action-item rhythm 仍需正式資料與真實時間累積，不能因 UI 重排、replay summary、fixture 或人工改表而標示為完成。

## Gate 1 Advice：決策工作台的唯讀操作

在「決策工作台」收到 Advice DTO 時，先看 mode、`decision_date`、`data_as_of_date`、資料品質與 warnings，再閱讀 action、Why / Why Not / Risk、source trace，以及持倉的 target/current/gap。這是可追溯的研究與人工決策輔助，不是委託、報酬保證或自動交易。

1. Guided Mode 僅顯示 promoted、參數鎖定且 disclosure 完整的策略結果；candidate / shadow 會 fail-closed。
2. Professional Mode 可以查看 candidate 研究結果，但不能把它與 formal Advice 混為同一決策依據。
3. `NO_NEW_POSITION`、`RESEARCH`、`AVOID` 是安全結果。看到這些結果時，先檢查拒絕原因（策略狀態、資料品質、可成交性、風險預算、現金或持倉限制），不要手動補值或繞過限制。
4. 平衡風險檔為最低現金 `2000 bp`、最多 8 檔、單檔上限 `1500 bp`；權重使用整數 bp，金額使用 `Decimal`。UI 只能顯示結果，不能修改 policy。
5. Advice 的 decision / data-as-of date 與 source trace 必須存在；資料截止日不得晚於決策日。缺資料、降級或未來資料會被拒絕或降級，不能當作可交易結論。

Advice 表格有三種空白狀態，不能只用「沒有列」判斷：`WAITING_FOR_ADVICE_DTO` 代表尚未載入 Advice DTO，應先依畫面導引檢查資料更新或推薦分析；`NO_ELIGIBLE_ADVICE` 代表 DTO 已成功載入但沒有符合條件的建議；`ADVICE_DTO_ERROR` 才代表 DTO 遺失、結構不完整或安全診斷拒絕。來源顯示 degraded / warning 但仍帶有有效 recommendations 時，表格應照常呈現，並把警告保留在摘要與警告區；不得把它誤判成 DTO 錯誤。

Advice 不寫 DB、不啟用 scheduler、不建立 broker order、不改 Scoring / ranking / backtest，也不套用 lifecycle action。weekly review history 的 working-copy 保存與真實時間累積屬 Gate 2；人工覆盤完成後只能以 `build_evidence_operations_weekly_review.py --save-history` 對隔離 working-copy DB 保存，再以 `--list-history` 核對，不得直接編輯 history、使用 production DB 或以 replay / fixture 補週數。它不因 Gate 1 完成而自動通過。

## 3. 每日建議流程

### 快速研究流程

1. 數據更新：先檢查資料狀態，必要時執行快速更新。
2. 市場探索：檢測 Regime，查看強弱與主力流向。
3. 推薦分析：選 Profile，執行推薦並閱讀 Why / Why Not。
4. 加入觀察清單：保存要研究的股票。
5. Research Lab：使用單股或批次回測驗證。
6. 保存結果；只有符合 Gate 的結果才升級策略版本。
7. 需要追蹤交易時記錄到持倉管理，後續寫覆盤日誌。

### 完整備份流程

定期或資料修復後使用「安全更新（完整 CSV + SQLite）」，保留 CSV 歷史備份與 SQLite 同步。

備份檔集中在 `DATA_ROOT/meta_data/backup/`，同一來源同一天只保留最新一份，最多保留最新 5 個日期版本；migration / backfill / registry / 大型 merge 入口也採同一 retention 規則。既有大型備份來源與清理候選見 [BACKUP_RETENTION_AUDIT_2026_07_06.md](../03_data/BACKUP_RETENTION_AUDIT_2026_07_06.md)，清理前必須先由使用者確認。

## 4. 數據更新

### 4.1 全部資料看板

窄視窗（小於 720px）會將左側資料來源導覽移到內容上方，核心狀態卡改為雙欄、候選資料卡改為單欄、快速／安全／狀態檢查按鈕改為直列；整個更新頁可垂直捲動。這只是畫面排版，更新日期、worker、SQLite 同步與 fail-closed 規則不變。

狀態卡片包括：

- 每日股票數據
- 大盤指數數據
- 產業指數數據
- 券商分點數據
- 技術指標數據
- 月營收資料

月營收卡片會以「最新可用日」顯示該期全部資料的 `available_date`，並在附加列顯示 `fundamental_monthly_revenues` 的「已匯入期別」；這兩者不能視為每日交易資料的「最新日期」。若同一期仍有部分公司尚未到可得日，該期仍列為待生效；卡片會顯示待生效期別數與完整可用起始日。這是 point-in-time 可見性保護，不代表更新失敗。

若 `OUTPUT_ROOT/monthly_revenue_mops_snapshots` 中存在比 SQLite 已匯入期別更新的受控命名 snapshot，卡片會改顯示「候選可用」，並列出「候選待套用期別」與抓取日。即使候選與已匯入期別相同，也會顯示「候選快照期別」與抓取日，避免重抓或修訂候選在畫面上消失。這只代表已取得新的數值候選，不代表公告日 availability mapping 或 SQLite 已完成；仍須先跑 availability validator 與 backfill dry-run，再由人工確認是否正式套用。snapshot 選擇依檔名的資料期別／抓取日，不依檔案大小，UpdateView 與兩個 availability builder 共用同一規則，避免歷史大檔遮蔽最新候選。

若 snapshot 尚未放入正式 `OUTPUT_ROOT`，可設定 `MONTHLY_REVENUE_SNAPSHOT_CANDIDATE=<絕對路徑>` 讓狀態檢查唯讀投影該明確候選；這不會掃描 TEMP、不會自動替換正式 snapshot，也不會改變更新頁的正式 backfill 欄位。路徑不存在或檔名不符合受控規則時，卡片會保留「缺漏／候選無效」與診斷，不會悄悄退回另一份 snapshot。

若已有由 `build_monthly_revenue_availability_history.py` 或受控 PIT 匯入產生的公告日／可得日候選 CSV，可設定 `MONTHLY_REVENUE_AVAILABILITY_CANDIDATE=<絕對路徑>`。資料更新狀態檢查只會讀取這個明確檔案，先執行 validator，再對正式 mapping 做唯讀 merge preview；卡片會列出候選期別、筆數、可用日、可併入／已併入／衝突／無效狀態，以及新增與衝突筆數。候選期別無法解析時也會保留狀態與最多兩筆 validator 診斷，避免檔案遺失或格式錯誤被誤看成「沒有候選」。`ready_for_merge` 仍只是候選可併入，不會自動寫入正式 mapping 或 SQLite；正式套用仍須另行執行 availability merge 與月營收 backfill 的確認流程。未設定此變數時不會掃描 TEMP 或其他相鄰目錄，也不會把 snapshot 候選誤當成公告日證據。

狀態意義：

| 狀態 | 意義 |
|---|---|
| 正常 | 本地資料接近最新交易日且可讀。 |
| 待更新 | 資料庫可讀，但日期落後。 |
| 異常 | SQLite 或必要資料讀取失敗。 |
| 未檢查 | 本次啟動尚未執行狀態檢查。 |

當市場指數、產業指數、券商分點或技術指標標為「待更新」且服務回傳
`freshness_status=lagging` 時，卡片與來源詳情會額外顯示「新鮮度基準日」及「資料最新日」。
這兩個日期用來直接判讀落後幅度；它們不是新的資料來源，也不會自動觸發下載或寫入。

狀態燈只依明確的 `status` token 判定：`ok`／`success`／`current`／`normal` 才是綠色「最新」；`error`、`missing`、`empty`、`unavailable` 或狀態查詢失敗會顯示紅色「異常」，不會因說明文字出現「最新」就視為正常。inline 摘要會把 `success`／`current`／`normal` 統一顯示為中文「正常」。若回傳 payload 缺少某一資料源，該卡片與對應 inline 摘要都會重設為「尚未檢查」，不沿用上一輪的日期、筆數或 0 筆判讀。

尚未按下檢查按鈕時，卡片內的提示文字不會被當成 `status` 欄位；燈號會維持灰色「未檢查」，不會誤顯示黃色「待更新」。

全部資料頁的卡片下方另有「資料更新時間軸（唯讀）」：按「檢查數據狀態」後會讀取固定的 `OUTPUT_ROOT/scheduled/data_update_quick/latest_status.json`、`OUTPUT_ROOT/scheduled/data_update_quick/history.jsonl`、`OUTPUT_ROOT/scheduled/data_freshness/latest_status.json` 與 `DATA_ROOT/meta_data/tpex_full_refresh_status.json`，顯示最後成功完成時間、run、目標資料日、每個更新步驟、最近執行歷史、freshness 結果與診斷。時間軸狀態 `最新`、`部分可用`、`freshness 異常`、`已過期`、`執行中`、`失敗`、`缺漏`、`格式異常`、`未設定` 的判讀彼此不同；history 缺檔時，若 latest status 仍存在，UI 會明示「新版 runner 尚未產生；不回填舊 latest」，`empty` 會明示等待下一次真實排程，`invalid` 會明示需修復 JSONL。缺檔或讀取失敗會清掉本輪步驟列與歷史列，不沿用上一輪成功結果。這個投影只讀檔，不掃描其他 `latest_status`、不發網路、不寫資料庫，也不把檔案修改時間當成成功完成時間。

時間軸旁另有「本次手動更新」摘要，專門記錄目前 UI 觸發的快速／安全／單一來源更新：執行中會顯示進度與資料區間，完成、失敗、錯誤或合作式取消會保留本輪訊息、失敗步驟、成功／失敗日期數與警告。它與排程時間軸分開，不會把上一輪排程成功結果當成本輪手動更新成功，也不會把手動結果回填成排程 history；若要確認實際 SQLite／CSV 狀態，仍應在工作完成後按「檢查數據狀態」。

手動更新若以失敗或背景例外結束，畫面在顯示本輪錯誤後會再做一次唯讀狀態檢查；因此即使前面已安全提交部分 CSV／SQLite，也會把實際最新日期與筆數刷新出來。這個重查不會重跑下載、合併或寫入，也不會把部分成功改標成完整成功。

「全部資料」頁另有「整體程式 readiness（唯讀）」區塊。若要在 UI 同時查看 P0、Evidence、
Paper Portfolio、Formal／ML、Runtime、效能／容量與更新歷史七個 lane，請在啟動前設定：

```powershell
$env:PROGRAM_READINESS_ARTIFACT = "C:\path\to\program_readiness.json"
```

按「檢查數據狀態」後，區塊會顯示整體狀態、每個已投影 lane 的狀態、阻擋原因、下一步與
是否需要外部輸入；原始 machine token 會保留在表格中。此路徑必須是明確的
`program-readiness.v1` JSON 檔，UI 不會自動搜尋或選擇 TEMP／正式目錄中的其他 artifact。
未設定、遺失、超過大小上限或 schema 不符時會顯示「未設定／缺漏／格式異常」診斷；這個區塊
永遠是 query-only，不會寫入 SQLite、發網路、啟用 scheduler／broker、解除 source acceptance
或取得 Formal credit。

要讓效能 lane 同時顯示「證據已整理」與「仍待 owner 決策」，產生 readiness 報告時可加上
`--performance-owner-packet <PERFORMANCE_OWNER_PACKET_JSON>`。該檔必須是由
`scripts\build_performance_canary_owner_packet.py` 產生、位於 OS TEMP 的
`performance-canary-owner-review.v1`；inspector 只投影 packet status、review lane 數與待處理
數，不讀取任意 nested payload。UI 的效能摘要會顯示 owner packet 狀態與 `待處理／總 lane`，
但 `needs_named_owner_reviewer`／`ready_for_owner_review` 都不是 production canary 授權，
仍須另外完成 technical backup／rollback、容量與 broker review。

同一頁的「P0 官方來源證據（候選／唯讀）」表格固定顯示 13 個來源及其治理／machine 狀態、實際 route、PIT／公告、coverage、license 與 owner／下游邊界。Fallback 欄位會區分：`是` 代表替代路徑真的被採用；`否（已嘗試但未採用）` 代表曾 probe 但因 `date_mismatch`、`official_no_data`、`network_error` 或其他 fail-closed 結果沒有採用；`否`／`未提供` 則表示沒有可觀測的 fallback 嘗試。日期不符會同時列出要求日與觀測日，傳輸／解析錯誤會在滑鼠提示中保留 error type、endpoint、HTTP／payload evidence；summary 另顯示 fallback 已嘗試、已採用與未採用計數。這些欄位只改善診斷，不授予 source acceptance，`downstream_eligibility` 永遠為 `none`。

表格最右側的「Probe 路徑狀態」會逐條顯示候選 route 的實際 probe 結果，例如 `已觀測（observed）`、`失敗（failed）`、`官方無資料（official_no_data）`、`日期不符（date_mismatch）` 或 `未嘗試（not_attempted）`，並以「已選」與 `fallback` 標記 lineage。摘要會列出已嘗試／總路徑及各狀態計數；若舊 artifact 沒有這個欄位，畫面保留「未提供」，不會把 route registry 當成網路成功證據。這仍是候選、唯讀診斷，不會解除 license／owner／PIT gate。

P0 表格的長欄位採固定上限欄寬、儲存格換行與水平捲動；完整原文仍保留在每格滑鼠提示中。這樣在一般視窗寬度下可以先讀到狀態與 blocker，不會因 endpoint、hash 或 license URL 把整頁撐寬；縮小視窗時請使用表格底部水平捲軸查看其餘欄位。

由「產生 P0 candidate intake／Owner packet」工具輸出的 machine evidence 也會保留 route probe status；packet 內 route label 會附上 `observed`／`failed`／`not_attempted` 與 selected／fallback 標記。這只方便 Owner 逐路徑複核，不會把 route registry 或單次 probe 自動轉成 accepted／limited。

若要讓 UI 使用最新 route status，請把明確產生的 audit 檔設定到 `P0_SOURCE_CONTROL_CENTER_AUDIT`（例如 `C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_evidence_20260828_route_status_refresh.json`）後重新開啟或重新載入更新頁；UI 不會自行掃描 TEMP。這份 refresh 若未同時指定 MOPS 季報 artifact，季報列顯示 `artifact_missing` 是預期的 fail-closed 結果，不代表其他 12 個來源的 probe 失敗。

快速更新排程會在 `latest_status.json` 旁以 append-only 方式保存 `data-update-status-history.v1` JSONL；每次真實執行會記錄 `running` 與 terminal status 的 run／時間／步驟摘要。預設 history 路徑為 `OUTPUT_ROOT/scheduled/data_update_quick/history.jsonl`，也可用 runner 的 `--history-path` 或 UI 的 `DATA_UPDATE_HISTORY_ARTIFACT` 指定。這個功能不會回放既有 latest status、不會把檔案 mtime 當成完成時間；既有環境的 history 缺檔會顯示「缺漏」，等下一次真實排程自然產生，不得手動複製舊結果補足。

若 history 缺檔，先用下列唯讀命令確認 Windows task 是否真的存在：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_scheduled_task_registration.py `
  --output C:\Users\archi\AppData\Local\Temp\scheduled_task_status.json
```

輸出會列出 13 個預期 task 的 available／missing 計數、安全摘要，以及本地 wrapper
manifest 是否存在、每個 task action 是否指向預期 `.cmd`；若 task 可用但 `Task To Run`
未出現，會另標示 action 尚未觀測，不能算 `configuration_ready`。它不會註冊或修改 task；若要
指定其他 checkout，可加 `--repo-root <path>`。也可把該 JSON 以 unified readiness 的
`--scheduled-task-status` 載入，讓 Update History lane 顯示
`scheduled_tasks_missing_or_unavailable:<available>/<total>`、wrapper 缺漏或 action mismatch。
若 task 缺失，需由 owner 在正確帳號下執行受控的
`scripts\scheduled\register_baldr_scheduled_tasks.cmd`，再觀察下一次真實 running／terminal
history；不可用舊 latest status 回填。
此 inspector 在解析參數前會設定 UTF-8 stdout／stderr，因此 Windows CP1252 主控台也能
正常使用 `--help` 與輸出繁中診斷；這只改善診斷工具顯示，不會改變 query-only 與不註冊 task
的安全邊界。

### 4.1.1 整體程式 readiness 盤點（唯讀）

若要一次確認目前各 Gate「在哪裡、卡在哪裡、下一步是什麼」，使用：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_program_readiness.py `
  --data-root <DATA_ROOT> `
  --output-root <OUTPUT_ROOT> `
  --training-as-of 2026-08-28T00:00:00+08:00 `
  --format markdown
```

需要載入已存在的證據時，再加上 `--p0-audit-json`、`--p0-license-evidence-json`、
`--approved-weekly-history-projection`、`--technical-performance-baseline` 與
`--broker-performance-baseline`。若要把 Direct/OOC 維護的容量結果一起納入
performance lane，另加 `--ml-direct-chain-status <ML_DIRECT_CHAIN_STATUS_JSON>`；
當 status 是 `blocked_insufficient_storage` 時，報告會保留
`direct_chain_storage_preflight_blocked`，只提示容量／保留策略，不啟動 worker。
若已建立效能 owner handoff，另加
`--performance-owner-packet <PERFORMANCE_OWNER_PACKET_JSON>`；報告與 UI 會顯示
`needs_named_owner_reviewer`／`ready_for_owner_review`、review lane 總數與待處理數，
但只作交接投影，不授予 production worker／fetch pool、Formal OOS 或清理權限。
若已有允許實際 host context 產生的 `runtime-environment-readiness.v1` 唯讀 artifact，
可再加 `--runtime-readiness-json <RUNTIME_READINESS_JSON>`；它只載入已核實的 Runtime
read model，不重新探測或修改正式 logger／Registry 路徑。schema 不符會 fail-closed，且
這仍不等同正式 Registry transaction／rollback proof。若要在不寫正式 Registry 的前提下
驗證目前正式 DB 的 schema 與 transaction 契約，可再加
`--runtime-registry-snapshot-probe <REGISTRY_SNAPSHOT_PROBE_JSON>`；它只載入由
`scripts\inspect_research_registry_transaction.py` 產生的 read-only source → TEMP clone
證據，不能把 clone proof 當成正式 ACL 寫入成功。
程式會固定顯示 P0、Evidence、Paper、Formal/ML、
Runtime、Update history、Performance 七個 lane 以及依序下一步；未提供的 artifact
會顯示 `waiting_for_external_input` 或 `action_required`，不會自行搜尋、回放、補歷史
或改接 prospective path。若要把獨立的 `data_freshness/latest_status.json` 一起投影，
可明確加入 `--freshness-status-path <FRESHNESS_STATUS_JSON>`；報告會分開列出
freshness status、`checked_at`、warnings／errors 與 read-only 標誌，不會用 freshness
結果掩蓋排程未註冊或 history 尚未累積。`update_history` 另外檢查 history JSONL
是否超過 8 MiB、是否有重複 record、terminal run，以及 latest status 與 history
最新 run 是否一致。

每個 lane 的「下一步」欄也會顯示 bounded 進度摘要，讓「已有機器證據」與「尚未通過治理／執行 gate」分開閱讀：P0 會顯示來源數、機器證據比例、`accepted／limited` 與 route 嘗試數；Evidence 會顯示 weekly／dry-run `已觀測／要求`、sidecar 中待人工審核的 `pending_human_review` 期數與 Formal credit 是否授權；Paper 會顯示 snapshot、benchmark、cost ledger 狀態、成本紀錄與 fills，避免只看到 `0` 卻不知道是 ledger 缺漏；Formal／ML 會顯示 owner-controlled input `ready／total`；Runtime、效能與更新歷史則顯示 host probe、canary／容量、排程與 freshness 摘要。阻擋原因會先顯示中文意義，括號保留原始 machine token，方便直接對照 log／artifact；這些只是 UI read model，不會改變任何 gate。

此命令是 query-only readiness projection：不建立資料夾、不寫正式 SQLite、不發網路、
不啟用 scheduler／broker；輸出 `partial` 也不代表 Formal credit、source acceptance、
Paper 成本後週報或平行 worker 已完成。若要保存報告，才另以 `--output <REPORT_PATH>`
指定明確的報告檔案。

若要在受控環境改用另一個已核准的 artifact，可設定 `DATA_UPDATE_STATUS_ARTIFACT`、`DATA_UPDATE_HISTORY_ARTIFACT`、`DATA_FRESHNESS_STATUS_ARTIFACT`、`TPEX_REFRESH_STATUS_ARTIFACT`、`MONTHLY_REVENUE_SNAPSHOT_CANDIDATE` 或 `MONTHLY_REVENUE_AVAILABILITY_CANDIDATE`；每個變數都必須是完整檔案路徑。未設定時使用上述固定出口，找不到時畫面會明示「缺漏／未設定」，不會自行搜尋相鄰目錄。

每日股價、大盤指數、產業指數、券商分點、技術指標、月營收，以及法人／信用／集保三個候選資料源分頁，都會在「檢查此資料源狀態」下方顯示同一份唯讀來源摘要；全域檢查完成後也會同步刷新這九份摘要。個別來源查詢失敗時只會將該來源標為異常，不會把其他來源卡片誤刷成錯誤。候選來源摘要仍屬 research-only，不代表正式評分或交易訊號。

若狀態卡顯示黃色「待更新」且文字含 `讀取模式：immutable_fallback`，代表 Windows 當下無法取得一般 SQLite read lock，系統使用最後已提交的 immutable 唯讀快照；這不是資料已確認最新，請先停止其他 SQLite 寫入工作，再按「檢查數據狀態」重查。SQLite 資料檢視頁的頁首也會顯示「immutable 唯讀快照，可能非即時」。

更新中的進度只代表目前這一輪工作；TWSE 批次下載會把子程序逐日期輸出映射到外層區間，TPEX 區間抓取也會逐日期回報，技術指標等其他子流程則映射到各自外層區間，進度不會倒退。每日資料合併會回報目前讀取的檔案與整合檔寫入批次；若增量模式沒有較新的 CSV，會明確顯示「資料已是最新」並標記為 no-op，不把它誤報成重新合併，也不會因 no-op 先建立整合檔備份；只有確認有新資料、即將原子提交時才建立備份；SQLite CSV 匯出會先以 query-only 查詢取得預估筆數，再回報已處理筆數。若來源端沒有可量化進度，畫面會保留目前階段文字，不把等待時間誤宣稱成百分比。最終「刷新資料狀態」若失敗，會停在未完成狀態，不會先顯示 100%。CSV、SQLite、合併、技術指標與匯出等寫入型背景工作同一時間只允許一個；若畫面提示「背景工作進行中」，請等待完成後再重試。唯讀的資料源狀態／詳情檢查可以在寫入期間執行。
寫入型背景工作啟動後，進度列下方會出現「取消目前工作」按鈕。按下後會送出合作式取消，TWSE 目前 API／batch 請求會先安全收尾，TPEX、券商分點與技術指標則在目前日期、檔案或 SQLite 寫入邊界停止；不會呼叫 `QThread.terminate()`，也不會截斷半筆 SQLite／CSV 寫入。畫面會顯示「已送出合作式取消」，待 worker 自然結束後恢復按鈕；已完成的部分會保留，請再按「檢查數據狀態」確認實際日期與筆數。
大型每日資料／券商分點合併與 CSV 匯出目前會先完成正在進行的安全操作，再套用取消；這段期間按鈕會保持停用並在日誌顯示等待收尾，不代表資料已回滾。這是目前仍保留的長任務限制，避免在檔案重建或 SQLite 交易中途切斷。
更新完成或未完成的訊息會同時列出 SQLite 同步狀態、來源、目標 table、寫入筆數與錯誤／取消原因；不必從日誌中的自然語言猜測 SQLite 是否真的寫入。
全域「檢查數據狀態」與 SQLite 個別來源詳情共用 daily reference freshness；市場指數、產業指數或技術指標的最晚日期落後每日股價時會標成 `lagging`／「待更新」，不會因為表內仍有舊資料就顯示「正常」。月營收則依公告 `available_date` 與期別判讀，不能拿每日交易日直接比較。

CSV 送入 SQLite 前會先在寫入用副本上正規化欄位與識別值：日期欄接受 `日期`／`date`／`Date`／`trade_date`／`decision_date`，股票代號接受 `證券代號`／`股票代號`／`stock_code`／`stock_id`／`code`／`ticker`，股票名稱接受 `證券名稱`／`股票名稱`／`stock_name`／`name`；日期轉為 `YYYYMMDD`、股票代號補足四碼。這不會改寫 raw CSV 或原始 DataFrame；缺必要欄位時仍 fail-closed 跳過並在結果／日誌保留原因。

### 4.2 快速更新與安全更新

| 模式 | 內容 | 適用情境 |
|---|---|---|
| 快速更新（跳過大型合併） | TWSE / TPEX 每日股價與券商分點會依 UI 最近範圍補齊，預設為結束日前最近 10 個工作日，並直接增量同步 SQLite；會保留已下載的日檔 CSV，但跳過 `stock_data_whole.csv` 與券商分點 `merged.csv` 的大型重寫。 | 日常盤後更新、只需要讓 SQLite 查詢與技術指標追上最新資料。 |
| 安全更新（完整 CSV + SQLite） | 依 UI 最近範圍補齊 TWSE / TPEX / 大盤 / 產業 / 券商分點，預設為結束日前最近 10 個工作日；完成後重建每日股價大表與券商分點 `merged.csv`，再同步 SQLite。 | 資料修復、備份完整性檢查、需要確認 CSV 歷史資料庫也完整時。 |

TWSE 補檔遇到平日休市（例如颱風停市）時，只有在至少一個官方查詢型別明確回覆「沒有符合條件的資料」且沒有任何成功資料時，才會標記為「官方無交易資料日」並略過。HTTP 錯誤、逾時或無法辨識的回覆仍保留為更新失敗；更新結果會保留各查詢型別的 HTTP / API 狀態與實際日期，方便後續診斷。

快速更新仍會更新必要的日檔 CSV，因為 SQLite 同步以這些日檔作為可追溯來源；速度優勢主要來自跳過大型合併檔重寫。最近 10 個工作日可涵蓋使用者約兩週才開一次程式的常見情境；若間隔更久，請改用個別資料來源日期範圍或安全更新補齊。若近期資料已存在，系統會先用 CSV / SQLite 判斷並跳過網頁抓取。

一鍵更新會先檢查更新前總覽。若任一核心資料源的狀態 payload 明確是 `error`／`failed`／`exception`，畫面會顯示「已停止寫入」並不啟動任何下載、合併或 SQLite 寫入；請先依失敗資料源的錯誤訊息排除資料庫或來源問題，再重新執行。`lagging`、`empty`、`unavailable` 是資料可用性診斷，不等同於這個前置寫入阻擋，但最後狀態刷新仍必須通過才會顯示更新完成。

### 4.3 個別資料來源

左側可選：

- 每日股價
- 大盤指數
- 產業指數
- 券商分點
- 技術指標
- 月營收
- SQLite 資料檢視

另有「三大法人」、「信用交易」、「集保股權」與「自動排程狀態」四個唯讀治理頁。

- **三大法人與信用交易**：目前屬於 Phase 3C 候選研究資料 (Candidate Data)。可使用獨立受控的歷史回補 CLI 腳本（`scripts/update_phase3c_candidates.py`），依據具官方證據的台股交易日進行斷點續跑匯入。apply 必須明確指定位於 `DATA_ROOT` 外的 Candidate DB；例如 `D:/Min/Python/Project/FA_Data_candidate/phase3c_candidate.db`。絕不寫入或覆寫正式資料庫 `twstock.db`。UI 只會讀取 `PHASE3C_CANDIDATE_DB_PATH` 指定的 Candidate DB，並顯示其筆數、最早/最新日期與 checkpoint 覆蓋率；Windows process environment 尚未刷新時，會唯讀採用同名 HKCU 使用者環境設定。兩者都未設定時仍不猜測路徑，也不將正式 DB 當成候選資料。
- UI 的 Candidate status read model 會以 SQLite URI `mode=ro` 並啟用 `PRAGMA query_only=ON` 開啟明確指定的 Candidate DB；即使目前只執行 SELECT，也不允許狀態查詢意外建立寫入連線。結果仍標示 `formal_records=0` 與「候選研究資料，不參與評分或投資決策」。
- **集保股權 (TDCC)**：目前官方 OpenData 端點 (`id=1-5`) 僅提供最新單週公開資料，不支援歷史多日期輪詢回補。加入 `--include-latest-tdcc` 時，系統只匯入 payload 自帶資料日的最新週 snapshot；例如在 2026-08-13 查詢時，官方最新資料日可仍為 2026-08-07。歷史期別仍明確標示為 `BLOCKED_NO_HISTORICAL_ENDPOINT` / `PARTIAL`，不會把執行日偽造成資料日。
- **排程狀態**：只讀取最近狀態紀錄，供人工判讀背景工作是否曾執行；它不授權啟用 production scheduler，也不代表資料已完整。按「檢查此資料源狀態」會重新彙整 `OUTPUT_ROOT/scheduled/*/latest_status.json`，顯示核心工作就緒數、正常／受控／需處理／不可用數與逐工作診斷；下方 raw JSON 也會同步刷新，不會只停留在開頁時讀到的舊檔。

每日股價、大盤、產業、券商分點操作：

1. 設定「結束日期」；可用日曆選取，或按「今日」一鍵帶入今天。
2. 設定「最近範圍」；系統換算出的開始日期會納入下載與缺漏檢查範圍。
3. 先按「檢查此資料源狀態」。
4. 按「手動下載此資料源」會依資料源下載或補齊指定日期範圍的原始資料。
5. 每日股價手動下載會同時處理 TWSE 與 TPEX：TWSE raw CSV 寫入 `DATA_ROOT/daily_price/YYYYMMDD.csv`，TPEX official daily close quotes 寫入 `DATA_ROOT/daily_price_tpex/YYYYMMDD.csv`，完成後同步 SQLite `daily_prices` 並觸發技術指標增量更新。TWSE 會先查 `MI_INDEX type=ALL`，若該 type 回傳錯誤或查無資料，會 fallback 到 `ALLBUT0999` 並以欄位辨識個股交易表。執行「合併每日股價」時，`stock_data_whole.csv` 也會同時納入這兩個日檔目錄。
6. 券商分點下載後，還要執行對應的「合併」才會寫入分析資料庫。

每日股價與券商分點按「檢查此資料源狀態」後，結果會顯示在該資料源頁面內的摘要列，包含最新日期、筆數、SQLite / CSV 狀態與缺漏提示；下方日誌只保留細節，不是唯一判讀入口。

按主頁的全域「檢查數據狀態」後，該摘要列也會同步刷新；若某個 payload 缺漏，卡片與頁面內文都會顯示「尚未檢查／異常」，不沿用上一輪數字。

每日股價的「強制重新合併所有每日股價」屬高風險維護操作。系統會先顯示二次確認對話框，按「取消」不會執行，只有按「確認強制合併」才會重建衍生合併資料；此流程不應亦不會修改或刪除 `DATA_ROOT` 底下的 raw CSV 原始檔。

若開啟「SQLite 資料檢視」時資料庫尚不存在、損毀或沒有讀取權限，頁面會保留並顯示「SQLite 不可用」；這是唯讀診斷結果，不會自動建立空的 `twstock.db`。請先確認 `TWStockConfig.db_file` 指向正確資料庫，再重新按「載入數據與結構」。

若「檢查數據狀態」顯示 SQLite `unavailable`，代表設定的 DB 尚未存在或不可讀；UpdateService 也不會為了顯示狀態而建立空資料庫，應先完成受控資料初始化／同步，再重新檢查。

若 TWSE 每日股價 batch 回報任何真正 `failed_dates`，該每日股價步驟會視為失敗並停止後續流程，避免 UI 顯示完成但實際缺個股日價；單一來源流程也不會再呼叫 TPEX、SQLite 同步或技術指標。只有 TWSE 的 `ALL` 與 `ALLBUT0999` 都精確回覆「很抱歉，沒有符合條件的資料！」時，日期才會列在 `no_data_skipped_dates`（同時保留於 `skipped_dates`），快速更新會顯示「TWSE 上游查無資料，已跳過日期：YYYY-MM-DD」警告並繼續 TPEX / SQLite / 技術指標流程；這種安全跳過不是成功下載，也不等同於資料完整。HTTP／timeout、JSON／欄位解析失敗、「查詢日期大於今日」或其他非完整的「查無資料」文案仍是 `failed_dates`，不會被當成休市日。若 TPEX endpoint timeout、Cloudflare/HTTP 阻擋或部分日期失敗，UI 會繼續已成功的 TWSE / SQLite / 技術指標流程，但最後會標示「未完整」並列出 `TPEX 每日股價缺少日期：YYYYMMDD`；這代表需要重測或補跑缺漏日期，不代表 TWSE 資料也失敗。若只有 TWSE 成功，`daily_prices` 當日可能只含上市股票，技術指標與全市場判讀應等 TPEX 缺口補齊後再視為完整。

每日股價分頁另有「背景補齊 TPEX + 技術指標」與「檢查背景任務狀態」。背景任務不會先強制跑 TWSE 全量，也不會強制全量重算技術指標；同步 SQLite 後會比對每日股價與技術指標最新日期，若技術指標已追上每日股價，狀態會顯示 skipped。每日股價頁面內另有可見狀態列，會顯示 `尚未啟動`、`執行中`、`完成` 或 `失敗` 及最後更新時間；狀態檔無法建立時，系統會停止啟動背景程序並顯示原因，不讓畫面留下無法追蹤的假執行狀態。狀態檔位於 `DATA_ROOT/meta_data/tpex_full_refresh_status.json`；若狀態顯示 `running`，請用狀態查詢確認進度，不要重複啟動第二個背景任務。日期範圍同步若發生例外會寫入下方日誌，應先處理該錯誤再開始下載。

#### 背景工作與安全關閉

資料更新、推薦／回測報告匯出、每日決策與主力流向等背景工作執行時，關閉子頁或主程式會先送出**非阻塞合作式取消**。系統不會對持有 SQLite、檔案或報告暫存資源的工作呼叫 `QThread.terminate()`，也不會在 UI 主執行緒無期限 `wait()`；若工作或 TPEX 獨立背景程序仍未結束，視窗會保持開啟並提示「已暫停關閉」。請等待畫面恢復可操作或背景狀態不再是 `running`，再關閉一次。

背景 worker 的結果 signal 可能早於原生 Qt thread return 抵達 UI；系統會保留 worker 參考直到 native `QThread.finished()`，且把過早的 `deleteLater()` 延後到 thread 停止後，避免 queued UI cleanup 釋放仍在執行的 Qt thread。若按下更新頁的取消按鈕，這個生命週期保護會繼續等待自然收尾；取消完成前不要切換成「更新成功」的人工判讀。

這個保護不會把未完成更新標成成功，也不會刪除 raw CSV、SQLite 或既有報告。若工作長時間沒有自然結束，應先保留 log／status 後依對應資料源的排錯流程處理，不要以強制結束程序取代資料一致性檢查。

桌面 App 直接啟動時會在載入 Qt 前啟用持久化 crash diagnostics，檔案固定為 `DATA_ROOT/logs/ui_qt_crash.log`。`SESSION_START` 後若沒有對應的 `SESSION_END`，或結尾為 `clean_shutdown=false`，代表程序未走完無例外的正常關閉；Python 主執行緒、背景執行緒與已被啟動邊界攔下的例外會保存 traceback，native fatal fault 則由 `faulthandler` 保存所有執行緒堆疊。每個 session 也會記錄 executable、argv0、cwd、parent PID 與 DATA_ROOT（不記錄完整環境或秘密），方便把 WER 對回實際 entrypoint。Windows 事件檢視器的 `RADAR_PRE_LEAK_64` 是記憶體壓力／疑似洩漏預警，不可單獨當成實際 crash；需與這份 log、WER Application Error 或 dump 一起判讀。

啟動訊息含有繁體中文；`ui_qt/main.py` 會在直接或被其他 launcher 呼叫的 entrypoint 先將 stdout/stderr 嘗試切換為 UTF-8，並以 `backslashreplace` 處理不允許 reconfigure 的 console。這避免 Windows cp1252 console 在建立 `QApplication` 前因 `UnicodeEncodeError` 退出；若 stream 不可調整，會 fail-soft 繼續啟動，真正的例外仍由上述 diagnostics 記錄。

`config.log`、`db_manager.log`、`data_loader.log`、`market_data_process.log` 或 `technical_calculation.log` 若因唯讀環境、短暫檔案鎖或權限問題無法建立，核心服務會降級為 console-only logging，不再只因診斷檔不可寫就中止 App 啟動或資料計算。這只放寬 log sink；SQLite、來源資料與任何正式 gate 的權限並未放寬。

券商分點同步會保存 `trade_type`，同一分點 / 股票 / 日期可同時有買超與賣超 rows。若舊 SQLite `broker_flows` 還是三欄主鍵，下一次同步券商分點時會先備份 DB，再把唯一鍵升級為 `(分點名稱, 證券代號, 日期, trade_type)`。

券商分點下載在 `force_all=false` 時會先檢查日檔 CSV 與 SQLite `broker_flows`。SQLite 檢查會同時比對分點顯示名稱與系統 key，避免 DB 已有資料卻仍啟動 MoneyDJ / Selenium 重新抓取。

券商分點下載仍採保守序列流程，但進入 MoneyDJ 前會先用每日股價日檔或 SQLite `daily_prices` 檢查目標日期是否有行情證據；無行情證據的日期會整天跳過，不會讓每個分點各自重試。MoneyDJ 正常頁面會優先使用 HTTP fast path 直接抓取 Big5 HTML，只有 HTTP 失敗或解析不到資料時才退回 Selenium fallback。預設請求間隔為 0.5 秒；若一次更新約 40 個分點耗時較長，先確認是否已有 CSV / SQLite 既有資料可跳過。本版尚未支援 5 或 10 worker 並行，避免對 MoneyDJ 造成過高併發與站方阻擋風險。

若需要量測技術指標本身而不觸發寫入，可使用：

```powershell
.\.venv\Scripts\python.exe scripts\qa_technical_indicator_latency.py `
  --technical-dir D:\Min\Python\Project\FA_Data\technical_analysis `
  --stocks 0050 2330 3008 --rows 500 --runs 3
```

此 probe 只讀取明確指定的既有指標 CSV，輸出 CSV read／calculate latency，並固定
標示 `parallelism_enabled=false`、`observed_worker_count=1` 與
`single_writer_required=true`。它不建立備份、不寫 SQLite，也不能用來宣稱全市場
更新已完成多核心化；完整規劃與 acceptance criteria 見
`docs/06_qa/DATA_UPDATE_PERFORMANCE_BASELINE_2026_08_28.md`。

若要量測 raw stock CSV 的全批次記憶體流程，可使用：

```powershell
.\.venv\Scripts\python.exe scripts\qa_technical_indicator_full_batch.py `
  --stock-data-file D:\Min\Python\Project\FA_Data\meta_data\stock_data_whole.csv `
  --stocks 0050 2317 2330 2454 `
  --min-rows 30 --max-rows-per-stock 120 --runs 1 `
  --output-json <TEMP_OUTPUT>
```

此 probe 會完整讀取明確 CSV，再在記憶體中依股票分組、呼叫
`calculate_all_indicators` 並 concat 結果；不呼叫 writer、不建立 backup、不寫
CSV／SQLite，也不啟用 worker。`--max-rows-per-stock` 只限制本次計算的樣本，不能
當成正式指標回補設定。輸出會分開列出 read／normalize／group／calculate／aggregate
耗時、row count、失敗代號與 `write_attempted=false`；它仍不能證明 CSV serialization、
backup 或 SQLite contention 已通過，後續需在 isolated staging 另做 write probe。

若要在不碰正式資料的前提下量測 CSV serialization、既有 SQLite writer 與 single-writer contention，可使用：

```powershell
New-Item -ItemType Directory -Path C:\Users\archi\AppData\Local\Temp\technical_analysis_write_probe_stage -Force
.\.venv\Scripts\python.exe scripts\qa_technical_indicator_write_probe.py `
  --stock-data-file D:\Min\Python\Project\FA_Data\meta_data\stock_data_whole.csv `
  --staging-root C:\Users\archi\AppData\Local\Temp\technical_analysis_write_probe_stage `
  --protected-root D:\Min\Python\Project\FA_Data `
  --protected-root D:\Min\Python\Project\FA_Data\output `
  --confirm-write-probe --stocks 0050 2330 --min-rows 30 --max-rows-per-stock 120 `
  --output-json <TEMP_OUTPUT>
```

這個 probe 必須明確傳入既有 staging root、至少一個 protected root 與 `--confirm-write-probe`；
未確認時不建立任何檔案，staging root 位於 protected root 內也會 fail-closed。確認後只在
staging 的 ephemeral 子目錄寫入逐股／合併 CSV 與 SQLite，結束後自動清除；正式 raw CSV
以前後 SHA-256 驗證未變更。輸出會列出 CSV／SQLite 各 stage 的耗時、row count、hash、
`database is locked` contention、serialized retry、cleanup 結果與
`production_write_attempted=false`。這只能證明隔離 writer 邊界，不代表 production
writer 已改造或授權提高 worker 數；在 broker rate-limit、取消／重試與 bounded worker
acceptance 通過前，技術指標仍維持單一 worker。

若要把真正的 `TechnicalIndicatorCalculator` 放進受控 process pool 做 staging throughput
驗收，可使用：

```powershell
New-Item -ItemType Directory -Path C:\Users\archi\AppData\Local\Temp\technical_analysis_process_pool_stage -Force
.\.venv\Scripts\python.exe scripts\qa_technical_indicator_process_pool.py `
  --stock-data-file D:\Min\Python\Project\FA_Data\meta_data\stock_data_whole.csv `
  --staging-root C:\Users\archi\AppData\Local\Temp\technical_analysis_process_pool_stage `
  --protected-root D:\Min\Python\Project\FA_Data `
  --protected-root D:\Min\Python\Project\FA_Data\output `
  --confirm-process-pool-probe --stocks 0050 2330 --min-rows 30 `
  --max-rows-per-stock 120 --workers 2 --max-in-flight 4 --max-retries 1 `
  --transient-fail-stocks 0050 --output-json <TEMP_OUTPUT>
```

這個 probe 必須明確指定 bounded 股票範圍、staging root、protected root 與確認旗標；
worker 只回傳計算結果，逐股／合併 CSV 由父程序寫入 ephemeral staging，SQLite connection
不會進入子程序。輸出會列出 worker PID、in-flight 上限、retry、CSV serialization、
cleanup、input hash 與 `production_worker_enabled=false`。`status=measured` 只代表真實
calculator 的 staging process-pool 形狀通過；這份 probe 本身不涵蓋 worker crash recovery、
長時間取消與正式 single-writer integration，因此 production worker 數維持 1。

若要在同樣的隔離邊界驗證 worker process 意外結束後的 recovery、queued cancellation
與 partial-result discard，可使用：

```powershell
New-Item -ItemType Directory -Path C:\Users\archi\AppData\Local\Temp\technical_analysis_worker_recovery_stage -Force
.\.venv\Scripts\python.exe scripts\qa_technical_indicator_worker_recovery.py `
  --stock-data-file D:\Min\Python\Project\FA_Data\meta_data\all_stocks_data_top10.csv `
  --staging-root C:\Users\archi\AppData\Local\Temp\technical_analysis_worker_recovery_stage `
  --protected-root D:\Min\Python\Project\FA_Data `
  --protected-root D:\Min\Python\Project\FA_Data\output `
  --confirm-probe --stocks 2330 2308 --min-rows 30 --max-rows-per-stock 120 `
  --workers 2 --max-in-flight 2 --max-retries 1 --output-json <TEMP_OUTPUT>
```

此 probe 會以真實 `TechnicalIndicatorCalculator` 驗證 `BrokenProcessPool` 後重建
executor、取消 queued work 與丟棄取消後才完成的結果；接著在 ephemeral staging
由父程序依序寫入逐股／aggregate CSV 與既有 `DBManager` SQLite writer，並驗證
SQLite lock／retry。worker 不持有 CSV／SQLite writer，staging 結束後會清理。
`status=measured` 代表 recovery／取消與 parent writer staging contract 通過，
而 `production_single_writer_integration=staging_measured`、scope=`isolated_staging`
仍不是正式資料寫入證明。現在 production batch 已接上明確 feature flag，但預設仍關閉；
未完成 backup／rollback 與 owner-approved canary 前，不應在排程 task 傳入啟用旗標。

若要在受控環境以已驗收的 contract 執行一次 bounded technical worker，可明確傳入：

```powershell
.\.venv\Scripts\python.exe scripts\scheduled\run_daily_data_update_quick.py `
  --data-root <DATA_ROOT> --output-root <OUTPUT_ROOT> `
  --enable-technical-process-pool --technical-process-pool-workers 2 `
  --technical-process-pool-max-in-flight 4 --technical-process-pool-max-retries 1
```

這個旗標只把計算放入 bounded process pool；日期／warm-up 決策仍在父程序，
worker 不寫 CSV／SQLite，父程序才逐股保存並做整合寫入。每次 run 的 running／terminal
status 會記錄 flag 與 queue 參數，便於回滾與查核。未傳入旗標時維持既有 serial path；
worker 例外或取消不會自動降級成另一套計算結果。

若要驗證券商 HTTP fetch 的 bounded queue、global rate-limit、retry、duplicate 與
single-writer 契約，可使用離線 transport probe：

```powershell
New-Item -ItemType Directory -Path C:\Users\archi\AppData\Local\Temp\technical_analysis_broker_fetch_stage -Force
.\.venv\Scripts\python.exe scripts\qa_broker_bounded_fetch_acceptance.py `
  --staging-root C:\Users\archi\AppData\Local\Temp\technical_analysis_broker_fetch_stage `
  --protected-root D:\Min\Python\Project\FA_Data `
  --protected-root D:\Min\Python\Project\FA_Data\output `
  --confirm-broker-fetch-probe --max-tasks 9 --workers 2 --max-in-flight 4 `
  --max-retries 1 --rate-limit-seconds 0.005 --response-delay-seconds 0.02 `
  --output-json <TEMP_OUTPUT>
```

此 probe 不連線、不啟動 Selenium，使用假的 response 但實際呼叫既有
`BrokerBranchUpdateService._fetch_metric_records_http`／parser；9 個 submission 含
duplicate、transient 與預期 permanent failure，結果只由父程序寫入 ephemeral CSV。
`status=measured` 代表離線工程契約通過，不能當成 MoneyDJ 真實來源、授權或
canary 成功；真實 HTTP canary、rate-limit 觀測、Selenium driver recovery 與 production
broker worker 仍需另行取得環境／owner 允許。

若要只做一次真實來源連線驗證，可使用受控 canary：

```powershell
New-Item -ItemType Directory -Path C:\Users\archi\AppData\Local\Temp\technical_analysis_performance -Force
.\.venv\Scripts\python.exe scripts\qa_broker_real_http_canary.py `
  --staging-root C:\Users\archi\AppData\Local\Temp\technical_analysis_performance `
  --protected-root D:\Min\Python\Project\FA_Data `
  --protected-root D:\Min\Python\Project\FA_Data\output `
  --branch-system-key 1030_1030 --branch-broker-code 1030 --branch-code 1030 `
  --branch-display-name 土銀 --url-param-a 1030 --url-param-b 1030 `
  --date 2026-08-28 --metric lots --timeout 15 `
  --confirm-real-http-canary `
  --baseline-json C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\broker_bounded_fetch_20260828.json `
  --output-json <TEMP_OUTPUT>
```

未提供 `--confirm-real-http-canary` 時完全不發網路請求；確認後固定只發一個 GET、
`retries=1`，使用既有 HTTP parser，Selenium 與平行 fetch 均不啟動。輸出會保留
branch/date/metric、endpoint、解析列數、parsed-row hash、cleanup 與所有 production
write flags。若加上 `--baseline-json`，只會讀既有離線 baseline 並產生新的合併 artifact，
不改寫 baseline。一次成功不能代表來源授權、長期 rate-limit、Selenium recovery 或
production writer 已通過；後續仍需 owner review，broker pool 維持關閉。

若要驗證 technical process-pool 的正式 single-writer 邊界，只能對一檔股票執行受保護的 production canary：

```powershell
.\.venv\Scripts\python.exe scripts\qa_technical_indicator_production_canary.py `
  --data-root D:\Min\Python\Project\FA_Data `
  --output-root D:\Min\Python\Project\FA_Data\output `
  --protected-root D:\Min\Python\Project\FA_Data `
  --protected-root D:\Min\Python\Project\FA_Data\output `
  --stock-id 2330 --expected-latest-date 2026-08-28 `
  --output-json C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\technical_production_canary_20260828.json
```

上述預設為唯讀預演，不建立 backup、不呼叫 `UpdateService`，且會先確認 production SQLite
完整性、指定股票日價與 expected latest date。只有 owner 明確提供
`--owner-approval technical-single-writer-canary`、
`--no-concurrent-writer-ack no-concurrent-writer` 及
`--confirm-production-technical-canary`，並先停止其他資料寫入者，才會建立 SQLite online backup
與單股 technical CSV backup，接著以 bounded process pool 重算一檔；worker 不寫檔，parent 才寫 CSV／SQLite。
建立 backup 前還會唯讀檢查 backup 所在檔案系統的 headroom，預設至少需要 20 GiB；不足時回報
`production_canary_storage_preflight_blocked`，不建立 backup、不啟動 writer。只有在受控環境明確調整
`--minimum-free-space-bytes` 且容量可追溯時才可降低門檻。
若 post-state 驗證失敗，工具會嘗試以 backup 回復並在 artifact 記錄 rollback 結果；canary 不下載行情、
不啟動 broker／Selenium，也不會註冊 scheduler。`status=measured` 只代表這一次 owner-approved
canary 的 backup／single-writer／post-state 驗收通過，不能直接把 scheduler worker 數提高。

若要把目前分散的效能證據交給 owner／reviewer，可使用唯讀 owner packet builder：

```powershell
.\.venv\Scripts\python.exe scripts\build_performance_canary_owner_packet.py `
  --technical-preview <TECHNICAL_PREVIEW_JSON> `
  --worker-recovery <WORKER_RECOVERY_JSON> `
  --broker-canary <BROKER_CANARY_JSON> `
  --direct-storage-preflight <DIRECT_STORAGE_PREFLIGHT_JSON> `
  --retention-direct <RETENTION_DIRECT_JSON> `
  --retention-ooc <RETENTION_OOC_JSON> `
  --output-json <TEMP_PERFORMANCE_OWNER_PACKET_JSON> `
  --markdown-output <TEMP_PERFORMANCE_OWNER_PACKET_MD> `
  --owner-role <NAMED_OWNER_ROLE> `
  --reviewer-role <NAMED_REVIEWER_ROLE>
```

六個輸入必須是呼叫端明確指定、位於 OS TEMP 的既有 artifact，且 schema／安全旗標不符時會
fail-closed；輸出也只能位於 OS TEMP，不能覆寫輸入。packet 只保留 bounded metadata、來源
path 與 SHA-256，固定 `candidate_only=true`、`write_performed=false`、
`destructive_action_performed=false`，不啟動 technical worker／broker production fetch pool、
不做 Formal OOS／broker order，也不刪除或搬移 Direct/OOC run。`needs_named_owner_reviewer` 或
`ready_for_owner_review` 只表示交接欄位狀態，不是 production canary 授權；容量低於 20 GiB
時必須先停止並交由 owner 決定 archive／擴容，不能用 packet 取代 capacity preflight。

若要驗證未來 technical compute-only worker 的 bounded queue 契約，可使用 synthetic probe：

```powershell
.\.venv\Scripts\python.exe scripts\qa_bounded_worker_acceptance.py `
  --workers 2 --max-in-flight 4 --max-retries 1 --cancel-after 3 `
  --output-json <TEMP_OUTPUT>
```

它不讀取或寫入任何正式資料，只驗證 in-flight 上限、有限 retry、permanent failure 不寫入、
duplicate idempotency、取消後停止新提交，以及 worker 不直接寫入而由主執行緒 single writer
收口。`status=measured` 只代表 synthetic orchestration contract 通過；真實 indicator
process-pool throughput 與 crash recovery 已有獨立 staging probe，broker HTTP rate-limit／retry
與正式 single-writer integration 仍需另外驗收，在此之前 production worker 數維持 1。

### 4.4 技術指標

- 「增量更新」：只處理新資料，日常首選；若單股指標已到最新股價日期會直接跳過，只有落後時才回看 120 個交易日重算重疊區間。
- 「強制全量更新」：重算所有股票歷史資料，只在指標算法改動或資料損毀時使用。
- 股票代號留空代表處理全部；輸入例如 `2330` 代表只處理單一股票。
- 增量寫入單股指標 CSV 時，若舊檔或新結果缺少可辨識日期欄位，會避免直接疊加資料；必要時以新計算結果覆蓋該單股檔，防止同一股票歷史列倍增。
- 一鍵更新與排程判斷技術指標是否可跳過時，除了比較 `daily_prices` / `technical_indicators` 最新日期，也會檢查最新日 eligible 股票覆蓋數；若 TWSE 先完成、TPEX 後補進來，系統會再跑增量計算，不會因全表最新日期相同而漏掉 TPEX 股票。
- 技術指標計算預設仍是單流程；若受控 caller 傳入 `--enable-technical-process-pool`，才會以 bounded compute-only worker 平行計算，並由父程序單一 writer 統一寫入 CSV／SQLite。可設定的 worker、in-flight 與 retry 上限會寫入 run status；正式 scheduler 預設不傳旗標，待 backup／rollback、真實 canary 與效能觀測完成後才評估啟用。
- 推薦與回測載入已保存技術指標後，只有在參數等於系統標準預設、欄位完整且含有效值時才直接重用；自訂參數、缺欄位、全無效欄位、ATR 或 ADX 仍會按原流程計算。這項最佳化不改技術指標更新排程、SQLite schema、推薦門檻或回測規則。

### 4.5 SQLite 資料檢視

1. **選擇與篩選**：選擇資料表，設定每頁限制筆數，填入股票代號、名稱、券商分點或日期篩選。券商分點可在 `broker_flows` 時由下拉選單選取，也可手動輸入關鍵字。日期預設空白，不會自動套用條件；打開日曆時會定位到今天。單一日期可按「今日」快速帶入今天，區間旁的「清除」會同時清掉單一日期與區間日期。
2. **載入數據**：點擊「載入數據與結構」按鈕。
3. **基本面資料表**：資料表下拉選單會列出 `fundamental_monthly_revenues`、`fundamental_statement_items`、`fundamental_valuation_metrics`。月營收表可用股票代號與日期篩選，日期對應 `as_of_date`，例如 `2026-05-31`。
4. **資料分頁控制**：
   - 底部設有分頁控制列，包含「上一頁」、「下一頁」、「跳至第 X 頁碼（輸入頁碼並按跳頁按鈕）」、以及「當前頁數 / 總頁數」與「篩選後總記錄數」。
   - **防禦機制**：修改篩選條件並重新載入時，系統會自動重設為第一頁，並快取 schema 避免不必要的拉取。
   - **Stale 結果防護**：連續切換分頁或資料表時，舊有的非當前背景查詢結果會被自動忽略；執行中的背景查詢會安全保留到自然結束，防止 UI 資料錯亂或執行緒提前銷毀。
5. **欄位結構**：在「欄位結構」Tab 查看欄位 Schema 與型態描述。
6. **表頭排序**：在「資料預覽」點擊任一欄位表頭可切換升冪 / 降冪。排序由 SQLite 端以白名單欄位 `ORDER BY` 執行，並沿用目前篩選與分頁限制，避免 UI 端載入全表排序。
7. **漲跌欄位顯示**：`daily_prices` 若遇到舊 schema 的簡體 `涨跌`，畫面會顯示為繁體 `漲跌`；`漲跌價差` 會依 `漲跌(+/-)` 或 `漲跌` 方向顯示正負號，以利顏色與排序判讀。
8. **重複顯示欄名防護**：若 raw schema 與 alias 造成相同顯示欄名，表格仍以欄位位置取值，不應出現 `PandasTableModel.data` 的 Series ambiguity 錯誤。

此工具是受控唯讀檢視器，不應用來修改或刪除資料。

### 4.6 市場資料完整性修復（受控 CLI）

當資料品質稽核發現 `daily_prices` 有空白股票代號、非交易日誤入資料，或 `market_indices` 缺少指數名稱時，使用受控 CLI；它不會改動 raw CSV、策略、Recommendation、evidence 或 scheduler。星期六、日不是直接刪除條件：個股日檔必須先符合「含 `證券代號`、`收盤價`」的欄位契約；若日期落在週末，還必須有 TWSE `MI_INDEX` 的官方開市資料才允許同步。官方查詢失敗時 fail-closed，不把該日當作可交易日。

```powershell
# 先只讀列出預計修復範圍與每個週末日期的官方查詢證據
.\.venv\Scripts\python.exe scripts\repair_market_data_integrity.py --json-output

# 人工核對後才套用：只建立一份 SQLite snapshot、移除已驗證非交易日 / 空代號列，並由 raw market_index.csv 重建 market_indices
.\.venv\Scripts\python.exe scripts\repair_market_data_integrity.py --apply --confirm apply-market-data-integrity-repair --json-output
```

套用前腳本會用 SQLite backup API 建立 `DATA_ROOT/sqlite/backups/twstock_before_market_data_integrity_<timestamp>.db`，並執行 `PRAGMA quick_check`。若驗證不通過，正式 DB 不會進行刪除。回復時應停止寫入工作、以該 snapshot 依 SQLite backup API 還原，再重新跑 `PRAGMA quick_check`；不可用複製貼上方式覆寫仍在使用中的 WAL 資料庫。

大型備份不會由腳本自動刪除。先以只讀盤點確認健康度與保留候選，再由 owner 對每一份候選確認用途與可回復性：

```powershell
.\.venv\Scripts\python.exe scripts\audit_sqlite_backup_retention.py --verify
```

預設建議是保留 active DB 與三份最新、已驗證的完整 snapshot；舊 snapshot 僅列為人工審核候選，絕不自動刪除，避免破壞與 migration / backfill 對應的回復點。

### 4.7 匯出 CSV 備案

個別資料頁可選：

- 最近範圍
- 全部歷史

輸出使用 UTF-8 with BOM，方便用 Excel 開啟。這是離線備份與人工研究功能，不影響系統日常運作。

### 4.8 高風險操作

「強制重新合併」與「強制全量更新」會長時間處理大量歷史資料。只有在資料損毀、schema 修復或算法變更後使用，不要作為日常更新方式。

### 4.9 Month 5 月營收候選資料抓取

月營收候選資料抓取只負責來源驗證與 raw evidence 保存；抓取 CLI 本身不會寫入正式 `DATA_ROOT/meta_data/monthly_revenue_availability.csv`，也不會寫入 `fundamental_monthly_revenues`。正式 mapping 與 SQLite 回填需另外走 validator / backfill 流程，並在高風險操作前由人工確認。

今晚建議先跑兩個檔案：

```powershell
.\.venv\Scripts\python.exe scripts\fetch_mops_monthly_revenue_snapshot.py --start-period 2014-04 --end-period 2026-05 --markets twse,tpex --output-dir D:\Min\Python\Project\FA_Data\output\monthly_revenue_mops_snapshots --fetch-date 2026-06-16 --sleep-seconds 0.5
.\.venv\Scripts\python.exe scripts\fetch_finmind_monthly_revenue_create_time.py --start-date 2014-04-01 --end-date 2026-05-31 --raw-dir D:\Min\Python\Project\FA_Data\financial_data --output-dir D:\Min\Python\Project\FA_Data\output\monthly_revenue_finmind_create_time --max-requests-per-hour 480 --resume --fetch-date 2026-06-16
```

第一個命令會保存 MOPS raw HTML 與完整市場月營收 snapshot CSV；它只代表營收內容快照，不得用 period 或歷史查詢日推定官方公告日。若從某天開始每日保存 MOPS snapshot，可把本機首次看見該月營收列的日期視為 first-seen observation candidate，搭配 `available_date=first_seen+1 calendar day` 作保守候選 mapping；這仍不是官方 MOPS 公告日，正式寫入前必須由人工確認。第二個命令會使用已加密保存於本機的 FinMind token 逐檔抓取 `TaiwanStockMonthRevenue.create_time`，輸出 create_time 分組檔；`create_time` 只作備用 / 交叉檢查與每月分批更新參考，不作主線 mapping。若 FinMind 流程中斷，用同一個 `--output-dir` 加 `--resume` 重跑即可接續。

毛利率不是月營收資料。MOPS `t163sb06` 是季度財務比率 / 毛利率彙總表，查詢維度是年度與季別；後續若要納入，應走季度財報 / 財務比率 pipeline，另建公告日與 `available_date` gate，不要混進今晚的月營收 snapshot 或 FinMind create_time 流程。

## 5. 市場探索

### 5.1 大盤指數

1. 點擊「檢測市場狀態」。
2. 查看 Regime、規則匹配度與判斷摘要。
3. 展開技術細節時，可查看價格與均線、趨勢、評分、其他指標與判斷條件。
4. 將策略建議作為 Profile 選擇參考，不要視為買賣訊號。

Regime 是對當下市場環境的分類，不是未來預測。規則匹配度是 detector 對目前資料符合既有規則的程度；100% 代表達到目前規則上限，不代表未來勝率或成功機率。

### 5.2 強勢與弱勢個股

1. 選擇「本日」或「本周」。
2. 第一次進入可按「載入數據」。
3. 需要重新計算時按「刷新」。
4. 選取股票後按「加入觀察清單」。

強勢排名不等於建議追價；弱勢排名也不等於做空或立即賣出。

強弱勢表格下方的狀態列會顯示「載入中」、「已更新」與實際筆數；若服務回傳空資料會顯示 0 筆，若刷新失敗則顯示第一行錯誤診斷並清空上一輪表格，避免把過期排名誤讀成目前結果。請先依狀態列診斷資料來源，再重試刷新。

弱勢頁的跌幅欄位位於顯示邊界，會安全處理 CSV／舊服務傳入的字串數字；無法轉換的值留為缺值，不會把整頁誤判成載入成功，也不會以 `0` 補值。

弱勢個股頁的 `跌幅%` 會把來源的負漲幅取絕對值顯示，例如來源 `-9.90%` 在畫面顯示為 `9.90`，並以紅色表示下跌語意；欄名已經說明這是跌幅，所以不再用負號重複表意。這只是視覺語意修正，不改變篩選排名或 scoring。

效能邊界：強 / 弱勢個股在 SQLite 啟用時會優先從 SQLite `daily_prices` 只讀近期交易日與必要欄位，不依賴全量 indicator CSV 掃描；產業共振理由會使用 `IndustryMapper` 最新產業表現快取，避免逐檔股票重掃產業指數 DataFrame；讀取失敗才降級為既有 CSV / 舊查詢路徑。若仍感到卡頓，應先量測 SQLite 查詢、DataFrame 分組與 UI thread 更新時間；不要把排名結果解讀成交易指令。

候選池頁同樣採狀態列語意：載入中、已更新筆數、空候選與錯誤都會直接顯示在表格下方；空清單或載入失敗不會插入 `-` 佔位資料列，批次回測按鈕也會維持停用。

### 5.3 強勢與弱勢產業

使用本日或本周排名判斷產業相對強弱，再回到個股頁或推薦頁研究產業內股票。

強 / 弱勢產業同樣採 SQLite-first，從 SQLite `industry_indices` 只讀近期交易日與 `日期` / `指數名稱` / `收盤指數` 必要欄位；缺資料或讀取失敗才 fallback CSV。大型資料量下第一次載入仍可能需要等待，但不再需要先載入整張產業指數表。

弱勢產業頁的 `跌幅%` 同樣以正數顯示跌幅大小、以紅色表示下跌語意；不應把紅色正數解讀為上漲。

### 5.4 主力流向

「個股資金流向」操作：

1. 選擇日線、週線或月線。
2. 選擇直方、折線或面積趨勢圖。
3. 選擇顯示範圍；預設為「Top / Bottom 50」，主表只顯示買超前 50 與賣超後 50，摘要統計仍使用全市場掃描結果。
4. 點擊「開始掃描」。
5. 點選主表股票，右側顯示分數、集中度、訊號原因與分點明細。
6. 主表新增「語意狀態」與「5/20/60 日診斷」欄；語意狀態包含 `初轉買`、`買超延續`、`初轉賣`、`賣超延續`、`高檔出貨疑慮`、`分點集中異常`。
7. 主表欄寬預設優先保留 5/20/60 日診斷與近期趨勢圖；集中度、語意狀態、5/20/60 日診斷與 Badges 欄都依目前資料最長內容加少量留白自動貼合，不吃掉所有剩餘空間。近期趨勢欄維持 compact 固定寬度，直方圖會在欄內以緊湊間距並保留左側 padding 繪製，右側分點 panel 會取得多餘空間；完整數字與品質細節保留在 tooltip。
8. 懸停列可查看 5 / 20 / 60 日 Top N quantity 集中度、observed / estimated / unavailable 筆數、5 / 20 / 60 日淨量與價格位置等診斷。
9. 表格標頭可排序。
10. 有 Watchlist service 時，可按「+ 觀察清單」。
11. 右側分點明細表會依 panel 寬度自動分配「分點名稱 / 買進張數 / 賣出張數 / 淨買賣超」四欄，優先完整顯示內容與淨買賣超 bar，不應需要水平捲動。
12. 在右側分點明細雙擊分點名稱，會切到「分點進出追蹤」並選中該分點。

「分點進出追蹤」操作：

1. 選擇券商分點。
2. 查看該分點近期操作股票、張數、標籤與趨勢。

資料品質：

| 品質 | 解讀 |
|---|---|
| observed | 原資料直接觀測到張數或金額。 |
| estimated | 由可用價格與金額估算，信心較低。 |
| unavailable | 無足夠資料，不應硬補成 0。 |

語意診斷限制：

- 5 / 20 / 60 日視窗只使用決策日以前可取得的分點事件，不使用未來資料補滿視窗。
- 分點集中度使用 quantity（張數 / 股數等價數量）計算，不使用千元金額直接當集中度。
- unavailable 事件不放進集中度分子或分母，會在 tooltip 揭露排除筆數與覆蓋率。
- `高檔出貨疑慮` 是價格位置與主力賣超聯動的風險提示，不等於賣出建議。
- `分點集中異常` 代表同方向淨量集中於少數分點，應搭配價格、成交量與資料品質判讀，不直接代表利多或利空。

單一分點買超不等於真實主力意圖，應優先觀察多分點共振、價格行為與資料覆蓋率。

## 6. 推薦分析

### 6.1 新手模式

1. 查看系統偵測的市場狀態與 Profile 建議。
2. 可按「一鍵套用建議 Profile」。
3. 或自行選擇 Profile。下拉會標示來源：
   - `內建｜...`：系統內建模板，例如暴衝、穩健、長期。
   - `自訂｜...`：使用者從目前推薦設定保存的 Profile，會標示「自訂，未經回測驗證」。
   - `策略版本｜...`：Research Lab / Strategy Registry 已通過 gate 的策略版本；停用或未通過 gate 的版本不顯示，但歷史策略版本資料不會被刪除。
4. 選擇 Profile 後，閱讀說明區的「對應進階設定」，確認權重、技術分類、型態預覽與主要篩選條件是否符合預期。三個內建 Profile 不只是 buy score / sell score 門檻不同，也會帶入不同的 `pattern` / `technical` / `volume` 權重、啟用技術分類、型態偏好與漲幅 / 成交量篩選。
5. 若目前設定值得重用，可按「保存目前設定為自訂 Profile」；保存後會出現在 `自訂｜...` 清單。
6. 點擊「執行推薦分析」。

市場狀態卡會顯示 Regime 中文名、regime code、confidence / 規則匹配度、Regime score、資料日期與來源。confidence / 規則匹配度是當下資料符合分類規則的程度，不是未來走勢勝率。

Profile-Regime 說明：

- `match` / `bonus`：目前 Regime 落在 Profile 適用 Regime；既有 scoring 會以 regime 權重調整揭露加分語意。
- `mismatch` / `penalty`：目前 Regime 不在 Profile 適用範圍；結果不會被直接排除，只在排序、分數或原因中揭露不匹配。
- `neutral` / `no_bonus`：Regime 尚不可用或 Profile 未指定適用 Regime；不套用 Profile-Regime 加分。

### 6.2 進階模式

可設定：

- 技術指標
- 圖形模式
- 最小漲幅
- 最小成交量比率
- 產業
- 排名門檻
- 月營收 YoY 最低值（可選）
- PE 最高值（可選）

參數治理限制：

- 新版配置啟用的技術指標必須提供完整參數；字串代替整數、未知欄位、越界值或衝突組合會直接顯示失敗，不會靜默使用猜測值。
- 關閉的子指標不會計算，也不會產生空欄位。
- 評分權重使用 `pattern`、`technical`、`volume` 三項整數基點，總和必須為 `10000 bp`。
- 核心總分使用 Decimal 並固定至 `0.01` 分；設定錯誤屬治理例外，不會被轉成空結果。
- buy score / sell score 是總分完成後的判讀門檻；調整門檻只改入選 / 賣出判讀，不會改變各項指標如何貢獻總分。若要改變「為什麼得分」，必須修改 Profile 權重、技術指標、型態或前置篩選，並重新做推薦回放 / Research Run 驗證。
- 啟用月營收 YoY 或 PE 篩選時，系統只採用 `available_date <= decision_date` 的基本面版本；決策日期無法標準化、PE／同月去年營收缺失、或未達門檻時，候選會以 `skipped` 留在 screening matrix，不會以 0、空值或未來資料補足。PE 預設 `999`、YoY 預設 `-100` 為停用哨兵；調整後才會啟用對應篩選。

### 6.3 固定門檻與百分位排名

| 模式 | 行為 |
|---|---|
| 固定門檻 | 使用既有絕對分數與篩選邏輯。 |
| 百分位排名 | 在當日 eligible universe 中計算橫斷面排名。 |

百分位模式參數：

- 最低百分位：例如 80% 代表保留當日母體中較高排名區間。
- 最小母體數：避免用太少股票產生不穩定百分位。
- 排名方法：目前為「最近名次法」，使用排序後最接近的觀測值作為百分位門檻，方便追溯。

若出現 eligible universe too small：

1. 放寬前置篩選。
2. 增加最大掃描股票數。
3. 降低最小母體數。
4. 不要把錯誤改成自動退回 fixed；兩種模式應保持可辨識。

quantile 目前是 opt-in，不能宣稱比 fixed 更準。

### 6.4 結果判讀

- Why：為何入選。
- Why Not：哪些條件不足或限制排名。
- Explain：技術、圖形、量能等子分數與風險點。
- 圖形理由若顯示型態名稱，代表該型態已在可用收盤資料的確認日成立，並標示仍處於 20 個交易日衰減觀察窗的第幾天；`end_idx` 本身不算確認。若只看到「圖形訊號偏多／偏空」，代表資料沒有提供可核對的具體型態名稱，系統刻意不臆測。
- 百分位與母體：只在 quantile 模式有意義。
- Regime match / mismatch：顯示目前 market Regime 與 Profile 期望 Regime 是否一致；mismatch 是解釋與排序訊號，不是自動排除或交易指令。

V1.7 後，「保存結果」會一併保存推薦當下的 screening matrix：每檔候選會以 pass / fail / degraded / skipped / missing 標示狀態，並保留 Why Not、Liquidity exclusion、歷史不足、無訊號或例外降級等原因。2026-07-06 後，若個股因 `min_volume_ratio` / `volume_ratio_min` 成交量門檻而沒有策略結果，會以 `liquidity_volume_ratio_below_min` 進入 Liquidity payload；這只補來源追溯，不會改分數、不會自動調整持倉、不會自動降級策略版本。

「目前策略傾向摘要」只描述已勾選技術指標與圖形模式推導出的摘要，不是可調偏好控制。若需要改變偏短線、偏長線或盤整 / 趨勢取向，應回到 Profile 或進階設定調整實際條件。

推薦分析不會自動下單、不會自動調整持倉，也不會把自訂 Profile 視為已通過回測驗證。策略版本 Profile 只代表該版本通過既有 gate，可作推薦設定來源，仍需自行判讀資料品質、風險與研究證據。

### 6.5 結果後續操作

- 「保存結果」：保存推薦配置、Profile、Regime、推薦名單、screening matrix 與 negative evidence payload；成功訊息會顯示保存 ID、保存範圍與下一步入口。
- 「加入觀察清單」：把選取股票加入 Watchlist。
- 「送 Research Lab 批次回測」：用推薦名單建立批次研究輸入。
- 「送 Research Lab 推薦回放」：重播整套推薦 Profile / Config 在歷史期間每個決策點會產生的推薦，不是只拿今日名單回測。回放結果可保存為 Research Run / Evidence，再由 Registry 與 lifecycle gate 判讀 promote / hold / demote_candidate / retire_candidate；目前不會從推薦頁直接自動降級或刪除策略版本。
- 表格右鍵「記錄到持倉管理」：建立帶推薦來源 metadata 的交易。
- 「匯出 Excel」：建立包含元數據、今日推薦配置、Regime 狀態以及推薦股票名單的 Excel 報告，並在背景執行原子寫入。

## 7. 觀察清單與選股清單

### 7.1 候選池操作

- 「新增股票」：手動輸入股票代號；系統會先用正式股票資料查找名稱，查不到的代號會被阻擋，不會混入正式觀察清單。
- 「移除選中」：刪除選取列。
- 「清空候選池」：刪除全部候選，無法復原。
- 「刷新」：重新載入資料。

候選池保存來源、加入時間與備註，用於研究，不是實際持倉。

### 7.2 選股清單

- 「保存為選股清單」：把目前候選池保存為可重用 Universe。
- 「載入到候選池」：把既有 Universe 載入目前候選池。
- 「新增 / 編輯 / 刪除」：管理 Universe 名稱、說明與股票內容。

「送 Research Lab 批次回測」可直接把目前觀察清單送到 Research Lab，並切到批次股票回測模式。若清單為空，按鈕會停用並在 tooltip 顯示原因；若要保存成可重用 Universe，仍可使用「保存為選股清單」。

## 8. 每日決策（Daily Decision Desk）

### 8.1 進入與刷新

Daily Decision Desk 採用 Midnight Analyst 深色介面：深色背景、section header 狀態 badge、緊湊摘要卡片與分行代碼清單。強勢、弱勢與低流動性代碼每類預設顯示前 8 檔，其餘以剩餘檔數摘要；完整資料仍由 service snapshot 保留，不因 UI 摘要而改變計算結果。

Market Breadth、Relative Strength / Liquidity 與 Smart Money 會在同一次 snapshot 內共用唯讀市場資料 frame，減少重複 SQLite 查詢；每次重新建立 snapshot 都會重新載入，且只接受 `日期 <= as_of_date`。這不會跨排程沿用 cache，也不改各 section 的 quality、warnings 或降級規則。

頁面最上方會先顯示 answer-first dashboard：

- `今日主結論`：以 `積極研究`、`正常研究`、`保守觀察`、`暫停新進場` 表示市場研究節奏。
- `研究模式註記`：提醒本頁是市場與籌碼輔助判讀，不是交易建議。
- `優先產業` / `避開產業 / 風險區`：由產業輪動摘要產生，幫助先決定研究方向。
- `優先研究股票` / `風險股票`：整合相對強弱、Watchlist、持倉警示與 Smart Money 語意摘要。
- 股票焦點按鈕可下鑽到「市場探索 > 主力流向」並定位該股票。

Watchlist、持倉或單一股票風險不會直接降低整體市場行動等級；它們只影響股票焦點、風險清單與提示文字。整體行動等級主要由 Market Regime、Market Breadth 與資料品質決定。

warnings 在 UI 會以繁體中文說明主要原因與影響範圍；原始 token 保留在底層 snapshot / log 供除錯追溯，不直接作為一般畫面文字。看到 warnings 時先判斷是資料覆蓋率、歷史不足或服務降級，不應只看工程代碼做決策。

1. 進入左側主導覽「市場探索」，選擇第一個子頁「市場總覽」。也可在「決策工作台 > 決策來源」按「開啟市場總覽」前往同一個唯一實例。
2. 進入頁面時會先顯示「尚未載入 / 載入中」，Snapshot 會在背景執行緒建立，避免主 App 啟動被每日決策查詢阻塞。
3. 點選「刷新」可在背景重建 Snapshot；載入期間按鈕會暫時停用，完成後自動更新畫面。
4. 若初始化或刷新失敗，畫面會保留可閱讀狀態並顯示 fallback 提示，不會中斷整體 App。

### 8.2 結果解讀

每日決策摘要會顯示：

- 主結論與行動等級
- 優先 / 風險產業與股票焦點
- `as_of_date`：資料對應日期
- `quality`：整體品質（`OBSERVED` / `ESTIMATED` / `DEGRADED` / `MISSING`）
- `warnings`：所有 section 的缺口與降級原因彙總
- 各區塊 section：如 Market Regime、Market Breadth、Sector Rotation、Watchlist Trigger、Portfolio Alert
- 「資料可見性與擴充因子」：顯示月營收廣度、三大法人市場流向，以及各來源的觀測日、可得日、PIT 與 eligibility 狀態。此區塊只供研究可見性，不參與主結論、行動等級、產業／股票焦點、Score 或整體品質聚合。

月營收正向比例以整數 basis points 呈現為百分比；例如 `5636 bp` 顯示為 `56.36%`。三大法人尚未匯入時會顯示「尚未匯入（0 筆）」，不會把缺漏資料假裝成「外資 0」。可見性服務失敗時，只有此區塊降級為 `DEGRADED`／`MISSING` 並保留來源 warning；既有 Decision Desk action、focus 與 Score 不會因此被重算或改寫。

Market Breadth v1 會從 SQLite `daily_prices` 唯讀推導：

- 多方 / 空方 / 持平家數
- 廣度比率 BP
- 20 / 60 日新高新低 metadata
- 漲跌停近似統計與成交量擴散 metadata

若指定日期不是交易日或該日尚無資料，本頁會使用最近可用交易日並在 warnings 顯示 fallback 日期，不會把缺資料補成當日觀測值。

Sector Rotation v1 會從 SQLite `industry_indices` 唯讀推導：

- 領先 / 落後產業
- 5 / 20 日變化
- 輪動強度 BP
- 產業排名 metadata

若指定日期不是交易日或該日尚無產業指數資料，本頁會使用最近可用交易日並在 warnings 顯示 fallback 日期。若某產業歷史不足 21 筆，該產業會被降級提示，不會強制補值。

Watchlist Trigger v1 會從 `WatchlistService` 與 SQLite `technical_indicators` 唯讀推導：

- 個股強度評分 `score_bp`（RSI * 100，值域 0~10000）
- 個股風險警示 `risk_alert`（偏離 RSI > 80 / < 20 或收盤價低於布林通道下軌 `Close < lowerband`）
- 新進候選、強度提升、強度下降等觸發統計

若指定日期不是交易日或該日無指標資料，本頁會採用最近可用交易日，並在 `warnings` 顯示 fallback 日期，且 quality 降級為 `DEGRADED`（在 warnings 中標註 `watchlist_trigger_as_of_fallback:<date>`）。

Portfolio Alert v1 會整合持倉條件監控與 `PortfolioChipService` 籌碼摘要。當持倉條件失效、警告，或個股籌碼風險為 bearish / extreme / risk 時，會列入持倉警示；若籌碼股數資料缺失、估算或部分事件不可用，會在 warnings 顯示 `portfolio_alerts_chip_*`，並將 quality 降級為 `ESTIMATED` 或 `DEGRADED`。`portfolio_alerts_chip_estimated:<stock_code>` 代表券商分點資料中存在 amount-only 觀測列：有買賣金額但缺買賣股數，因此系統用金額與收盤價換算股數，保留為估算品質揭露；要完全消除此 warning，需要上游 `broker_flows` 補齊實際股數，而不是把估算值標成 observed。Portfolio Alert 的來源歸因會顯示每檔警示持倉的來源標籤、condition 狀態、chip risk level 與原因 token。這用於解釋警示來源，不代表自動賣出或調倉。

Relative Strength / Liquidity Ranking v1 會從 SQLite `daily_prices` 唯讀推導 5 / 20 日相對強度與平均成交金額，顯示強勢代碼、弱勢代碼與低流動性代碼。
- **畫面呈現**：每日決策頁會把強勢、弱勢與低流動性代碼以單一 compact list 分行顯示，單類別只顯示前 8 檔並標示剩餘檔數，避免大量股票代碼撐寬主視窗；各 section 的品質狀態以 header badge 顯示。
- **流動性過濾**：當 20 日平均成交金額低於預設的 20,000,000 元時，該股將被列為低流動性代碼。
- **強弱勢判定**：股票的 20 日相對強度必須至少有 21 個有效交易觀測值（當日 + 前 20 日歷史）。若因歷史資料不足（如新上市股票或資料缺失）無法滿足 21 天，該股票將不參與強度排序，並以 `relative_strength_liquidity_skipped_symbols:<count>` 保留覆蓋率 warning；少量 skipped 不會自動拖累整個模組 quality。若使用 fallback 日期、整個模組無可用觀測歷史，或 skipped symbol 比例超過容忍門檻（預設 5%，以 basis points 記錄在 meta），quality 才會降級為 `DEGRADED`；整體無法排序時會在 warnings 中標註 `relative_strength_liquidity_insufficient_history`。

Why Not / 風險提示 v1 會從既有已計算的區塊 DTO 中，推導出可行動的風險提示（prompts），而不在 UI 或此服務內重新計算複雜邏輯：
- **市場風險提示（market_context）**：大盤為 risk-off 或 bear 等狀態時提示「市場風險偏高」，建議降低對個股強勢的解讀信心。
- **流動性提示（liquidity）**：個股被 Relative Strength / Liquidity 判定為低流動性時提示「低流動性」，提醒檢查部位大小。
- **相對弱勢提示（weakness）**：個股在 20 日相對弱勢清單時提示「相對弱勢」，提醒確認反轉條件再行考慮。
- **觀察清單風險觸發提示（watchlist_risk）**：個股觸發 Watchlist 的 risk_alert 時提示「觀察清單風險觸發」。
- **持倉警示提示（portfolio_alert）**：個股位於 Portfolio Alert 警示名單時提示「持倉警示」。
- **基本面診斷提示（fundamental_diagnostic）**：當 Research metadata 或 application service 提供 abnormal fundamental diagnostics 時，會以 `source=fundamental` 顯示營收與獲利背離、一次性收益風險或資料品質缺口。這只是研究風險提示，不代表財報已被重算、推薦分數已被扣分或系統產生買賣建議。
- **品質警告規則**：當來源區塊品質為非 OBSERVED 時，會產生 `risk_prompt_source_quality:...` 警告，並將 Why Not 區塊之 quality 降級為 `DEGRADED`。

#### quality 與 warnings 規則

- `OBSERVED`：當前節點資料完整且已驗證可用。
- `ESTIMATED`：有可補值但非直接觀測值。
- `DEGRADED`：有資料但需降級顯示，需注意風險。
- `MISSING`：節點缺資料，僅保留警示，不能視為可交易依據。

#### 限制與排錯

- 本頁是每日決策摘要，不是自動交易或下單介面。
- Market Breadth v1、Sector Rotation v1、Relative Strength / Liquidity Ranking v1、Watchlist Trigger v1 與 Portfolio Alert v1 已接線，但仍可能因 SQLite 缺資料、資料日期 fallback、歷史不足或籌碼資料缺失而降級顯示 `DEGRADED` 或 `ESTIMATED`。
- Portfolio Alert 僅為持倉摘要警示，未直接改變持倉。
- 基本面診斷提示僅使用已治理 metadata；不會直接讀 raw financial CSV、不會改寫財報、不會輸出目標價、合理價、上漲空間或交易建議。

#### 月營收 availability mapping 維護

月營收 raw CSV 不能自行推定公告日或可得日。若要建立候選 mapping，可先使用 TWSE/TPEX historical dry-run builder：

```powershell
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability_history.py --start-period 2020-01 --end-period 2026-05 --markets twse,tpex
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability_history.py --start-period 2020-01 --end-period 2026-05 --markets twse,tpex --stock-code 2330 --output <candidate-csv>
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability_history.py --start-period 2024-04 --end-period 2024-04 --markets twse --mops-html-dir <mops-html-dir> --output <candidate-csv>
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability_history.py --start-period 2024-04 --end-period 2024-04 --markets twse --stock-code 2330 --mops-static
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability_history.py --start-period 2020-01 --end-period 2024-04 --markets twse,tpex --pit-csv <authorized-pit-export.csv> --pit-source-version <export-version> --output <candidate-csv>
```

未提供 `--output` 時只輸出 summary，不寫檔；指定 `--output` 時只寫候選 CSV，不會改寫正式 `DATA_ROOT/meta_data/monthly_revenue_availability.csv`。候選列使用官方 `出表日期` 作 `announced_date`，並以公告日隔天作保守 `available_date`，避免同日盤中可得性假設。`--mops-html-dir` 僅讀人工保存的官方 MOPS HTML，檔名規則為 `twse_YYYY-MM.html` / `tpex_YYYY-MM.html`；HTML 必須含頁面層級 `出表日期` 與 `公司代號` 表格，否則只輸出 diagnostics，不用 raw CSV 日期補值。`--mops-static` 會走新版 MOPS `/mops/api/redirectToOld` 取得 `mopsov.twse.com.tw/nas/t21/...` historical static report，只作來源驗證；目前該 report 的 `出表日期` 是查詢當日重新出表日，不是歷史原始公告日，因此會被 `as_of_date + 45 days` 合理揭露窗口擋下。

自 2026-08-06 起，任何要進入正式 availability mapping 的新列都必須符合 `formal-availability.v2`：`evidence_class=official_announcement`、明確 `announced_date`、SHA-256 `source_hash`，以及連續的 `revision`／`parent_revision`。目前正式 builder 對有官方公告證據的列會自動輸出這些欄位；`first_observed`、`local_first_seen`、本機 observation 與 `manual.available_date_mapping` 只可作 shadow／研究候選，validator 會 fail-closed。為維持既有日常資料可用，只有 `twse.monthly_revenue_announcement / twse-openapi-t187ap05-l-2026-07-14` 與 `tpex.monthly_revenue_announcement / tpex-openapi-mopsfin-t187ap05-o-2026-07-14` 這兩組已 materialize 的 2026-06 mapping 可走精確 legacy compatibility；它不是未來新資料的範本。

若取得授權 point-in-time 月營收公告日匯出檔，可使用 `--pit-csv`。匯出檔必須至少有股票代號、資料年月與公告日欄位；支援 `stock_code` / `公司代號`、`period` / `資料年月`、`announced_date` / `公告日` / `出表日期` 等欄名。`--pit-source-version` 必須非空，並會原樣寫入候選 mapping 的 `source_version`。PIT 匯入來源目前治理為 `tej.monthly_revenue_announcement_pit`；此路徑仍只產生 candidate CSV，不會寫正式 mapping，也不會回填 SQLite。

舊版 TWSE OpenAPI 候選產生器仍可用於單一最新月來源測試：

```powershell
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability.py --fetch-date 2026-06-16
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability.py --source-json <twse-json> --output <candidate-csv> --fetch-date 2026-06-16
```

寫入正式 `DATA_ROOT/meta_data/monthly_revenue_availability.csv` 前，必須先以 `scripts\validate_monthly_revenue_availability.py --path <candidate-csv>` 驗證 v2 provenance、PIT 日期與 revision chain，並取得人工確認；此工具不會自動改寫正式 mapping、raw CSV 或 SQLite。

若要把已驗證候選安全地併入既有 mapping，可先預覽 merge plan：

```powershell
.\.venv\Scripts\python.exe scripts\apply_monthly_revenue_availability_candidate.py --candidate <candidate-csv> --target D:\Min\Python\Project\FA_Data\meta_data\monthly_revenue_availability.csv
```

此 plan 會保留既有列、以 `(stock_code, period)` 做 natural-key 去重；相同內容視為 idempotent，內容不同則以 conflict 停止，不會猜測覆蓋。只有人工確認後才可套用：

```powershell
.\.venv\Scripts\python.exe scripts\apply_monthly_revenue_availability_candidate.py --candidate <candidate-csv> --target D:\Min\Python\Project\FA_Data\meta_data\monthly_revenue_availability.csv --apply --confirm apply-monthly-revenue-availability
```

套用前會將既有 mapping 備份到 `--backup-dir`（預設為 target 同層 `backup`），並在 target 同一目錄先完成 UTF-8 CSV 暫存檔後 atomic replace；candidate、raw CSV 與 SQLite 不會由此 CLI 改寫。套用 mapping 後，仍須另外對同一 candidate 與 MOPS snapshot 執行 `backfill_monthly_revenue_fundamentals.py --dry-run`，確認 0 diagnostics，再以 `--confirm apply-monthly-revenue-backfill` 明確回填 SQLite。兩個 apply 必須分開確認，避免 availability 日期與數值資料只更新一半時被誤認為完成。

截至 2026-06-16，TWSE 上市 endpoint `/opendata/t187ap05_L` 與 TPEX 上櫃 endpoint `/openapi/v1/mopsfin_t187ap05_O` 均可提供最新月 `出表日期`；樣本為 `2330` / `9935` 的 `2026-05` 公告日 `2026-06-15`，以及 `3207` 的 `2026-05` 公告日 `2026-06-16`。這些 OpenAPI 目前未提供歷史 period query；MOPS historical static report 可透過新版 API 取得，且可看到 `113/04` 的 `2330`、`9935`、`3207` rows，但其 `出表日期` 是查詢當日，不能視為歷史公告日。正式 raw 月營收目前只到 `2024-04`，與最新月來源無交集，因此 `2020-01..2026-05` dry-run 產生 0 candidate rows。歷史公告日仍需可追溯的原始公告日批次來源或受控人工 mapping。

#### 月營收 normalized backfill

正式 DB 已有 `fundamental_monthly_revenues` schema，但回填必須先通過 availability mapping。可先執行 dry-run：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_monthly_revenue_fundamentals.py --dry-run
```

dry-run 只輸出 plan，不寫入 SQLite。若正式 `DATA_ROOT/meta_data/monthly_revenue_availability.csv` 不存在，結果會是 `ready_for_apply=false` 並輸出 `fundamental_availability.mapping_file_missing`，不會讀 raw 月營收 rows，也不會產生 normalized records。

MOPS snapshot 可以作月營收**數值**主來源，但不能自行證明歷史公告／可得時間。只有每一筆數值都能與 v2 或上述受限 legacy 正式 availability mapping 完整對應時，才可用 `--mops-snapshot-file` 做 dry-run；不需先轉成 `financial_data/*_monthly_revenue.csv`：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_monthly_revenue_fundamentals.py --dry-run --mops-snapshot-file <mops-snapshot.csv> --availability-file <formal-availability-v2.csv> --source-version <snapshot-version>
```

此路徑會把 normalized record 的 `source` 保留為 `mops.monthly_revenue_static_snapshot`，但其正式可得性一律以獨立 mapping 為準。2026-06-16 的 1,848 筆 2026-05 MOPS first-seen 回填是歷史資料：原始 DB row 保留、不可刪除，但因沒有正式 mapping，現在已被 Recommendation／Fundamental provider 的 live gate 隔離，不能作為正式 PIT 特徵。當前可正式使用的是 1,832 筆 2026-06 值，它們與 TWSE／TPEX 官方公告 mapping 的日期完整對應。

正式回填必須在 mapping 通過驗證後，由人工確認再執行：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_monthly_revenue_fundamentals.py --apply --confirm apply-monthly-revenue-backfill
```

正式 apply 會先備份 DB；缺少 `--confirm apply-monthly-revenue-backfill` 時會拒絕執行。回填工具只寫入 `fundamental_monthly_revenues`，不會修改 raw CSV、availability mapping 或既有核心表。apply 後必須以正式 provider／推薦 filter 再確認 row 與 mapping 的 `stock_code`、`period`、`as_of_date`、`announced_date`、`available_date` 完全一致；只標為 `quality=observed` 不足以取得正式讀取資格。若指定 `--db-file` 但未指定 `--backup-dir`，備份會放在該 DB 同層的 `backup` 目錄；未指定 `--db-file` 時才沿用正式 `DATA_ROOT/meta_data/backup`，明確的 `--backup-dir` 優先。

#### 更新頁月營收功能

主 UI 的「資料更新」頁新增「月營收」分頁。此分頁提供三個欄位：

- `MOPS 月營收快照檔`：從 MOPS snapshot CSV 讀取各公司每月營收值。
- `正式可得日對照檔`：指定 `monthly_revenue_availability.csv`，用來決定每筆月營收從哪一天起可被因子層讀取。
- `本次寫入版本名稱`：寫入資料表的版本名稱，用於日後追溯與比對。

此分頁提供兩個操作：

- `先檢查，不寫入`：只檢查可回填筆數與診斷結果，不寫入正式資料庫。
- `確認後寫入月營收`：先跳出確認視窗，再建立 DB 備份並寫入 `fundamental_monthly_revenues`。此按鈕不抓取新 MOPS HTML、不修改 raw CSV，也不更新 availability mapping。

更新頁目前只負責 SQLite backfill；若已有新的官方 availability candidate，先在外部執行上述 merge CLI，完成人工檢查與 mapping 備份後，再重新載入此分頁做 dry-run。UI 不會把「候選可用」誤顯示成「已套用」。

若要補抓最新月份，先以 MOPS snapshot CLI 取得數值，再用 TWSE／TPEx historical availability builder 取得官方 `出表日期` 候選；兩者交集才可進 backfill dry-run。兩條來源缺一時，更新頁只應顯示候選／缺口，不可用 snapshot 查詢日或本機檔案日期推定公告日。

#### 月營收因子檢視

若要確認正式 SQLite 月營收是否已進入基本面 factor layer，可使用唯讀檢視 CLI：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_fundamental_factors.py --all-monthly-revenue-stocks --decision-date 2026-06-30 --diagnostic-limit 8 --stock-summary-limit 12
```

此工具只讀取 `fundamental_monthly_revenues`、`fundamental_statement_items` 與 `fundamental_valuation_metrics`，透過 `FundamentalFactorService` 產生當下可見的 factor records / diagnostics，不寫 SQLite、不修改 CSV，也不接 `ScoringEngine`。2026-06-16 單月營收初版檢查結果為：股票數 1,848、factor records 4,464、diagnostics 3,696；其中月營收已產生 `fundamental.revenue_3m_trend` 1,848 筆與 `fundamental.revenue_new_high` 1,848 筆。2026-06-17 retroactive baseline 補齊後，Revenue Factor Pack 可產生 YoY 1,843 筆、MoM 1,842 筆、3M trend 1,848 筆與 new high 1,848 筆，剩餘 diagnostics 11 筆。這代表 Month 5 已能把 SQLite 月營收送到 Revenue Factor Pack；但 historical baseline 多數 quality 為 `degraded`，不可解讀為官方歷史 point-in-time 公告日，也不可直接接入 `ScoringEngine`。

#### 月營收歷史 baseline 候選

MOPS snapshot 可以用來補「從導入日之後才可使用」的歷史 baseline。此路徑不是官方歷史公告日 mapping；產出的 source 固定為 `manual.retroactive_baseline_mapping`，`announced_date` 留空，`available_date` 設為人工指定的導入可用日，品質會是 `degraded`。因此它可讓 2026-06-17 之後的決策日計算 YoY / MoM baseline，但不得用於 2026-06-17 以前的歷史回測。

建議先產生候選檔，不覆蓋正式 mapping：

```powershell
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_retroactive_baseline_mapping.py --snapshot-file D:\Min\Python\Project\FA_Data\output\monthly_revenue_mops_snapshots\mops_monthly_revenue_snapshot_2014-04_2026-05_2026-06-16.csv --start-period 2014-04 --end-period 2026-04 --available-date 2026-06-17 --source-version mops-retroactive-baseline-2014-04_2026-04-2026-06-17 --output D:\Min\Python\Project\FA_Data\output\monthly_revenue_availability_candidates\mops_retroactive_baseline_monthly_revenue_availability_2014-04_2026-04_2026-06-17.csv
.\.venv\Scripts\python.exe scripts\validate_monthly_revenue_availability.py --path D:\Min\Python\Project\FA_Data\output\monthly_revenue_availability_candidates\mops_retroactive_baseline_monthly_revenue_availability_2014-04_2026-04_2026-06-17.csv
.\.venv\Scripts\python.exe scripts\backfill_monthly_revenue_fundamentals.py --dry-run --mops-snapshot-file D:\Min\Python\Project\FA_Data\output\monthly_revenue_mops_snapshots\mops_monthly_revenue_snapshot_2014-04_2026-05_2026-06-16.csv --availability-file D:\Min\Python\Project\FA_Data\output\monthly_revenue_availability_candidates\mops_retroactive_baseline_monthly_revenue_availability_2014-04_2026-04_2026-06-17.csv --source-version mops-static-snapshot-monthly-revenue-2026-06-16
```

2026-06-16 dry-run 結果：candidate 242,651 筆、validator accepted 242,651 筆、backfill normalized 242,651 筆、diagnostics 0。依人工確認正式 apply 後，`fundamental_monthly_revenues` 共有 244,499 筆，期間 `2014-04..2026-05`，股票數 1,848、period 數 146、0 duplicate；品質分布為 242,651 筆 `degraded` historical baseline 與 1,848 筆 `observed` 2026-05 records，DB 備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_mops_monthly_revenue_backfill_20260616_224147.db`。factor inspection 顯示 `fundamental.revenue_yoy` 1,843 筆、`fundamental.revenue_mom` 1,842 筆、`fundamental.revenue_3m_trend` 1,848 筆、`fundamental.revenue_new_high` 1,848 筆，剩餘 diagnostics 11 筆主要為 baseline missing / zero。

#### 季度財報 available date gate

季度財報 raw CSV 不能直接進入因子層；必須先有 `fundamental_statement_availability.csv` 作 `available_date` gate。正式預設路徑為 `DATA_ROOT/meta_data/fundamental_statement_availability.csv`，欄位為 `stock_code`、`statement_type`、`period`、`as_of_date`、`announced_date`、`available_date`、`source`、`source_version`。

MOPS 公告快易查現在可作季報官方發布時間的 research-only 主線。它只讀查詢 `F26` 資產負債表、`F27` 綜合損益表、`F28` 現金流量表與 `F29` 權益變動表，保存「公告日期時間」至秒及 `+08:00` 時區；不使用 `M31`，因為 M31 同時包含「董事會預計召開日期」與「董事會通過財報」，不能一律視為財報已發布。執行範例：

MOPS 公告時間 artifact 只證明 availability，不能自行衍生 ROE、毛利率、營益率、負債比或 EPS。任何聲稱 numeric PIT 的 research candidate 必須以獨立、唯讀保存的原始數值財報 artifact 為來源，並同時保存 raw-numeric artifact、MOPS availability artifact、canonical dataset manifest/dataset 的 SHA-256 lineage；每列要有 raw numeric row 與 availability event 的 SHA-256、帶時區 publication timestamp、次一曆日的 `available_date`，且數值只用整數 minor units／basis points。validator 只會標為 `research_candidate`，不會賦予 official、source acceptance、formal OOS 或 production eligibility。內建常數、sample/default ratio、固定更正履歷、或將寫入前的 digest 塞回同一份 JSON 的輸出，一律 fail-closed。

若需要建立可核驗的 bounded numeric PIT candidate，可使用 `scripts/build_mops_numeric_pit_candidate.py`。它從 MOPS `t163sb06` 保存季度數值比率 raw HTML，再從 `t57sb01` 保存同一公司／季度的 IFRSs 合併財報 listing，以 listing 上的原始上傳時間和更(補)正欄建立 publication/revision lineage；所有檔案、各層 SHA-256 與 candidate 都會寫入唯一 TEMP run directory。範例：

```powershell
.\.venv\Scripts\python.exe scripts\build_mops_numeric_pit_candidate.py `
  --stock-code 2330 --roc-year 114 --season 1 --market sii `
  --output-root C:\Temp\technical_analysis_development_output `
  --run-id dev71-mops-numeric-pit-2330-2025q1-r1 `
  --canonical-manifest C:\Temp\technical_analysis_development_output\generations\terra-v0-canonical-2025-dev-20260714\manifest.json `
  --canonical-dataset C:\Temp\technical_analysis_development_output\generations\terra-v0-canonical-2025-dev-20260714\dataset.json
```

`--run-id` 不可重用；工具會在同一目錄保存 raw HTML、numeric source、availability source、candidate 與 run manifest，並在發布 candidate 前重新執行 validator。MOPS listing 若顯示更(補)正，不會猜測 revision，而是停止要求另行建立具比較基準的 correction lineage。此工具可計算 canonical dataset 的 PIT-eligible coverage；coverage 有限時只代表 source artifact 已取得，不能當作 feature 已 materialize、ML 可訓練、source accepted 或 Formal evidence。

#### MOPS numeric PIT aggregate、bounded resume 與 materialization gate

多份 candidate 只能在 TEMP／development root 內以 `scripts/aggregate_mops_numeric_pit_candidates.py` 聚合；aggregate validator 會重新核對四層 source identity、canonical/candidate/manifest SHA-256、candidate identity 唯一性、`0 <= eligible <= matching <= denominator` 與固定 `8,000 bp` coverage policy。`--minimum-coverage-bp` 不得用來降低門檻，輸出採 staging 後 atomic rename，不能寫入正式 `DATA_ROOT`、SQLite 或 Formal DB。

`scripts/acquire_mops_numeric_pit_batch.py` 是前景 bounded 工具，`--max-items` 必填；既有 `(stock_code, period)` 只有在 batch manifest 明確提供且完全相符的 `candidate_sha256` 時才可 skip。缺 hash、hash 衝突、既有 bundle 損壞或 output path 不在 TEMP root 時，會在 fetch 前 fail-closed；不會自動建立 revision，也不啟用 scheduler、background job 或 retry loop。

`check_mops_materialization_readiness` 與 `materialize_development_feature_overlay` 只接受有效 aggregate、具名 Source Owner／Reviewer dossier，以及 append-only decision registry 的 `accepted`／`limited` applying revision；revision 的 source、evidence IDs、decision timestamp、rollback reference、allowed use case 與 dossier 必須逐項相符。沒有 registry revision、coverage 不足、license 未核准或 lineage 不一致時不得 materialize。即使 gate 通過，輸出仍固定 `research_only=true`、`formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`downstream_eligibility=none`，不得進入 scoring、Recommendation、Portfolio、Exit、training 或正式資料庫。

```powershell
.\.venv\Scripts\python.exe scripts\fetch_mops_statement_availability.py `
  --start-date 2026-07-27 `
  --end-date 2026-07-28 `
  --query-window-days 7 `
  --query-retries 2 `
  --output-root C:\Temp\technical_analysis_development_output\mops-statement-availability
```

`--output-root` 必須位於正式 `DATA_ROOT` 與 repo 之外；整體日期範圍最多 31 天，`--query-window-days` 可將每個 market/item 拆成 1–31 天的連續窗口。MOPS 單一 query 回傳達 1000 筆時會拒絕該窗口；應縮小此參數後重跑，artifact manifest 會保留每個實際 query window 與 response hash，避免把分段查詢誤看成同一個未分窗請求。`--query-retries` 最多允許 3 次額外重試，只重試被標為 error 的 query；成功後 manifest 會保留 `attempt_count` 與前次 `retry_error_codes`，最終失敗仍維持 `degraded`，不會把錯誤轉成官方無資料。輸出包含完整 JSON artifact 與 `fundamental-statement-availability.csv` 候選 mapping；JSON 保留官方 `announcement_at`，CSV 因既有 consumer 只有 date grain，固定以公告次一曆日作 `available_date`，避免同日盤中 look-ahead。具官方 timestamp 的延後申報採實際公告日，不再套用 120 天推定窗口。此 CLI 不寫正式 availability mapping／SQLite、不執行每日更新或排程、不提供 Formal credit；要接到正式資料仍須另一個明確 apply 決議與備份流程。

CLI 的 `--help` 與 JSON summary 會在可重設的 Windows stdout/stderr 上先採 UTF-8；若由 pytest 或其他 host 管理的 stream 不允許重設，會保留原 stream 繼續執行，不因繁體中文說明而中止。舊主控台若仍顯示亂碼，可在執行前設定 `$env:PYTHONIOENCODING='utf-8'`。

查詢品質摘要會把三種結果分開保存：`successful_query_count` 是有正常回應的查詢、`official_no_data_query_count` 是官方以 `status=fail` 回覆且沒有資料列、`failed_query_count` 才是 timeout／網路／解析錯誤。官方無資料不會被誤報成 outage，但仍會留在 `query_manifest`，供 owner 判斷市場範圍是否完整；若有真正錯誤，整體狀態為 `degraded`，不得以部分列數宣稱完整 coverage。輸入若把 `status=fail` 與資料列混用，builder 會 fail-closed。

歷史 EZSearch 回應可能出現欄位漂移（例如舊列缺 `CTIME`）。builder 會逐列將無法解析的 row 放入 bounded `invalid_event_samples`，以 `invalid_event_error_counts` 保存完整錯誤計數，並保留同一 query 回應內的有效列；只要 `invalid_event_count>0`，artifact 與 CLI 狀態就會是 `degraded`、return code=`3`，不可把部分成功當成完整 coverage。這種 quarantine 只保留可稽核摘要，不會把 malformed row 轉成 availability evidence。

若目前只要建立「導入日後可用」的歷史 baseline candidate，可先產生候選檔：

```powershell
.\.venv\Scripts\python.exe scripts\build_statement_retroactive_baseline_mapping.py --raw-dir D:\Min\Python\Project\FA_Data\financial_data --available-date 2026-06-17 --source-version statement-retroactive-baseline-2026-06-17 --output D:\Min\Python\Project\FA_Data\output\statement_availability_candidates\statement_retroactive_baseline_availability_2026-06-17.csv
.\.venv\Scripts\python.exe scripts\validate_statement_availability.py --path D:\Min\Python\Project\FA_Data\output\statement_availability_candidates\statement_retroactive_baseline_availability_2026-06-17.csv
.\.venv\Scripts\python.exe scripts\backfill_fundamental_statement_items.py --dry-run --raw-dir D:\Min\Python\Project\FA_Data\financial_data --availability-file D:\Min\Python\Project\FA_Data\output\statement_availability_candidates\statement_retroactive_baseline_availability_2026-06-17.csv --source-version financial-data-statements-2026-06-17
```

2026-06-16 dry-run 結果：statement availability candidate 170,425 筆、validator accepted 170,425 筆、diagnostics 0；statement item backfill normalized 1,645,555 筆、diagnostics 0。依人工確認正式 apply 後，`fundamental_statement_items` 期間為 `2014-Q2..2024-Q1`、股票數 1,567、period 數 40、0 duplicate，quality 全為 `degraded`，DB 備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_statement_items_backfill_20260617_004912.db`。此資料已可作導入日後 EPS、毛利率、營益率、ROE、業外損益 factor 的 baseline foundation；factor layer 只輸出 records / diagnostics，不接 `ScoringEngine`。

`backfill_fundamental_statement_items.py --dry-run` 現在會將診斷輸出限制為前 20 筆，同時保留 `diagnostics`、`diagnostic_counts` 與 `missing_availability_count` 的完整數字；任何一筆缺 `available_date` 都會讓 `ready_for_apply=false`。這避免大量歷史 raw row 把 console 淹沒，也不會因截短顯示而誤放行 apply。只有 plan 的 `diagnostic_count=0`、`missing_availability_count=0` 且有 normalized records 時，才可進入既有明確 confirmation、備份與 apply 流程。dry-run 若已明確提供 `--raw-dir`／`--availability-file`，不會為了取得不使用的 DB／backup 預設值而初始化正式 `TWStockConfig`。

不同月份或不同官方窗口可重複傳入 `--availability-file`，例如：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_fundamental_statement_items.py --dry-run `
  --raw-dir D:\Min\Python\Project\FA_Data\financial_data `
  --availability-file C:\Temp\mops_2024_03.csv `
  --availability-file C:\Temp\mops_2024_04.csv `
  --availability-file C:\Temp\mops_2024_05.csv
```

讀取器會忽略重複的完整列；若相同 `(stock_code, statement_type, period)` 出現不同公告／provenance，會保留 revision-chain 診斷並拒絕 apply，不猜測哪個窗口正確。這讓多路徑、分月補件能累積 coverage，同時維持正式 mapping／SQLite 的 fail-closed 邊界。

若要先確認整個 raw universe 能否落到既有 schema，可把導入日後的 `statement_retroactive_baseline_availability_2026-06-17.csv` 與 MOPS candidates 一起 dry-run。這可能得到 `ready_for_apply=true`，但必須檢查 quality 分布：baseline 仍是 `degraded`、不能作正式歷史 PIT；只有具官方公告時間且經 owner／reviewer 核准的 rows 才能進入正式 availability mapping。此 hybrid dry-run 不會自動寫入 SQLite，也不會授予 source acceptance 或 Formal credit。

歷史窗口若收到官方 `status=fail` 且零資料列，會計入 `official_no_data_query_count`；這和 timeout、network error、schema drift 的 `failed_query_count`／`invalid_event_count` 不同。官方無資料不可直接補成 baseline，也不可把其他月份的成功列宣稱為全期間 coverage。

季度財報 factor layer 已可用唯讀方式檢查：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_fundamental_factors.py --all-monthly-revenue-stocks --decision-date 2026-06-30 --diagnostic-limit 12 --stock-summary-limit 12
```

2026-06-17 正式 DB inspection 結果：總 factor records 14,840、diagnostics 812；statement factors 為 `fundamental.statement.eps` 1,411 筆、`fundamental.statement.gross_margin` 1,368 筆、`fundamental.statement.operating_margin` 1,374 筆、`fundamental.statement.roe` 1,277 筆、`fundamental.statement.non_operating_income_ratio` 1,261 筆。缺 statement rows、缺必要科目或分母為 0 時只輸出 diagnostics，不輸出中性訊號，不接 `ScoringEngine`。

PB / PS 目前只做來源政策檢查：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_valuation_source_policy.py
```

Month 5 後 P/E、P/B、P/S 都具備 presentation policy。P/B 與 P/S 只接受 governed external observations 或後續明確 backfill records；系統不會在內部用不完整財報推導 book value、share count、market cap 或 TTM sales，也不會把估值指標接進 `ScoringEngine`。

#### Month 5 closeout 判讀

Month 5 Fundamental Layer v1 的完成定義是「基本面資料已能以受治理、可診斷、可追溯的方式進入 factor records / diagnostics」，不是把基本面自動納入推薦分數。使用者在 Daily Decision Desk、Research metadata 或 factor inspection 看到 fundamental diagnostics 時，應將其視為研究風險提示與資料品質揭露；系統不會因此自動買賣、調倉、改寫財報或調整 `ScoringEngine` 分數。下一階段 Month 6 才會討論策略生命週期與 Portfolio feedback 如何使用這些 evidence。

#### 公司清單 / 產業 mapping 更新

`meta_data/companies.csv` 可用官方 TWSE/TPEX 公司基本資料更新。預設 dry-run 不寫檔：

```powershell
.\.venv\Scripts\python.exe scripts\update_company_registry.py --dry-run
```

正式寫入必須人工確認：

```powershell
.\.venv\Scripts\python.exe scripts\update_company_registry.py --apply --confirm apply-company-registry
```

正式 apply 會先備份既有 `companies.csv`，只更新公司 registry CSV，不修改 SQLite、daily price 或 raw financial CSV。2026-06-16 已以官方 TWSE/TPEX 來源正式更新：輸出 2,326 筆、0 diagnostics、無重複 `stock_id`，備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/companies_company_registry_20260616_031111.csv`。抽查 `3207` 耀勝為 `電子零組件業 / tpex`，`9935` 慶豐富為 `居家生活 / twse`。

CLI 會先讀取官方 JSON OpenAPI；若 JSON endpoint 暫時不可用（例如 HTTP 520），會自動切換至同一官方資料平台的 CSV 來源。JSON／CSV 都失敗時，CLI 會輸出 `status=blocked`、`reason=official_company_registry_source_unavailable` 與 `writes_allowed=false`，return non-zero 且保留既有 `companies.csv`；不得用部分市場回應或舊快照覆寫完整 registry。來源恢復後可重新執行 dry-run，再依既有備份／確認契約 apply。

注意：`companies.csv` 是公司與產業 registry，不代表 `daily_prices` 已具備該股票行情。TPEX daily price 已納入日常市場日價管線；若歷史 TPEX 股票缺舊日價，需由每日股價區間補齊、快速 / 安全更新或背景補齊流程處理，不應用 company registry 或 fundamental layer 假造價格列。

#### TPEX daily price 日常更新與歷史 dry-run

日常快速 / 安全更新會在 TWSE 每日股價後抓取 TPEX official daily close quotes，保存到 `DATA_ROOT/daily_price_tpex/YYYYMMDD.csv`，並在 SQLite 同步時寫入 `DATA_ROOT/sqlite/twstock.db` 的 `daily_prices`。這是市場資料層更新，不修改 `companies.csv`、raw financial CSV、fundamental tables、技術指標算法或推薦分數。

若上櫃股票存在於 `companies.csv` 但缺歷史 `daily_prices`，先使用歷史 dry-run plan：

```powershell
.\.venv\Scripts\python.exe scripts\plan_tpex_daily_price_history_backfill.py --start-date 2026-01-01 --end-date 2026-06-16
```

dry-run plan 只讀官方來源或指定 source JSON、SQLite 既有資料，輸出日期範圍、每日來源筆數、已存在筆數、新增候選筆數、失敗日期與估計耗時，不寫正式 DB。正式歷史回補需另行人工確認。

單日受控補寫工具仍保留給已確認日期使用。預設先 dry-run：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_tpex_daily_prices.py --date 2026-06-16 --dry-run
```

dry-run 只讀官方 TPEX daily close quotes 與 SQLite，顯示 `ready_for_apply`、`insert_count`、`existing_count` 與 diagnostics，不寫入資料。正式寫入必須先取得人工確認，再執行：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_tpex_daily_prices.py --date 2026-06-16 --apply --confirm apply-tpex-daily-price-backfill
```

正式 apply 會先備份 DB；缺少 `--confirm apply-tpex-daily-price-backfill` 時會拒絕執行。此 workflow 只寫入 `daily_prices`，不會修改 `companies.csv`、raw financial CSV、fundamental tables、技術指標或推薦分數。批次模式只處理指定交易日、四碼普通股且收盤價為正數的 rows；債券、權證、ETF 或停牌無價 rows 會被跳過。

2026-06-16 已對正式 DB 執行一次：dry-run 顯示可新增 877 筆、0 diagnostics；正式 apply 後備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_tpex_daily_price_backfill_20260616_034627.db`。驗證結果：`daily_prices` 的 `20260616` 有 877 筆四碼上櫃日價、0 duplicate `(證券代號, 日期)` keys；`3207` 耀勝已有 `20260616` 日價，`9935` 慶豐富既有日價仍保留。

#### 估值 metrics backfill

正式 DB 已有 `fundamental_valuation_metrics` schema。P/E v1 可由 SQLite `daily_prices.本益比` 與 `meta_data/companies.csv` 產業 mapping 建立受治理 valuation records，並計算同產業整數基點分位。預設只執行 dry-run：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_valuation_metrics.py --dry-run
.\.venv\Scripts\python.exe scripts\backfill_valuation_metrics.py --as-of-date 2026-06-15 --dry-run
```

未指定 `--as-of-date` 時，工具會選擇 `daily_prices` 中最新有 P/E 的交易日。dry-run 只輸出 plan，不寫入 SQLite；P/E 非正數、無法解析或缺產業 mapping 的 rows 會列為 diagnostics 並跳過。同產業只有單一樣本時會保留 record，但 `industry_percentile_bp` 為空且 quality 降級，後續估值 adapter 只會輸出 diagnostics。

正式寫入必須先取得人工確認，再執行：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_valuation_metrics.py --apply --confirm apply-valuation-metrics-backfill
```

正式 apply 會先備份 DB；缺少 `--confirm apply-valuation-metrics-backfill` 時會拒絕執行。此 workflow 只寫入 `fundamental_valuation_metrics`，不會修改 raw CSV、`companies.csv` 或既有核心表。若指定 `--db-file` 但未指定 `--backup-dir`，備份會放在該 DB 同層的 `backup` 目錄；未指定 `--db-file` 時才沿用正式 `DATA_ROOT/meta_data/backup`，明確的 `--backup-dir` 優先。2026-06-16 更新官方 `companies.csv` 後再次執行正式 apply：最新 P/E 日為 `2026-06-15`，來源 1,090 筆，831 筆可正規化，259 筆 diagnostics；正式表 count 為 831，0 duplicate primary keys，quality 全為 `observed`，DB 備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_valuation_metrics_backfill_20260616_031146.db`。

## 9. Research Lab / 策略回測

### 9.1 五種實驗模式

| 模式 | 主要用途 |
|---|---|
| 單股回測 | 驗證一檔股票套用策略後的交易表現。 |
| 批次股票回測 | 比較同一策略在多檔候選股票上的差異。 |
| 固定組合回測 | 研究固定股票清單的組合表現；目前 Registry 保存採 per-stock run，並以固定組合 metadata 區分來源。 |
| 推薦系統回放 | 回放推薦配置與名單。 |
| 策略研究 | 比較策略模板、參數、最佳化與驗證結果。 |

模式下方會用「適合 / 輸入來源」說明目前模式該用在哪種研究情境，以及主要輸入來自股票代號、候選池、固定清單、推薦結果或策略模板。

Research Lab 左側設定面板預設保留足夠寬度給長下拉選項與表單欄位，右側結果區吃剩餘空間；一般 1400px 預設主視窗不應需要手動左右拖動才看得到完整「執行價格」等設定列。

### 9.2 基本設定

1. 選擇策略來源或載入 Preset。
2. 選擇單股或選股清單。
3. 設定開始與結束日期。
4. 設定初始資金、手續費與滑價。
5. 執行價格建議使用 `next_open`；`close` 是同根 K 收盤成交假設，必須清楚揭露。

開始日期與結束日期可開啟日曆選取；開始日期預設為今天往前一年，結束日期預設為今天。日曆開啟時會先定位到今天，方便從目前日期往前選擇研究區間。

### 9.3 停損、停利與部位

- 百分比模式：使用固定停損停利百分比。
- ATR 倍數模式：依市場波動調整距離。
- 全倉：可用資金集中於目前部位。
- 固定金額：每次使用指定金額。
- 風險百分比：依風險比例與 ATR 決定部位。

部位管理包括最大持倉數、等權/分數加權/波動調整、加碼、重新進場與冷卻期。

台股整股模擬以 1000 股為單位。高價股若資金不足一張，可能產生 0 交易。

最大持倉數設為 `0` 代表無限制；設為 `1` 代表最多同時只持有 1 檔。這是部位數量限制，不是買賣訊號來源。

### 9.4 市場限制

- 漲跌停限制
- 成交量限制
- 最大參與率

如果訊號很多但交易為 0，先檢查資金、整股限制、成交量與參與率，不要直接判定策略沒有訊號。

### 9.5 固定門檻與百分位排名

- 「固定門檻」使用固定買賣分數。
- 「百分位排名」使用 T-1 以前的 expanding 歷史分布，暖機需要 60 個有效觀測值。
- 暖機完成前不應產生 quantile 交易訊號。
- 比較兩模式時必須使用相同資料、成本、成交假設與期間。

### 9.6 參數最佳化

1. 選擇目標：Sharpe、年化報酬或 CAGR-MDD。
2. 設定工作線程數。範圍為 1 到 8，預設使用保守上限；目前是 ThreadPool，不是 ProcessPool 多進程。
3. 對要掃描的參數設定固定值或範圍。
4. 執行參數掃描。大型掃描會先顯示預估組合數、worker 數、資料來源與取消提示，確認後才開始。
5. 在「最佳化 / 驗證」查看結果。
6. 選取結果後按「套用選中參數」。

資料與效能邊界：單股最佳化會在執行前預載該股資料一次；`config.use_sqlite=True` 時優先讀 SQLite，缺資料或讀取失敗才 fallback CSV。Optimizer 會用 bounded in-flight futures 分批提交任務，避免一次把所有參數組合送進 ThreadPool。

取消流程：按取消後系統會停止提交新組合，並清理已啟動子任務；清理期間 UI 會顯示「已送出取消」。若組合數很大，已啟動的少量子任務仍需要安全結束才會完全解鎖。

最佳化結果是 In-Sample 候選，不能直接視為可靠策略。

### 9.7 Walk-forward

- Train-Test Split：單次訓練/測試切分。
- Walk-forward：以訓練月數、測試月數與步進月份滾動驗證。

結果摘要會顯示樣本可靠度提示。Train-Test 會列出訓練集交易數與 OOS 交易數；Walk-forward 會列出 Fold 數、OOS 交易數與測試期正向 Sharpe 覆蓋率。Fold 少於 3、OOS 交易數不足，或出現勝率 100% 但最大回撤偏大的不直覺組合時，系統會提示「樣本不足，不宜作正式策略判斷」。此提示只使用該次驗證已產生的結果 metadata，不重新抓取目前資料，也不改變績效計算。

至少檢查：

- OOS 報酬是否穩定
- 最大回撤是否惡化
- 交易次數是否足夠
- 不同窗口是否只靠單一期間獲利
- fixed / quantile 是否用完全相同條件

本專案 2026-06-14 基準實證使用 10 檔股票、每檔 8 個 OOS fold；fixed 57 筆、quantile 79 筆交易均通過 20 筆最低樣本 Gate，Regime coverage 為 100%。結果未顯示 quantile 的平均 OOS Sharpe 優於 fixed，詳見 `docs/06_qa/WALK_FORWARD_COMPARISON_REPORT.md`。

### 9.8 執行、取消、保存與升級

- 「執行實驗」：開始目前模式。
- 「取消執行」：合作式取消；已開始的單檔工作可能安全收尾。
- 「保存結果」：將單股回測、批次回測單檔結果、固定組合 per-stock 結果或推薦回放結果保存到 Research Run Registry；系統會保存參數快照、資料 fingerprint、成本、成交假設、績效摘要、factor snapshot / contribution metadata、equity curve 與 trades。單股、批次與固定組合 per-stock 結果的 factor metadata 來自該次回測已產生的 score/factor records，不會在保存時重算分數或重新抓取資料。
- 「升級為策略版本」：新版 Gate 必須讀取 Research Run Registry，不得只靠單次 summary；run 需 committed / valid、未封存、未升級、具備可還原參數合約版本，且通過最低 validation gate 與 Month 6 lifecycle gate。Lifecycle gate 會檢查交易次數、總報酬、Sharpe、最大回撤、勝率、benchmark excess return、factor quality 與 regime compatibility。成功升級後，若 lifecycle evidence repository 已啟用，系統會保存 applied evidence，包含 decision snapshot、gate reasons 與 version id。

「保存結果」與「升級為策略版本」按鈕會依目前是否已有可保存結果、是否已保存、validation 是否允許而啟用；停用時 tooltip 會說明原因。保存成功訊息會顯示 Registry run ID 與下一步。

保存、刪除或升級成功後，Research Lab 會刷新歷史列表、圖表選單與 Registry 比較面板，並在進度文字顯示剛保存的 run ID 或升級後的策略版本 ID。

Month 6 lifecycle gate 的預設最低交易數為 20 筆，且缺 benchmark excess return 或 factor snapshot 時會保守降級，不允許只靠單次高報酬升級策略版本。通過 Gate 不代表已完成實盤驗證。Demote / retire 判斷會先以 proposed evidence 保存，供人工 review；系統不會自動刪除策略版本或改寫歷史 run。

保存安全限制：

- 只有目前成功完成且尚未被新一輪執行取代的結果可以保存。
- 開始新一輪回測或推薦回放後，舊 pending result 會被視為 stale，不可再保存。
- Registry 寫入採 SQLite metadata + Parquet 明細；若 hash 不符或檔案不完整，載入時會以完整性錯誤處理，不會靜默讀取部分結果。
- Legacy 單股回測 / 推薦組合保存庫仍可用於歷史資料與 backfill；新的「保存結果」入口以 Research Run Registry 為準。

### 9.9 結果分頁

- 實驗摘要：績效摘要與交易明細。
- 圖表：權益、回撤、報酬分布、持有天數。
- 最佳化 / 驗證：參數掃描與 Walk-forward。
- 歷史與比較：載入、刪除與比較 legacy 已保存結果。
- Registry 比較：列出 Research Run Registry 中的 run，可依類型、strategy、tag 篩選並分頁瀏覽；類型在 UI 顯示為「單股回測」或「推薦回放」，但存檔 metadata 仍保留原始 run type。run 清單每列以兩行顯示名稱、類型、策略與時間，方便選取多筆長名稱 run。選取 2 至 5 個 run 後，先以深色語意狀態列顯示「可直接比較 / 需謹慎比較 / 不可直接比較」與中文原因，再把所選 run 映射為 A / B / C / D / E 代號；摘要卡只顯示代號與中文欄位重點，長 run name / run_id 保留在上方對照與 tooltip，不塞進每個差異欄位。指標區會以小型對照表呈現，左欄為中文指標名稱，右欄為 A / B / C 數值，避免長段落混在一起。標準化權益需先按「比較選中」才會觸發，且所選 run 必須都有 equity curve 與共同日期；沒有共同日期或缺欄位時會顯示原因，不會補值或推估。
- 證據覆盤：唯讀檢查已保存 evidence / observation / review，以及 Windows Task Scheduler 產出的最新 scheduled dry-run 狀態。子頁包含「前瞻證據」、「研究落差」、「訊號衰退」、「決策品質」、「覆盤歷史」與「排程狀態」。頁面上方會顯示目前實際讀取的 SQLite 資料庫路徑，並提供「複製路徑」按鈕，方便確認是否使用 working-copy DB。各子頁日期欄位使用日曆選擇器，未選日期時不套用日期篩選；未選日期的日曆會先定位到今天，不會停在 sentinel 年份。
  - 前瞻證據：檢查已保存 evidence events / outcomes 的 forward summary。可依日期、event type / family、source type、股票、regime、sector、profile、strategy version、window days、group by 與最小樣本數篩選，並查看事件總數、已完成 / 等待中 / 缺失結果、樣本不足、benchmark / industry 缺口、quality 與 warnings。close-to-close forward return 是 research basis，不代表可執行績效。
  - 研究落差：檢查 portfolio source trace、Research Run / strategy version、evidence event / outcome link、portfolio mode、gap metrics、attribution categories、match confidence、quality 與 warnings。沒有真實交易與人工 override 記錄時，只能解讀為 research / simulated gap。
  - 訊號衰退：檢查 event_type、event_family、strategy_version、profile scope 的短窗 / 長窗樣本、decay score、status、lifecycle candidate、confidence、quality 與 warnings。`demote_candidate` / `retire_candidate` 只是人工覆盤候選，不會自動套用。
  - 決策品質：檢查週 / 月 / custom review item、process score、reason codes、review question、open / reviewed / dismissed 狀態、quality 與 warnings。score 只代表流程 evidence，不是投資能力、不是交易建議，也不是責備使用者。
  - 排程狀態：讀取 `OUTPUT_ROOT/scheduled/data_freshness/latest_status.json`、`OUTPUT_ROOT/scheduled/recommendation_snapshot/latest_status.json`、`OUTPUT_ROOT/scheduled/evidence_pipeline_dry_run/latest_status.json` 與 latest status 指向的 dry-run markdown report preview，顯示 data freshness、recommendation snapshot result id / 筆數 / screening matrix rows、evidence dry-run、`pipeline_overall_status`、report path、warning occurrences、blocking gaps 與 `confirm / writes_recommendation_result / writes_evidence_db / auto_trading / lifecycle_action` 安全邊界。推薦結果寫入會另標示為 research-only output，不會和 production evidence / trading write risk 混為同一概念。若 scheduled recommendation latest status 缺失，但同一 decision date 已有人工保存的 `OUTPUT_ROOT/recommendation/runs/rec_YYYYMMDD_*.json`，頁面會把 recommendation source 顯示為 `manual_result`、status 顯示為 `manual_observed`；這只代表人工補跑結果可供判讀，不代表 scheduled snapshot 正常，也不計入 scheduled 共同觀測天數。下方狀態明細採「判讀摘要 / 人工要看 / 關鍵欄位 / 安全邊界」優先，report preview 只保留前段 metadata，完整 JSON diagnostics 請依 `report_path` 開啟原始 report。這只是讓每日 scheduled output 與人工補跑觀察在 UI 可見；不重跑 pipeline、不寫 evidence DB、不自動追加 `POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md`。
  這個分頁只使用 dashboard service、已保存 read model 與 scheduled output status 檔，不重算推薦、不重算策略、不讀 UI state、不寫 evidence，也不建立或修改排程；樣本不足或資料降級時只能作資料品質檢查，不可作訊號有效性判斷。
  - 覆盤歷史：只讀取已保存 weekly review；若 history DB／table 不存在，畫面會顯示 `evidence_operations_history_db_missing`／`...table_missing` 診斷與 CLI 建立指引，絕不因刷新畫面建立空 schema。
- 批次結果：排行榜與整體統計，雙擊股票可載入明細；頁首會說明排行榜只用來找出同批次內值得複核的股票，整體統計用來看樣本分布與成功率，不代表正式策略判斷、交易建議或持倉調整。
- 推薦回放：摘要分為概況、交易假設與可信度、風險與情境指標、Monte Carlo 情境；V1.2 result details 會補充 `rolling_risk_metrics`、`microstructure_preflight` 與 `relative_attribution`，用來判讀 rolling risk、可選台股微結構風險與 benchmark / industry / concept 背景；下方以分頁呈現組合價值 / 回撤圖、期間持倉、股票貢獻與交易紀錄。

### 9.9.1 Evidence Pipeline Runner（手動 dry-run）

Evidence Pipeline Runner 是手動 CLI，用來模擬每日 evidence pipeline；它不是 Windows Task Scheduler、cron 或背景 job。預設只做 dry-run，不會寫入 evidence events / outcomes。正式 `--confirm` 只能對 explicit working-copy DB 執行，且仍需人工審核 diagnostics report。

常用命令：

```powershell
.\.venv\Scripts\python.exe scripts\run_evidence_pipeline.py --decision-date 2026-06-30 --dry-run --json-output
.\.venv\Scripts\python.exe scripts\run_evidence_pipeline.py --decision-date 2026-06-30 --dry-run --sources recommendation,watchlist-trigger,portfolio-alert,risk-prompt --report-output output\evidence_pipeline\reports\evidence_pipeline_2026-06-30.md
.\.venv\Scripts\python.exe scripts\run_evidence_pipeline.py --decision-date 2026-06-30 --confirm --db-path <working-copy-db>
.\.venv\Scripts\python.exe scripts\inspect_evidence_source_coverage.py --db-path <working-copy-db> --decision-date 2026-06-30 --json-output
.\.venv\Scripts\python.exe scripts\smoke_evidence_pipeline_working_copy.py --source-db-path <source-db> --working-copy-db-path <working-copy-db> --decision-date 2026-06-30 --repeat 2 --json-output
.\.venv\Scripts\python.exe scripts\evaluate_evidence_scheduler_readiness.py --db-path <working-copy-db> --json-output
.\.venv\Scripts\python.exe scripts\evaluate_evidence_scheduler_readiness.py --db-path <working-copy-db> --approval-artifact <owner-approved-json> --json-output
.\.venv\Scripts\python.exe scripts\inspect_data_source_capabilities.py --json-output
.\.venv\Scripts\python.exe scripts\inspect_corporate_action_policy.py --json-output
```

支援參數包含 `--decision-date`、`--start-date`、`--end-date`、`--db-path`、`--sources`、`--windows`、`--group-by`、`--window`、`--min-sample-size`、`--limit`、`--dry-run`、`--confirm`、`--skip-snapshot`、`--skip-capture`、`--skip-outcomes`、`--skip-summary`、`--json-output`、`--report-output`。`--dry-run` 與 `--confirm` 互斥；`--confirm` 必須指定 `--db-path`。若 DB path 看起來是正式 DB，還需要額外 `--allow-production-db-confirm`，但一般 QA 不應使用正式 DB。

Runner steps：

1. `source_coverage_check`
2. `capture_decision_desk_snapshot`
3. `capture_evidence_events`
4. `calculate_forward_outcomes`
5. `summarize_forward_performance`
6. `write_diagnostics_report`

輸出 summary 會包含 events_seen、events_inserted、events_skipped_duplicate、outcomes_attempted、outcomes_created、outcomes_updated、outcomes_pending、summary_groups、groups_ready、groups_insufficient_sample、groups_degraded、warnings_count、warning_counts、warning_unique_count、warning_top_counts、errors_count、blocking_gaps、warnings 與 scheduler_readiness。Markdown report 的 `Warning Summary` 會分開顯示跨 pipeline steps 的 warning occurrence 總量與唯一 warning token 數，`Warning Breakdown` 會列出完整 warning token 分布；`diagnostic:<code>` 代表 warning 等級 diagnostic，不代表 blocking error。Readiness 最高只到 `ready_for_manual_confirm`，不代表 production scheduler 已批准。

V1.5 後，source coverage 由 `EvidenceSourceCoverageService` 統一判讀。`recommendation_persisted_missing`、`decision_desk_snapshot_missing`、`watchlist_trigger_snapshot_section_missing`、`portfolio_alert_snapshot_section_missing`、`risk_prompt_snapshot_section_missing` 是 durable source blocking gaps；`screening_matrix_missing`、`why_not_payload_missing` 與 `liquidity_gate_payload_missing` 是 payload warnings，會使整體 readiness 維持 `dry_run_only`，但不等於 durable source missing。V1.7 後新保存的推薦結果會包含 screening matrix、Why Not 與 Liquidity payload；舊推薦結果若缺 payload，只會列 warning / diagnostic，不回補、不重算。2026-07-06 後，成交量門檻造成的 empty strategy result 會被保存為 Liquidity payload，而非一般 `strategy_filter_no_signal`。若 runner dry-run 在同一輪建立 transient Daily Decision Desk snapshot，報告會以 `source_coverage_basis=dry_run_transient_decision_desk_snapshot` 標示，並把同輪 transient snapshot 用於 source coverage 判讀，避免把 dry-run 未寫 durable snapshot 誤列為 stale `decision_desk_snapshot_missing`；這只影響 report diagnostics，不寫 durable snapshot 或 production evidence DB。若使用 `--sources why-not` 或 `--sources liquidity-gate` 明確要求 exclusion source，runner 仍會在該請求層級阻擋缺 payload 的 capture。Current 查詢會以台灣市場今日為日期上限；active Decision Desk future row 會列為 `decision_desk_snapshot_future_dated` blocker，並排除於 current latest，原始 row 不刪除。`EvidenceSourceCoverageService`、`inspect_evidence_source_coverage.py` 與 `inspect_decision_desk_snapshots.py` 都是 query-only 檢查，不會因 repository 初始化 schema 而寫入正式 DB。`inspect_data_source_capabilities.py` 只檢查 source registry，不抓外部資料；`inspect_corporate_action_policy.py` 只輸出價格政策與資料表候選，不建立 adjusted price、不寫正式 DB。

### 9.9.2 Historical Evidence Replay（歷史排程重放）

Historical Evidence Replay 用來把 Evidence Pipeline 放到半年前或指定歷史期間逐交易日重放。它會先把 source SQLite DB 複製成 replay DB，再每天只使用當日可見的資料跑 source coverage、snapshot capture、recommendation evidence capture 與 forward outcome maturity。這是 `historical_replay` / `simulated_scheduler`，不是既有 Windows Task Scheduler，也不會取代每天 05:15 的 scheduled dry-run report。

常用命令：

```powershell
.\.venv\Scripts\python.exe scripts\replay_historical_evidence_pipeline.py --start-date 2026-01-06 --end-date 2026-07-06 --source-db-path <source-db> --replay-db-path tmp\historical_replay\evidence_replay_2026h1.db --json-output --report-output output\evidence_pipeline\historical_replay_2026h1.md
.\.venv\Scripts\python.exe scripts\replay_historical_evidence_pipeline.py --start-date 2026-01-06 --end-date 2026-07-06 --source-db-path <source-db> --replay-db-path tmp\historical_replay\evidence_replay_2026h1.db --confirm --overwrite-replay-db --sources all --windows 5,10,20,60 --outcome-mode final --json-output
```

主要參數：

- `--start-date` / `--end-date`：要重放的歷史日期區間；實際執行日會從 source DB 的 `daily_prices` 交易日中挑出。
- `--source-db-path`：原始 SQLite DB，只用來複製與查交易日；不可與 replay DB 同一路徑。
- `--replay-db-path`：重放用 working-copy DB。若不存在會由 source DB 複製；若已存在，只有加 `--overwrite-replay-db` 才會重建。
- `--confirm`：預設不寫 business rows；加上後才會對 replay DB 寫入 evidence events / outcomes。正式 evidence DB 不應拿來當 replay DB。
- `--outcome-mode final|daily`：預設 `final`，逐日 capture 完成後只在 replay end date 做一次 forward outcome 計算，適合半年 replay；`daily` 會每天用當日 `data_as_of_date` 重新計算 outcome maturity，語意更細但大型 DB 會明顯變慢。
- `--sources`、`--windows`、`--group-by`、`--window`、`--min-sample-size`、`--limit`：沿用 Evidence Pipeline Runner / forward summary 的控制語意。
- `--report-output`：輸出 Markdown replay report；JSON summary 會固定印到 stdout。

No-look-ahead 邊界：

- Recommendation 類來源只會選 `created_at` 日期不晚於當日 decision date 的 persisted result；若沒有當日以前 result，會記錄 `recommendation_asof_result_missing`，並略過 `recommendation` / `why-not` / `liquidity-gate` 類來源，不用未來 result 補值。
- Event metadata 會帶入 `replay_mode=historical_replay`、`source_label=simulated_scheduler`、`replay_run_id`、`replay_decision_date` 與 `replay_data_as_of_date`，方便和真實 scheduled dry-run 分開查。
- Forward outcome 計算會以 `data_as_of_date` 限制價格可見日；`final` 模式以 replay 最後一個交易日作上限，`daily` 模式以每日 replay date 作上限。在可見日尚未成熟的 5 / 10 / 20 / 60 日 window 仍會維持 pending，不會提前看未來價格。Pending outcome 會依交易日序列揭露 `expected_maturity_date` 與剩餘交易日；日曆資料不足時顯示 `waiting_for_calendar`，不得用 calendar days 補算。
- Replay report 只能用來看 source gap、payload gap、decision workflow 與 V2.0 workbench 設計方向；不計入目前 weekly history `1/3 waiting_for_time`、已達 `3/3 ready` 的 multi-day dry-run 實際紀錄、manual approval 或 production scheduler gate，也不是投資有效性證明。

結果判讀：

- 2026-07-06 reference return fix 後，若 event 沒有 `benchmark_id`，forward outcome 會以 `TAIEX` 作為市場 benchmark default；`market_indices` 可使用未命名市場序列，並在 `收盤指數` 缺值時 fallback 到 `收盤價`。
- Industry return / excess 不會推估未知產業；只有 event 有 `industry_benchmark_id` 或 `sector` 且可保守映射到 `industry_indices` 時才會填入。缺值會保留 `NULL` 與 `missing_industry_benchmark` warning，不會填 0。
- `_reference_fix` replay 產物中，ready benchmark return / excess 已可用；industry 大量 `DEGRADED` 代表舊 recommendation payload 缺 sector / industry，不代表 raw forward return 或 benchmark excess 壞掉。cleanup 後保留位置為 `D:/Min/Python/Project/FA_Data/output/evidence_pipeline/historical_replay_reference_fix_20260706/`；Workbench CLI 只應讀其中 JSON summary。
- `source_missing_screening_matrix` 代表舊 recommendation result 沒有當時的 screening matrix payload；系統不回補、不重算舊結果。

### 9.9.3 Simulated Phase Progress 與 Phase 5 Approval Rehearsal

V2.2 後，可用 `scripts\inspect_simulated_phase_progress.py` 將 Historical Evidence Replay summary、scheduled dry-run latest status 與 Pre-V2 readiness 串成 simulated Phase 0-5 判讀。這個 CLI 只讀既有 JSON / Markdown / DB，不執行 replay、不啟用 scheduler、不寫 evidence DB，也不會把 replay 補成 official gate。它與 Workbench 共用 `WEEKLY_EVIDENCE_HISTORY_PROJECTION_PATH`；如需明確指定 owner-approved projection，可加上 `--approved-weekly-history-projection <path>`，只會影響 UI／readiness 揭露，不授予 formal credit。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_simulated_phase_progress.py --db-path <working-copy-db> --replay-summary-path D:\Min\Python\Project\FA_Data\output\evidence_pipeline\historical_replay_reference_fix_20260706\historical_replay_2026-01-06_2026-07-06_reference_fix.json --scheduled-output-root D:\Min\Python\Project\FA_Data\output\scheduled\evidence_pipeline_dry_run --decision-date <YYYY-MM-DD> --json-output
.\.venv\Scripts\python.exe scripts\inspect_simulated_phase_progress.py --db-path <working-copy-db> --replay-summary-path <replay-summary.json> --approved-weekly-history-projection <projection.json> --json-output
.\.venv\Scripts\python.exe scripts\inspect_simulated_phase_progress.py --db-path <working-copy-db> --replay-summary-path D:\Min\Python\Project\FA_Data\output\evidence_pipeline\historical_replay_reference_fix_20260706\historical_replay_2026-01-06_2026-07-06_reference_fix.json --scheduled-output-root D:\Min\Python\Project\FA_Data\output\scheduled\evidence_pipeline_dry_run --decision-date <YYYY-MM-DD> --markdown --report-output output\qa\simulated_phase_progress.md
```

輸出判讀：

- `simulated_overall_status=simulated_ready` 只代表 approval rehearsal 可演練，不代表 official gate 完成。
- replay-derived evidence 必須保留 `replay_mode=historical_replay`、`source_label=simulated_scheduler`、`official_gate_credit=false`、`requires_real_world_validation=true`。
- scheduled dry-run latest status 若為 `dry_run=true`、`confirm=false`、`writes_evidence_db=false`，只代表看見 raw output；`manual_record_credit=false` 時不可計入 multi-day record。
- `official_phase_5_status=blocked` 與 `production_scheduler_allowed=false` 必須保留，直到正式 Phase 0 / approval gates 通過。

不得標示為已完成、必須等待正式資料的項目：

| 項目 | 完成前必須等到 |
|---|---|
| weekly history | 3 筆不同週期、人工確認後保存的 weekly evidence operations history。 |
| multi-day dry-run | 3 個真實交易日的 freshness、scheduled dry-run、working-copy confirm smoke、dashboard review 與 manual notes。 |
| manual review note rhythm | 真實操作日可比較的人工覆盤 notes。 |
| action item rhythm | 真實 review / dismissed / follow-up 節奏；目前 Action Items 只是 read-only queue。 |
| Phase 3 source acceptance | 每個 candidate source 的 available-date / quality / missing policy 與 dry-run diagnostics。 |
| Phase 4 execution realism acceptance | spread、odd-lot、locked limit、gap execution、unfilled reason 等 research-only sandbox 驗證。 |
| Phase 5 scheduler approval | backup / rollback / recovery evidence、source gaps acceptance、working-copy idempotency 與 explicit manual approval。 |

`docs/06_qa/V2_2_PHASE5_APPROVAL_REHEARSAL_PACKAGE_2026_07_07.md` 是目前的審核包預演文件；它可用來準備審核材料，但不改 lifecycle、不開 scheduler、不代表 production readiness。

Phase 3C 後，可用 `scripts\inspect_source_candidate_readiness.py` 做三大法人、信用交易與 TDCC / 集保庫存 source candidate dry-run。此 CLI 只檢查 candidate readiness / coverage / diagnostics，不正式接入策略訊號，不寫 production DB，不提供 `--confirm`，不啟用 scheduler，不改 `ScoringEngine`、推薦分數、threshold、profile 權重、portfolio 或 lifecycle。

Phase 3C adapter 的 provider-facing source identity（`twse_institutional`、`twse_credit`、`tdcc_shareholding`）與 Gate 3 canonical contract 的對應，固定由 `data_module.p0_source_contract_registry.map_candidate_source_id()` 的 `p0-candidate-source-alignment.v1` 明確映射：分別對應 `institutional_flows`、`credit_transactions`、`tdcc_shareholding`。這只是 identity／traceability 對齊，不會自動接受來源，也不會授予 `downstream_eligibility`。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_source_candidate_readiness.py --sample --format json
.\.venv\Scripts\python.exe scripts\inspect_source_candidate_readiness.py --sample --format markdown
.\.venv\Scripts\python.exe scripts\inspect_source_candidate_readiness.py --db-path <working-copy-db> --decision-date <YYYY-MM-DD> --format json
```

輸出判讀：

- `institutional_flows` 檢查外資、投信、自營商的 buy / sell / net buy-sell 欄位與 source quality / available_date / decision_date 邊界。
- `credit_transactions` 檢查融資買進、融資餘額、融券賣出、融券餘額；`financing`、`securities_lending` 只有資料存在才列入，缺欄位只回 `missing_optional_source`，不補值。
- `tdcc_shareholding` 檢查股權分散、持股級距、大戶比例、散戶比例等候選 payload；週資料或公告延遲資料必須保留 explicit `available_date`，缺 available date 不得進 decision-time feature。
- 缺 DB、缺 table 或尚未 ingestion 時會輸出 `source_not_ingested` / `missing_db` / `missing_table`，不建立 DB 或 table。
- table 存在但缺 `available_date` 時會輸出 `missing_available_date`，且 `decision_ready=false`。
- `available_date > decision_date` 會輸出 `future_data_blocked`，不得被使用。
- `access_boundary` 必須保留 `writes_allowed=false`、`production_scheduler_allowed=false`、`scoring_engine_write_allowed=false`、`investment_effectiveness_claim=false`。

### V2.3 P0 資料來源人工接受台帳

`docs\06_qa\V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md` 是 Gate 3 / V2.3 的逐來源人工決策台帳。它完整涵蓋除權息 / 除權、未登錄的減資 / 分割 / 面額變更、停牌 / 復牌、處置、分盤、全額交割、漲跌停鎖死、三大法人、信用交易、TDCC / 集保持股分散與 PIT fundamentals；它不是資料抓取命令，也不會改變 CLI、UI、DB 或資料來源設定。

操作與結果判讀：

1. 先以本節的 candidate readiness CLI 保留來源 diagnostics、`available_date` 與 quality 證據；候選資料只可用於審核，不能直接接入策略訊號。
2. 再由具名人工決策人逐列審核 source version、`as_of_date`、授權 / 使用範圍、rate limit、freshness / coverage、PIT 語意、missing / outage、quarantine、retry 與 evidence / review / rollback pointer。
3. 未填完人工作業前，台帳的 `human decision` 必須維持 `requires_human_acceptance`，`owner` 與 `date` 必須分離保持未填，`downstream eligibility` 必須維持 `none`。
4. `decision_ready_candidate` 只代表該筆候選資料未觸發 available-date / required-field blocking diagnostic；它不是 `accepted`，不得讓資料進入 `ScoringEngine`、Advice、Portfolio、lifecycle 或 production scheduler。
5. 資料缺失、outage、stale、缺 `available_date` 或 `available_date > decision_date` 時，維持 fail-closed 或明示 degraded / warning；不得補值或當作 observed。除權息 / 除權 capability 不能延伸主張為減資 / 分割 / 面額變更；後三者及停牌 / 復牌均須各自完成來源接受。
6. `python -m scripts.build_source_acceptance_dossier --input <candidate-json> --output <TEMP-projection.json>` 只可輸出到正式 `DATA_ROOT` 之外。投影的 `dossier_content_hash` 是 dossier 欄位的 canonical SHA-256；檔案傳輸或落盤完整性必須另算 serialized file SHA-256，兩者不可混用。投影仍固定 `candidate_only=true`、`formal_oos_allowed=false`、`production_blend_alpha_bp=0`，不構成來源接受。

只有台帳已記錄真實的 `accepted` / `limited` / `rejected` / `deferred` 結論、owner、日期與明確 downstream eligibility 時，才可另行規劃後續受控實作。本手冊與台帳本身不授權任何 ingestion 或策略變更。

V1.6 後，可用 cross-sectional factor snapshot inspection CLI 唯讀檢查已保存的 daily factor snapshot。這個 CLI 不建立 DB、不寫 snapshot、不重算 scoring；若指定的 DB 不存在會以錯誤結束。snapshot 只會在其他受控 workflow 明確呼叫 `CrossSectionalFactorPipeline` / `CrossSectionalFactorRepository` 保存後才存在。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_cross_sectional_factor_snapshot.py --db-path <working-copy-db> --latest --json
.\.venv\Scripts\python.exe scripts\inspect_cross_sectional_factor_snapshot.py --db-path <working-copy-db> --snapshot-id <snapshot-id> --markdown
```

輸出會包含 snapshot metadata、row count、factor / quality / rank bucket 分布、sector / concept basket counts 與 diagnostics counts。rank / quantile 只代表當日橫斷面 factor 排序與研究 attribution，不是推薦名單、不代表買賣訊號，也不會改 `ScoringEngine`。Concept basket 只有在定義的 `available_date <= decision_date` 時才會進入 row；未到可得日只會出現在 diagnostics。

V1.8 後，可用 Portfolio Sandbox inspection CLI 檢查研究用 allocation / virtual execution trace 的樣本輸出。這個 CLI 目前只支援 `--sample`，不讀正式 DB、不寫 output、不建立持倉、不產生 broker order；輸出全部標示為 research-only。Allocation 結果使用整數 bp 權重、`Decimal` 金額字串、整數股數與 lot sizing；trace event 只表示虛擬 lifecycle，不代表實際委託或成交。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_portfolio_sandbox.py --sample --format json
 .\.venv\Scripts\python.exe scripts\inspect_portfolio_sandbox.py --sample --format markdown
```

### 資料來源路由與 FinMind 配額

日常更新優先使用富邦 market-data API、TWSE／TPEX／MOPS／TDCC 官方端點與已受控的自有網頁抓取器；每種資料必須先依資料語意選擇 provider，不能把價格、法定公告與盤中狀態互相冒充 fallback。富邦是授權市場資料主源，適用於即時／當下可觀測行情與已文件化的公司行動欄位；MOPS 仍是財報、月營收與更補正的法定公告鏈；TWSE／TPEX／TDCC 仍是市場制度與日終資料鏈。

資料源的嘗試順序為：同一語意的富邦或官方 API／官方 HTML fast path → 同一語意的受控爬蟲 fallback（MoneyDJ 僅 HTTP Big5 失敗或無法解析時才啟用 Selenium）→ 已保存 raw artifact 的唯讀重試。任何 source 切換都要保留 provider、source version、實測時間、row count、成功／失敗原因與 fallback 原因；沒有等價語意的來源時 fail closed，不以其他資料類型補值。

FinMind 是低頻 bulk／缺口來源，不是全市場逐檔的日常更新主線。帳戶上限為每小時 600 requests，實作與人工執行均採 `480` requests/hour 軟上限，保留 20% 給暫時錯誤與人工查詢；逐檔 dataset 必須以缺口 queue、夜間執行與 `--resume` 續跑，官方或富邦已成功取得的同一資料不得重複請求。月營收 create-time CLI 必須明確提供至少一個 `--stock-code`；若確實要使用 raw 清單做批次，必須同時提供 `--all-raw-stock-codes --resume`，避免無意間啟動全市場逐檔請求。可一次取得全市場或涵蓋所需期間的 FinMind dataset 才可進 bulk queue；`create_time` 僅是 FinMind 觀測時間，不能取代 MOPS／交易所公告時間。

### 富邦行情 API 人工唯讀連線測試

`scripts/test_fubon_readonly_marketdata.py` 只供人工確認 Windows Credential Manager API key、憑證與 OTC 行情 snapshot 連線。可在目前終端設定 `FUBON_PERSONAL_ID`、`FUBON_CERT_PATH`，必要時設定 `FUBON_CERT_PASS`；若 Codex／Antigravity 等終端 process 不共用環境變數，則可在 Windows Credential Manager 建立下列 Generic Credentials，username 一律為 `market-data`：`fubon-neo-readonly-api-key`（API key）、`fubon-neo-readonly-personal-id`（身分識別）、`fubon-neo-readonly-cert-path`（憑證完整路徑），以及只有私鑰密碼不同於身分識別時才建立的 `fubon-neo-readonly-cert-pass`。工具優先使用當前 process 的環境變數，其次讀取這些 Credential Manager 項目；不得把任何值寫入 repo、命令列或 log。缺少任一必要 credential 時腳本以 exit code 2 停止，登入失敗以 exit code 1 停止；成功登入後唯一允許的資料呼叫是 OTC snapshot quotes。此工具不呼叫帳務、持倉、委託或交易 API，不保存行情、不寫 DB，也不代表 broker lane、source acceptance 或 Formal evidence 已成立。自動化與測試只能使用 injected fake SDK，不得代替人工實際登入。

### 富邦行情 Source Acceptance Dossier 唯讀盤點與評估

`scripts/inspect_fubon_dossier.py` 用於對富邦 market-data 的 source acceptance dossier 進行唯讀盤點與評估。它可以檢測當前 dossier 缺少的證據，並區分「程式可驗證」與「只能由 owner / legal / source owner 提供」的項目，最後在指定安全白名單的 shadow root 目錄下產生一個供 owner 審查的繁體中文範本：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_fubon_dossier.py `
  --dossier C:\Temp\external-evidence-shadow\fubon_dossier_projection.json `
  --output-template C:\Temp\external-evidence-shadow\review_template.md `
  --shadow-root C:\Temp\external-evidence-shadow
```

本工具為 review-only，所處理之 dossier 被標記為 deferred candidate，且狀態始終保持為 owner review pending。無論檢核項目是否完整，狀態一律投影為 deferred、allowed_use_cases=()，且下游 downstream_eligibility=none。此工具不寫入正式資料庫，預設不輸出 template 檔案，且只有當 `--output-template` 與 `--shadow-root` 同時存在並通過嚴格的正式路徑拒絕驗證時才允許寫入。

### Formal clock 起跑前檢查

Formal clock 不是 development adapter 完成的延伸；只有在真實決策當下才能建立第一個 observed day。開始前必須同時具備：

1. 具名 owner 的 `HoldoutConsumptionRegistry.jsonl` 已置於 development output root 的 `governance/`，並在每次綁定前重新檢查；它必須可證明 owner decision 指定的第一個未消費交易時段尚未被使用。沒有 registry 時不得宣稱 holdout 已綁定、已消費或 formal readiness 成立。
2. 真正 decision-time 產生的 `manual_observed` JSON：`decision_timestamp`、`max_available_timestamp`、`data_as_of_date`、source versions、Rule champion identity、universe hash、symbol、why／why-not／risk、restriction state 與所有 missing/degraded reason 都必須來自當下可見的決策輸出。不得由歷史 replay、fixture、事後補寫或 automation invocation count 合成。
3. owner 若已綁定 Rule-only lane，可在該 lane 的**真實台北盤中 09:00–13:30**，以新的 foreground-only 命令產生當下的 decision source。它只讀 `daily_prices` 中嚴格早於決策日的最近 60 個交易日，使用固定 20 日價格／成交量整數 bp 排名，輸出受 HMAC 驗證的 Rule Champion、hash-addressed decision output 與可交給下一步的 `manual_observed.json`。它不讀 MOPS／富邦／基本面／ML，不寫 market DB、Recommendation、Portfolio、Exit、Score、lifecycle 或 evidence ledger，也不建立 scheduler。第一次使用前，owner 必須在自己的 Windows 使用者環境設定受控的 `RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY` 與非空的 `RULE_CHAMPION_CONTROLLED_STORE_ID`；key 不得寫入 repo、命令列、log 或 JSON artifact。

```powershell
.\.venv\Scripts\python.exe scripts\run_manual_rule_only_decision.py `
  --development-output-root C:\Temp\technical_analysis_development_output `
  --market-db <TWStockConfig.db_file 的實際 SQLite 路徑> `
  --lane-decision-json C:\Temp\technical_analysis_development_output\governance\FormalObservationLaneDecision_20260807_r1.json `
  --confirm produce-manual-rule-only-decision
```

成功時請從 JSON 輸出取得 `manual_observed_json` 路徑；這只建立決策來源，**不**代表 formal credit、elapsed day、holdout consumption、source acceptance 或 production readiness。若命令回報盤外、session mismatch、registry／lane 無效、資料庫時間晚於決策時間、資料不足或 attestation key 缺失，保持 snapshot count=`0`，不要用改時間、fixture、歷史資料或再次 automation invocation 補造輸出。

4. snapshot 僅可追加到 TEMP 或明確命名的 shadow sidecar，並由下列命令人工確認；它不寫 market DB、不啟用 scheduler、交易、training、promotion 或 formal OOS：

```powershell
.\.venv\Scripts\python.exe scripts\capture_external_evidence_manual.py `
  --db $env:TEMP\external-evidence-shadow\evidence.sqlite `
  --output-root $env:TEMP\external-evidence-shadow `
  --snapshot-json <真實決策當下保存的-manual_observed.json> `
  --confirm append-external-evidence
```

5. 每一筆 P0 source 仍需依 `docs/06_qa/V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md` 取得具名 owner／reviewer 的 license、quality、PIT、coverage、missing／outage 與 rollback 決議；candidate、degraded 或 research-only artifact 都不會自動變成 accepted source。

若上述任一項缺失，snapshot count 維持 0；不得以同日多次執行、pending outcome、歷史回填或 fake／replay artifact 取得 formal credit。

不得用內建常數、sample rows、固定 timestamp／score／source hash 的 CLI 輸出組裝 `manual_observed`。每個 snapshot 的 `parent_artifact_ids` 至少必須有一個 hash-addressed 的真實 decision-output lineage（格式含 `:sha256:`）；缺少時 capture 與 preflight 都會拒絕。即使其他 schema 欄位相符，該 JSON 仍是 synthetic fixture，沒有真實決策輸出與來源 provenance，必須排除於 Formal snapshot、observed day、denominator 與 credit。

`HoldoutConsumptionRegistry.jsonl` 是 owner 的 append-only 決議載體，不是 automation 可代寫的設定檔。`development_holdout_start` 是開發資料的排除起點；`formal_trading_session` 則是 owner 在綁定當下選定的第一個未消費正式觀測交易時段，兩者不可因為現在才綁定而倒填成過去的 observed day。owner 真正決定綁定後，才可依下列一行 JSONL 契約建立第一筆 record；尖括號內容必須是 owner 的真實資料，不能直接複製為正式證據：

```json
{"schema_version":"holdout-consumption-registry.v2","record_type":"formal_holdout_binding","development_holdout_start":"2026-07-15","formal_trading_session":"<綁定後第一個未消費臺灣交易時段>","owner_id":"<具名 owner>","binding_authorization":"<可引用的 owner 決議 ID 或 artifact>","bound_at":"<含時區的綁定時間>","owner_decision_sha256":"<DevelopmentDataUsageDecision.jsonl 的 sha256:...>","unconsumed_before_binding":true,"formal_oos_allowed":false,"production_blend_alpha_bp":0}
```

preflight 會拒絕缺欄、無時區、早於 owner decision、formal session 早於 binding、decision hash 不符、未明示 `unconsumed_before_binding=true`，或任何解除安全旗標的 record；snapshot 的決策日期也必須剛好等於 `formal_trading_session`。它只能驗證 owner 的結構化聲明，不能自行證明交易時段確為「第一個」；該判定與授權仍屬 owner 責任。

若舊 v2 session 已經留下 shadow-only／deferred artifact，不得覆寫或倒填。owner 可以另建一份 `formal-observation-lane-decision.v1`，以 `holdout_id`、決議時間、第一個決議後未使用交易日、Rule-only source whitelist 與 candidate-source exclusion list 凍結新 lane；接著使用下列 CLI append 一筆 v3 binding。CLI 會保留舊 v2 record，拒絕重複 `holdout_id`、重複交易時段、決議前 binding、非 owner 核准 session、repo／正式 `DATA_ROOT` 路徑與任何安全旗標放寬：

```powershell
.\.venv\Scripts\python.exe scripts\bind_formal_observation_lane.py `
  --development-output-root C:\Temp\technical_analysis_development_output `
  --decision-json C:\Temp\technical_analysis_development_output\governance\FormalObservationLaneDecision_20260728_r1.json `
  --formal-trading-session 2026-07-29 `
  --bound-at <含時區的真實綁定時間>
```

v3 binding 只是 future observation lane 的 owner-attested boundary，不是 observed snapshot、holdout consumption、Formal credit 或 source acceptance。富邦可以同時維持 shadow／candidate 可用，但若 decision artifact 未把 `fubon.marketdata` 排除，lane contract 會 fail closed。

先以唯讀 preflight 檢查 owner decision、owner-attested registry binding 與**已存在**的 snapshot 結構；此命令不建立 registry、不綁定 holdout、不寫 evidence，也不會宣稱 formal readiness。`can_capture_shadow_snapshot=true` 僅表示 binding 契約與 snapshot 均通過結構驗證；實際「第一個未消費交易時段」的判定仍須具名 owner 決議，且 source acceptance 未完成時 `formal_readiness` 一律為 `false`。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_formal_clock_readiness.py `
  --development-output-root C:\Temp\technical_analysis_development_output `
  --lane-decision-json C:\Temp\technical_analysis_development_output\governance\FormalObservationLaneDecision_20260728_r1.json
```

若已有真正 decision-time artifact，才可額外傳入其路徑檢查契約；不要用 fixture、replay 或事後補寫檔案測試後就執行 capture：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_formal_clock_readiness.py `
  --development-output-root C:\Temp\technical_analysis_development_output `
  --lane-decision-json C:\Temp\technical_analysis_development_output\governance\FormalObservationLaneDecision_20260728_r1.json `
  --snapshot-json <真實決策當下保存的-manual_observed.json>
```

V2.4 紙上政策可用下列唯讀 CLI 檢查。它固定使用核准的平衡型參數，對現金、單檔、產業、週轉與 cooldown 限制產生 `PAPER_TRADE_CANDIDATE` 或 `NO_PAPER_TRADE`；結果不是交易指令，也不讀實際持倉或寫入任何資料庫。

Paper Portfolio 日更工程另提供 append-only snapshot repository。每個 `snapshot_id` 只能新增一次，歷史 snapshot 不可覆寫；價格、現金與市值以 Decimal 字串保存，權重以整數 bp 保存。此 repository 僅存 research paper ledger，不連接正式持倉或 broker。

Daily mark-to-market runner 只使用 `price_date <= decision_date` 且 `available_date <= decision_date` 的價格。若任一持倉沒有 causal price，整次日更 fail-closed，不建立部分 snapshot；非交易日可使用前一個可見交易日並留下 diagnostic。它只重算紙上市值與權重，不執行再平衡或 broker order。

Portfolio-level rebalance evaluator 會依固定順序逐檔套用現金、單檔、產業、cooldown 與累計週轉限制；前一筆 paper candidate 會占用後續批次的週轉額度。結果固定 `apply_rebalance=false`、`broker_order_allowed=false`，需要另行人工檢視，不會改寫 snapshot。

Equal-weight benchmark 在 baseline 日凍結 constituents 與等額 units，後續不因新推薦或下市存活狀態替換成分，以避免 survivor bias。每日 benchmark ledger 只接受 causal price 並 append-only 保存；任一 frozen constituent 缺價即 fail-closed。

Weekly paper report 同時列出 gross return、成本後 net return、固定成分 benchmark return、net excess、交易成本與 turnover；觀測交易日少於預期時標示 `DEGRADED / incomplete_trading_week`。報告固定 `research_only=true`、`investment_effectiveness_claim=false`。

Position thesis contract 要求人工保存 entry thesis、entry/decision/available date、持有期限、下次 review date、source trace 與至少一條結構化 invalidation rule。規則 threshold 使用 Decimal，future-available thesis 會被拒絕；contract 固定 `auto_exit_allowed=false`。

Position Health state machine 僅使用決策日當下可得的 Decimal metrics。future 或 missing metric 會 fail-closed 到 `WATCH`，失效規則命中只提出 `EXIT_CANDIDATE`；`CLOSED` 是終態。所有結果固定 `apply_transition=false`、`auto_exit_allowed=false`。

Position Health transition repository 採 append-only event。`proposal` 事件的 `recorded_state` 必須維持 previous state；只有帶 reviewer 的 `human_approved` 事件可記錄核准後狀態。兩者都固定 `auto_action_allowed=false`，不會送出賣單。

Workbench 的 engineering closure projection 只顯示工程包完整度與尚待人工／時間／授權／ML 重驗項目。每列會顯示 owner、最早驗證日、進度及下一個驗證命令；Action Item 固定唯讀，不能在 Workbench 直接標記完成、修改 registry 或套用任何 production action。

Exit effectiveness read model 依 reason code 分組，只將 maturity=`ready` 的 outcome 放入績效分母，分別揭露 avoided loss、early-exit regret、precision 與 realized return；pending 只計數。報告固定不宣稱投資有效性，也不啟用 auto exit。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_paper_portfolio_policy.py --sample --format json
```

若要從已保存 Recommendation 建立第一個真實資料 paper baseline，使用下列命令。輸出只寫 JSON artifact，不寫 Portfolio DB、不產生 broker order、不自動再平衡；正式操作前仍需確認來源 result ID 與輸出位置。

```powershell
.\.venv\Scripts\python.exe scripts\build_paper_portfolio_baseline.py --recommendation-json <saved-recommendation.json> --output <paper-baseline.json>
```

V2.5 可用下列唯讀 CLI 檢查持倉健康狀態的輸出形狀。它以內建樣本顯示 thesis／condition／feedback 缺口如何形成 `HEALTHY`、`WATCH` 或 `EXIT_CANDIDATE`；任何狀態都不是交易或平倉指令，`auto_action_allowed` 固定為 false。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_position_health.py --sample --format json
```

可由 paper baseline 建立 fail-closed health baseline；缺 entry thesis、invalidation、holding horizon 或 review date 時固定為 `WATCH`，並列為人工必填欄位。此命令不寫正式持倉，也不允許自動 action。

```powershell
.\.venv\Scripts\python.exe scripts\build_position_health_baseline.py --paper-baseline <paper-baseline.json> --output <health-baseline.json>
```

目前支援的 allocation method 為 `equal_weight`、`score_weight` 與 `inverse_volatility`。`max_position_weight_bp` 只會限制單一部位上限，不會自動把超出的權重重新分配到其他股票；買不起最小 lot 或套用上限後的現金差額會留在 `residual_cash` 與 diagnostics。Virtual trace 支援 `created`、`submitted`、`partially_filled`、`filled`、`rejected`；`cancelled`、零股、買賣價差、完整撮合與 gap actual execution model 仍是後續 execution-model residual。

V1.9 後，可用本地 MCP server `twstock-evidence-access` 讓支援 MCP 的 Agent 查詢 evidence。這個 server 只包裝 `AgentEvidenceAccessService`，使用 read-only SQLite URI / `PRAGMA query_only=ON` 與既有 read-only repository；它不建立 schema、不寫 DB、不修改策略、不下單、不套用 lifecycle action。若 DB 或 table 不存在，輸出會在 `diagnostics` 回報，檔案不會被建立。

```powershell
.\.venv\Scripts\python.exe mcp_servers\evidence_access_server.py
```

MCP tools：

- `get_agent_permission_model`：回傳 read-only role、allowed / denied actions、DB policy 與 lifecycle policy。
- `get_ai_report_template`：回傳 evidence-only report template，要求引用 evidence rows、quality、warnings、source trace 與 limitations。
- `query_evidence_events`：查 evidence events，必要時包含 forward outcomes；支援 symbol、event type、decision date / date range、limit、window days。
- `summarize_forward_evidence`：依 event type / family / source / regime / sector / profile / score bucket / liquidity / data quality 彙總 forward outcomes。
- `query_research_runs`：唯讀查 Research Run Registry metadata，可依 run id、run type、strategy id 過濾。
- `query_portfolio_review_evidence`：查已保存 live research gap observation 與 lifecycle evidence rows；Portfolio Review snapshot 本身不是 V1.9 的持久化查詢物件。

輸出判讀：

- `access_boundary.mode` 應固定為 `read_only`，`writes_allowed=false`。
- `limitations` 必須與 report 一起保留；結果不是買賣建議，不是策略變更，也不是 lifecycle action。
- `diagnostics` 有值時代表資料源、table 或查詢條件不足；不得用空結果推論策略有效或失效。
- AI report 只能把查到的 evidence rows 整理成摘要與審核問題；LLM thesis 不是 primary evidence。

V2.0 前可用 `scripts\inspect_pre_v2_readiness.py` 做非排程 readiness 檢查。此 CLI 只讀既有 evidence DB、Research Run DB、multi-day record markdown 與 scheduled dry-run `latest_status.json`，不建立 schema、不寫 evidence、不啟用 scheduler；missing DB / table 只會回 diagnostics。它會把 weekly history、multi-day dry-run、source gaps 與 read-only Agent report sample 分成 `ready`、`waiting_for_time`、`action_required`，且 `production_scheduler_allowed` 永遠是 `false`。JSON／Markdown 也會明確輸出 `formal_credit_authorized=false`，避免把 owner-approved projection 的 `ready` 誤讀成 Formal credit 已授權。CLI 現在與 Workbench 共用 `WEEKLY_EVIDENCE_HISTORY_PROJECTION_PATH`；也可用 `--approved-weekly-history-projection <path>` 明確指定同一份 `approved-weekly-history-projection.v1`，明確參數優先於環境變數。projection 只供 UI／readiness 揭露，不授予 formal credit。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_pre_v2_readiness.py --db-path <working-copy-db> --decision-date 2026-07-06 --multi-day-record-path docs\06_qa\POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md --json-output
.\.venv\Scripts\python.exe scripts\inspect_pre_v2_readiness.py --db-path <working-copy-db> --decision-date 2026-07-06 --markdown --report-output output\qa\pre_v2_readiness.md
# 與 Workbench 使用同一份 owner-approved projection（只讀）
.\.venv\Scripts\python.exe scripts\inspect_pre_v2_readiness.py --approved-weekly-history-projection <projection.json> --json-output
```

`waiting_for_time` 代表仍需真實多週 / 多日累積，不可用 fixture、單次 smoke 或無證據的手動改表替代。V2 closeout 可接受修正後歷史觀察日，但必須保留同日或指定觀察日的 dry-run report / scheduled `latest_status.json`；source-gap closeout 只會在 `dry_run=true`、`writes_evidence_db=false`、`source_coverage_blocking_gaps=[]`、`pipeline_blocking_gaps=[]` 且 `scheduler_readiness_after=ready_for_manual_confirm` 時採信。此 fallback 只解除 readiness inspector 的 source-gap 紅點，不代表正式 DB 已 confirm、scheduler approval、production readiness、投資有效性或交易建議。

V2.0 Phase 1 / Phase 1.5 可用 `scripts\inspect_v2_workbench_prototype.py` 檢查 read-only Workbench prototype 輸出。這個 CLI 保留 `--sample`，也可用受控 `--db-path` / `--decision-date` 讀 existing read-only sources：Pre-V2 readiness、Daily Decision durable snapshot、AgentEvidenceAccess summary 與可選 Historical Replay JSON summary。Current Workbench 與 Pre-V2 查詢上限固定為台灣市場今日；若 DB 內有未來 Decision Desk row，會保留 raw 診斷／blocker，畫面只採用最後一筆安全 snapshot，不把未來 row 當成 current evidence。它不寫 evidence、不掛主 UI、不建立 scheduler、不下單、不套用 lifecycle action，也不重算 scoring、portfolio、backtest 或 lifecycle 狀態。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_v2_workbench_prototype.py --sample --format json
.\.venv\Scripts\python.exe scripts\inspect_v2_workbench_prototype.py --sample --format markdown
.\.venv\Scripts\python.exe scripts\inspect_v2_workbench_prototype.py --sample --replay-summary-json D:\Min\Python\Project\FA_Data\output\evidence_pipeline\historical_replay_reference_fix_20260706\historical_replay_2026-01-06_2026-07-06_reference_fix.json --format markdown
.\.venv\Scripts\python.exe scripts\inspect_v2_workbench_prototype.py --db-path <working-copy-db> --decision-date 2026-07-06 --multi-day-record-path docs\06_qa\POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md --format json
.\.venv\Scripts\python.exe scripts\inspect_v2_workbench_prototype.py --db-path <working-copy-db> --decision-date 2026-07-06 --replay-summary-json D:\Min\Python\Project\FA_Data\output\evidence_pipeline\historical_replay_reference_fix_20260706\historical_replay_2026-01-06_2026-07-06_reference_fix.json --format markdown
```

輸出會包含：

- `access_boundary.mode=read_only`、`writes_allowed=false`、`production_scheduler_allowed=false`。
- `source_mode=sample_only`、`sample_plus_historical_replay`、`read_only_sources` 或 `read_only_sources_plus_historical_replay`。
- 「今日待判讀」、Evidence mode、market context、portfolio / watchlist summary、Daily Checklist、warnings。
- 若 `--db-path` 缺檔、缺 `decision_desk_snapshots` table 或找不到指定 decision date snapshot，輸出會保留 read-only dashboard 並在 warnings / review items 揭露 degraded source；若發現 future decision date，會顯示 `decision_desk_snapshot_future_dated` 與排除診斷；CLI 不會建立 DB 或 schema。
- 若讀取 `_reference_fix` replay JSON summary，會揭露 simulated scheduler、source gap、source gap coverage、payload gap、outcome maturity、benchmark coverage、industry benchmark coverage、missing industry benchmark、pending future-data 與「方向正確但尚未 production-ready」限制。

V3 score effectiveness audit 可用 `scripts\inspect_score_effectiveness.py` 檢查既有 Evidence Event / Forward Outcome 中，`TotalScore` raw bucket 與 forward outcome 的唯讀關係。第一版支援 `--sample`、`--format json|markdown`、`--output`、`--min-sample-size`，也可用明確 `--db-path` 以 SQLite `mode=ro` / `PRAGMA query_only=ON` 讀既有 evidence DB。這個 CLI 只做 read-only aggregation，不寫 production DB、不提供 `--confirm`、不啟用 scheduler、不改 `ScoringEngine`、不改推薦權重、不改 threshold，也不訓練 ML model。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_score_effectiveness.py --sample --format json
.\.venv\Scripts\python.exe scripts\inspect_score_effectiveness.py --sample --format markdown --output output\qa\score_effectiveness_sample.md
.\.venv\Scripts\python.exe scripts\inspect_score_effectiveness.py --db-path <working-copy-db> --format json --min-sample-size 10
```

輸出固定保留 `0-40`、`40-50`、`50-60`、`60-70`、`70-80`、`80-100` 六個分數區間，即使該 bucket 沒有樣本也會顯示 empty bucket。每個 bucket 會列出樣本數、ready / pending / missing outcome、各 horizon 的 forward return bp、benchmark excess bp、industry excess bp、max drawdown bp、win rate bp、warnings 與 limitations。`access_boundary.writes_allowed=false`、`production_scheduler_allowed=false`、`investment_effectiveness_claim=false` 與 `ml_training_allowed=false` 必須保留；結果只能用於研究覆盤，不能解讀為買賣建議、投資有效性證明、threshold promotion 或 ML production readiness。

Phase 2 起，Qt 主 UI 新增 `決策工作台` 分頁作為 read-only Unified Decision Workbench MVP shell。2026-08-14 後，總覽第一屏先顯示「今日行動中心」與單一下一步導覽，再顯示今日重點帶、語意色摘要卡、今日待判讀、背景證據流、只讀 Action Items 與 Inspector；這些導覽按鈕只切換既有工作區。操作節奏、Evidence mode / data quality、Daily Checklist 與 warnings / degraded source 改成可收合區塊，需要時再展開。畫面只透過 `WorkbenchSourceService` 取得 `WorkbenchDashboardDTO`，不直接讀 SQLite、不寫 DB、不啟用 scheduler，也不重算 scoring、portfolio、backtest 或 lifecycle。若預設 `_reference_fix` replay JSON summary 存在於 `OUTPUT_ROOT/evidence_pipeline/historical_replay_reference_fix_20260706/`，主 UI 會自動把 JSON summary 傳入 WorkbenchSourceService；這仍只是讀 summary，不會讀 replay DB 或執行 replay。

操作與判讀：

- 入口：執行 `.\.venv\Scripts\python.exe ui_qt\main.py`，開啟頂層 `決策工作台` 分頁。
- 今日重點帶與摘要卡：第一屏最上方會用醒目色帶彙總待判讀、人工處理、等待真實時間與 warnings。橘色代表需要人工注意或等待真實時間，紅色代表 warning / blocked / missing 類高風險，藍色代表資訊或 manual observed，綠色代表 ready / observed / passed。顏色只用來輔助掃描，仍需依 Inspector 與原始 source trace 判讀。
- 操作下鑽：`開啟市場總覽`、`開啟市場探索`、`開啟證據覆盤`、`開啟持倉管理` 只會切到既有 Market Exploration / Daily Decision、Research Lab / 證據覆盤、Portfolio 頁面；Workbench 不嵌入或建立第二份 Decision Desk。它們是 expert drill-down，不會從 Workbench 觸發寫入、scheduler、回測或 lifecycle action。Action Items、今日待判讀與背景證據流的 row drill-down target 也走同一個舊頁導向 contract：`daily_decision` 切到「市場探索 > 市場總覽」、`portfolio_review` 切持倉管理、`evidence_review` / `evidence_mode` 切證據覆盤。
- Status strip：檢查 Daily Decision durable snapshot、Evidence gate、Data quality 與 Production Scheduler；scheduler 應維持 `off` / `production_scheduler_allowed=false`。
- 今日待判讀：只列出需要人工 review 的 watchlist trigger、portfolio alert、risk prompt 或 readiness gap；它不是買賣建議，也不會產生下單動作。
- 詳情檢視 / Inspector：點選今日待判讀、背景證據流或 Action Items 的任一列，右側會用狀態徽章與三個分區顯示完整內容：「重點摘要」看標題與 summary，「來源與邊界」看 source trace、degraded reason、drill-down target 與 read-only 保證，「診斷訊號」看 diagnostics token。表格只保留掃描欄位；完整證據不要在表格橫向捲動找，改看 Inspector。
- 背景證據流：只彙整既有 DTO / service payload，包括 Daily Decision snapshot、Evidence Review readiness、Portfolio alerts 與可選 replay summary diagnostics。清單表格只顯示「證據來源 / 狀態 / 摘要」，完整 source trace、degraded reason、diagnostics 需點列後在 Inspector 查看。這個區塊不讀 replay DB、不重跑 Evidence Pipeline、不重新判斷 portfolio 或 scoring。若清單為空，文案會提醒只是 DTO payload 為空，不代表 gate 通過；若來源降級，文案會要求依 source trace / diagnostics 人工檢查，不補值、不重跑 pipeline。
- 背景證據流也會顯示 `Scheduled morning pipeline`，來源是 `ScheduledEvidenceStatusService` 唯讀讀取 `OUTPUT_ROOT/scheduled/*/latest_status.json`、recommendation snapshot 檔、同日人工 recommendation result fallback 與 evidence dry-run report 檔。它會顯示最新 scheduled 或 manual recommendation result id、推薦筆數、recommendation snapshot 觀測天數、manual recommendation 觀測天數、evidence dry-run 觀測天數與 scheduled recommendation/evidence 共同觀測天數；`manual_observed` 只解除人工判讀的資訊缺口，不會把 scheduled 狀態標成 passed，也不會自動解除正式 multi-day gate。
- 只讀 Action Items：只顯示人工待處理事項；清單供排序與掃描，完整 `queue_group`、`severity`、`source_label`、`source_trace`、`degraded_reason`、`drilldown_target` 與 `write_intent=false` 可點列後在 Inspector 查看。Composer 會先依 severity，再依 queue group 與 source 排序，讓持倉警示、風險提示、觀察清單與 readiness gap 更容易掃描。空狀態不代表可以交易或 gate 已通過；降級狀態只供人工覆盤排序，不是買賣建議。Workbench 不建立 action item repository、不 append DB、不標記完成、不套用 lifecycle action。
- 操作節奏：只從 `WorkbenchDashboardDTO.operating_loop_steps` 顯示 daily first-look、manual queue、weekly review history、multi-day dry-run、manual review note 與 scheduler gate。這個區塊預設收合；展開後以直列 timeline card 呈現步驟編號、狀態 badge、摘要與 linked item chips，避免水平捲動。長的 source trace、人工提示與 `write_intent=false` 會收在「展開細節」中；Workbench 不會把項目標記完成、不會寫 DB、不會補 weekly history / multi-day dry-run、不會啟用 scheduler。
- Evidence mode / data quality：讀取 DTO 內的 evidence summary 與 diagnostics；上方以兩張摘要卡拆分「邊界與 Gate 摘要」及「覆蓋率與缺口」，下方表格只保留證據、狀態與摘要，完整 diagnostics 需點列後在 Inspector 查看。若 payload 帶 replay summary，會揭露 `simulated_scheduler`、source gap / coverage、payload gap、outcome maturity、benchmark coverage、industry benchmark coverage、missing industry benchmark 與 pending future-data 限制。2026-07-06 `_reference_fix` summary 的目前判讀是市場 benchmark coverage 已補齊成熟 outcomes，但 screening matrix source gap、產業 benchmark 大量缺口與 pending future-data 仍阻擋 production readiness；這不是投資有效性結論。
- Workbench > Evidence / Research Console：此子頁固定分成 Safety Boundary、Development Pipeline、Evidence / Source Gates 三區。Safety Boundary 必須顯示 `formal_oos_allowed=False`、`production_blend_alpha_bp=0`、Production ML disabled、正式 Recommendation / Portfolio 維持 Rule-only，以及 promotion / retrain / scheduler / trading disabled。Development Pipeline 只複製顯式 `RESEARCH_CONSOLE_PROJECTION` 指向的 sanitized `ResearchConsoleProjection.json`，顯示 Dataset V0、Rule Development Baseline、ML Development Challenger、E2E identity、row / feature count、label maturity、artifact citation 與 blockers；缺欄使用 `Missing / Unknown`，不補零。Evidence / Source Gates 固定保留 EV1–EV5、13 個 P0 source、獨立 Broker lane、P0 Data Source Control Center 與 Artifact Inspector；Control Center 逐列顯示 governance/machine/audit/decision status、row 數、blockers 與 `downstream_eligibility`，沒有 audit 時仍顯示 13 列 `contract_only`，不把 development、candidate、provisional、degraded、fixture 或 replay 冒充 formal accepted / forward evidence。頁面唯一控制是「重新載入唯讀 projection」，沒有 Apply、Promote、Retrain、Blend、Accept Source 或 Trade。
- Research Console 排錯：未設定 `RESEARCH_CONSOLE_PROJECTION`、檔案不存在、JSON/schema 不合法時，頁面仍可開啟並顯示 `Missing` 或 `degraded`；若 projection scope 不是 exact `historical_research_seen_development_data`，或宣稱 formal OOS、非零／非整數 alpha、promotion eligible、缺少 canonical apply flag、出現額外 flag、任一 flag 不是 literal `false`，service 會以 `projection_boundary_violation` fail-closed，不套用該內容。`lineage.generated_at` 必須是含時區的 ISO-8601；缺少、格式錯誤、超過未來 5 分鐘或距目前超過 7 天時，分別顯示 `projection_generated_at_missing`、`projection_generated_at_invalid`、`projection_generated_at_future` 或 `projection_stale`，保留 sanitized identity 供排錯但整體固定降級，不代表 formal elapsed day。E2E row 的 artifact hash 是實際 projection bytes 的 SHA-256；injected mapping 沒有實體檔時保持 Unknown。啟動與重新載入只讀 JSON，不掃描 development／正式資料目錄、不建立 SQLite 連線、table、directory 或 artifact。
- 工程預演狀態 / Evidence Rehearsal：在「Evidence mode」下方查看注入的 `EvidenceRehearsalDashboard`。此唯讀區塊固定揭露「工程／Replay／Shadow；不是 forward evidence」、rehearsal tier、coverage、blockers、是否提供 Shadow comparison 與 `Forward handoff：pending`。coverage 會逐來源列出 observed、missing、degraded、future-blocked 與 immature-label 計數；`missing`、source outage 或 `insufficient_sample` 必須維持已阻擋／預演狀態，不得被畫成 clean、ready 或正式通過。這個區塊沒有 apply / promote 按鈕，不能寫入 DB、啟用 scheduler、改變 Advice 或把 replay / shadow 結果視為 forward evidence；要補齊問題時，只能依 blocker 回到既有人工、資料授權或真實時間流程處理。
- Daily Checklist：以 status card 顯示 freshness、Evidence gate、multi-day dry-run、manual review 與 scheduler write-mode 等 gate，內容可換行，不再以寬表格呈現。Phase 0 weekly history 以 readiness inspector 的 live 值為準：未設定 approved projection 時為 `0/3 waiting_for_time`；projection 只作 UI 揭露，不能授予 formal credit。multi-day dry-run record 已為 `3/3 ready`，但 Week 2 / Week 3 與 manual review / action-item rhythm 只能繼續靠真實時間累積，不能用 fixture、單次 smoke、手動改表或 replay 補齊。
- Warnings / degraded source：missing DB、missing table、snapshot missing、replay limitation 或 Agent sample limitation 都會以 warning 保留；Warnings 會依唯讀 / Phase Gate、缺漏來源、Replay / 模擬資料、資料品質、需要人工覆盤與其他警示分組，每組預設顯示前三項，其他項目可展開查看。不要手動補空資料或改表讓畫面變綠。

Replay summary 只能使用 JSON summary；不得把 replay DB 直接交給 prototype CLI 或 Qt Workbench。`--db-path` 建議使用 working-copy DB 或明確允許的 read-only source path；missing / degraded source 是要被呈現的 evidence gap，不可手動補 fixture 當作 gate 通過。Workbench CLI 與 Qt shell 都是 V2.0/V2.1 資訊架構與 read-only contract 檢查，不代表 production scheduler approval，也不是交易建議。

目前 replay summary 分析數字（讀自 `historical_replay_2026-01-06_2026-07-06_reference_fix.json`）：118 個交易日、118,056 events、472,224 outcomes；成熟 outcomes 為 380,736，pending future-data 為 91,488。成熟 outcomes 的市場 benchmark coverage 為 380,736/380,736、missing benchmark 為 0；產業 benchmark coverage 為 2,245/380,736、missing industry benchmark 為 378,491；`source_missing_screening_matrix` 出現在 118/118 replay days，另有 missing event price 216。這表示 Workbench 的 read-only evidence direction 是正確的，因為 benchmark 全缺問題已解除且缺口可被揭露；但仍不能宣稱 production readiness、投資有效性或啟用 scheduler。

2026-07-06 closeout 的參考結果：在 ignored working-copy DB 與 output-root mirror 中，source gaps 為 `ready`、read-only Agent report sample 為 `ready`、Evidence Review UI smoke passed、all-source working-copy confirm smoke repeat=2 idempotency passed；當日整體仍為 `waiting_for_time`，因 weekly history `0/3`、multi-day dry-run `1/3`。2026-07-08 已將 multi-day dry-run record 累積至 `3/3 ready`；weekly history 與 manual review / action-item rhythm 仍未完成。這個結果不代表正式 DB 已 confirm，也不代表 production scheduler 可啟用。

Working-copy smoke 會先確認 source DB 與 working-copy DB 不是同一路徑；若 working-copy DB 不存在，會以 `shutil.copy2` 從 source DB 複製一份，再只對 working-copy DB 執行 confirm smoke。預設 repeat 至少 2 次，用 event / outcome counts 檢查 idempotency；source DB 應維持 read-only。readiness evaluator 會彙總 source coverage、smoke report 與 dashboard availability；若未提供具名 owner 簽署的 `evidence-production-scheduler-approval.v1`，即使其他輸入沒有 blocking gap，仍會保留 `production_scheduler_approval_missing`／`invalid` 並維持 `production_scheduler_allowed=false`。只有該 artifact 的七項 checks 全部通過且未過期時，才可能回報 `operational_production`；正式排程前仍需人工 review `docs/06_qa/POST_V1_EVIDENCE_PRODUCTION_SCHEDULER_APPROVAL_CHECKLIST_2026_07_07.md` 的 source coverage、diagnostics report、backup path、rollback path 與 manual approval steps。

Live vs Research Gap linkage CLI 用來把 portfolio position source trace、Evidence Event / Outcome 與 saved source metadata 串成 gap observation。這是 evidence，不是 action；不修改持倉、不修改 Research Run、不做 lifecycle action，也不是完整實帳歸因。沒有真實交易與人工 override 記錄時，只能解讀為 research / simulated gap。Symbol / date fuzzy match 只會列為 low-confidence candidate，不會當作 confirmed evidence link。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_live_research_gap.py --observation-date 2026-07-03 --json-output
.\.venv\Scripts\python.exe scripts\capture_live_research_gap.py --observation-date 2026-07-03 --dry-run --json-output
.\.venv\Scripts\python.exe scripts\capture_live_research_gap.py --observation-date 2026-07-03 --confirm --db-path <working-copy-db> --json-output
```

Signal Decay Monitor CLI 用來檢查已保存 forward evidence 與 live gap observation 是否在近期相對長窗轉弱。v1 支援 `event_type`、`event_family`、`strategy_version`、`profile` scope；`factor_name` scope 尚未完成。Research Lab `Evidence Review` 已提供唯讀 Signal Decay 子頁。輸出的 `demote_candidate` / `retire_candidate` 只是 lifecycle proposed payload，不會自動修改策略狀態、策略版本或持倉。樣本不足時只會標示 `insufficient_sample`，不能解讀為策略失敗；缺 benchmark 或 live gap evidence 時會降低 confidence。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_signal_decay.py --observation-date 2026-07-03 --json-output
.\.venv\Scripts\python.exe scripts\capture_signal_decay.py --observation-date 2026-07-03 --scope event_type --scope-id recommendation_included --dry-run --json-output
.\.venv\Scripts\python.exe scripts\capture_signal_decay.py --observation-date 2026-07-03 --scope all --confirm --db-path <working-copy-db> --json-output
```

`capture_signal_decay.py` 預設 dry-run；`--confirm` 必須指定 explicit `--db-path`，疑似正式 DB 仍需額外 `--allow-production-db-confirm`。一般 QA 與人工審核應使用 working-copy DB。

Decision Quality Review CLI 用來建立週 / 月 / custom 流程覆盤。它只檢查 source trace、journal linkage、manual override、portfolio alert、large live gap、signal decay candidate 與資料品質是否已有覆盤證據；輸出的 score 是 process quality bp，不是投資能力、不是交易建議，也不是責備使用者。Research Lab `Evidence Review` 已提供唯讀 Decision Quality 子頁；CLI 與 repository 仍是資料來源。

```powershell
.\.venv\Scripts\python.exe scripts\inspect_decision_quality.py --start-date 2026-06-01 --end-date 2026-06-30 --json-output
.\.venv\Scripts\python.exe scripts\capture_decision_quality_review.py --review-type weekly --start-date 2026-06-24 --end-date 2026-06-30 --dry-run --json-output
.\.venv\Scripts\python.exe scripts\capture_decision_quality_review.py --review-type monthly --start-date 2026-06-01 --end-date 2026-06-30 --confirm --db-path <working-copy-db> --json-output
```

`capture_decision_quality_review.py` 預設 dry-run；`--confirm` 必須指定 explicit `--db-path`，疑似正式 DB 仍需額外 `--allow-production-like-db`。缺 journal、缺 source trace 或 sample size 不足都只代表 review gap / warning，需要人工判讀。

V1.3 / V1.4 Evidence Operations weekly review CLI 用來把 scheduler readiness、Decision Quality、Signal Decay 與 action item 彙總成每週人工覆盤包，並可在 V1.4 以 append-only weekly review history 保存人工覆盤快照。它預設只讀並輸出 JSON 或 Markdown；`production_scheduler_allowed` 仍固定為 `false`。樣本不足時 status 會是 `coverage_only`，只能要求繼續累積 evidence，不可解讀成策略結論。Signal Decay 的 `demote_candidate` / `retire_candidate` 只會列為 `manual_lifecycle_candidates`，每筆 `apply_action=false`，不會自動修改策略版本。

```powershell
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date 2026-06-24 --end-date 2026-06-30 --db-path <working-copy-db> --json-output
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date 2026-06-24 --end-date 2026-06-30 --db-path <working-copy-db> --plan-action-items --json-output
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date 2026-06-24 --end-date 2026-06-30 --db-path <working-copy-db> --confirm-action-items --save-history --action-owner human --json-output
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date 2026-07-01 --end-date 2026-07-04 --db-path <working-copy-db> --list-history --json-output
```

`--plan-action-items` 只預覽 open Decision Quality item 會形成哪些 action item，不寫入 DB。`--confirm-action-items` 才會 append-only 寫入指定 DB，且必須提供 explicit `--db-path`；CLI 會 canonicalize 實際 DB path 並比對 configured／環境 `DATA_ROOT` 與預設正式 root，故 `--data-root` 不可繞過 production-like DB 拒絕，也沒有 allow 旗標。正式 weekly review 要將 `--confirm-action-items --save-history --action-owner <owner>` 合併於同一次 working-copy 操作，讓 snapshot 保存 owner、planned action 與 created / skipped 結果。`--save-history` 會把當次 weekly review payload、hash、status、scheduler readiness 與 production scheduler disabled 邊界保存到 `evidence_operations_weekly_reviews`；`--list-history` 只讀取已保存歷史，缺 DB / table 時回 diagnostics，並在 config 初始化前完成純 path 解析，絕不建立 DB parent、log directory 或 SQLite 物件。一般覆盤應先用 `smoke_evidence_pipeline_working_copy.py` 的 copy/guard 建立 working-copy DB。

Research Lab `Evidence Review` 分頁在 V1.4 新增「覆盤歷史」子頁，用來唯讀檢查已保存 weekly review history 的週期、status、scheduler readiness、Decision Quality / Signal Decay 數量、manual lifecycle candidate 數量與 warnings。此子頁只讀 dashboard service，不建立週報、不寫 action item、不啟用 scheduler，也不自動套用任何 lifecycle action。

若 weekly history 保存在隔離 working-copy DB，主 UI 不會自行掃描或合併該 DB。可由具名 owner 建立外部 `approved-weekly-history-projection.v1` JSON，並在啟動 UI 前設定 `WEEKLY_EVIDENCE_HISTORY_PROJECTION_PATH` 為該檔案的絕對路徑；決策工作台只讀取其中 `status=approved_weekly_review`、具 `review_id`、`review_hash`、週期、`owner_role` 與 `approved_at` 的列，顯示其累積數。projection 必須固定 `formal_credit_authorized=false`，只供 UI 揭露 weekly Gate 進度，不寫入正式 DB、不授權 formal credit、不啟用 scheduler 或交易。

Workbench 的證據門檻摘要會另外列出 sidecar 中仍為 `pending_human_review` 的期數與日期區間（最多預覽前三期），並同時顯示 `formal_credit_authorized=false`。因此 `3/3` 是已觀測／具名核准 projection 的數量，不代表 pending 週期已核准，也不代表 Formal 或 production scheduler 已開啟。
若未設定該環境變數，Workbench 會在 warnings 與 weekly history 詳情明示 `approved_weekly_history_projection_not_configured`，並只計算正式 evidence DB 內可讀的 legacy review history；這不代表 projection 已自動核准，也不會把 pending sidecar 轉成 Gate credit。

若 sidecar 已累積 `pending_human_review` 期段，可先用下列唯讀命令產生具名 owner／reviewer 的交接輸入包：

```powershell
.\.venv\Scripts\python.exe scripts\build_evidence_weekly_approval_input.py `
  --sidecar-path <WEEKLY_COLLECTION_SIDECAR_DB> `
  --output-json <TEMP_APPROVAL_INPUT_JSON> `
  --markdown-output <TEMP_APPROVAL_INPUT_MD> `
  --owner-role <NAMED_OWNER_ROLE> `
  --reviewer-role <NAMED_REVIEWER_ROLE>
```

這個命令只對明確指定的 sidecar 做 SQLite `mode=ro`／`PRAGMA query_only=ON` 讀取，驗證
collection id、期間、來源路徑／SHA-256、payload 與錯誤欄位，並輸出
`evidence-weekly-approval-input.v1`。輸出中的 owner／reviewer 只是交接欄位；即使填入角色，
每列 `review_decision`、`reviewed_at` 與 `review_note` 仍需人工完成，packet 仍固定
`candidate_only=true`、`formal_credit_authorized=false`、`production_scheduler_allowed=false`、
`downstream_eligibility=none`、`write_performed=false`。不要把此檔案直接改名或送入
`approved-weekly-history-projection.v1`／Formal loader；人工完成審核後，必須沿既有 governed
path 另外產生相容的 approved projection。輸出路徑不可覆寫 sidecar、`twstock.db`，且 parent
directory 必須先存在；此流程不寫 sidecar、正式 Evidence DB、Registry 或 scheduler。

Report evidence boundary 固定為：This report is research evidence only. Close-to-close forward return is not executable live performance. No trading recommendation is produced.

### 9.9.2 V2.2 Weekly Review Runbook

V2.2 的固定三週人工覆盤格式與 working-copy 操作順序見 `docs/07_guides/V2_2_WEEKLY_REVIEW_RUNBOOK.md`。每週必填週期日期、資料 freshness、dry-run 狀態、warnings、reviewed / dismissed / follow-up、owner、working-copy DB path、`--save-history` 結果與下一步；少任何一項都不能計入三週 Gate。先以既有 copy/guard 建立隔離副本，再產生唯讀週報；取得明確人工核准後，在同一次 working-copy 操作使用 `--confirm-action-items --save-history --action-owner`，最後以 `--list-history` 唯讀核對。不要對正式 DB 保存 history；production-like DB 強制拒絕，沒有 `--allow-production-like-db` 可用。

截至 2026-07-12，Week 1 已完成並保存於隔離 working-copy，weekly history 為 `1/3 waiting_for_time`；multi-day dry-run 為 `3/3 ready`，scheduler 尚未獲核准且 `production_scheduler_allowed=false`。因此不可建立 V2.2 formal closeout；replay、fixture、raw scheduled report、單次 smoke 或手動補表都不能補足 Week 2 / Week 3。三週紀錄完成後，仍需人工完成 backup / rollback / recovery 演練與 scheduler approval package；日後若 scheduler 獲准，也只能保存 evidence，不得自動交易或套用 lifecycle action。

### 9.9.3 Evidence Review Manual Smoke / Multi-day Dry-run

Evidence Review UI 完成後，正式 scheduler 前仍需要人工 closeout：

- `docs/06_qa/POST_V1_EVIDENCE_REVIEW_UI_SMOKE_CHECKLIST_2026_07_12.md`：人工檢查 Forward Evidence、Live vs Research Gap、Signal Decay、Decision Quality、boundary banner、empty / degraded / insufficient sample states、read-only guarantee 與無買賣建議語言。
- `docs/06_qa/POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md`：記錄 3-5 個交易日的 data update status、source coverage、dry-run pipeline、working-copy confirm smoke、events / outcomes / summary / warnings / blocking gaps、dashboard review 與人工 decision。
- `docs/06_qa/POST_V1_EVIDENCE_SCHEDULER_APPROVAL_SOP.md`：描述 Manual run → Multi-day dry-run → Working-copy confirm smoke → Dashboard review → Manual approval checklist → Production scheduler design → explicit approval 後才 implementation。

這些文件是 production scheduler 前的 QA scaffold；目前只允許受控 market data quick update、read-only freshness 與 evidence dry-run 範圍。現有 Windows Task Scheduler 會先執行非 UI 快速資料更新，再跑 data freshness check 與 evidence pipeline dry-run，不是 production confirm scheduler。任何 production confirm 未來都需要 backup、rollback、diagnostics 與 explicit human approval；scheduler 不得自動 lifecycle action，也不得自動交易。

### 9.9.4 Evidence Scheduled Dry-run Wrappers

`scripts/scheduled/` 提供 safe scheduled wrappers，用於每日自動產生「可人工檢查」的 freshness 與 evidence dry-run 輸出。PowerShell `.ps1` 註冊路徑曾被 local execution policy 擋住，因此目前採 CMD wrapper + Windows 內建 `schtasks.exe`；不要使用 `Set-ExecutionPolicy`。

```cmd
scripts\scheduled\register_baldr_scheduled_tasks.cmd dryrun
scripts\scheduled\register_baldr_scheduled_tasks.cmd register
scripts\scheduled\register_baldr_scheduled_tasks.cmd register-all
scripts\scheduled\query_baldr_scheduled_tasks.cmd
scripts\scheduled\unregister_baldr_scheduled_tasks.cmd unregister
```

register 只註冊 12 個每日 task；register-all 會在同一個受控操作中註冊
12 個每日 task 與每週日 collection task。兩者都會先檢查選定的 .cmd
wrapper 是否存在，缺檔時在呼叫 schtasks 前停止，不會留下指向不存在檔案的
task。執行前仍須先以 dryrun 檢查 repo root、時間與 action，執行後再用
registration inspector 與真實 terminal history 驗證；本段不代表目前 host 已完成註冊。

目前 Windows Task Scheduler task：

- `baldr-data-update-quick-daily`：每日本機時間 04:20，走非 UI 快速更新路徑，補最近工作日窗口的 TWSE / TPEX 每日股價、大盤、產業、券商分點、SQLite 同步與必要的技術指標增量；輸出位於 `<OUTPUT_ROOT>/scheduled/data_update_quick/`。若 TWSE 的 `ALL` 與 `ALLBUT0999` 都精確回覆「很抱歉，沒有符合條件的資料！」，該日會列入 `no_data_skipped_dates`，task 會以 `passed_with_warnings` 記錄警告並繼續同步；HTTP、timeout、解析錯誤、未來日期或其他非完整文案回覆仍是 `failed`。若 TPEX 當日或窗口內日期抓取失敗，task 會繼續可完成步驟並以 `passed_with_warnings` 保存 `TPEX 每日股價缺少日期：YYYYMMDD`，不再把只有既有 skipped CSV 的情況誤判為完整成功。
- `baldr-data-freshness-check-daily`：每日本機時間 05:00，唯讀檢查 SQLite / `DATA_ROOT` freshness，只寫 `<OUTPUT_ROOT>/scheduled/data_freshness/latest_status.json` 與 logs。除了 SQLite `daily_prices` / `technical_indicators` 最新日期，也會反查同一最新日的 `daily_price/YYYYMMDD.csv` 與 `daily_price_tpex/YYYYMMDD.csv`；若 SQLite 最新但 TPEX 原始日檔缺失，狀態會是 `degraded`。freshness 也會讀取最近一次 `data_update_quick/latest_status.json`；若快速更新為 `failed`、status 檔遺失或 status 日期未達預期工作日，即使資料年齡仍在容許範圍，freshness 仍會是 `degraded` 並列出相應 warning。
- 若正式 `OUTPUT_ROOT` ACL 不允許 freshness status／log 寫入，owner 可在受控 Task Scheduler 執行環境明確設定 `BALDR_FRESHNESS_STATUS_PATH`；未設定 `BALDR_FRESHNESS_LOG_PATH` 時 wrapper 會將 `.log` 放在 status path 旁。UI 另設定 `DATA_FRESHNESS_STATUS_ARTIFACT` 讀取該明確 status 檔。這只是把 read-only 觀測輸出導到已核准可寫路徑，不會建立或修改 DB、source acceptance、Evidence、Formal 或 broker 權限；未設定覆寫時仍使用既有 `<OUTPUT_ROOT>/scheduled/data_freshness/`。
- `baldr-recommendation-snapshot-daily`：每日本機時間 05:10，在 freshness check 後產生一筆 research-only recommendation snapshot，保存到 `<OUTPUT_ROOT>/recommendation/runs/`，並寫 `<OUTPUT_ROOT>/scheduled/recommendation_snapshot/latest_status.json`。status 會列出 `result_id`、`recommendations_count`、`screening_matrix_rows`、`why_not_payload_rows`、`liquidity_gate_payload_rows`、`writes_recommendation_result=true`、`writes_evidence_db=false`、`auto_trading=false` 與 `lifecycle_action=false`。它只保存推薦結果供 evidence dry-run 與 UI 判讀，不寫 production evidence DB、不改 portfolio、不自動交易、不自動 lifecycle。
- `baldr-evidence-pipeline-dry-run-daily`：每日本機時間 05:15，只執行 evidence pipeline `--dry-run`；scheduled wrapper 會把已解析的 `DATA_ROOT`、`OUTPUT_ROOT` 與 `DB_PATH` 明確傳給內層 pipeline，避免環境覆蓋時讀到另一套預設來源。scheduled status 會同時承接 freshness 與 pipeline `overall_status`。子程序 exit code 為 `0` 只代表正常完成並產生報告；只要 pipeline 為 degraded、warnings_count 大於 0、blocking gaps 非空，或 freshness 不是 passed，`latest_status.json` 的 `status` 就不會誤標為 passed。因 05:10 已先保存當日 recommendation snapshot，dry-run 可讀到最新 recommendation payload（含 screening matrix / why-not / liquidity gate payload，若當日推薦流程有產出）。輸出位於 `<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/`。2026-07-06 後，`latest_status.json` 會另外保存 pipeline summary 摘要欄位，例如 `pipeline_overall_status`、`pipeline_diagnostic_codes`、`source_coverage_warnings`、`recommendation_screening_matrix_available`、`recommendation_exclusion_payload_available` 與 `source_coverage_basis`；2026-07-09 後也會保存 `pipeline_warning_counts`、`pipeline_warning_unique_count` 與 `pipeline_warning_top_counts`，對應 markdown report 的 `Warning Summary` / `Warning Breakdown`，方便 read-only morning report 直接判讀 V1.7 payload readiness、warning occurrence 總量與 warning 分布。新版 status 另分開保存 `pipeline_natural_maturity_warning_counts`、`pipeline_actionable_warning_counts`、`natural_maturity_only` 與 `manual_action_required`；只有非自然 warning、error、blocking gap、缺少 pipeline summary 或 freshness 非 passed 才列為需人工處理，`insufficient_future_data` 仍是自然成熟度，不應以補跑或人工填值消除。安全旗標固定為 `dry_run=true`、`confirm=false`、`writes_evidence_db=false`、`production_scheduler_allowed=false`。證據覆盤的「排程狀態」會把 pipeline warnings 與 freshness warnings 分開顯示；若看到 `freshness warnings: 無` 但 `pipeline warnings` 有數量，代表資料新鮮度檢查沒有 warning，但 evidence dry-run 仍有來源品質或事件品質 warning。這些欄位只來自同次 dry-run stdout，不額外重跑 pipeline。
- `baldr-evidence-working-copy-smoke-manual`：不建立每日 task；只保留 manual-only script，必須人工指定 source DB 與 working-copy DB，且不得寫 source DB 或 default `DATA_ROOT/sqlite/twstock.db`。

Codex app 另外有一個 read-only daily automation：`baldr scheduled evidence morning report`。它每日本機時間約 05:30 只查詢 Task Scheduler 狀態、`latest_status.json`、最新 data update / freshness / evidence dry-run report 與必要 log 區段，並產生繁體中文摘要；它不重新執行 data update / freshness / evidence pipeline、不建立或修改 Windows Task Scheduler task。

明早檢查步驟見 `docs/07_guides/EVIDENCE_SCHEDULED_MORNING_CHECK.md`。Scheduler QA 紀錄見 `docs/06_qa/POST_V1_SCHEDULED_EVIDENCE_PIPELINE_QA_2026_07_12.md`；舊 PowerShell execution policy block 歷史見 `docs/06_qa/POST_V1_EVIDENCE_SCHEDULED_DRY_RUN_QA_2026_07_12.md`。

這些 wrappers 中只有 `baldr-data-update-quick-daily` 會寫 market data CSV / SQLite；evidence dry-run 與 Codex read-only 摘要不寫 production evidence DB、不跑 UI、不讀 UI state、不做 portfolio / lifecycle action，也不代表任何訊號或事件類型已被證明有效。

### 9.9.5 DEV-70 Development ML Data Inventory & Experiment Runner

DEV-70 提供獨立、Sanitized、Machine-Readable 的 ML 資料盤點 CLI (`scripts/inspect_development_ml_data_inventory.py`) 與 ML 實驗執行 CLI (`scripts/run_development_ml_experiment.py`)。其所有輸出皆限定於 TEMP 根目錄 (`validate_development_output_root`)，絕不寫入正式 DB、不改寫 Formal Acceptance 狀態，也不授權 Production Promotion。

1. **Development ML Data Inventory Inspection CLI**:
   盤點核心 20 個特徵、4 個標籤、MOPS 季報時間軸 (Availability Gate)、Broker/Fundamental 候選族群與 DEV-69 TWSE 微觀結構 5 個 Source 的訓練狀態與遮蔽原因。
   ```powershell
   .\.venv\Scripts\python.exe scripts/inspect_development_ml_data_inventory.py --manifest C:\Temp\technical_analysis_development_output\generations\terra-v0-canonical-2025-dev-20260714\manifest.json --dataset C:\Temp\technical_analysis_development_output\generations\terra-v0-canonical-2025-dev-20260714\dataset.json --output-root C:\Temp\technical_analysis_development_output
   ```

2. **Development ML Experiment Runner CLI**:
   執行具備不可變 Contract 的隔離 ML 開發實驗，支援特徵組合 (Feature Pack: `core_20`, `technical_only`, `price_only`, `price_technical`)、模型家族對比 (`linear_logistic`, `hist_gradient_boosting`) 與超參數 Grid 實驗。
   ```powershell
   .\.venv\Scripts\python.exe scripts/run_development_ml_experiment.py --manifest C:\Temp\technical_analysis_development_output\generations\terra-v0-canonical-2025-dev-20260714\manifest.json --dataset C:\Temp\technical_analysis_development_output\generations\terra-v0-canonical-2025-dev-20260714\dataset.json --output-root C:\Temp\technical_analysis_development_output --experiment-id exp-ablation-technical-v1 --feature-pack technical_only
   ```

安全旗標恆定為：`formal_oos_allowed=false`, `production_blend_alpha_bp=0`, `promotion_allowed=false`。


**報告匯出按鈕**：
- 在「實驗摘要」設有「匯出 Excel 報告」按鈕（僅在單股回測成功後啟用）。
- 在「批次結果」設有「匯出批次 Excel」按鈕（僅在批次回測成功後啟用）。
- 在「推薦回放」設有「匯出回放 Excel」按鈕（僅在推薦組合回測成功後啟用）。
- **安全設計**：所有匯出皆在背景線程（`TaskWorker`）執行，防止 UI 卡死，並採用臨時檔寫入後 `os.replace` 原子替換；替換失敗時既有報告保持不變。報告使用執行結果與參數快照，不重跑策略或摘要績效；equity curve 可接受 `日期`、`date` 或日期 index。若元數據缺失，會在「資料完整性」警示中顯示中文欄位名並保留原始代號，例如「資料截止日期（data_as_of_date）」；系統不以目前 UI 值或預設常數代填。

Registry 比較只使用已保存的 metadata、equity curve 與 benchmark_results，不重新抓取目前資料。資料 fingerprint、execution 或 sizing 不同時會標示為「不可直接比較」，並以中文原因顯示如「資料指紋不同」「成交假設不同」「部位 sizing 模式不同」；期間、Universe 或成本不同時會標示為「需謹慎比較」，並以「日期區間不同」「Universe 股票池不同」「交易成本模型不同」等原因提醒，不應直接做優劣排名。畫面中的參數、指標、Regime 與 Benchmark 會先以摘要卡顯示重點，並以 A / B / C 代號對應長 run 名稱；完整資料仍來自同一批已保存 run metadata，不重新計算。標準化權益只在共同日期交集上把每個 run 的第一筆淨值設為 10000；沒有共同日期時不補值、不推估，也不重新計算回測。Registry-based Promote 會先做 Registry Gate，通過後才建立策略版本。

策略回測頁左側設定面板頂部有「收合左側設定」按鈕，可暫時隱藏設定面板，讓右側結果分頁、Registry 比較與圖表取得更多橫向空間；收合後標題列會顯示「展開左側設定」作為恢復入口。此操作只改變 UI 空間配置，不改變目前輸入參數、已選 run、回測結果或保存狀態。

固定組合目前的 Registry 保存粒度是每檔股票的 per-stock run，metadata 會標記為 `fixed_basket_stock` 以保留固定組合來源，並沿用該檔回測產生的 factor records 生成 `factor_snapshot` / `factor_contributions`。完整固定組合層級的現金帳、再平衡、未成交、Liquidity / Gap 風險揭露仍未建成，不應把 per-stock 保存結果解讀為完整可成交的固定組合績效；Month 3 v1 的完整 portfolio credibility 揭露集中在推薦組合回放。

### 9.10 推薦回放

建議從推薦頁按「送 Research Lab 推薦回放」載入配置。這個入口會帶入當下 Profile / Config，並在歷史期間按設定重新產生推薦；它不是只回測今日推薦名單。

可設定：

- 每次推薦檔數
- 每期候選上限
- 持有天數
- 每週重播或只跑一次：每週重播會在回放期間定期重新產生推薦名單，只跑一次則只用起始日名單。
- 等權或分數加權：等權配置平均分配資金，分數加權會讓高分股票取得較高權重。

執行後可保存到 Research Run Registry。結果頁摘要只顯示一次，並用段落解釋總報酬、最大回撤、交易檔數、資金使用、交易假設、虧損交易占比、最拖累股票、Sharpe / Sortino 與 Monte Carlo P05 / P50 / P95。資金使用代表期間投入金額，不等同最終淨值；Monte Carlo P05 / P50 / P95 分別是偏弱、中位與偏強情境，不是保證績效。期間明細、個股貢獻與交易紀錄在結果頁內部分頁查看，避免被底部區域吃掉。若要比較 Profile 或判斷升降級，應以訓練期間先提出候選調整，再用獨立驗證期間或 walk-forward 驗證凍結邏輯，避免用同一段未來資料同時調參與宣稱有效；`ProfileReplayComparisonService` 的驗證期必須晚於訓練期，驗證結果只輸出人工 lifecycle candidate，不會自動降級、退休或刪除策略版本。

歷史載入、刪除與 legacy Promote 能力仍保留在舊 repository 邊界；新版 Cross-run Comparison 與 Registry-based Promote Gate 以 Registry run 為準。結果 details 會包含 `portfolio_credibility`、`unfilled_orders`、`cash_ledger`、`weight_exposure` 與 `gap_risk`：若推薦股票在回放視窗內沒有可用價格列，會以 `missing_price_rows` 記錄為未成交，而不是靜默跳過；若呼叫端提供 `max_participation_rate`，系統會用進場日成交股數與收盤價估算可參與金額，配置金額超過時以 `liquidity_limited` 記錄為未成交。回放現在會在建立 holding 前檢查可用現金，現金不足時以 `cash_limited` 記錄為未成交；`cash_ledger` 由這個現金 gate 流程產生買進、賣出與 `ending_cash`。若呼叫端提供 fee / tax / slippage bps，成本會套用到買賣現金流、ledger breakdown 與 `total_transaction_cost`；未提供時維持無成本回放。若呼叫端提供 `lot_size`，配置金額會依進場價向下取整為可成交整股股數，買不起最小交易單位時以 `lot_size_limited` 記錄為未成交。期間持倉的 `allocation_weight` 代表推薦配置的目標權重，`actual_allocation_weight` 代表整股 sizing 與 cash gate 後的實際可成交權重；`weight_exposure` 會依每個再平衡日彙總目標權重、實際權重、未成交權重與殘餘現金權重。若歷史資料含「開盤價」，`gap_risk.records` 會列出每筆 holding 的 `entry_close_price`、下一個可用交易日 `next_open_price`、`gap_pct`、`gap_direction` 與 `severity`，用來揭露同日收盤成交假設在隔日開盤可能遇到的跳空風險。V1.2 details 另含 `rolling_risk_metrics`、`microstructure_preflight` 與 `relative_attribution`：rolling risk 只讀已產生 equity curve / holdings；microstructure preflight 只檢查歷史資料內可選的處置股、分盤交易、全額交割、漲跌停鎖死與除權息欄位，缺欄位時揭露 missing source；relative attribution 只在 history 提供 benchmark / industry / concept 參考欄位時產生相對報酬。`portfolio_credibility` 仍會揭露同日收盤成交、再平衡現金重用限制、成交量 / Liquidity 與 Gap 限制；目前仍未建零股、委託簿撮合、買賣價差或 gap 實際成交模型，`gap_risk`、microstructure 與 attribution 只做診斷，不會改變 PnL、成交價、cash ledger 或 sizing。這些 warning 應先讀完，再判讀回放績效。結果仍依成交與推薦回放假設，不等同實盤。

## 11. Gate 2 Data Governance Consolidation & PIT Safeguards

### 11.1 資料品質防線 (DataQualityFirewall)

`DataQualityFirewall` 提供非破壞性數據品質診斷，絕不上寫或刪除正式 SQLite 原始資料庫：

1. **`daily_prices` 診斷**:
   - 捕捉 NULL / 空白 / 非法 `證券代號`（隔離標記 `QUARANTINE_REJECT`）。
   - 捕捉週末 / 休市日 OHLC 記錄（標記 `SUSPICIOUS_WEEKEND_DATE` 與警告日誌）。
   - 捕捉重複主鍵 `(證券代號, 日期)` 與價格範圍違規（`QUARANTINE_ISOLATE`）。
   - 產出可追溯 anomaly report，包含 exact primary key、row hash、原因與建議處置。

2. **`market_indices` 診斷**:
   - 檢核規範欄位 `指數名稱` 與舊欄位 `收盤價` / `收盤指數`。
   - 若 `指數名稱` 缺失但舊 OHLC 仍可由 fallback 讀取，系統明確評估為 `degraded`（降級），絕不誤報為 `healthy`。

### 11.2 PIT (Point-In-Time) 安全防線

適用於 `fundamental_monthly_revenues`、`fundamental_statement_items` 與 `valuation`：

1. **可得日規則**: 強制要求 `available_date <= decision_as_of_date` 才能在歷史推薦、策略評分與回測中採信。
2. **未來資料偏誤攔截**:
   - `available_date > decision_as_of_date` 觸發 `PIT_FUTURE_LOOK_AHEAD` 並強制拒絕。
   - `available_date` 缺失觸發 `PIT_AVAILABLE_DATE_MISSING` 並強制拒絕/降級。
   - 月營收與季度財報讀取同時要求可驗證的 `announced_date`；缺失時觸發 `PIT_ANNOUNCED_DATE_MISSING` 並 fail-closed，不得把回填 `available_date` 當作歷史 PIT 證據。
   - 事後補齊之公告日觸發 `PIT_POST_HOC_ANNOUNCEMENT` 並強制拒絕。
3. **無 Future Leakage 保證**: 防線確保缺失資料不會默默填充為 0 或高分，絕不引入未來函數。

### 11.3 Gate 2 證據三層模型與運作包

1. **三層模型**:
   - **Layer 1: Weekly Collection**: 側邊每週自動採集，標記為 `pending_human_review` 或 `collection_failed`。
   - **Layer 2: Approved History Projection**: 經具名 owner 核准之外部唯讀 JSON 投影 (`approved-weekly-history-projection.v1`)，固定 `formal_credit_authorized=false`。
   - **Layer 3: Formal DB Credit**: 正式資料庫 credit 權限，必須由具名人工權責角色簽署。
2. **Projection 驗證限制**: 嚴禁 projection 指向正式 SQLite 資料庫目錄，並重複檢查週期重疊與 Schema 格式。
3. **人工審查包與災原演練**:
   - 提供週次審查表單範本、Working-Copy 備份與復原演練 SOP 及緊急回滾核對清單。

### 11.4 排程與日常證據可觀測性

1. **五大排程任務相依性**:
   - `daily_data_update_quick` -> `daily_data_freshness_check` -> `scheduled_recommendation_snapshot` -> `scheduled_evidence_pipeline_dry_run` -> `v2_2_weekly_collection`
2. **寫入意圖劃分**:
   - `daily_data_update_quick` 允許進行市場價格資料更新寫入 (`MARKET_DATA_UPDATE_WRITE`)。
   - `production_scheduler_allowed=false` 僅約束正式 DB Evidence 寫入，**絕不代表禁止每日市場價格資料更新**。


## 10. 持倉管理

### 10.1 手動記錄交易

1. 點擊「手動記錄交易」。
2. 輸入股票、買賣別、價格、股數、日期、費用與稅金。
3. 可選擇策略來源並填寫備註。
4. 保存後系統重算持倉與平均成本。

也可以按「匯入交易 CSV」匯入券商或紙上交易檔：

1. 選擇 CSV；系統先以 UTF-8／CP950 嘗試解碼並自動辨識中英文欄名。
2. 系統逐列檢查證券代號、買賣別、股數、價格、交易日期、費用與稅金，先產生唯讀預覽。
3. 預覽全部通過且檔案 SHA-256 未變更時，按確認才會 append 到 Portfolio；取消、欄位錯誤、重複匯入或檔案被修改都不寫入。

匯入只支援可映射的成交明細，不連接券商 API，也不代表券商已成交；同一檔案的重複列會以來源 hash 與列內容產生可追溯交易 ID。CSV 欄名無法辨識時，請改用 `stock_code`、`stock_name`、`side`、`quantity`、`price`、`trade_date` 及可選 `fees`、`taxes`、`notes`。

輸入股票代號後，系統會嘗試從 stock master / SQLite 自動補證券名稱；找不到正式代號時會提示。手續費與證交稅會依台股預設值自動估算，使用者仍可手動覆寫。

賣出數量不得超過目前可用持倉。

### 10.2 從推薦或回測建立來源追溯

- 推薦結果表右鍵「記錄到持倉管理」。
- 回測交易明細右鍵記錄交易。

這些入口會保存推薦結果、回測 run 或策略版本來源。它們仍是手動記錄，不會送出券商委託。

相容 API `PortfolioService.get_benchmark_comparison()` 在尚未提供比較期間、現金／資金流帳與固定 benchmark constituents 時會回傳 `status=not_computable` 與 `None`，不再用數值 0 冒充已完成的超額報酬比較。正式的成本後 Portfolio／Equal Weight 比較要走 Paper Portfolio 的期間化 ledger 與 weekly report。

目前不要把批次回測排行榜理解成已提供直接加入持倉入口；可記錄到持倉的主要入口是推薦結果表與回測交易明細。

### 10.3 Paper Portfolio 與 Equal Weight 狀態

持倉管理右側「Paper Portfolio」分頁是排程紙上帳的唯讀觀測面：

1. 顯示 daily status、最新可採用 snapshot 日期／ID、raw 累積 snapshot 筆數、現金、總值與最新安全持倉列；若 raw 最新列是未來日期，會保留 blocker／diagnostic 並排除於 current projection。
2. 顯示 Equal Weight benchmark 觀測數、Paper Trade Ledger 狀態、成本合計、full／partial／reject／override 統計與 weekly report 狀態；缺 benchmark、ledger 或 ledger 欄位不完整時會明示 `partial`／`not_computable`，不會以 0 補值。
3. 顯示 status／snapshot 路徑、blockers、warnings 與固定安全邊界。此分頁不建立資料庫、不寫正式 Portfolio、不調 Advice、不啟用 broker 或自動再平衡。
4. 「計算最近週報」會以最近 `5` 筆（可調整 `1–31`）snapshot 的實際首尾日期，唯讀重建 Paper weekly evidence，顯示 gross／net／benchmark／net excess（bp）、成本、換手、觀測日數與 `OBSERVED`／`DEGRADED` 品質。觀測不足、期間邊界不一致、缺 turnover／execution gap 或缺 ledger 時，畫面會保留 `partial`／`degraded`／`not_computable` 與具體 blocker，不把缺口當成 0。
5. 「匯入 Paper 成交 CSV」只接受完整的 paper execution 欄位，先顯示檔案 hash、筆數與總成本，二次確認後才 append 至 Paper Trade Ledger；不會修改手動 Portfolio、Paper snapshot 或發送 broker 訂單。取消、欄位缺失、狀態／數量不一致或檔案在確認前變更時，整批拒絕且不建立 ledger。
6. 「匯出成交範本」會建立空白 `paper_fills_template.csv`；範本只有欄位標題、不包含示例交易，且預設不覆寫既有檔案。請填入真實 execution 後，再按「匯入 Paper 成交 CSV」走預覽與二次確認。
7. 每日 Paper／Decision Desk 排程預設採用最近一個已到達的台北 08:30 cutoff；若以 `--decision-at` 明確指定尚未到達的時間，Paper runner 會回報 `skipped_future_decision` 並不開啟 state／market DB，避免再產生 look-ahead row。
8. 「預覽／建立 Equal Weight」會先唯讀驗證 baseline safety flag、snapshot 首尾日期、frozen constituents 與每個決策日的 T-1 市場價格；預覽成功後才二次確認建立新的 benchmark ledger。目標已存在、輸入在確認前變更、future snapshot 或缺因果價格時會拒絕，不覆寫既有資料；這只補 benchmark observation，不能替代真實 Paper fills。

`export_paper_trade_csv_template.py --help` 會先設定 UTF-8 console；Windows CP1252 主控台也能正常顯示繁中說明。這只影響 CLI 顯示，不改變範本不含資料、預設不覆寫與不建立 Paper ledger 的安全邊界。

可用下列命令做相同的唯讀檢查：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_paper_portfolio_readiness.py `
  --output-root <OUTPUT_ROOT> `
  --format json
```

上述 Paper readiness、Paper weekly evidence、Equal Weight builder 與 Runtime readiness CLI 會在解析參數前設定 UTF-8 主控台輸出；Windows 預設 CP1252 環境也能正常使用 `--help` 與繁中診斷。這只影響顯示，不改變唯讀與不建 schema 的安全邊界。

Equal Weight readiness 預設讀取 `<OUTPUT_ROOT>/paper_portfolio/paper_equal_weight_benchmark.sqlite`；若 ledger 放在其他位置，可明確提供：

```powershell
$env:PAPER_EQUAL_WEIGHT_BENCHMARK_PATH = '<EQUAL_WEIGHT_LEDGER.sqlite>'
```

此環境變數只供唯讀檢查定位既有 ledger；預設檔案不存在時會顯示 `equal_weight_benchmark_db_missing`，不會由 readiness／weekly evidence 自動建立 schema。持倉管理 > Paper Portfolio 的「預覽／建立 Equal Weight」會使用 baseline、Paper snapshot 與 `TWStockConfig.db_file` 的市場資料，先產生只讀 preview；使用者明確確認後才建立新的研究用 append-only ledger，且若目標已存在會拒絕覆寫。這個入口不改市場 DB、Paper snapshot、手動 Portfolio 或 Paper Trade Ledger，也不把 benchmark 當成成交紀錄。

最近一次實測有 `21` 筆 raw snapshot，raw 最新日 `2026-08-28`、總值 `490950.00`；本次台北市場日同為 `2026-08-28`，該列可作當日 current projection。受控流程已以 frozen constituents `1418／1536／1615` 在 `<OUTPUT_ROOT>/paper_portfolio/paper_equal_weight_benchmark.sqlite` 建立 `21` 筆 Equal Weight observation，benchmark reader 為 ready；這只補齊研究用 benchmark 輸入，不補足 Paper Trade Ledger，也不代表成本後績效或投資有效性。正式 readiness 仍為 `partial`。若執行時台北市場日早於 snapshot 日期，readiness 會將該列標成 future、排除於 current NAV，並只保留 blocker／diagnostic。

若 Paper Portfolio、weekly evidence 或 Equal Weight builder 遇到 `paper_snapshot_future_dated`、`paper_daily_status_future_dated` 或 `paper_weekly_report_future_period`，先停止採用該期間，不要刪除、回填或手動改寫正式資料；請由 owner 追查排程時鐘、時區與來源事件。現行排程入口已改採最近已到達 cutoff，且 writer 對明確未到達的 `--decision-at` fail-closed；既有 future row 仍只作 blocker／diagnostic。Equal Weight builder 也會在 preview／apply 前拒絕 future snapshot，避免 look-ahead 污染 benchmark。

Paper Trade Ledger 預設位置為 `<OUTPUT_ROOT>/paper_portfolio/paper_trade_ledger.sqlite`，也可用 `PAPER_TRADE_LEDGER_PATH` 或 CLI 的 `--cost-ledger-db` 指定。Ledger 必須由受控 paper execution producer 寫入；不能把手動 Portfolio 的 `trades.jsonl`、virtual order trace 或 snapshot mark 直接複製成成本帳。每筆 fill 至少要有 requested／filled 數量、狀態、Decimal 成本、turnover、execution gap 與來源事件；缺任何必要欄位時 weekly report 維持不可計算。Readiness 會另外檢查 `event_date` 是否晚於台灣市場日；future-dated fill 會保留 raw row 供稽核但標成 `paper_trade_ledger_future_dated`、排除成本總額與 ready 判定，Portfolio UI 會顯示 future-dated fill 計數。

目前可用的受控 producer CLI 為：

```powershell
.\.venv\Scripts\python.exe scripts\append_paper_trade_ledger.py `
  --input-json <PAPER_FILL_JSON> `
  --ledger-db <PAPER_TRADE_LEDGER.sqlite>
```

上述命令只驗證與預覽，不建立 ledger；確認事件與來源無誤後，才加上 `--confirm-append-paper-ledger`。CLI 仍只寫研究用 Paper Trade Ledger，不會改寫手動 Portfolio、正式市場 SQLite 或呼叫券商。

JSON producer 會在預覽輸出 `source_hash`，並把 SHA-256 前 16 碼綁入每筆
`source_event_id`（`paper_json:<hash-prefix>:<event-id>`）；確認 append 前會再次
檢查輸入檔 hash，檔案在讀取期間變更就整批拒絕。若未提供 `source_type`，會固定標為
`paper_trade_json_import`，方便 readiness／weekly evidence 判斷來源；這仍不代表該
JSON 內的事件已由系統驗證為真實成交，owner 仍須提供可稽核的 paper execution 來源。

若來源是 CSV，可使用與 UI 相同的完整 execution contract：

```powershell
.\.venv\Scripts\python.exe scripts\append_paper_trade_csv.py `
  --input-csv <PAPER_FILLS.csv> `
  --ledger-db <PAPER_TRADE_LEDGER.sqlite>
```

CSV 至少要有 `fill_id`、`order_id`、`portfolio_id`、`event_date`、`stock_code`、`side`、`requested_quantity`、`filled_quantity`、`reference_price`、`fill_price`、`commission`、`tax`、`slippage_cost`、`turnover_bp`、`execution_gap_bp`、`status` 與 `source_event_id`；`override_reason` 可選。預覽成功後才加上 `--confirm-append-paper-ledger`。匯入 producer 固定寫入 `source_type=paper_trade_import`，並將 CSV hash 綁入 `source_event_id`，以便週報保留來源追溯。

在確認 append 前，建議先用 query-only reconciliation 對帳外部 fills 與 Paper snapshot 的期初／期末股數：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_paper_trade_reconciliation.py `
  --input-csv <PAPER_FILLS.csv> `
  --state-db <PAPER_PORTFOLIO.sqlite> `
  --ledger-db <PAPER_TRADE_LEDGER.sqlite> `
  --portfolio-id paper-main `
  --period-start 2026-08-24 `
  --period-end 2026-08-28 `
  --format markdown
```

這個預覽先重驗完整 `paper-trade-import.v1` execution contract，再以 SQLite
`mode=ro`／`PRAGMA query_only=ON` 讀取明確期間的唯一期初／期末 snapshot，逐股票比較
buy／sell 的 `filled_quantity` 與 snapshot quantity delta，也會檢查既有 ledger 的
`fill_id` collision。輸出 `paper-trade-reconciliation.v1` 固定是 candidate-only、
`write_performed=false`；只有明確期間、snapshot 邊界與數量對帳均通過才顯示
`status=ready`／`ledger_append_allowed=true`。period 自動推導或對帳不一致只回
`needs_review`；欄位 invalid、future event、portfolio 不符或 collision 回 `rejected`。
snapshot 不會被用來反推成交，`ready` 也不會自動寫 ledger；確認仍須回到上方
`append_paper_trade_csv.py --confirm-append-paper-ledger`，並重新驗證輸入檔 hash。

若缺少欄位格式，可先建立空白範本（只寫入欄位標題，不建立 ledger）：

```powershell
.\.venv\Scripts\python.exe scripts/export_paper_trade_csv_template.py `
  --output-csv <PAPER_FILLS_TEMPLATE.csv>
```

既有檔案預設不覆寫；只有確認目標是未使用的範本檔時才使用 `--overwrite`。

若要以既有 paper baseline、snapshot 日期與正式行情的 T-1 價格建立 frozen-constituent Equal Weight benchmark，可先執行唯讀 preview：

```powershell
.\.venv\Scripts\python.exe scripts\build_paper_equal_weight_benchmark.py `
  --baseline <PAPER_BASELINE_JSON> `
  --state-db <PAPER_PORTFOLIO.sqlite> `
  --market-db <TWSTOCK.sqlite> `
  --output-ledger <EQUAL_WEIGHT.sqlite>
```

preview 會驗證 baseline safety flags、首日邊界、snapshot 日期唯一性、frozen constituents 與每一日可取得的 T-1 價格；不建立 output。確認結果後才加上 `--confirm-build-paper-benchmark`，且 output 已存在時會拒絕、不覆寫。此命令只寫新的研究用 Equal Weight ledger，不改正式市場 SQLite、paper snapshot、手動 Portfolio 或 broker；建立後仍需用本節 readiness inspector 檢查週報輸入與成本帳是否完整。

若 benchmark 與 Paper Trade Ledger 都已存在，可用下列命令唯讀重建指定期間的週報 evidence：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_paper_portfolio_weekly_evidence.py `
  --output-root <OUTPUT_ROOT> `
  --period-start 2026-08-20 `
  --period-end 2026-08-21 `
  --expected-trading-days 2 `
  --benchmark-db <EQUAL_WEIGHT.sqlite> `
  --cost-ledger-db <PAPER_TRADE_LEDGER.sqlite> `
  --format json
```

此 CLI 與 Portfolio UI 使用相同的 query-only adapter；只會讀既有 SQLite，缺資料或 schema 時回報原因並以非零狀態結束，不建立資料庫。成本列的 `source_type` 必須保留 `paper_` provenance；手動交易、`broker_csv`、snapshot mark 或 virtual execution trace 不會被當成成交成本。`expected-trading-days` 是完整性標示，不是補值參數；週報的研究邊界固定為 `research_only=true`、`investment_effectiveness_claim=false`、`writes_allowed=false`、`broker_execution=false` 與 `auto_rebalance_allowed=false`。

### 10.4 持倉與交易歷史

選取持倉後，右側同步顯示：

- 交易歷史
- 覆盤日誌
- 策略與價格監控
- 生命週期回顧
- 籌碼監控

交易歷史可直接選取一列，再按表格下方的「刪除選取交易」；未選取資料時按鈕維持不可按，右鍵刪除仍可使用。持倉列表是一檔股票的衍生彙總，不會因為誤按而直接刪除整檔歷史；每次只刪除選取的一筆原始交易。確認後系統會以剩餘交易重算持倉與平均成本；若刪除會造成超賣或不合法持倉，系統會拒絕並保留原始資料。

從持倉篩選交易歷史時，交易歷史區會顯示目前篩選狀態，並提供「清除篩選」回到全部交易。

持倉頁頂端的「持倉市值（未含現金）」只加總有可用最新價格的活躍持倉；現金帳、未入帳負債與完整 NAV 尚未納入此 MVP，因此不會把投入金額加上已實現損益冒充淨值。缺少價格時顯示 `N/A`，摘要會列出已標記筆數、缺價格股票與價格日期。

### 10.5 情境與壓力測試

持倉管理右側「情境壓力」分頁提供唯讀的 Portfolio Scenario & Stress Lab v1。可選擇快速下跌、跳空跌停、相關股同跌、最大持倉事件、流動性消失、輪動失敗或來源中斷等情境，按「執行情境」後查看基準市值、壓力後市值、變動與逐檔明細。

- 價格衝擊是固定的研究假設（例如 `-1000 bp`），不是市場預測，也不會改寫持倉、交易、日誌或資料庫。
- 缺少最新價格時會顯示「部分可計算」並列出股票；只計算已標記持倉，不外推缺失值。
- 「輪動失敗」與「來源中斷」目前會 fail-closed 顯示不可計算，因為尚未有產業曝險或可用來源契約；不可把 `N/A` 解讀成零風險。
- 所有結果固定標示研究用途，不是投資建議、績效證據或交易指令。

按「保存研究快照」並完成二次確認後，才會把目前結果寫入
`OUTPUT_ROOT/portfolio/stress_history.sqlite` 的 append-only history；取消確認、缺少結果或重複相同 payload 都不會新增資料。分頁下方的 Stress 歷史表由 query-only read service 讀取，會顯示執行時間、基準日、情境、狀態、市值變動與 payload hash；資料庫不存在時顯示 `stress_history_not_configured`，不會因畫面 refresh 建立空 DB。保存的快照仍固定為 `research_only=true`、`investment_effectiveness_claim=false`，不得當成正式績效或交易 evidence。

若要在 UI 外預覽或保存單一結果，先將 `PortfolioStressResult.to_dict()` 輸出成 JSON，再使用：

```powershell
.\.venv\Scripts\python.exe scripts\append_portfolio_stress_history.py `
  --input-json .\stress_result.json `
  --history-db .\output\portfolio\stress_history.sqlite

# 只有明確確認才會建立／寫入 history DB
.\.venv\Scripts\python.exe scripts\append_portfolio_stress_history.py `
  --input-json .\stress_result.json `
  --history-db .\output\portfolio\stress_history.sqlite `
  --confirm-save-stress-history
```

### 10.6 覆盤日誌

1. 選取持倉。
2. 點擊「新增日記」。
3. 記錄進場假設、風險、觀察結果與出場理由。

### 10.7 策略與價格監控

顯示：

- 目前價格
- 未實現損益
- 停損與停利門檻
- 監控狀態與原因
- 策略、推薦或回測來源

目前價格會一併顯示價格日期。手動建立持倉會顯示為「手動建立，無推薦 / 回測來源」，避免誤解為資料缺失。

目前價格查詢是唯讀路徑：先查詢既有 SQLite `daily_prices`，SQLite 不存在或不可讀時才降級讀取既有每日 CSV；打開持倉頁或查詢價格不會建立空 `twstock.db`。若 SQLite 使用 `immutable_fallback`，應把數值理解為最後已提交快照，並回到「數據更新」或 SQLite Inspector 檢查 freshness。

警示是輔助判讀，不會自動平倉。

### 10.8 生命週期回顧

選取持倉後，右側「生命週期回顧」會顯示：

- Thesis 狀態：假設仍成立、證據降級 / 持續觀察、或假設失效 / 需要覆盤。
- 來源追溯：例如推薦結果、回測 run 或策略版本來源。
- 執行落差：進場平均成本相對來源快照價格的 basis points gap。
- 訊號落差：`PortfolioConditionMonitor` 的 valid / warning / invalid 狀態與原因。
- 市場體制：進場 regime 與目前 regime 是否一致。
- 資料品質：來源 hash、來源品質與 degraded / estimated flags。
- 摘要 tokens：source / execution / signal / market / data_quality 的狀態摘要。

此分頁只做 post-trade attribution 與 live-vs-research gap 判讀，不會自動下單、平倉、調整持倉、刪除策略版本或改寫回測結果。若顯示假設失效，使用者應回到 Research Lab、Registry 比較或覆盤日誌確認原因。

### 10.9 籌碼監控

顯示籌碼風險、近期分點買賣明細與資料品質。風險等級與品質狀態會以繁體中文顯示，原始 key 保留在 tooltip 供除錯。按「下鑽詳細主力流向」會切換至「市場探索 > 主力流向」並定位目前股票。

### 10.10 清空全體數據

此操作會永久清空持倉交易與日誌，需要二次確認。執行前應先確認資料是否已備份。

## 11. Runtime Observatory（Owner 營運與治理監控）

這是唯讀觀測頁，不是選股工具；它並列呈現兩條**不得互相推論**的觀測平面：

1. **營運排程**：只讀 `<OUTPUT_ROOT>/scheduled/*/latest_status.json` 已保存產物，顯示核心資料更新、資料新鮮度、推薦快照、證據 dry-run、決策證據與 Paper Portfolio，以及 ML／官方市場事件／ML Direct-OOC 維護等安全狀態。
2. **治理 Runtime**：只讀 `runtime/` 的任務、context 與 append-only 治理事件；它反映 agent／governance workflow，不是日常資料、推薦或 Paper 流程的健康度。

營運排程的每一列是「已保存檔案的讀取結果」，**不是** Windows Task Scheduler 的註冊、啟動中、成功結束或 `Last Result` 證明；某 task 被列出或未列出，都不能反推其 Windows task 狀態。若要確認 Scheduler，請使用本手冊 V4.0 排程章節的 query 命令。

### 11.1 正式路徑環境診斷

Runtime 頁面最上方的「正式路徑環境（唯讀診斷）」會立即顯示四個 App 依賴位置：`DATA_ROOT`、`OUTPUT_ROOT`、`DATA_ROOT/logs` 與 `OUTPUT_ROOT/research_runs/research_runs.db`。狀態意義如下：

- **可用**：路徑／檔案已存在，程序目前可讀；需要寫入的既有 logger／Registry 檔案也能開啟寫入 handle（只開啟與關閉，不寫入內容）。
- **待建立**：父路徑可見，但目標尚未建立；此頁只揭露缺口，不會自動建立目錄、probe 檔或 SQLite。
- **需要處理**：路徑可見但讀取、`os.access` 或既有檔案 write-handle probe 不符合需求。
- **無法使用**：資料根目錄不存在、父路徑不可見，或檢查本身失敗。

卡片採首次立即讀取、之後約每 30 秒重新整理。它是 side-effect-free 的環境提示：目錄／檔案先以 `os.access` 檢查，若已有 `config.log` 或 Research Registry，再以不寫入內容的 handle probe 交叉檢查；不會建立檔案或執行 SQLite 寫入，因此仍不能證明 schema 變更、原子提交或網路磁碟鎖定一定成功。若卡片顯示需要處理，先依 diagnostic 修正 ACL／鎖定或改用具名且可寫的 `OUTPUT_ROOT`；系統不會替使用者修改權限。

窄視窗使用 Runtime 時，寬度小於 720px 會自動將「任務狀態機／Context」與「治理 Runtime／事件流」由左右兩欄改為上下排列；整頁可垂直捲動，長狀態文字會換行，底部 Session context 會以省略號保留摘要。主視窗可縮至 320px（左導覽同步改為 icon-only）；這些都是顯示層調整，不會改變資料讀取、排程或寫入權限。

窄視窗使用 Runtime 時，寬度小於 720px 會自動將「任務狀態機／Context」與「治理 Runtime／事件流」由左右兩欄改為上下排列；整頁可垂直捲動，長狀態文字會換行，底部 Session context 會以省略號保留摘要。主視窗可縮至 320px（左導覽同步改為 icon-only）；這些都是顯示層調整，不會改變資料讀取、排程或寫入權限。

不開啟主 UI 也可執行同一份唯讀檢查：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_runtime_environment_readiness.py `
  --data-root D:\Min\Python\Project\FA_Data `
  --output-root D:\Min\Python\Project\FA_Data\output `
  --format markdown
```

預設輸出 JSON；`--format markdown` 方便貼入稽核紀錄。整體 `ready` 時 exit code 為 `0`，其餘狀態為 `2`；兩者都不會建立缺少的路徑。輸出會保留 `side_effect_free=true`、`write_probe=os.access_plus_existing_handle` 與每一路徑的 diagnostic，供後續判讀正式 logger／Registry 權限與鎖定問題。

若要在不碰正式資料的前提下驗證實際 ACL／檔案與 SQLite 寫入，可另外指定一個**已存在且位於 `DATA_ROOT`、`OUTPUT_ROOT` 之外的 staging 目錄**。未帶確認旗標時只會回報 `confirmation_required`，不會寫入：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_runtime_environment_readiness.py `
  --data-root D:\Min\Python\Project\FA_Data `
  --output-root D:\Min\Python\Project\FA_Data\output `
  --write-probe-root C:\Temp\baldr-runtime-probe `
  --confirm-write-probe --format json `
  --output C:\Temp\runtime_write_probe.json
```

確認 staging 目錄無誤後，才可明確加入 `--confirm-write-probe`；`--output` 可把 JSON／Markdown 證據保存到明確指定的非正式路徑。程式會在該目錄建立短生命週期的暫存文字檔與使用正式 `ResearchRunRepository` schema 的 SQLite，寫入／讀回一筆 probe、rollback 後確認該筆消失，再清理全部檔案；JSON／Markdown 會顯示 `registry_transaction_succeeded`，通過時 exit code 為 `0`，其他狀態為 `2`。這只能證明指定 staging 目錄的實際 Registry schema transaction／rollback 與清理能力，不能取代正式 Registry ACL／鎖定驗證；指向正式 `DATA_ROOT` 或 `OUTPUT_ROOT` 會被阻擋。

若需要更接近正式 Registry 的 schema 證據，可使用下列唯讀來源 clone probe：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_research_registry_transaction.py `
  --registry D:\Min\Python\Project\FA_Data\output\research_runs\research_runs.db `
  --confirm-snapshot-probe `
  --format json `
  --output C:\Temp\research_registry_snapshot_probe.json
```

此命令只以 `mode=ro` 開啟 `--registry`，將一致性 snapshot 複製到 OS TEMP，再在 clone
上執行 schema／`quick_check`／insert／讀回／rollback；clone 會自動清除，正式 DB 的
bytes、mtime 與 SHA-256 會前後比對。報告的
`write_probe=formal_registry_read_only_snapshot_clone_transaction`、
`formal_write_attempted=false` 代表目前正式 schema 可由 clone 驗證，並不代表正式
Registry ACL、鎖定或 production writer 已經實寫成功。

若要在 owner 明確核准後驗證**正式 Research Registry 的實際 transaction／rollback**，使用
guarded production canary；它不是 UI 動作，也不應由 scheduler 呼叫：

```powershell
.\.venv\Scripts\python.exe scripts\qa_research_registry_production_canary.py `
  --registry D:\Min\Python\Project\FA_Data\output\research_runs\research_runs.db `
  --output-root D:\Min\Python\Project\FA_Data\output `
  --protected-root D:\Min\Python\Project\FA_Data `
  --owner-approval research-registry-transaction-canary `
  --no-concurrent-writer-ack no-concurrent-writer `
  --confirm-production-registry-canary `
  --output-json C:\Temp\research_registry_production_canary.json
```

執行前必須先停用／確認沒有其他 Registry writer；命令會先做 schema v2、required
tables／columns、`quick_check` 與 row count 預檢，再把正式 DB snapshot 到 OS TEMP。
canary 只插入一筆唯一 marker、讀回後立即 rollback，最後用唯讀連線確認 marker 不存在、
row count／content hash 沒有變化。未同時提供 owner approval、無並行 writer acknowledgement
與 confirm 時，結果是 `confirmation_required` 或 `blocked`，不會開啟正式寫入 handle。
成功輸出 `status=measured` 只表示該次可回滾 transaction 的實際證據，固定
`durable_change_allowed=false`；不代表長期 Registry writer、Formal、Evidence、scheduler
或 broker gate 已開啟。若驗證失敗，OS TEMP backup 會保留供人工比對；不要直接重跑或覆寫
既有 DB。`--output-json` 必須位於 OS TEMP 且不可落在 protected root。

### 11.2 營運排程判讀

- **正常**：核心工作已保存可接受的最新狀態。
- **安全邊界中**：工作受保護地完成或停在預期 gate；例如具完整 natural-maturity 證據的 evidence `degraded`、ML promotion `blocked`，或 ML Co-pilot `passed_rule_only`／`alpha=0`。這不是 ML 已 promotion，也不能人工解除 gate。
- **需要注意**：核心 status 缺失、無法讀取、過期、evidence 缺少完整 natural-maturity 證據，或有未預期狀態。先查看列出的 raw status、時間來源、source path 與 diagnostic，再回到對應功能／排程日誌處理。ML Direct/OOC 顯示 `blocked_insufficient_storage` 時，應先依 `storage_preflight.free_bytes` 盤點容量與保留策略，不要直接重跑或刪除既有 run。
- **無法判定**：非核心／安全工作缺少可用 status；不能把它當成功或失敗。

狀態時間只採 `checked_at`、`generated_at`，否則採檔案修改時間；市場決策日期（如 `decision_at`、`as_of_date`）不是排程完成時間。超過 36 小時的 core artifact 會被視為過期。tooltip 保留 raw status、讀取狀態、時間來源、來源路徑與 diagnostic，供追查 provenance。畫面只保證顯示已知或發現的 status artifact，不保證覆蓋全部 12 個 Windows tasks。

### 11.3 治理 Runtime 判讀

治理健康度只以目前 24 小時內、時間可解析且不超出容許時鐘誤差的治理事件判定。只有這些 current 事件可使治理狀態成為 `ERROR` 或 `HALTED`；舊事件會顯示為「僅有歷史治理事件」，未來時間或無法解析時間會顯示為不能判定目前狀態。歷史重大違規仍保留供稽核，但不能解讀成今天日常營運已暫停。

事件檔無法讀取或部分無法解析時，畫面會明示「無法讀取」或「部分無法解析」，不會把它降格成「尚無事件」或健康。`ERROR`／`HALTED`、拒絕率與最近重大違規只代表治理 workflow；它們不代表資料更新、推薦、Paper Portfolio 或主 App 一般功能失敗。

「本次開啟後的治理事件流」只顯示此 UI session 開啟後追加的最多 500 筆事件；它是 live 觀測而非完整歷史稽核查詢。當出現 `ERROR` 或 `HALTED`，先查看最近重大違規與 raw tooltip，再回到對應功能頁或日誌排錯。

此頁不會寫入 DB、啟動或修改 Windows task、重跑資料更新／模型訓練、變更 ML alpha／promotion、改寫 Runtime 事件、執行 Paper 操作或送出券商委託。任何需要執行的動作，都必須回到對應功能、排程腳本或受治理流程。

## 12. 常見問題

### UI 無法啟動

```powershell
.\.venv\Scripts\python.exe -c "import PySide6; print(PySide6.__version__)"
.\.venv\Scripts\python.exe ui_qt\main.py
```

確認目前目錄是 repo 根目錄，並檢查 `DATA_ROOT` 是否可存取。

### 圖表空白

確認 PySide6 QtWebEngine 可用；系統無法使用 fast renderer 時會嘗試 Matplotlib fallback。先查看 terminal 或應用日誌的匯入錯誤。

### 更新後推薦仍沒有最新日期

1. 檢查 SQLite 狀態日期。
2. 手動下載後確認已合併。
3. 確認技術指標已增量計算。
4. 在 SQLite Inspector 檢查 `daily_prices` 與 `technical_indicators`。

### Smart Money 沒有資料

確認券商分點已下載、合併並同步至 `broker_flows`。`unavailable` 不應解讀為 0 張。

若主表有股票但「語意狀態」顯示未計算，先確認 `SmartMoneySemanticService` 是否初始化成功，以及 SQLite `daily_prices` 是否可提供決策日前價格；沒有價格時仍可顯示 5 / 20 / 60 日淨量，但高檔出貨疑慮可能不會產生。

若快速更新在「同步券商分點至 SQLite」遇到同一分點 / 股票 / 日期的買超與賣超唯一鍵衝突，代表 DB 仍是舊三欄主鍵；更新後的流程會在同步前先備份並升級為含 `trade_type` 的主鍵。

### TPEX 股票日價缺漏

若在 SQLite Inspector 查 `3207` 缺少某個交易日，先檢查 `DATA_ROOT/daily_price_tpex/YYYYMMDD.csv` 是否存在；若不存在，代表 TPEX 官方日價未抓到或被站方阻擋，不應用 TWSE 當日已存在來判定完整。2026-06-17 排查後的正式歷史狀態應可看到 `3207` 覆蓋 `20140102..20260617`、共 2,907 筆；後續每日若 TPEX 當日失敗，UI / scheduled status 會列出缺少日期。請使用每日股價手動下載、快速/安全更新，或「背景補齊 TPEX + 技術指標」重試缺漏日期並同步。

### TWSE 股票日價缺漏

若 SQLite Inspector 查 TWSE 股票（例如 `2330`）缺少某個交易日，先檢查 `DATA_ROOT/daily_price/YYYYMMDD.csv` 是否存在；若日檔不存在，代表 TWSE 日檔未下載成功或曾被跳過，需用每日股價手動下載或安全更新補齊該日期範圍後再同步 SQLite。若缺少日期是交易所休市日則屬正常，例如 2026-06-19 為端午節休市。

### 回測 0 交易

依序檢查：

1. 資金是否足夠買一張。
2. 日期範圍是否涵蓋足夠訊號。
3. quantile 是否仍在暖機期。
4. 固定門檻是否過高。
5. 漲跌停、成交量與最大參與率是否拒絕成交。
6. 是否只有期末未平倉部位。

### Promote 按鈕不能使用

確認結果已保存，且驗證狀態不是 FAIL。樣本不足、無結果、未保存、run 已封存、run 已升級、資料完整性不是 valid、缺少參數合約版本、最低 validation gate 未通過、缺 benchmark excess return、factor snapshot 品質不足、regime compatibility 不足或 Month 6 lifecycle gate 未通過時，不允許升級。若策略版本 JSON 已寫入但 Registry 回填失敗，系統會執行補償刪除；刪除失敗時標記 reconciliation required，需進入受控修復流程。

## 13. Manual 覆蓋狀態

| 工作區 | 啟動/入口 | 操作 | 參數 | 結果解讀 | 安全/排錯 |
|---|---:|---:|---:|---:|---:|
| 數據更新 | 完成 | 完成 | 完成 | 完成 | 完成 |
| 市場探索 | 完成 | 完成 | 完成 | 完成 | 完成 |
| 推薦分析 | 完成 | 完成 | 完成 | 完成 | 完成 |
| 觀察清單 | 完成 | 完成 | 完成 | 完成 | 完成 |
| 市場探索 / 市場總覽；決策工作台 / 決策來源 | 完成（每日決策唯一實例位於市場探索 index 0；Workbench 僅導覽） | 完成 | 完成 | 今日待判讀、空狀態、session-only 已查看提示、主結論 / 行動等級、焦點卡、quality / warnings、月營收／三大法人資料可見性判讀；Market Breadth v1 / Sector Rotation v1 / Relative Strength / Liquidity Ranking v1 / Watchlist Trigger v1 / Portfolio Alert v1 / Smart Money semantics / Why Not v1 / fundamental diagnostics prompts 已接線 | 完成；可見性區塊不改 action / focus / Score；weekly history 以 live readiness inspector 判定（未設定 projection 時 `0/3 waiting_for_time`，approved projection 僅作揭露），multi-day dry-run record 已為 `3/3 ready`，Week 2 / Week 3 與 manual review / action-item rhythm 仍待正式資料累積 |
| Research Lab | 完成 | 完成 | 完成 | 完成 | 完成 |
| 持倉管理 | 完成 | 完成 | 完成 | 部分完成：手動交易、CSV 預覽／匯入、日誌、監控、固定情境壓力投影與研究快照歷史可用；正式 Paper NAV／Equal Weight 成本後比較、fill／partial-fill／override 狀態與壓力正式 evidence 仍未完成 | 完成；所有新入口均維持明確確認、研究唯讀或 fail-closed 邊界，不接券商自動交易 |
| Runtime Observatory | 完成 | 完成 | 不適用 | 完成 | 完成 |

功能行為改動時，必須同步更新本表與對應章節。

完整主 UI 人工 smoke test 母檔維護於 [FULL_APP_HEALTHCHECK_2026_06_16.md](../06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md)。每次修改數據更新、SQLite 檢視、每日決策或跨工作區流程後，除自動化測試外，應依該 healthcheck 做 smoke test。

非破壞式 Full App Healthcheck Runner 可用於開發期間的自動化輔助驗證：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab recommendation --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
```

`--tab` 可用於分頁驗證，目前支援 `update`、`market`、`decision`、`research`、`recommendation`、`watchlist`、`portfolio`、`runtime` 與 `cross-flow`。這些測試只代表已核准的非破壞 direct bridge / QA script 通過；真實資料寫入、刪除、匯出檔案、完整 MainWindow 啟動、視覺判讀與真人互動流程仍要依母檔人工確認。

若需要接近真人 UI 操作的 MainWindow smoke，可明確 opt-in：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --ui-smoke --ui-smoke-switch-tabs --ui-smoke-screenshot --ui-smoke-resize 1366x768 --ui-smoke-resize 390x844 --ui-smoke-dialog-cancel --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
```

這會在隔離子程序啟動真實 PySide6 MainWindow、逐一切換左側主導覽的 8 個主工作區、保存 startup / resize screenshots、記錄 requested / actual viewport size，並測試 UpdateView 強制重新合併 dialog 的取消路徑。`startup.png` 會在切換工作區前擷取，代表實際初始頁；`resize_*` 則是各指定 viewport 的畫面。`--ui-smoke-dialog-cancel` 只會按取消，不會按確認；若 destructive action 被呼叫，healthcheck 會失敗。Smoke 子程序會自動把 `DATA_ROOT`／`OUTPUT_ROOT` 指到報告目錄下的隔離 `_isolated_app`，因此不會因正式 SQLite 的唯讀權限而在啟動階段中止，也不會改寫正式資料。1024×768 與 1440×900 是目前決策工作台／主導覽的基本 desktop viewport；report 應為 `matched`，仍需人工開圖判讀文字與按鈕的可讀性。

若正式 `OUTPUT_ROOT` 或 Research Run Registry DB 是唯讀，策略回測頁仍會開啟計算與唯讀證據檢視；「保存結果」與 Registry 比較會停用，設定面板會顯示 `Research Run Registry` 的具體錯誤。這代表研究結果持久化尚未可用，請先修正輸出路徑權限或指定可寫的 `OUTPUT_ROOT`，不要把空白 Registry 當成沒有歷史資料。

## Phase 3C governed ingestion candidate CLI

Phase 3C (三大法人、信用交易、TDCC 集保庫存) 的資料抓取為 **manual-only candidate ingestion**，它不屬於 V3.0 engineering closeout gate，不掛載於「一鍵安全更新」，也不由正式排程執行。

執行腳本 `scripts/update_phase3c_candidates.py` 預設為 `--dry-run` 模式，不會建立 Candidate DB 或 table；它只進行來源與交易日 diagnostics，並在隔離暫定位置輸出摘要 sidecar。apply 必須同時提供確認 token 與明確的、位於 `DATA_ROOT` 外的 Candidate DB 路徑。

```powershell
# Dry-run；不寫入 Candidate DB。預設不對本地缺少證據的日期進行線上交易日 probe。
.\.venv\Scripts\python.exe scripts\update_phase3c_candidates.py --start-date 2026-07-06 --end-date 2026-07-08

# 實際寫入隔離 Candidate DB（不可放在 DATA_ROOT 下），並讓 UI 能唯讀顯示狀態。
$env:PHASE3C_CANDIDATE_DB_PATH = 'D:/Min/Python/Project/FA_Data_candidate/phase3c_candidate.db'
.\.venv\Scripts\python.exe scripts\update_phase3c_candidates.py --start-date 2026-07-06 --end-date 2026-07-08 --sources institutional,credit --db-path $env:PHASE3C_CANDIDATE_DB_PATH --confirm apply-phase3c-candidate-ingestion

# 同時寫入 TDCC 官方最新一週 snapshot；資料日採 payload，不做歷史逐日假回補。
.\.venv\Scripts\python.exe scripts\update_phase3c_candidates.py --date 2026-08-13 --sources tdcc --include-latest-tdcc --db-path $env:PHASE3C_CANDIDATE_DB_PATH --confirm apply-phase3c-candidate-ingestion
```

輸出會明確包含以下邊界：
- `access_boundary: writes_allowed=false` (若是 dry-run)
- `access_boundary: production_scheduler_allowed=false`
- `access_boundary: scoring_engine_write_allowed=false`
- `access_boundary: investment_effectiveness_claim=false`
- `access_boundary: v3_closeout_gate_credit=false`

## 14. 更新記錄

- 2026-08-14：持倉管理的交易歷史新增可見的「刪除選取交易」按鈕。選取一筆交易後才可操作，確認後只刪除該筆原始交易並由既有 PortfolioService 重新驗證／重算持倉；刪除會造成不合法庫存時會被拒絕，持倉彙總列不會直接刪除整檔歷史。
- 2026-08-27：持倉管理新增 Paper Portfolio 唯讀 readiness 分頁、Paper weekly evidence 顯示與 `inspect_paper_portfolio_readiness.py`／`inspect_paper_portfolio_weekly_evidence.py`。正式輸出重新檢查到 21 筆 raw paper snapshots，其中最新 `2026-08-28` 超過台北今日 `2026-08-27`；readiness／weekly／Equal Weight builder 現在會 fail-closed 或降級並排除 future row 的 current projection，保留 blocker／diagnostic，不刪除或回填資料。Equal Weight ledger／交易成本帳尚未配置，故 UI 明示 `degraded`／`not_computable`，不把 paper 日更冒充成本後績效或正式持倉。
- 2026-08-27：修正 Paper／Decision Desk 每日排程的日期選擇語意：排程預設使用最近已到達的台北 08:30 cutoff，Paper runner 對明確未到達的 `--decision-at` 回報 `skipped_future_decision` 並不開啟 state／market DB，避免再次產生 future／look-ahead snapshot；既有 future row 仍保留供稽核。
- 2026-08-27：Paper Portfolio 新增完整 execution contract 的「匯入 Paper 成交 CSV」入口與 `append_paper_trade_csv.py`。預覽要求狀態、reference／fill price、Decimal 成本、turnover、execution gap 與來源事件；確認後只 append Paper Trade Ledger，不修改手動 Portfolio、snapshot 或 broker。
- 2026-08-28：新增 `inspect_paper_trade_reconciliation.py` 唯讀 fills preflight；外部 CSV 先通過 execution contract，再與明確期初／期末 Paper snapshot 對帳 filled quantity delta，並檢查既有 ledger 的 fill-id collision。只有 `status=ready` 才可交給既有明確 confirm append，工具本身不建立或修改 ledger。
- 2026-08-27：修正「資料更新 > 全部資料」月營收狀態卡的可見欄位；卡片現在會同步顯示已匯入期別、目前完整 PIT 可用期別，以及待生效期別與完整可用起始日，避免只看到日期／筆數而誤判月營收狀態。
- 2026-08-27：Runtime Observatory 新增「正式路徑環境（唯讀診斷）」卡片與 `inspect_runtime_environment_readiness.py`。它會立即／每 30 秒揭露 `DATA_ROOT`、`OUTPUT_ROOT`、logs 與 Research Run Registry 的存在、可讀性、`os.access` 可寫提示、既有 logger／Registry 的不寫入 handle probe 與 diagnostic；不建立目錄、probe 檔或 SQLite。`os.access_plus_existing_handle` 仍不是正式 schema／原子提交保證，正式 Registry 權限仍以實際錯誤與受控 smoke 為準；CLI 的 Markdown 輸出固定以 UTF-8 顯示繁中。
- 2026-08-28：新增 `qa_research_registry_production_canary.py` guarded production transaction／rollback 入口；預設只讀，需 owner approval、無並行 writer acknowledgement 與 explicit confirm，先在 OS TEMP 保存 snapshot，再對正式 Registry 插入唯一 marker、讀回、rollback 與 hash／row count／quick-check 驗證。成功也固定 `durable_change_allowed=false`，失敗保留 backup，不由 UI／scheduler 自動呼叫。
- 2026-08-27：Pre-V2／Workbench／Evidence source coverage 的 current Decision Desk 查詢新增台灣市場日期上限；future snapshot 只保留 raw 診斷並從 current latest 排除。`EvidenceSourceCoverageService` 與 `inspect_decision_desk_snapshots.py` 改為 query-only 檢查，正式唯讀 DB 不會再因 writer repository 建 schema 而報錯。
- 2026-08-27：資料更新進度改為可觀測的日期／檔案／資料批次回報；TWSE 批次子程序與 TPEX 區間流程會把已輸出的日期／序號映射到 UI，日價合併會顯示檔案與整合檔 chunk，SQLite CSV 匯出會顯示預估總筆數與已處理筆數，並保留舊 service double 相容性。這只改善等待期間的可見性，不改下載、合併、SQLite 寫入或日期完整性判定。
- 2026-08-27：大型每日合併新增單一 CSV 內的讀取批次取消檢查；完整檔案讀完才會納入待提交集合，取消不會產生半份整合檔或替換既有目標。這仍是批次邊界取消，不提供逐列中斷。
- 2026-08-27：修正資料更新個別來源詳情查詢失敗時的錯誤顯示；現在只會將該來源標為異常，不再把其他來源狀態卡誤刷成錯誤。
- 2026-08-27：補強資料更新頁顯示一致性：全域／各來源日期控件的「今日」統一採台灣市場日期；localized `不可用` 會顯示為異常而非待更新；全域狀態檢查失敗會清除六個核心與三個候選來源頁的舊 inline 摘要並保留共同錯誤原因，候選來源分頁也會顯示檢查結果，方便排錯且不誤讀舊數字。
- 2026-08-28：資料更新狀態卡與來源詳情會將 `degraded`／`partial`／`action_required` 等狀態統一轉成中文；核心資料落後 daily reference 時，直接顯示新鮮度基準日與資料最新日，並保留來源錯誤訊息供排錯。
- 2026-08-28：Data Update「全部資料」新增 `program-readiness.v1` 七 lane 唯讀投影；設定 `PROGRAM_READINESS_ARTIFACT` 後可在同一頁查看整體狀態、blocker 與 next action，未設定／schema 錯誤會 fail-closed，且不會授予任何正式 gate。
- 2026-08-28：資料更新頁新增「本次手動更新」唯讀摘要，將 UI 觸發的執行中／完成／失敗／錯誤／取消與排程時間軸分開顯示；保留本輪資料區間、失敗步驟、日期計數與警告，避免失敗後只看到上一輪排程成功結果。
- 2026-08-28：手動更新以失敗／背景例外結束後會自動做唯讀狀態重查，揭露可能已提交的部分 CSV／SQLite 變更；不重跑寫入、不把部分成功改標成完整成功。
- 2026-08-28：Data Update 狀態卡燈號改為保留 `partial`／`degraded`／`action_required`／`running`／`pending_human_review`／`not_configured` 等細分語意，分別顯示部分完成、需注意、需處理、進行中、待人工覆核、未設定；machine token 仍保留於卡片內文，避免不同處理路徑被誤讀成同一個「待更新」。
- 2026-08-28：補齊 Data Update 共用狀態投影，`date_mismatch`／`transport_error`／`registry_error`／磁碟空間不足／成本帳缺漏等診斷碼不再直接漏出英文；官方無資料維持「官方無資料」的可辨識狀態，不再在低階燈號中誤標成一般異常。
- 2026-08-28：P0 Data Update／Research Console 的 coverage 欄位改名為「解析通過率」，明確標示 accepted／observed／blocked 分母；不再讓 parser 通過率被誤讀成官方市場 universe 完整覆蓋率。
- 2026-08-28：Data Update 狀態卡補齊 `not_computable`、`pending_human_review`、`blocked`、`running` 等常見服務狀態的繁中投影，並讓「解析通過率」與既有期別／覆蓋提示一樣出現在卡片摘要；只改善可讀性，不改 readiness 或資料邊界。
- 2026-08-28：月營收狀態卡新增明確 `MONTHLY_REVENUE_SNAPSHOT_CANDIDATE` 唯讀入口；同一期 snapshot 也會顯示抓取日，外部候選遺失／命名無效時保留缺漏與診斷，不再靜默退回另一份 snapshot。候選仍不會自動寫入正式 SQLite 或 availability mapping。
- 2026-08-28：Direct/OOC scheduled wrapper 新增唯讀 filesystem headroom preflight；輸出所在磁碟低於預設 20 GiB 時只寫 `blocked_insufficient_storage` 與 `storage_preflight`，不啟動重建、不進 retry loop、不刪除既有 run，避免 `Errno 28 No space left on device` 反覆消耗容量。這不改 Formal／promotion／broker gate。
- 2026-08-28：Runtime 排程 read model 新增 `ML Direct/OOC 維護` 安全工作；`blocked_insufficient_storage` 會以「需要注意」與明確容量 diagnostic 顯示，並保留 raw status／source path 供排錯。
- 2026-08-28：整體 readiness 盤點新增 `--ml-direct-chain-status`；載入 Direct/OOC maintainer status 後，performance lane 會明確投影 `direct_chain_storage_preflight_blocked`／磁碟不足診斷與下一步，仍維持唯讀、不啟動 worker、不刪除歷史 run。
- 2026-08-28：整體 readiness 盤點新增 `--runtime-readiness-json`；可載入明確 host-context `runtime-environment-readiness.v1` artifact，避免 sandbox token 的 `PermissionError` 覆蓋 host 狀態；schema 不符即 fail-closed，仍不寫正式 Registry。
- 2026-08-28：新增 `scripts\inspect_research_registry_transaction.py` 與 `--runtime-registry-snapshot-probe`；以正式 Research Registry 的 read-only snapshot 在 TEMP clone 驗證 schema／quick_check／insert／rollback／source hash 不變，明確區分 clone proof 與正式 production writer／ACL 證據。
- 2026-08-28：修正 Evidence Operations weekly review CLI 在 Windows CP1252 主控台輸出繁中 JSON 時的編碼錯誤，統一先設定 UTF-8 console；同輪補登錄新測試檔並同步 inventory，最新全量回歸為 `3747 passed / 1 skipped / 26 warnings`（`532.28s`）。
- 2026-08-28：新增 `inspect_ml_storage_retention.py` 唯讀容量／retention inventory；可對明確 Direct/OOC 根目錄做 bounded metadata scan，列出完整／截斷狀態、manifest status 與 owner review 候選，固定不刪除、不搬移、不修改 lock／pointer。
- 2026-08-28：P0 條款候選證據若同一來源的多個官方 URL 出現「部分成功、部分失敗」，Data Update／Research Console 改顯示 `capture_partial` 與「部分取得，仍需複核」，保留已取得 hash 與失敗原因；這只修正可觀測性，不改變 `license_accepted=false` 或下游資格。
- 2026-08-28：P0 bounded probe／owner packet 新增受限的 HTTP `Date`、`Last-Modified`、`ETag` 與 `Content-Type` transport evidence（含 fallback lineage）；這些欄位只供診斷與 owner review，永遠不會升格為 publication／PIT timestamp，也不會複製敏感 header。
- 2026-08-28：MOPS 季報 availability CLI 啟動時先以容錯方式設定 UTF-8 stdout/stderr；Windows CP1252 主控台執行 `--help` 或輸出繁中 summary 不再因 `UnicodeEncodeError` 中止，且不改變查詢、候選輸出或正式 gate。
- 2026-08-29：Paper Portfolio daily CLI 啟動時也先以容錯方式設定 UTF-8 stdout/stderr；Windows CP1252 主控台執行 `scripts/run_paper_portfolio_daily.py --help` 或顯示繁中受控狀態時不再因 `UnicodeEncodeError` 中止，且不改變 snapshot、ledger、正式行情 DB 或 broker 邊界。
- 2026-08-28：MOPS 季報 availability CLI 新增 1–31 天分段 query 與最多 3 次 error-only retry；artifact manifest 保留每段 query window、attempt count 與前次錯誤碼，讓 MOPS 1,000 列上限及暫時網路錯誤可重試但仍可稽核，不把失敗誤標成官方無資料。
- 2026-08-28：歷史 MOPS EZSearch row schema drift（例如缺 `CTIME`）改採逐列 quarantine；artifact 會保留 bounded invalid samples／完整錯誤計數並標成 `degraded`，不再因單一 malformed row 丟掉同一回應的有效列。
- 2026-08-28：季度財報 backfill dry-run 新增完整 diagnostics／missing-availability 計數與 20 筆 bounded console 輸出；缺 `available_date` 仍 fail-closed，且明確提供 raw／availability 路徑時不初始化不必要的正式 config／log side effect。
- 2026-08-28：季度財報 backfill CLI 支援重複 `--availability-file`；相同完整列去重、natural-key provenance 衝突由 revision validator fail-closed，允許多個官方窗口累積 coverage 而不覆蓋證據。
- 2026-08-28：完成 retroactive baseline + MOPS candidate 的 hybrid dry-run，證明現有 `financial_data` 可全量 normalized；文件明確要求以 quality 分布區分 `observed` 與 `degraded`，不把 schema coverage 誤當 Formal／PIT 完成。
- 2026-08-28：backfill plan／CLI 新增 `quality_counts`，在 `ready_for_apply` 旁直接顯示 records 的 `observed`／`degraded` 分布，降低把可套用 schema 誤讀成正式 gate 通過的風險。
- 2026-08-28：歷史 MOPS 查詢說明補上 `official_no_data_query_count` 與真正 `failed_query_count` 的分流，避免官方空回應被當成 network outage 或被其他月份資料補成完整 coverage。
- 2026-08-28：歷史 MOPS candidate 已可按季度公告窗口持續回溯至 2022-Q1；操作手冊保留單獨 validator、單獨 backfill 與多檔 hybrid dry-run 的判讀方式，並明確禁止將部分 observed rows 視為全期間 PIT。
- 2026-08-28：MOPS 歷史 candidate 回溯再延伸至 2021-Q4；下一段仍以 2021-Q3 公告窗口為目標，所有查詢保持 31 天上限、7 天分段、bounded retry 與 candidate-only 輸出。
- 2026-08-28：MOPS 歷史 candidate 回溯再延伸至 2021-Q3；下一段仍以 2021-Q2 公告窗口為目標，所有查詢保持 31 天上限、7 天分段、bounded retry 與 candidate-only 輸出。
- 2026-08-28：MOPS 歷史 candidate 回溯再延伸至 2021-Q2；下一段仍以 2021-Q1 公告窗口為目標，所有查詢保持 31 天上限、7 天分段、bounded retry 與 candidate-only 輸出。
- 2026-08-28：MOPS 歷史 candidate 回溯再延伸至 2021-Q1；下一段仍以 2020-Q4 公告窗口為目標，所有查詢保持 31 天上限、7 天分段、bounded retry 與 candidate-only 輸出。
- 2026-08-28：MOPS 歷史 candidate 回溯再延伸至 2020-Q4；下一段仍以 2020-Q3 公告窗口為目標，所有查詢保持 31 天上限、7 天分段、bounded retry 與 candidate-only 輸出。
- 2026-08-28：MOPS 歷史 candidate 回溯再延伸至 2020-Q3；下一段仍以 2020-Q2 公告窗口為目標，所有查詢保持 31 天上限、7 天分段、bounded retry 與 candidate-only 輸出。
- 2026-08-28：MOPS 歷史 candidate 回溯再延伸至 2020-Q2；下一段仍以 2020-Q1 公告窗口為目標，所有查詢保持 31 天上限、7 天分段、bounded retry 與 candidate-only 輸出。
- 2026-08-28：MOPS 歷史 candidate 回溯再延伸至 2020-Q1；下一段仍以 2019-Q4 公告窗口為目標，所有查詢保持 31 天上限、7 天分段、bounded retry 與 candidate-only 輸出。
- 2026-08-28：MOPS 歷史 candidate 回溯再延伸至 2019-Q4；下一段仍以 2019-Q3 公告窗口為目標，所有查詢保持 31 天上限、7 天分段、bounded retry 與 candidate-only 輸出。
- 2026-08-28：MOPS 歷史 candidate 回溯再延伸至 2019-Q3；先重跑 unified readiness，再決定是否以 2019-Q2 公告窗口為下一段，所有查詢保持 31 天上限、7 天分段、bounded retry 與 candidate-only 輸出。
- 2026-08-28：歷史 MOPS candidate 回溯至 2019-Q3 後完成 unified readiness recheck；修正 baseline 輸入後只保留真實 blockers，availability candidate 仍不自動接入正式 mapping／SQLite、Formal 或 scheduler。
- 2026-08-28：歷史 MOPS candidate 再延伸至 2019-Q2（2019-08）與 2019-Q1（2019-05）；兩個窗口均以 7 天分段、bounded retry、官方無資料／真正失敗分流與逐列 quarantine 取得候選 mapping。合併 dry-run `availability_file_count=23`、raw／normalized=`1,645,555 / 1,645,555`、quality=`observed 749,071`／`degraded 896,484`；仍禁止自動 apply、PIT／Formal 或 scheduler credit。
- 2026-08-28：歷史 MOPS candidate 再延伸至 2018-Q4（2019-03）；40/40 有資料 query、40 個官方無資料、真正失敗=`0`，8 筆缺 `CTIME` 逐列 quarantine。加入後合併 dry-run `availability_file_count=24`、quality=`observed 782,656`／`degraded 862,899`，仍禁止自動 apply、PIT／Formal 或 scheduler credit；下一段可重跑 2018-Q3（2018-11）。
- 2026-08-28：新增 `build_evidence_weekly_approval_input.py` 唯讀交接流程；可把 weekly sidecar 的 8 筆 `pending_human_review` 列整理成 `evidence-weekly-approval-input.v1`，供具名 owner／reviewer 逐期填寫，但不產生 approved projection、不授予 Formal credit、不寫 sidecar／正式 DB。
- 2026-08-28：新增 `build_formal_input_owner_packet.py` 唯讀 owner handoff；將 bounded Formal candidate inventory 整理成 `formal-input-owner-review.v1`，讓三項 expected input 有具名 owner／reviewer review slot 與 bounded candidate metadata；不選 candidate、不發布正式 manifest、不授予 Formal／promotion／broker credit。
- 2026-08-28：新增 `build_performance_canary_owner_packet.py` 唯讀效能 owner handoff；將 technical／worker／broker／Direct-OOC storage／retention TEMP evidence 組成 `performance-canary-owner-review.v1`，固定 candidate-only、不寫入、不刪除／搬移、不啟動 production worker／fetch pool。容量不足、technical canary 與 broker long-term review 仍維持原 gate。
- 2026-08-28：readiness 聚合入口會先 trim／去重 blockers 與 next actions；Data Update／Research Console 不再因 evidence payload 的前後空白顯示多餘縮排或重複提示。這只改善唯讀可讀性，不改變 machine token、gate、寫入權限或 owner decision。
- 2026-08-28：以 host artifacts 重新產生含 performance owner packet 的完整 readiness 唯讀基線；七 lane 狀態維持原判定，blocker／next action whitespace check=`0`，owner packet 仍待具名 reviewer，未因顯示修正而開啟任何正式 gate。
- 2026-08-28：修正資料更新下鑽頁的唯讀狀態路由：三大法人／信用交易／集保股權不再回報 `unknown source`，會讀取明確 `PHASE3C_CANDIDATE_DB_PATH` 的候選 DB；排程狀態也會從 scheduled artifacts 重新彙整並同步更新摘要／raw JSON。這些查詢不寫 status manifest、正式 SQLite 或 Windows Task Scheduler。
- 2026-08-28：候選資料卡統一顯示 `最新日期`、`總記錄數`、資料區間與覆蓋率；候選資料有列時不再因舊版 `總筆數` 欄位文字而顯示 `--`／未知。服務回傳 malformed 日期或計數時，畫面採 `未知`／`0` fail-closed，並保留原始狀態與 warning 供排錯。
- 2026-08-27：修正資料更新狀態卡 placeholder 被誤解析成 `待更新`；未執行檢查時現在固定顯示灰色 `未檢查`。
- 2026-08-27：Data Update 全部資料新增 P0 官方來源證據唯讀 projection；全域狀態檢查會把明確指定的 audit／owner decision 與核心資料狀態一起呈現，逐列保留 actual route、fallback lineage、PIT／公告、coverage、license、owner decision 與 `downstream_eligibility=none`。未設定時是 `contract_only`，artifact 遺失／格式錯誤時是 `audit_unavailable`，不會掃描正式目錄、發網路請求或把 candidate 升格為正式來源。
- 2026-08-27：持倉管理的「情境壓力」新增明確確認式 Stress history v1；UI 與 `append_portfolio_stress_history.py` 可預覽／保存 hash-idempotent 研究快照，並由 query-only history table 唯讀揭露。此歷史仍不構成正式績效、交易 evidence 或投資有效性。
- 2026-08-26：持倉管理新增 Gate 4 的「情境壓力」與「匯入交易 CSV」入口。前者以 Decimal 做固定情境的研究唯讀投影，缺價／缺必要來源時 partial 或 not-computable；後者先做 UTF-8／CP950、欄位、日期、hash 與重複 ID 預覽，只有二次確認才批次驗證並 append。兩者均不接券商、不自動交易；Paper NAV、Equal Weight 成本後 evidence、fill 狀態與壓力歷史仍待後續。

- 2026-08-14：決策工作台首頁改為「今日行動中心」，以既有唯讀 DTO 將資料狀態、市場待判讀、Advice／候選與持倉覆盤整理成四個入口，並只提供導向既有工作區的下一步按鈕；不會更新資料、執行策略、寫入持倉或交易。主工作區也改為只由目前可見頁面決定最小尺寸，1024×768 時左側導覽會自動收為 icon-only，避免隱藏頁面強制放大視窗。

- 2026-08-13：修正 Phase 3C backfill 對 TWSE／TPEX 現行 `tables[].data`、三大法人 24 欄與信用交易 15 欄 schema 的解析，加入回應日期 fail-closed 與 TDCC 最新週 snapshot 明確選項；歷史 TDCC 仍維持 blocked。桌面 App 新增啟動前 native／Python／背景執行緒 crash diagnostics，DBManager／DataLoader 的檔案日誌失敗改為 console-only 降級，並保留既有合作式安全關閉契約。另修正 Direct/OOC release follow-up 將 `output/release_v4` 重複附加為共同 output root 的問題，後續 promotion／authority／daily orchestration 會讀取正確的 scheduled proof 路徑，仍維持 fail-closed 與 `--auto-catch-up` 時序限制。

- 2026-08-12：自動完成 immutable raw PIT publication、Direct numeric v4 與 OOC v5 續接訓練；新 Direct／OOC manifest、年度 checkpoint、hash custody、41-fold OOC、記憶體限制與 look-ahead 驗證均已落盤。另自動完成當日 data-update quick，core date 推進至 2026-08-12；evidence 已通過 strict T-1 proof，但因三項正式 readiness blocker 維持 fail-closed。新增的 chain maintenance supervisor 會以同一 run identity 自動防重複與中斷續接，formal alpha=0、broker order=false。
- 2026-08-13：修正 allocation copilot `--auto-catch-up` 的 scheduler clock 邊界；當 runtime 證明候選日 strict T-1 尚未就緒時，會正確進入 hash-bound 的最近已過交易日重試，且不改變明確指定日期、資料寫入或 formal promotion gate。後續補入 Direct/OOC formal-input watcher 與 raw PIT refresh regression 後，完整 collection 為 `3134` tests；完整回歸結果以本輪 QA 紀錄為準，formal alpha 仍為 0。

- 2026-08-06：月營收／季報 availability 新增 `formal-availability.v2` provenance contract；正式讀取端只接受 v2 或兩組限縮 legacy 官方 mapping，並以 mapping 與 SQLite row 的完整日期對應隔離無正式公告證據的舊 first-seen 快照。完成 OOC v5 custody resume，但 promotion evidence 仍 blocked、alpha 維持 0；Runtime 改為分開呈現營運 artifact 與治理事件，UI 關閉改採非阻塞合作式取消。

- 2026-07-14：修正 TWSE 平日休市補檔判斷；颱風等官方無交易資料日不再因備援查詢的 HTTP 307 被誤判為失敗，未知網路錯誤仍 fail-closed。全部資料的月營收狀態卡改為分開顯示已匯入期別、目前 PIT 可用期別與待生效日。

- 2026-07-13：校正目前 weekly evidence operations history 為 `1/3 waiting_for_time`；這只同步既有 Week 1 證據，不改 production scheduler、external Gate completion 或正式產品 closeout。
- 2026-07-13：Daily Decision Desk 改為「市場探索 > 市場總覽」index 0 的唯一實例；Workbench「決策來源」改為純導覽，不再嵌入第二份 widget。市場總覽新增月營收、三大法人與五類來源的資料可見性區塊；可見性維持 read-only、PIT-aware、fail-soft，且不參與 action、focus、Score 或既有整體品質聚合。
- 2026-07-12：新增 V2.2 三週 weekly review runbook 入口與 working-copy 保存步驟；目前 weekly `0/3 waiting_for_time`、multi-day `3/3 ready`、scheduler 未核准，不能 formal closeout。
- 2026-07-12：新增 Gate 1 Advice 唯讀操作、Guided / Professional Mode、安全拒絕輸出、平衡限制、日期 / source trace 與不交易邊界；weekly review working-copy 保存仍是 Gate 2 真實時間工作。
- 2026-07-12：新增 V2.3 P0 資料來源人工接受台帳操作規則；candidate readiness、`decision_ready_candidate` 與正式 accepted feature 明確分離。所有未決 P0 source 維持 `requires_human_acceptance`、`downstream eligibility=none`，不啟用 ingestion、`ScoringEngine`、scheduler 或交易。
- 2026-07-09：統一推薦最新價格／成交量衍生特徵，新增預設參數技術指標安全 reuse，並讓 Daily Decision Desk 在單次 snapshot 內共用 read-only 市場 frame；公開 service / scheduler 介面、DTO、SQLite schema、scoring、threshold 與 dry-run / confirm gate 均維持不變。

- 2026-07-08：Phase 3C governed ingestion candidate 已建立 manual-only dry-run/apply 邊界；不屬於今晚 V3.0 closeout gate。
- 2026-07-07：左側主導覽從兩字母縮寫升級為自製線條 SVG icon，並保留 icon-only 收合模式；Runtime Observatory 改為緊湊 scope note，避免大片空白；Workbench 總覽新增四個指揮台摘要 block，Evidence / 持倉追蹤 / 操作節奏標示為摘要與下鑽入口 / 預留深挖區；市場探索弱勢個股與弱勢產業的 `跌幅%` 以正數顯示並用紅色代表下跌語意。以上只改 UI presentation，不啟用 scheduler、不寫 DB、不補 Phase gate。
- 2026-07-07：主 UI 改為左側主導覽，預設進入「決策工作台」；「每日決策」整併為「決策工作台 > 決策來源」，「市場觀察」改名為「市場探索」。Workbench 新增今日待判讀空狀態與 session-only 已查看提示；當日 Phase 0 weekly history `0/3` 與 multi-day dry-run `1/3` 仍需正式資料累積，不能用 replay 或 UI 狀態補齊。後續 multi-day dry-run record 已達 `3/3 ready`，weekly history 與 manual review / action-item rhythm 仍待真實時間累積。
- 2026-07-06：更新 V2.0 Phase 1 / Phase 1.5 read-only Workbench prototype CLI 操作說明，標示 sample、受控 `--db-path` / `--decision-date`、Pre-V2 readiness、Daily Decision durable snapshot、AgentEvidenceAccess summary、replay JSON summary、degraded source diagnostics 與不寫 DB / 不啟用 scheduler / 不產生交易建議限制。
- 2026-07-05：新增 V1.6 cross-sectional factor snapshot inspection CLI 操作說明，標示 rank / quantile 僅供研究 attribution，不是推薦、不改 `ScoringEngine`、不建立 DB、不啟用 scheduler。
- 2026-07-02：完成 V1.2 Research Credibility & Execution Model v1 操作說明，補充 Profile replay 訓練 / 驗證分離、推薦回放 rolling risk metrics、microstructure preflight、relative attribution 與仍未完成的實盤撮合 residual。
- 2026-07-02：完成主 PySide6 UI 金融研究工作台視覺整理；統一設計 token、表格樣式、按鈕 variant、空狀態與缺字 icon 清理，並明確維持資料抓取、推薦、回測、每日決策與持倉計算邊界不變。
- 2026-07-02：Research Lab 策略回測日期欄與證據覆盤日期篩選改用受控日曆 popup；開啟時定位今天，未設定日期不再讓日曆停在 sentinel 年份。
- 2026-06-30：縮小 Research Lab 參數最佳化列的 label 留白；強 / 弱勢個股產業共振理由改用最新產業表現快取，正式資料路徑載入由約 13 秒降至約 0.6 秒；Smart Money 集中度、語意狀態、診斷與 Badges 欄改為依最長內容貼合寬度，近期趨勢欄維持 compact 固定寬度且直方圖以緊湊間距與左側 padding 繪製。
- 2026-06-30：Smart Money 右側分點明細表改為依 panel 寬度自適應四欄，移除固定欄寬，優先保留淨買賣超數值與 bar 的顯示空間，避免不必要水平捲動。
- 2026-06-30：每日決策總覽 warnings 與持倉警示來源歸因改為 UI 顯示中文化，底層 warning token 與 DTO 資料維持原樣供除錯追溯。
- 2026-06-30：調整 Research Lab 左側設定面板與 Smart Money 主表欄寬；策略回測長下拉欄位預設可完整顯示，主力流向以 compact 5D/20D/60D 診斷與固定欄寬保留近期趨勢圖。
- 2026-06-30：市場觀察的強 / 弱勢個股與強 / 弱勢產業改為 SQLite-first 快速載入，只讀近期交易日必要欄位；SQLite 不可用時才降級既有 CSV / 舊查詢路徑。
- 2026-06-30：快速更新與安全更新的預設補齊窗口改為結束日前最近 10 個工作日；快速更新仍跳過大型合併但不再只限最近 2 天，降低兩週才開啟程式時漏抓資料的風險。
- 2026-06-30：新增 executable opt-in MainWindow UI smoke 說明；可啟動真實 MainWindow、切換 tab、截圖、測 resize evidence 與 Update 強制合併 cancel dialog，且預設 healthcheck 不會啟動 MainWindow。
- 2026-06-29：補充 Full App Healthcheck Runner 分頁驗證方式；`--tab` 可分別驗證 Update、Market、Decision、Research、Recommendation、Watchlist、Portfolio、Runtime 與 cross-flow 的安全 direct bridge，完整真人 UI smoke test 仍以母檔人工確認為準。
- 2026-07-01：新增 Research Lab `Forward Evidence` 分頁操作說明，標示 Forward Performance Dashboard read-only UI v1 只檢查已保存 evidence summary，不重算策略、不寫 evidence、不建立 scheduler，且 close-to-close forward return 不是實盤可執行績效。
- 2026-07-01：新增 Evidence Pipeline Runner 手動 dry-run CLI 操作說明，標示 runner 預設 dry-run、confirm 只允許 working-copy DB、readiness 最高只到 `ready_for_manual_confirm`，production scheduler 仍未啟用。
- 2026-07-04：補充 V1.5 data credibility CLI 操作說明，新增 source capability registry、corporate action policy 與 evidence source coverage 分級；payload partial 為 warning / `dry_run_only`，durable source missing 才是 blocking gap。
- 2026-07-01：新增 working-copy DB smoke 與 scheduler readiness evaluator 操作說明，標示 source DB read-only、repeat confirm idempotency check、`production_scheduler_allowed=false` 與正式排程前人工核准 checklist。
- 2026-07-01：新增 Live vs Research Gap linkage CLI 操作說明，標示 gap observation 是 evidence，不是 action；沒有真實交易與人工 override 時只能解讀為 research / simulated gap。
- 2026-07-01：新增 Signal Decay Monitor CLI 操作說明，標示 decay observation 與 lifecycle proposed payload 只是人工審核 evidence，不自動套用策略生命週期動作。
- 2026-07-01：新增 Decision Quality Review CLI 操作說明，標示 review item 與 process quality score 只作流程覆盤，不是投資能力、交易建議或責備判斷。
- 2026-07-03：新增 V1.4 Evidence Operations weekly review history 操作說明與 Research Lab `Evidence Review -> 覆盤歷史` 子頁說明；history 只保存人工覆盤快照，不啟用 scheduler、不自動 lifecycle action。
- 2026-07-01：新增 Research Lab `Evidence Review` 分頁操作說明，標示 Forward Evidence、Live vs Research Gap、Signal Decay 與 Decision Quality dashboard 只讀已保存 evidence / observation / review，不寫 evidence、不建立 scheduler、不自動 lifecycle action。
- 2026-07-02：新增 Evidence Review manual smoke、multi-day dry-run record 與 scheduler approval SOP 操作說明，標示這些是 production scheduler 前的人工 QA scaffold，不代表 scheduler 已啟用。
- 2026-07-02：Evidence Review UI 介面中文化，Research Lab 結果分頁顯示為「證據覆盤」，四個子頁顯示為「前瞻證據 / 研究落差 / 訊號衰退 / 決策品質」，日期篩選改用日曆選擇器。
- 2026-07-02：證據覆盤頁新增「目前資料庫」資訊列與複製路徑按鈕，協助人工 smoke 時確認 UI 實際讀取的 SQLite DB。
- 2026-07-07：證據覆盤新增「排程狀態」子頁，只讀顯示 latest data freshness、scheduled recommendation snapshot、scheduled evidence dry-run、report preview 與 `confirm / writes_recommendation_result / writes_evidence_db / auto_trading / lifecycle_action` 邊界，方便在 UI 檢查當日 Windows Task Scheduler 產物；此頁不重跑 pipeline、不寫 evidence DB、不自動補 multi-day record。
- 2026-07-02：新增 safe scheduled wrappers 操作說明與 morning check guide；每日 task 僅做 read-only freshness check 與 evidence dry-run，working-copy smoke 預設 disabled / manual-only。
- 2026-07-04：更新 safe scheduled 操作說明為 CMD wrapper + `schtasks.exe` 現況，記錄 04:20 非 UI 快速資料更新、05:00 / 05:15 Windows Task Scheduler task 與 05:30 Codex app read-only 摘要 automation；production confirm 仍未啟用。
- 2026-07-05：新增 V1.8 Portfolio Construction & Execution Trace Sandbox 操作說明，標示 sample CLI 只輸出 research-only allocation / virtual trace，不讀正式資料、不建立持倉、不下單。
- 2026-07-06：新增 V1.9 Read-only Agent / MCP Evidence Access 操作說明，標示 `twstock-evidence-access` 只讀 evidence / source trace / quality / warnings，不寫 DB、不改策略、不下單、不套用 lifecycle action。
- 2026-07-06：新增 Pre-V2 readiness inspection CLI 操作說明，標示它只做 read-only 非排程前置檢查，不取代多週 history / multi-day dry-run / scheduler approval。
- 2026-07-07：更新 Qt `決策工作台` Phase 2 Workbench MVP shell 操作說明，標示中文優先顯示、舊 Daily Decision / Evidence Review / Portfolio read-only drill-down、預設 `_reference_fix` replay JSON summary 分析，以及 source gap coverage / benchmark coverage / industry benchmark coverage 限制；UI 只透過 `WorkbenchSourceService` / `WorkbenchDashboardDTO`，不直接讀 SQLite、不寫 DB、不啟用 scheduler、不產生交易建議。
- 2026-07-08：補充 Pre-V2 readiness 修正後歷史觀察日規則；source-gap closeout 可採信同日 scheduled dry-run `latest_status.json` 的 read-only 證據，但仍不寫 DB、不啟用 scheduler、不代表 production approval。
- 2026-07-08：新增 V3 score effectiveness audit CLI 操作說明；`inspect_score_effectiveness.py` 以 read-only 方式輸出 `TotalScore` raw bucket、forward outcome、benchmark / industry excess、limitations 與安全邊界，不寫 DB、不提供 `--confirm`、不改分數 / threshold，也不訓練 ML model。
- 2026-07-07：補充 Workbench background evidence feed / read-only Action Items MVP 操作說明；背景證據流只彙整既有 DTO / service payload，Action Items 每列帶 source trace、degraded reason 與 drill-down target，且不建立 repository、不寫 DB、不套用 lifecycle。
- 2026-07-07：補充 Workbench Action Items 人工佇列操作說明；Action Items 依 severity / queue group / source 排序並顯示來源，row drill-down target 與舊頁導向一致，Evidence Feed / Action Items 空狀態與降級狀態文案維持只讀、非建議、不補值邊界。
- 2026-07-07：補充 Workbench Phase 2C / 2D 操作節奏 closeout；Operating Loop 只顯示 daily first-look、manual queue、weekly history、multi-day dry-run、manual review note 與 scheduler gate，不寫 DB、不標記完成、不補真實時間 gate。
- 2026-07-07：新增 Simulated Phase Progress / Phase 5 Approval Rehearsal 操作說明；historical replay 可用於 simulated Phase 0-5 審核包預演，但 weekly history、multi-day dry-run、manual review/action item rhythm、source acceptance、execution realism、backup / rollback / recovery 與 explicit approval 必須等正式資料才能標為 completed。
- 2026-07-06：修正 TPEX 每日股價缺日判讀；手動 / 一鍵更新會在 TPEX 缺日期時標示未完整，Windows data update quick task 會輸出 `passed_with_warnings`，freshness probe 會檢查 TWSE / TPEX 原始日檔並在 TPEX 缺檔時標示 `degraded`；技術指標 skip 判斷也新增最新日 eligible 股票覆蓋檢查，避免 TPEX 後補時漏算。
- 2026-07-06：新增 Historical Evidence Replay 操作說明，標示 replay 只在 working-copy / replay DB 逐日重放 evidence，事件會標示 `historical_replay` / `simulated_scheduler`，不取代真實 scheduled dry-run、weekly history、多日 dry-run 或 production scheduler approval。
- 2026-07-06：補充 Historical Replay reference return fix 結果判讀，說明 TAIEX benchmark fallback、market `收盤價` fallback、industry payload gap 與 `source_missing_screening_matrix` 限制。
- 2026-07-06：補充 `_reference_fix` replay artifact cleanup 後位置；JSON / report / replay DB 已移至 `D:/Min/Python/Project/FA_Data/output/evidence_pipeline/historical_replay_reference_fix_20260706/`，Workbench CLI 範例改讀 D 槽 JSON summary。
- 2026-07-06：修正 Evidence Pipeline Runner dry-run report 的 source coverage 判讀；同輪 transient Daily Decision Desk snapshot 會解除 stale durable snapshot missing 並標示 coverage basis，仍不寫 durable snapshot 或 production evidence DB。
- 2026-07-06：scheduled evidence dry-run `latest_status.json` 新增 pipeline summary / source coverage 摘要欄位，讓 morning report 可直接辨識 V1.7 payload readiness 與 diagnostics，而不需只解析完整 markdown report。
- 2026-07-09：Evidence Pipeline Runner dry-run summary / markdown report / scheduled `latest_status.json` 分開記錄 warnings 與 advisories；MoneyDJ 完整 observed / estimated provenance 會顯示 `ready_with_advisories` 與每檔 observed / estimated / unavailable 計數，真正缺失、過期或 blocking gap 才是 `degraded`。固定門檻推薦未保存可比較母體時，百分位標為不適用，不從已選推薦股補造百分位。此欄位只揭露既有來源品質，不寫 evidence DB、不改分數或交易行為。
- 2026-08-05：修正 scheduled evidence dry-run 的 root 傳遞與 America/Los_Angeles 日期一致性；status 明確保存 `confirm=false`、`production_scheduler_allowed=false`，並區分自然 `insufficient_future_data` 與真正需人工處理的 warning。Decision Desk SQLite 來源讀取固定使用 `mode=ro/query_only`。
- 2026-07-07：新增 `baldr-recommendation-snapshot-daily` / `run_recommendation_snapshot.cmd`，預設在 05:10 自動保存 research-only recommendation snapshot；05:15 evidence dry-run 可接著讀取當日最新推薦 payload。UI「證據覆盤 -> 排程狀態」會顯示 recommendation result id、推薦筆數、screening matrix rows 與安全旗標。
- 2026-07-07：決策工作台背景證據流新增 `Scheduled morning pipeline`，顯示 latest scheduled recommendation/evidence 狀態與共同觀測天數；此數字用來確認每日排程產物是否累積，不自動替代正式 multi-day dry-run record gate。
- 2026-07-07：排程狀態與 Workbench 背景證據流新增 same-day manual recommendation fallback；當 scheduled recommendation latest status 缺失但同日人工 `rec_YYYYMMDD_*.json` 存在時顯示 `manual_observed / manual_result`，並明確保留 scheduled latest status missing、production scheduler disabled 與 official gate 不自動完成的邊界。
- 2026-07-07：排程狀態明細改為判讀摘要優先，只在 UI 內保留裁切後 report preview；完整 source coverage JSON 與 diagnostics 仍以 `report_path` 原始 markdown 為準，避免人工判讀時被大段 raw payload 淹沒。
- 2026-07-07：Workbench 總覽降密度改版；背景證據流改為緊湊三欄清單，完整 source trace / degraded reason / diagnostics 改由右側 Inspector 顯示，操作節奏、Evidence mode、Daily Checklist 與 Warnings 改為可收合區塊；僅改 UI presentation，不寫 DB、不啟用 scheduler、不補 Phase gate。
- 2026-07-07：補充 Workbench 總覽可讀性改版；操作節奏改為 timeline card、Evidence mode 改為雙摘要卡與 Inspector diagnostics、Daily Checklist 改為 status card、Warnings 改為分組與展開顯示；僅改 UI presentation，不寫 DB、不啟用 scheduler、不補 Phase gate。
- 2026-07-07：更新 Research Lab `Registry 比較` 操作說明；比較狀態改為深色語意列，參數 / 指標 / Regime / Benchmark 改為摘要卡優先，標準化權益空狀態補明觸發方式與共同日期條件；僅改 UI presentation，不改 Research Run Registry 資料或回測計算。
- 2026-07-07：補充主導覽與 Research Lab 空間操作；目前已選主工作區按鈕可再次點擊收合 / 展開左側主導覽，策略回測頁標題列可收合左側設定面板，Registry 比較以 A / B / C 代號對應長 run 名稱，降低長字串對閱讀的干擾。
- 2026-07-07：調整 Research Lab 空間與說明互動；左側設定收合按鈕移至設定面板頂部，收合後才在標題列顯示展開入口；Registry 比較的指標區改為 A / B / C 小型對照表；全域按鈕文字清理不再移除 InfoButton 的 `i`。
- 2026-07-03：新增 V1.3 Evidence Operations weekly review CLI 操作說明，標示 manual approval package、action item planning、production scheduler disabled 與 signal decay candidate 不自動套用 lifecycle action。
- 2026-07-02：完成 V1.1 workflow bridge v1 操作說明，補充推薦 Profile 進階摘要、buy / sell score 與權重差異、推薦回放是 Profile / Config 歷史重播，以及升降級判讀需經 Research Run / Evidence 與人工 lifecycle gate。
- 2026-06-23：完成 Healthcheck Batch 2 計畫範圍實作後的操作說明：Daily Decision Desk answer-first dashboard、Smart Money 5 / 20 / 60 日語意診斷、quantity concentration 與股票焦點下鑽。
- 2026-06-23：完成 Healthcheck Batch 4 Research Lab 結果頁操作說明：推薦回放結果頁重排、Registry 比較中文化與空狀態、批次結果比較目的、Train-Test / Walk-forward 樣本可靠度提示。
- 2026-06-23：同步 Full App Healthcheck 修正後的操作說明；新增全部資料月營收狀態卡、Smart Money Top / Bottom 50 預設與分點雙擊跳轉、推薦分析「加入觀察清單」文案、Watchlist 直接送 Research Lab、Daily Decision warnings 中文化、Research Lab 最大持倉 0=無限制、固定門檻 / 百分位排名 tooltip 與推薦回放保存 / 成交假設提醒。
- 2026-06-23：補充推薦分析 Profile / Regime lifecycle：內建、自訂、策略版本 Profile 來源標示，自訂 Profile 未回測驗證警示，Profile-Regime match / mismatch / bonus / penalty 判讀，以及 mismatch 不直接排除推薦結果的安全限制。
- 2026-06-23：補充 Healthcheck Batch 1 direct fixes：資料源檢查摘要與強制合併確認、Research Lab 模式 / 日期 / Registry 刷新 / 報告缺欄位診斷、持倉管理交易表單與監控中文化，以及 Runtime Observatory 監控範圍。
- 2026-06-23：修正每日股價手動下載 / 快速更新的日期邊界說明；開始日期會納入缺漏檢查，並補充 TWSE 股票日價缺漏排錯方式。
- 2026-06-17：完成 Month 5 Fundamental Layer v1 closeout 說明，確認月營收、季度財報與 P/E 估值已進 factor records / diagnostics；P/B、P/S 已補 guarded presentation policy，官方歷史 PIT 公告日保留為後續治理 residual，基本面仍不接 `ScoringEngine`。
- 2026-06-18：更新每日股價與 TPEX 操作說明，確認手動每日股價、快速更新與安全更新皆納入 TPEX 區間補齊、SQLite 同步與技術指標增量；新增背景補齊 TPEX + 技術指標狀態查詢說明，並修正 `3207` 歷史日價缺漏排錯判斷。
- 2026-06-18：更新每日股價日期選擇與 SQLite 資料檢視操作說明；日期預設空白、日曆定位今天、單一日期可一鍵今日、共用清除會清掉所有日期條件，券商分點篩選可使用下拉選單；背景 TPEX 補齊若技術指標已最新會跳過重算。
- 2026-06-18：修正每日股價大表合併說明與流程；`stock_data_whole.csv` 合併會同時納入 `daily_price/` 與 `daily_price_tpex/`，避免 TPEX 已有最新日檔但合併後大表最新日期落後。
- 2026-06-18：修正快速 / 安全更新模式說明亂碼；補充快速更新仍保留可追溯日檔 CSV、跳過大型合併重寫、券商分點會用 CSV / SQLite 先行跳過既有資料；補充技術指標增量合併缺日期時不直接疊加，避免單股指標檔倍增。
- 2026-06-18：更新 Daily Decision Desk 啟動行為說明，確認每日決策 Snapshot 改為背景載入，主 App 會先顯示工作台再更新每日摘要。
- 2026-06-17：完成 Month 6 Strategy Lifecycle / Portfolio Feedback v1 操作說明，補充 Registry-based Promote lifecycle gate、持倉管理「生命週期回顧」分頁、post-trade attribution 與 live-vs-research gap 判讀限制。
- 2026-06-17：補充 lifecycle evidence 持久化操作語意，說明 promotion applied evidence、demote / retire proposed evidence 與不自動刪除策略版本的安全限制。
- 2026-06-16：新增月營收 normalized backfill 操作說明，記錄 dry-run、正式 apply confirm、備份與缺 availability mapping 時 fail-closed 的行為。
- 2026-06-16：新增公司清單 / 產業 mapping 更新操作說明，記錄 TWSE/TPEX 官方 registry dry-run、正式 apply confirm、備份、`3207` TPEX daily price 缺口與 `9935` 產業修正。
- 2026-06-16：更新估值 metrics backfill 操作說明，記錄 P/E dry-run、產業 mapping、同產業分位、正式 apply confirm、備份與 831 筆正式寫入狀態。
- 2026-06-16：新增 TPEX daily price backfill 操作說明，記錄 TPEX official daily close quotes dry-run、正式 apply confirm、DB 備份、`3207` 日價補齊與 877 筆正式寫入驗證。
- 2026-06-16：新增月營收 availability mapping 維護說明，記錄 TWSE OpenAPI 候選產生器、validator 流程、正式資料寫入前人工確認要求，以及最新月端點與本機歷史 raw 期間暫無交集的限制。
- 2026-06-16：補充 TWSE/TPEX 月營收 historical dry-run builder，記錄最新月 OpenAPI 樣本、MOPS historical 自動化限制、`2020-01..2026-05` dry-run 0 candidate rows，以及正式 mapping / 月營收 backfill 的人工 gate。
- 2026-06-16：補充 MOPS HTML source-dir 操作方式，記錄 `--mops-html-dir` 檔名規則、`出表日期` requirement、`mops.monthly_revenue_announcement` source 與 fail-closed diagnostics。
- 2026-06-17：補充 `--mops-static` 操作方式，記錄新版 MOPS redirectToOld / mopsov historical static report 可驗證歷史 rows，但 `出表日期` 為查詢當日，會被 45 天合理揭露窗口 gate 擋下。
- 2026-06-16：補充授權 PIT 月營收公告日 CSV 匯入方式，記錄 `--pit-csv`、必填 `--pit-source-version`、支援欄位與 candidate-only / 人工 gate 限制。
- 2026-06-16：更新 SQLite 資料檢視操作說明，補充日期日曆選擇器、清除日期、資料庫端表頭排序、`daily_prices` 繁中欄位 alias 與 `漲跌價差` 正負號顯示規則。
- 2026-06-16：調整 SQLite 資料檢視日期控件說明，單一日期預設今天，日期區間預設本月 1 日至今天，清除後才不套用日期條件。2026-06-18 已改為預設空白，避免未注意到預填日期而誤套篩選。
- 2026-06-16：更新每日股價操作說明，確認快速 / 安全更新已納入 TPEX official daily close quotes；TPEX CSV 寫入 `DATA_ROOT/daily_price_tpex/`，SQLite 寫入 `daily_prices`，TPEX endpoint timeout 會以警告呈現且不阻斷其他資料同步。
- 2026-06-16：補充 SQLite Inspector 重複欄名防護、券商分點 `broker_flows` 主鍵納入 `trade_type`、TPEX 歷史缺漏判讀，以及 Full App Healthcheck 人工驗證入口。
- 2026-06-16：新增 Month 5 月營收候選資料抓取操作段，記錄今晚要跑的 MOPS snapshot 與 FinMind create_time 兩個 candidate-only CLI、輸出位置、resume / rate limit 與毛利率季度資料邊界。
- 2026-06-16：補充 MOPS first-seen 作為月營收主線候選來源、FinMind 退為備用 / 交叉檢查來源，並新增 `--mops-snapshot-file` 月營收 backfill dry-run 說明；正式 mapping 與 SQLite apply 仍需人工 gate。
- 2026-06-16：更新資料更新頁月營收分頁文案，將 MOPS 快照檔、正式可得日對照檔與版本名稱改為完整中文說明；SQLite 資料檢視白名單新增三張 fundamental tables，可直接檢視 `fundamental_monthly_revenues`。
- 2026-06-16：新增 `scripts/inspect_fundamental_factors.py` 唯讀檢視入口，可確認正式 SQLite 月營收已進 Revenue Factor Pack；目前 2026-05 單月資料可產生 3M trend / new high，YoY / MoM 仍因 baseline 不足只回 diagnostics。
- 2026-06-16：新增 `scripts/build_monthly_revenue_retroactive_baseline_mapping.py`，可從 MOPS snapshot 產生 retroactive baseline 候選 mapping；此來源只供導入日後決策使用，不作官方歷史公告日或導入日前回測。
- 2026-06-17：季度財報 baseline 已正式寫入 `fundamental_statement_items`，並新增 EPS、毛利率、營益率、ROE、業外損益 statement factor diagnostics；PB / PS 來源政策改為 guarded external-observation boundary。
- 2026-06-15：整理 Daily Decision Desk 顯示密度，將強弱與流動性代碼改為分行摘要並限制單類別顯示數量，避免主視窗被長清單撐寬。
- 2026-06-16：完成 Month 4 Daily Decision Desk 收尾說明，確認 section quality 以 header badge 顯示，強弱 / 流動性代碼採單一 compact list 呈現，UI 不重算 service snapshot 以外的 domain logic。
- 2026-06-15：補充 Portfolio Alert Attribution v1，說明每檔持倉警示的來源標籤、condition 狀態、chip risk level 與原因 token 歸因呈現，用於輔助警示來源之分析與判讀。
- 2026-06-15：補充 Why Not / 風險提示 v1 對接，說明如何由既有 section DTO 屬性與 quality/warnings 推導風險提示、各提示類別之解讀與 quality 降級規則。
- 2026-06-16：補充 Daily Decision Desk fundamental diagnostics 風險提示，說明異常基本面只作研究風險提示，不改財報、不扣分、不輸出交易建議。

- 2026-06-15：補充 Relative Strength / Liquidity Ranking v1 已由 SQLite `daily_prices` 接線，說明相對強度基點計算、20 日平均成交額流動性門檻過濾，以及歷史不足 21 天的 fallback 與 quality/warnings 降級判讀。
- 2026-07-05：補充 V1.7 Screening Matrix & Negative Evidence，說明推薦保存結果會保存 pass / fail / degraded / skipped / missing matrix、Why Not / Liquidity payload 與 source coverage warning；舊結果不回補、不重算。
- 2026-06-15：補充 Portfolio Alert v1 已由 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService` 共同接線，說明如何整合條件與籌碼風險警示，以及籌碼缺資料、估算、unavailable 的 quality / warnings 判讀。
- 2026-06-15：補充 Watchlist Trigger v1 已由 `WatchlistService` 與 SQLite `technical_indicators` 接線，說明強度 `score_bp`、風險 `risk_alert`、觸發統計與非交易日 fallback warning。
- 2026-06-15：補充 Daily Decision Desk v1 已接上主 UI 頂層「每日決策」頁籤，並更新質量欄位（OBSERVED / ESTIMATED / DEGRADED / MISSING）與 warnings 的解讀方式。
- 2026-06-15：補充 Market Breadth v1 已由 SQLite `daily_prices` 接線，說明多方 / 空方 / 持平、廣度比率、新高新低 metadata、成交量擴散與非交易日 fallback warning。
- 2026-06-15：補充 Sector Rotation v1 已由 SQLite `industry_indices` 接線，說明領先 / 落後產業、5 / 20 日變化、輪動強度、產業排名 metadata 與非交易日 fallback warning。
- 2026-07-26：新增 Fubon Shadow Feature Mapping 契約與可計算性 (computability contract)；對 post-DEV-61 Fubon shadow lane 做完整唯讀稽核，建立 FubonShadowFeatureMapping 契約與 ComponentComputabilityResult。目前既有 Score、Recommendation、Portfolio 與 Exit consumer 尚未讀取 Fubon shadow 欄位，因此即使觀測資料通過 PIT 驗證，也會回傳 typed not_computable 與 machine-readable blockers，避免將不變的 baseline 誤稱為候選結果。此診斷為 symbol-isolated、PIT-safe、research-only；formal_rule_only_path_unchanged=true，formal_decision_influence_allowed=false，formal_evidence_credit_authorized=false，production_blend_alpha_bp=0，不影響正式 Rule-only 決策與證據信用。
- 2026-07-13：Workbench > Evidence placeholder 替換為唯讀 Research Console；新增 Safety Boundary、Development Pipeline、EV1–EV5／P0-13／Broker lane／Artifact Inspector，僅讀顯式 sanitized projection 或 injected DTO。`formal_oos_allowed=false`、`production_blend_alpha_bp=0`、Rule-only 正式路徑與所有 apply / promotion / trading 禁令維持不變。
- 2026-07-27：新增 MOPS 公告快易查 F26–F29 季報秒級 publication-time research adapter 與 TEMP-only CLI；說明 M31 語意排除、31 日／1000-row fail-closed、次日 `available_date` look-ahead 邊界，以及 limited research acceptance 不等於正式 ingestion 或 Formal credit。
### Direct v4 自動等待合規 PIT sidecar

`scripts\\maintain_ml_direct_v3_refresh_chain.py --watch-formal-inputs` 會在 chain 完成後持續
驗證 `ml_pit_year_shards/latest_manifest.json` 指向的 `all_field_enriched` raw PIT dataset：
pointer、publication／dataset canonical hash、formal safety、`decision_at` 與目前 Direct
identity 必須一致；較新的 publication 或同一 cutoff 但內容 hash 改變時，會自動以新的
`training_as_of` 建立 immutable Direct → OOC chain。它也會驗證最新 official market-event
publication，並在 refresh 時保留已綁定且仍符合 cutoff 的 sector sidecar。官方 wrapper 只有
metadata 變更、canonical events hash 未變時，不會造成重複重訓。causal non-cash ledger 與
Rule Champion controlled artifact 沒有正式受控來源時不會被自動創造或替代，formal gate、
alpha=0、broker disabled 維持不變。

Direct v4 完成後，若新的 PIT sector sidecar 被放入 direct output lineage，
`continue_ml_direct_ooc_after_store.py` 會以正式 assembler 驗證 canonical manifest、
`status=accepted`、source／license／source hash、可得時間與 training cutoff；全部通過
才會建立新的 immutable Direct run，否則沿用現有 publication 並維持 formal gate 關閉。
可用 `BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH` 指向受控來源；未設定時只掃描明確的
`pit_sector_membership`／`sector_membership`／`sidecars` 目錄與固定檔名，不會把
`companies.csv` 或研究輸出當成 PIT 歷史資料。搭配
`scripts\maintain_ml_direct_v3_refresh_chain.py --watch-formal-inputs` 時，維護程序
會在 chain 完成後持續等待合規來源出現並自動續跑；沒有來源時不會重複訓練，且不會
改寫舊 run、寫正式 SQLite 或放寬 formal gate。

同一個 watcher 也會讀取受控環境變數 `BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH` 與
`BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH`。它不會從 research／output 目錄猜測
ledger 或 history；若三項正式輸入尚未同時通過驗證，formal-only refresh 會繼續等待，
避免只因 owner 分批放入來源而重跑部分 Direct/OOC chain。已綁定的 immutable path
則會由 Direct identity 以 file hash carry-forward，來源遺失或 tamper 時 fail closed。
長駐 watcher 也會在 polling 時重新讀取 Windows 使用者／系統環境登錄值，讓啟動後的
owner deposit 能被同一個 process 接收；只更新 process memory，HMAC value 不會進入檔案、
命令列、status 或 log。若 watcher 採用的登錄值被移除，process 內的 adopted value 會
清掉，formal 驗證仍會 blocked。

單獨執行 `scripts\inspect_ml_formal_input_readiness.py` 時也會使用相同的受控 Windows registry handoff；它只把 late owner deposit 接到當前唯讀 process memory，不會寫回 registry、artifact 或 source DB。

`run_ml_direct_chain_maintenance.cmd` 在啟動 Direct/OOC 前另做唯讀磁碟空間 preflight，
預設要求輸出所在檔案系統至少有 20 GiB 可用空間。低於門檻時會寫入
`status=blocked_insufficient_storage`、`storage_preflight.free_bytes` 與診斷，直接結束本次
wrapper，不啟動重建、不進入維護器 retry loop，也不刪除既有 run。這只是容量保護，不是
Formal／promotion 通過；若需調整門檻，使用受控命令列的
`--minimum-free-space-bytes`，並先確認年度 raw shard 估算、備份與 rollback 空間。

若 preflight 已回報 `blocked_insufficient_storage`，可先用下列唯讀工具整理容量與人工
retention 候選：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_ml_storage_retention.py `
  --root <DIRECT_RAW_ROOT> `
  --root <DIRECT_NUMERIC_ROOT> `
  --root <OOC_TRAINING_ROOT> `
  --minimum-free-space-bytes 21474836480 `
  --max-files 500000 `
  --format markdown `
  --output $env:TEMP\technical_analysis_program_readiness\ml_storage_retention_inventory.md
```

工具只讀取檔案 metadata 與小型 `manifest.json`，會列出大小、manifest status、掃描是否
截斷及可逆的外部 archive／人工 review 建議；不刪除、不搬移、不修改 lock／pointer，且
輸出明確固定 `automatic_delete_allowed=false`。若 `scan_truncated=true`，候選清單只能作
初步盤點，需提高 `--max-files` 重跑後再交 owner 決定；不要因清單出現 `status=complete`
就直接刪除 immutable run。
