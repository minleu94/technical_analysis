# V4 Position Health source-to-caller gap map（2026-09-08）

## 範圍

本清冊盤點每日 position-health transition evaluator 所需的五類輸入：Paper
position／entry lineage、受治理的 thesis、PIT current condition、Decimal metrics、
官方交易日曆。檢查範圍包括正式 Paper snapshot／ledger、app service、scheduled
caller 與既有 derived 產物；不把 UI 快取、recommendation 文案或模型輸出視為持倉
thesis 或 entry evidence。

## 實際 source-to-caller 狀態

| 輸入 | 已存在的來源 | 目前 caller | 結論與缺口 |
| --- | --- | --- | --- |
| Position／entry lineage | `paper_portfolio.sqlite` 的 `paper_portfolio_snapshots`／`paper_portfolio_positions`，加 `paper_trade_ledger.sqlite` 的 bounded read window 與 `paper_portfolio_isolated/latest_status.json` coverage receipt | `PaperPositionIdentityProvider` → `PositionHealthDailyRefreshService` → evaluator | 已接上唯讀 source-to-ID provider。只接受同一 Paper ledger 中、`[previous_snapshot_date, current_snapshot_date)` 內、已驗證且 filled 的 buy，並且該事件將數量由 0 轉為正數；ID 由 canonical event row hash deterministic 產生。現有 9/8 三筆持倉的 bounded window 沒有可證明 entry event，故三筆維持 `position_id=null`／`unproven`／degraded；stock code 不會被升格為 lineage。 |
| Thesis | `PositionThesisContract` schema；ledger 僅有 `thesis_id`，沒有 thesis 本體 | `PositionThesisRegistryProvider`／`PositionThesisRegistryWriter` 與 `scripts/record_position_thesis.py` 是受治理的人工入口；`decision_quality_service.manual_thesis` 與 advice DTO 不是 contract producer | registry 已具備版本、effective／available time、內容 hash、跨程序 lock 與實際 `recorded_at`；無人工輸入時保持 missing，且晚到的手填不能取得歷史 PIT credit。 |
| PIT current condition | `PortfolioConditionMonitor`／`PortfolioCurrentSnapshot` domain contract；每日 `technical_indicators` 與 `daily_prices` 由 quick update／freshness receipt 證明 | `PositionHealthMarketSourceProducer` → `PITConditionSourceProvider` → evaluator；scheduled `run_scheduled_evidence_pipeline_dry_run.py --produce-position-health-sources` 已接線 | producer 先讀兩份 upstream receipt，再以 SQLite `mode=ro/query_only` capture selected rows，保存真實 capture 起訖、DB stat／data version、selected rows hash。輸出 condition 是 observation-only（沒有 thesis／current regime 不會猜），缺 stable lineage 的 stock code 只列 `unresolved_identity_codes`。目前 9/8 真 readback 沒有可驗證 ID，故 condition row 為 0、整體 degraded。 |
| Decimal metrics | `PositionHealthMetric` contract；同一個 market source producer 的 `technical_indicators`／`daily_prices` selected rows | `PositionHealthMarketSourceProducer` → `DecimalMetricSourceProvider` → evaluator；與 condition 共用同一 source snapshot hash | producer 只將已 capture 的欄位轉為 Decimal text，保存 available_at、metric definition、source／baseline／receipt hash 與 lineage；不從 UI float、model 或 stock code fallback 生成 invalidation。9/8 因三筆持倉均無 stable ID，metrics row 為 0，等待合法 entry lineage。 |
| Official calendar | `OfficialTradingCalendar` + `load_verified_twse_calendar_cache`；9/8 cache 為 `output/paper_execution_eod_replay/calendar_cache/twse_holiday_schedule_2026_20260907_capture1.json`，可 offline 驗證 | `OfficialCalendarSourceProvider`；`run_official_calendar_cache_refresh_daily.py` 已接 `run_ml_allocation_forward_daily.cmd` 的盤前 pre-step | 已直接接線。provider 以 verified cache 回傳交易日、cache/source hash、capture／expiry，並拒絕過期、未來或缺年度；盤前 refresh 失敗會使 forward／health caller 保留 blocker，不借用過期 cache。 |

## 9/8 真 baseline 與 market source readback（唯讀）

來源為 `output/v4_next_ops/position_health_identity_readback_20260908_v3/`，摘要收據為
`readback_summary.json`，
其中 `baseline_20260908.json` 的 baseline hash 是
`sha256:1e335f4681ddfcecbc33f3c096d778b8c67205f66dd19ff289ee026c2b79831b`；Paper
snapshot 為 `paper-main-20260908`，3 筆 active rows。新的 identity provider 以同一
state DB、Paper ledger 與 `paper_portfolio_isolated/latest_status.json` 做唯讀讀回：
coverage `status=ready`、ledger window 是 `[2026-09-07, 2026-09-08)`、row count=0，
因此 1418／1536／1615 都保留 `position_id=null`、`entry_lineage_status=unproven`，
沒有捏造 lineage。隔離 evaluator 的結果在同目錄 `transition/latest.json`：
`status=degraded`、3 positions、0 proposals，calendar verified；缺 stable identity、
thesis、PIT condition 與 Decimal metrics。baseline／evaluator 都標示不寫 Paper、
Formal 或 raw。

同一份 baseline 以實際 CLI 時鐘執行
`scripts/run_position_health_market_sources.py`，readback 在
`output/v4_next_ops/position_health_market_source_readback_20260908/`。upstream quick
receipt 的 `completed_at=2026-09-08T11:32:45-07:00`、freshness receipt 的
`checked_at=2026-09-08T05:00:01-07:00` 均早於本次 capture；source receipt 保存
`market_capture_started_at`／`market_capture_completed_at=
2026-09-08T16:57:50.762482Z`、source snapshot hash
`sha256:15ca90632c274d04912da3d9d5469a956179a8a8ce297a376df901bd063b69d4`，status
為 `degraded`、condition／metrics row 均為 0、未寫 D／Paper／Formal。capture
沒有凍結成呼叫前的歷史時間；若指定較早 cutoff，實際 capture 越過 cutoff 會
fail closed。

## 接線規則

1. provider 只讀 immutable／append-only derived artifact；market source 先讀 upstream
   receipt 再 capture selected SQLite rows，不寫 D 槽 raw、Paper state
   或 Formal producer。
2. 每一筆返回的 source id、artifact hash、available_at、as-of date 與 position／entry
   lineage 都必須能被 caller 驗證；`available_at > decision_at`、hash 改變、stock 或
   lineage 不符時為 blocked。market source 另保存真實 capture 起訖；沒有 selected
   identity 時跳過大表掃描，不用 stock code 代替 lineage。
3. 缺 source 是 degraded／unknown；不得將缺 source 轉成 `HEALTHY`，也不得從
   recommendation、模型或 UI 文字捏造 thesis／metric。
4. 官方 calendar 只能重用 verified cache；cache 需涵蓋 thesis entry 到 decision 的
   endpoint，並在 observed time 尚未過期。

## 最小可完成路徑與剩餘項目

本片已接上 registry／condition／metrics／calendar provider、Paper source-to-ID provider、
market source producer 與 evaluator caller，讓已提供且可驗的資料真的進入 request；
9/8 真實 baseline 的 market source readback 已完成，但仍會因現有持倉缺 entry event、
人工 thesis、可供 transition 的 PIT condition 與 metric 保持 degraded。新自然
entry 的 producer 接口已定義為：Paper producer 在下個 preopen snapshot 中保留
filled buy 的 `fill_id`／`source_event_id`、event date、source type 與 coverage receipt；
provider 會用 bounded interval 和同一 ledger rows hash 產生 stable ID。這個接口只讀
Paper producer 的既有輸出，不修改 `data_module/paper_daily_execution_producer.py`。
跨日持倉只有在 verified prior identity 且期間沒有 flat transition 時才 carry；closed→
reentry 一律新 ID；歷史無法證明則維持 unknown。後續仍需 reviewer 建立 thesis
contract，並由資料 owner 產生 PIT condition 與 Decimal metrics artifact；這些輸入齊全
且通過時間／hash／lineage gate 後，才可取得非 degraded 的 proposal-only transition
結果。

### Source-to-ID 合法性規則

1. Snapshot schema 只有 `stock_code`／quantity，不能單靠代號建立 position identity。
2. Coverage receipt 必須是 isolated Paper producer 的 `status=passed`，綁定同一 state DB、
   ledger path、snapshot id／decision date、calendar validation 與 execution boundary；
   receipt bytes 於讀取前後相同。
3. Ledger 僅讀取 bounded `[previous_snapshot_date, current_snapshot_date)`；同日 current
   snapshot 的事件留到下一個 preopen，避免把盤後成交授予當日盤前決策。
4. 只有已驗證 `filled`／`partially_filled` buy 且從零持倉變成正數，才可產生
   `paper:{portfolio}:{stock}:entry-{canonical_event_hash_prefix}`；quantity mismatch、
   sell 超過持倉、source type／hash／schema／時間不符直接 blocked。v1 ledger 沒有同日
   sequence／time；同一 stock 同日有兩筆以上 material fill 時直接以
   `paper_position_identity_event_order_ambiguous` blocked，不用 `fill_id` 猜先後。
5. Provider、baseline 與 evaluator 都保留 source file／rows hash、coverage hash、
   available／decision time、snapshot identity 與 entry evidence；不寫 Paper、Formal、
   D raw 或 broker。

新的自然 entry 將在下一個 preopen snapshot 首次滿足上述 interval 後自動產生 deterministic
ID；不以 9/8 的盤後事件倒填 9/8 ID，也不把目前未知持倉升格為已證明 lineage。

## Frozen policy 與新持倉 thesis 欄位映射

目前 Formal Rule source 的實際可用欄位是 `policy_hash`、`policy_version`、
`strategy_version`、`source_window_hash`、`clock_manifest_hash`、排名所用的
`score_configuration_hash` 與安全邊界。它能證明「某日以哪一份 Rule ranking machine
source 做候選觀測」，不能證明「某筆持倉為何應進場、何時失效或持有多久」。
`FrozenRulePolicySourceProvider` 將這些欄位放在 `provenance.policy`，而 Health state
machine 的實際 `policy_hash` 維持獨立；完整 provenance 仍進入 evaluator 的 position
`input_hash`。

新持倉若要從候選走到 source-backed Health，caller 應沿以下既有來源鏈提供欄位：

| Health 欄位 | 可接受來源與綁定 | 目前狀態 |
| --- | --- | --- |
| `position_id`／`entry_lineage_id`／`entry_date` | Paper preopen snapshot、filled buy 的 `fill_id`／`source_event_id`、同一 ledger rows digest 與 coverage receipt；flat→positive 產生新 lineage | 新自然 entry 可自動建立；9/8 三筆舊持倉無可證明 entry，保持 unknown |
| `entry_thesis` | reviewer 以 `PositionThesisContract` 寫入 registry；候選的 `recommendation_reasons` 只算 machine observation | 目前缺 reviewer contract；不可由 recommendation 文案或 Rule hash 代填 |
| `invalidation_rules` | 明確版本化 `forward-position-policy.v1` 或 reviewer contract；每條含 `metric_id`、operator、Decimal `threshold`、`reduce`／`exit` | Formal Rule source 未提供；需策略 owner 凍結並保存 policy bytes／hash |
| `holding_horizon_trading_days`／`next_review_date` | 同一 explicit policy + verified official calendar，依 decision cutoff 計算 | Formal Rule source 未提供；不可把 daily `data_as_of_date` 當 horizon 或 review date |
| condition／metrics | `PositionHealthMarketSourceProducer` 讀 quick／freshness verified 的 PIT SQLite rows，condition 與 metrics 共用 source snapshot／capture completion hash | caller 已接線；無 stable lineage 時合法輸出 0 rows／degraded |
| Health transition `policy_hash` | Health state machine 自己的實際 transition rules／schema identity | 已保留；不可被 Formal Rule ranking hash 覆寫 |

`app_module/dtos.RecommendationDTO` 現有 `recommendation_reasons`、四類分數、產業與
`regime_match` 可作候選的可追溯觀測；`RecommendationResultDTO.config` 可綁 profile／
strategy config hash。`RecommendationAdviceDTO` 雖保留 `entry_thesis`、
`invalidation_conditions`、`holding_horizon` 與 `review_date` 欄位，但目前
`AdviceComposer` 不會從推薦結果產生完整 `PositionThesisContract`，故這些空欄不能被
視為已完成的 thesis producer。正式 Rule-only 設定目前只有 20-session history、
60-session source window、score formula、selection capacity=1 及 no-trade safety
flags；沒有持倉失效或持有期限。`PortfolioConditionMonitor` 雖能讀取舊
`source_summary.stop_loss_pct`／`take_profit_pct`，現行
`build_recommendation_trade_source` 沒有從 `RecommendationDTO` 產生這些欄位，且
legacy monitor 不能直接作 PIT source；因此這些門檻目前也是缺資料，不可從 monitor
預設值補出。

最小未來閉環是：推薦 producer 保存 recommendation file／content hash、候選觀測理由
與 frozen strategy config → explicit machine policy producer 提供 invalidation／horizon／
review date → Paper filled entry 綁定同一 result／source hash → Health source producer
以同一 lineage 產 PIT condition／Decimal metrics → evaluator 保持 Health policy identity
並產 proposal。`ForwardPositionThesisBindingProvider` 會在重新讀取 candidate／policy
bytes、Paper fill proof 與 verified official calendar 後，僅對 policy 生效日後的新
flat→positive entry 建立 `PositionThesisContract(source_type=machine_policy)`；review
date 以實際 entry date 加 cadence sessions 重算，並把 actor、policy bytes/hash、
recommendation／Paper hashes 與 entry evidence 放入 source trace。這個 machine contract
仍然是 proposal-only，`human_approval_required=true`，不會寫入人工 registry，也不會
自動核准或執行 transition。無 explicit policy、缺可得時間或 lineage custody 時仍是
degraded／awaiting，不以 recommendation 文案補 thesis。人工作業 contract 仍優先於
machine fallback。歷史三筆無法證明的持倉不回填；只有新的自然 entry 或 reviewer 明確
輸入能填補上述缺口。
