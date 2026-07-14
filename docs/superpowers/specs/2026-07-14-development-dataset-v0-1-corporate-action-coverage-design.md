# Development Dataset V0.1 Corporate-Action Coverage 設計規格

## 決策

採用 **Coverage-first／既有來源優先**。本切片只使用 repository 與正式資料根中已存在、可唯讀且具可驗證歷史時間語意的 corporate-action 資料；不申請或接入新外部來源，不以價格跳空反推事件，不調整 Rule／ML 模型或超參數。

## 目標

在 Terra Development Dataset V0 的 label construction 前加入 corporate-action coverage boundary，使除權息、減資、拆併股或面額變更落入 label window 時，系統能夠：

1. 以可追溯事件資料安全調整 label；或
2. 在資料不足時明確排除／降級該 label window；
3. 保存事件、coverage、排除原因與 content hash lineage；
4. 產生新的 append-only V0.1 development generation，使用相同 frozen Rule／ML policy 重跑比較。

此目標改善 development label correctness，不建立 formal OOS、source acceptance、promotion eligibility 或 production readiness。

## 非目標

- 不取得或接受新的外部 corporate-action source。
- 不把現今公司行動 master 資料倒灌成歷史 PIT 真相。
- 不由價格跳空、成交量或技術指標猜測事件。
- 不改正式 SQLite、Score、Recommendation、Portfolio、Exit、scheduler 或 Rule-only formal path。
- 不調模型 family、feature set、hyperparameter、fold、cost policy 或 selection rule。
- 不讀取 EV3 hard gate 禁止的 2025 outcome payload／return／metric／ranking／report body。
- 不啟動 T6、unblind、promotion、production blend 或交易。

## 資料權威與事件契約

任務第一階段唯讀盤點既有 table、CSV、repository adapter、fixture 與文件，逐一記錄：來源位置、事件類型、symbol、effective/ex-date、announcement/first-observed/available timestamp、調整量或比率、修訂 lineage、coverage 與缺口。只有同時滿足下列條件的來源可成為 V0.1 provider：

- 可辨識證券與事件類型；
- 有歷史 effective/ex-date；
- 有可驗證的 historical availability／first-observed lineage；
- 有完成 label adjustment 所需的整數、`Decimal` 或有理數資料；
- 讀取路徑可保持唯讀，且不依賴目前 UI state。

建議的 domain contract 為不可變 `CorporateActionObservation`，至少包含：

- `symbol`
- `event_kind`
- `effective_date`
- `available_at`
- `adjustment_numerator`／`adjustment_denominator` 或明確 cash amount minor unit
- `source_id`、`source_revision`、`source_payload_hash`
- `quality` 與 `degraded_reasons`

若既有來源無法滿足契約，不得自行補值；provider 回傳 coverage missing，受影響 label window 依本規格排除或維持 `research_only_degraded`。

## 時間與防洩漏語意

- Feature 仍只使用 decision date 當下可得的 T-1 資料；corporate-action outcome 不得進 feature。
- Label 可以處理發生於未來 label horizon 內的真實事件，但 label 的 `available_date` 必須不早於 horizon end 與事件資料實際可得時間兩者的較晚者。
- `available_at` 不明時，不得假設等於 announcement date、effective date 或本次抓取日。
- 事件修訂不得覆寫舊 observation；以新 source revision／content hash append，並保留 supersedes lineage。
- 任何 label 只有在 `label.available_date <= training_as_of` 時才能進 fit。
- 2025 永久維持 `seen_oos`／development-only；2026 matured outcomes 僅可進 evaluation，永不進 fit、normalizer、selection 或調參。

## Label coverage policy

對每個 symbol／label window，coverage engine 產生以下互斥結果：

- `no_event_observed`：來源在該 window 有可驗證 coverage 且無事件，沿用既有 label。
- `adjusted`：事件資料完整，以固定 corporate-action policy 建立調整後 label。
- `excluded_missing_terms`：已觀察事件但缺 adjustment ratio／cash amount 等必要資料。
- `excluded_unknown_availability`：事件 historical availability 不可證明。
- `excluded_source_gap`：來源對該 symbol／date window 無 coverage。
- `excluded_conflict`：同一事件存在未解決的 revision／terms conflict。

所有 accepted、adjusted、excluded rows 必須守恆，manifest 與 diagnostics 分別記錄事件類型與原因計數；不得將 missing／excluded 補成零事件。

## 系統邊界與資料流

```text
Existing read-only corporate-action source
  -> CorporateActionSourceAdapter
  -> CorporateActionCoverageIndex
  -> Terra Dataset label construction
  -> V0.1 manifest / dataset / diagnostics (external append-only root)
  -> unchanged frozen Rule + ML comparison
  -> sanitized ResearchConsoleProjection
  -> read-only UI
```

UI 只呈現 V0.1 projection 中已計算的 coverage、row counts、lineage 與 blockers；不得在 Qt／Application layer 重算 corporate-action adjustment。

## Artifact 與版本規則

- Dataset schema／generation 必須明示 V0.1 corporate-action policy ID 與 policy hash。
- 每次 generation 使用新且唯一的 `generation_id`，禁止覆寫 V0 artifact。
- Manifest 保存 source fingerprints、coverage counts、adjusted/excluded counts、policy hash、content hash、training cutoff 與安全旗標。
- Research report 使用與 V0 相同的 frozen policy；任何差異只可歸因於 dataset／label coverage，而不是模型設定變更。
- Research projection 保持 exact scope `historical_research_seen_development_data`、`formal_oos=false`、整數 `alpha_bp=0`、`promotion_eligible=false`，四個 canonical apply flags 全為 literal `false`。
- V0.1 projection 使用新的 append-only run path；使用者層級 `RESEARCH_CONSOLE_PROJECTION` 必須在驗收後明確改指新檔案，不建立自動目錄掃描。

## 錯誤處理

- 缺 table／file／column：fail closed，輸出 coverage missing diagnostics；不建立正式 schema。
- unknown availability：受影響 window 排除，不猜日期。
- invalid ratio、零分母、非整數 shares 或裸 `float`：拒絕該事件並記錄 deterministic reason。
- conflicting revisions：保留 lineage並排除，直到有明確 authority resolution。
- output root 位於 `DATA_ROOT`、formal DB path 或 generation 已存在：在讀取／訓練前拒絕。
- artifact pair 寫入失敗：使用 staging＋atomic publish，不留下半套 generation／projection。

## 測試策略

實作採 TDD，至少覆蓋：

1. 無事件且 coverage 完整時，V0 與 V0.1 label parity。
2. split／reduction／par-value 事件的 deterministic ratio adjustment。
3. cash distribution terms 完整與缺漏時的 accepted／excluded 行為。
4. 事件在 label horizon 內、外及邊界日的判斷。
5. unknown／late availability 不進提前可用 label。
6. 多事件、revision conflict、零分母與非法數值 fail closed。
7. accepted＋adjusted＋excluded row conservation。
8. manifest policy/source/content hashes 與 persisted dataset parity。
9. 2025 fit／2026 evaluation separation、formal false／alpha 0／apply flags false。
10. 正式 DB hash／mtime 在 generation 與 comparison 前後不變。
11. V0.1 serialized projection 可由真實 `ResearchConsoleSourceService` 讀取，且 UI 不重算 domain logic。

## 完成定義

任務完成必須同時具備：

- 既有 corporate-action source inventory 與 authority／availability 判讀；
- production code、TDD tests、操作文件與資料 lineage 同步；
- 一個非零、append-only 的 V0.1 development generation；
- V0 與 V0.1 coverage／row exclusion 對照；
- 使用相同 frozen Rule／ML policy 的新 comparison report；
- 可由 Research Console 唯讀顯示的新 sanitized projection；
- 正式 DB bytes／mtime 不變的驗證證據；
- `formal_oos_allowed=false`、`production_blend_alpha_bp=0`、Rule-only formal path 與 T5 Forward Clock 不變。

若既有來源完全不具可驗證 historical availability，任務不得偽造 adjusted labels；完成產物改為 authority inventory、fail-closed provider、coverage/exclusion diagnostics 與明確 blocked recommendation，仍不得接新外部來源。
