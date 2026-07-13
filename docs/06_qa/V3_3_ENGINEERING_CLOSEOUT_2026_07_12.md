# V3.3 Engineering Closeout（2026-07-12）

> **狀態**：`V3.3 Engineering Complete`，並進入 `V4.0 Evidence Accumulation Track`。這是工程收口，不是正式 V4.0、投資有效性、production ML、production scheduler 或 broker execution 核准。

## Capability 對照矩陣

| Capability | 實際狀態與入口 | Tests / artifact | Remaining engineering | External-only gate |
|---|---|---|---|---|
| Workbench / UI | CURRENT_ENGINEERING；`workbench_view.py`、read-only composer | Workbench / Advice suites；既有 snapshots | approval command UI deferred | 人工 review / override evidence |
| Application Orchestration | CURRENT / distributed；`app_module` services、composers | service suites、domain repositories | 不建立 mega-façade | 正式 approval ownership |
| Advice Policy | CURRENT；`advice_policy.py`、`advice_composer.py` | 94 focused tests；V2.1 closeout | lineage projection已補齊 | 投資有效性 |
| Market Intelligence | CURRENT / REPOSITION；breadth、regime、decision frame | decision desk snapshots | package reposition deferred | regime effectiveness |
| Recommendation / Screening | CURRENT；ranking、Why / Why Not | saved Recommendation artifacts | 舊 payload 不回補 | forward effectiveness |
| Research / Backtest / Evidence | CURRENT；Registry、Backtest、Evidence | runs、events/outcomes | production write scheduler禁止 | weekly/forward/live maturity |
| Portfolio Construction | CURRENT_ENGINEERING / paper | append-only paper snapshots | 不串 broker | 交易日與成本後 evidence |
| Position Health / Exit | CURRENT_ENGINEERING / proposal-only | thesis/state machine/transitions/exit read model | auto action非目標 | 人工 thesis/transition/outcome |
| Data Source Governance | CURRENT_ENGINEERING / candidate | P0 contracts/adapters/verifier | 不接正式 decision layer | license、quality、PIT 接受 |
| Execution Realism | CURRENT / research | simulator、slippage、virtual trace | broker command非目標 | 真實 fill / cost gap |
| ML Shadow | CURRENT_ENGINEERING / shadow | 9 slices、registries、boundary guard | production dependency禁止 | shadow days / promotion review |
| AI Research Copilot | CURRENT / read-only | evidence access MCP / tests | 寫入與決策權非目標 | 人工研究採納 |
| Runtime / Scheduling | CURRENT / guarded | runtime events、dry-run status | production write scheduler禁止 | owner approval |
| Storage / Artifact Registry | CURRENT_ENGINEERING / federated | domain repositories + canonical verifier | 不建重複 registry | last-approved refs |
| External Source Adapters | CURRENT_ENGINEERING / shadow | P0 adapter tests/diagnostics | accepted ingestion不得預作 | source-by-source acceptance |

## Artifact identity / lineage / integrity

`app_module/artifact_lineage_verifier.py` 是唯讀 canonical projection，不保存第二套 registry。既有 repository 可輸出 artifact/run/date/source/quality/strategy/policy/model/parent/evidence/status/hash/rollback 欄位後重跑：

```powershell
.\.venv\Scripts\python.exe scripts\verify_artifact_lineage.py --manifest <lineage-manifest.json> --output <temp-report.json>
```

Verifier fail-closed 檢查 future available/as-of date、缺 parent、duplicate id、cycle、hash shape 與 rollback reference；固定 `formal_product_closeout=false`、`production_actions_allowed=false`。Fixture chain 只證明工程契約，不能冒充 forward/paper/live evidence。

## Operations handoff

Control Center 與 append-only `EngineeringGateRegistry` 維持唯一外部 Gate 真相來源。

| Cadence | Command / input | Output / owner | Safety / failure | Rollback / completion | Prohibited |
|---|---|---|---|---|---|
| Daily data | Update Workbench quick mode；freshness CLI；configured source | update/freshness report；Data operator | 不重建資料；degraded/missing fail-closed | 停止 downstream；日期與 quality 明確 | 自行接受 source |
| Daily Advice/paper/health | Workbench、paper/health CLIs；saved Recommendation | Advice、paper snapshot、health proposal；Research operator | 不下單；失敗輸出 NO_NEW_POSITION/WATCH | last approved policy/snapshot；artifact 可追溯 | broker/auto rebalance/exit |
| Daily Evidence/ML | evidence dry-run、ML inspection；governed artifact | dry-run/shadow artifact；Evidence/ML reviewer | production write disabled；blocking gap停止 | rule champion；無 blocking gap | confirm production/auto promotion |
| Weekly | weekly review CLI；approved working-copy/date/owner | append-only history；Evidence reviewer | production-like DB拒絕 | backup/recovery；list-history核對 | fixture補週/覆寫 history |
| Monthly | effectiveness/paper/ML CLIs；matured evidence | pruning/policy/revalidation proposal；Named reviewer | insufficient sample即 defer | champion/policy ref；具名決議或 waiting | auto pruning/promotion |
| Maturity | outcome/exit/source/promotion verifier | gate revision；Gate owner | 只 append；未滿維持 open | last revision；10,000 bp + evidence | 模擬成熟 |
| Failure | source/schema/drift/scheduler diagnostics | incident + gate revision；Owning operator | fail-closed並保留 artifact | last approved ref；recovery驗證 | 刪歷史/靜默降級/auto action |

## 只能等待的項目

- 真實 weekly / forward / paper / exit evidence 與 outcome maturity。
- P0 source license、quality、PIT、missing/outage 與逐來源人工接受。
- thesis、position transition、signal pruning 與 lifecycle 人工決議。
- ML shadow days、重驗、drift review 與 promotion review。
- production evidence scheduler 明確 owner approval；目前維持 disabled。

上述項目持續登記於 [External Validation Register](GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md)，不得用 fixture、replay 或工程測試改寫狀態。
## P1 lineage parent contract correction (2026-07-13)

Canonical lineage verifier 現已固定跨領域鏈：`daily_governed_data` → `market_context` → `recommendation` → `bounded_advice` → `paper_portfolio` → `position_health` → `evidence_event` → `forward_outcome` → `weekly_review` → `signal_effectiveness` → `ml_shadow_prediction`。後繼 artifact 必須包含直接前序領域 parent；額外更早上游 parent 可保留 provenance。相同或後序領域 parent，以及缺直接前序 parent 均 fail-closed。

即使 artifact type 正確且無 cycle，parent domain/order 錯置仍使 rehearsal 報告降為 `degraded`，且不得投影 artifact DAG 或 hashes。本修正不改變 formal product closeout、production action、external Gate 或 evidence maturity。
