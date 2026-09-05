# Runtime／Performance Readiness Refresh — 2026-08-30

## 結論

本輪已把 Runtime 與 Performance 的「容量阻塞」和「正式 canary 尚未核准」分開：D 槽目前有足夠 headroom，Direct/OOC 也可在不啟動長任務的情況下完成真實 preflight；但正式 Registry transaction、technical backup／rollback 與 broker production fetch pool 仍未獲 owner 授權，因此整體不升格為 production-ready。

本輪沒有刪除、搬移或覆寫 `D:\Min\Python\Project\FA_Data` 任何檔案，沒有啟動 Direct/OOC chain，沒有取得 production lock，也沒有寫入正式 Registry、technical SQLite／CSV 或 broker。

## 1. Runtime 實際寫入能力與正式 Registry 邊界

### TEMP ephemeral write probe

以明確 `--confirm-write-probe` 在 OS TEMP 建立 ephemeral file／SQLite／Registry transaction，完成後清除：

- artifact：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\runtime_write_probe_20260830.json`
- SHA-256：`47CA3F407CF93F8974F9225829E8DE5FFEBC9B11CDB95353A01C5BE43A413DF4`
- `status=passed`
- `file_write_succeeded=true`、`sqlite_write_succeeded=true`、`registry_transaction_succeeded=true`
- `cleanup_succeeded=true`
- `side_effect_free=false`：這是正確揭露，因為 probe 曾在 TEMP 寫入後再清除；它不是 production DB 寫入證明

### Formal Registry production canary preview

正式 Registry 只做 read-only preflight，沒有 owner approval、no-concurrent-writer acknowledgement 或 explicit confirm，因此沒有建立 backup、insert、read-back 或 rollback：

- artifact：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\research_registry_production_canary_preview_20260830.json`
- SHA-256：`88EF464EDE3541FE0128378DDFA2FA763756FA562DF1828918F2800B976CFD5C`
- `status=confirmation_required`、`read_only_preflight=true`
- production Registry `quick_check=ok`、schema v2、row count=`98`、缺 tables／columns=`0`
- `production_write_attempted=false`、`rollback.attempted=false`、`writes_allowed=false`

因此目前正確狀態是「host 可做受控 transaction、正式 Registry canary 待核准」，不是 production writer ready。

## 2. Technical production canary preview

單股 `2330` 的 technical canary 只完成唯讀預演：

- artifact：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\technical_production_canary_preview_20260830.json`
- SHA-256：`0EF43BF09E73991D2C4ED297ABE1EF14108E1EEA3CB935176EEEC2042D39321D`
- `status=confirmation_required`、`production_write_attempted=false`
- production DB `quick_check=ok`
- daily rows=`3,075`、technical rows for 2330=`3,084`、technical table total=`5,228,274`
- daily／technical latest=`2026-08-28`
- `workers=1`、`max_in_flight=1`，但 `owner_approval=false`、`no_concurrent_writer_ack=false`、`production_worker_enabled=false`

下一步仍須獨立取得 owner approval 與 no-concurrent-writer acknowledgement，才可執行單股 backup／write／post-state／rollback canary；不能由這份 preview 自動放行。

## 3. Direct／OOC 容量與保留盤點

三份 retention inventory 都是 read-only，固定 `automatic_delete_allowed=false`、`deletion_attempted=false`、`move_attempted=false`；目前觀察到 D 槽可用 `364,003,164,160` bytes（約 338.9 GiB），高於 20 GiB 門檻。

| Root | 本輪狀態 | 掃描內容 | Artifact SHA-256 |
|---|---|---:|---|
| `ml_pit_year_shards` | `headroom_ok` | 8 個 PIT run、約 170.89 GB | `C9AE985EB5B455099C931A25917EAE5B621866D43F1DB2C845D2F1841E549EFD` |
| `portfolio_ml_direct_numeric_production_v4_v2` | `headroom_ok` | 9 個 Direct run、約 53.68 GB | `A0AED678CC0885D5052BC8EB79F4C0C80A69C649FC8CF054CF55D60B4056CB29` |
| `portfolio_ml_direct_ooc_training_production_v4_v5` | `headroom_ok` | 9 個 OOC run、約 49.59 GB | `BFFF313E736004C64551F6B5D9EBF318BB09C03AC4F0703F5B36C7D932215500` |

整體三 root inventory artifact：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\ml_storage_retention_inventory_20260830.json`，SHA-256=`320026E804C2C5AF546AE31167848E5BD879AD03544E2C452EE0E708CC2B2CF5`。Direct／OOC 的 retention candidate 仍只是人工 review 候選，不能因 headroom 恢復就自動刪除。

清理後新增的 2 個 PIT、3 個 Direct、3 個 OOC run 是本輪盤點時已存在的 post-cleanup outputs；本輪不刪除它們，也不把它們誤寫成 cleanup 保留清單。Current pointers 維持各自綁定最新 manifest；OOC lock 只看到 stale／mismatched PID，未找到目前 Python maintainer process，故不執行 lock 清理。

## 4. 明確 preflight-only 模式

新增 `scripts/scheduled/run_ml_direct_chain_maintenance.py --preflight-only`。它會解析 immutable raw pointer、確認資料庫為 `ro/query_only`、讀取 Direct/OOC storage headroom，然後在取得 maintenance lock 或啟動 child maintainer 前結束。

本輪實際輸出：

- artifact：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\ml_direct_storage_preflight_20260830.json`
- SHA-256：`E2662B6BC64D113CFDB5951A3CF8D5C0FB22C71A6722621F91FCE285999BB312`
- `status=preflight_only`、`execution_started=false`、`destructive_action_performed=false`
- `within_minimum_free_space=true`、`formal_oos_allowed=false`、`broker_order_allowed=false`

這個模式把「可以安全觀察容量」與「真的開始長時間 rebuild」分成兩個明確動作，避免為了刷新 UI 而意外產生新的大型 run。

## 5. Performance owner packet

重新整合 technical preview、worker recovery、broker baseline、preflight 與兩份 retention inventory：

- JSON：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\performance_canary_owner_packet_20260830.json`
- JSON SHA-256：`BBF553B4E79C92E8692F4F17524C44882736A0E5BA2B7D37902AF0C2F0ABE204`
- Markdown：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\performance_canary_owner_packet_20260830.md`
- Markdown SHA-256：`FA55F55089E6FE9D1E32941FD93D58055A82FFA5EACF15C1DE1A9B4E2417D509`
- `packet_status=needs_named_owner_reviewer`
- technical lane=`confirmation_required`
- Direct/OOC=`preflight_only`、headroom=`true`
- worker staging=`observed_staging_only`、broker=`pending_production_pool_review`
- `formal_oos_allowed=false`、`production_worker_enabled=false`、`production_fetch_pool_enabled=false`、`broker_order_allowed=false`、`automatic_delete_allowed=false`

## 6. 驗證與下一步

本輪新增 runner 的回歸測試，與 performance packet focused suite 結果為 `15 passed`。正式 canary 尚未執行的原因是必要的 owner approval／no-concurrent-writer acknowledgement 尚未存在；這是授權缺口，不是容量或程式崩潰。

以本輪所有最新 lane artifact（含 P0 live retry、weekly sidecar、Paper／Formal read model、Runtime probes、fresh capacity 與 Data Update status）重建的 unified readiness：

- artifact：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\program_readiness_current_20260830.json`
- SHA-256：`5229F27373B0CF83E875E4B05D2867121D9E16D18813E91529C337F545720F6E`
- overall=`action_required`
- P0=`action_required`、Evidence=`waiting_for_external_input`、Paper=`partial`、Formal/ML=`action_required`
- Runtime=`ready`、Data Update/History=`ready`、Performance=`partial`
- Performance 唯一剩餘 blocker=`technical_production_single_writer_canary_not_completed`

此報告 exit code 為 2 是因整體仍有 gate blockers，並非產出失敗；UI 若要讀取它，必須在啟動前明確設定 `PROGRAM_READINESS_ARTIFACT`，不會自動掃描 TEMP。
Update View 會以已設定的 data-update／freshness status path 做 bounded mtime 參照；若明確
readiness artifact 較舊，只追加 `program_readiness_artifact_older_than_reference:*`
diagnostic，不自動換檔或改變 lane status。

可持續推進的順序：

1. 由具名 owner／reviewer 審核 performance packet，決定是否核准單股 technical canary。
2. 若核准，先停用並行 writer，再執行 Registry transaction／rollback 與 technical backup／rollback，各自獨立驗證。
3. Broker 仍先維持 serialized fallback 與 production pool 關閉；不能只因 bounded HTTP baseline 已量測就開 pool。
4. Direct/OOC 若要繼續產生新 run，先使用 `--preflight-only`；只有另行核准後才啟動長任務，並保留新的 pointer／manifest lineage。
