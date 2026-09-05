# Gate 2–7 External Validation Register

> **Current-state notice（2026-08-30）**：本文件下方的 V4.0 revision／table 是 2026-07-30 的 append-only 歷史投影，保留供追溯，**不是目前 readiness 的 SSOT**。目前狀態請以 [Program Status Rebaseline 2026-08-29](PROGRAM_STATUS_REBASELINE_2026_08_29.md)、[Project Snapshot](../00_core/PROJECT_SNAPSHOT.md) 頂部、對應唯讀 inspectors 與具時間戳 source artifacts 重新判讀；不得從本頁歷史的 `complete`／`4/3`／`13/13` 敘述推定今日 Gate 已解除。Current P0 為 13/13 machine evidence，其中 `1 verified / 9 degraded / 3 official_no_data`，accepted／limited 仍 0；Evidence formal credit 未授予、歷史 working-copy 1/3、UI projection 3/3、sidecar pending 10、multi-day 3/3；Paper 21/21 但 fills／cost 0；Formal inputs 0/3。既有歷史列不回填或改寫。最新 P0 與 Evidence handoff 分別見 [P0 Evidence Refresh 2026-08-30](P0_EVIDENCE_REFRESH_2026_08_30.md) 與 [Evidence Weekly Approval Refresh 2026-08-30](EVIDENCE_WEEKLY_APPROVAL_REFRESH_2026_08_30.md)。

## V4.0 歷史 revision 投影（2026-07-30；非目前狀態）

> 本節與下方 revision／table 是 append-only 歷史資料，只供追溯。`Rule/Advice/Paper operational production` 等文字描述的是當時 revision 的宣告，不代表目前環境已啟用；目前狀態以本頁上方 Current-state notice、Program Status Rebaseline 與實際 inspectors 為準。

## 2026-07-30 V4.0 revision 投影（historical）

| Item | 最新狀態 | 機器／政策決議 |
|---|---|---|
| `evidence:weekly-history-3` | `complete` | scheduler sidecar 已累積 4 個不同真實週期（門檻 3），revision 3 由機器證據完成 |
| `evidence:forward-maturity` | `insufficient_evidence` | 只把 available/matured outcomes 放入分母 |
| `p0:source-acceptance-13` | `complete` | 13/13 已逐源處置：0 accepted、12 research shadow、1 blocked provenance |
| `paper:policy-approval` | `complete` | 平衡型 int-bp／Decimal policy 正式採用 |
| `paper:elapsed-observation` | `insufficient_evidence` | 05:28 task 已啟動，真實週期由 append-only ledger 累積 |
| `v3:manual-pruning-review` | `complete` | Rule champion 保留；低證據 challenger 全部限制於 shadow |
| `health:thesis-input` | `complete` | 缺 thesis → WATCH；invalidation → EXIT；ML 不得創建 thesis |
| `health:transition-review` | `complete` | 合法／非法 transition 由 deterministic state-machine tests 判定 |
| `exit:outcome-maturity` | `insufficient_evidence` | 只由成熟 horizon 自動更新 |
| `ml:shadow-days` | `insufficient_evidence` | 四 lane 已啟動；歷史 replay 不算 20 個真實 elapsed trading days |
| `ml:promotion-policy` | `complete` | `allocation-promotion-v4`；最小通過 alpha，任一失效原子回退 0 |
| `ml:revalidation` | `in_progress`（revision 6，8,500 bp） | 全市場 raw PIT custody、official-event bounded 4-fold model、八個 feature packs、逐 horizon outcome 契約與自動 promotion／authority 管線已完成；revision 6 封存時 direct store 已完成 2014–2018、2019 組裝中，live checkpoint 隨後至少完成至 2019。Engineering replay 可重算帳務但 Formal semantic verifier 仍 fail closed；Shadow observation 不具 promotion day credit，formal OOC／calibration／drift 由 scheduler 自動續驗 |
| `release:rule-operational` | `complete` | Decision／Advice／Paper／配置已 operational；broker=false |
| `release:formal-gates` | `insufficient_evidence` | 僅指 ML 非零權重；不影響 Rule operational production |

正式 sidecar registry：`OUTPUT_ROOT/release_v4/engineering_gate_registry.sqlite`。2026-07-30 首批與 live P0 重驗共 append 28 個 revisions；weekly sidecar 自動計數達 4/3 後 append `evidence:weekly-history-3` revision 3；`ml:revalidation` 依序追加 revision 3（actual training 與 post-freeze fail-closed）、revision 4（全市場 raw custody 與每日 Co-pilot）、revision 5（全市場 direct OOC checkpoint、逐 horizon metrics 與獨立 promotion authority）及 revision 6（正式 replay semantic gate、Shadow day-credit gate 與完整 release QA）。目前共 33 列；除 weekly history 與 ML revalidation 外，其餘項目最新仍為 revision 2，禁止改寫既有 row。

## 自動 Gate 決策規則

- Gate 2：weekly、forward maturity 與 elapsed evidence 由排程計數；未達門檻寫 `insufficient_evidence`。
- Gate 3：每一個 P0 source 都必須是 accepted／research_shadow／rejected／blocked 的明確決議；沒有 blanket acceptance。
- Gate 4：policy 已決議；每日 Paper task 只做 T-1 append-only 估值，不自動 rebalance。
- Gate 5：Rule champion 固定保留，challenger 必須有可重播 evidence 才能解除 shadow。
- Gate 6：Health/Exit 由狀態機與硬風控決定；ML 不能取消 EXIT。
- Gate 7：policy 已接受，權重影響仍只由 promotion artifact 決定；禁止手動設定 `formal_oos_allowed` 或非零 alpha。

機器 promotion 必須同時證明 PIT/future/constraint violations=0、replay hash 一致、至少四 folds 且三 folds 勝 Rule、bootstrap 95% lower bound >=0、ECE <=500 bp、calibrated Brier 不劣化、PSI <2500 bp、core/enriched/fill coverage 達門檻、MDD/CVaR 惡化 <=100 bp、turnover 達門檻及 20 個真實 shadow trading days。候選 alpha 固定 `2000 → 3500 → 5000` 選最小通過者。

> **Agent 接手導覽**：工程完成證據見 [Pure Engineering Closeout](GATE_2_TO_7_PURE_ENGINEERING_CLOSEOUT_2026_07_12.md)；registry 操作與狀態投影見 [Engineering Control Center](GATE_2_TO_7_ENGINEERING_CONTROL_CENTER.md)；所有 ML 更新、重訓與 promotion review 必須遵循 [Gate 7 ML Shadow Engineering](GATE_7_ML_SHADOW_ENGINEERING.md)。本表管理自動時間證據、外部來源條件與政策決議；不再建立等待人工批准的 blanket Gate。

> 每個 cadence 的 command/input/output/owner/safety/failure/rollback/completion/prohibited 契約見 [V3.3 Engineering Closeout](V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)；本表只保存 append-only external state，不複製操作規則。

> 這是未來人工補件、真實時間驗證、資料授權與 ML 更新驗證的操作入口。工程已完成不會自動把下列項目標成 complete。

> External Evidence 下一階段只使用 companion 文件導覽，不由本頁提前建立 revision：先讀 [External Evidence Design](../superpowers/specs/2026-07-13-external-evidence-investment-validation-design.md) 與 [Master Plan](../superpowers/plans/2026-07-13-external-evidence-investment-validation-master-plan.md)；第一個執行切片固定為 [OOS Exposure／Custody Audit Plan](../superpowers/plans/2026-07-13-oos-exposure-custody-audit-execution-plan.md)，Terra 接手邊界見 [Execution Handoff and Prompt Pack](../superpowers/prompts/2026-07-13-terra-external-evidence-execution-handoff.md)。這些文件不改變下表狀態。

## 狀態更新方式

1. 複製對應 item 成 JSON，revision 加一。
2. 更新 owner、earliest validation date、progress bp、artifacts、commands、completion evidence 與 notes。
3. 透過 `scripts/manage_engineering_gate_registry.py ... append` 新增 revision。
4. 用 `list-latest` / `history` 檢查；禁止直接修改 SQLite 舊列。

## 初始待辦矩陣（歷史；不可當最新狀態）

| Item ID | Category | Owner | Earliest validation | 初始狀態 | Completion rule | 禁止動作 |
|---|---|---|---|---|---|---|
| `evidence:weekly-history-3` | waiting_for_time | evidence owner | 第 3 個真實週期結束後 | waiting | 3 個獨立真實週期及 review evidence | 用 replay/fixture 補時間 |
| `evidence:forward-maturity` | evidence_maturity | evidence owner | 各 horizon expected maturity date | waiting | ready outcomes 達樣本門檻且無 future data | 把 pending 放入績效分母 |
| `v3:manual-pruning-review` | human_approval | strategy owner | V3 metrics 成熟後 | open | retain/restrict/downweight/retire/defer 逐項簽核 | 自動套用 pruning |
| `p0:source-acceptance-13` | data_license | data/release owners | license/quality evidence 齊備後 | open | 13 sources 各自 accepted/limited/rejected/deferred | 批次推定 accepted |
| `paper:elapsed-observation` | waiting_for_time | portfolio owner | 至少一個完整真實 paper 週期 | waiting | daily snapshots、cost、benchmark、missing-day review | 用回測冒充 forward paper |
| `paper:policy-approval` | human_approval | portfolio/risk owners | paper evidence 可審查後 | open | 現金、單檔、產業、turnover、cost assumptions 簽核 | 自動 rebalance / broker order |
| `health:thesis-input` | human_input | position owner | 每次 paper position 建立時 | open | 每檔 thesis、invalidation、horizon、review date 完整 | 由模型自動編造 thesis |
| `health:transition-review` | human_approval | position owner | transition proposal 出現後 | open | human-approved event 含 reviewer/reason | proposal 直接改 recorded state |
| `exit:outcome-maturity` | evidence_maturity | evidence owner | exit horizon maturity date | waiting | ready exit outcomes 可比較 avoided loss/regret | pending outcome 當有效 |
| `ml:shadow-days` | waiting_for_time | ML reviewer | 至少 20 個 shadow observed days | waiting | registry 有 causal predictions 與完整 matured labels | 回填或合成 elapsed days |
| `ml:revalidation` | ml_revalidation | ML reviewer | 新成熟 evidence/schema change/drift/scheduled review | open | 十步 runbook artifacts 全部通過 | auto retrain/promotion |
| `release:formal-gates` | human_approval | release owner | 上述依賴完成後 | open | 逐 Gate formal decision 與 rollback plan | 以工程 closeout 代替正式核准 |

## ML 設定何時更新

出現下列任一 trigger 時建立新的 `ml_revalidation` revision，不修改既有 model record：

- 新一批 forward / exit outcomes 已成熟。
- Feature schema、source version、label horizon 或 availability policy 改變。
- PSI 達 moderate/major drift，或 champion comparison 明顯退化。
- 排定的月／季 shadow review 到期。

執行：

```powershell
.\.venv\Scripts\python.exe scripts\build_ml_revalidation_runbook.py --run-id <id> --trigger <trigger> --dataset-id <new-frozen-id> --current-model-id <id> --training-as-of <YYYY-MM-DD> --owner <owner> --output <runbook.json>
```

必須重新凍結 dataset manifest、檢查 available dates、purged walk-forward、訓練 challenger、OOF calibration、寫 shadow predictions、drift、same-sample champion comparison、promotion evidence package 與 shadow dependency guard。只有機器可驗證 evidence 全數通過後，獨立 promotion authority 才可簽發相容 artifact 並選擇最小通過 alpha；任何條件失效皆原子回退 `alpha=0`，不等待人工 review，也不得手動 promotion。

## Formal Week 1 evidence report revision（2026-07-14 至 2026-07-19）

- revision: `formal-week-1-20260719-r1`；在自然週結束後補登，不改寫任何既有 state。
- formal credit snapshot count=`0`；outcome revision count=`0`；matured outcome denominator=`0`。
- manual why-not：週期內沒有已綁定的未消費 formal trading session，也沒有合格 decision-time `manual_observed` artifact；因此不得以 development invocation、replay、fixture 或事後資料補成 observed day。
- source acceptance：13 個 P0 source 仍待逐來源 owner/reviewer 的 license、quality、PIT、coverage、missing/outage 與 rollback review；沒有 source 被自動 accepted。
- fubon.marketdata：已為 Fubon market-data 建立 research-only candidate dossier 審查投影，當前 hash: `sha256:8275ef80b6a409d3da4f9372569246abe0d28cabc60d322634c5d9a639715a60` (projection: `C:\Temp\external-evidence-shadow\fubon_dossier_projection.json`)，已完成第三輪硬化使 review package 檢核清單與阻擋器完全一致（可用 `scripts/inspect_fubon_dossier.py` 進行唯讀、review-only 盤點），其狀態為 owner review pending / deferred candidate，eligibility 保持 none，formal credit 保持 0，不供 downstream 使用。
- safety：`formal_oos_allowed=false`；`production_blend_alpha_bp=0`；Rule-only；未啟用交易、scheduler、training、promotion 或 unblind。
- note：2026-07-21 的 TEMP/shadow snapshot 發生在本週期之後，不回填 Week 1，也不構成 Week 1 credit。

## Formal Week 2 evidence report revision（2026-07-20 至 2026-07-26）

- revision: `formal-week-2-20260726-r1`；在自然週結束後於 2026-07-27 append，不覆寫 Week 1 或任何既有 state。
- formal credit snapshot count=`0`；既有 shadow `manual_observed` count=`1`；outcome revision count=`0`；matured outcome denominator increment=`0`；formal credit increment=`0`。
- manual why-not：週內 2026-07-21 的 `snapshot:2330:20260721:6bec1c3d03ebae5e` 是 decision-time TEMP/shadow `DEFER` artifact，結構驗證有效，但其 `fubon.marketdata` owner decision revision `decision:fubon.marketdata:20260721-r1` 仍為 `deferred`、allowed use cases 空、downstream eligibility=`none`、formal credit 未授權；因此不得納入 formal snapshot count、observed day、matured denominator 或任何產品／投資有效性結論。
- holdout registry：`HoldoutConsumptionRegistry.jsonl` v2 owner-attested binding 重新檢查為有效，formal trading session=`2026-07-21`；本 revision 沒有建立新 binding、沒有把 shadow capture 宣稱為 formal consumption，也沒有消耗另一個交易時段。
- source acceptance：13 個 P0 source 仍全數為 `requires_human_acceptance`、downstream eligibility=`none`。本週完成的 P0 machine audit/readiness hardening 只改善 candidate evidence diagnostics；12 項 official probes 未在本次重跑，`pit.quarterly_financials` 仍缺具公告／可得時間、revision、source hash 與 correction status 的真實 MOPS artifact，不構成 owner/reviewer acceptance。
- approved weekly history：外部 `approved-weekly-history-projection.v1` SHA-256 仍為 `5D86BE7C469AB83B4C769DB4A76A7BE052FE4F38A667A93E5BBB301782C07ED4` 且固定 `formal_credit_authorized=false`；其 owner-approved UI disclosure records 不轉換為 Formal Week 2 observed snapshot 或 credit。
- degraded：`first_observed_only`、`official publication timestamp missing`、`no documented full-delivery indicator`；missing=`new decision-time manual_observed artifact`、`accepted Fubon source decision`；capture failure=`none in this revision`。
- safety：`formal_oos_allowed=false`；`formal_evidence_credit_authorized=false`；`production_blend_alpha_bp=0`；Rule-only formal path；未寫 Candidate／formal／market DB，未執行 scheduler、broker/trading、Recommendation／Portfolio／Exit／Score／lifecycle mutation、training、retraining、promotion、unblind 或 blend。

## Formal Week 3 evidence report revision（2026-07-27 至 2026-08-02）

- revision: `formal-week-3-20260802-r1`；自然週結束後於 2026-08-03 append，不覆寫 Week 1、Week 2 或任何既有 state。
- formal credit snapshot count=`0`；既有 shadow `manual_observed` count=`1`；outcome revision count=`0`；matured outcome denominator increment=`0`；formal credit increment=`0`；elapsed formal-day increment=`0`。
- manual why-not：2026-07-28 owner 決議與 `HoldoutConsumptionRegistry.jsonl` v3 已將 Rule-only lane `formal-rule-only-20260729-r1` 綁定至決議後第一個未消費交易時段 2026-07-29，且本次重新檢查 binding 仍有效；但週內及補登時均沒有該時段真正 decision-time 的 `manual_observed` decision output，因此不得用 development invocation、TEMP candidate、scheduler sidecar、replay、fixture 或事後審核合成 observed day、denominator 或 Formal credit。
- holdout registry：本 revision 未建立或重綁 holdout、未宣稱 consumption，也未消耗另一個交易時段。正式 preflight 維持唯一 blocker=`manual_observed_snapshot_missing`、`formal_readiness=false`；allowed Formal sources 仍只限 `daily_prices`、`industry_indices`、`market_indices`、`technical_indicators`。
- development clock：週內新增 2330、2317、2454、2308 四個 2025 Q1 MOPS numeric PIT TEMP-only candidates；截至週末合計 4 symbols、470 matching decision rows、174 PIT-eligible rows，占 canonical 179,271 rows 的 9 bp。這些 artifact 只改善 research-only raw-numeric／availability／canonical lineage，未取得具名 numeric source owner/reviewer acceptance，亦未 materialize feature、fit 2026、training、promotion 或進入 Formal path。
- approved weekly history：外部 `approved-weekly-history-projection.v1` SHA-256=`02EB67FF812C17F604C34F4EB30C1B87941596AF6AA9EBAFF6EC1D555B64B4D8`，仍只有三筆截至 2026-07-26 的 owner-approved disclosure records，且固定 `formal_credit_authorized=false`；registry item `evidence:weekly-history-3` 的 4/3 scheduler-sidecar complete 是獨立機器週期計數，不轉換為本週 Formal snapshot、elapsed day 或 credit。
- degraded=`none for the bound Rule-only lane`；missing=`genuine 2026-07-29 decision-time Rule-only manual_observed artifact`；capture failure=`no qualifying observed artifact supplied or found`。既有 shadow snapshot `snapshot:2330:20260721:6bec1c3d03ebae5e` 發生於 Week 2，維持 shadow-only，不回填 Week 3。
- safety：`formal_oos_allowed=false`；`formal_evidence_credit_authorized=false`；`production_blend_alpha_bp=0`；Rule-only formal path；未寫 Candidate／formal／market DB，未執行 scheduler、broker/trading、Recommendation／Portfolio／Exit／Score／lifecycle mutation、training、retraining、promotion、unblind 或 blend。

## Formal Week 4 evidence report revision（2026-08-03 至 2026-08-09）

- revision: `formal-week-4-20260809-r1`；自然週結束後於 2026-08-14 append，不覆寫 Week 1–3 或任何既有 state。
- formal credit snapshot count=`0`；既有 shadow `manual_observed` count=`1`；outcome revision count=`0`；matured outcome denominator increment=`0`；formal credit increment=`0`；elapsed formal-day increment=`0`。
- manual why-not：週內 owner 先後將 Rule-only lane `formal-rule-only-20260805-r1` 與 `formal-rule-only-20260807-r1` 綁定至決議後當時未使用的交易時段；本次重新檢查 `HoldoutConsumptionRegistry.jsonl` 共 4 筆記錄，全部仍未消耗。週內及補登時都沒有這兩個 session 的真正 decision-time `manual_observed` decision output，因此 binding 不轉換成 snapshot、observed day、denominator、consumption 或 Formal credit。
- readiness：最新可引用 lane=`formal-rule-only-20260807-r1`，owner decision 與 registry binding 均有效，formal session=`2026-08-07`；但 snapshot=`missing`、`can_capture_shadow_snapshot=false`、`formal_readiness=false`，唯一 formal blocker=`manual_observed_snapshot_missing`。本 revision 未建立、重綁或消耗 holdout，也未取得另一個交易時段。
- development clock：週內 `DEV-115` 只在 TEMP research evidence 新增 2412／6505 的 2025-Q1 MOPS numeric PIT candidates，ML-universe candidate coverage 為 9/11、aggregate coverage=`118/8000 bp`；`DEV-119` 只補上 foreground-only Rule-only source producer。這些工程輸入都沒有 materialize feature、fit 2026、training、promotion、Formal capture 或寫入正式 decision path。
- approved weekly history：registry item `evidence:weekly-history-3` 的 machine sidecar 週期計數已是 complete，但它與 Formal Week 4 的 decision-time snapshot clock 互相獨立；不得將 scheduler-sidecar history、development invocation、replay 或 fixture 換算成本週 observed day 或 credit。
- degraded=`none for the latest bound Rule-only lane`；missing=`genuine 2026-08-07 decision-time Rule-only manual_observed artifact`；capture failure=`no qualifying decision-time artifact supplied or found`。歷史 `manual_observed_20260729.json` 維持無法用於本 lane，不回填 Week 4。
- safety：`formal_oos_allowed=false`；`formal_evidence_credit_authorized=false`；`production_blend_alpha_bp=0`；Rule-only formal path；未寫 Candidate／formal／market DB或 artifact pointer，未執行 scheduler、broker/trading、Recommendation／Portfolio／Exit／Score／lifecycle mutation、training、retraining、promotion、unblind、blend 或 Task 6。

## Formal Week 5 evidence report revision（2026-08-10 至 2026-08-16）

- revision: `formal-week-5-20260816-r1`；自然週結束後於 2026-08-17 append，不覆寫 Week 1～4 或任何既有 state。
- formal credit snapshot count=`0`；既有 shadow `manual_observed` count=`1`；outcome revision count=`0`；matured outcome denominator increment=`0`；formal credit increment=`0`；elapsed formal-day increment=`0`。
- manual why-not：最新可引用 Rule-only lane 仍為 `formal-rule-only-20260807-r1`；本次重新檢查 `HoldoutConsumptionRegistry.jsonl` 共 4 筆 records，全部未消耗。Week 5 期間與補登時都沒有該 session 的真正 decision-time `manual_observed` decision output，因此不得用 development invocation、prospective handoff、scheduler sidecar、replay、fixture、歷史 `manual_observed_20260729.json` 或事後審核合成 snapshot、observed day、denominator、consumption 或 Formal credit。
- readiness：2026-08-07 owner decision 與 registry binding 仍有效，formal session=`2026-08-07`；snapshot=`missing`、`can_capture_shadow_snapshot=false`、`formal_readiness=false`，唯一 formal blocker=`manual_observed_snapshot_missing`。本 revision 未建立、重綁或消耗 holdout，也未取得另一個交易時段。
- development clock：週內 owner 採用 prospective-only、非實盤的模擬持倉 clock，PFS-01～PFS-10 與 deferred execution handoff 已完成工程驗證；但三個 `BALDR_ML_*_PATH` 尚未由 owner 在受控環境提供，未選 activation trading day，亦未發布 clock、建立 ledger／Rule／PIT／calibration／capture artifact、啟動 watcher／Direct／OOC 或取得 Formal OOS／promotion credit。這些事實只屬 Development clock，不轉換成本週 Formal event。
- approved weekly history：registry item `evidence:weekly-history-3` 的 machine sidecar 週期計數已是 complete，但它與 Formal Week 5 的 decision-time snapshot clock 互相獨立；不得將 scheduler-sidecar history、PFS engineering completion、development invocation、replay 或 fixture 換算成本週 observed day 或 credit。
- degraded=`none for the latest bound Rule-only lane`；missing=`genuine 2026-08-07 decision-time Rule-only manual_observed artifact`；capture failure=`no qualifying decision-time artifact supplied or found`。唯一歷史 snapshot 仍是 `manual_observed_20260729.json`，不重用、不回填 Week 5。
- safety：`formal_oos_allowed=false`；`formal_evidence_credit_authorized=false`；`production_blend_alpha_bp=0`；Rule-only formal path；未寫 Candidate／formal／market DB 或 artifact pointer，未執行 scheduler、broker/trading、Recommendation／Portfolio／Exit／Score／lifecycle mutation、fit、training、retraining、promotion、unblind、blend 或 Task 6。

## Formal Week 6 evidence report revision（2026-08-17 至 2026-08-23）

- revision: `formal-week-6-20260823-r1`；自然週結束後於 2026-08-25 append，不覆寫 Week 1～5 或任何既有 state。
- formal credit snapshot count=`0`；既有 shadow `manual_observed` count=`1`；outcome revision count=`0`；matured outcome denominator increment=`0`；formal credit increment=`0`；elapsed formal-day increment=`0`。
- manual why-not：最新可引用 Rule-only lane 仍為 `formal-rule-only-20260807-r1`；本次重新檢查 `HoldoutConsumptionRegistry.jsonl` 共 4 筆 records，全部未消耗且 Formal credit 未授權。Week 6 期間與補登時都沒有該 session 的真正 decision-time `manual_observed` decision output，因此不得用 prospective restart direction、Rule Champion acceptance、development invocation、scheduler sidecar、replay、fixture、歷史 `manual_observed_20260729.json` 或事後審核合成 snapshot、observed day、denominator、consumption 或 Formal credit。
- readiness：2026-08-07 owner decision 與 registry binding 仍有效，formal session=`2026-08-07`；snapshot=`missing`、`can_capture_shadow_snapshot=false`、`formal_readiness=false`，唯一 formal blocker=`manual_observed_snapshot_missing`。本 revision 未建立、重綁或消耗 holdout，也未取得另一個交易時段。
- development clock：Week 6 期間 owner 鎖定新的 prospective-only restart direction，並接受 `manual-rule-only-daily-rank-v1` + `foreground-owner-bound-v1` Champion identity；這些是 Development clock 的未來執行輸入，不是獨立 Rule-only Formal lane 的 decision-time snapshot。Week 6 內未建立可計入本 register 的 Formal Rule／Portfolio／PIT input、strict readiness、shadow maturity、Formal OOS 或 promotion artifact。
- approved weekly history：registry item `evidence:weekly-history-3` 的 machine sidecar 週期計數已是 complete，但它與 Formal Week 6 的 decision-time snapshot clock 互相獨立；不得將 scheduler-sidecar history、prospective plan、staging、development invocation、replay 或 fixture 換算成本週 observed day 或 credit。
- degraded=`none for the latest bound Rule-only lane`；missing=`genuine 2026-08-07 decision-time Rule-only manual_observed artifact`；capture failure=`no qualifying decision-time artifact supplied or found`。唯一歷史 snapshot 仍是 `manual_observed_20260729.json`，不重用、不回填 Week 6。
- safety：`formal_oos_allowed=false`；`formal_evidence_credit_authorized=false`；`production_blend_alpha_bp=0`；Rule-only formal path；未寫 Candidate／formal／market DB 或 artifact pointer，未執行 clock activation、capture producer、scheduler、watcher、broker/trading、Recommendation／Portfolio／Exit／Score／lifecycle mutation、fit、training、retraining、promotion、unblind、blend 或 Task 6。
