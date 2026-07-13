# 兩日 Evidence Foundation 全力施行設計

## 目的

用既有 historical replay、working-copy Evidence、P0 shadow adapters、Paper Portfolio、Position Health 與 ML shadow 工程底座，建立一套可重跑、可比較、可故障注入的研究驗證基線。它要讓目前未完整計算的資料、未接入的新來源與 ML challenger 提早被看見，但不得把 replay、fixture 或殘缺資料升格成 forward、paper、live 或 formal product evidence。

## 採用方案

採用「分層證據演練」，不建立大型統一 replay engine，也不建立第二套 artifact registry：

1. `engineering_fixture`：驗證 schema、missing/degraded、lineage、idempotency、安全拒絕。
2. `historical_replay_candidate`：只使用 decision-time 可得資料，驗證 PIT、特徵、label maturity、benchmark 與成本假設。
3. `shadow_comparison`：新來源／ML challenger 與 rule baseline 並行，永不改正式 Advice。
4. `forward_handoff_pending`：產出未來真實 evidence 可直接接手的 manifest、command 與 completion rule。

## 架構

新增一個小型 application-level rehearsal service，組合既有服務的唯讀輸出，不複製其計算：

```text
Scenario Manifest
→ Data Coverage / Quality Projection
→ Historical Replay Summary
→ P0 Source Shadow Coverage
→ Paper / Health Proposal Projection
→ ML Dataset / Prediction / Drift Shadow
→ Canonical Artifact Lineage
→ Engineering Validation Report
→ Forward Handoff Package
```

核心輸出為 JSON/Markdown report；任何 SQLite 寫入只允許 temp path 或明確 working-copy。正式來源僅能 read-only，production evidence scheduler、broker、auto action、source acceptance、pruning 與 ML promotion一律禁止。

## 缺失資料政策

- 不以 0、均值或未揭露 forward-fill 靜默補值。
- 每個欄位保存 observed / estimated / degraded / missing、coverage bp、exclusion reason 與 source version。
- 缺 `available_date` 或 `available_date > decision_date` 的資料不得進 decision-time feature。
- 報表同時呈現 all-row、complete-case、coverage cohort；不得只顯示可用樣本而隱藏母體缺口。
- ML dataset manifest 保存 missingness policy、feature coverage、label maturity 與 excluded row counts。

## 驗收

- 同一 scenario 重跑得到相同 artifact ids、hashes 與 counts。
- source outage、missing day、future available date、immature label、缺 benchmark皆有明確 fail-closed/degraded結果。
- rule baseline、source shadow、ML shadow可在同一 comparison report查看，但正式 Advice不變。
- lineage DAG 可由 `verify_artifact_lineage.py` 重跑。
- forward handoff 明確列出哪些只能等待真實時間、license或人工決議。
- 全量 pytest、mypy、encoding、relative links、quant guard、ML boundary與Gate 2–7 verifier通過。

## 非目標

- 不宣稱 replay 投資有效性、正式 V4.0 或 production ML ready。
- 不回補或改寫舊 Recommendation/Evidence artifact。
- 不寫 production DB、不啟用 scheduler、不串 broker。
- 不自動接受資料源、prune signal、套用 health/lifecycle transition或 promote model。

