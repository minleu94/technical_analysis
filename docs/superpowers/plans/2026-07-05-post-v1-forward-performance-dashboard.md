# Post-V1 Forward Performance Dashboard Read-only UI Plan 2026-07-05

## Goal

建立 Forward Performance Dashboard read-only UI v1，讓 Research Lab 可檢查已保存 evidence events / outcomes 的 forward summary、coverage、quality 與 warnings。

## Checklist

- [x] Checkpoint Round 4 local commit，且不 push。
- [x] Preflight：確認 UI placement、read model contract、現有 Qt pattern 與安全邊界。
- [x] 新增 dashboard DTO。
- [x] 新增 dashboard service，僅呼叫 `ForwardPerformanceReadModel`。
- [x] 新增 read-only evidence repository adapter，用 SQLite read-only mode 支援 UI 查詢。
- [x] 新增 Qt table model，display role 格式化 bp，raw value 保留 bp。
- [x] 新增 Forward Performance view。
- [x] 掛入 Research Lab 結果分頁 `Forward Evidence`。
- [x] 新增 service / UI / forbidden language tests。
- [x] 完整驗證命令。
- [x] QA 文件回填實際結果。

## Files

新增：

- `app_module/forward_performance_dashboard_dtos.py`
- `app_module/forward_performance_dashboard_service.py`
- `ui_qt/models/forward_performance_table_model.py`
- `ui_qt/views/forward_performance_view.py`
- `tests/test_forward_performance_dashboard_service.py`
- `tests/test_ui_qt_forward_performance_view.py`
- `tests/test_forward_performance_dashboard_no_trading_language.py`
- `docs/superpowers/specs/2026-07-05-post-v1-forward-performance-dashboard-design.md`
- `docs/superpowers/plans/2026-07-05-post-v1-forward-performance-dashboard.md`
- `docs/06_qa/POST_V1_FORWARD_PERFORMANCE_DASHBOARD_QA_2026_07_05.md`

修改：

- `ui_qt/views/backtest/result_panel.py`
- core docs 與 manual

## Verification

必跑：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_forward_performance_dashboard_service.py tests/test_ui_qt_forward_performance_view.py tests/test_forward_performance_dashboard_no_trading_language.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests/test_forward_performance_read_model.py tests/test_summarize_forward_performance_cli.py tests/test_evidence_pipeline_smoke.py -q -o addopts=
.\.venv\Scripts\python.exe scripts/check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m py_compile <expanded changed python files>
git diff --check
```

## Risks

- UI 初始化若建 schema，會違反 read-only intent；以 read-only repository adapter 避免。
- 正向 return 顯示若用強烈配色，可能暗示訊號有效；表格不以正負報酬上色。
- 既有 repo 內有舊交易語彙；禁語測試聚焦新 dashboard surface。
- Dashboard 仍只能反映已保存 evidence，不代表樣本足夠或任一訊號有效。
