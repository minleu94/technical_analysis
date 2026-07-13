# V2.1 至 V4.0 產品成熟度路線圖

> **最後更新**：2026-07-12
> **定位**：本文件是 V2.0 之後的長期產品成熟度與版本階梯權威；版號代表產品能力與證據成熟度，不代表功能數量。
> **工程順序**：未來六個月以 [ROADMAP_6M_ENGINEERING.md](ROADMAP_6M_ENGINEERING.md) 為準。
> **產品方向**：投資問題、能力演進與產品 Gate 以 [PRODUCT_ROADMAP_POST_REFACTOR.md](PRODUCT_ROADMAP_POST_REFACTOR.md) 為準。
> **歷史交棒**：V1.1 至 V2.0 的已完成演進見 [VERSION_ROADMAP_V1_1_TO_V2_0.md](VERSION_ROADMAP_V1_1_TO_V2_0.md)。

---

## 1. 版號判讀原則

1. 工程完成不等於投資有效。
2. Dashboard、scheduler、ML 或資料表完成不單獨構成大版本。
3. Historical replay 不算 forward / live evidence。
4. Candidate source、readiness、shadow model 不算 formal decision capability。
5. V4.0 必須由長期 Forward / Paper / Live Evidence 支持，不能用規劃日期提前宣告。
6. 版本 closeout 必須有明確 non-goals、residual、rollback 與 evidence boundary。

## 2. Scoped Authority

| 主題 | 權威文件 |
|---|---|
| 目前狀態 | `PROJECT_SNAPSHOT.md` |
| 產品方向與產品 Gate | `PRODUCT_ROADMAP_POST_REFACTOR.md` |
| 六個月工程交付 | `ROADMAP_6M_ENGINEERING.md` |
| North Star / Evidence / Success Levels | `system_vision_specification.md` |
| Current Architecture | `system_architecture.md` |
| Target Architecture | `target_system_architecture.md` |
| 本文件 | V2.1-V4.0 maturity mapping |

## 3. 版本階梯總覽

| 版本 | 成熟度定位 | 最低成立條件 | 不代表 |
|---|---|---|---|
| V2.1 | Daily Usable Workbench | 單一日常入口、Advice Contract 可見、quality / warnings 完整 | 投資有效 |
| V2.2 | Evidence Operations | 真實 weekly review / action-item / evidence write / recovery 節奏 | production trading |
| V2.3 | Data Credibility | P0 source-by-source acceptance / limitation / rejection | candidate source 已進 score |
| V2.4 | Portfolio Coach Foundation | Risk budget、target/current/gap、Equal Weight benchmark、paper portfolio | 自動配置或 broker execution |
| V2.5 | Position Health Foundation | thesis / invalidation contract、health read model、manual decision journal | 完整 Exit effectiveness |
| V3.0 | Signal Effectiveness & Pruning | Score、component、gate、alert、Profile 可判讀並有 pruning 決議 | 所有 signal 有效 |
| V3.1 | Portfolio Advice Validation | sizing / bands / risk policy 有 OOS / forward / paper 成本後比較 | 保證優於 benchmark |
| V3.2 | Position Health & Exit Validation | Add / Hold / Reduce / Exit 有 lead-time、false rate、opportunity-loss evidence | 自動平倉 |
| V3.3 | ML Shadow / Champion-Challenger | rule baseline 可判讀；ML 只作 shadow 並具 registry / calibration / drift / rollback | production ML 或黑箱決策 |
| V4.0 | Evidence-Validated Investment Decision System | 長期 Recommendation / Portfolio / Exit / lifecycle evidence 支持決策品質與風險調整表現 | 保證獲利、自動交易、免人工審核 |

## 4. V2.x：Daily Usable、Evidence Operations、Data Credibility、Portfolio Foundation

### V2.1：Daily Usable Workbench

目的：把既有 Workbench 從 read-only 工程資訊入口，演進為能呈現 bounded Advice 的日常產品入口。

最低能力：

- Guided / Professional Mode 共用核心。
- Recommendation Advice Contract。
- `RESEARCH`、`ADD_CANDIDATE`、`HOLD`、`REDUCE_CANDIDATE`、`EXIT_CANDIDATE`、`AVOID`、`NO_NEW_POSITION`。
- Why / Why Not / Risk / Evidence / quality / strategy / data date。
- Portfolio Advice 最低欄位：target/current/gap；可先為 read-only / paper。

Closeout Gate：Advice 可拒絕、可重算、可回溯；UI 不直接計算；不串 broker。

**目前版本狀態（2026-07-12）**：V2.1 已於 2026-07-12 14:51:42 -07:00 獲 release owner 明確 `approve`，正式 closeout 狀態為 `formal_closeout_complete`。已驗證的 bounded / read-only Daily Usable Workbench 行為為：Guided 僅接受 `promoted`、parameters locked 與 disclosure complete 的策略；`max_positions` 只允許 `1..8`；Professional candidate 僅 `RESEARCH` 並與正式 Advice 分區。focused suite 為 `94 passed in 2.91s`，engineering readiness 與 approval record 分別見 `docs/06_qa/V2_1_ENGINEERING_READINESS_2026_07_12.md`、`docs/06_qa/V2_1_FORMAL_CLOSEOUT_2026_07_12.md`。此狀態不改變本文件的 maturity 定義，亦不代表投資有效性、broker execution、production scheduler、P0 source acceptance 或後續版本 Gate 已完成。

### V2.2：Evidence Operating Loop

目的：讓 Evidence 不再只有 dashboard / dry-run，而形成真實 weekly review、manual note 與 action-item rhythm。

最低能力：

- 真實 weekly periods 與人工 review。
- append-only evidence / review artifact。
- dry-run → working-copy → approved evidence write-mode。
- backup / rollback / recovery。
- replay / dry-run / forward / paper / live tier 分離。

Closeout Gate：production evidence scheduler 如獲批准只保存 evidence；不自動交易、不套 lifecycle action。

**目前版本狀態（2026-07-12）**：V2.2 的 weekly review CLI、append-only history 操作介面、working-copy runbook 與 scheduler approval package 已具 engineering readiness；weekly history 實際仍為 `0/3 waiting_for_time`，multi-day dry-run 已為 `3/3 ready`，scheduler 未獲核准且 `production_scheduler_allowed=false`。因此不得建立 V2.2 formal closeout，也不得將 `--save-history`、replay、fixture、raw scheduled report 或單次 smoke 解讀為真實三週 Gate。工程 readiness 詳見 `docs/06_qa/V2_2_ENGINEERING_READINESS_2026_07_12.md`；三週人工操作格式詳見 `docs/07_guides/V2_2_WEEKLY_REVIEW_RUNBOOK.md`。本狀態不改變本節 maturity definition，亦不代表 production trading、lifecycle action 或投資有效性。

### V2.3：P0 Data Credibility

目的：逐一處理 Corporate Action、trading restriction、三大法人、信用交易、TDCC、PIT fundamentals。

最低能力：

- 每個 source 有 `source_id`、version、`as_of_date`、`available_date`、quality、license、rate limit、missing、look-ahead、eligibility。
- Diagnostics → Shadow → Evidence Review → Accepted Feature。
- Data Source Control Center 可見 freshness、coverage、quarantine、retry 與 downstream eligibility。

Closeout Gate：每個 P0 source 有 accepted / limited / rejected / deferred 決議；candidate 不冒充 formal。

**目前版本狀態（2026-07-12）**：V2.3 已建立工程 readiness 與完整 Gate 3 P0 source-by-source 人工接受台帳，見 `docs/06_qa/V2_3_ENGINEERING_READINESS_2026_07_12.md`、`docs/06_qa/V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md`。除權息 / 除權、未登錄的減資 / 分割 / 面額變更與停牌 / 復牌、其他交易限制、三大法人、信用交易、TDCC 與 PIT fundamentals 目前全部是 `requires_human_acceptance`，且 `downstream eligibility=none`；每列保留 source version、as-of / available date、rate limit、freshness / coverage、quarantine / retry、evidence / review / rollback 與分離 owner / date。`decision_ready_candidate` 只屬診斷結果，不是 accepted feature；既有 `corporate_action.ex_dividend_timeline` 不涵蓋未登錄 corporate-action 事件。V2.3 formal closeout 尚未建立，必須等待逐來源完成 license、quality、PIT / available-date、missing / outage 與具名 owner / date 的 accepted / limited / rejected / deferred 決議。本狀態不改變本節 maturity definition，亦不代表正式 ingestion、`ScoringEngine` 接線、Advice / Portfolio eligibility、scheduler approval 或投資有效性。

### V2.4：Portfolio Coach Foundation

目的：從「推薦一批股票」演進為 risk-budgeted Portfolio Advice。

最低能力：

- Portfolio Risk Budget。
- `target_weight_bp` / `current_weight_bp` / `weight_gap_bp`。
- Equal Weight benchmark。
- Rebalance bands、minimum trade、turnover、cooldown。
- Paper Portfolio、execution feasibility、Trade Import / Decision Journal foundation。

Closeout Gate：能安全輸出 Portfolio Advice 或 `NO_NEW_POSITION`；不串 broker。

### V2.5：Position Health Foundation

目的：建立 thesis-based Health / Exit 的資料與狀態契約。

最低能力：

- Entry thesis、invalidation、holding horizon、review date。
- HEALTHY / WATCH / REDUCE_CANDIDATE / EXIT_CANDIDATE / CLOSED。
- Hard Risk、thesis、relative、time、portfolio、data、restriction reason categories。
- Manual override / decision journal / source trace。

Closeout Gate：每個 transition 可解釋、可回溯；不自動平倉。

**目前版本狀態（2026-07-12）**：V2.5 已有 read-only `PositionHealthService` 與 sample report，將既有 condition、feedback 與 source trace 投影為 HEALTHY / WATCH / EXIT_CANDIDATE，固定 `auto_action_allowed=false`。缺 condition 或 source trace 時維持 WATCH；它不讀實際持倉、不寫 DB、不自動減碼或平倉。工程 readiness 詳見 `docs/06_qa/V2_5_ENGINEERING_READINESS_2026_07_12.md`；真實 thesis、人工 state transition 與 decision journal 尚未累積，故 formal closeout 尚未建立。

## 5. V3.x：Signal、Portfolio、Exit、Pruning、ML Shadow、Paper Validation

### V3.0：Signal Effectiveness & Pruning

目的：回答 TotalScore、component、gate、alert 與 Profile 是否有用。

最低證據：

- Forward / benchmark / industry / concept excess。
- MAE / MFE、hit、payoff、bucket monotonicity、Precision@K。
- Fixed threshold robustness、component ablation、regime / liquidity stability。
- Signal / gate / alert / Profile 的 retain / restrict / downweight / retire 決議。

現況邊界：2026-07 的 score effectiveness / V3 engineering candidate 只代表 read-only scaffold 與 `ready_for_manual_validation`，不是本版本 closeout。

### V3.1：Portfolio Advice Validation

目的：驗證 Portfolio policy 是否在成本、風險與限制後比 Equal Weight 更合理。

最低證據：cost-adjusted / excess return、Sharpe、Sortino、MDD / duration、CVaR、turnover、cash、concentration、diversification、exposure stability、paper vs research gap。

方法次序：Equal Weight → Score Weight / Inverse Volatility → Risk Budgeting / HRP / shrinkage → 複雜 optimizer。Expected Return 不可靠時，不使用 unconstrained mean-variance 作正式基準。

### V3.2：Position Health & Exit Validation

目的：證明 Add / Hold / Reduce / Exit 不只是規則存在，而有實際 risk / opportunity 取捨。

最低證據：alert lead time、alert 後 MAE、false-positive / false-negative、avoided loss、opportunity loss、early exit、post-exit、Add / Reduce outcome，並依 regime / liquidity / reason / quality 分層。

### V3.3：ML Shadow / Champion-Challenger

目的：ML 只在 V3.0 baseline 可判讀後，研究 ranking、calibration、meta-labeling、downside risk 與 drift。

必要治理：Feature / Label / Dataset / Model Registry、purged / embargo split、calibration、importance、shadow prediction、drift、Champion / Challenger、Promotion Gate、rollback。

Closeout Gate：最多提出繼續 shadow、拒絕或人工 promotion review；不自動上線、不改 scheduler / Portfolio / lifecycle、不交易。

## 6. V4.0：Evidence-Validated Investment Decision System

V4.0 是長期 maturity milestone，不是目前六個月工程承諾。只有以下條件由長期 Forward / Paper / Live Evidence 支持時才成立：

1. Recommendation ranking / Advice 在合理 benchmark、industry / concept 與 liquidity 調整後具可判讀價值。
2. Portfolio Advice 扣除成本後有合理穩定性，且相對 Equal Weight 的增益與代價可解釋。
3. 重大回撤、CVaR、concentration 與 exposure 可被 policy 控制。
4. Alert / Exit 有 lead-time、avoided-loss 與 opportunity-loss 證據。
5. Research-to-paper/live gap 可由 execution、資料、regime、策略與人工 override 解釋。
6. Signal / strategy decay 可被發現；無效 feature / Profile / model 會被限制或退休。
7. 持續調參受到 Experiment Contract、search budget、OOS 與 pruning 約束，沒有用過度擬合換取版號。
8. Model / source / policy 出現 drift 或 failure 時，可回到 last approved champion。

V4.0 仍不代表：

- 保證獲利。
- 自動交易或 broker order。
- AI 報牌。
- 免人工審核。
- 所有市場環境都有效。

## 7. 版本 Promotion / Demotion 規則

### Promotion

- 工程 DoD、資料 Gate、Evidence Gate、風險與 rollback 全部成立。
- 版本 artifact 可追溯 data / strategy / policy / model / decision date。
- 人工 review 明確接受 limitations。

### Demotion / Hold

- Evidence 衰退、source quality 降級、research-to-live gap 擴大或風險超標時，版本可限制適用 regime、降級 Guided exposure 或停止 Promotion。
- 單次異常不足以直接退休；需依預先定義的 evidence policy。

### Retirement

- 保留歷史 artifact、effective date、reason、replacement / fallback 與 rollback reference。
- 不刪除歷史 Research Run / Evidence 以美化結果。

## 8. Deferred / 明確不納入近期版本

- Production broker execution / 自動下單。
- AI 自動 Strategy Lifecycle action。
- 強化學習核心主線。
- GPU-first Portfolio optimization。
- 未量測就進行 SQLite split / async rewrite。
- 未治理資料直接進 `ScoringEngine`。
- LLM output 作為統計 evidence。
- DL 作為近期核心推薦引擎。

## 9. 更新規則

本文件只在 maturity definition、版本 Gate 或跨版本責任改變時更新；單一 bugfix、dashboard polish、dry-run、candidate adapter、readiness scaffold 或一次 replay 不改變版本 closeout。

---

## 更新記錄

- 2026-07-12：記錄 V2.2 engineering readiness 與三週 weekly review runbook；weekly `0/3 waiting_for_time`、multi-day `3/3 ready`、scheduler 未核准，不能 formal closeout。
- 2026-07-12：修正 V2.1 為 engineering readiness complete / `awaiting_release_owner_confirmation`；保留 `592d3db` safeguards、focused suite、人工 UI 文案 smoke 與 rollback 證據，待 release owner 實際填寫 owner / timestamp / decision 後才可正式 closeout。
- 2026-07-11：依產品成熟度重整 V2.1-V4.0；V2.x 聚焦 Daily Advice / Evidence / Data / Portfolio foundation，V3.x 聚焦 Signal / Portfolio / Exit effectiveness、pruning 與 ML shadow，V4.0 改以長期 evidence-validated investment decision system 判定。
