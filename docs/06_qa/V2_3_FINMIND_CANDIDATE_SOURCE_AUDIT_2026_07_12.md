# V2.3 FinMind Candidate Source Audit

> 日期：2026-07-12
> 狀態：candidate mapping；不代表 source acceptance、正式 ingestion 或 downstream eligibility。

## 可驗證的資料集對應

| V2.3 P0 項目 | FinMind dataset | 初步可用性 | 必要限制 |
|---|---|---|---|
| 三大法人 | `TaiwanStockInstitutionalInvestorsBuySell` / `Wide` | Free；官方文件標示日更約 20:00 | 必須保存 fetch timestamp / source version，且以可取得時間而非交易日作 `available_date`。 |
| 信用交易 | `TaiwanStockMarginPurchaseShortSale` | Free；官方文件標示日更約 21:00 | 同上；資料未完成前不可用於同日 decision。 |
| 集保持股分級 | `TaiwanStockHoldingSharesPer` | Backer / Sponsor | 須先確認帳號 tier、FinMind 與 TDCC 使用／再散布條款、週資料 available-date。 |
| 停牌 / 復牌 | `TaiwanStockSuspended` | Backer / Sponsor | 須驗證公告、停牌及復牌時間語意；不以缺席價格推定。 |
| 漲跌停限制 | `TaiwanStockPriceLimit` | Free | 僅作可成交性 / restriction diagnostics；不替代成交或流動性證據。 |
| 除權息 / 除權 | `TaiwanStockDividend` / `TaiwanStockDividendResult` | dataset 存在 | 必須逐事件驗證公告 / 生效 / available-date 與 adjusted-price policy。 |
| 面額變更 | `TaiwanStockParValueChange` | dataset 存在 | 仍需逐事件 PIT / coverage / correction policy。 |
| 月營收 | `TaiwanStockMonthRevenue` | dataset 存在 | 不可把資料列日期假定為原始公告日；PIT mapping 必須另驗證。 |

## API / 取得契約

- API base：`https://api.finmindtrade.com/api/v4`；以 Bearer token 呼叫。
- 官方完整文件列示 token 為每小時 600 requests、無 token 為每小時 300 requests；實作必須有 token presence check、rate limiter、429 / 402 retry backoff、raw response hash、fetch timestamp 與 source-version capture。
- FinMind tier 對 Backer / Sponsor dataset 的可用性取決於帳號權限；沒有權限時必須記錄 `source_access_not_authorized`，不得 fallback、爬取或偽造資料。

## 尚不可補完的項目

- 處置、分盤、全額交割等交易限制尚須官方來源 manifest、公告時間與使用條款驗證。
- 減資 / 分割的完整事件 contract、PIT 季度財報公告日及資料修訂語意仍需正式來源／mapping。
- FinMind 的資料集存在不等於決策當時可得；任何未有 explicit `available_date` 的 row 仍為 `eligibility=none`。

## 實作前必要設定

使用者需在本機安全設定 `FINMIND_API_TOKEN`（不要寫進 repo 或聊天訊息）。未提供 token 時，只能進行 dataset manifest / free-tier access probe，不進行大範圍下載或 formal coverage declaration。

## 來源

- [FinMind Complete API & Dataset Reference](https://finmind.github.io/llms-full.txt)
- [FinMind API Swagger](https://api.finmindtrade.com/docs)
