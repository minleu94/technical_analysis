# V2.4 Paper Portfolio Policy Approval

> 日期：2026-07-12
> 決策人：使用者
> 決策：核准下列平衡風險 paper-only policy 作為 V2.4 baseline。

| 參數 | 核准值 |
|---|---:|
| initial paper capital | NT$500,000 |
| minimum cash | 2,000 bp（20%） |
| max positions | 8 |
| per-position cap | 1,500 bp（15%） |
| sector / concept cap | 3,000 bp（30%） |
| rebalance band | 300 bp（3%） |
| minimum trade | 200 bp（2%） |
| weekly turnover cap | 2,000 bp（20% NAV） |
| same-symbol cooldown | 5 trading days |
| paper buy / sell slippage | 10 bp each side |
| paper commission | 15 bp each side |
| common-stock sell tax baseline | 30 bp |

## 邊界

- 本 policy 只適用 paper / research simulation，不是實際下單指令或 broker 設定。
- ETF、權證、期貨、零股與不同費率商品不可直接套用 30 bp 股票賣出稅 baseline；必須另列 cost model。
- 資料品質、可成交性、交易限制、風險預算或 portfolio source 不成立時，系統維持 `NO_NEW_POSITION` 或 fail-closed diagnostics。
- 任何真實持倉、broker、auto-rebalance、auto-exit 仍未獲授權。
