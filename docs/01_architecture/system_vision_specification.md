# baldr 系統願景規格

> **最後更新**：2026-07-11
> **目前成功層級**：`V3.3 Engineering Complete` 只表示工程入口可運作、驗證、追溯與回滾；Evidence Accumulation Track 不等同投資有效性或正式 V4.0。
> **定位**：本文件是 baldr 的 North Star、Product Principles、Bounded Advice Policy、Evidence Requirements、Success Levels 與 Non-goals 權威。
> **不保存**：目前完成流水帳、詳細工程 checklist、外部專案清單或現況架構細節。
> **Scoped SSOT**：目前狀態看 [PROJECT_SNAPSHOT.md](../00_core/PROJECT_SNAPSHOT.md)；產品演進看 [PRODUCT_ROADMAP_POST_REFACTOR.md](../00_core/PRODUCT_ROADMAP_POST_REFACTOR.md)；六個月工程 Gate 看 [ROADMAP_6M_ENGINEERING.md](../00_core/ROADMAP_6M_ENGINEERING.md)；目前架構看 [system_architecture.md](system_architecture.md)；目標架構看 [target_system_architecture.md](target_system_architecture.md)。

---

## 1. North Star

baldr 是一套可以觀察台股市場、篩選候選股票、產生結構化投資建議、建立建議投資組合、追蹤持倉健康、協助加減碼與退出判斷，並持續驗證自身建議是否有效的投資決策系統。

baldr 的目的不是產生最多分數、報表或功能，而是讓使用者能持續做出：

- 資料可追溯的決策。
- 風險與反對理由可見的決策。
- 權重與資金限制明確的決策。
- 事後可驗證、可修正、可停止使用的決策。

## 2. 每日核心問題

系統每天應回答：

1. 現在市場處於什麼狀態，是否適合新增風險？
2. 哪些產業、題材與股票值得研究，哪些應避免？
3. 哪些候選適合列為建立部位候選，理由與反對理由是什麼？
4. 建議 Portfolio 的目標權重、目前權重與差距是多少？
5. 現有持倉應加碼、持有、減碼或退出嗎？
6. Recommendation、Portfolio、Alert 與 Exit 建議後來是否有效？
7. 哪些 signal、gate、feature、Profile 或模型應保留、限制、降權或退休？

## 3. Product Principles

### 3.1 Decision First

資料、回測、模型與 UI 必須服務於市場、候選、Portfolio、持倉與改善決策，不以工程完成度作產品終點。

### 3.2 Bounded, Not Black-box

系統可以提供有界結構化投資建議，但每筆建議必須有條件、證據、風險、資料日期、策略版本、失效條件與可成交性。黑箱自然語言或單一分數不得取代核心規則。

### 3.3 Evidence Before Promotion

工程完成、historical replay、read-only UI、dry-run、candidate source 或 ML readiness 都不等於投資有效。Promotion 必須經 OOS、forward / paper evidence、成本、風險與人工 review。

### 3.4 Portfolio Before Isolated Picks

推薦股票不是產品終點。系統必須考慮總曝險、現金、單股／產業／題材／相關性限制、流動性、成本、target/current/gap 與 rebalance bands。

### 3.5 Thesis Before Mechanical Exit

退出不只依固定停損、RSI 或 TotalScore。持倉健康需同時考慮 Hard Risk、Entry Thesis、Relative Deterioration、Time Stop、Portfolio Rebalance、Data Quality 與 Trading Restriction。

### 3.6 Point-in-time by Default

任何 Recommendation、Backtest、Portfolio、Exit、模型或 benchmark 只能使用決策當下可得資料。無法證明 available-date 的資料不得進 formal decision layer。

### 3.7 Simpler Baseline Earns Priority

Equal Weight、規則排名與簡單風險政策是正式 benchmark。複雜 optimizer、ML 或 DL 只有在相同資料、成本、限制與 OOS 條件下證明穩定增益後才可 Promotion。

### 3.8 Pruning Is a Product Capability

系統不只新增功能，也要能限制、降權、隱藏或退休無效 signal、gate、alert、feature、Profile 與 model，同時保留歷史 evidence 與 rollback。

### 3.9 Degrade Honestly

缺資料、來源過期、樣本不足或執行不可行時，系統應輸出 MISSING / DEGRADED、`RESEARCH`、`AVOID` 或 `NO_NEW_POSITION`，不得補成 observed 或硬湊建議。

## 4. Bounded Advice Policy

### 4.1 允許的建議

- `RESEARCH`
- `ADD_CANDIDATE`
- `HOLD`
- `REDUCE_CANDIDATE`
- `EXIT_CANDIDATE`
- `AVOID`
- `NO_NEW_POSITION`

### 4.2 每筆建議的最低內容

- 建議原因與反對理由。
- 主要風險與資料品質。
- Evidence tier 與 confidence tier。
- 建議目標權重、目前權重與權重差距。
- Entry thesis 與 invalidation conditions。
- 預期持有期間與 review date。
- Market regime、liquidity state 與 execution feasibility。
- Strategy / policy version、decision date 與 data-as-of date。

### 4.3 建議與執行的硬邊界

```text
Investment Advice
≠
Broker Execution
```

baldr 不自動送單、不自動平倉、不控制券商帳戶。即使輸出 `ADD_CANDIDATE` 或 `EXIT_CANDIDATE`，仍由使用者決定是否執行、何時執行與如何處理成交差異。

### 4.4 Confidence 邊界

Confidence tier 代表證據完整度、校準狀態與適用範圍，不是保證勝率。AI 文字信心不得成為 statistical confidence。

## 5. Guided Mode 與 Professional Mode

### Guided Mode

只使用通過 Promotion Gate、參數鎖定、evidence disclosure 完整的正式策略。使用者選擇投資週期、風險容忍度、資金、小型股／低流動性接受度與最大持倉數；系統產生受限 Advice、Portfolio target 與 Position Health。

### Professional Mode

允許 Candidate Profile、factor / threshold / horizon / SLTP / sizing 實驗，以及 ablation、robustness、walk-forward、execution realism、shadow testing。未經 Promotion 的結果不得進 Guided Mode。

兩種模式必須共用 Recommendation、Portfolio、Evidence、Advice Policy 與資料治理核心，只以可見設定、策略狀態與 permission 區隔。

## 6. Portfolio Advice Policy

Portfolio Advice 至少包含：

```text
stock_code
advice_action
target_weight_bp
current_weight_bp
weight_gap_bp
confidence_tier
evidence_tier
holding_horizon
entry_thesis
invalidation_conditions
market_regime
strategy_version
liquidity_state
execution_feasibility
risk_reasons
data_quality
review_date
```

Portfolio policy 必須治理總曝險、現金、單股、產業／題材、高相關股票、小型股／低流動性、目標波動、最大回撤、turnover 與交易成本。

Equal Weight 是 sizing benchmark。Score Weight、Inverse Volatility、Risk Budgeting 與 Confidence-adjusted Weight 都要通過 OOS、forward / paper evidence 與成本比較；不得假設分數高就一定配置更多。

Rebalance 必須使用 lower / target / upper bands、minimum trade threshold、turnover budget 與 cooldown，避免微小偏差造成每日交易。

## 7. Position Health / Exit Policy

狀態機：

```text
HEALTHY → WATCH → REDUCE_CANDIDATE → EXIT_CANDIDATE → CLOSED
```

狀態轉移來源：

1. Hard Risk。
2. Entry Thesis Invalidated。
3. Relative Deterioration。
4. Time Stop。
5. Portfolio-level Rebalance。
6. Data Quality Degradation。
7. Trading Restriction。

每次 transition 必須保存 reason category、source trace、data quality、evidence link、review date 與人工 override。Exit 仍是 Candidate advice，不是自動平倉。

## 8. Evidence Requirements

### 8.1 證據層級

| Evidence | 可支持的結論 | 不可支持的結論 |
|---|---|---|
| Historical replay | source / payload / workflow gap、研究方向 | 真實 forward effectiveness |
| IS backtest | 假設形成與工程檢查 | Promotion |
| OOS / walk-forward | 研究可信度與 robustness | 實盤可成交績效 |
| Shadow recommendation | challenger 比較 | 正式 Advice |
| Forward evidence | 決策日後 outcome | 完整 Portfolio 執行效果 |
| Paper Portfolio | 配置、成本、限制與 execution gap | 真實帳戶績效 |
| Live review | 實際 fill、override、journal 與 research gap | 保證未來結果 |

### 8.2 Recommendation Evidence

- Forward return。
- Benchmark、industry、concept excess return。
- MAE、MFE、hit rate、payoff ratio。
- Score bucket monotonicity、Precision at K。
- Regime stability、liquidity-adjusted performance、execution feasibility。

### 8.3 Portfolio Evidence

- Cost-adjusted / excess return。
- Sharpe、Sortino、maximum drawdown、drawdown duration、CVaR。
- Turnover、cash utilization、concentration、diversification、exposure stability。
- Paper / Live vs Research Gap。

### 8.4 Alert / Exit Evidence

- Alert lead time、alert 後 MAE。
- False-positive / false-negative rate。
- Avoided loss、opportunity loss。
- Early exit rate、exit 後續表現、Add / Reduce 後續結果。

### 8.5 Model Evidence

- Ranking quality、calibration、stability、regime performance。
- Feature drift、label drift、OOS decay、research-to-live degradation。

每個指標必須對應產品決策：保留、限制、降權、退休、Promotion、risk budget、holding horizon、rebalance band 或 `NO_NEW_POSITION`；不保存只有數值、沒有決策用途的 vanity metric。

## 9. Data Governance Requirements

所有來源至少保存：

```text
decision_use_case
source_id
source_version
official_licensed_or_candidate
expected_fields
historical_availability
as_of_date
available_date
quality
rate_limit
license_note
missing_policy
look_ahead_risk
ingestion_stage
scoring_eligible
portfolio_advice_eligible
```

所有新資料依序通過：

```text
Diagnostics
→ Shadow Layer
→ Evidence Review
→ Accepted Feature
→ Formal Decision Layer
```

Candidate source 不得直接進 `ScoringEngine` 或 formal Portfolio Advice。資料 priority 與接受 Gate 詳見 Product Roadmap。

## 10. Model / AI Policy

### 10.1 規則與金融模型

優先使用可解釋、可比較的 ranking、quantile、factor attribution、regime policy、robustness、bootstrap / Bayesian uncertainty、decay detection，以及 Equal Weight、Inverse Volatility、Risk Budgeting、shrinkage、HRP、scenario stress 等方法。

Expected Return 不可靠時，不使用 unconstrained mean-variance 作早期正式方法。

### 10.2 ML Shadow-first

ML 主要用於 ranking、calibration、low-quality signal filtering、success-condition / downside prediction、drift / anomaly detection。不得把預測明日收盤價作主要產品目標。

ML 必須具備 Feature / Label / Dataset / Model Registry、purged / embargo split、calibration、importance、drift、shadow store、Champion / Challenger、Promotion Gate 與 rollback。

Gate 前不得修改正式 Recommendation、Portfolio Advice、Strategy Lifecycle、scheduler、參數或交易。

### 10.3 Deep Learning 邊界

DL 目前不作核心推薦引擎。較合理用途為公告／法說／新聞分類、長文本摘要、時序 embedding 與多來源 representation learning；只有在樣本、label、傳統 baseline、purged OOS、成本、解釋與 rollback 都成立時才可進 shadow。

### 10.4 AI Research Copilot

AI 只能讀受治理資料與 Evidence，用於摘要、Portfolio 變化解釋、研究問題、Profile 比較、weekly review 與 evidence gap。AI 不得捏造推薦原因、繞過 service 重算核心、修改正式策略、下單或把文字信心當統計信心。

## 11. Success Levels

### Level 1：Daily Usable Advice

- 每日能回答市場、候選、Portfolio 與持倉問題。
- Advice 完整、可拒絕、可回溯。
- Guided / Professional 共用核心。
- 不把 UI 完成當投資有效。

### Level 2：Evidence Operations & Data Credibility

- weekly review、action item、evidence write / recovery 形成真實節奏。
- P0 sources 有接受、限制或拒絕決議。
- replay、dry-run、forward、paper、live 狀態清楚。

### Level 3：Portfolio / Signal / Exit Effectiveness

- Portfolio Advice 相對 Equal Weight 有成本後可比較證據。
- Signal、gate、alert、Profile 可被 pruning / retirement。
- Position Health / Exit 有 thesis-based evidence。
- ML 若存在，仍只在 shadow / governed promotion boundary。

### Level 4：Evidence-Validated Investment Decision System

- Portfolio 建議扣除成本後具合理穩定性。
- 重大回撤可被控制，CVaR / exposure 在政策範圍內。
- Alert / Exit 有實際 lead-time 與風控價值。
- Research-to-paper/live gap 可解釋。
- 策略衰退可被發現，無效能力可被退休。
- 系統沒有因持續調參而過度擬合。

Level 4 仍不代表保證獲利、自動交易、AI 報牌或免人工審核。

## 12. Non-goals

- 保證獲利或承諾持續提高勝率。
- 預測明日股價的黑箱。
- AI 報明牌。
- 高頻／逐筆交易平台。
- 自動下單、券商帳戶控制或自動平倉。
- 用單一總分取代完整 Advice / Portfolio / Evidence。
- 未治理資料直接進 formal decision layer。
- 用 historical replay 取代 forward evidence。
- 用 dry-run scheduler 取代 production approval。
- 用 Portfolio Sandbox 取代 Portfolio Advice。
- 用 ML readiness 取代 production ML validation。
- 只增加功能而不做 pruning / retirement。

---

## 更新記錄

- 2026-07-11：重整為 North Star 與 Evidence 權威；允許 bounded structured advice，同時保留 Broker Execution、黑箱 AI、自動交易與自動 lifecycle 的禁止邊界；新增 Portfolio Advice、Position Health / Exit、signal pruning 與分層成功標準。
