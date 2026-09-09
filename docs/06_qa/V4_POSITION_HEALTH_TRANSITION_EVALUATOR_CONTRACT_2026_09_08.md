# V4 Position Health Transition Evaluator 契約與接線盤點

日期：2026-09-08

owner：scheduler／operations（盤點、source provider 與 proposal-only caller）；完整資料 producer 與 reviewer workflow 仍需由 root／對應 owner 接續審核。

範圍：盤點現有 PositionHealth、condition、entry thesis 的真正生產接線，定義最小可完成的 daily transition evaluator。這一片沒有新增投資理由、沒有改寫 Paper／Formal writer，也沒有改動 D 槽原始資料。

## 結論

目前專案已經有可重用的狀態機、thesis schema、append-only transition repository、Paper snapshot／lineage 的 daily baseline producer，以及本片新增的 proposal-only evaluator path。Evidence consumer 現在可以讀到當日 health source；Paper source-to-ID provider 也已接入，但 9/8 現有持倉在 bounded ledger window 找不到可證明 entry event，因此 real readback 仍是 `degraded`，並缺少 thesis、invalidation、holding horizon、review date 的人工作業資料。這表示目前可以交付「有來源的 freshness／baseline」與安全的 transition proposal，還不能宣稱 V4 的完整每日持倉 transition evaluation 已完成。

本片已新增一個薄的 evaluator adapter，重用既有服務與契約，不再建立第二套持倉狀態機：

1. `PositionHealthDailyRefreshService` 提供 Paper snapshot、持倉數量、entry lineage、ledger coverage 與 readback digest；`PaperPositionIdentityProvider` 由驗證過的 Paper fill evidence 產生或承接 stable position／entry ID。
2. `PositionThesisRegistryProvider`／`PositionThesisRegistryWriter` 與 `scripts/record_position_thesis.py` 提供受治理的人工 `PositionThesisContract` 入口；缺少或無法驗證時保留 `WATCH`／unknown。
3. `PITConditionSourceProvider` 與 `DecimalMetricSourceProvider` 接受帶有 PIT 時間、source hash 與 stable lineage 的 derived artifact；目前 9/8 repository 沒有這兩類實際 producer，故仍回報缺件。
4. evaluator 呼叫 `PositionHealthStateMachine` 與 `PositionHealthService`，只產生 proposal，交由 `PositionHealthTransitionRepository` 保存 proposal；只有人工核准事件才改變 recorded state。

在實際 thesis／condition／metrics artifact 產生並通過 PIT、hash、lineage gate 前，daily evaluator 的 overall 狀態最多是 `degraded`，不應用缺值填成 HEALTHY，也不應把 UI 即時計算結果當成排程來源。官方 calendar 已透過 `OfficialCalendarSourceProvider` 從已驗 cache 唯讀接入。

## 現有接線盤點

### 已存在且可重用的元件

| 元件 | 實際能力 | 目前限制 |
| --- | --- | --- |
| `app_module/position_health_service.py` | 將 condition 與 feedback GateStatus 映射成 `HEALTHY`、`WATCH` 或 `EXIT_CANDIDATE`，並保留 reasons/source trace；現在由薄 evaluator 組合。 | 沒有持倉／來源 provider；只接受 caller 傳入的 condition result。 |
| `app_module/position_health_state_machine.py` | 依 thesis invalidation rules、Decimal metrics、review date、明確交易日曆產生 proposal；future metric、缺 metric、calendar 不完整會 fail closed。 | 沒有 production orchestration；`apply_transition=False` 是唯一安全模式。 |
| `app_module/position_thesis_contract.py` | 驗證 position identity、entry／decision／available date、entry thesis、horizon、review date、invalidation rule、source trace；禁止 auto exit。 | 已有人工 registry writer／CLI；沒有 producer 將 Paper fill 或 advice 自動轉為此 contract。 |
| `app_module/position_health_transition_repository.py` | append-only SQLite；proposal 不改 recorded state，human-approved 需要 reviewer；禁止 auto action；由 evaluator 以 identity/date conflict guard 寫入 proposal。 | repository record 本身仍不保存完整 input hash，hash 由 evaluator event id／result provenance 綁定。 |
| `app_module/position_health_daily_refresh_service.py` | 唯讀讀 Paper snapshot、Paper status、ledger coverage，做跨 snapshot entry-lineage readback，輸出 immutable baseline／latest receipt。 | 明確只做 baseline，不評估 thesis、invalidation、condition 或 transition。 |
| `app_module/paper_position_identity_provider.py` | 以同一 state DB、Paper ledger、preopen coverage receipt 與 bounded event window 驗證 source；對 flat→positive filled buy 產生 deterministic stable ID，對 verified active lineage carry，closed→reentry 產生新 ID。 | 目前 9/8 的 bounded window 沒有可證明的三筆既有持倉 entry；不把 stock code 當 ID，也不改 Paper producer。 |
| `app_module/paper_decision_desk_evidence_source.py` | 將 Paper snapshot 與 health baseline 接到 Evidence consumer，未知／缺來源保留 unknown。 | 是 evidence source，不是 transition evaluator。 |

### 已存在但沒有安全 scheduled source 的路徑

1. `app_module/portfolio_condition_monitor.py` 的 `evaluate(position, current_snapshot=None)` 可以比較進場來源與目前 regime／score／price，但結果本身沒有 as-of date、source hash 或 quality receipt。
2. `app_module/portfolio_alert_service.py` 在 `_collect_alerts` 以 `condition_monitor.evaluate(position)` 呼叫，沒有傳 `PortfolioCurrentSnapshot`。因此 Decision Desk scheduled path 不能證明目前 regime／score；缺少 current snapshot 時不能當成有效的 daily condition source。
3. UI `ui_qt/views/portfolio_view.py` 會自行取得 `_current_snapshot_for_position`，再呼叫 condition monitor。這是互動快照／cache 路徑，沒有可供 Paper PIT evaluator 直接信任的持久 receipt，不應被排程直接重用。
4. `app_module/portfolio_feedback_service.py` 與 `app_module/portfolio_review_service.py` 都接受 caller 提供的 condition result／drift report；它們沒有預設的 current-condition provider，也不會自動產生 thesis。

### 衝突或孤立的舊路徑

`app_module/position_service.py` 是另一個 legacy `PositionDTO` 與 JSON 檔案路徑。它會以 `datetime.now()`、float 分數與固定 `score drop < -10` 修改 condition status，沒有 official calendar、PIT receipt、structured thesis 或 transition repository。現在 UI／Paper 主要使用 `app_module.dtos.portfolio_dtos.PositionDTO` 與 `PortfolioService`，production code 沒有 caller 真正注入 legacy `PositionService`；這條路徑必須在後續整併決策中明確標示為 legacy，不能混接到 V4 evaluator。

`app_module/advice_composer.py` 的 advice DTO 雖然有 `entry_thesis`、`invalidation_conditions`、`holding_horizon`、`review_date` 欄位，但 recommendation／portfolio compose 目前沒有提供完整 thesis contract；portfolio 的 `review_date` 只是 `data_as_of_date`。`app_module/portfolio_source_adapter.py` 只保存 recommendation／backtest 的 source metadata。`data_module/portfolio_ledger_repository.py` 已保存 `source_id`、`source_snapshot_hash`、`thesis_id`，可作為治理接點，但缺少 thesis 本體並不等於已完成 thesis。

`app_module/decision_quality_service.py` 的 `manual_thesis` 是 review／journal 提示與 source trace 類型，不是結構化、可供 evaluator 驗證的 thesis producer。Evidence 內的新鮮 `captured_at` 也不能替代原始 thesis 的 authored／reviewed date。

## 最小 daily evaluator 契約

本片已實作單一薄 adapter，邏輯入口為：

```text
evaluate_daily_transition(request: DailyPositionHealthTransitionRequest)
    -> DailyPositionHealthTransitionResult
```

### Request 必填內容

| 欄位 | 契約 |
| --- | --- |
| `decision_date` | Asia/Taipei 的 `YYYY-MM-DD`；不得晚於實際 observed boundary。 |
| `observed_at` | timezone-aware UTC timestamp；所有 child／receipt 的時間都必須可比較，future input 直接 blocked。 |
| Paper snapshot | `portfolio_id`、stable `snapshot_id`、snapshot decision date、active positions／quantity、state DB path、rows digest、data version。使用 `PositionHealthDailyRefreshService` 的 read-only receipt。 |
| previous health | previous baseline hash、source snapshot identity、每個 position 的 previous state／reasons／history；只可作歷史與 continuity proof，不能無條件按 stock code 繼承。 |
| Paper lineage | preopen status receipt、previous/current endpoint identity、同一 ledger path／hash、SQL bounded `[previous_snapshot_date, current_snapshot_date)` event coverage、WAL-visible canonical row digest，以及由 filled buy evidence 產生的 stable `position_id`／`entry_lineage_id`。`unproven` 只能輸出 WATCH／unknown。 |
| thesis map | `position_id -> PositionThesisContract`；缺少時明確傳 missing，不由 model、advice 或 evaluator 代填。 |
| condition map | 每個 active position 的 `PortfolioConditionResult` 加 `PortfolioCurrentSnapshot`，並包在 `source_id`、`source_snapshot_hash`、`as_of_date`、`available_at`、quality／boundary receipt 中。scheduled caller 不可只傳 `position`。 |
| metrics map | 每個 invalidation rule 的 `PositionHealthMetric`，值必須是 `Decimal`，`available_date <= decision_date`；缺少、future 或來源 hash 不匹配時不能宣稱 healthy。 |
| calendar attestation | 已驗官方 cache 的 source path／hash、calendar version、完整 entry→decision session coverage；不可用 weekday 猜交易日。 |
| policy／schema | evaluator schema version、condition/thesis source versions、policy hash；所有輸入 hash 要進輸出 provenance。 |

### Result 必填內容

```json
{
  "schema_version": "position-health-transition-evaluation.v1",
  "status": "passed|degraded|blocked",
  "decision_date": "YYYY-MM-DD",
  "observed_at": "aware ISO-8601",
  "research_only": true,
  "apply_transition": false,
  "auto_action_allowed": false,
  "broker_execution": false,
  "formal_credit": false,
  "provenance": {},
  "positions": []
}
```

`provenance` 至少包含 Paper snapshot／rows hash、previous baseline hash、ledger file／rows digest、calendar cache hash、thesis source ids／hashes、condition source ids／hashes、metric source ids／hashes、policy hash、coverage receipt。每個 position result 至少包含：

```json
{
  "position_id": "stable lineage id",
  "stock_code": "code",
  "previous_state": "HEALTHY|WATCH|REDUCE_CANDIDATE|EXIT_CANDIDATE|CLOSED",
  "proposed_state": "HEALTHY|WATCH|REDUCE_CANDIDATE|EXIT_CANDIDATE|CLOSED",
  "condition_status": "valid|warning|invalid|unknown",
  "reasons": [],
  "required_human_fields": [],
  "metrics_evidence": [],
  "entry_lineage_status": "same_snapshot_verified|ledger_continuous_no_trade|natural_entry_verified|carried_verified|unproven|closed_prior_not_projected",
  "source_trace": [],
  "review_required": true,
  "transition_event": {"decision_kind": "proposal", "recorded_state": "previous_state"}
}
```

`transition_event` 的形狀應能直接轉成 `PositionHealthTransitionRecord.proposal`；不應在 daily evaluator 內呼叫 `human_approved`，也不應寫 broker order、Paper fill 或 Formal ledger。人工核准必須另有 reviewer、決策日期與理由，並由既有 append-only repository 保存。

### Gate 與狀態規則

1. **Identity／lineage gate**：active quantity、stable position identity、Paper snapshot endpoint 與 ledger coverage 必須一致。`PaperPositionIdentityProvider` 只接受 bounded window 內已驗證的 filled buy 從 flat 轉為 positive，或已有 verified identity 且期間沒有 flat transition 的 carry；closed→reentry 不得只用同一 stock code 繼承舊 thesis。無法證明時 current state 只可 WATCH／unknown，舊欄位留在 `historical_prior_*`。
2. **PIT／time gate**：thesis available date、condition as-of、metric available date 不得晚於 decision date；aware observed timestamp 不得在 observed boundary 之後。future、naive、malformed 或 source 在讀取期間變更時為 `blocked`。
3. **Thesis completeness gate**：完整通過 `PositionThesisContract` 才能送入 state machine；任何 required human field 缺少時保留 `WATCH`／degraded，不產生推測的 thesis、invalidation 或 review date。
4. **Condition gate**：condition 必須有 current snapshot、日期、來源 id／hash 與 quality。缺 current snapshot 時不可由 `PortfolioConditionMonitor` 的預設空 snapshot 得到 HEALTHY；缺來源／unknown 只能 WATCH／degraded。
5. **Metric gate**：每一條 invalidation rule 都要有可追溯且 PIT 合法的 Decimal metric；missing／future metric 要留下具體 reason，不能當作未觸發。
6. **Calendar gate**：entry 到 decision 的官方 session coverage 必須完整；否則保留 `time_stop_calendar_incomplete`，不得把工作日數當成交易日數。
7. **Deterministic state gate**：重用既有 state machine 與 PositionHealthService，合併時採固定嚴重度 `EXIT_CANDIDATE > REDUCE_CANDIDATE > WATCH > HEALTHY`，並保留全部 reasons。condition invalid 或 feedback fail 不得被較弱的 healthy 結果覆寫；此優先序在實作前需由 root 核准並以表格測試固定。
8. **Human review gate**：daily 結果永遠是 proposal；`apply_transition=false`、`auto_action_allowed=false`。只有 reviewer-backed `human_approved` event 才能改 recorded state。
9. **Output integrity gate**：result／receipt 要 atomic write、同日 idempotent、保存 immutable history 與 source readback；任何 source DB、D 原始資料、Paper execution state 都不可被 evaluator 改寫。所有 required input 通過才可 `passed`；安全但資料不完整是 `degraded`，邊界／hash／schema／future／讀取失敗是 `blocked`。

## 還缺少的確切人工作業資料

每個仍持有的 `position_id` 都要由人或受治理流程補齊下列資料，不能由 model 或 recommendation 理由自動生成：

1. 穩定的 position／entry lineage，對應 Paper snapshot、filled ledger event／`thesis_id`；平倉後再進場要是新的 lineage。
2. `entry_thesis` 原文、作者／reviewer、建立日期與 source id／source snapshot hash。
3. 至少一條結構化 invalidation rule：`metric_id`、operator、Decimal threshold、unit、`reduce` 或 `exit` action，以及 metric source。
4. `entry_date`、thesis `available_date`、decision date 的關係證明。
5. `holding_horizon_trading_days`，以及由官方 calendar 計算的 session coverage。
6. `next_review_date`；不能把 daily `data_as_of_date` 當成 review schedule。
7. 當日 current condition 的來源觀測：regime／score／price（若策略需要）、as-of date、source id／hash、品質與邊界收據。
8. 人工 review／approval：reviewer、review date、採納或駁回 proposal、理由；此資料最後才可寫入 transition repository 的 `human_approved` event。

目前 real Paper evidence readback 已證實 health age 是當日且有 3 個 source-backed alerts；source-to-ID readback 也已驗證 state／ledger／coverage 的 bytes 與 bounded window，但三筆既有持倉沒有可證明 entry event，故 stable identity、以上第 2–8 項仍未形成完整 producer；因此 evidence 的 degraded 狀態是正確結果。

## 後續實作的最小驗收矩陣

實作 slice 需至少覆蓋：

- 完整 thesis／metrics／condition 產生 deterministic proposal；缺 thesis 或 partial thesis 只 WATCH／degraded，無 invented reason。
- future、naive、malformed condition／metric／thesis 直接 fail closed。
- scheduled path 沒有 current snapshot 時不會產生 HEALTHY。
- invalid condition、feedback fail、invalidation reduce／exit 的優先序與全部 reasons 穩定。
- official calendar 缺中間 session 時保留 `time_stop_calendar_incomplete`。
- 新的 flat→positive filled buy 可建立 deterministic stable ID；跨日 buy→flat→buy 只採最後一次 entry；同一 active lineage 跨不同 snapshot、ledger window 無事件時可 carry；closed→reentry 不 carry，缺 evidence 維持 unknown。v1 ledger 同一股票同日多筆 material fill 因沒有 sequence／time 而 blocked，不以 `fill_id` 猜順序。
- ledger coverage 缺失、WAL readback／來源 bytes hash 變更時 blocked；全歷史以外只讀關注 codes 與 bounded date window。
- duplicate proposal idempotence；human approval 沒 reviewer 必拒絕。
- daily evidence wrapper 的 health refresh blocked + 舊 latest fixture 使用 missing sentinel、overall non-ready／exit 2，不能沿用 stale data（此負例已在 `tests/test_scheduled_evidence_pipeline_dry_run_wrapper.py` 驗收）。

本文件是接線與驗收契約；本片已實作並接上 proposal-only evaluator、source providers 與 05:15 scheduled caller。官方 calendar 已以真實 verified cache readback；人工 registry 的 writer／CLI 也已提供可審核入口，但 9/8 真 baseline 沒有 stable lineage、人工 thesis、PIT condition 或 Decimal metric artifact，因此完整 source-backed transition evaluation 仍為 `degraded`。後續仍需由 root／對應 owner 接通 condition／metrics producer 與 reviewer workflow，再以本文件的正負矩陣完成 V4 transition evaluator 正式驗收；人工批准永遠只由真正 reviewer event 產生。
