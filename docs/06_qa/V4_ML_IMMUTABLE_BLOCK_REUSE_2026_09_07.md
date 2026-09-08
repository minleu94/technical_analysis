# V4 ML 跨 run immutable block reuse（2026-09-07）

## 範圍與安全邊界

本輪建立獨立的 `ml-immutable-block-store.v1` registry 與 bounded QA sample，
並將 shared PIT view 接到既有 assembler、Direct numeric builder 與 OOC training
consumer。它只讀已接受的 repo output／fixture，輸出到新的 repo `output` 目錄；
沒有移動、清理或修改 D 槽來源，沒有讀取新 fold，也沒有改寫既有已發布
model/release。assembler、Direct numeric 與 OOC consumer 已增加明確的 shared
root 接入分支；既有 run-local path 分支仍保留。這是可審核的研究／QA reuse
slice，不是正式資料來源接入或 promotion。

## 現有 run-local 依賴盤點

| 階段 | manifest／artifact schema | 目前 path 語意 | 目前 hash／consumer 驗證 |
| --- | --- | --- | --- |
| PIT | `ml-pit-year-shards.v1`、`ml-pit-year-shard-dataset.v1` | publication 內 `runs/<publication_id>/<dataset_id>/...`；dataset assembler 以 dataset manifest 的 publication root 拼 shard path | shard 同時保存 `compressed_sha256`、`content_sha256`、bytes／row metadata；consumer 重新讀檔核對 hash |
| Direct numeric | `portfolio-ml-direct-numeric.v4`、年度 `portfolio-ml-ooc-year.v3` | 預設仍為 `runs/<direct_run_id>/year=YYYY/...`；啟用 shared numeric 時年度目錄只保存 manifest／references，8 個 numeric、rows、replay、carry object 由 immutable registry 直接提供。shared PIT input 仍只保存 `block_reference`／`source_path` lineage，不把 gzip copy 回 Direct run | Direct manifest 綁 dataset／feature／source manifest hashes 與 `shared_block_store_mode=content_addressed`；shared numeric 年度 key 另綁 source shard、sector custody、carry／replay、label／maturity 與 descriptor semantic hashes |
| OOC store | `portfolio-ml-ooc-store.v3`、`portfolio-ml-ooc-year.v3`、`portfolio-ml-ooc-fold-index.v1` | 預設仍讀 `runs/<ooc_run_id>/year=YYYY/...`；Direct shared numeric manifest 由 `_NumericStore` 以 shared registry mmap 5 個 numeric object，並以 shared `rows.sqlite` 串流日期驗證，無需複製回 OOC run | Direct store manifest hash／file hash、year artifact key／object hash、fold train/test file hash，並重算 store／year／fold manifest hash；舊 local numeric manifest 維持原 path 分支 |
| OOC training／release | `allocation-ooc-training.v5` 及其 artifact records | training run 的 `artifacts`／`work` 相對 path；training manifest 綁定上游 Direct store hash | 綁 store manifest hash、dataset／feature／source lineage 與 artifact file hash；OOC output 不複製 shared PIT object，既有 consumer 仍預期 local numeric run root |

目前的 hash 是完整性與 lineage 驗證，並未提供跨 run 的可搬移 object reference。
因此相同 bytes 在兩個 run 目錄會各存一份；把 path 改成另一個 run root 也不能通過
現有 consumer 的 root／hash custody。

## 共享 reference 設計

新 registry 的目錄只包含 immutable object 與每個語意 key 的 immutable record：

```text
<shared-root>/
  objects/sha256/<bytes-sha256>.blob
  keys/<semantic-key-sha256>.json
```

run manifest 嵌入的 reference 只使用相對路徑，不保存 registry 絕對路徑：

```json
{
  "schema_version": "ml-immutable-block-reference.v1",
  "store_schema_version": "ml-immutable-block-store.v1",
  "key_hash": "sha256:<semantic-key>",
  "key": {
    "schema_version": "ml-immutable-block-key.v1",
    "block_type": "pit_shard",
    "artifact_schema_version": "<producer-schema>",
    "source_version": "<source-publication-version>",
    "source_manifest_hashes": [["<source-id>", "sha256:<hash>"]],
    "feature_contract_hash": "sha256:<hash>",
    "label_contract_hash": "none",
    "maturity_policy": "<maturity-policy>",
    "time_range": {"start": "<ISO>", "end": "<ISO>"},
    "encoding": "<encoding>",
    "lane": "formal|research_shadow"
  },
  "key_manifest": {"path": "keys/<key-hash>.json", "sha256": "sha256:<hash>", "bytes": 0},
  "object": {"path": "objects/sha256/<bytes-hash>.blob", "sha256": "sha256:<hash>", "bytes": 0}
}
```

`key_hash` 是完整 canonical key 的 SHA-256，不能由檔名或 run id 推導。來源版本、
每個 source manifest hash、artifact schema、feature／label contract、maturity
policy、時間範圍、encoding 與 lane 任一改變，都會產生不同語意 key；loader 會拒絕
把新 key 套在舊 key record 或改過的 bytes 上。若語意 key 改變但 bytes 恰好相同，
可以共用同一個 content object，仍會保存獨立 key record，避免把相同數值誤當成
相同資料語意。

object 與 key record 都是同目錄 temp、flush／fsync、create-only hard-link。並行
寫入同一 hash 時只會保留一個完整 object；中斷時不會把 partial 當成最終 hash
object。`directory_size_bytes` 是唯一容量計算入口，寫入前後都核對上限，硬終止
留下的 `.partial` 仍計入容量並交由受控清理，不假稱自動消失。每個 registry
使用 `<shared-root-parent>/.ml_immutable_block_store.lock` 作為 canonical OS
lock；這把鎖涵蓋 existing／planned capacity check、temp 峰值檢查、atomic
publish 與 final bytes 核對，caller 提供其他 lock path 會 fail closed。暫存根目錄
可由 `temporary_roots` 傳入，現有 bytes 與 caller 的歷史 peak 取較大值，並以
`temporary_budget_bytes` 限制；未知峰值不會被當作零。registry 沒有可變 latest
pointer；每個 run 只保存 reference，因此整個 registry 搬到另一個 root 後仍可用
新 root load。

## 小樣本實測

QA 入口：

```powershell
.\.venv\Scripts\python.exe scripts\qa_ml_immutable_block_reuse_sample.py `
  --bundle-manifest output\v4_ml_allocation_v3_linear_20260907\qa\readback_bundle\manifests\1f119043742d32976c206eed9b63220bc5c4c4002d35981f1684bc37ab9eadbf.json `
  --output-root output\v4_ml_allocation_v3_linear_20260907\qa\immutable_block_reuse_sample_v2
```

結果保存於 `output/v4_ml_allocation_v3_linear_20260907/qa/immutable_block_reuse_sample_v2/reuse_report.json`（1,016 bytes，file SHA-256 `sha256:afbec87f74d6f245905732be194d812531b4178c7cec2abce641fd77de026f0b`）；sample 目錄總大小 42,925 bytes：

- source bundle identity：`sha256:1f119043742d32976c206eed9b63220bc5c4c4002d35981f1684bc37ab9eadbf`。
- input object：`sha256:fdda4d32c54d4509781ac0597c4b6e8b6709cfd2da0bc526e893759cfee5c735`，35,254 bytes；source manifest refs 9 個。
- 兩個 run reference 都是相對 path，`shared_object_count=1`；第二次相同 key 發布 `immutable_block_reused`、`new_bytes_written=0`。
- 若兩個 run 各保存一份 input，object bytes 為 70,508；共享 object 為 35,254，物件層節省 35,254 bytes。registry 含 key metadata 的總量為 37,345 bytes，已如實分開列示。
- key hash：`sha256:959e5c734f4fc6e09a06c266f190aadccd24ebf90a744d15c7cd1b28a17a2ea2`；未讀 D、未訓練、`formal_oos_allowed=false`、alpha 0、broker false。

測試 `tests/test_immutable_ml_block_store.py` 共 11 項，覆蓋兩 run 同 hash、registry
搬移後 load、source version 改變、schema／bytes tamper、KeyboardInterrupt exception
recovery、並行 create-only、canonical lock、兩個不同 object 的跨 process 容量競爭，
以及 `.partial`／外部暫存峰值實際計入容量後的 fail-closed；file publisher 另驗
1 MiB 分塊、hash 後 source 增長在 partial 超額前拒絕。測試中的兩個競爭者
各自在空 store 都能單獨發布；ready queue 讓兩個 process 都先到等待點，再同時
嘗試同一 canonical lock，最後只保留一個 object/key。

## PIT 小型真實接線

`data_module/ml_pit_shared_block_resolver.py` 提供兩個入口：

- `resolve_pit_shard_record(...)` 先辨識 `block_reference`；shared reference
  透過 immutable loader 驗證 key/schema/object，再重新核對 gzip bytes、compressed
  SHA、content SHA 與 bytes。沒有 `block_reference` 時，沿用既有相對 `path`，並
  對舊 local manifest 執行同一套 hash/content 驗證。
- `build_shared_pit_publication(...)` 讀取既有 PIT dataset manifest 及其 parent
  publication manifest，兩者 hash 不符即停止；它只將 shard bytes 發布到 shared
  registry，derived publication 只保存相對 block references。source fingerprint、
  eligibility、feature contract、maturity、lane、時間範圍與每 shard compressed／
  content hash 都進入 key 或 lineage。每 shard key 不直接綁會因單一 shard 改變的
  aggregate dataset hash，故未改 shard 可重用；changed shard 會取得新 key/object。
  content SHA 以 gzip stream 分段讀取計算，不把解壓後整個年度 shard 複製到第二份
  buffer。`source_version` 同時綁定 source contract、eligibility、artifact schema、
  feature／label、maturity、lane、dataset/year 與該 shard 的 bytes hashes；parent
  dataset/publication hash 另保留在 derived lineage，兩者不混為同一語意。

可執行入口為：

```powershell
.\.venv\Scripts\python.exe scripts\build_ml_pit_shared_block_publication.py `
  --dataset-manifest <EXISTING_PIT_DATASET_MANIFEST> `
  --shared-store <NEW_REPO_OUTPUT>\registry `
  --output-dir <NEW_REPO_OUTPUT>\publication
```

`--lock-path` 只有在它正好等於 shared store 的 canonical lock 時才可使用；省略
時由 store root 自動解析。source publication 與 shared store／derived output
不可重疊，source database 不會被開啟。derived manifest 的 status／new bytes
只保留在本次 CLI 回傳，不寫入 logical manifest，因此相同 publication 重跑不會
因 telemetry 變動產生新 identity。

`tests/test_ml_pit_shared_block_resolver.py` 的真實小路徑以
`PITYearShardExporter` 從兩年度 SQLite fixture 產生兩個年度 gzip shard，並建立
第二個 exporter publication，只改來源 DB 的 2024 一列。第一次 publication 建立
兩個 shared objects；第二次 publication 對未改的 2023 shard 回報
`immutable_block_reused`，只為 2024 changed shard 增加一個 object/key；重跑第二
publication 兩 shard 都 reuse，derived manifest bytes 不變。測試另以 resolver
讀回 shared shards，並以原始 local record 驗證舊 manifest 相容；全程未讀 D、未讀
新 fold。assembler 公用 `build()` 與 Direct 公用
`PortfolioMLDirectNumericStoreBuilder.build()` 均有 shared view 路徑，並在刪除
producer run-local publication 後完成實際 spool／numeric artifacts；第二次
resume 只允許 heartbeat 變更，其餘 manifest、年度 artifacts、fold refs hash
保持不變。resolver 測試目前共 8 個 pytest cases（schema／feature tamper 以
parameterized case 計數）。

另以 repo 內既有的 bounded PIT publication（`all_field_enriched`，parent dataset
manifest hash `sha256:c092de08964f56f33a41049eaf0a4612f039bd43052758b0bbf09eb6fd8e1933`）
執行 CLI 兩次，未開啟 source database。實際結果保存於
`output/v4_ml_shared_pit_reuse_20260907/`：derived manifest
`publication/runs/pit-shared-9edc8dbeb915a5b6548c2fc4/manifest.json` 的 hash 為
`sha256:1e5c1191644d70989f5f9759b835266f0ebf13625b154da947ad95e06ed72c30`，含
3 shards／53,004 rows；shared registry 含 3 objects，`directory_size_bytes` 為
18,254,818 bytes，整個 QA output 為 18,262,778 bytes。第一次三 shard 均為
`immutable_block_created`，第二次三 shard 均為 `immutable_block_reused` 且
`new_bytes_written=0`；三個 shared references 以 loader 讀回、gzip content 與
compressed SHA 全部核對通過。這次實跑只使用 repo output 既有來源、未寫回 parent、
未讀新 fold；它是 bounded research/QA evidence，不代表正式 PIT promotion。最新含
consumer dataset view 的實跑另保存於 `output/v4_ml_shared_pit_consumer_20260907/`：
publication `pit-shared-14127774a7ded93cd564fdcf` 的主 manifest hash 為
`sha256:61d0ced0bcbd96a56f8a66c8caefd5ff42fe4436db4d0e74b66243d157a89543`，
consumer view hash 為 `sha256:9a284311a5dda244066f8658e01196996a202e4fcf9d866109993cebb65ba49a`，
含 3 shards／53,004 rows；registry／publication／lock 合計 18,292,954 bytes。
view 的每個 shard 都有 `block_reference`、相對 key/object path，且沒有 run-local
shard copy。publisher 以 file stream 讀來源與 gzip content hash，沒有
`read_bytes()` 將年度 shard 載入記憶體。

## 公開 Direct 與 OOC bounded readback

公開 Direct CLI 首次使用 production-like `minimum_train_dates=252`、
`test_date_count=63` 時，在 discovery 因可用日期不足四個 outer folds 而
fail-closed；該 blocked output 保留，沒有把日期切分改標成功。使用預先固定的
bounded research split `minimum_train_dates=65`、`test_date_count=63`（purge 60、
embargo 5）後，實際 CLI 命令為：

```powershell
.\.venv\Scripts\python.exe scripts\build_portfolio_ml_direct_numeric_store.py `
  --raw-manifest output\v4_ml_shared_pit_consumer_20260907\publication\runs\pit-shared-14127774a7ded93cd564fdcf\all_field_enriched\manifest.json `
  --shared-block-store output\v4_ml_shared_pit_consumer_20260907\registry `
  --output-dir output\v4_ml_direct_shared_consumer_20260907_bounded `
  --training-as-of 2026-09-07T08:30:00+08:00 --benchmark-entity TAIEX `
  --minimum-train-dates 65 --test-date-count 63 --purge-trading-days 60 `
  --embargo-trading-days 5 --batch-size 2048 --workers 1 --memory-budget-mb 4096 `
  --no-resume
```

成功 run `direct-ooc-415dba364b4dacbe583b9284` 的 manifest hash 為
`sha256:988bd6a8d0c71a7fdc30ae775ca6f2e0cfbca1b6119fe542e36b43e6e75384a5`，
file hash 為 `sha256:f1932ff3faeec2b4f71638c7556048b5120d7d15317008cbd2e31700dce6ab6a`，
產生 3 年／4,588 rows／62 features／6 folds 的 numeric store。Direct output
總量為 7,182,408 bytes；實測 peak RSS 198,447,104 bytes、年度 temporary peak
186,675,944 bytes，`direct_store_complete=true`，但 `full_market_ready=false`，
原因仍是 sector／official custody／portfolio ledger／rule history 缺件。同一
命令不帶 `--no-resume` 已 readback 相同 run id、manifest hash 與 file hash。

再以該 Direct manifest 執行既有 OOC ridge/h5 bounded downstream，沒有重新讀 PIT
或複製 shared object；training output 保存於
`output/v4_ml_ooc_from_shared_direct_20260907/`。training run
`allocation-ooc-99af5c31a18393e110a83bcb` 的 manifest hash 為
`sha256:d7cd69a899a162ff6414709027f8e740ff4f753ec5322179e1766ceddde86bc7`，file
hash 為 `sha256:6239e448642d6caf25a3562f08042b6627629f47459149d8de23594829fa9760`，
`store_manifest_hash` 精確指向上述 Direct manifest，18 個 base experts／5 個
meta folds，output 1,501,326 bytes。OOC readback 重跑維持相同 run／manifest
hash；`memory_budget_mb=1024` 下實測 peak RSS 192,385,024 bytes。該 training
artifact 仍 `formal_oos_allowed=false`、`production_alpha_bp=0`、promotion
false；這是 consumer wiring／bounded research evidence，不是模型效果或正式
部署證據。

## Direct 年度 numeric 跨 run reuse

新增 `data_module/ml_direct_shared_block_resolver.py` 與 Direct builder 的
`--shared-numeric-store` 接線。年度 artifact key 版本為
`direct-numeric-year-key.v2`；每個 key 以 artifact schema、年度與 ordinal、年度
decision dates、PIT source shard 的 compressed／content SHA、feature registry、
label contract、maturity policy、training cutoff、benchmark、corporate custody、
portfolio replay policy、明確的 sector membership custody、以及當年輸入的
bounded carry hash 組成。descriptor 另外保存 shape、row counts、每個 artifact
reference 與同一組 semantic hashes。aggregate raw manifest 不直接成為年度 key，
因此只改某年度 shard 時，未受影響年度仍可重用；年度 descriptor 的 exact lookup
會在建立年度 workspace、assembly SQLite 或 numeric staging 之前執行。

首次建立年度時，builder 透過 immutable store 的 canonical OS lock，以 1 MiB
分塊串流發布 8 個年度 object 與小型 descriptor；完成後 run-local 年度目錄只
保留 manifest／references。第二次 run 命中 exact descriptor 時，直接建立新的
run manifest 指向既有 references，`_build_year` 與年度 staging 都不會被呼叫，
`new_bytes_written=0`。未命中的年度才建立 workspace 並發布新 semantic key；
carry hash 改變會使直接相鄰的下一年度失效，bounded 20-event window 老化後的
更晚年度可以再次重用。改動 sector sidecar 也會使所有受其語意影響的年度 key
失效，不能因 numeric bytes 恰好相同而靜默重用。

OOC 的 `_NumericStore` 以 Direct 年度 manifest 的 shared references 直接 mmap
`features.values.i64`、`features.masks.u8`、`targets.i32`、`labels.i32`、
`labels.masks.u8`，並以 shared `rows.sqlite` 驗證 decision date／row id；
`AllocationOutOfCoreTrainingService` 與 `train_ml_allocation_out_of_core.py`
接受 `--shared-numeric-store`。沒有此欄位的既有 local Direct／OOC manifest
仍走原有相對路徑。

驗證命令：

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_ml_direct_numeric_shared_reuse.py -q -o addopts=
```

該檔 4 項測試以隔離 SQLite fixture 先由 `PITYearShardExporter` 產生真實年度
shard，再由公開 `PortfolioMLDirectNumericStoreBuilder` 建立兩次 run，沒有讀 D
槽或新 fold。結果為 `4 passed, 1 warning in 28.93s`（warning 是 pytest cache
無寫入權限）。測試確認：2024 source 改動時 2022 年不呼叫 `_build_year`、不建立
同年度 staging，OOC training 可直接消費 shared rows／numeric；2022 年末 volume
改動會使 2022／2023 重建、2023 的 `direct:carry-input` 改變，而 2024 在 bounded
carry 老化後重用；sector custody 改動會使所有年度拒絕 reuse；registry 搬移、
object tamper 與 Direct resume 均 fail closed／保持原 immutable bytes。另已通過
Direct shared resolver 的 7 項測試與既有 OOC pipeline 的 22 項測試；mypy／
py_compile 定向檢查無錯。這些是 bounded research／QA evidence，不是全歷史
重建、模型 promotion 或正式 alpha 證據。

## 公開 Direct/OOC bounded CLI 實跑與重用證據

本輪沿用已接受的 bounded shared PIT consumer：
`output/v4_ml_shared_pit_consumer_20260907/`。Direct CLI 的輸入 manifest 是
`publication/runs/pit-shared-14127774a7ded93cd564fdcf/all_field_enriched/manifest.json`，
其 shared PIT dataset view logical hash 為
`sha256:9a284311a5dda244066f8658e01196996a202e4fcf9d866109993cebb65ba49a`，含
3 shards／53,004 rows。D 槽只作為既有來源的 lineage 背景，本輪 CLI 沒有開啟或寫入
D，也沒有讀新 fold。

兩次 Direct 公開 CLI 使用同一組固定 bounded 參數：`minimum_train_dates=65`、
`test_date_count=63`、`purge=60`、`embargo=5`、`batch_size=2048`、1 worker、
memory 4096 MiB、persistent／temporary 各 1 GiB、safety reserve 200 GiB；兩個
run 使用不同 output root、同一 shared numeric registry。第二次命令只將第一個
命令的 `--output-dir` 改為 `direct_run_b`：

```powershell
.\.venv\Scripts\python.exe scripts\build_portfolio_ml_direct_numeric_store.py `
  --raw-manifest output\v4_ml_shared_pit_consumer_20260907\publication\runs\pit-shared-14127774a7ded93cd564fdcf\all_field_enriched\manifest.json `
  --shared-block-store output\v4_ml_shared_pit_consumer_20260907\registry `
  --shared-numeric-store output\v4_ml_direct_numeric_cli_reuse_20260907\shared_numeric `
  --output-dir output\v4_ml_direct_numeric_cli_reuse_20260907\direct_run_a `
  --training-as-of 2026-09-07T08:30:00+08:00 --benchmark-entity TAIEX `
  --minimum-train-dates 65 --test-date-count 63 --purge-trading-days 60 `
  --embargo-trading-days 5 --batch-size 2048 --workers 1 --memory-budget-mb 4096 `
  --temporary-storage-budget-bytes 1073741824 `
  --persistent-storage-budget-bytes 1073741824 `
  --safety-reserve-bytes 214748364800 --no-resume
```

實跑結果如下：

| 證據 | Direct A | Direct B |
| --- | ---: | ---: |
| run id | `direct-ooc-2c1fa57c911925b9fb7afec1` | 同一 deterministic identity |
| manifest logical hash | `sha256:e60123f8c6f84f8fbc38b6537a8016c7289562bce5fb40891439ec40164e35f8` | `sha256:a96288d92a31d1d0c8e5fde724eb5e225952039ca244b39a43814a7e48d73f39` |
| manifest file SHA-256 | `sha256:1b22d9f6e07113ee17cce0c3ee165949e276398d81abcdb40d73ab48446aeffc` | `sha256:372f3aeebc4f6bbdbf3ea968e6750dc2615da261839f43e7b4ff24d8e923c0d5` |
| rows／features／folds | 4,588／62／6 | 4,588／62／6 |
| run output bytes | 632,218 | 632,763 |
| shared registry bytes | 6,951,008 | 6,951,008 |
| shared objects／keys | 27／27 | 27／27 |

A 年度 shared publication 新增 `2024=1,373,000`、`2025=3,810,277`、
`2026=1,767,731` bytes，合計 6,951,008。B 三個年度均在建立 workspace／staging
前命中相同 descriptor 與 8 個 artifact keys：`reuse_before_build=true`、
`new_bytes_written=0`；三個 run-local `year=YYYY` 目錄都只含 `manifest.json`，
沒有 numeric copy。這是實際 Direct 跨 run immutable reuse 與容量結果，不是只比較
loader 回傳值。

接著 OOC CLI 以 Direct B manifest 及同一 shared numeric store 執行
`ridge_logistic`／horizon 5／`minimal_linear_shadow`，同樣使用 1 GiB persistent、
1 GiB temporary、200 GiB reserve 與 memory 4096 MiB：

```powershell
.\.venv\Scripts\python.exe scripts\train_ml_allocation_out_of_core.py `
  --store-manifest output\v4_ml_direct_numeric_cli_reuse_20260907\direct_run_b\runs\direct-ooc-2c1fa57c911925b9fb7afec1\manifest.json `
  --shared-numeric-store output\v4_ml_direct_numeric_cli_reuse_20260907\shared_numeric `
  --output-dir output\v4_ml_direct_numeric_cli_reuse_20260907\ooc_run `
  --algorithm ridge_logistic --horizon 5 --profile minimal_linear_shadow `
  --batch-size 2048 --workers 1 --memory-budget-mb 4096 `
  --ridge-alpha-bp 100 --logistic-iterations 1 `
  --temporary-storage-budget-bytes 1073741824 `
  --persistent-storage-budget-bytes 1073741824 `
  --safety-reserve-bytes 214748364800
```

OOC run `allocation-ooc-05bf3f871a2013c62de44f6e` 的 manifest logical hash 為
`sha256:f46772e9daf1272a9ed4e852a961258e8f2008b8ce7b2e7b257c62c5d8795045`，file
SHA-256 為 `sha256:00073adc68d42992a2fa82b8bd78cc49b035cbd1b1813a8c1ea42cb0d647345d`；
其 `store_manifest_hash`／file hash 精確指向 Direct B，產出 18 個 base experts、5
個 meta folds、4,588 rows／62 features。以同一命令 resume 一次後，manifest logical
hash、file hash 與 run id 均相同；`ooc_run/runs/<run_id>` 的目錄為 1,501,884 bytes，
resume 前後完整檔案 snapshot 都是 1,501,884 bytes、沒有 changed files。

可重播的證據入口是 `scripts/qa_ml_direct_ooc_shared_reuse.py`。本次最新
不可變報告保存於
`output/v4_ml_direct_numeric_cli_reuse_20260907/qa_v2/`。早期的
`qa/` 目錄保留第一次 snapshot；該組 snapshot 正好包住實際 OOC resume，
因此最新報告仍以它們作為 before／after 輸入，不覆寫原 snapshot：

```powershell
.\.venv\Scripts\python.exe scripts\qa_ml_direct_ooc_shared_reuse.py snapshot `
  --root output\v4_ml_direct_numeric_cli_reuse_20260907\ooc_run\runs\allocation-ooc-05bf3f871a2013c62de44f6e `
  --output output\v4_ml_direct_numeric_cli_reuse_20260907\qa\ooc_resume_before.json

# 以同一組 train_ml_allocation_out_of_core.py 參數執行一次 resume 後，再保存 after snapshot。
.\.venv\Scripts\python.exe scripts\qa_ml_direct_ooc_shared_reuse.py snapshot `
  --root output\v4_ml_direct_numeric_cli_reuse_20260907\ooc_run\runs\allocation-ooc-05bf3f871a2013c62de44f6e `
  --output output\v4_ml_direct_numeric_cli_reuse_20260907\qa\ooc_resume_after.json
.\.venv\Scripts\python.exe scripts\qa_ml_direct_ooc_shared_reuse.py report `
  --direct-first-manifest output\v4_ml_direct_numeric_cli_reuse_20260907\direct_run_a\runs\direct-ooc-2c1fa57c911925b9fb7afec1\manifest.json `
  --direct-second-manifest output\v4_ml_direct_numeric_cli_reuse_20260907\direct_run_b\runs\direct-ooc-2c1fa57c911925b9fb7afec1\manifest.json `
  --shared-numeric-store output\v4_ml_direct_numeric_cli_reuse_20260907\shared_numeric `
  --ooc-manifest output\v4_ml_direct_numeric_cli_reuse_20260907\ooc_run\runs\allocation-ooc-05bf3f871a2013c62de44f6e\manifest.json `
  --output-dir output\v4_ml_direct_numeric_cli_reuse_20260907\qa_v2 `
  --before-snapshot output\v4_ml_direct_numeric_cli_reuse_20260907\qa\ooc_resume_before.json `
  --after-snapshot output\v4_ml_direct_numeric_cli_reuse_20260907\qa\ooc_resume_after.json
```

| 檔案 | 實測內容 |
| --- | --- |
| `ooc_resume_before.json`／`ooc_resume_after.json` | OOC run 每個檔案的串流 SHA-256／bytes；兩者 snapshot hash 都是 `sha256:cd030ec9b57dbc292c30d07f83babecfd5c68e19e3794a8ef6f0d1d0b6b985b1`，file SHA 都是 `sha256:c3361e97b68d63a33425cd2cc6a931cd7d1631dc85741688f1351082c734780c` |
| `qa_v2/reuse_evidence_manifest.json` | logical hash `sha256:d54d49d1645ab35b3e2efde5a58759272fabcc67b060f4e795ec441ec3806cad`，file SHA `sha256:2fea1134a174d8382239e5bfbd909c35e55e011a8552d72a86326d283001190d` |
| `qa_v2/reuse_summary.json` | summary hash `sha256:0bbb9d1e187d3dcbecafd7821daf8dc8bdbcdd78ccc23e6a5501da5eb962c16b`，file SHA `sha256:adf82670fd04e2a8e7ef9f530093fb7226fe80e215f3e82c9c84aa8f7672d226` |

`qa_v2` 目錄總量為 160,582 bytes，低於本輪 1 GiB 持久新增上限。summary／manifest
明確保存 Direct 年度 lineage、descriptor／artifact key 與 object hash、每年
new bytes、OOC store hash、resume snapshot、容量預算，以及
`formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false`。
Direct 的 readiness 仍因 sector membership、official corporate／trade custody、
causal non-cash ledger 與 formal rule history 缺件而不具正式 OOS 資格；OOC 的
calibration 仍是 measured cross-fitted diagnostic（ECE 1,499 bp、threshold 500 bp、
`production_eligible=false`），所以這個 bounded run 不代表 promotion 或投資優勢。

### OOC 訓練 artifact 跨 run reuse（v2 bounded 實裝）

前一版文件中的「尚未接入」是當時的狀態；本輪已加入
`ml_module/allocation_ooc_shared_artifact_store.py` 與
`--shared-artifact-store`。它把 OOF、final base、meta OOF、final meta 的 payload
放在新的 immutable registry，run-local `artifacts/` 只留下 manifest／reference，
既有沒有 shared reference 的 local reader 仍走原路徑。兩個獨立 output root 使用同一
request 時會得到相同 deterministic `run_id`；這裡的跨 run 證據是兩次獨立 CLI
invocation 的 registry reuse，不把同一 output root 的 resume 當成 reuse。

每個 artifact 先建立完整 semantic key，再以 canonical hash lookup。key 以分離的
namespace 綁定 `artifact_kind`／scope（pack、fold、horizon、lane）、Direct store
logical／file hash 與 dataset/source lineage、feature registry／順序／scale、
label／target contract、train／test／calibration split、purge／embargo、maturity
cutoff、完整 model hyperparameters、training profile／complexity、rank contract、
family-weight policy、calibration contract／withheld OOF row identity、時間範圍與
implementation schema version。`base_oof`、`final_base`、`meta_oof`、`final_meta`
及 `calibrator` namespace 不可互相混用；fold、pack、lane、feature／label maturity、
參數或 implementation 任一改變都會變成新 key。當同一 key 已綁定不同 core manifest
時，publisher 在任何新 payload 寫入前拒絕；loader 會重驗 key、descriptor、bytes／
content hash 與 lineage。校準 namespace 在本片仍標示 cross-fitted diagnostic-only，
沒有把它升格為 production calibrator 或 promotion 證據。

實際 bounded CLI 只讀已接受的 Direct B manifest（沒有寫 D、沒有讀新 fold、沒有
重建全歷史），命令 A／B 的核心參數如下：

```powershell
.\.venv\Scripts\python.exe scripts\train_ml_allocation_out_of_core.py `
  --store-manifest output\v4_ml_direct_numeric_cli_reuse_20260907\direct_run_b\runs\direct-ooc-2c1fa57c911925b9fb7afec1\manifest.json `
  --shared-numeric-store output\v4_ml_direct_numeric_cli_reuse_20260907\shared_numeric `
  --shared-artifact-store output\v4_ml_ooc_artifact_reuse_20260907\shared_artifacts `
  --output-dir output\v4_ml_ooc_artifact_reuse_20260907\run_a `
  --algorithm ridge_logistic --horizon 5 --batch-size 31 --workers 1 `
  --profile minimal_linear_shadow --memory-budget-mb 4096 `
  --temporary-storage-budget-bytes 1073741824 `
  --persistent-storage-budget-bytes 1073741824 `
  --safety-reserve-bytes 214748364800
```

B 使用相同參數，僅將 `--output-dir` 改成
`output\v4_ml_ooc_artifact_reuse_20260907\run_b`。A 的 manifest logical／file hash
是 `sha256:718475b9379d8be0fd72e03ec7cf2010eb97394714f1edbaa7abc27b2edc2f49`／
`sha256:67758a4e1704ec763bd8ec4eee78673248594b5ee8cb968fdc763677cdb185ac`；B 是
`sha256:b1939488f8d86415ab9b0d85f8401c03ff22c4288be47299c748fbe7692e58e7`／
`sha256:4aa135241db9dd3a81e3a0ed4626e0ccd08886aa7459005818be0b939622b5b6`。兩次均為
`allocation-ooc-c5f3c3b939b04a6d9fc78cb6`、18 base experts／5 meta folds；A 建立
registry 後，B 的 27 個 artifact（18 base OOF、3 final base、5 meta OOF、1 final
meta）全部 `shared_immutable`，semantic key 與 payload hash 逐項相同，並留下
`base_expert_shared_reused=18`、`final_base_expert_shared_reused=3`、
`meta_fold_shared_reused=5`、`final_meta_shared_reused=1` 事件。第二次沒有呼叫 fit，
且 shared registry 在前後 snapshot 都是 `2,817,166` bytes、changed files 為空。

可用下列 QA command 重新驗證兩次 manifest、shared registry snapshot 與 27 個
artifact 的 reference／payload：

```powershell
.\.venv\Scripts\python.exe scripts\qa_ml_direct_ooc_shared_reuse.py report `
  --direct-first-manifest output\v4_ml_direct_numeric_cli_reuse_20260907\direct_run_a\runs\direct-ooc-2c1fa57c911925b9fb7afec1\manifest.json `
  --direct-second-manifest output\v4_ml_direct_numeric_cli_reuse_20260907\direct_run_b\runs\direct-ooc-2c1fa57c911925b9fb7afec1\manifest.json `
  --shared-numeric-store output\v4_ml_direct_numeric_cli_reuse_20260907\shared_numeric `
  --ooc-manifest output\v4_ml_ooc_artifact_reuse_20260907\run_a\runs\allocation-ooc-c5f3c3b939b04a6d9fc78cb6\manifest.json `
  --ooc-second-manifest output\v4_ml_ooc_artifact_reuse_20260907\run_b\runs\allocation-ooc-c5f3c3b939b04a6d9fc78cb6\manifest.json `
  --ooc-shared-artifact-store output\v4_ml_ooc_artifact_reuse_20260907\shared_artifacts `
  --shared-artifact-before-snapshot output\v4_ml_ooc_artifact_reuse_20260907\qa_artifact_v1\shared_before_b.json `
  --shared-artifact-after-snapshot output\v4_ml_ooc_artifact_reuse_20260907\qa_artifact_v1\shared_after_b.json `
  --output-dir output\v4_ml_ooc_artifact_reuse_20260907\qa_artifact_v1\report
```

報告保存於 `output/v4_ml_ooc_artifact_reuse_20260907/qa_artifact_v1/report/`：
`reuse_evidence_manifest.json` logical hash 為
`sha256:dda0023fcc7786c6c2165ce20c9895209b58df23fea838cb1fc5472e2941889e`，
`reuse_summary.json` logical hash 為
`sha256:019173859bd6a0938342992b9c70e79355fac555957d2e7acae72592cbc94b0e`。
summary 的 bounded scope 是 persistent／temporary 各 1 GiB、memory 4096 MiB、
reserve 200 GiB、source_data_modified=false、new_fold_read=false、
full_history_rebuilt=false、formal OOS=false、alpha=0、broker=false；這證明的是
artifact 完整性與重用，不是模型績效或投資有效性。

## 後續接入界線

本片已完成 PIT shared view → assembler → Direct numeric → OOC training 的
bounded 公用入口接線與 readback。OOC model／OOF／meta 現已可透過 shared registry
直接消費 immutable reference；正式 caller 仍必須共用 registry 的 canonical
lock，不能另傳一把相似名稱的鎖；shared view 與 shared numeric 的 schema、
feature contract、maturity、lane、source／content hash 任一不符即 fail closed。
Direct 年度 numeric artifact 現可選擇 immutable shared references，OOC fold index
仍依 run 建立並綁定 Direct store hash，不把不同 stage 或不同 lane 的 bytes 靜默
混用。正式 Direct/OOC production chain 仍受既有 sector、official custody、
ledger、rule history readiness blockers 約束；本片沒有開啟 alpha、formal OOS 或
broker action，也沒有重建全歷史資料。
