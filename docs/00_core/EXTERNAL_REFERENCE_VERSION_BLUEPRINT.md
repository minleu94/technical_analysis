# 外部專案參考與未來版本藍圖

> **最後更新**：2026-07-04
> **定位**：本文件是 `ROADMAP_6M_ENGINEERING.md` 與 `VERSION_ROADMAP_V1_1_TO_V2_0.md` 的參考 companion。它負責保存外部開源專案對照、可借鏡做法、資料源優先序與 V1.5 至 V2.0 版本形狀；不取代 Vision、Snapshot、6M Roadmap 或 Architecture。

---

## 1. 文件邊界

這些外部專案建議不應大幅塞進 Vision。Vision 的責任是北極星、Current State、Evidence Requirement 與 Gap Register；若把 20 多個 GitHub 專案、資料源與技術選型全部寫進 Vision，會讓 Vision 變成研究筆記，反而降低權威性。

因此採用下列邊界：

- **Vision**：只保留長期產品方向與證據要求，新增本文件連結即可。
- **6M Roadmap**：決定未來 6 個月可執行順序。
- **Version Roadmap**：把 V1.1 至 V2.0 拆成可驗收版本。
- **本文件**：保存外部參考、資料源補強順序、可借鏡設計與未來版本藍圖。

外部專案的 stars、license、活躍度與描述屬於時間敏感資訊；本文只保存 2026-07-04 查核後的方向性結論，不把 stars 數當 roadmap 依據。Gemini 回傳內容中有部分 license、stars 或活躍度與 GitHub metadata 不完全一致，本文採「架構可借鏡性」而非人氣排序。

---

## 2. 高階結論

baldr 目前最值得補強的不是更早導入強化學習、GPU 或自動交易，而是：

1. **資料可信度**：V1.5 已補 source capability registry、corporate action / adjusted price policy、governed microstructure metadata 與 source coverage 分級；正式除權息 / 處置股資料 ingestion、三大法人與信用交易仍待後續。
2. **跨橫截面因子管線**：把每日市場、產業、題材、強弱、流動性與籌碼特徵寫成可追溯 factor snapshot，而不是直接塞進 `ScoringEngine`。
3. **負面證據與 Why Not**：把排除原因、低流動性、樣本不足、資料降級與策略不適用，提升到與推薦事件同等重要的 evidence。
4. **Portfolio construction sandbox**：研究層的配置、限制與事件生命週期可以先補，但仍不做自動下單。
5. **Read-only AI / MCP**：AI 可以查詢 evidence、生成摘要與提出覆盤問題，但不能繞過 no-look-ahead、資料可得日與人工核准。

NVIDIA `cuFOLIO` 目前不需要排入近期實作。baldr 現階段瓶頸主要是資料治理、source gaps、SQLite 寫入節奏、UI workflow 與 evidence 樣本，而不是大型 GPU portfolio optimization。只有當系統進入大量 portfolio construction、上萬參數組合、Monte Carlo / covariance / efficient frontier 批次優化，且 CPU / NumPy / vectorized pandas / Numba 都已證明不夠時，才重新評估 GPU。

---

## 3. 外部專案分組與可借鏡做法

### 3.1 台股資料與本地生態

| 專案 | 主要做什麼 | 可參考做法 | baldr 現況對比 |
|---|---|---|---|
| [FinMind/FinMind](https://github.com/FinMind/FinMind) | 台股與金融資料 API / dataset 封裝 | 資料表命名、FinMind dataset catalog、重試與標準化流程 | baldr 已有 SQLite-first 與 governed factor layer；可參考其資料廣度，但不應依賴免費 API 作唯一來源。 |
| [FinMind/FinMind-MCP](https://github.com/FinMind/FinMind-MCP) | 把 FinMind 資料封裝成 MCP server | LLM tool schema、dataset 查詢邊界、read-only AI access | baldr 可在 V1.9 建本地 read-only MCP / evidence query，不讓 AI 直接改 DB 或策略。 |
| [mlouielu/twstock](https://github.com/mlouielu/twstock) | TWSE / TPEX 抓取與台股工具 | 交易日、簡單過濾器、錯誤處理概念 | baldr 已有更完整 SQLite / evidence / no-look-ahead；twstock 僅適合作為歷史參考與輕量 filter 靈感。 |
| [wirelessr/three-gate-screener](https://github.com/wirelessr/three-gate-screener) | 台股三關篩選、TDCC / FinMind、OOS 與失敗教訓 | 負面結果文件、嚴格 OOS、邊緣效應檢查 | baldr 已有 Evidence Review；應吸收「Why Not / negative evidence first」精神。 |
| [benhuang36/kanpan](https://github.com/benhuang36/kanpan) | Tauri / React 台股看盤與 AI 分析 | 桌面 UI、即時看盤資料流、圖表互動 | baldr 目前 PySide6 研究工作台已成形；可參考 UI 資料流，不應轉向看盤軟體。 |
| [Sinotrade/rshioaji](https://github.com/Sinotrade/rshioaji) / [fugle-dev/fugle-trade-python](https://github.com/fugle-dev/fugle-trade-python) | 券商 API、行情、下單、帳務 | order lifecycle、broker API adapter、低延遲服務邊界 | baldr 短期不自動交易；V1.8 可只借鏡 event sourcing 與虛擬帳務同步。 |

### 3.2 因子研究、回測可信度與研究治理

| 專案 | 主要做什麼 | 可參考做法 | baldr 現況對比 |
|---|---|---|---|
| [microsoft/qlib](https://github.com/microsoft/qlib) | AI / quant research platform、dataset / model / recorder 解耦 | Research run registry、dataset handler、factor / label pipeline、模型生命週期 | baldr 已有 Research Run Registry、FactorGate、Evidence Event Store；V1.6 應參考其 pipeline / recorder 思路，而不是直接套 Qlib。 |
| [stefan-jansen/zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded) | 嚴謹回測與 Pipeline API | point-in-time pipeline、corporate actions、cross-sectional ranking | baldr V1.5 要先補 corporate action / adjusted price policy；V1.6 再做 cross-sectional factor pipeline。 |
| [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | Crypto bot、SQLite、Web UI、lookahead-analysis | lookahead 檢查工具、策略 CLI、SQLite workflow、推播 | baldr 已有 no-look-ahead 契約與 SQLite-first；可參考其自動化檢查與告警節奏，不採 crypto 高頻假設。 |
| [jesse-ai/jesse](https://github.com/jesse-ai/jesse) | trading research dashboard、walk-forward / optimization | 參數最佳化報告、CLI / dashboard 分離 | baldr 已有 Research Lab、Registry、Profile comparison；可補更清楚的 optimization report，但要避免 overfit。 |
| [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | NumPy / Numba 向量化高速回測 | 大量參數掃描、forward outcome 批次計算 | baldr 可在 evidence outcome 或 factor pipeline 過慢時局部採 vectorized/Numba；不先重寫引擎。 |

### 3.3 Portfolio、execution model 與數值治理

| 專案 | 主要做什麼 | 可參考做法 | baldr 現況對比 |
|---|---|---|---|
| [PyPortfolioOpt](https://github.com/robertmartin8/PyPortfolioOpt) | portfolio optimization、efficient frontier、risk models | constraints、risk model、allocation API | baldr 可在 V1.8 做 research-only portfolio construction sandbox；不能把 optimizer 輸出當交易建議。 |
| [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | Rust / Python event-driven trading engine | event engine、Decimal / precision、order lifecycle、execution state | baldr 已有 Decimal / lifecycle governance；可借鏡 event-sourcing 形狀，不導入完整交易引擎。 |
| [vnpy/vnpy](https://github.com/vnpy/vnpy) | Python 量化交易平台與 PyQt UI | EventEngine、交易 UI、Portfolio / account 模型 | baldr PySide6 可參考事件驅動 UI 綁定，但目前主線仍是研究與決策，不是交易終端。 |
| [NVIDIA-AI-Blueprints/cuFOLIO](https://github.com/NVIDIA-AI-Blueprints/cuFOLIO) | GPU portfolio optimization toolkit | 大規模 covariance / optimization / Monte Carlo 加速 | 近期不需要；只有 V1.8+ portfolio optimization 壓力明確超過 CPU / vectorized path 時再評估。 |

### 3.4 AI / Agent / Research terminal

| 專案 | 主要做什麼 | 可參考做法 | baldr 現況對比 |
|---|---|---|---|
| [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) | 金融資料平台、Research terminal、API / UI | 多資料源 provider、command -> API -> UI 組織 | baldr 可參考 provider catalog / command surface，但台股本地治理與 evidence layer 是 baldr 自己的優勢。 |
| [OpenBB-finance/openbb-agents](https://github.com/OpenBB-finance/openbb-agents) | LLM agents 調用金融工具 | tool index、agent 權限、報告生成 | baldr V1.9 可做 read-only analyst agent，限制工具權限與輸出語氣。 |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | multi-agent investment demo | analyst / risk / portfolio manager 角色拆分 | 可借鏡角色分工與解釋流程；不可讓 LLM 決策直接進 strategy lifecycle 或 portfolio action。 |
| [D11225687/taiwan-stock-advisor](https://github.com/D11225687/taiwan-stock-advisor) | 台股 multi-agent / FastAPI / React / ML | 多 agent 分工、Web app 架構 | baldr 目前更強在 no-look-ahead 與 evidence governance；不建議短期引入 17-agent 複雜度。 |
| [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | 強化學習、Gym-style market environment | market state / action / reward 抽象 | 近期不採 RL。可把 Market Regime 當 state 的概念留作長期研究，不進 V1.5-V2.0 主線。 |

### 3.5 Screener 類小型專案

| 專案 | 主要做什麼 | 可參考做法 | baldr 現況對比 |
|---|---|---|---|
| [xang1234/stock-screener](https://github.com/xang1234/stock-screener) | 基本篩選器 / watchlist 類工具 | 簡潔條件式 screener 與使用者輸入流程 | baldr 已有推薦、Watchlist、Why Not 與 evidence；可參考條件矩陣 UI，不需降級成單純 screener。 |
| [starboi-63/growth-stock-screener](https://github.com/starboi-63/growth-stock-screener) | 成長股篩選與財務條件 | growth metrics、基本面條件篩選 | baldr Fundamental Layer 已能保守輸出 diagnostics；V1.7 可以把基本面條件納入 screening matrix，但仍不進 `ScoringEngine`。 |
| `x-qa/stock-screener-service` | 無法穩定確認公開可用內容 | 暫不採用 | 不作 roadmap 依據；若未來提供 repo 內容再重新審查。 |

---

## 4. baldr 已經與外部專案相同或更嚴謹的部分

baldr 目前已經具備下列能力，不需要從零重做：

- **SQLite-first 本地資料底座**：與 Freqtrade / OpenBB 的本地資料思想類似，但更聚焦台股資料與 UI workflow。
- **Research Run Registry**：方向接近 Qlib recorder / research workflow，已能保存 metadata、hash、Parquet 明細、比較與 promote gate。
- **No-look-ahead governance**：已建立 FactorGate `available_date <= decision_date`、fixed / quantile Expanding T-1 與推薦 eligible universe boundary。
- **Evidence Event Store**：已能保存 Recommendation、Watchlist、Portfolio Alert、Risk Prompt、Why Not / Liquidity 類 evidence event 與 forward outcome。
- **Manual lifecycle boundary**：已能產出 promote / hold / demote_candidate / retire_candidate，但不自動改策略或刪除歷史版本。
- **Portfolio feedback**：已有來源追溯、condition monitor、chip monitor、lifecycle review 與 live-vs-research gap linkage v1。
- **資料品質語彙**：`OBSERVED` / `ESTIMATED` / `DEGRADED` / `MISSING` 已貫穿 Daily Decision、Smart Money、Portfolio Alert 與 Evidence Review。

因此下一步不是「學一個大神 repo 然後重寫 baldr」，而是把外部專案成熟的治理模式吸收到現有 scoped architecture 中。

---

## 5. 資料源補強優先序

### P0：先補，直接影響可信度

1. **除權息 / 還原價 / corporate action timeline**
   - 目的：避免長期技術指標、forward return 與回測因事後還原價產生偏差。
   - V1.5 狀態：已建立 raw / decision-date adjusted candidate / full hindsight adjusted policy inspection；尚未 ingest 正式 corporate action timeline 或建立 adjusted price series。
   - Done：每個價格序列可標示 raw / adjusted policy；任何 adjusted series 都有 decision-date 可得性聲明。

2. **處置股 / 分盤 / 全額交割 / 漲跌停鎖死**
   - 目的：讓 microstructure preflight 從 optional source 變成 governed source。
   - V1.5 狀態：已在推薦組合 replay preflight 輸出 governed source metadata、status 與 missing policy；尚未接正式外部 source。
   - Done：source、available_date、quality、missing policy 完整，並能進 Why Not / Portfolio Alert。

3. **Evidence source gap 修補**
   - 目的：why-not / liquidity exclusion payload、watchlist 實際事件、portfolio active positions 能穩定進 evidence pipeline。
   - V1.5 狀態：centralized `EvidenceSourceCoverageService` 已將 durable source 缺口列為 blocking gaps，why-not / liquidity optional payload 缺口列為 warnings / `dry_run_only`；完整 negative evidence 仍待 V1.7。
   - Done：source coverage 不再把 optional payload 缺口列為 blocking gaps；仍需樣本累積後才判斷有效性。

4. **Data Source Capability Registry**
   - 目的：先記錄每個資料源能提供什麼、延遲多久、可不可信，再決定是否進 factor。
   - V1.5 狀態：已建立 read-only registry 與 inspection CLI，涵蓋 price、evidence、corporate action candidate 與 microstructure candidate sources。
   - Done：每個新 source 都有 source id、欄位、可得日、延遲、授權 / rate limit、missing policy、可回溯程度。

### P1：下一輪補強，支援更好的市場判讀

1. **三大法人**
   - 補 Smart Money / Chip Flow 的外資、投信、自營商維度。
   - 不得直接把單日法人買超變成買進理由。

2. **信用交易**
   - 補融資 / 融券、擁擠度、斷頭與軋空風險。
   - 優先放 Why Not / Risk Prompt，而不是 scoring。

3. **TDCC / 集保持股分散**
   - 補籌碼集中、散戶 / 大戶結構與變化。
   - 適合放 V1.6/V1.7 的 factor pipeline 與 screening matrix。

4. **Concept Basket / 題材籃子**
   - 補官方產業分類不能捕捉台股題材輪動的限制。
   - 需保存成分股版本與有效日期。

5. **P/B、P/S governed observations**
   - 只能由 governed external observations 或明確 backfill records 進入，不能在系統內臨時推導分子 / 分母。

### P2：長期研究，不進近期主線

- Broker real-time / order API：先只作 virtual account / event sourcing 參考，不自動交易。
- News / text / LLM theme extraction：需先有 source governance 與 hallucination boundary。
- Options / futures / ETF flows：除非 Daily Decision 明確需要，否則先不擴張。
- Reinforcement learning / FinRL：過擬合風險高，待 evidence layer 與 dataset registry 成熟後再做研究 sandbox。
- GPU / cuFOLIO：只在 portfolio optimization 批次規模與 CPU bottleneck 被量測證明後才評估。

---

## 6. V1.5 至 V2.0 版本形狀

### V1.5：Data Credibility & Corporate Action Gate

目的：讓 forward outcome、長期回測、技術指標與 Portfolio replay 的價格基礎更可信。

核心交付：

1. Data Source Capability Registry v1。
2. corporate action / adjusted price policy 文件與資料表候選設計。
3. microstructure governed source preflight：處置股、分盤、全額交割、漲跌停鎖死。
4. evidence source gaps 修補：why-not / liquidity payload、watchlist / portfolio source coverage。

2026-07-04 v1 closeout：上述 governance layer 已完成第一版，包括 read-only registry / CLI、corporate action policy / CLI、microstructure governed metadata 與 shared source coverage service。尚未接入正式外部資料、未建立 adjusted price series，也未把 optional payload 升級為完整 negative evidence。

不做：

- 不改 `ScoringEngine`。
- 不導入新黑箱模型。
- 不啟用 production evidence write-mode scheduler。

### V1.6：Cross-sectional Factor Pipeline & Sector Rotation v2

目的：參考 Qlib / Zipline，把每日橫斷面特徵、產業 / 題材輪動與資料品質寫成可追溯 pipeline。

核心交付：

1. Daily factor snapshot pipeline：market, sector, concept, liquidity, smart money, fundamental diagnostics。
2. Sector Rotation v2：官方產業 + concept basket，支援成分版本與 available_date。
3. Factor quantile / rank 保存到 SQLite，與 Research Run Registry / Evidence Event Store 可串接。
4. 初版 factor attribution dashboard 或 CLI summary。

不做：

- 不把三大法人 / 信用 / 基本面直接硬塞進 scoring。
- 不把 factor rank 直接當推薦結果。

### V1.7：Screening Matrix & Negative Evidence

目的：把推薦、排除、低流動性、資料品質、watchlist trigger、portfolio alert 的判斷做成同一套可檢查矩陣。

核心交付：

1. Screening Matrix：pass / fail / degraded / skipped / missing。
2. Why Not / Liquidity exclusion payload 持久化完成。
3. Negative evidence 與 recommendation evidence 同等地位，能進 forward outcome。
4. Growth / fundamental screener 只以 diagnostics / gate 形式呈現，不進核心 score。

不做：

- 不自動降低策略版本。
- 不把「被排除」解釋成一定會下跌。

### V1.8：Portfolio Construction & Execution Trace Sandbox

目的：讓研究層可以比較配置、限制、交易生命週期與 execution gap，但仍維持不自動下單。

核心交付：

1. research-only portfolio construction sandbox：等權、分數權重、risk parity / constrained allocation 候選。
2. PyPortfolioOpt-style constraints / risk model adapter，所有輸出標示為 research basis。
3. Event sourcing model：Order Created -> Submitted -> Partially Filled -> Filled / Cancelled / Rejected 的虛擬事件生命週期。
4. Portfolio replay residual：零股、買賣價差、完整撮合、gap actual execution model、未成交原因。

不做：

- 不串 production broker 下單。
- 不導入 Nautilus / vn.py 完整交易引擎。
- 不導入 cuFOLIO，除非 portfolio optimization bottleneck 被量測證明。

### V1.9：Read-only Agent / MCP Evidence Access

目的：讓 AI 能查詢 baldr evidence、資料品質與覆盤歷史，協助產生摘要與問題清單，但不能代替治理。

核心交付：

1. 本地 read-only MCP server 或等價 tool surface。
2. Evidence / Research Run / Portfolio Review 查詢 schema。
3. Agent permission model：只能 read，不得 write DB、不得改策略、不得下單、不得自動 lifecycle action。
4. AI report template：只引用 evidence rows、quality、warnings 與 source trace。

不做：

- 不讓 LLM 直接輸出買賣指令。
- 不把 AI-generated thesis 當成 evidence。

### V2.0：Unified Decision Workbench

目的：當 V1.5-V1.9 讓資料、因子、負面證據、portfolio sandbox 與 read-only AI 都有足夠 governance 後，再重整資訊架構。

V2.0 應長成：

1. 第一畫面是「今日決策任務」，不是功能分頁清單。
2. Daily Decision、Market Watch、Evidence Review、Portfolio Review 成為同一個工作流。
3. 每個候選股票都能看到：Why、Why Not、Risk、Evidence、Forward outcome、Live gap、Data quality。
4. 每個策略都能看到：有效範圍、失效範圍、近期 decay、manual lifecycle candidates。
5. 舊 Tab 保留為 drill-down / expert mode，避免資訊架構重整破壞既有研究能力。

---

## 7. 明確不納入近期 Roadmap 的項目

- **SQLite async / split DB 改造**：使用者已指示先不動。後續只有在真實寫入 lock / throughput bottleneck 被量測證明後，才重開設計。
- **Production auto trading**：不做。券商 API 只可作行情、帳務或 virtual execution trace 參考。
- **強化學習主線**：不進 V1.5-V2.0。可留長期 sandbox，但需 dataset registry、walk-forward 與 overfit guard。
- **GPU-first portfolio optimization**：不做。先用向量化、NumPy / pandas / Numba、合理批次與單 writer 寫入治理。
- **AI 自動升降級**：不做。LLM 只能生成摘要與審核問題，lifecycle action 仍需人工核准。

---

## 8. 對現有 Roadmap 的審查結論

### Vision

不建議大幅改寫。Vision 已正確保存 North Star、Evidence Requirement、Gap Register 與非目標。這輪只需補上本文件連結，避免外部專案清單污染願景層。

### V1.1 至 V2.0 版本路線

原文件已準確標示 V1.1 至 V1.4 完成。2026-07-04 已完成 V1.5 v1 的資料可信度治理層；V1.6 至 V1.9 仍是 V2.0 前的中繼版本，而不是把 V2.0 直接提前。

### 6M Roadmap

6M Roadmap 的主線仍合理：Evidence-Driven baldr、資料治理、Factor Layer、Daily Decision、Portfolio Feedback。外部參考校準後的版本化重排已完成 V1.5 資料可信度治理層；後續順序仍是 V1.6 因子管線、V1.7 negative evidence、V1.8 portfolio sandbox、V1.9 read-only AI。

### Roadmap Hub

Roadmap Hub 不應保存完整外部分析。V1.5 v1 已完成後，它只需保留本文件為 companion，並把 Next 的短版維持在「累積 evidence，同時準備 V1.6-V1.9 的版本化路線」。

---

## 9. 更新記錄

- 2026-07-04：新增外部專案參考與 V1.5-V2.0 版本藍圖；確認 Vision 不大幅改寫，外部參考由本 companion 承接；將 cuFOLIO / RL / broker API / SQLite split 等高成本方向列為 deferred，短中期聚焦資料可信度、cross-sectional factor pipeline、negative evidence、portfolio sandbox 與 read-only AI。
- 2026-07-04：完成 V1.5 Data Credibility & Corporate Action Gate v1 的治理層 closeout，標記 registry、policy、microstructure metadata 與 source coverage service 已落地；正式資料 ingestion、adjusted price series 與完整 negative evidence 仍移交後續版本。
