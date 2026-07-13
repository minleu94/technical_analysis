# V2.4 Paper Portfolio Baseline

> 日期：2026-07-12
> 狀態：第一個真實 saved-Recommendation paper baseline 已建立；不是 V2.4 formal closeout。

## 輸入與政策

- 輸入：`scheduled_rec_20260712_051002.json`，3 筆已保存 Recommendation。
- 核准政策：NT$500,000、minimum cash 2,000 bp、max positions 8、單檔上限 1,500 bp、整股 lot 1,000 股。
- 產物：`D:/Min/Python/Project/FA_Data/output/paper_portfolio/baseline_20260712.json`。

## 結果

| 股票 | Score bp | Target bp | Constrained bp | 紙上股數 | 紙上金額 |
|---|---:|---:|---:|---:|---:|
| 1615 大山 | 6622 | 3582 | 1500 | 1000 | 46,400 |
| 1536 和大 | 6559 | 3547 | 1500 | 1000 | 55,000 |
| 1418 東華 | 5309 | 2871 | 1500 | 3000 | 57,600 |

- 紙上可執行總額：NT$159,000。
- 殘餘現金：NT$341,000。
- `research_only=true`、`writes_positions_db=false`、`broker_order_allowed=false`、`auto_rebalance_allowed=false`。

## 判讀

本產物證明 approved policy 可消費真實 saved Recommendation 並產生可追溯 target / constrained / lot-sizing baseline。它尚無後續交易日 paper NAV、成本後比較、Equal Weight 對照或 decision journal，因此只完成第一個觀察起點，不構成 V2.4 formal closeout 或投資有效性。
