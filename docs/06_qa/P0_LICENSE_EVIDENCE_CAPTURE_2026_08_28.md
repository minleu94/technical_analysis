# P0 License Evidence Capture（2026-08-28）

## Capture result

在明確的 `capture-p0-license-evidence` confirmation 下，對 route registry
allowlist 的 3 個唯一條款／OpenAPI URL 各發出一次 bounded GET。工具只保存 response
metadata、bytes hash 與 bounded keyword flags，不保存頁面全文，也沒有修改 source
acceptance registry、market SQLite、Scoring／Advice、scheduler 或 broker。

| URL | 結果 | HTTP | content SHA-256 |
|---|---|---:|---|
| `https://openapi.tdcc.com.tw/`（final `/swagger-ui/index.html`） | `captured` | 200 | `da32064601d2c8d87d196e9c75377ff3af8e0247babae0d4c4f78bf9fff601db` |
| `https://www.twse.com.tw/zh/terms/use.html` | `captured` | 200 | `ae9fa0704103fbae0ed61173a83cf55dca36dba2f7c86936fc018c4c39fb0c2c` |
| `https://www.tpex.org.tw/web/inc/gtsm_disclaimer.php?l=zh-tw` | `http_error` | 520 | — |

候選輸出：

`C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_license_evidence_capture_20260828_110645.json`

這次 capture 的 `captured_count=2`、`failed_count=1`。把它載入 P0 Source Control
Center 後，TWSE／TDCC 的 machine evidence 指紋可見，TPEX 條款仍為 HTTP error；整體
仍是 `13 blocked_provenance`、`accepted=0`、`limited=0`、`downstream_eligibility=none`。

## 尚未解除的治理條件

response fingerprint 不是 license acceptance。13 個 source 仍各需要具名 owner／
reviewer 決議、允許的 use-case／再分發政策、publication／available／PIT lineage、
quality／coverage 與 rollback／quarantine 證據；TPEX 條款 endpoint 還需要重新觀測或
由 owner 提供可驗證的官方條款證據。未完成前不得把 candidate route 接入 Scoring、
Formal OOS、production ingestion 或 scheduler。

## Re-run

```powershell
.\.venv\Scripts\python.exe scripts\capture_p0_license_evidence.py `
  --decision-date 2026-08-28 `
  --confirm capture-p0-license-evidence `
  --output <NEW_TEMP_JSON>
```

同一 output 不應覆寫；若網路不可用，保留 `transport_error`／`http_error` 診斷，不以
舊 capture 或猜測補值。

