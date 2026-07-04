# V1.5 Data Credibility & Corporate Action Gate Design

> 日期：2026-07-04  
> 範圍：Data Source Capability Registry、corporate action / adjusted price policy、microstructure governed source preflight、evidence source coverage 分級  
> 狀態：設計稿，供本輪 V1.5 closeout 實作使用

## 目標

V1.5 的目標是把 Post-V1 evidence 與 replay 所依賴的資料可信度邊界補成可檢查、可回溯、可降級的治理層。這一版不新增交易模型、不改 `ScoringEngine`、不啟用 production evidence write-mode scheduler，也不重建或改寫正式 `DATA_ROOT` 原始資料。

V1.5 完成後，系統應能回答四個問題：

1. 每個資料來源能提供哪些欄位、延遲多久、品質如何、缺資料時如何處理。
2. 價格序列目前採用 raw / adjusted / candidate adjusted 哪一種政策，以及哪些 corporate action 欄位尚未具備正式可得日。
3. 推薦組合 replay 的處置股、分盤、全額交割、漲跌停鎖死與除權息檢查是否有 governed source metadata，而不是只看 DataFrame 是否剛好有欄位。
4. Evidence source coverage 的 blocking gap 與 non-blocking warning 是否一致，避免 optional payload 被誤解為 production readiness。

## Scope In

- 新增 `DataSourceCapabilityRegistry`，以程式碼內建 registry 保存 V1.5 P0 source capability。v1 只提供 read-only inspection，不寫 production DB。
- 新增 corporate action / adjusted price policy inspection，明確標示 raw price、decision-date adjusted candidate 與 full hindsight adjusted 的使用邊界。
- 新增 microstructure source preflight helper，將處置股、分盤、全額交割、漲跌停鎖死與除權息來源納入 governed metadata。
- 將 evidence source coverage 統一成 application service，讓 CLI、runner 與 scheduler readiness 共用同一份 gap / warning 分級。
- 更新測試與文件，將 V1.5 closeout 記錄到 Snapshot、6M Roadmap、Version Roadmap、Architecture、Manual 與 QA 摘要。

## Scope Out

- 不新增或修改正式資料表內容。
- 不從外部網站抓 corporate action 或處置股資料。
- 不把三大法人、信用交易、TDCC 或 concept basket 接入 factor pipeline。
- 不把 Why Not / Liquidity negative evidence 做成完整 Screening Matrix；那是 V1.7。
- 不自動 promote / demote / retire 策略版本。
- 不輸出交易建議或投資有效性結論。

## 架構

### Data Source Capability Registry

新增 `data_module/data_source_capability_registry.py`。核心 DTO：

- `DataSourceCapability`
- `DataSourceField`
- `DataSourceCapabilityRegistry`
- `inspect_data_source_capabilities()`

欄位包含：

- `source_id`
- `source_name`
- `source_type`
- `status`：`ready` / `partial` / `planned` / `deferred`
- `coverage_scope`
- `available_date_policy`
- `latency_policy`
- `quality_policy`
- `missing_policy`
- `license_note`
- `rate_limit_note`
- `backfill_policy`
- `fields`
- `warnings`

v1 內建 P0 source：

- `twse.daily_prices.raw`
- `tpex.daily_prices.raw`
- `sqlite.daily_prices`
- `recommendation.persisted_result`
- `recommendation.exclusion.why_not_payload`
- `recommendation.exclusion.liquidity_gate_payload`
- `decision_desk.snapshot.watchlist_trigger`
- `decision_desk.snapshot.portfolio_alert`
- `decision_desk.snapshot.risk_prompt`
- `corporate_action.ex_dividend_timeline`
- `microstructure.disposition_stock`
- `microstructure.periodic_call_auction`
- `microstructure.full_delivery`
- `microstructure.limit_lock`

### Corporate Action Policy

新增 `data_module/corporate_action_policy.py` 與 CLI `scripts/inspect_corporate_action_policy.py`。v1 不產生 adjusted price，只保存政策：

- Raw price 是目前 decision layer 的預設。
- Full hindsight adjusted price 不得用於回測決策特徵。
- Decision-date adjusted candidate 只有在 source capability 具備 `available_date <= decision_date` 時可進後續設計。
- corporate action table candidate 只作設計輸出，不建立 migration。

### Microstructure Governed Preflight

新增 `data_module/microstructure_source_preflight.py`，並讓 `RecommendationPortfolioBacktestService._build_microstructure_preflight()` 使用它輸出：

- `governed_sources`
- `source_capability_status`
- `missing_sources`
- `risk_count`
- `risks`

此改動只增加 metadata，不改 PnL、成交價、cash ledger、sizing 或 Research Run lifecycle。

### Evidence Source Coverage

新增 `app_module/evidence_source_coverage_service.py`，統一目前散落在 CLI、pipeline runner 與 scheduler readiness evaluator 的 source coverage 判斷。分級規則：

- `recommendation_persisted_missing`、`decision_desk_snapshot_missing`、watchlist / portfolio / risk prompt section missing 是 blocking gap。
- why-not / liquidity payload missing 是 warning，因為 V1.5 只承認 optional / partial payload；完整 negative evidence 是 V1.7。
- readiness 最高仍只到 `ready_for_design` 或後續 runner 的 `ready_for_manual_confirm`，不得輸出 production-ready。

## Look-ahead 自查

- Registry 與 policy inspection 不讀未來資料，不回填正式 DB。
- Microstructure preflight 只檢查 replay snapshot 的 `as_of_date` 當日 rows 與該日欄位，不使用後續日期判斷。
- Corporate action policy 明確禁止 full hindsight adjusted price 進入決策特徵。
- Evidence source coverage 只看已保存 durable source，不 fallback UI state，不重算 Why Not / Liquidity Gate。

## 測試策略

- 新增 registry 單元測試，確認 P0 sources、狀態、欄位與 JSON/Markdown inspection。
- 新增 corporate action policy 測試，確認 forbidden / allowed price policy 與 table candidate。
- 新增 microstructure preflight 測試，確認 governed source metadata 與既有風險偵測不退化。
- 新增 evidence source coverage service 測試，確認 warning / blocking gap 分級與既有 CLI 輸出。
- 執行 focused pytest、py_compile、quant guard；若 UI 未修改，不跑 Update Tab 強制 UI QA。

## 文件更新

完成實作後同步：

- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md`
- `docs/00_core/DEVELOPMENT_ROADMAP.md`
- `docs/01_architecture/system_architecture.md`
- `docs/07_guides/APPLICATION_MANUAL.md`
- `docs/06_qa/` 新增 V1.5 QA closeout 摘要
- `docs/00_core/DOCUMENTATION_INDEX.md` 若新增 QA / design 文件需索引

## 驗收 Gate

- V1.5 source capability registry 可由 CLI 唯讀檢查。
- Corporate action policy 明確標示 raw / adjusted policy 邊界。
- Recommendation replay microstructure preflight 帶出 governed source metadata。
- Evidence source coverage 分級一致，payload partial 不再被包裝成 production readiness。
- focused tests、py_compile、quant guard 通過。
- 相關文件已更新後才允許最後 push。
