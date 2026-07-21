# Gate 2–7 External Validation Register

> **Agent 接手導覽**：工程完成證據見 [Pure Engineering Closeout](GATE_2_TO_7_PURE_ENGINEERING_CLOSEOUT_2026_07_12.md)；registry 操作與狀態投影見 [Engineering Control Center](GATE_2_TO_7_ENGINEERING_CONTROL_CENTER.md)；所有 ML 更新、重訓與 promotion review 必須遵循 [Gate 7 ML Shadow Engineering](GATE_7_ML_SHADOW_ENGINEERING.md)。本表只管理尚待人工、時間或外部條件成立的項目。

> 每個 cadence 的 command/input/output/owner/safety/failure/rollback/completion/prohibited 契約見 [V3.3 Engineering Closeout](V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)；本表只保存 append-only external state，不複製操作規則。

> 這是未來人工補件、真實時間驗證、資料授權與 ML 更新驗證的操作入口。工程已完成不會自動把下列項目標成 complete。

> External Evidence 下一階段只使用 companion 文件導覽，不由本頁提前建立 revision：先讀 [External Evidence Design](../superpowers/specs/2026-07-13-external-evidence-investment-validation-design.md) 與 [Master Plan](../superpowers/plans/2026-07-13-external-evidence-investment-validation-master-plan.md)；第一個執行切片固定為 [OOS Exposure／Custody Audit Plan](../superpowers/plans/2026-07-13-oos-exposure-custody-audit-execution-plan.md)，Terra 接手邊界見 [Execution Handoff and Prompt Pack](../superpowers/prompts/2026-07-13-terra-external-evidence-execution-handoff.md)。這些文件不改變下表狀態。

## 狀態更新方式

1. 複製對應 item 成 JSON，revision 加一。
2. 更新 owner、earliest validation date、progress bp、artifacts、commands、completion evidence 與 notes。
3. 透過 `scripts/manage_engineering_gate_registry.py ... append` 新增 revision。
4. 用 `list-latest` / `history` 檢查；禁止直接修改 SQLite 舊列。

## 初始待辦矩陣

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

必須重新凍結 dataset manifest、檢查 available dates、purged walk-forward、訓練 challenger、OOF calibration、寫 shadow predictions、drift、same-sample champion comparison、promotion review package 與 shadow dependency guard。完成後仍只可送人工 review，不會自動 promotion。

## Formal Week 1 evidence report revision（2026-07-14 至 2026-07-19）

- revision: `formal-week-1-20260719-r1`；在自然週結束後補登，不改寫任何既有 state。
- formal credit snapshot count=`0`；outcome revision count=`0`；matured outcome denominator=`0`。
- manual why-not：週期內沒有已綁定的未消費 formal trading session，也沒有合格 decision-time `manual_observed` artifact；因此不得以 development invocation、replay、fixture 或事後資料補成 observed day。
- source acceptance：13 個 P0 source 仍待逐來源 owner/reviewer 的 license、quality、PIT、coverage、missing/outage 與 rollback review；沒有 source 被自動 accepted。
- fubon.marketdata：已為 Fubon market-data 建立 research-only candidate dossier 審查投影，當前 hash: `sha256:8275ef80b6a409d3da4f9372569246abe0d28cabc60d322634c5d9a639715a60` (projection: `C:\Temp\external-evidence-shadow\fubon_dossier_projection.json`)，維持 deferred/disabled 且 eligibility=none，不供 downstream 使用。
- safety：`formal_oos_allowed=false`；`production_blend_alpha_bp=0`；Rule-only；未啟用交易、scheduler、training、promotion 或 unblind。
- note：2026-07-21 的 TEMP/shadow snapshot 發生在本週期之後，不回填 Week 1，也不構成 Week 1 credit。
