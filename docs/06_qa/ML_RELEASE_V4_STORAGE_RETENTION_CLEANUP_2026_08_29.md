# ML Release v4 Storage Retention Cleanup — 2026-08-29

## 結論

2026-08-28（America/Los_Angeles）依使用者明確指示，對
`D:/Min/Python/Project/FA_Data/output/release_v4` 執行一次人工 retention 清理；
清理後於 2026-08-29 重新盤點。三個主要 ML artifact root 合計由
`631,570,753,299` bytes 降為 `197,836,559,482` bytes，釋放
`433,734,193,817` bytes（約 `403.95 GiB`）。Post-cleanup inventory 於
`2026-08-28T23:48:53-07:00` 觀察到 D 槽可用 `440,561,684,480` bytes（約
`410.31 GiB`），20 GiB filesystem headroom 檢查已由實體容量觀察改為通過。

這次處置只清理 immutable ML publication／training run，沒有刪除、搬移或改寫
`FA_Data/sqlite`、原始市場資料、CSV source、Paper ledger、Evidence DB 或 Research
Registry。也沒有把資料搬到 `E:`。容量 blocker 的實體原因已解除，但 Formal input、
Paper fills、P0 source acceptance、technical production canary 與 scheduler／broker
權限不會因此自動完成。

## 授權、範圍與不可逆性

- 使用者先要求刪除未完成 run，之後明確指示「執行平衡清理，四個 resume 也刪除」。
- 目標只限 `D:/Min/Python/Project/FA_Data/output/release_v4` 下三個明確 root：
  - `ml_pit_year_shards`
  - `portfolio_ml_direct_numeric_production_v4_v2`
  - `portfolio_ml_direct_ooc_training_production_v4_v5`
- 每批刪除均使用已解析的 exact literal path；未使用 wildcard、遞迴 root 清除或跨磁碟搬移。
- 刪除前檢查 latest pointer、保留鏈依賴與 active Python／maintenance custody；刪除後逐項確認目標不存在並重跑完整 metadata inventory。
- 沒有為刪除的 immutable run 建立另一份備份。若未來需要，只能依 builder／source
  重新產生；因來源與 cutoff 可能改變，不能保證重建 bytes 與原 artifact 完全一致。

## 清理前後容量

清理前 PIT／Direct 數字取自 combined host inventory
`ml_storage_retention_inventory_host_20260828_v3.json`（SHA-256=
`0C6169053B482296A51F441AF21847158A7DB146C59875516445B00C756CC8CD`）；該檔的
OOC root 因 file limit 截斷，不用它的 OOC bytes。OOC 清理前數字改取完整 deep scan
`ml_storage_retention_inventory_ooc_host_20260828_v3.json`（SHA-256=
`5950784709288C7361F654ABB50BD3AC0B2851F0EFB52666CB4F93163814628D`，
`scan_truncated=false`）。清理後三個 root 則取自本文件「驗證證據」列出的完整
post-cleanup inventory；因此表內每一個 per-root bytes 都有未截斷掃描來源，但不是由
單一 before artifact 提供。

| Layer | 清理前 | 清理後 | 釋放 |
|---|---:|---:|---:|
| PIT year shards | 358,945,569,578 bytes（334.29 GiB） | 128,935,606,790 bytes（120.08 GiB） | 230,009,962,788 bytes（214.21 GiB） |
| Direct numeric | 165,423,387,694 bytes（154.06 GiB） | 35,905,933,278 bytes（33.44 GiB） | 129,517,454,416 bytes（120.62 GiB） |
| OOC training | 107,201,796,027 bytes（99.84 GiB） | 32,995,019,414 bytes（30.73 GiB） | 74,206,776,613 bytes（69.11 GiB） |
| **合計** | **631,570,753,299 bytes（588.20 GiB）** | **197,836,559,482 bytes（184.25 GiB）** | **433,734,193,817 bytes（403.95 GiB）** |

清理分三批完成：

| 批次 | 行為 | 釋放 |
|---|---|---:|
| Exact duplicate／empty cleanup | 2 個完整 exact duplicate、2 個 empty／failed Direct 目錄 | 11,806,896,809 bytes（11.00 GiB；由完整 inventory 差額核對） |
| Resume／partial cleanup | 2 個 Direct、2 個 OOC 未完成 run | 57,372,564,792 bytes（53.43 GiB） |
| Balanced historical retention | 11 個 PIT、12 個 Direct、12 個 OOC 完整歷史 run | 364,554,732,216 bytes（339.52 GiB） |

## 已刪除 run

### Exact duplicate／empty／failed

- `direct-ooc-04045b348c6fd97c4e0de8fa`
- `direct-ooc-95cd49becd293ab30b2ae3e4`
- `direct-ooc-4286e964b2cf71309e1d4b03`
- `direct-ooc-b594a8b6a69136dfe7546bed`

### 未完成 resume／partial

- `direct-ooc-4959f5d2ecd3b9c63587c32e`
- `direct-ooc-b7602830c1fecd263398238b`
- `allocation-ooc-c342411c05015596f5e3e394`
- `allocation-ooc-12ab3028323300779ff3dfaa`

刪除 resume 的意思是放棄從該 checkpoint 接續，不是放棄整個 PIT／Direct／OOC
能力。後續若需同一 cutoff，必須從仍存在的 upstream publication 或正式 source 重跑；
不得把已刪 checkpoint 標成 completed。

### Balanced PIT historical runs

- `pit-12a0e354d4858497733759ff`
- `pit-1f0dd90e2a23ef2332923dfd`
- `pit-283b74f4aae111cce8cf6ce3`
- `pit-8534d95c308072e2bdfe4bc1`
- `pit-8d4b268620dfeb5247434efe`
- `pit-9aa4e9d4d74d6978e570c61e`
- `pit-a1edd6829bc124c80794b1fb`
- `pit-a8d1c76c1df4b7197264ae64`
- `pit-b816bc65bf5e8db3498799ea`
- `pit-d8cf045217fdd03d1bf8ae57`
- `pit-ed0ec633b015ce21a6a66e93`

### Balanced Direct historical runs

- `direct-ooc-2193e8c7e8d91fd8629086fd`
- `direct-ooc-5542aa711e7b36b0bcbcd6c8`
- `direct-ooc-6697b9ba925645f6aa6b0880`
- `direct-ooc-7f280fd1d6944afdd9756821`
- `direct-ooc-8722f1b16cfacaf93c54d1a3`
- `direct-ooc-96b90820308bfd7bb3fdcd95`
- `direct-ooc-96f3d103b6f72b7147d8d405`
- `direct-ooc-bb77937cc9a45c4318d6270f`
- `direct-ooc-dbb2dd1ab7a66c82d8626ed3`
- `direct-ooc-df753dacfb2e7afa05e6329b`
- `direct-ooc-e57112940bcc2b07f99c41d6`
- `direct-ooc-ebe3b30354d43aca9e505b59`

### Balanced OOC historical runs

- `allocation-ooc-4f9218abc874896dc7a2f96b`
- `allocation-ooc-69870fc40af3e71f7d3e563f`
- `allocation-ooc-6b8cb6575232ed90342984a8`
- `allocation-ooc-76c99234ec90c515998a8ac3`
- `allocation-ooc-789fce44ac1e4f91391d59bf`
- `allocation-ooc-7af095e904ba530cd1ce94c7`
- `allocation-ooc-844649b94de4d5bc628bada8`
- `allocation-ooc-88756fba5c73ce52d37243ec`
- `allocation-ooc-9018233cad0add36730313ad`
- `allocation-ooc-c95eadf25b87fa699ce6c2f3`
- `allocation-ooc-f3b51e10713037e4ca4d271b`
- `allocation-ooc-f81d9eb64dc920a8615896b4`

## 保留鏈與 current pointer

清理採「current pointer + 可追溯完整鏈 + 少量歷史基線」原則，不是依模型績效排名。
保留的 OOC → Direct → PIT manifest dependency 如下：

| PIT publication | Direct store | OOC training |
|---|---|---|
| `pit-4a860a5fa18add4e0e15f2aa` | `direct-ooc-73f491054fdfac318cb5c1f2` | `allocation-ooc-99c60a4209d58e58bc28bc48` |
| `pit-29505ceb0005d068610dde01` | `direct-ooc-09dabea3b84115b2d5e4b753` | `allocation-ooc-2416e7265c6f3c15072173c6` |
| `pit-a2f236fefac769e7346e04be` | `direct-ooc-6ff7650245ffea99ced5bf21` | `allocation-ooc-9750e409b0622fb4472a1a0f` |
| `pit-a2f236fefac769e7346e04be` | `direct-ooc-815952ad0901725627a8bfb0` | `allocation-ooc-aab7ec6a692afb9a9a52093f` |
| `pit-53d01cdb01c49b256611526f` | `direct-ooc-8857f844bdb4ea81c9b292c0` | `allocation-ooc-f41f68ddcbf012b6b53dff3d` |
| `pit-edfff7906a0c27861b602ef0` | `direct-ooc-94355ffac5a541dbd9cb7282` | `allocation-ooc-05fd4dd6515cddfdf6e0228d` |

另外保留尚未被上述 Direct stores 消費的 current PIT publication
`pit-dcae710a1657d06d36843a00`。清理後各 layer 都是 6 個完整 run。

| Pointer | 指向 | Pointer file SHA-256 |
|---|---|---|
| PIT `latest_manifest.json` | `pit-dcae710a1657d06d36843a00` | `82B1293E0E12C9A75AF77466E37B8CB7513723C8EB953847AC258A1FC626C24B` |
| Direct `latest_manifest.json` | `direct-ooc-8857f844bdb4ea81c9b292c0` | `FD350D29F81DF8B3E9873E6E6B20F6B02751DBD52A039231C133E1554B7321D0` |
| OOC `latest_manifest.json` | `allocation-ooc-f41f68ddcbf012b6b53dff3d` | `D661FB3D76D1E447485B0594DF8F699B7896ED46BFFDBF2CC6D1DE21075DD74D` |

OOC current pointer 仍明示 `formal_oos_allowed=false`、`production_alpha_bp=0`、
`broker_order_allowed=false`。保留完整鏈不等於 promotion 或 production ML 已通過。

## 歷史 reference tombstone

Repository 的 `runbook_ml_revalidation_revision5.json` 與
`runbook_ml_revalidation_revision6.json` 仍保留歷史未完成 checkpoint
`direct-ooc-df753dacfb2e7afa05e6329b`。兩份 runbook 是 append-only／歷史證據，
因此沒有把 ID 偷換成另一個 retained run。

這個 ID 現在必須視為 retention tombstone：

- 它不是 PIT、Direct 或 OOC 的 current pointer。
- 它在 runbook 中本來就記錄 `direct_ooc_checkpoint_complete=false`。
- 該實體目錄已刪除，不能再宣稱可以由原 checkpoint resume。
- 若需重做 revision 5／6 的驗證，只能從相符 upstream raw manifest 重新建 Direct；
  新 run 必須取得新 identity，不能沿用已刪 run ID。

其餘 42 個已刪 ID 在 tracked repository 文件／設定中沒有命中；current pointer
與 retained dependency closure 均未指向已刪目標。

## 2026-09-03 follow-up balanced retention

2026-09-03 依使用者選定的「保留最新 6 組」方案，再次對同一個
`release_v4` 範圍執行人工清理。這一批只處理已完成、較舊的四組 PIT 及其
唯一 Direct／OOC dependency closure；沒有刪除原始 SQLite、CSV、官方事件、
evidence DB 或目前 latest pointer。實際移除 14 個 exact literal run 目錄，
目錄 byte inventory 合計約 `134.258 GiB`。

本批刪除的 immutable run（均視為 retention tombstone，不可再宣稱可由原
checkpoint resume）如下：

- PIT：`pit-a2f236fefac769e7346e04be`、`pit-29505ceb0005d068610dde01`、
  `pit-edfff7906a0c27861b602ef0`、`pit-4a860a5fa18add4e0e15f2aa`
- Direct：`direct-ooc-6ff7650245ffea99ced5bf21`、
  `direct-ooc-815952ad0901725627a8bfb0`、
  `direct-ooc-09dabea3b84115b2d5e4b753`、
  `direct-ooc-94355ffac5a541dbd9cb7282`、
  `direct-ooc-73f491054fdfac318cb5c1f2`
- OOC：`allocation-ooc-9750e409b0622fb4472a1a0f`、
  `allocation-ooc-aab7ec6a692afb9a9a52093f`、
  `allocation-ooc-2416e7265c6f3c15072173c6`、
  `allocation-ooc-05fd4dd6515cddfdf6e0228d`、
  `allocation-ooc-99c60a4209d58e58bc28bc48`

清理後驗證：PIT 保留 6 組（`pit-a33caaed7d27ae4aa3320a91`、
`pit-0f16248a939f2075b113abca`、`pit-047d45eb6ee0bee84c3ba8c6`、
`pit-f8b6e39444f24a3487bf2fb2`、`pit-f62b6b24b4c2f32331fc92a5`、
`pit-53d01cdb01c49b256611526f`），三個 latest pointer 仍分別指向
`pit-a33caaed7d27ae4aa3320a91`、`direct-ooc-bb5d1c65006fc963c5817439`、
`allocation-ooc-807f308529148c96c4b4f640`。Direct 與 OOC 各剩 8 組；其中
`direct-ooc-0f731f46b29c0b146fa20145`／`allocation-ooc-280c6a939c761810b6fbd03f`
及 `direct-ooc-df65993e5802208eea828928`／
`allocation-ooc-245f021230b60fac9792b2b6` 沒有對應目前 PIT，刻意留待另一輪
孤兒鏈審查，未納入本批刪除。

本次刪除沒有建立逐位元備份；若要回復，只能從保留的 PIT／正式 source 重建，
新的 run identity 與 manifest hash 不保證與 tombstone 相同。歷史 snapshot／QA
文件中的舊 ID 仍屬 append-only 證據，不能當作目前 filesystem 路徑使用。

## 驗證證據

清理後執行：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_ml_storage_retention.py `
  --root D:\Min\Python\Project\FA_Data\output\release_v4\ml_pit_year_shards `
  --root D:\Min\Python\Project\FA_Data\output\release_v4\portfolio_ml_direct_numeric_production_v4_v2 `
  --root D:\Min\Python\Project\FA_Data\output\release_v4\portfolio_ml_direct_ooc_training_production_v4_v5 `
  --output $env:TEMP\technical_analysis_program_readiness\ml_storage_retention_post_cleanup_20260828.json `
  --format json
```

- Artifact：`C:/Users/archi/AppData/Local/Temp/technical_analysis_program_readiness/ml_storage_retention_post_cleanup_20260828.json`
- Generated at：`2026-08-28T23:48:53-07:00`
- SHA-256：`6A76F1FEF248857A8980BC524B63B7FBD5DDC3D3C944B7631D11DBC49E9F1A67`
- `status=headroom_ok`
- `scan_truncated=false`、errors=`[]`
- `minimum_observed_free_bytes=440561684480`
- `within_minimum_free_space=true`
- `deletion_attempted=false`、`move_attempted=false`、`lock_or_pointer_modified=false`

Artifact 仍固定 `automatic_delete_allowed=false`，與本次行為不矛盾：CLI 本身沒有
自動刪除權限；實際清理是使用者在看到範圍、風險與保留策略後另行明確授權的一次人工操作。

## 對 readiness 的影響

- 已解除：Direct/OOC 的**實體 filesystem headroom** 不足。
- 尚待刷新：既有 scheduled `ml-direct-chain-maintenance-status.v1` 與舊
  `program-readiness.v1` 仍保存清理前 `blocked_insufficient_storage`，只能作歷史證據。
  不應手改該 append-only／status artifact；下一次受控 preflight 或自然排程應產生新狀態。
- 仍未解除：technical production single-writer backup／rollback canary、Formal 3 inputs、
  Paper fills／成本帳、P0 owner／license／PIT acceptance、production scheduler 與 broker pool。
- 不應僅為「刷新 status」直接執行 maintenance wrapper，因為 headroom 通過後 wrapper
  可能真正啟動 Direct/OOC rebuild。沒有新的執行授權時，使用本文件與唯讀 retention
  inventory 作為容量現況證據。

## 後續 retention 原則

1. 每個 layer 至少保留 current pointer 及其完整 upstream／downstream dependency closure。
2. 未完成 resume 可在明確 owner 決策後清除，但要先記錄「放棄 resume、改由重算」的含義。
3. 完整歷史 run 若被 runbook／release／QA 引用，應先建立 durable tombstone 或移至冷 archive。
4. 清理前先做 untruncated inventory、active lock／process、pointer、manifest hash 與 repo reference 檢查。
5. 只使用 exact literal targets；禁止以 `release_v4` root、wildcard 或 modified time 單獨作刪除範圍。
6. `inspect_ml_storage_retention.py` 保持 read-only；未來若要自動輪替，需另立 retention
   contract、保留數、dependency verifier、tombstone 與 owner approval，不能把本次人工行為當成自動授權。
