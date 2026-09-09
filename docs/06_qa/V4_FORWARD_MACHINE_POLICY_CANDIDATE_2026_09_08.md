# V4 前瞻 Paper machine policy candidate（2026-09-08）

狀態：`approved_for_activation`。這份文件是 root 已核准、並已寫入 future-effective
policy bytes 的 research-only 工程基準；在政策生效日前不產生新持倉 contract，仍不能
被 Paper、broker、Formal promotion 或 ML credit 消費。所有參數都是前瞻工程假設，不是
由舊持倉、歷史報酬、未曝光 fold 或回測結果推導出來，也不代表已驗證的風控效果。

## Candidate identity

| 欄位 | 候選值 |
| --- | --- |
| `policy_id` | `paper-machine-thesis-benchmark-v1` |
| `version` | `2026-09-08-approved-v1` |
| `source` | `root_approved_forward_machine_policy_engineering_baseline` |
| `actor` | `forward_position_policy_producer` |
| `status` | `approved_for_activation`；policy bytes 建立後仍只做 proposal-only |
| `effective_from` | 第一個 verified official session 且其台北 08:30 cutoff 嚴格晚於 policy producer 的實際 available_at；若當日 cutoff 已過則取下一 session，不固定寫入過去日期 |
| `available_at` | policy producer 以實際 timezone-aware clock 寫入，並同時保存 `recorded_at` |
| `candidate_only` | `true` |
| `research_only` | `true` |
| `auto_action_allowed` | `false` |
| `broker_order_allowed` | `false` |
| `formal_credit` | `false` |

## Proposed invalidation rules

這些指標都已在 `PositionHealthMarketSourceProducer` 的 Decimal source schema 中存在；
root 已核准它們作為前瞻 research-only `forward-position-policy.v1` baseline。所有 threshold
都是 Decimal 文字，避免 JSON binary float 進入核心計算。

| `metric_id` | 單位與來源 | operator / threshold | action | 選值理由（工程基準） |
| --- | --- | --- | --- | --- |
| `macd_hist` | 每股價格單位（TWD/share），`technical_indicators.MACD_hist` | `lte` / `"0"` | `reduce` | 以動能柱當日 level ≤ 0 作為需要人工複核的保守訊號；它不是已證實的「翻負」cross，與既有 recommendation profile 的 MACD 欄位一致 |
| `rsi` | 指標點（Decimal，預期 0–100），`technical_indicators.RSI` | `lte` / `"30"` | `reduce` | 定義極弱動能的 review trigger；不是自動賣出條件，也未宣稱是歷史最優門檻 |
| `adx` | 指標點（Decimal，常見 0–100），`technical_indicators.ADX` | `lt` / `"15"` | `reduce` | 低趨勢強度時要求重新檢視持倉假設；與既有 daily trend source 相容 |

這三條規則的作用是產生 proposal signal。`PositionHealthStateMachine` 仍必須收到
三條同一 decision cutoff 的 Decimal metrics；任何一條缺失、future、identity 不符或
source hash 不符都維持 `WATCH`／`degraded`，不會被當成「未觸發」。只有人工 reviewer
另行核准後，才可能改變 recorded state；此 candidate 絕不允許自動 exit。

## Holding and review policy

| 欄位 | 候選值 | 理由與限制 |
| --- | --- | --- |
| `holding_horizon_trading_days` | `20` | 獨立的前瞻工程觀察窗，與 Rule 的 minimum history 語意不同；不是歷史績效結論 |
| `review_cadence_trading_days` | `5` | 自動每五個 verified sessions 產生 review evidence 的節奏；人可覆核，但人工可用性不是排程 gate |
| `next_review_date` | policy 生效後，以實際 entry date 加 5 個 verified official sessions 計算 | 不用 weekday 推算，不從舊持倉日期回填；跨假日由 calendar cache 決定 |
| `policy_expiry` | policy bytes 在明確 `supersede`／`retire` 前保持 immutable 有效 | calendar／source receipt 失效時 fail closed；經既有 validated renewal 取得新的 calendar observation／snapshot 後恢復當日驗證，不修改舊 policy，也不因日曆續期切換 policy identity |

## Required source custody before activation

啟用時 producer 必須保存並重驗：

1. policy 完整 bytes、`policy_file_sha256`、`available_at`、`recorded_at`、actor 與
   owner approval；`available_at` 不得晚於 recommendation decision cutoff。
2. recommendation result 的 file hash、canonical content hash、result id、config hash、
   decision timestamp 與機器觀測理由。理由只作 `machine_observation`，不冒充人類
   `entry_thesis`。
3. Paper 新增 filled buy 的 `position_id`、`entry_lineage_id`、`fill_id`、
   `source_event_id`、entry date、entry evidence hash；必須與同一 recommendation
   result／file hash／content hash 對上。
4. official calendar cache path、file/source hash、available／expires 與完整 session
   coverage；review date 必須在 entry lineage 生效後重新計算。
5. 當日 PIT condition／Decimal metrics 的 source snapshot hash、capture completion、
   selected rows 與上述 lineage；所有輸入在 evaluator cutoff 前可得。

## Activation gates

這份 candidate 已取得 root 的參數核准，並已由 policy producer 保存 owner approval、
實際 available_at、immutable policy bytes／hash 與 activation receipt；policy producer、
candidate binder、Health consumer 的 isolated positive／negative matrix 已通過，並已
設定 `FORWARD_THESIS_POLICY_PATH`。啟用後仍只允許
candidate／proposal-only：

- 新 policy 生效日前的候選與既有三筆未知持倉不建立 machine thesis，不回填歷史。
- new flat→positive Paper entry 才能建立 machine thesis contract；closed→reentry
  一律新 lineage。
- machine thesis 需標示 `source_type=machine_policy`、`actor`、policy bytes/hash、
  recommendation identity 與 Paper evidence；缺任一 custody 欄位即 `awaiting_lineage`
  或 `blocked`。
- `entry_thesis` 的 machine statement 只能說明可驗證的策略觀測，例如候選 id、
  Rule config hash 與 source trace，不可生成「看好」「高勝率」等人類投資理由。
- Health policy identity 與 Formal Rule policy identity 必須分離；Rule hash 只放
  provenance/input hash。

## 審核結果

root 已於 2026-09-08 以具名 machine policy review 核准上述三個
metric／threshold、20 個交易日觀察窗與 5 個交易日自動 review evidence cadence，
並核准 machine policy thesis 進入 proposal-only Health evaluator。這項核准不等於
自動交易或人工 approval；policy bytes 仍須 immutable，明確 supersede／retire 前
保持同一 policy identity。

policy producer 的有效日規則是：取第一個 verified official session，且其台北 08:30
cutoff 嚴格晚於 producer 實際 `available_at`；若當日 cutoff 已過則取下一交易日。
日曆來源會以完整 bytes 存成 policy 專屬 immutable snapshot；日後 calendar renewal
只在新的 activation observation receipt 記錄現行來源 hash，不改舊 policy bytes／hash，
也不要求重新人工批核同一組參數。來源或日曆驗證失敗仍 fail closed。

首次 activation receipt（實際 clock）為：
`output/forward_position_thesis/policy_activation/activation_paper-machine-thesis-benchmark-v1_2026-09-08-approved-v1_772f6656220d35f7.json`；
policy bytes hash 為
`sha256:23c3d37f36630b9a9217f41e6d60c50b17ee1bea44b3843edef55c1d904512ee`，
immutable calendar snapshot 為
`output/forward_position_thesis/calendar_snapshots/paper-machine-thesis-benchmark-v1_2026-09-08-approved-v1_74790d36d0cd6639.json`。

本片即使完成 policy bytes 建立，也只啟用未來新 entry 的 proposal-only contract；不
回填舊持倉，不代表完整 V4 Health／Exit 或任何歷史／實盤效果已完成。
