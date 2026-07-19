# P0 官方來源 parser fixtures

這些 fixture 是依 2026-07-13 官方公開端點 schema 擷取後縮減的最小、去識別測試樣本，只保留 parser contract 所需欄位，不含 token、cookie 或大量原始資料。

| 檔案 | 官方端點 | schema / capture 證據 |
|---|---|---|
| `twse_institutional.json` | `https://www.twse.com.tw/fund/T86` | TWSE `fields` + `data` JSON；capture date 2026-07-13 |
| `twse_credit.json` | `https://www.twse.com.tw/exchangeReport/MI_MARGN` | TWSE `tables[].fields/data` JSON；capture date 2026-07-13 |
| `tdcc_shareholding.csv` | `https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5` | TDCC Open Data CSV header；capture date 2026-07-13 |
| `twse_disposition.json` | `https://www.twse.com.tw/announcement/punish` | TWSE `fields` + `data` JSON；公布日期與處置起迄日是民國日期，官方 payload 未提供可驗證 publication timestamp；capture date 2026-07-18 |
| `twse_ex_dividend.json` | `https://www.twse.com.tw/exchangeReport/TWT49U` | TWSE 除權除息計算結果表；資料日期是生效日，不是公告 timestamp；capture date 2026-07-18 |
| `twse_reduction.json` | `https://www.twse.com.tw/exchangeReport/TWTAUU` | TWSE 股票減資恢復買賣參考價格；恢復買賣日期不是公告 timestamp；capture date 2026-07-18 |

Fixture 中的數值是最小合成列；欄名、容器形狀與日期格式依 captured official schema 固定。fixture 不構成來源 license acceptance 或正式 source acceptance。
