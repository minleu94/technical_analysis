# Month 3 Factor Run Integration Plan

> **狀態**：已實作。
> **範圍**：把既有 Factor Layer v1 snapshot serialization 接入 Research Run 實際保存流程；不新增資料源、不改 `ScoringEngine` 核心、不做 SQLite schema migration。

## 目標

讓 `ResearchRunService.save_run()` 成為 factor 追溯 metadata 的實際寫入 owner。呼叫端可提供已建好的 `factor_snapshot` / `factor_contributions`，或提供 `FactorRecord` 與決策日，由 service 透過 `FactorService` 建立 snapshot 與 contribution summary 後寫入 `data_manifest`。

## Scope In

- `FactorService.build_contributions()`：由已 gate 的 snapshot 產生 `by_stock` 與 `summary_by_factor`。
- `ResearchRunService.save_run()`：在 SQLite metadata 寫入前合併 `data_manifest.factor_snapshot` 與 `data_manifest.factor_contributions`。
- 保留既有 manifest 欄位，例如 `daily_prices`、`technical_indicators` 或後續資料 fingerprint 明細。
- 單元測試覆蓋實際 save/load round-trip。

## Scope Out

- 不新增營收、法人、估值或其他資料來源。
- 不變更 Research Run SQLite schema。
- 不在 Cross-run Comparison 重新抓取當前 factor 資料。
- 不宣稱 factor 讓績效提升。

## 實作步驟

- [x] 先寫失敗測試：`FactorService` contribution summary、`ResearchRunService.save_run()` factor records 寫入與 explicit factor metadata 合併。
- [x] 實作 `FactorService.build_contributions()`。
- [x] 擴充 `ResearchRunService.save_run()` 的 optional factor metadata 參數。
- [x] 在寫入前以 `replace(metadata, data_manifest=...)` 建立不可變 DTO 快照。
- [x] 驗證保存後 `load_run_data()` 可讀回 `factor_snapshot` / `factor_contributions`。

## 驗收

- 已通過 focused regression：
  - `tests/test_factor_service_research_run.py`
  - `tests/test_research_run_service.py`
  - `tests/test_research_run_comparison_service.py`
- Look-ahead gate 仍由 `FactorService.build_snapshot()` 呼叫 `FactorGate` 執行。
- `factor_contributions` 只由已保存 snapshot 摘要而來，不重算策略、不讀取當前市場資料。
