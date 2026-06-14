# SQLite 檢視器分頁與規格化 Excel 報告匯出實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 Phase 5 Month 1 的 SQLite 檢視器穩定分頁，以及單股回測、批次回測、推薦回放、目前推薦結果的可追溯 Excel 報告匯出。

**Architecture:** SQLite 分頁維持唯讀，由 `SqliteInspectorService` 統一建立篩選條件與穩定排序，UI 僅保存頁碼狀態並透過背景 worker 讀取。Excel 匯出先建立明確、不可變的 report payload DTO，再由純 application service 序列化為 `.xlsx`；UI 只負責建立 payload、選擇路徑與啟動背景工作，不在匯出層重新計算策略、績效或金融數值。

**Tech Stack:** Python 3、PySide6、pandas、SQLite、openpyxl、pytest、mypy

---

## 1. Scope 與安全契約

### Scope In

- SQLite Inspector 的資料庫層 `LIMIT/OFFSET` 分頁。
- 篩選後筆數統計、穩定排序與跨頁無重複/遺漏測試。
- 單股回測、批次回測、推薦回放、目前推薦結果的 Excel 匯出。
- 匯出工作在 `TaskWorker` 背景執行，採暫存檔完成後原子替換。
- UI 按鈕狀態、錯誤處理、空結果處理與文件同步。

### Scope Out

- PDF 匯出。
- Research Run Registry、Cross-run Comparison 或新資料庫 schema。
- SQLite 寫入、migration、資料重建或正式資料修改。
- 重新計算 Sharpe、Sortino、Monte Carlo、PnL、benchmark 或其他績效。
- 為補齊報告而偽造 data version、strategy version、Regime 或 benchmark。
- 改變回測、推薦、撮合、評分、風控或 Look-ahead 行為。

### 強制安全規則

- 匯出服務只能序列化 payload 已提供的值；缺值輸出 `N/A` 並記錄於「資料完整性」區塊。
- 金融數值沿用既有 DTO/application boundary；匯出服務不得新增裸 `float` 核心計算。
- Excel 寫入時允許在 presentation boundary 將 `Decimal` 轉成 Excel 可接受的數值或字串。
- SQLite 查詢必須維持白名單、參數化篩選與唯讀行為。
- `COUNT` 與 page query 必須共用相同 filter builder，避免頁數與資料不一致。
- 同日期多筆資料必須加入穩定 tie-breaker；不得只用日期排序。
- 實作開始時依 repo 規則更新 `docs/agents/shared_state/active_task.yaml`；交接或進入 QA Gate 時追加 `handoff_log.md`，但兩者不得 stage。

## 2. 檔案結構

### 新增

- `app_module/report_export_dtos.py`
  - 定義報告 metadata、資料完整性、四種 export payload DTO。
- `app_module/report_export_service.py`
  - 純 Excel workbook 建立、格式化、暫存寫入與原子替換。
- `tests/test_report_export_dtos.py`
  - payload 建構、缺失欄位與不可變快照測試。
- `tests/test_report_export_service.py`
  - 四種 workbook 的 sheet/schema/value/format/失敗清理測試。
- `tests/test_ui_qt_report_export.py`
  - 匯出按鈕狀態、payload 傳遞與背景 worker 行為測試。

### 修改

- `requirements.txt`
  - 新增有界版本 `openpyxl>=3.1,<4`。
- `app_module/sqlite_inspector_service.py`
  - 共用 filter builder、穩定排序、count 與 offset。
- `ui_qt/widgets/sqlite_inspector_widget.py`
  - 分頁控制、查詢世代防 stale result、schema 快取。
- `tests/test_sqlite_inspector_service.py`
  - count、offset、排序與跨頁契約。
- `tests/test_ui_qt_update_view_workbench.py`
  - SQLite Inspector 分頁 UI 契約。
- `ui_qt/views/backtest/result_panel.py`
  - 三個匯出按鈕。
- `ui_qt/views/backtest_view.py`
  - 建立 payload、背景匯出、按鈕生命週期。
- `ui_qt/views/recommendation_view.py`
  - 建立目前推薦 payload 與背景匯出。
- `docs/07_guides/APPLICATION_MANUAL.md`
  - 操作、欄位判讀、安全限制與排錯。
- `docs/02_features/UI_FEATURES_DOCUMENTATION.md`
  - 分頁與匯出功能說明。
- `docs/02_features/BACKTEST_LAB_FEATURES.md`
  - 回測報告內容與限制。
- `docs/01_architecture/system_architecture.md`
  - report payload/application service/UI worker 資料流。
- `PROJECT_NAVIGATION.md`
  - 新 service/DTO 與功能入口。
- `docs/00_core/PROJECT_SNAPSHOT.md`
  - Phase 5 Month 1 完成狀態。
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - Month 1 交付物與驗收結果。
- `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`
  - 大表格分頁與 Excel 報告移交項目的完成證據。
- `docs/00_core/DOCUMENTATION_INDEX.md`
  - 計畫連結與 Phase 5 狀態。

## Task 1: 鎖定依賴與建立 report payload 契約

**Files:**
- Modify: `requirements.txt`
- Create: `app_module/report_export_dtos.py`
- Create: `tests/test_report_export_dtos.py`

- [ ] **Step 1: 寫入 payload 失敗測試**

測試必須覆蓋：

```python
def test_single_backtest_payload_preserves_traceability_metadata():
    payload = SingleBacktestExportPayload(
        metadata=ReportMetadata(
            report_type="single_backtest",
            generated_at="2026-06-14T12:00:00",
            data_version="sha256:abc",
            strategy_version="baseline_score@1.0",
            regime="Trend",
            benchmark="TAIEX",
            execution_assumption="next_open",
        ),
        run_params={"fee_bps": 14.25, "slippage_bps": 5.0},
        metrics={"total_return": 0.12},
        validation={"status": "PASS", "messages": []},
        trades=pd.DataFrame(),
        equity_curve=pd.DataFrame(),
    )
    assert payload.metadata.data_version == "sha256:abc"
```

```python
def test_missing_traceability_fields_are_explicit():
    metadata = ReportMetadata(report_type="current_recommendation")
    assert set(metadata.missing_fields()) >= {
        "data_version",
        "strategy_version",
        "benchmark",
    }
```

```python
def test_payload_copies_input_dataframes():
    source = pd.DataFrame([{"equity": 100}])
    payload = SingleBacktestExportPayload(
        metadata=ReportMetadata(report_type="single_backtest"),
        run_params={},
        metrics={},
        validation={},
        trades=pd.DataFrame(),
        equity_curve=source,
    )
    source.loc[0, "equity"] = 0
    assert payload.equity_curve.loc[0, "equity"] == 100
```

- [ ] **Step 2: 執行測試並確認失敗**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_report_export_dtos.py -q -o addopts=
```

Expected: FAIL，因 `report_export_dtos.py` 尚不存在。

- [ ] **Step 3: 實作明確 payload DTO**

使用 frozen metadata 與 DataFrame defensive copy：

```python
@dataclass(frozen=True)
class ReportMetadata:
    report_type: str
    generated_at: str = ""
    data_as_of_date: str = ""
    data_version: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    regime: str = ""
    benchmark: str = ""
    execution_assumption: str = ""

    def missing_fields(self) -> list[str]:
        required = (
            "generated_at",
            "data_as_of_date",
            "data_version",
            "strategy_version",
            "regime",
            "benchmark",
            "execution_assumption",
        )
        return [name for name in required if not getattr(self, name)]
```

建立：

```python
SingleBacktestExportPayload
BatchBacktestExportPayload
RecommendationReplayExportPayload
CurrentRecommendationExportPayload
```

每個 payload 只接受報告所需的已完成資料，不接受 UI widget 或 repository。`__post_init__` 對 DataFrame 做深層 copy。

- [ ] **Step 4: 新增 openpyxl 依賴**

在 `requirements.txt` 新增：

```text
openpyxl>=3.1,<4
```

- [ ] **Step 5: 執行 DTO 測試**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_report_export_dtos.py -q -o addopts=
```

Expected: PASS。

- [ ] **Step 6: Commit**

```powershell
git add requirements.txt app_module/report_export_dtos.py tests/test_report_export_dtos.py
git commit -m "feat: define traceable report export payloads"
```

## Task 2: 建立穩定、可重用的 SQLite 分頁查詢

**Files:**
- Modify: `app_module/sqlite_inspector_service.py`
- Modify: `tests/test_sqlite_inspector_service.py`

- [ ] **Step 1: 寫入 count、offset 與穩定排序失敗測試**

新增同日期多股票、多分點資料，驗證：

```python
def test_query_table_data_count_uses_same_filters(test_config):
    service = SqliteInspectorService(test_config)
    assert service.query_table_data_count(
        "daily_prices",
        stock_name="積電",
        start_date="2026-05-28",
        end_date="2026-05-29",
    ) == 2
```

```python
def test_paginated_rows_are_stable_without_overlap(test_config):
    service = SqliteInspectorService(test_config)
    page_1 = service.query_table_data("daily_prices", limit=2, offset=0)
    page_2 = service.query_table_data("daily_prices", limit=2, offset=2)
    keys_1 = set(zip(page_1["日期"], page_1["證券代號"]))
    keys_2 = set(zip(page_2["日期"], page_2["證券代號"]))
    assert keys_1.isdisjoint(keys_2)
```

```python
@pytest.mark.parametrize("offset", [-1, -100])
def test_negative_offset_is_clamped_to_zero(test_config, offset):
    service = SqliteInspectorService(test_config)
    actual = service.query_table_data("daily_prices", limit=10, offset=offset)
    expected = service.query_table_data("daily_prices", limit=10, offset=0)
    pd.testing.assert_frame_equal(actual, expected)
```

- [ ] **Step 2: 執行測試並確認失敗**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_sqlite_inspector_service.py -q -o addopts=
```

Expected: FAIL，因 count/offset 尚未實作。

- [ ] **Step 3: 抽出共用 query plan**

在 service 建立私有 helper：

```python
def _build_filtered_query(
    self,
    table_name: str,
    *,
    stock_code: Optional[str] = None,
    stock_name: Optional[str] = None,
    date_str: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    broker_branch: Optional[str] = None,
) -> tuple[list[str], str, list[Any], str]:
    """回傳 valid_columns、WHERE SQL、params、ORDER BY SQL。"""
```

排序契約：

- 有 `日期`：`"日期" DESC`
- 有 `證券代號`：再加 `"證券代號" ASC`
- 有 `分點系統鍵`、`分點名稱`、`對手券商代號` 等欄位：依存在順序加入 tie-breaker
- 最後加入 `rowid ASC`，只用於目前五個 rowid table；若未來出現 `WITHOUT ROWID`，必須改由明確主鍵

- [ ] **Step 4: 實作 count 與 offset**

```python
def query_table_data_count(
    self,
    table_name: str,
    stock_code: Optional[str] = None,
    stock_name: Optional[str] = None,
    date_str: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    broker_branch: Optional[str] = None,
) -> int:
    _, where_sql, params, _ = self._build_filtered_query(
        table_name,
        stock_code=stock_code,
        stock_name=stock_name,
        date_str=date_str,
        start_date=start_date,
        end_date=end_date,
        broker_branch=broker_branch,
    )
    df = self.db_manager.execute_query(
        f'SELECT COUNT(*) AS cnt FROM "{table_name}"{where_sql}',
        tuple(params),
    )
    return int(df.iloc[0]["cnt"]) if not df.empty else 0
```

```python
def query_table_data(
    self,
    table_name: str,
    stock_code: Optional[str] = None,
    stock_name: Optional[str] = None,
    date_str: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    broker_branch: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> pd.DataFrame:
    limit = max(10, min(limit, 5000))
    offset = max(0, int(offset))
    valid_columns, where_sql, params, order_by_sql = self._build_filtered_query(
        table_name,
        stock_code=stock_code,
        stock_name=stock_name,
        date_str=date_str,
        start_date=start_date,
        end_date=end_date,
        broker_branch=broker_branch,
    )
    escaped_cols = ", ".join(f'"{column}"' for column in valid_columns)
    sql = (
        f'SELECT {escaped_cols} FROM "{table_name}"'
        f"{where_sql}{order_by_sql} LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])
    return self.db_manager.execute_query(sql, tuple(params))
```

- [ ] **Step 5: 執行 service 測試**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_sqlite_inspector_service.py -q -o addopts=
```

Expected: PASS。

- [ ] **Step 6: Commit**

```powershell
git add app_module/sqlite_inspector_service.py tests/test_sqlite_inspector_service.py
git commit -m "feat: add stable sqlite inspector pagination"
```

## Task 3: 實作 SQLite Inspector 分頁 UI 與 stale-result 防護

**Files:**
- Modify: `ui_qt/widgets/sqlite_inspector_widget.py`
- Modify: `tests/test_ui_qt_update_view_workbench.py`

- [ ] **Step 1: 寫入 UI 分頁失敗測試**

使用 fake inspector service 驗證：

```python
def test_sqlite_inspector_next_page_uses_offset(qtbot):
    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    widget.current_table = "daily_prices"
    widget.page_size = 100
    widget.current_page = 2
    widget._request_page(load_schema=False)
    assert service.last_query["offset"] == 100
```

```python
def test_filter_reload_resets_to_first_page(qtbot):
    widget.current_page = 4
    widget.stock_code_input.setText("2330")
    widget._load_current_table_data()
    assert widget.current_page == 1
```

```python
def test_stale_worker_result_is_ignored(qtbot):
    widget._active_request_id = 2
    widget._on_table_data_loaded(
        {
            "request_id": 1,
            "table_name": "daily_prices",
            "info": None,
            "schema": None,
            "filtered_count": 0,
            "preview": pd.DataFrame(),
        }
    )
    assert widget.preview_model is None
```

另驗證空結果顯示 `第 0 / 0 頁`、最後一頁禁用 next、跳頁上限同步。

- [ ] **Step 2: 執行目標測試並確認失敗**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
```

Expected: 新增測試 FAIL。

- [ ] **Step 3: 加入分頁控制與狀態**

初始化：

```python
self.current_page = 1
self.page_size = self.limit_spin.value()
self.total_filtered_records = 0
self.total_pages = 0
self._active_request_id = 0
self._cached_schema_table = ""
self._cached_schema_df = pd.DataFrame()
```

控制列包含：

```text
上一頁 | 第 X / Y 頁 | 下一頁 | 跳至 [spin] 頁 | 跳頁 | 共 N 筆
```

- [ ] **Step 4: 分離 reload 與 page request**

```python
def _load_current_table_data(self):
    self.current_page = 1
    self.page_size = self.limit_spin.value()
    self._request_page(load_schema=True)
```

```python
def _request_page(self, *, load_schema: bool):
    request_id = self._active_request_id + 1
    self._active_request_id = request_id
    offset = (self.current_page - 1) * self.page_size
```

背景 task 同一次 read request 回傳：

```python
{
    "request_id": request_id,
    "table_name": table_name,
    "info": info if load_schema else None,
    "schema": schema_df if load_schema else None,
    "filtered_count": filtered_count,
    "preview": preview_df,
}
```

禁止在分頁按鈕中重新讀 schema。新查詢到來時，不使用 `terminate()` 中止舊 SQLite worker；允許舊 worker 完成並以 `request_id` 忽略 stale result。

- [ ] **Step 5: 更新 UI 狀態**

```python
self.total_pages = (
    math.ceil(self.total_filtered_records / self.page_size)
    if self.total_filtered_records
    else 0
)
self.prev_btn.setEnabled(self.current_page > 1)
self.next_btn.setEnabled(self.current_page < self.total_pages)
self.jump_spin.setRange(1, max(1, self.total_pages))
```

若刪減/更新資料導致目前頁超界，將頁碼 clamp 至最後一頁並重新 request 一次。

- [ ] **Step 6: 執行 UI 目標測試**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
```

Expected: PASS。

- [ ] **Step 7: Commit**

```powershell
git add ui_qt/widgets/sqlite_inspector_widget.py tests/test_ui_qt_update_view_workbench.py
git commit -m "feat: add sqlite inspector pagination controls"
```

## Task 4: 實作純 Excel exporter 與原子寫入

**Files:**
- Create: `app_module/report_export_service.py`
- Create: `tests/test_report_export_service.py`

- [ ] **Step 1: 寫入 workbook schema 失敗測試**

四種報告分別驗證固定 sheet 名稱：

```python
assert workbook.sheetnames == ["摘要與設定", "交易明細", "淨值與回撤"]
assert workbook["摘要與設定"]["A1"].value == "單股回測研究報告"
```

```python
assert workbook.sheetnames == ["批次總覽", "排行榜", "失敗與警告"]
```

```python
assert workbook.sheetnames == [
    "回放摘要與設定",
    "期間持倉",
    "個股貢獻",
    "交易紀錄",
    "淨值與回撤",
]
```

```python
assert workbook.sheetnames == ["推薦總覽與配置", "推薦股票名單"]
```

另外測試：

- 缺少 metadata 時「資料完整性」列出缺失欄位。
- equity curve 只有 `equity` 時由 presentation helper 產生 drawdown。
- 已提供 drawdown 時不得覆寫。
- `NaN`、`inf`、`None`、timezone datetime、`Decimal` 可安全寫入。
- 儲存失敗不留下目標檔與 `.tmp`。

- [ ] **Step 2: 執行測試並確認失敗**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_report_export_service.py -q -o addopts=
```

Expected: FAIL，因 service 尚不存在。

- [ ] **Step 3: 實作 workbook 共用元件**

```python
class ReportExportService:
    def export_single_backtest(
        self, target_path: Path, payload: SingleBacktestExportPayload
    ) -> Path:
        return self._export(
            target_path,
            lambda: self._build_single_backtest_workbook(payload),
        )

    def export_batch_backtest(
        self, target_path: Path, payload: BatchBacktestExportPayload
    ) -> Path:
        return self._export(
            target_path,
            lambda: self._build_batch_backtest_workbook(payload),
        )

    def export_recommendation_replay(
        self, target_path: Path, payload: RecommendationReplayExportPayload
    ) -> Path:
        return self._export(
            target_path,
            lambda: self._build_recommendation_replay_workbook(payload),
        )

    def export_current_recommendation(
        self, target_path: Path, payload: CurrentRecommendationExportPayload
    ) -> Path:
        return self._export(
            target_path,
            lambda: self._build_current_recommendation_workbook(payload),
        )
```

共用私有 helper：

```python
_normalize_target_path
_write_key_value_section
_write_dataframe
_safe_excel_value
_apply_header_style
_apply_number_formats
_set_bounded_column_widths
_freeze_and_filter
_build_drawdown_series
_save_atomically
```

欄寬必須有上限，例如 `min(max_width, 60)`，避免長推薦理由造成昂貴或失控的寬欄。

- [ ] **Step 4: 實作原子寫入**

```python
tmp_path = target_path.with_name(f".{target_path.name}.{uuid4().hex}.tmp")
try:
    workbook.save(tmp_path)
    os.replace(tmp_path, target_path)
finally:
    if tmp_path.exists():
        tmp_path.unlink()
```

`target_path` 自動補 `.xlsx`。目標父目錄必須已存在；不得暗中建立任意正式資料目錄。

- [ ] **Step 5: 鎖定資料來源**

- 單股：metrics 來自 `BacktestReportDTO`，trades/equity 來自 `report.details` 的既有資料。
- 批次：直接使用 `BatchBacktestResultDTO` 與未格式化 leaderboard DataFrame，不從 UI 顯示字串反解析。
- 推薦回放：使用 result DTO 的 summary、period dataframe、contribution dataframe、trades、equity、diagnostics/hints。
- 目前推薦：使用 `RecommendationResultDTO` 快照，而非鬆散 `List + Dict`。
- benchmark 僅輸出 payload 已提供的名稱/結果；不得在 exporter 內查資料庫。

- [ ] **Step 6: 執行 exporter 測試**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_report_export_service.py -q -o addopts=
```

Expected: PASS。

- [ ] **Step 7: Commit**

```powershell
git add app_module/report_export_service.py tests/test_report_export_service.py
git commit -m "feat: export traceable research reports to excel"
```

## Task 5: 整合 Backtest UI 背景匯出

**Files:**
- Modify: `ui_qt/views/backtest/result_panel.py`
- Modify: `ui_qt/views/backtest_view.py`
- Create: `tests/test_ui_qt_report_export.py`

- [ ] **Step 1: 寫入按鈕與 payload 失敗測試**

覆蓋：

```python
def test_backtest_export_button_enabled_only_with_current_report(
    qtbot, backtest_view, backtest_report
):
    assert not backtest_view.export_report_btn.isEnabled()
    backtest_view._on_backtest_finished(backtest_report)
    assert backtest_view.export_report_btn.isEnabled()
```

```python
def test_batch_export_uses_raw_batch_result_not_formatted_table(
    backtest_view, batch_result
):
    backtest_view.current_batch_result = batch_result
    payload = backtest_view._build_batch_export_payload()
    assert payload.overall_stats == batch_result.overall_stats
```

```python
def test_export_failure_restores_button_and_preserves_existing_file(
    qtbot, backtest_view, tmp_path, monkeypatch
):
    target = tmp_path / "existing.xlsx"
    target.write_bytes(b"existing")
    monkeypatch.setattr(
        backtest_view.report_export_service,
        "export_single_backtest",
        lambda target_path, payload: (_ for _ in ()).throw(OSError("locked")),
    )
    backtest_view._export_single_backtest_to_path(target)
    qtbot.waitUntil(lambda: backtest_view.export_report_btn.isEnabled())
    assert target.read_bytes() == b"existing"
```

- [ ] **Step 2: 執行測試並確認失敗**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_report_export.py -q -o addopts=
```

Expected: FAIL。

- [ ] **Step 3: 在 ResultPanel 加入三個按鈕**

- 實驗摘要：`export_report_btn`
- 批次結果：`export_batch_report_btn`
- 推薦回放：`export_portfolio_report_btn`

三者預設 disabled，並加上 tooltip 說明「報告只輸出目前結果，不重新計算績效」。

- [ ] **Step 4: 在 BacktestView 建立 payload builder**

新增純方法：

```python
_build_single_backtest_export_payload()
_build_batch_export_payload()
_build_recommendation_replay_export_payload()
```

metadata 取得順序：

1. 已保存 run/result metadata。
2. `current_run_params` 或 recommendation replay config。
3. `report.details` / result summary。
4. 仍缺少則留空，交由 exporter 標示 `N/A`。

不得以目前 UI 控制值冒充已完成 run 的歷史設定。

- [ ] **Step 5: 建立共用背景匯出流程**

```python
def _start_excel_export(self, *, target_path, export_callable, payload, button):
    button.setEnabled(False)
    button.setText("匯出中...")
    worker = TaskWorker(export_callable, Path(target_path), payload)
    worker.finished.connect(
        lambda path: self._on_excel_export_finished(button, path)
    )
    worker.error.connect(
        lambda message: self._on_excel_export_error(button, message)
    )
    worker.cancelled.connect(
        lambda: self._on_excel_export_cancelled(button)
    )
    self._report_export_workers.append(worker)
    worker.start()
```

需求：

- 保存 worker reference，避免被 GC。
- 成功、error、cancelled 都恢復按鈕文字與 enabled 狀態。
- 成功顯示實際路徑。
- 錯誤對話框只顯示摘要，完整 traceback 寫 logger。
- 關閉 view 時採合作式等待；不得 `terminate()` 正在寫 Excel 的 worker。

- [ ] **Step 6: 執行 UI 匯出測試**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_report_export.py -q -o addopts=
```

Expected: Backtest cases PASS。

- [ ] **Step 7: Commit**

```powershell
git add ui_qt/views/backtest/result_panel.py ui_qt/views/backtest_view.py tests/test_ui_qt_report_export.py
git commit -m "feat: add background excel export to research lab"
```

## Task 6: 整合 Recommendation UI 背景匯出

**Files:**
- Modify: `ui_qt/views/recommendation_view.py`
- Modify: `tests/test_ui_qt_report_export.py`

- [ ] **Step 1: 寫入推薦匯出失敗測試**

```python
def test_recommendation_export_hidden_without_results(qtbot, recommendation_view):
    assert not recommendation_view.export_report_btn.isVisible()
```

```python
def test_recommendation_export_uses_result_snapshot(
    recommendation_view, recommendations
):
    recommendation_view.current_recommendations = recommendations
    payload = recommendation_view._build_current_recommendation_export_payload()
    assert payload.result.recommendations == recommendations
    assert payload.result.regime == recommendation_view.current_regime
```

空推薦結果時，按鈕必須維持隱藏且不可匯出舊結果。

- [ ] **Step 2: 執行測試並確認失敗**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_report_export.py -q -o addopts=
```

Expected: 新增 recommendation cases FAIL。

- [ ] **Step 3: 加入按鈕與 snapshot payload**

重用 `_build_current_result_snapshot()`，建立 `CurrentRecommendationExportPayload`。分析開始時先清除舊 `current_recommendations` 並隱藏按鈕；成功且結果非空時才顯示。

- [ ] **Step 4: 使用背景 worker 匯出**

行為與 Backtest 一致：

- 自動補 `.xlsx`
- 匯出中禁用
- 成功/失敗恢復
- 不在 UI thread 建 workbook
- 不在 exporter 重新取得 Regime 或推薦資料

- [ ] **Step 5: 執行 UI 匯出測試**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_report_export.py -q -o addopts=
```

Expected: PASS。

- [ ] **Step 6: Commit**

```powershell
git add ui_qt/views/recommendation_view.py tests/test_ui_qt_report_export.py
git commit -m "feat: export current recommendations to excel"
```

## Task 7: 文件 Coverage Pass 與 Patch Pass

**Files:**
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/02_features/UI_FEATURES_DOCUMENTATION.md`
- Modify: `docs/02_features/BACKTEST_LAB_FEATURES.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `PROJECT_NAVIGATION.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`

- [ ] **Step 1: 執行 Documentation Coverage Pass**

依 `docs/00_core/DOC_COVERAGE_MAP.md` 確認 Must/Should 文件。不得先把 Roadmap 標記完成；必須等功能與驗證通過。

- [ ] **Step 2: 更新 Manual**

必須包含：

- SQLite 分頁入口、每頁筆數、上一頁/下一頁/跳頁。
- 篩選變更會回到第一頁。
- 總筆數是篩選後筆數。
- 資料更新期間翻頁可能看到新的總筆數，重新載入可取得一致結果。
- 四種 Excel 報告入口與按鈕啟用條件。
- `N/A` 代表來源結果未提供，不代表零。
- 報告不會重新計算或修正回測結果。
- 匯出失敗、檔案被 Excel 鎖定、路徑不可寫的排錯。

- [ ] **Step 3: 更新架構與功能文件**

資料流：

```text
Current Result DTO / Run Metadata
  -> Export Payload Builder
  -> immutable payload snapshot
  -> TaskWorker
  -> ReportExportService
  -> temporary xlsx
  -> atomic replace
```

- [ ] **Step 4: 驗證通過後更新狀態權威**

- Snapshot：Phase 5 部分完成項加入「SQLite 分頁與 Excel 報告」。
- 6M Roadmap：Month 1 最小輸出標記 Excel 完成，PDF 仍未完成。
- Legacy Carryover：只將「大表格分頁」標記完成；報告項目明確記錄 Excel 完成、PDF 尚未完成，不得把 Excel/PDF 整項誤標完成。
- Index：加入本 plan，更新 Phase 5 狀態。

- [ ] **Step 5: Commit**

```powershell
git add docs/07_guides/APPLICATION_MANUAL.md docs/02_features/UI_FEATURES_DOCUMENTATION.md docs/02_features/BACKTEST_LAB_FEATURES.md docs/01_architecture/system_architecture.md PROJECT_NAVIGATION.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/00_core/LEGACY_ROADMAP_CARRYOVER.md docs/00_core/DOCUMENTATION_INDEX.md
git commit -m "docs: document sqlite pagination and excel reports"
```

## Task 8: 完整驗證與 QA Gate

**Files:**
- Verify all changed files

- [ ] **Step 1: 執行 focused pytest**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_sqlite_inspector_service.py tests\test_report_export_dtos.py tests\test_report_export_service.py tests\test_ui_qt_report_export.py -q -o addopts=
```

Expected: PASS。

- [ ] **Step 2: 執行強制 UI pytest**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
```

Expected: PASS。

- [ ] **Step 3: 執行 Update Tab QA**

```powershell
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

Expected: 所有檢查通過；不要 stage `output/qa/update_tab/RUN_LOG.txt` 或 `VALIDATION_REPORT.md`，除非任務另有明確要求。

- [ ] **Step 4: 執行完整 mypy**

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

Expected: PASS。

- [ ] **Step 5: 執行金融 float boundary gate**

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

Expected: PASS；匯出 presentation boundary 若出現轉型，必須有既有格式的 boundary 註記。

- [ ] **Step 6: 執行 py_compile**

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\report_export_dtos.py app_module\report_export_service.py app_module\sqlite_inspector_service.py ui_qt\widgets\sqlite_inspector_widget.py ui_qt\views\backtest\result_panel.py ui_qt\views\backtest_view.py ui_qt\views\recommendation_view.py
```

Expected: PASS。

- [ ] **Step 7: 手動驗證 SQLite 分頁**

使用 `technical_indicators` 與 `broker_flows`：

1. 驗證第一頁、下一頁、上一頁、最後一頁與跳頁。
2. 驗證改變股票、名稱、分點、單日、日期區間篩選後回到第一頁。
3. 驗證頁面資料無重複，總筆數與篩選一致。
4. 快速連續切表/跳頁時，舊 worker 結果不得覆蓋新查詢。
5. 記錄 page query 的實測時間；驗收標準以「UI 無假死且一般頁面可互動」為準，不承諾固定毫秒數。

- [ ] **Step 8: 手動驗證四種 Excel**

以 Excel 或 LibreOffice 開啟：

1. 中文 sheet/header 無亂碼。
2. 百分比、金額、基點與日期格式正確。
3. 凍結窗格、篩選、欄寬可讀。
4. 缺少 metadata 明確顯示 `N/A` 與缺失欄位清單。
5. 現有目標檔被占用時，顯示錯誤且不破壞舊檔。
6. 報告數值與 UI/DTO 一致，沒有 exporter 自行重算造成差異。

- [ ] **Step 9: 檢查工作區與提交範圍**

```powershell
git status --short
git diff --check
```

確認：

- 不包含 `.superpowers/`
- 不包含 shared state
- 不包含 tracked QA output
- 不包含 `.xlsx` 測試產物
- 不包含本任務以外的使用者變更

- [ ] **Step 10: Final commit**

只有仍有未提交的本任務修正時才執行：

```powershell
git add requirements.txt app_module/report_export_dtos.py app_module/report_export_service.py app_module/sqlite_inspector_service.py ui_qt/widgets/sqlite_inspector_widget.py ui_qt/views/backtest/result_panel.py ui_qt/views/backtest_view.py ui_qt/views/recommendation_view.py tests/test_report_export_dtos.py tests/test_report_export_service.py tests/test_sqlite_inspector_service.py tests/test_ui_qt_report_export.py tests/test_ui_qt_update_view_workbench.py docs/07_guides/APPLICATION_MANUAL.md docs/02_features/UI_FEATURES_DOCUMENTATION.md docs/02_features/BACKTEST_LAB_FEATURES.md docs/01_architecture/system_architecture.md PROJECT_NAVIGATION.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/00_core/LEGACY_ROADMAP_CARRYOVER.md docs/00_core/DOCUMENTATION_INDEX.md
git commit -m "test: verify phase 5 excel reporting workflow"
```

## 3. Definition of Done

- SQLite Inspector 使用資料庫分頁，不會一次載入完整大表。
- 所有 page query 具穩定排序，測試證明跨頁無重複與遺漏。
- 篩選後 count 與資料查詢使用同一契約。
- stale worker result 不會覆蓋最新 UI 查詢。
- 四種 Excel 報告均由明確 payload DTO 輸入。
- 報告不重新計算核心金融數值，缺失 metadata 明確標示。
- Excel 寫入在背景執行，使用暫存檔與原子替換。
- focused pytest、強制 UI pytest、QA script、完整 mypy、float gate、py_compile 全部通過。
- Manual、UI docs、Architecture、Navigation、Snapshot、6M Roadmap、Legacy Carryover 與 Index 已同步。
- PDF、Research Run Registry 與 Cross-run Comparison 仍明確保留為後續範圍。

## 4. 自我審查

### Spec coverage

- SQLite database-level pagination：Task 2-3。
- 單股、批次、推薦回放、目前推薦 Excel：Task 1、4-6。
- UI buttons：Task 5-6。
- 可追溯 metadata 與缺失標示：Task 1、4。
- 背景執行與原子寫入：Task 4-6。
- 測試與 repo 強制 QA：Task 8。
- 文件同步與 Scoped SSOT：Task 7。

### 明確不宣稱完成

- PDF 報告未包含於本計畫。
- Research Run Registry 未包含於本計畫。
- benchmark-relative attribution 未新增；只輸出既有結果。
- data version 缺失時不推測、不偽造。
