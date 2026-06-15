# Month 3 Factor Layer v1 Design

> **狀態**：設計草案，供實作計畫與後續工程 Gate 使用。  
> **範圍**：Month 3 只建立 Factor Layer 地基，不接營收、法人、估值等新資料源。  
> **權威對齊**：目前狀態以 `docs/00_core/PROJECT_SNAPSHOT.md` 為準；未來路線以 `docs/00_core/ROADMAP_6M_ENGINEERING.md` 為準；架構邊界以 `docs/01_architecture/system_architecture.md` 為準。

## 1. 目標

Month 3 的目標是建立可插拔、可追溯、可防未來函數的 Factor Layer v1，讓後續營收、基本面、估值、三大法人與更多籌碼資料能安全接入，而不是直接污染既有 `ScoringEngine`、推薦服務或回測核心。

本階段完成後，系統應具備：

1. 統一 Factor Contract。
2. Factor Registry 與品質語意。
3. Look-ahead Gate，拒絕決策當下不可取得的資料。
4. 既有技術、量能與券商分點資料的 adapter。
5. Research Run 可保存 factor snapshot / contribution，以便比較與追溯。

## 2. 不做什麼

- 不接月營收、財報、估值或三大法人新資料源。
- 不改變既有 `ScoringEngine` 的核心評分公式。
- 不把 factor 權重直接塞進 UI 或硬編碼到推薦服務。
- 不把缺失資料硬補成 0。
- 不宣稱新增 factor 會提高績效；任何績效改善都必須另走 OOS 實證。

## 3. 核心契約

### 3.1 FactorRecord

Factor v1 的單筆標準輸出稱為 `FactorRecord`，欄位如下：

| 欄位 | 型別 | 規則 |
|---|---|---|
| `factor_name` | `str` | 穩定識別碼，例如 `technical.rsi`, `volume.volume_ratio`, `broker_flow.net_lots`。 |
| `stock_code` | `str` | 台股代號，保留字串格式。 |
| `as_of_date` | `date` | Factor 所描述的資料日期。 |
| `available_date` | `date` | 決策系統可取得該資料的最早日期。 |
| `value` | `Decimal | int | str | None` | 原始或標準化後的 factor 值；金融核心數值不使用裸 `float`。 |
| `score_bp` | `int | None` | 0 到 10000 的整數基點分數；不可用時為 `None`。 |
| `quality` | enum | `observed`、`estimated`、`missing`、`neutral`、`stale`。 |
| `missing_policy` | enum | `fail_closed`、`neutral`、`skip`。 |
| `source_version` | `str` | 資料來源、算法或 adapter 版本。 |
| `metadata` | `dict` | 非決策用補充資訊，例如 rank、window、source table、diagnostics。 |

### 3.2 品質語意

| 品質 | 意義 | 預設處理 |
|---|---|---|
| `observed` | 原始資料直接觀測且日期合法。 | 可參與 factor aggregation。 |
| `estimated` | 由可靠輸入估算，信心較低。 | 可參與，但必須保留 metadata。 |
| `missing` | 缺少資料。 | 依 `missing_policy` 處理，不中斷整體流程。 |
| `neutral` | 明確採中性值，不視為缺失。 | 可參與，但不得偽裝成 observed。 |
| `stale` | 資料過舊，超過 registry 定義的新鮮度。 | 預設 skip 或 neutral，需記錄原因。 |

### 3.3 Look-ahead Gate

任何 factor 在決策日 `decision_date` 使用前，必須通過：

```text
available_date <= decision_date
```

若 `available_date > decision_date`：

- `missing_policy = fail_closed`：直接拒絕該次決策或該 factor set。
- `missing_policy = neutral`：轉為 `quality = neutral`，`score_bp` 使用 registry 定義的中性分數。
- `missing_policy = skip`：該 factor 不參與 aggregation，並在 diagnostics 記錄。

Look-ahead Gate 不允許靜默降級；每一次拒絕、轉中性或跳過都必須可追溯。

## 4. 架構設計

### 4.1 新增模組

建議新增 `decision_module/factors/`：

```text
decision_module/factors/
  __init__.py
  factor_dtos.py
  factor_registry.py
  factor_gate.py
  factor_adapters.py
```

責任：

- `factor_dtos.py`：定義 `FactorRecord`、`FactorDefinition`、品質 enum 與 missing policy enum。
- `factor_registry.py`：保存 factor 定義、版本、可接受品質、stale window、中性分數與 adapter key。
- `factor_gate.py`：集中處理 `available_date`、品質與 missing policy，不讓各服務自行判斷。
- `factor_adapters.py`：提供既有資料轉 factor 的 adapter 介面與 v1 adapter。

### 4.2 Application Layer 整合

建議新增 `app_module/factor_service.py`，作為 UI / research service 使用的 application service：

```text
Recommendation / Replay / Research Run
  -> FactorService.collect(...)
  -> adapters emit FactorRecord[]
  -> FactorGate.validate_for_decision(...)
  -> factor snapshot / contribution
  -> ResearchRunService.save_run(...)
```

`FactorService` 不直接修改 scoring，也不直接寫入正式資料表。v1 只回傳記憶體 DTO 與 Research Run metadata。

### 4.3 Research Run 保存

`ResearchRunMetadata` 的 JSON 欄位可新增或沿用可擴充 metadata：

```json
{
  "factor_snapshot": {
    "schema_version": 1,
    "decision_date": "2026-06-14",
    "factor_set_version": "factor-layer-v1",
    "records": []
  },
  "factor_contributions": {
    "schema_version": 1,
    "by_stock": {}
  }
}
```

v1 不要求建立新 SQLite table；先保存於 registry metadata JSON，降低 migration 風險。若後續 Month 4/5 需要大量查詢，再設計正式 factor tables。

## 5. v1 Factor Set

Month 3 v1 只包裝既有資料：

1. `technical.total_score`
   - 來源：既有推薦 / scoring 結果。
   - `available_date`：該分數使用資料的最後可得日。
   - `score_bp`：由既有分數轉整數基點。

2. `volume.volume_ratio`
   - 來源：既有量能欄位或推薦結果中的 volume score。
   - `quality`：資料存在且日期合法為 `observed`，缺失走 registry policy。

3. `broker_flow.net_lots`
   - 來源：既有 `BrokerFlowService` / `PortfolioChipService` 的品質三態。
   - `quality`：沿用 observed / estimated / unavailable 語意，轉換為 Factor Layer 的 observed / estimated / missing。

## 6. 資料流

```text
Existing service output
  -> Factor adapter
  -> FactorRecord[]
  -> FactorGate(decision_date)
  -> accepted / neutralized / skipped / rejected records
  -> Research Run metadata
  -> Cross-run comparison reads saved factor metadata
```

這條資料流的關鍵是「保存當時看到的 factor 狀態」，不是在比較時重新抓取目前資料。

## 7. 錯誤與診斷

Factor Layer 應輸出結構化 diagnostics：

| code | 意義 |
|---|---|
| `factor.lookahead_rejected` | `available_date > decision_date` 且 policy 為 fail-closed。 |
| `factor.neutralized_missing` | 缺資料但 policy 允許轉中性。 |
| `factor.skipped_missing` | 缺資料且 policy 為 skip。 |
| `factor.stale` | 資料超過 stale window。 |
| `factor.invalid_score_bp` | `score_bp` 非整數或超出 0-10000。 |

診斷需能被 Research Run 保存與 Excel / 後續報告輸出使用。

## 8. 測試策略

Month 3 必須使用 TDD，每個增量先寫測試。

必備測試：

1. `FactorRecord` 驗證 `score_bp` 範圍與品質 enum。
2. `FactorGate` 拒絕 `available_date > decision_date`。
3. missing / neutral / stale 三態處理。
4. broker flow unavailable 不被當成 0。
5. Research Run 保存與載入 factor snapshot。
6. Cross-run comparison 只讀保存的 factor metadata，不重新抓目前資料。

量化防禦：

- 策略 / 回測 / 推薦 / factor 改動後跑 `.\.venv\Scripts\python.exe scripts\quant_guard_linter.py`。
- 若修改金融核心白名單，另跑 `.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py`。
- Factor look-ahead 不能只依賴靜態 linter，必須有單元測試覆蓋。

## 9. 文件同步範圍

實作 Month 3 時，至少檢查：

- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/00_core/DEVELOPMENT_ROADMAP.md`
- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/01_architecture/system_architecture.md`
- `docs/07_guides/APPLICATION_MANUAL.md`（若 UI 或使用者可見流程改變）
- `docs/02_features/UI_FEATURES_DOCUMENTATION.md`（若 UI 顯示 factor 品質）
- `docs/02_features/USER_GUIDE.md`（若新增使用者解讀方式）

## 10. 風險

| 風險 | 防線 |
|---|---|
| 未來函數滲漏 | `available_date` gate + no-look-ahead tests。 |
| 缺資料被當成 0 | 品質 enum + missing policy + diagnostics。 |
| ScoringEngine 被污染 | v1 adapter 只輸出 factor，不改核心 scoring。 |
| JSON metadata 過大 | v1 先保存 snapshot 摘要與 contribution；大量資料再另設 table。 |
| 使用者誤解為績效改善 | 文件與 UI 只宣稱可追溯，不宣稱更準。 |

## 11. Month 3 Definition of Done

- Factor Contract、Registry、Gate 與 v1 adapters 完成。
- 技術、量能、券商分點至少一條完整走過 factor path。
- `available_date > decision_date` 會被拒絕、轉中性或跳過，且 diagnostics 可追溯。
- Research Run 可保存並讀回 factor snapshot / contribution。
- Cross-run comparison 不重新抓取目前 factor 資料。
- 所有新增金融/量化邊界通過 quant guard 與 no-look-ahead 測試。
- 文件同步完成，且 Snapshot 明確顯示 Month 3 已進入 Factor Layer v1。

