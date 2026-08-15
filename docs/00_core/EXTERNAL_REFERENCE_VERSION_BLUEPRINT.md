# 外部專案參考與未來版本藍圖

> **最後更新**：2026-07-11
> **狀態校正**：P0 adapters 已完成 shadow engineering，但仍須逐來源 license / quality / PIT 人工接受；candidate 不得進 ScoringEngine 或 formal Advice。
> **定位**：本文件是 `ROADMAP_6M_ENGINEERING.md`、`VERSION_ROADMAP_V1_1_TO_V2_0.md` 與 `VERSION_ROADMAP_V2_1_TO_V4_0.md` 的參考 companion。它負責保存外部開源專案對照、資料源補強優先序、可借鑑設計、Blueprint 衝突檢查與 V1.8 至 V2.0 版本形狀；不取代 Vision、Snapshot、6M Roadmap、長期版本階梯或 Architecture。

---

## 1. 文件邊界

外部專案研究不應大幅寫進 Vision。Vision 負責 North Star、Evidence Requirement、Gap Register 與非目標；外部 repo 清單、資料源對照與技術選型放在本文件，避免 Vision 變成研究筆記。

採用下列 Scoped SSOT：

| 文件 | 權威範圍 |
|---|---|
| `PROJECT_SNAPSHOT.md` | 目前狀態、本週優先事項、高風險區。 |
| `ROADMAP_6M_ENGINEERING.md` | 未來 6 個月工程執行順序。 |
| `VERSION_ROADMAP_V1_1_TO_V2_0.md` | V1.1 至 V2.0 的版本化交付節奏。 |
| `VERSION_ROADMAP_V2_1_TO_V4_0.md` | V2.0 之後長期版號階梯與 maturity milestone 邊界。 |
| `system_vision_specification.md` | 長期產品願景、Evidence Requirement、Gap Register。 |
| 本文件 | 外部專案參考、資料源優先序、衝突檢查、版本形狀補充。 |

---

## 2. 外部參考採用規則

本文件只把「真的找得到內容，且能理解專案狀態與操作方式」的外部專案列為參考。採用門檻如下：

1. GitHub repo 必須公開可讀，或官方文件能穩定開啟。
2. README / docs 必須足以判斷用途、資料來源、安裝或操作方法。
3. 專案做法必須能映射到 baldr 的現有邊界：SQLite-first、本地資料治理、no-look-ahead、Decimal / integer financial boundary、read-only AI、非自動交易。
4. 若 repo 可讀但用途與 baldr 主線衝突，僅能列為「限縮參考」或「長期觀察」，不得變成 Roadmap 交付項。
5. 若 repo 404、內容不足、或無法理解操作方式，列入「不採用 / 待補證據」，不得當作版本規劃依據。

2026-07-05 查核結果：

- `x-qa/stock-screener-service` 目前 GitHub API 回傳 404，移出 active reference，只保留在不採用清單。
- `robertmartin8/PyPortfolioOpt` 解析至目前 repo `PyPortfolio/PyPortfolioOpt`，文件內改用目前可驗證 canonical repo。
- `OpenBB-finance/openbb-agents` 解析至 `OpenBB-finance/experimental-openbb-platform-agent`，只能作 agent / tool permission playground 參考，不列為穩定產品架構依據。
- 其他保留專案皆已確認公開、README 存在，且至少能判斷用途與操作邊界；但不是每個都適合進主 Roadmap。

---

## 3. 高階結論

baldr 目前最值得補強的不是更早導入 GPU、強化學習、券商自動下單或 SQLite 分檔，而是：

2026-07-08 closeout note：今晚目標已轉為 `V3.0 engineering candidate closeout/readiness report`。Score bucket audit、fixed threshold robustness、component ablation readiness、ML shadow-only contract 與 Phase 3C source candidate readiness dry-run 都只作工程候選輸入；本文件仍只保留外部參考與資料源邊界，不把候選來源升級為正式 ingestion、`ScoringEngine` 接線、scheduler approval、V4 readiness 或投資有效性結論。

1. **資料可信度**：corporate action、adjusted price policy、microstructure metadata、source coverage、資料可得日與 missing policy。
2. **橫截面 factor pipeline**：把市場、產業、題材、流動性、籌碼、基本面 diagnostics 寫成可追溯 snapshot。
3. **Negative evidence**：Why Not、Liquidity exclusion、資料降級、樣本不足、策略不適用要與推薦 evidence 同等重要。
4. **Portfolio sandbox**：只做 research-only allocation、constraints、virtual order lifecycle 與 execution trace，不自動下單。
5. **Read-only AI / MCP**：AI 只查 evidence、source trace、quality、warnings 與覆盤歷史，不寫 DB、不改策略、不產生 lifecycle action。

明確邊界：

- **SQLite 不拆檔**：近期仍維持單一主 SQLite DB 與現有資料治理。SQLite 的 single writer 是每個 DB file 的寫入鎖限制；拆成多個 DB 可以分散寫入鎖，但會提高一致性、查詢、備份、migration 與 transaction 複雜度。baldr 現階段瓶頸不在必須拆 DB，後續只在真實 lock / throughput 量測證明需要時重開設計。
- **暫不導入 GPU / cuFOLIO**：`cuFOLIO` 是大型 portfolio optimization / scenario generation 的 GPU 加速範例；baldr 目前瓶頸是資料治理、evidence 樣本、UI workflow 與 source gaps，不是大規模 covariance / CVaR / Monte Carlo 最佳化。
- **不自動交易**：券商 API、Nautilus、vn.py 只能借鑑 event lifecycle、adapter boundary、帳務 / 虛擬執行模型，不進 production broker order。
- **不讓 AI 決策**：Agent repo 只參考 tool permission、報告生成與角色分工；LLM 輸出不得當成 evidence。

---

## 4. 採用分級

### 4.1 Primary references：可直接影響 V1.8-V2.0 設計

| 專案 | 可借鑑內容 | baldr 採用方式 |
|---|---|---|
| [FinMind/FinMind](https://github.com/FinMind/FinMind) | 台股資料 catalog、SDK / API、三大法人、融資券、財報、除權息等資料範圍。 | 作為資料源 inventory / capability registry 參考；不得依賴免費 API 作唯一正式來源，需自建 SQLite cache 與 source quality。 |
| [FinMind/FinMind-MCP](https://github.com/FinMind/FinMind-MCP) | 把金融資料封裝給 LLM / MCP 查詢的 schema 與 read-only tool surface。 | V1.9 可參考本地 MCP / evidence query 設計；僅 read-only，不允許 AI 寫 DB。 |
| [microsoft/qlib](https://github.com/microsoft/qlib) | Dataset / model / recorder 解耦、research run 管理、factor / label pipeline。 | 已對應到 Research Run Registry、FactorGate、factor snapshot；後續繼續借鑑 pipeline / recorder，不直接套 Qlib。 |
| [stefan-jansen/zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded) | Point-in-time pipeline、corporate actions、cross-sectional ranking。 | 用於校準 Sector Rotation / factor pipeline 的 no-look-ahead 與 adjusted price policy。 |
| [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | SQLite workflow、CLI、lookahead-analysis、推播與 scheduler discipline。 | 參考檢查工具與操作節奏；不採 crypto 高頻假設，也不啟用 production write scheduler。 |
| [wirelessr/three-gate-screener](https://github.com/wirelessr/three-gate-screener) | 台股免費資料 pipeline、SQLite cache、TDCC / FinMind / twsthr、walk-forward、明確記錄策略沒有 edge。 | 很適合補 baldr 的 negative evidence / Why Not 精神；資料源可作 P1 候選，但要逐一登錄 source policy。 |
| [xang1234/stock-screener](https://github.com/xang1234/stock-screener) | 多市場 screener、80+ filters、market breadth、group ranking、theme discovery、operations console、Docker 操作說明。 | 參考 Screening Matrix / Operations Console / Market Breadth UI；不把 baldr 轉成多市場 server stack，也不採其 LLM research 為 evidence。 |
| [PyPortfolio/PyPortfolioOpt](https://github.com/PyPortfolio/PyPortfolioOpt) | Efficient frontier、risk model、constraints、Black-Litterman、HRP。 | V1.8 research-only portfolio construction sandbox 可借鑑 API 形狀；輸出只標示 research basis，不作交易建議。 |
| [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) | Provider catalog、金融資料平台、command / API / UI 組織方式。 | 參考 provider registry 與研究工具 surface；台股資料治理、evidence layer 仍由 baldr 自己控制。 |

### 4.2 Constrained references：可借鑑，但必須限縮

| 專案 | 限縮原因 | 可用部分 |
|---|---|---|
| [mlouielu/twstock](https://github.com/mlouielu/twstock) | 經典台股抓取工具，但不提供 baldr 需要的完整 governance / backtest evidence。 | 交易日、簡單台股 filter、錯誤處理概念；不作核心 ingestion 唯一依據。 |
| [benhuang36/kanpan](https://github.com/benhuang36/kanpan) | Tauri / React 看盤工具，主軸是展示與即時 UI。 | K 線、內外盤、法人 / 融資券資料流與桌面 UI 互動；baldr 不轉為看盤軟體。 |
| [Sinotrade/rshioaji](https://github.com/Sinotrade/rshioaji) | 券商 API / 行情 / 下單能力會誘發自動交易邊界風險。 | 僅參考 adapter / service boundary、行情與 virtual execution trace。 |
| [fugle-dev/fugle-trade-python](https://github.com/fugle-dev/fugle-trade-python) | 富果生態綁定，且偏 order / account API。 | 只參考 order object、整股 / 零股狀態與帳務同步語意。 |
| [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | 完整交易引擎過重，導入成本與系統目標不符。 | 參考 event-driven state machine、Decimal / precision、order lifecycle。 |
| [vnpy/vnpy](https://github.com/vnpy/vnpy) | 交易平台與 PyQt UI 很完整，但對研究型 baldr 過重。 | 參考 EventEngine 與 PySide / PyQt UI event binding，不導入交易終端邏輯。 |
| [jesse-ai/jesse](https://github.com/jesse-ai/jesse) | Crypto trading bot，單商品 / 高頻假設與台股橫截面不同。 | 參考 optimization report、dashboard / CLI 分離、walk-forward 操作節奏。 |
| [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | 高度向量化 / Numba，可讀性與治理成本高。 | 只在 forward outcome 或 factor sweep 量測過慢時局部借鑑，不重寫引擎。 |
| [OpenBB-finance/experimental-openbb-platform-agent](https://github.com/OpenBB-finance/experimental-openbb-platform-agent) | experimental playground，不列為穩定架構來源。 | 只參考 agent tool index、報告生成、權限分層概念。 |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | 多 Agent investment demo，決策隨機性與實盤邊界風險高。 | 參考 analyst / risk / portfolio manager 角色分工；LLM 不能產生 lifecycle action。 |
| [D11225687/taiwan-stock-advisor](https://github.com/D11225687/taiwan-stock-advisor) | 17-agent / FastAPI / React / ML 架構較大，短期維護成本高。 | 參考多 agent 分工與 Web app 組織；不複製 agent 數量與複雜度。 |
| [starboi-63/growth-stock-screener](https://github.com/starboi-63/growth-stock-screener) | 成長股 screener 可讀，但較像條件掃描，不是完整治理框架。 | 參考 growth metrics / 基本面條件矩陣；只能進 diagnostics / gate，不進 `ScoringEngine`。 |

### 4.3 Long-term watch：暫不進 V1.8-V2.0 主線

| 專案 | 判斷 |
|---|---|
| [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | 可借鑑 market state / action / reward 抽象，但 RL 在台股容易過擬合；不進 V1.8-V2.0 主線。 |
| [NVIDIA-AI-Blueprints/cuFOLIO](https://github.com/NVIDIA-AI-Blueprints/cuFOLIO) | GPU portfolio optimization 工具可作長期觀察；只有在 V1.8+ portfolio sandbox 出現可量測 CPU bottleneck 後才重評估。 |
| sklearn / XGBoost / LightGBM 類監督式 ML | 可作 V3.3 shadow-only calibration、meta-labeling、ranking 或權重學習候選；必須等 V3.0 score bucket audit、threshold robustness、component ablation 可判讀後再進實驗，不直接替代 rule engine。 |

### 4.4 不採用 / 待補證據

| 專案 | 原因 |
|---|---|
| `x-qa/stock-screener-service` | 2026-07-05 查核時 GitHub repo 404，無法確認內容、狀態或操作方法；不得作 roadmap 依據。 |

---

## 5. Blueprint 衝突檢查

| 潛在衝突 | 風險 | 本次決議 |
|---|---|---|
| 外部 repo 很多，容易把 roadmap 變成技術堆疊清單。 | 失去 baldr 現有 evidence-first 主線。 | 分為 Primary / Constrained / Watch / Excluded；只有 Primary 可影響近中期設計。 |
| FinMind / twstock / three-gate 等資料源看起來可直接接。 | API rate limit、資料授權、資料可得日與歷史追溯不一定符合 no-look-ahead。 | 先進 Data Source Capability Registry；正式 ingestion 需 source id、available_date、quality、missing policy。 |
| 券商 API repo 可能導向自動下單。 | 破壞目前 manual lifecycle boundary。 | 只參考 virtual order lifecycle、帳務語意與 event sourcing；不串 production broker order。 |
| PyPortfolioOpt / cuFOLIO 可能讓 V1.8 被誤解為投資組合自動建議。 | Optimizer 輸出被誤當交易指令。 | V1.8 只做 research-only sandbox；cuFOLIO 不導入，PyPortfolioOpt-style adapter 也只輸出 research basis。 |
| OpenBB / AI agent repo 可能讓 LLM 直接參與決策。 | AI hallucination、權限越界、evidence 污染。 | V1.9 只做 read-only evidence access；AI-generated thesis 不算 evidence。 |
| ML 看起來可以直接提高推薦品質。 | 若 `TotalScore` 本身、fixed threshold 或 component 貢獻尚未被驗證，模型只會把 overfit 包裝成更難解釋的分數。 | 先完成 V3 score effectiveness audit；ML 只作第二層 shadow diagnostics，包括 calibration、meta-labeling、ranking 或權重學習。 |
| SQLite single writer 被誤解成必須拆 DB。 | 過早拆 DB 造成 migration / transaction / backup / cross-db query 複雜化。 | 不拆檔、不做 async / split DB 改造；只在量測證明 lock / throughput 成為真瓶頸後重開。 |
| vectorbt / Numba / GPU 加速被提前導入。 | 增加可讀性與治理成本，問題根源未必是計算。 | 先用 pandas / NumPy / SQL batch / single-writer discipline；只有局部量測過慢才局部最佳化。 |

目前 blueprint 沒有需要推翻的方向；需要的是把「限縮參考」與「暫不採用」寫清楚，避免外部專案反過來拉歪 V1.8-V2.0。

---

## 6. 資料源補強優先序

Post-Refactor 後，資料優先序以 [PRODUCT_ROADMAP_POST_REFACTOR.md](PRODUCT_ROADMAP_POST_REFACTOR.md) 的投資可信度與 Advice use case 為準；本文件保留來源候選與外部參考細節。統一分級如下：

| Priority | 來源 |
|---|---|
| P0 | Corporate Action（除權息、減資、分割、面額變更）、停復牌、處置、分盤、全額交割、漲跌停鎖死、三大法人、信用交易、TDCC、PIT 月營收與季度財報公告日。 |
| P1 | Concept Basket、ETF 持股／指數成分、借券、重大訊息、法說、股利事件、市場波動與衍生品風險。 |
| P2 | 新聞 NLP、公告／法說文字模型、分析師預估、替代資料、ML ranking feature、DL temporal feature。 |

所有來源仍先走 Diagnostics → Shadow → Evidence Review → Accepted Feature → Formal Decision Layer；下列既有細節不構成正式 ingestion 承諾。

### 6.1 既有來源細節：直接可信度與 Evidence gaps

1. **Corporate action / adjusted price timeline**
   - 目的：避免除權息、分割、還原價造成 forward return、技術指標、回測與 portfolio replay 失真。
   - 來源候選：FinMind、TWSE / TPEX / MOPS 官方資料、後續授權 PIT 匯出。
   - Gate：任何 adjusted series 都要標示 raw / adjusted policy、available_date、source_version。

2. **台股微結構治理資料**
   - 內容：處置股、分盤、全額交割、漲跌停鎖死、交易限制。
   - 來源候選：TWSE / TPEX 官方公告、FinMind 或其他可追溯來源。
   - Gate：必須能進 Why Not / Portfolio Alert；缺資料時 fail-closed、degraded 或 skip。

3. **Evidence source gaps**
   - 內容：Why Not / Liquidity payload、watchlist 實際事件、portfolio active positions、risk prompt source。
   - Gate：舊 result 缺 payload 只診斷，不回補、不重算；新 result 必須在 decision-time 保存。

### 6.2 既有來源細節：籌碼、信用、題材與估值

#### 2026-08-14 Formal ML PIT sector source audit

TWSE Data E-Shop 的 `TWT58U`「證券及產業別對照表」官方頁面明列：每日交易日 22:00 產製、內容為證券代號與產業別代碼、資料起始日為 `2019-12-23`，並以月訂閱提供。這是可作為正式 source candidate 的受控來源，但目前沒有本機授權下載、原始 publication archive 或 license／source hash lineage；更重要的是，它無法單獨覆蓋 Direct/OOC 所需的 `2014–2026` 全期間。未取得可驗證的 2014–2019 歷史來源前，不得以 TWT58U 尾段、現行 `companies.csv` 或產業指數成分回填 PIT sector membership；`pit_sector_membership_present` 維持 blocked。

來源：[TWSE Data E-Shop｜證券及產業別對照表（TWT58U）](https://eshop.twse.com.tw/zh/product/detail/000000006e0bbe8d016f18269c59032c)。

#### 2026-08-14 Formal ML PIT sector source expansion audit

本次進一步核對到兩個可能覆蓋完整 Direct/OOC 歷史區間的官方產品，但兩者都仍是受控訂閱來源，尚未取得本機授權原始檔：

- TWSE `T97`「漲跌幅度表檔」每日 23:30 產製，資料內容包含證券代號與產業別代碼，資料起始日為 `2014-01-06`。官方頁面同時列出 TEXT／CSV、訂閱與內外部使用限制；它可作為上市市場的 PIT sector source candidate，但不能在未交付逐日原始檔、publication timestamp、license 與 source hash lineage 前直接進 sidecar。
- TPEX「上櫃股票基本資料」頁面列出每日 `T30`「上櫃股票漲跌幅度表」，資料起始日為 `2008-11-01`，且可申購歷史月份；TPEX 格式文件確認產業別代碼是 T30 欄位。它可作為上櫃市場的 PIT sector source candidate，但仍須逐檔驗證格式版本、publication time、修訂切換與授權範圍。

因此，`T97 + T30` 是目前最接近覆蓋 `2014–2026` 的正式候選組合，但本機仍沒有可驗證 deposit，尚未建立或採用任何 partial／synthetic sidecar。正式 acceptance 仍要求：市場與證券 universe coverage、每檔原始檔 SHA-256、publication／available_at、格式版本或修訂 lineage、license id，以及轉換後 `pit-sector-membership-sidecar-v1` 的 canonical manifest。`pit_sector_membership_present` 維持 blocked。

來源：[TWSE T97 漲跌幅度表檔](https://eshop.twse.com.tw/zh/product/detail/75ce5fd1ad574df49ad9ff82209ca837)、[TPEX 上櫃股票基本資料（含 T30）](https://eshop.tpex.org.tw/zh/product/detail/BCDDCDFD315841EC011ED99B91DD528E)、[TPEX 收市後交易資訊格式說明](https://www.tpex.org.tw/storage/regular_system/%E6%96%B0%E7%89%88%E6%94%B6%E5%B8%82%E5%BE%8C%E4%BA%A4%E6%98%93%E8%B3%87%E8%A8%8A%E6%A0%BC%E5%BC%8F%E8%AA%AA%E6%98%8E%28V1.33%E7%89%88%29.pdf?t=20251127)。

#### 2026-08-14 Prospective-only sector decision

Owner 已決定不再以補齊 `2014–2026` full-history Formal coverage 作為目前產品路線，T97／T30 歷史採購與 `2014-01-03` 補充來源因此移為 deferred option；既有期間只保留 research/history，不宣稱舊契約通過。新的 Gate 7 路線依 [Prospective Formal Simulated Portfolio Execution Plan](../06_qa/PROSPECTIVE_FORMAL_SIMULATED_PORTFOLIO_EXECUTION_PLAN_2026_08_14.md)，從未來 activation trading day 開始保存每日 PIT membership。

這項範圍縮減只移除「回溯 2014」的產品主張，不等於可以使用未授權或無 lineage 的現行分類。Activation 前仍須確定合法 daily source 與 allowed use、保存 license id、原始 publication／available_at、格式版本、source hash、effective interval、universe coverage 與轉換後 canonical hash；沒有這些證據時，prospective PIT capture 與 Formal clock 都必須維持 blocked，且不得自行付費採購。

#### 2026-08-14 Local causal ledger candidate rejection audit

唯讀盤點發現本機存在 `ml_research_causal_ledger_full_v4_official_events` 的 research ledger
與 SQLite，但 latest pointer 的 `schema_version` 為 `research-causal-ledger-latest.v1`、
`research_only=true`；其目前 run manifest 另明列 `formal_consumer_compatible=false`、
`promotion_eligible=false`，並包含 `research_causal_ledger_not_formal_source` blocker。這些
artifact 不可作為 `causal_non_cash_portfolio_ledger` 的 owner-controlled formal deposit，
因此沒有設定 formal path、沒有改寫正式 DB，也沒有觸發 Direct/OOC refresh。

2026-07-08 Phase 3C 已先把三大法人、信用交易與 TDCC 做成 source candidate readiness dry-run：只檢查 DB / table / `available_date` / future-data / diagnostics，不正式 ingestion、不接 `ScoringEngine`、不改推薦 threshold、不啟用 scheduler。下列資料源仍需後續 source policy、授權與正式 ingestion gate 才能進入日常流程。

1. **三大法人 / 外資 / 投信 / 自營商**
   - 用途：Smart Money、Chip Flow、Risk Prompt、Screening Matrix。
   - 禁止：不得把單日法人買超直接解釋成買進理由。

2. **信用交易**
   - 用途：融資融券、擁擠度、斷頭 / 軋空風險。
   - 優先放 Why Not / Risk Prompt，不進核心 score。

3. **TDCC / 集保持股分散**
   - 用途：籌碼集中度、散戶 / 大戶結構、週頻變化。
   - 參考：`three-gate-screener` 的 TDCC / archive / twsthr 取捨，但 baldr 必須自行定義授權與 source policy。

4. **Concept Basket / 題材籃子**
   - 用途：補官方產業分類無法捕捉台股題材輪動的限制。
   - Gate：成分股版本、有効日期、available_date 必須保存。

5. **P/B、P/S governed observations**
   - 用途：fundamental diagnostics / valuation presentation。
   - Gate：只接受 governed external observation 或明確 backfill record；不在系統內臨時計算分子 / 分母。

### 6.3 既有來源細節：長期研究

- Broker real-time / order API：只作 virtual execution trace 與帳務語意參考。
- News / text / theme extraction：先有 source governance 與 hallucination boundary 再談。
- Options / futures / ETF flows：除非 Daily Decision 明確需要，否則不擴張。
- FinRL / RL：只留 sandbox 概念，不進 V1.8-V2.0 主線。
- cuFOLIO / GPU：只在 portfolio optimization 量測成為真瓶頸後重評估。

---

## 7. baldr 已經具備或更嚴謹的部分

baldr 目前不是從零開始追外部 repo，已經有幾個核心能力與成熟專案方向一致：

- **SQLite-first 本地資料底座**：類似 Freqtrade / screener 類專案的本地資料思路，但更聚焦台股與 evidence governance。
- **Research Run Registry**：方向接近 Qlib recorder / research workflow，已能保存 metadata、hash、Parquet 明細、比較與 promote gate。
- **No-look-ahead governance**：已建立 FactorGate `available_date <= decision_date`、fixed / quantile Expanding T-1、eligible universe boundary。
- **Evidence Event Store**：已保存 Recommendation、Watchlist、Portfolio Alert、Risk Prompt、Why Not / Liquidity 類 events 與 forward outcomes。
- **Negative evidence v1**：已保存 screening matrix、Why Not / Liquidity payload 與 capture events；舊資料只診斷，不回補。
- **Manual lifecycle boundary**：promote / hold / demote_candidate / retire_candidate 仍需人工批准，不自動改策略。
- **資料品質語彙**：`OBSERVED` / `ESTIMATED` / `DEGRADED` / `MISSING` 已貫穿 Daily Decision、Smart Money、Portfolio Alert 與 Evidence Review。

因此下一步不是重寫 baldr，而是把外部成熟做法吸收進既有 scoped architecture。

---

## 8. V1.8 至 V2.0 版本形狀

### V1.8：Portfolio Construction & Execution Trace Sandbox

目的：讓研究層能比較配置、限制、交易生命週期與 execution gap，但仍不自動下單。

交付方向：

1. Research-only allocation：等權、分數權重、risk parity / constrained allocation 候選。
2. PyPortfolioOpt-style constraints / risk model adapter，所有輸出標示為 research basis。
3. Virtual event sourcing：Order Created -> Submitted -> Partially Filled -> Filled / Cancelled / Rejected。
4. Portfolio replay residual：零股、買賣價差、完整撮合、gap actual execution model、未成交原因。

不做：

- 不串 production broker 下單。
- 不導入 Nautilus / vn.py 完整交易引擎。
- 不拆 SQLite DB。
- 不導入 cuFOLIO，除非 optimization bottleneck 被量測證明。

### V1.9：Read-only Agent / MCP Evidence Access

目的：讓 AI 能查詢 baldr evidence、資料品質與覆盤歷史，協助摘要與提出審核問題，但不取代治理。

狀態：2026-07-06 v1 已完成，範圍限定 read-only app-layer service 與 MCP wrapper。

已交付：

1. 本地 read-only MCP server：`mcp_servers/evidence_access_server.py` / `twstock-evidence-access`。
2. App-layer read-only service：`app_module/agent_evidence_access_service.py`。
3. Evidence / Research Run / Portfolio Review saved evidence 查詢 schema。
3. Agent permission model：read-only；不得 write DB、不得改策略、不得下單、不得 lifecycle action。
4. AI report template：只引用 evidence rows、quality、warnings、source trace。

不做：

- 不讓 LLM 輸出買賣指令。
- 不把 AI-generated thesis 當成 evidence。
- 不用 experimental agent repo 當穩定架構來源。

### V2.0：Unified Decision Workbench

目的：當 V1.5 至 V1.9 的資料可信度、factor pipeline、negative evidence、portfolio sandbox 與 read-only AI 都完成第一版，且有足夠實際 evidence accumulation / smoke / dry-run 證據後，再重整資訊架構。

V2.0 應長成：

1. 第一畫面是「今日決策任務」，不是功能分頁清單。
2. Daily Decision、Market Watch、Evidence Review、Portfolio Review 成為同一工作流。
3. 每個候選股票都能看到 Why、Why Not、Risk、Evidence、Forward outcome、Live gap、Data quality。
4. 每個策略都能看到有效範圍、失效範圍、近期 decay、manual lifecycle candidates。
5. 舊 Tab 保留為 drill-down / expert mode，避免破壞既有研究能力。

---

## 9. 明確不納入近期 Roadmap

- **SQLite async / split DB 改造**：先不動。後續只有在真實 lock / throughput bottleneck 被量測證明後，才重開設計。
- **Production auto trading**：不做。券商 API 只可作行情、帳務或 virtual execution trace 參考。
- **強化學習主線**：不進 V1.8-V2.0。可留長期 sandbox，但需 dataset registry、walk-forward、overfit guard。
- **GPU-first portfolio optimization**：不做。先用 SQL batch、pandas / NumPy、必要時局部 vectorized / Numba。
- **AI 自動升降級**：不做。LLM 只能產生摘要與審核問題，lifecycle action 仍需人工核准。
- **不可驗證外部 repo**：不做 roadmap 依據；`x-qa/stock-screener-service` 目前屬此類。

---

## 10. 對現有 Roadmap 的審查結論

### Vision

不建議大幅改寫。Vision 應保持 North Star、Evidence Requirement、Gap Register 與非目標；外部專案清單由本文件承接。

### 6M Roadmap

主線仍合理：Evidence-Driven baldr、資料治理、Factor Layer、Daily Decision、Portfolio Feedback。外部參考校準後不需要改方向；V1.8 portfolio sandbox、V1.9 read-only AI 與 Workbench formal read-only source adapter 已完成 v1，後續維持先補 evidence accumulation / manual smoke / multi-day dry-run，再評估 V2.0 Unified Decision Workbench 主 UI 的順序。

### Version Roadmap

V1.1 至 V1.9 已完成的定位不變。已完成的 portfolio sandbox 不等於自動配置建議，read-only AI 不等於 AI 決策。V2.0 前必須先用實際週期證據驗證哪些 evidence summary / dashboard / action item 真正有用。
V2.0 之後的 V2.1-V4.0 只在 `VERSION_ROADMAP_V2_1_TO_V4_0.md` 中維護 maturity milestone，不由本文件直接承諾外部資料源導入或投資有效性。

### Roadmap Hub

Roadmap Hub 不應保存完整外部分析。它只需要指向本文件，並在 Next 保持「累積 evidence、用 read-only adapter 補 V2.0 前置驗證、V2.0 主 UI 等 evidence 和使用節奏成熟後再評估」。

---

## 11. 更新記錄

- 2026-07-11：對齊 Post-Refactor Data Source priority；P0 納入 corporate action、trading restriction、三大法人、信用交易、TDCC 與 PIT fundamentals，P1 / P2 依產品可信度重排；所有來源仍 candidate-first，不直接進 `ScoringEngine`。
- 2026-07-08：補上今晚目標已轉為 `V3.0 engineering candidate closeout/readiness report`；score/source readiness 只作工程候選與人工驗證輸入，不代表正式資料 ingestion、ScoringEngine 接線、scheduler approval、V4 readiness 或投資有效性。
- 2026-07-08：補上 supervised ML 採用邊界；sklearn / XGBoost / LightGBM 只可作 V3.3 shadow-only 候選，必須等 V3 score effectiveness audit 可判讀後才進實驗，不取代 rule engine、不直接改推薦。
- 2026-07-08：補上 Phase 3C source candidate readiness 現況；三大法人、信用交易與 TDCC 只完成 candidate-only dry-run，不代表正式資料 ingestion、ScoringEngine 接線或 scheduler approval。
- 2026-07-06：補上 `VERSION_ROADMAP_V2_1_TO_V4_0.md` 的 scoped authority 對照，明確本文件不直接承諾 V2.1-V4.0 外部資料源導入或投資有效性。
- 2026-07-05：重新整理外部專案採用規則與分級；確認只保留公開可讀且 README / docs 足以理解用途與操作方法的專案；`x-qa/stock-screener-service` 因 404 移出 active reference；`PyPortfolioOpt` 改用目前 canonical `PyPortfolio/PyPortfolioOpt`；`OpenBB agents` 降級為 experimental playground 參考。
- 2026-07-06：標記 Workbench formal read-only source adapter 已完成；V2.0 主 UI 仍等待 Phase 0 weekly history / multi-day dry-run / manual workflow evidence，不因 adapter 或 replay 提前解除 gate。
- 2026-07-06：標記 V1.9 Read-only Agent / MCP Evidence Access v1 已完成；V2.0 前置條件改為 evidence accumulation、manual smoke、multi-day dry-run 與真實 workflow 樣本成熟。
- 2026-07-05：補上 Blueprint 衝突檢查，明確寫入 SQLite 不拆檔、不做 async / split DB 改造、暫不導入 GPU / cuFOLIO、不自動交易、不讓 AI 決策。
- 2026-07-04：新增外部專案參考與 V1.5-V2.0 版本藍圖；確認 Vision 不大幅改寫，外部參考由本 companion 承接。
