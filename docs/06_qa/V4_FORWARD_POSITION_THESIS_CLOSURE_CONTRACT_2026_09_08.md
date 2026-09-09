# V4 前瞻持倉 Thesis／Entry Lineage 閉環契約（2026-09-08）

## 目的與邊界

本契約只處理新的前瞻候選：在 research-only recommendation／Decision Desk 決策
完成時保存可驗證的結構化觀測與政策引用，之後只用 Paper producer 已追加的真實
filled buy 與 `PaperPositionIdentityProvider` 已證明的 flat-to-positive entry 綁定
`position_id`／`entry_lineage_id`。它不回填既有持倉、不改寫 Paper ledger、Formal
資料、D 槽原始資料或既有績效起點，也不產生 broker／lifecycle 動作。

機器輸出的候選不是人類 investment thesis，也不能代替人工 review。候選會保存
推薦原文、當時的 Rule／risk policy hash、資料可得時間與缺件狀態；只有明確存在的
政策才可形成 invalidation rule／holding horizon。缺少政策時仍保存可審核 packet，
狀態為 `awaiting_explicit_policy`，不把猜測值寫成健康 contract。

## Owner 與檔案分工

| Owner | 允許修改／責任 | 不可修改 |
|---|---|---|
| Scheduler／Operations | `app_module/forward_position_thesis_candidate_producer.py`、`scripts/run_forward_position_thesis.py`、`scripts/scheduled/run_scheduled_recommendation_snapshot.py`、對應 scheduled tests／docs；產生候選 packet、驗證來源 hash、接入隔離 output、把已證明 entry 綁回候選 | Paper／Formal writer、推薦／ML 計算核心 |
| ML／Recommendation owner | recommendation／ML source 的實際 Rule、model、feature、release identity；若要提供 horizon／invalidation policy，交付 versioned policy JSON 與 hash | 不由本片代寫或推測 thesis |
| Formal／Paper owner | `data_module/paper_daily_execution_producer.py` 與 Paper fill／state snapshot；提供 immutable filled event、source receipt、calendar／cost 語意 | 本片不改 Formal／Paper producer 或正式 ledger |
| Position owner／reviewer | 將 candidate packet 審閱後，以既有 `scripts/record_position_thesis.py` 寫入 explicit human thesis registry；reviewer identity／理由不可由本片捏造 | 不把 candidate-only packet 當成 approved thesis |

## Candidate packet schema

固定 schema：`forward-position-thesis-candidate.v1`。每筆 candidate 的 identity 是
`candidate:{recommendation_result_id}:{stock_code}`，不可只用 stock code；同一股票在
不同決策日可有多筆不可變 records。

必要內容：

```json
{
  "schema_version": "forward-position-thesis-candidate.v1",
  "candidate_id": "candidate:<result_id>:<stock_code>",
  "status": "awaiting_explicit_policy|candidate_ready|blocked",
  "candidate_only": true,
  "human_approval_required": true,
  "auto_action_allowed": false,
  "recommendation_source": {
    "result_id": "...",
    "path": "...",
    "file_sha256": "sha256:...",
    "content_sha256": "sha256:...",
    "created_at": "timezone-aware",
    "decision_date": "YYYY-MM-DD",
    "available_at": "timezone-aware"
  },
  "instrument": {"stock_code": "...", "stock_name": "..."},
  "decision_observation": {
    "reasons": ["原始推薦理由"],
    "scores": {"total_score": "Decimal text", "indicator_score": "Decimal text"},
    "industry": "...",
    "regime_match": false
  },
  "thesis": {
    "kind": "machine_observation",
    "statement": "由來源證據組成的觀測摘要；不是人工投資理由",
    "source_trace": ["recommendation:<id>", "config_hash:sha256:..."]
  },
  "invalidation": {
    "status": "explicit_policy|missing",
    "policy_id": "...",
    "policy_version": "...",
    "policy_source": "...",
    "policy_actor": "...",
    "policy_path": "...",
    "policy_hash": "sha256:...",
    "rules": []
  },
  "holding_horizon": {
    "status": "explicit_policy|missing",
    "trading_days": null,
    "review_cadence_trading_days": null,
    "next_review_date": null
  },
  "entry_binding": {
    "status": "awaiting_paper_fill|bound|rejected_preexisting|ambiguous",
    "position_id": null,
    "entry_lineage_id": null,
    "fill_id": null,
    "entry_evidence_hash": null,
    "entry_available_at": null
  }
}
```

`decision_observation.reasons` 必須逐字保留推薦來源；它不是 `entry_thesis`。候選
只有在呼叫端交付已 hash 綁定的 policy JSON 時，才可填寫 `invalidation.rules`、
`holding_horizon.trading_days` 與 `next_review_date`。policy 必須宣告來源、版本、
有效時間與官方交易日 calendar hash；沒有明確 policy 就 fail closed 為
`awaiting_explicit_policy`。

所有分數在核心保存為 Decimal text；推薦 DTO 的 float 只在既有輸入邊界被轉成
Decimal。`available_at <= decision_at`，source bytes 在讀取前後必須相同；candidate
內容用 canonical JSON hash，當日同 identity 的 bytes 不一致不得覆寫，另產新 immutable
hash path 並在 receipt 標示 conflict。

## Entry binding 與 Health 接線

候選在 recommendation 時不取得 position identity。Paper producer 完成後，binder
只接受：

1. 同一 Paper portfolio 的 read-only ledger；
2. `filled`／`partially_filled` 且 `filled_quantity > 0` 的 buy event；
3. identity provider 已證明的 flat-to-positive entry，含 `entry_fill_id`、
   `entry_source_event_id`、entry evidence hash；
4. `entry_date > candidate.decision_date` 且 candidate 在 entry 前已 available；
5. 跨日期沒有同日無序 material fill、source bytes／calendar／snapshot receipt
   變動或 future row。

既有持倉若 entry evidence 早於 candidate decision，輸出
`rejected_preexisting`；不可把同 stock code 的舊 position 綁到新 candidate。
無法唯一選擇 candidate 或 entry 順序不明則輸出 `ambiguous`，不猜測。binding receipt
只寫隔離 derived output；不追加 human thesis registry，也不改 Paper／Formal。

綁定成功後，下一次自然 health refresh 讀取同一 stable identity，market source
producer 對該 `position_id` 產生 Decimal metrics／PIT condition，transition evaluator
再以同一 `entry_lineage_id` 驗證來源。candidate policy 仍標示
`human_approval_required=true`；未經既有 reviewer 以 `record_position_thesis.py`
寫入 registry 前，不可當作 approved human thesis，也不可授權自動 transition。
若 candidate 的 explicit policy、availability、Paper proof 與官方 calendar 都重新驗證
成功，`ForwardPositionThesisBindingProvider` 會建立
`PositionThesisContract(source_type=machine_policy, source_actor=...)` 作為前瞻
proposal-only evaluator input；這個 machine contract 只保存可重驗的 machine
observation、失效規則與 review horizon，不生成投資理由，也不寫入 human registry。
同一 lineage 若已有 human-reviewed registry contract，human contract 仍優先。

綁定 consumer 會重新驗證整條 custody chain，而不是只比對 `stock_code` 或
`result_id`：`candidate.result_id` → candidate 的 recommendation `file_sha256`／
`content_sha256` → Paper candidate 的相同 recommendation path／兩種 hash →
`source_event_id`／`order_id` → 唯一 filled buy `fill_id` → read-only Paper ledger
row／`entry_evidence_hash`。Paper execution candidate、ledger 或 binding entry 任一
欄位被替換、換 portfolio、換 fill 或換 evidence hash 都會被拒絕；缺少尚未可驗的
Paper proof 則維持 `awaiting_paper_fill`，不可降級成 bound。

05:15 Health scheduled caller 以 repository-isolated
`output/forward_position_thesis/bindings/` 目錄自動讀取全部 immutable binding
receipts，逐筆以當日可見的 baseline position identity 重驗上述 chain；因此不需人工
指定單一檔案，也不會把 `latest_binding_status.json` 視為完整 portfolio。成功的
binding 在沒有 policy 時只加入 lineage provenance；有 explicit verified policy 時，
可另外提供 machine-policy contract 作為 proposal-only evaluator input。缺少 policy、
PIT condition／metrics 或任一 custody 時，evaluator 保留 `degraded`／
`required_human_fields`；human approval 在所有情況仍然需要。

## Daily caller 與 Gate

- 05:10 recommendation task 儲存 result 後立即產生 candidate packet；output 預設為
  repo 隔離目錄 `output/forward_position_thesis/`，不把大檔寫入 D 槽。
- 05:15 health/evidence task 只讀 packet／baseline 與
  `output/forward_position_thesis/bindings/` 全部 receipts；沒有新 filled entry 時維持
  `awaiting_paper_fill`，不為舊三筆補 identity。
- Paper EOD／next natural health refresh 後可呼叫 binder；binder 的成功只代表
  lineage evidence 可追溯，不代表 thesis review、transition apply、Formal credit 或
  broker permission。
- `blocked`／`ambiguous`／source hash mismatch／future clock／missing policy 均保留
  receipt 與原因，return code 非零或 wrapper 顯示 degraded；不可用 stale packet
  冒充 current decision。

## 負向驗收矩陣

| 情境 | 預期 |
|---|---|
| recommendation 檔讀取中變動 | `blocked`，不寫 candidate |
| recommendation `available_at` 晚於 decision cutoff | `blocked` |
| 沒有明確 policy | packet 可保存但 `awaiting_explicit_policy`，rules／horizon 為 missing |
| policy hash／schema／calendar 不符 | `blocked` |
| candidate 同日重跑相同 bytes | idempotent，immutable bytes 不變 |
| 同 stock 新決策日 | 新 candidate id，不覆寫舊 packet |
| 舊三筆 entry 早於 candidate | `rejected_preexisting` |
| buy→flat→buy | 只綁第二次 verified entry |
| 同日多筆 material fill 無 sequence/time | `ambiguous`／blocked |
| fill 只有 rejected／zero quantity | `awaiting_paper_fill` |
| bind 後 source/evaluator | machine policy 可供 proposal-only；缺 policy／source 仍 degraded，human approval 不變 |
