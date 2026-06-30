# PySide6 UI

`ui_qt/` 是目前主要使用者介面。主入口：

```powershell
.\.venv\Scripts\python.exe ui_qt\main.py
```

完整操作見 [APPLICATION_MANUAL.md](../docs/07_guides/APPLICATION_MANUAL.md)。

## 架構邊界

UI 層負責：

- 收集使用者輸入
- 呼叫 `app_module` service
- 顯示 DTO、DataFrame 與圖表
- 將長任務交給 worker

UI 層不應直接承擔：

- 原始資料抓取與合併
- 策略評分與推薦理由計算
- 回測撮合與績效計算
- Portfolio domain 規則
- Runtime 核心狀態機

## 頂層工作區

1. 數據更新
   - 快速更新與安全更新
   - 個別資料來源維護
   - 技術指標增量/全量計算
   - CSV 匯出
   - SQLite Inspector

2. 市場觀察
   - 大盤 Regime
   - 強勢/弱勢個股
   - 強勢/弱勢產業
   - Smart Money 個股與分點追蹤

3. 每日決策
   - Market Breadth、Sector Rotation、Relative Strength / Liquidity Ranking
   - Watchlist Trigger、Portfolio Alert 與 fundamental risk prompts
   - answer-first dashboard 與資料品質 / warning 揭露

4. 策略回測
   - 單股、批次、固定組合、推薦回放、策略研究
   - 參數最佳化與 Walk-forward
   - fixed / quantile 雙模式
   - 保存、比較、Promote 與 Portfolio 來源追溯

5. 推薦分析
   - 新手/進階模式
   - Profile、Regime 建議、Why / Why Not / Explain
   - fixed / eligible-universe 百分位排名
   - 候選池、批次回測、推薦回放與 Portfolio 入口

6. 觀察清單
   - 候選池
   - 選股清單 Universe CRUD
   - Research Lab 輸入準備

7. 持倉管理
   - 手動交易與來源追溯
   - 持倉、交易歷史與覆盤日誌
   - 策略/價格、停損停利與籌碼監控
   - Smart Money 下鑽

8. Runtime Observatory
   - FSM 狀態
   - 治理健康
   - append-only event stream

## 主要目錄

```text
ui_qt/
├── main.py
├── tab_info_config.py
├── views/
│   ├── update_view.py
│   ├── market_regime_view.py
│   ├── strong_stocks_view.py
│   ├── weak_stocks_view.py
│   ├── strong_industries_view.py
│   ├── weak_industries_view.py
│   ├── recommendation_view.py
│   ├── decision_desk_view.py
│   ├── watchlist_view.py
│   ├── backtest_view.py
│   ├── backtest/
│   ├── smart_money/
│   ├── portfolio_view.py
│   └── runtime_view.py
├── models/
├── widgets/
├── workers/
└── bridges/
```

## 目前已完成

- Phase 1、Phase 2、Phase 2.5 核心能力
- Phase 3.1、3.2、3.3a、3.3b 研究閉環
- Portfolio Phase 4.1 與籌碼下鑽能力
- Runtime Observatory MVP
- Smart Money Terminal MVP
- Daily Decision Desk v1 主 UI 入口
- SQLite DB-first 與 CSV fallback
- fast chart renderer 與 Matplotlib fallback
- 批次回測並行化與合作式取消
- Strategy & Scoring Governance 機制回歸
- Research Run Registry、Cross-run Comparison、Indicator Parameter Registry、Recommendation Weight Contract 與 Month 6 lifecycle / Portfolio feedback 入口

## 目前 Backlog

以 [ROADMAP_6M_ENGINEERING.md](../docs/00_core/ROADMAP_6M_ENGINEERING.md) 為準，近期包括：

- 全 UI 健檢與 release healthcheck runner 收斂
- Month 6.1 lifecycle QA、manual approval workflow、Review Dashboard 與 Evidence Explainability
- PDF 規格化研究報告輸出

## UI 修改驗證

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```
