# Gate 7 ML Shadow Engineering

> **2026-08-30 current correction**：Gate 7 目前仍是 shadow-only；strict validator 以
> cutoff=`2026-08-28T00:00:00+08:00` 重驗且完整 manifest scan 的
> Formal inputs=`0/3`，`formal_oos_allowed=false`、production alpha=`0`、broker／promotion
> disabled。2026-07-30 的「Production Co-pilot／V4.0 覆寫」是當日 engineering freeze 的
> 歷史命名，只表示管線與 fail-closed lane 可日常檢查，不授予正式 OOS 或 V4 product
> closeout。若狀態衝突，以 [Program Status Rebaseline](PROGRAM_STATUS_REBASELINE_2026_08_29.md)
> 與 [Project Snapshot](../00_core/PROJECT_SNAPSHOT.md) 為準。
>
> **歷史 engineering overlay（2026-07-30）**：Gate 7 當時由「價格／技術 shadow challenger」擴充為「全欄位配置型 Production Co-pilot」。該詞只表示資料、訓練、推論、shadow sidecar 與 promotion/rollback lane 的工程入口可執行；不表示已有非零配置權重。截至該次 freeze，reference v2 與逐 horizon metrics artifact 已存在，但 machine gate 仍缺正式 OOS、實際因果投組 replay 及 20 個真實成熟 shadow days，因此 ECE／Brier／PSI 為 `null / NOT EVALUATED`，並輸出 `alpha=0`、`formal_oos_allowed=false`。下方原 shadow 文件保留作歷史底座。

> **Prospective-only 決議（2026-08-14）**：Owner 已確認現有 Portfolio 是測試資料，沒有可追溯的歷史 Formal transitions／Rule snapshots；後續依 [Prospective Formal Simulated Portfolio Execution Plan](PROSPECTIVE_FORMAL_SIMULATED_PORTFOLIO_EXECUTION_PLAN_2026_08_14.md) 建立從未來交易日起算、`real_money=false`／`broker_execution=false` 的正式模擬持倉 clock。既有 model 只能作 frozen research-trained challenger；model／training cutoff／calibration／evaluation identities 必須在 activation 前凍結，同一 clock 禁止以已消費的 Formal OOS period 重訓。此決議不回填 `2014–2026`、不讓新契約靜默通過舊 full-history v1 Gate，也不改變 calibration、20 日、class coverage、promotion authority、alpha 0 或 broker disabled 邊界。

## 2026-07-30 release_v4 全欄位配置工程架構（歷史命名）

資料治理先為每個 SQLite `table.column` 與 file-backed source field 登錄 source、dtype、unit/scale、event/announced/available/first-seen/effective/revision、missing/staleness/quality/license/hash。正式 dataset 契約只允許 `formal_backfill` 與已完成來源／授權驗證的 `first_seen_only`；本次 freeze 的 disposition summary 為 `formal_backfill=52`、`first_seen_only=0`、`research_shadow=32`，shadow 特徵獨立發布。identifier、leakage、blocked provenance 與 unreviewed 全部 fail closed，Wildcard 不得自動進模型。

Feature packs：

1. `price_liquidity_technical`
2. `market_sector_cross_section`
3. `fundamental_growth_quality`
4. `valuation`
5. `flow_chip`
6. `corporate_microstructure`
7. `rule_portfolio_health`
8. `data_quality`

`core_long_history` 保留十年以上正式長歷史；`all_field_enriched` 使用欄位聯集與 missing masks，不因短歷史來源截短；`research_shadow_all_fields` 永遠不進正式 fit。年度 shard 是 deterministic gzip JSONL，不新增 Parquet dependency；SQLite 固定 `mode=ro/query_only`。

### 全種類 Research Challenger（與 Formal 永久隔離）

為避免「沒有正式來源接受」被誤解成「欄位完全沒有進模型」，另設 `research_shadow_challenger_all_fields`。`scripts/build_ml_research_shadow_union.py` 讀取已發布的 `all_field_enriched`、`research_shadow_all_fields` 與正式配置 training manifest；沿用正式列的 T-1 features、causal portfolio state、Teacher targets、horizon labels 與 purge/embargo folds，再按相同 `symbol + decision_at` 追加 `available_at <= decision_at` 的 Shadow feature。所有欄位均有明確 observed／missing／stale／quality-blocked mask；current snapshot 只能從可證明的 `first_seen_at` 往後使用，不能用事件期末日倒灌。

專用訓練入口是 `scripts/train_ml_research_shadow_challenger.py`。union publication 與訓練 manifest 固定：

- `dataset_id=research_shadow_challenger_all_fields`
- `research_only=true`
- `formal_oos_allowed=false`
- `production_alpha_bp=0`
- `promotion_eligible=false`
- `formal_consumer_compatible=false`

Research 訓練 manifest 使用 `allocation-research-training-manifest-v1`，正式 daily orchestrator 只接受正式 training schema 與 `all_field_enriched` identity，因此不能誤載這個 artifact。這條 lane 可以回答 feature-family 增量研究問題，但不能提供 Formal OOS credit、20 日 shadow credit、非零 alpha、Recommendation／Portfolio mutation 或 broker action。

最終 research publication 使用 22,093 筆 official-event post-policy 配置列、2014–2026 年度 shards、150 個顯式 features／8 packs與 4 個 expanding folds。官方事件 manifest hash=`sha256:c6dfdb60a09292452e4fcaa53bc07a7939e7869419ed8d80ce416a9f350dcf17`；`corporate_microstructure` 僅使用 publication-time 可證明且 `result_only=false` 的停復牌／交易限制事件，44,186／88,372 個 feature values observed、coverage=`5,000 bp`，其餘維持 explicit missing。除權息／減資等 result-only 事件不會反推成當時已知。

`research-ledger-769c4d1d3f829df5c7f7c044` 以 T-1 價格 prefix 與前一日 state 遞迴 Rule／Risk Budget／Inverse Volatility baseline；2,533 個決策日中 2,493 日為非現金 state，累積 792 次 add、754 次 reduce，未讀同日 Advice，也未把 Teacher target 餵回 state。其 manifest hash=`sha256:5035af12d40163fb9ddbeeec0539244b39daa20118fedfc841de5e091b73f8cc`、ledger chain hash=`sha256:6aa57a1087bfbfe1e1d018dd6484219c4471468c7510be9db03adb12f150bc6e`。

Final A/B 兩次獨立訓練的 model、audit、manifest bytes 均相同：model hash=`sha256:dd512d6d32d853db151e971e816d514cd81c6b1cbf143289fc719ae41009a705`、audit file hash=`sha256:8a95519bd0f20b2cfabe119f0b91d3a160262f9f02b307ab13d114f370b6eefa`、training manifest file hash=`sha256:ae511983a486317bd8c412934f280ed09e6df0aa3278e9d8ab1183d5d8337d19`、replay hash=`sha256:b7dce1751da79b2269228f6c16b93615a309b3b6b4d173087de3e08392b9764a`。完成 1,137,664 筆 base OOF 與 12,984 筆 meta OOF；family weights 為 `corporate_microstructure=123`、`data_quality=2,893`、`flow_chip=123`、`fundamental_growth_quality=0`、`market_sector_cross_section=2,118`、`price_liquidity_technical=1,771`、`rule_portfolio_health=2,972`、`valuation=0 bp`，嚴格合計 10,000 bp。全資料都沒有 observed 值的 fundamental／valuation pack 權重自動為 0，不以 missing pattern 假造訊號。Canonical research artifact 位於 `ml_research_shadow_challenger_causal_official_events_a`；B 只保留 deterministic 證據。這仍是 research-only 權重學習，不是 Formal OOS、投資有效性或 Promotion 證據；有效 production alpha 仍為 `0`。

歷史產業歸屬只能透過 `pit-sector-membership-sidecar-v1` 進入 assembler：每列必須明確為 `status=accepted`，並帶非空 `source_id`、`license_id` 與合法 `source_hash`；sidecar manifest 必須通過 row count、canonical rows hash 與 canonical manifest hash 重算。`research_shadow`／`rejected`／`unknown`、缺欄、hash tamper、training cutoff 後才 first-seen 的 mapping，以及現行 `companies.csv` 當期快照一律 fail closed，不得倒灌為歷史產業歸屬。

## 模型與 Teacher

- 訓練器輸出 schema 固定為 `allocation-model-artifact-v2`。每個 pack／5、10、20、60 日 horizon／Ridge-Logistic 或 HistGradientBoosting expert 均有 9 個 head：`expected_excess_return_bp`、`expected_sector_excess_return_bp`、`downside_probability_bp`、`predicted_mae_bp`、`predicted_mfe_bp`、`predicted_realized_volatility_bp`、`predicted_max_drawdown_bp`、`predicted_tail_loss_bp`、`fill_feasibility_probability_bp`。
- 每個 expert 送入 Meta Allocator 的固定向量為 19 維：9 個 head、1 個 benchmark `rank_bp`、9 個逐 head missing masks。Artifact base payload 保存 `regression_models`、`classification_models`、`head_fit_row_ids` 與 `head_missing_reasons`；例如缺 PIT-safe 產業 benchmark label 時，sector head 必須是 `model=None` 加明確 reason/mask，不得以 0 假裝已觀測。
- imputer、normalizer 與 calibration 只 fit train fold；HGB 保留 NaN/missing masks。Meta Allocator 只看 base expert 的 OOF prediction。
- Teacher 以 100 bp 格點先滿足硬限制，再比較 20 日成本後 benchmark excess；10 bp 同分依 CVaR、MDD、turnover、集中度排序。
- Paper ledger 按 T-1 因果逐日遞推；未來結果只作 supervised label。驗證至少四個 decision-date expanding folds、purge 60 trading days、embargo 5 days。
- 正式 holdout 只可由 freeze 後第一個交易日開始；已看過的歷史期間不得改名 Formal OOS。

公開 contract 為 `PITFeatureValue`、`PortfolioMLDatasetRow`、`AllocationTargets`、`MLAllocationSignalRow`、`MLAllocationProposal`、`AllocationWeightContract` 與 `PortfolioAllocationResultV2`。公開／持久化／金融決策全部使用 int bp、縮放整數、股數或 `Decimal`；float 只存在 sklearn 邊界。

### 真實模型證據狀態

目前 canonical official-event post-policy training 涵蓋 11 symbols、22,093 rows 與 4 個 expanding outer folds，並產生 426,624 筆 base OOF predictions、12,984 筆 meta OOF predictions。這證明 `allocation-model-artifact-v2` 的 training／OOF／Meta 管線實際執行完成，不等於 Formal OOS lane 已評估。正式 compact model artifact hash 為 `sha256:92668aa574967990fa560aef8a48e595296eb22f3fef2a4264cff08210d78b6d`，replay hash 為 `sha256:ba0eb2456569d55d5981d97b612f109818c4acc01881e07ca9d1d6bf2042092d`。

| Promotion 證據 | 本次 freeze 狀態 |
|---|---|
| Calibration ECE／calibrated Brier | `NOT EVALUATED` |
| PSI drift | `NOT EVALUATED` |
| 四個以上 Formal OOS folds／成本後勝 Rule fold 數 | `NOT EVALUATED`（engineering training 的 4 folds 不是此項 promotion 結論） |
| Block-bootstrap 95% 超額報酬下界 | `NOT EVALUATED` |
| core／enriched／feasible-fill coverage | `NOT EVALUATED` |
| MDD／CVaR／weekly turnover | `NOT EVALUATED` |
| 20 個真實 shadow trading days | `NOT EVALUATED` |

`allocation-model-artifact-v2`、head masks、OOF 隔離與上述 bounded actual training 是工程／訓練管線證據，不是表內投資或 promotion 指標。沒有一組完整、可信 custody 下的正式證據前，Formal ECE／Brier、PSI 與 alpha OOS lane comparison 均維持 `NOT EVALUATED`，`formal_oos_allowed=false`、有效 alpha 為 0。

### Formal replay semantic gate

OOS replay producer／consumer 已能從 hash-bound execution ledger 逐日重算現金、持股、買賣成本、turnover、隔夜報酬、closing value 與 state chain；缺決策日、持倉股票缺實際 bar、價格或 lineage tamper 都會 fail closed。這只證明帳務 replay 可重算，不自動證明該持倉是當時正式部署語意的輸出。

目前每份完成的 engineering replay 都明確保存：

- `formal_semantic_validation.schema_version=allocation-oos-semantic-verification.v1`
- `formal_semantic_validation.verifier_id=allocation-oos-semantic-verifier-v1`
- `formal_semantic_validation.verified=false`
- `promotion_eligible_input=false`

其 blockers 固定揭露尚未由獨立 verifier 完成的四件事：官方交易日曆 custody、production Rule Champion replay、完整六頭 Meta OOF 投影，以及 promotion consumer 對 retro raw derivation 的獨立重算。Promotion Builder 還會重驗 Meta OOF artifact 的六個 target fields、shape／dtype／byte count 與 fold identities，且有效 Meta OOF folds 少於 4 個即拒絕。Cash-only 訓練 portfolio state 不得在 replay 階段事後重建成非現金狀態；舊資料若缺這項語意證據只能重訓，不能靠 sidecar 升格。

Daily Shadow observation 仍可 append 與 idempotent 重跑，但目前因正式 Rule weight snapshot 及 sector／thesis／health context custody 不完整，保存 `promotion_day_credit_allowed=false`；彙總器只計算明確為 true 的 observation/outcome。這避免以 current holdings 冒充 Rule baseline，或用成功執行的工程 observation 灌滿 20 日門檻。

## Rule/ML 混合與硬風控

每個 symbol 與 cash 使用：

```text
numerator = (10000 - alpha) * rule_weight_bp + alpha * ml_weight_bp
```

先整數商，再用 largest remainder 配完剩餘 bp；同餘數按股票代碼排序。混合後依序投影 Health/Exit、cash `>=2000 bp`、最多 8 檔、單檔 `<=1500 bp`、產業 `<=3000 bp`、買量 `<=T-1 20日中位量 5%`、weekly turnover `<=2000 bp`、band `300 bp`、minimum trade `200 bp`、cooldown 5 日、整張 1,000 股與買/賣成本 25/55 bp。不可行時依 `all_field_enriched → core_long_history → Rule/Risk Budget/Inverse Volatility → 100% cash` fail closed。

`CausalPortfolioState` 是可執行配置前置條件，不是可選提示。它必須由 T-1 Paper ledger 建立，包含嚴格早於 decision date 的 `as_of_date`、總和 10,000 bp 的 `AllocationWeightContract`、完整且 canonical sort 的現有持倉 symbol universe，以及內容 hash。Portfolio consumer 會逐檔比對 context `current_weight_bp`、state weight 與 cash；缺 state、漏掉既有持倉、日期不嚴格在前、cash／context 不一致或 10,000 bp 不守恆時，仍可產生唯讀 target 診斷，但 `executable_weights=null` 且 Advice 固定 `NO_NEW_POSITION`。

## Promotion 與每日 runner

`scripts/build_ml_revalidation_runbook.py --trigger production_promotion` 產生 12-step runbook。正式每日鏈固定為 05:17 `run_ml_promotion_evidence_pipeline.py`（unsigned evidence）→ 05:18 `run_ml_promotion_authority.py`（DPAPI-protected independent authorization）→ 05:20 `run_daily_ml_allocation_orchestration.py`（四 lane inference／consumer revalidation）。Builder 不簽章、Authority 不訓練模型、Co-pilot 不接受人工作業環境變數繞過固定 custody。

### 凍結 Promotion Reference 與每日 Evidence Collector

`scripts/build_ml_allocation_promotion_reference.py` 會從 hash-bound frozen training dataset 與 model 產生 versioned calibration／PSI reference。2026-07-30 canonical reference v2 使用 22,093 rows、62 features／3 formal families，reference hash=`sha256:8ee81ae9c5691c6e10d95f14eac293b2ecd121a53877f0d0de73e20b514dd5b0`、file hash=`sha256:d02ab09f8cfa19449b7524d4ca12139a9e27e55b2f4d78f70cbc1be15821800f`，並綁定 model `92668a…`、dataset identity `f7ed2f…`、promotion policy `b19636…` 與 outcome contract `sha256:95172f7d8678fd6ecde83c1c166b56878b0d3b769750290acb5b0b3753c96a11`。Reference 分別保存 5／10／20／60 日 calibrated／uncalibrated downside probability baseline、逐 feature frozen bins 與 family coverage bins；current observation 不能回寫或取代 frozen reference，hash／schema／custody 任一不符即 fail closed。

Daily orchestrator 以 strict T-1 post-freeze rows、當日 proposal 與同一 frozen model 建立 promotion observation；每列分別保存 5／10／20／60 日 calibrated／uncalibrated downside probability 與 current feature/family distribution。Outcome 只採每檔下一可交易 OPEN 至第 h 個 session CLOSE、同區間 TAIEX，並扣買入 25 bp／賣出 55 bp；價格列、availability、revision、calendar 與公司行動 publication 均納入 hash，缺一即 fail closed。四條 `0 / 2000 / 3500 / 5000 bp` lane、Paper ledger current state、風控投影結果及完整 Why／Why Not Advice 另存於 `shadow_evidence_collector` 的 append-only SQLite／immutable JSON。相同 decision date + custody 為 idempotent；custody 修訂會 append 新 revision，但成熟日數與 outcome denominator 只取每個 decision date 的最新 revision，不會因重跑灌水。

2026-07-31 canonical run 在 reference v2 下重驗後，最新 observation revision=7；reference metrics hash=`sha256:607adf7b48f4210809ee2f31d355d3adfef56027cb0d7d6322db3fd02dda750d`、shadow evidence hash=`sha256:82332fb24eb62dcf2018e8d940d9f7e4faa21dd83a5e9bd48990dbd2d6d36669`。Latest observation 明確為 `promotion_day_credit_allowed=false`，fully matured outcome=0；5／10／20／60 日可計入 promotion 的天數各為 `0/20`。

成熟後 evaluator 才逐 horizon 使用 post-decision actual downside 計算 ECE、calibrated Brier、uncalibrated Brier、feature PSI 與 family PSI。任一 horizon 未滿 20 個唯一成熟交易日時，這些 metrics 固定為 `null / NOT EVALUATED`，reference 狀態仍為 `ready`，blocker 格式為 `matured_shadow_days_insufficient:h<horizon>:<n>/20`；不能用 0 冒充指標。20 日後仍須和 PIT、兩次獨立 formal OOS replay、lane 成本後比較、drawdown/CVaR、coverage、turnover 等其餘 machine gates 一起通過，才可能選出非零 alpha。

非零 alpha 的 consumer 驗證必須同時通過：

1. 05:18 Authority 由 Windows user-scope DPAPI secret 載入 issuer key，05:20 consumer 只讀固定 authority pointer；trusted custody roots 與 `custody_id` 必須符合固定 release policy。顯式部署 trust 設定只可縮小或替換受信任邊界，不能注入 promotion artifact 或繞過 fixed pointer。
2. authorization 簽章、artifact hash、registry revision id/hash 與 decision window；`issued_at` 不得晚於 decision，`frozen_at` 不得晚於 issuance 或 decision，有效窗不得超過 verifier 上限。
3. evidence、model artifact、dataset manifest、OOF bundle、shadow evidence 與 registry revision 實體檔都位於可信 root，路徑互異，且重新計算的 SHA-256 與 authorization/evidence identity 完全一致。
4. `AllocationPromotionEvaluator` 重新計算後選出的 lane 必須等於 request alpha；request 的非零 `alpha_bp` 本身不具授權力。缺少 decision/model/dataset context 的低階 blend API 永遠回 Rule-only。
5. Authorization 的 model／dataset 必須與當次真正執行 inference 的 release 完全相同；其他模型即使取得完整 evidence 也不能授權目前 proposal。

可正常解析但缺件，或簽章、路徑、時效、freeze、registry、identity、policy、實體 hash、threshold 任一驗證不通過時，runner 安全完成為 `passed_rule_only`，有效 alpha 原子回退 0。若部署端信任設定本身格式錯誤或 custody root 無效，task 可明確失敗，但仍不得產生非零 alpha、portfolio mutation 或 broker action。禁止手動設定 `formal_oos_allowed` 或繞過 consumer re-verification。

> **2026-07-30 歷史 engineering snapshot**：當時稱 Production Co-pilot 的資料、訓練器、推論、四 lane、unsigned builder、DPAPI Authority、consumer custody 與 rollback 工程路徑可日常執行；canonical 11-symbol official-event training 已完成 22,093 rows／4 folds／426,624 base OOF／12,984 meta OOF。這是 Rule／ML shadow engineering 能力，不是 current production maturity。Current truth 固定回到本文件頂部：Formal inputs=`0/3`、Formal ECE／PSI／OOS lane=`NOT EVALUATED`、`formal_oos_allowed=false`、alpha 0、promotion／broker disabled。

2026-08-14 以現有 test fixtures 完成 formal downstream wiring 回歸：OOS replay／promotion pipeline `30 passed`、promotion evidence/reference/validation `53 passed`、copilot／portfolio consumer `31 passed`。三項正式 custody 到位後，正式執行順序固定為 `build_allocation_oos_replay_inputs()`、primary／verification identical result hash，再進入 promotion evidence；測試 fixture 不會被發布為正式 evidence。

> **Agent 接手導覽**：工程切片與驗證證據見 [Pure Engineering Closeout](GATE_2_TO_7_PURE_ENGINEERING_CLOSEOUT_2026_07_12.md)；待辦狀態以 [External Validation Register](GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md) 為準；append-only 更新方式見 [Engineering Control Center](GATE_2_TO_7_ENGINEERING_CONTROL_CENTER.md)。

Gate 7 使用隔離的 `ml_module/` 建立結構化傳統 ML challenger。此工程不取代 rule-generated signals、不修改推薦 threshold、不接 production scheduler、不產生交易建議，也不具有 production eligibility。

## Frozen dataset manifest

每個訓練資料集必須先建立 immutable manifest，記錄 dataset id、決策日期範圍、row count、feature/label schema、source versions、content hash 與 manifest hash。所有 feature 與 label 欄位都必須具有 available-date contract。Manifest registry 採 append-only；相同 dataset id 不可覆寫。

## Available-date boundary

Feature 必須滿足 `feature.available_date <= row.decision_date`。Label 可以在決策日之後成熟，但訓練時必須是 `ready` 且 `label.available_date <= training_as_of`。Future decision rows、future features、pending labels 與 cutoff 後才可得的 labels 全部隔離並保留 diagnostics。

## Purged walk-forward

模型驗證使用 expanding walk-forward，不使用 random shuffle/K-fold。每個 fold 的 train decision dates 早於 test，且 train label end 不得跨入 test start；test blocks 之間保留明確 embargo。Fold 生成對未來資料保持 prefix invariance。

## Boosted challengers

第一組完整 challenger 使用 scikit-learn histogram gradient boosting：regressor 同時提供 future return bp prediction 與 ranking score，classifier 提供 downside probability。訓練要求 feature shape 一致、有限值、至少十列及 downside 兩類樣本。Bundle 固定 `shadow_only=true`、`production_eligible=false`；float 僅存在 `ml_module` 模型邊界。

## Probability calibration

Downside probability 使用 isotonic calibration，且 calibration input 必須來自至少兩個 walk-forward out-of-fold blocks。校準拒絕樣本不足、單一 label class、非有限值或超出 0..1 的 raw probability。Calibrator 固定 shadow-only，不提供 production eligibility。

既有 OOC run 可用 `scripts/audit_existing_ooc_calibration.py --training-manifest <training-manifest> --output <shadow-audit.json>` 做完整 artifact hash 重驗與 cross-fitted calibration 重算；此命令為唯讀診斷，不改寫 training manifest、不寫入正式 SQLite，也不建立 promotion-compatible pointer。`quality_pass` 或 calibration 通過不會單獨解除 formal OOS、alpha 或 broker gate。

2026-08-14 起 audit report 的每個 calibration horizon 另保存 `horizon_trading_days`（5／10／20／60），不再依賴陣列順序判讀 ECE／Brier；此為觀測契約修正，不改變 calibration 數值、training artifact 或 promotion gate。

2026-08-15 的 PFS-05 另建立 `prospective-formal-inference-calibration-policy.v1` 與 shadow audit：正式 inference calibration 必須並列 `identity`／`isotonic_integer_bp`，每個 target fold 只能使用完整 prior validation folds，5／10／20／60 日採 conservative max，ECE 門檻固定 `500 bp`，且 `rebalance_worthwhile` 必須自然具備 class 0／1。policy hash 綁定 clock／model／dataset identity；isotonic 若 ECE／Brier 不優於 identity、任何 horizon 缺 class coverage 或 only class 0，audit 維持 blocked，不可事後改選 method、attach calibrator、產生非零 alpha 或解除 Formal Gate。

2026-08-15 的 PFS-06 capture-only readiness 只驗證 clock-bound policy、prospective ledger wrapper、Rule history 與 PIT sidecar 的完整 custody；即使三項均 ready，readiness 仍固定 `capture_only=true`、`heavy_rebuild_launch_allowed=false`，不會自動呼叫 Direct/OOC。未經 PFS-07 owner activation 與未來交易日選定，不設定正式 Windows paths、不計 elapsed day、不產生 Formal OOS 或 promotion credit。

2026-08-15 的 PFS-07 activation contract 將 PFS-06 readiness hash、candidate／feature／training cutoff、calibration／evaluation／universe／source／seed identities 與三個 controlled path 的 file hash 綁成 create-only manifest；只接受 owner activation timestamp 已發生、activation trading day 仍在未來、controlled store id 與 secret-store configured flag 已就緒的 schedule。低 CPU daily start record 只固定蒐證順序與 zero-credit flags，仍不設定 Windows paths、不讀 HMAC secret、不啟動 watcher／Direct／OOC；下一個 Gate 是 PFS-08 的真實 elapsed trading days 與 matured outcomes。

2026-08-15 的 PFS-08 shadow maturity gate 只接受 activation 後的 complete observation 與已成熟 integer-bp outcomes，重新驗證 T-1 input、clock／activation／source lineage hashes、unique sorted capture dates 與 no-replay／no-backfill flags。至少 20 個 shadow days、每個 5／10／20／60 horizon 至少 20 個 matured observations 且 `rebalance_worthwhile` 雙類別自然覆蓋後，才回報 `maturity_gate_ready_shadow_only`；這仍不授權 Formal OOS、promotion、alpha 或 broker，下一步才是 PFS-09 frozen-candidate replay／calibration／PSI。

單日 observation 的受控入口為 `scripts/capture_prospective_shadow_observation.py --fixture-only`；它只組合 activation-bound producer hashes、T-1 與 caller 已提供的 matured outcome rows，沿用同一 PFS-08 validator 並 create-only 寫出，不能用來回填 2014–2026 或補足缺失日期。

2026-08-15 的 PFS-09 frozen-candidate OOS evidence 只綁定外部完成的 primary／verification replay、inference calibration audit 與 integer-bp PSI report；兩次 replay 的 identity／result hash 必須一致，且 fit／retrain／post-outcome method selection 全為 false。缺件、identity mismatch 或 quality failure 都只留下 blockers；即使 package `ready_for_formal_review`，仍固定 `formal_oos_allowed=false`、alpha=`0`、promotion=`false`，下一步才是 PFS-10 review authority。

2026-08-15 的 PFS-10 promotion review package 只聚合 machine gates 與 owner-review metadata；10 個 machine gates 全 true 時最多回報 `ready_for_owner_review`，仍固定 owner authorization false、`promotion_eligible=false`、`formal_oos_allowed=false`、alpha=`0`、broker disabled。程式面 PFS-01～PFS-10 已完成，執行面不會自行選 activation date、設定正式 path 或啟動 watcher，等待 owner 的受控 prospective decision。

Execution handoff 另由 `scripts/inspect_prospective_activation_environment.py` 唯讀檢查
Windows user/system registry：目前三個 formal path 都 missing；controlled store／HMAC
configured flag 只以布林值回報，secret 不會出現在 stdout、JSON、repo、command line 或
log。未來 paths 尚未全部存在前，不能執行 activation CLI，也不能把既有 research／
fixture artifacts 放入 formal path。Owner 設定 paths 後，
`scripts/inspect_prospective_capture_readiness.py --controlled-environment` 可用明確
opt-in 把同一 controlled reader 的三條路徑交給 PFS-06 schema／hash／T-1／lineage
驗證；這個命令仍只做 capture-only preflight，不寫環境、不讀 HMAC secret、不啟動
watcher／Direct／OOC，任何 missing／invalid 都維持 formal OOS blocked。PFS-07
activation CLI 也支援 `--fixture-only --controlled-environment`，只取非秘密 store
identity 與 HMAC configured flag，並把 path/file hash 再交給 immutable activation
validator；它不自行選日期、不建立歷史 credit，也不啟動 ML。

2026-08-14 起 `maintain_ml_direct_v3_refresh_chain.py --watch-formal-inputs` 會在 polling
時重新讀取 Windows 使用者／系統環境的受控 formal path、PIT sector path、Rule HMAC key
與 store id，補足
長駐 process 的啟動時 environment snapshot 限制。刷新只存在目前 process memory，變數 value
不會寫入檔案、command line、status 或 log；移除 watcher 自己採用的 registry value 會清除
該 process 內的 adopted value，並維持 schema／hash／cutoff／HMAC／formal gate 的原有
fail-closed 驗證。此為 custody handoff observability／runtime contract，未放寬任何 promotion、
alpha 或 broker 條件。

獨立 readiness inspector 也共用這個受控 Windows environment handoff：它可接收 watcher 啟動後才出現的 owner deposit，但只更新當前 read-only process memory，仍不會寫入 artifact、source DB 或任何 secret-bearing status。

2026-08-14 另完成既有 OOC calibration 的唯讀 scope split：984 個 base OOF experts 分成
492 個 `ridge_logistic` 與 492 個 `hist_gradient_boosting` 後，兩組在 5／10／20／60 日
horizon 仍全部 `quality_pass=false`；combined 最大 ECE=`2,627 bp`，ridge 最大
ECE=`2,668 bp`，HGB 最大 ECE=`2,683 bp`，均高於 `500 bp`。因此高 ECE 不是單純由
跨模型混合造成的 indexing／reporting 假象；calibration 仍是 shadow diagnostic，
不放寬 threshold，也不把未 attached 的 calibrator 當成 production evidence。

## Model and prediction registries

Model registry append-only 保存 model/dataset id、feature list、artifact path/hash、calibration id 與固定 `shadow_candidate` lifecycle。Prediction registry append-only 保存 symbol、decision/available date、return/ranking/downside outputs；future-available 或非有限值會被拒絕。兩者皆無 production action eligibility。

## Drift and champion comparison

Feature drift 使用 frozen baseline quantile bins 計算 PSI，分成 stable、moderate 與 major drift；任何狀態都不會自動 retrain。Champion comparison 強制使用同一組 unique matured samples，比較 Precision@K、challenger return MAE 與 downside Brier；結果只提供 direction review，`auto_promotion_allowed=false`。

## Rollback and promotion review

`scripts/build_ml_promotion_review.py` 產生非套用型 review package。需要最低 shadow days、可審查 comparison、無 major drift、calibration passed、rollback artifact 與 verification artifacts；否則 `defer`。最高狀態只有 `eligible_for_human_review`，固定 `apply_promotion=false`、`auto_promotion_allowed=false`、`production_scheduler_allowed=false`。

## Static shadow boundary

`scripts/check_ml_shadow_boundary.py` 以 AST 檢查 production packages 不得 import `ml_module`，`ml_module` 不得 import Advice/Decision/Portfolio/UI/runtime/backtest 路徑，且不得把 production/promotion/trading flags 設為 true。違反時 CLI exit 1。
