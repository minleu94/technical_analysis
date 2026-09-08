# V4 ResearchShadowUnion → PIT → Direct overlay readback（2026-09-07）

## 目的與邊界

本片新增唯讀公開入口
`data_module.ml_research_shadow_overlay_integration.build_research_shadow_overlay_direct_readback`，以及
`scripts/build_ml_research_shadow_overlay_direct_readback.py`。入口把已驗收的
33 筆 official daily-price overlay 與既有 label replay、ResearchShadowUnion、
shared PIT、Direct numeric rows 做 hash-bound readback。它不重跑 label spool、
不回寫 SQLite/PIT/Direct、不訓練模型，也不把事後 overlay 當成盤前 feature。

輸出是小型摘要；每個來源只保留路徑、file SHA、manifest/content identity、
cutoff、coverage 與逐 symbol label diff。`sha256:*` 欄位若標示
`file_sha256` 是檔案 bytes hash；`manifest_hash`、`replay_hash`、
`integration_hash` 是去除自身 digest 後對 canonical JSON 的 logical hash，兩者
不混用。

## 實際執行

```powershell
.\.venv\Scripts\python.exe scripts\build_ml_research_shadow_overlay_direct_readback.py `
  --overlay output\v4_ml_daily_price_source_quality_20260907\canonical_overlay_20260520_official_v1.json `
  --label-replay output\v4_ml_daily_price_overlay_impact_20260907\research_label_replay_20260520_h20_v3.json `
  --research-union-manifest D:\Min\Python\Project\FA_Data\output\release_v4\ml_research_shadow_union_full_v4_official_events\runs\research-union-c385b17c541f2a132d05efa6\manifest.json `
  --pit-manifest output\v4_ml_shared_pit_consumer_20260907\publication\runs\pit-shared-14127774a7ded93cd564fdcf\manifest.json `
  --pit-shared-store output\v4_ml_shared_pit_consumer_20260907\registry `
  --direct-manifest output\v4_ml_direct_shared_consumer_20260907_bounded\runs\direct-ooc-415dba364b4dacbe583b9284\manifest.json `
  --output output\v4_ml_research_shadow_overlay_direct_readback_20260907\readback_20260520_v4.json `
  --pretty
```

實際 exit code 為 `0`，最新輸出為
`output/v4_ml_research_shadow_overlay_direct_readback_20260907/readback_20260520_v4.json`。
先前的 `readback_20260520.json`、`readback_20260520_v2.json` 與
`readback_20260520_v3.json` 保留為 immutable 舊版本，沒有原地覆寫。
v4 檔案大小 `115995` bytes，file SHA 為
`sha256:b45914dbf39d2f29e7c1d03408b1a0015927a95f619c3e5f745630f2141e11e5`，
logical `integration_hash` 為
`sha256:b701b5f26ad070bc581051f2b3f91ca16ce6059acb915134909318ce9e0dfe9a`，
狀態為 `completed_partial_research_shadow_overlay_pit_direct_readback`。
v4 沿用並重新執行官方 nested capture readback：重新讀取並驗證 `receipt.json`、
`comparison.json` 及 response gzip 的實際檔案與內容 hash，並核對日期、33 檔
requested symbols、33 筆官方 rows、completion timestamp 與 overlay 宣告一致。
這一步不是只信任 overlay metadata；官方 comparison file SHA 為
`sha256:525dd56d7aff5cc4771c267438c5d4c0c291d0631205370eabe073e996bec048`、
receipt file SHA 為
`sha256:1e82ddcfca88c6fb30fe175e08ec1a8042074829f6d630a069d5be4dc1752707`，
response file SHA 為
`sha256:f185b2e953836028b9c2ed70c380f41155f68abc6357843a33bed1afe1345cea`；
logical comparison/receipt identity 則分別為
`sha256:edc6c029d76a3fa280002dd67deb1a75542d5b2da858c11e61a17519a9a5a741` 與
`sha256:82183af8f848c52ac8a7b4321d4771f0a8d517eb00b74ba90d249169f0c5737b`。
輸出可用下列命令驗證自身 logical hash：

```powershell
.\.venv\Scripts\python.exe -c "import json, pathlib; from data_module.ml_research_shadow_overlay_integration import _payload_hash; p=pathlib.Path(r'output\v4_ml_research_shadow_overlay_direct_readback_20260907\readback_20260520_v4.json'); j=json.loads(p.read_text(encoding='utf-8')); h=j.pop('integration_hash'); print(h == _payload_hash(j), h)"
```

## 來源與 coverage 證據

| 階段 | 實際 identity | readback 結果 |
|---|---|---|
| Official overlay | overlay file `sha256:aa6880dff65a7632dd1006c42e9572901288d9ed0ed2c36e0bb8111b1b4e0214`；logical overlay `sha256:5b8542725775a3f062f47f8e49d4f5e47f9b60bbce8ea96c9e3baac243b8c326`；TWSE response `sha256:f185b2e953836028b9c2ed70c380f41155f68abc6357843a33bed1afe1345cea` | 2026-05-20、33 symbols、capture `2026-09-07T12:24:00.737021-07:00`，capture 晚於歷史決策 cutoff；`historical_decision_time_available=false` |
| Label replay | file `sha256:3f1a1432697551d18beecd82463f283b9ca033f31a889d3843d12b4e1bc09b08`；logical replay `sha256:eabaf3ecc55bf9944ea72c9848d4d1697801014352d65239cd1bb86f9e98269e` | 33/33 rows 由既有 `portfolio_ml_dataset_assembler._build_label_spool` replay；original SQLite 保留，overlay 只進 corrected supervised label |
| ResearchShadowUnion | manifest file `sha256:3a12bd8f0aa92f672e7cd3937f226c15980f799e89526751f164f5e9f448289f`；logical manifest `sha256:21f2a11cec3a84dd0fc11b66a617da997b5b4eb9cafcf605547ff099fbd2c657`；feature registry `sha256:8af2e100ed785cd5dd3294e79f0c7cc907be8400fef6b76acbbdf9029e3be45a` | full union 為 all-symbols research-only manifest，但其 2026 shard 最後日期為 2026-03-23；overlay 2026-05-20 不在 union 日期範圍，故 `0 symbol / 0 row`，沒有事後補接 |
| Shared PIT | manifest file `sha256:f49b5ed2a650ebc97c51eb26d5c5244d1f43f248bc0f4333cf28d38da5361aac`；logical manifest `sha256:61d0ced0bcbd96a56f8a66c8caefd5ff42fe4436db4d0e74b66243d157a89543`；feature contract `sha256:5eaba73dcf4a46d5a668e4a532ac6d50be49972e987151139e5a679dcb3c676c` | overlay 交集為 2454 一檔、3 PIT rows；`available_at <= 2026-05-20T08:30:00+08:00` 為 `0`，所以 3 rows 只作 readback，沒有進決策 feature |
| Direct numeric | manifest file `sha256:f1932ff3faeec2b4f71638c7556048b5120d7d15317008cbd2e31700dce6ab6a`；logical manifest `sha256:988bd6a8d0c71a7fdc30ae775ca6f2e0cfbca1b6119fe542e36b43e6e75384a5`；2026 year manifest `sha256:841180b09b5f880c2c43ba8e1d60a048be86d6dd494581eadf9a227a2831a283`；rows SQLite file `sha256:52cc3a30d4cbd77ecda8c74b75dcce914cc52b3d2307ecfde20cabec63d15796` | 2026-05-20 Direct rows 11 檔；與 33 筆 overlay 交集為 2454 一檔。只 read-only 查詢 frozen row identity、sample hash、target/label availability；沒有讀 numeric features/targets |

逐列 label 差異由輸出 `label_diff` 保存：33/33 symbols changed，總共 157 個 head，包含
`benchmark_excess_return_bp` 33、`mae_loss_bp` 33、`mfe_gain_bp` 33、
`realized_volatility_bp` 33、`downside_observed` 24、`tail_loss_bp` 1。
2454 的 Direct row、PIT 3-row readback、original/corrected labels 與每個來源 hash
都在 `rows[]` 中可獨立核對。

## Synthetic teacher contract QA

`tests/test_ml_research_shadow_overlay_integration.py` 的
`test_synthetic_teacher_source_to_assembler_gate_is_explicitly_research_only`
以隔離合成 sector、Rule history、ledger source artifact 實際呼叫
`build_teacher_source_row_provenance_for_assembly`，再送入
`evaluate_allocation_teacher_eligibility`。測試確認 source rows 是 artifact
rebuild、availability 可驗證、gate 可通過，但仍固定
`formal_oos_allowed=false`、`broker_order_allowed=false`、`production_alpha_bp=0`。
這個 positive 只代表 synthetic contract wiring，不是 Formal custody。現有
`test_missing_ledger_availability_is_a_blocked_gate_state` 仍驗證 ledger
availability 缺失時 gate fail closed；沒有移除 OOC 的正式來源要求。
同一測試檔另以 tamper cases 驗證 nested `comparison.json` 與 `receipt.json`
的內容 hash；即使外層 overlay 仍帶有格式正確的 digest，內容改寫也會在
下游 Union/PIT/Direct readback 前 fail closed。

## 驗證與限制

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_research_shadow_overlay_integration.py -q -o addopts=
.\.venv\Scripts\python.exe -m mypy --explicit-package-bases data_module/ml_research_shadow_overlay_integration.py scripts/build_ml_research_shadow_overlay_direct_readback.py
.\.venv\Scripts\python.exe -m py_compile data_module/ml_research_shadow_overlay_integration.py scripts/build_ml_research_shadow_overlay_direct_readback.py
```

結果：`5 passed`（pytest cache 權限 warning）、mypy `Success: no issues found in 2 source files`、
py_compile 成功。研究產物所有安全旗標均維持 false/zero；它是 partial
readback 與 label-diff 證據，不是 performance、formal PIT custody、training
或 promotion 證據。官方 overlay capture 是事後取得，不能改寫成 2026-05-20
08:30 的歷史可得資料。
