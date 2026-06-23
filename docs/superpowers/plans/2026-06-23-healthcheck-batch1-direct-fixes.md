# Healthcheck Batch 1 Direct Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the first executable batch of issues from `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`: `UPDATE-ISSUE-030`, `UPDATE-ISSUE-031`, `PORTFOLIO-ISSUE-001` through `PORTFOLIO-ISSUE-009`, `RUNTIME-ISSUE-001` through `RUNTIME-ISSUE-004`, and Research Lab Batch 1 UX readability items.

**Architecture:** Keep domain and calculation logic in service/domain layers. UI files render DTOs, labels, navigation state, and user guidance only. Do not modify raw CSV files or formal data roots. Any JSON serialization defense must preserve numeric precision with strings, integers, `Decimal`, or an explicit presentation boundary.

**Tech Stack:** Python 3.12, PySide6, pytest, mypy, JSONL storage, pandas table models, existing `TaskWorker` background worker pattern, repository documentation under `docs/`.

---

## Scope Boundary

This plan intentionally covers Batch 0 and Batch 1 only.

Implement in this plan:

- `UPDATE-ISSUE-030`: source-specific status check results are visible inside the relevant source page.
- `UPDATE-ISSUE-031`: force merge confirmation has explicit cancel and data safety copy.
- `PORTFOLIO-ISSUE-001` to `PORTFOLIO-ISSUE-009`: direct Portfolio UI, source-label, drill-down, and Decimal JSON defenses.
- `RUNTIME-ISSUE-001` to `RUNTIME-ISSUE-004`: Runtime Observatory scope, Chinese labels, warnings, and readable event stream.
- Research Lab Batch 1 UX readability: mode explanations, date calendar behavior, Registry refresh consistency, save/promote guidance, Excel missing-field Chinese explanations, and basic comparison localization.
- Healthcheck status updates and minimal Application Manual updates for visible UI behavior changes.

Do not implement in this plan:

- Daily Decision Dashboard v2: `DECISION-ISSUE-002`, `DECISION-ISSUE-003`, and dashboard-dependent pieces of `MARKET-ISSUE-006` / `MARKET-ISSUE-007`.
- Smart Money semantic service full 5 / 20 / 60 day layer, Top N concentration metrics, and look-ahead guarded high-position rules.
- Recommendation Profile / Regime profile lifecycle: `RECOMMEND-ISSUE-001`, `RECOMMEND-ISSUE-002`, `RECOMMEND-ISSUE-003`, `RECOMMEND-ISSUE-004`, `RECOMMEND-ISSUE-008`.
- Performance investigations: `UPDATE-ISSUE-013`, `UPDATE-ISSUE-014`, `MARKET-ISSUE-002`, `MARKET-ISSUE-003`, `BACKTEST-ISSUE-011`, `BACKTEST-ISSUE-012`, `BACKTEST-ISSUE-013`.

The out-of-scope items stay recorded in the healthcheck and the design spec as later batches.

---

## Current File Map

- `ui_qt/views/update_view.py`
  - Existing source-detail checks flow through `_check_source_detail()`, `_on_source_detail_checked()`, and `_on_status_checked()`.
  - Force merge currently uses a standard `QMessageBox.warning()` with `Yes` / `No`.

- `tests/test_ui_qt_update_view_workbench.py`
  - Existing UpdateView widget tests and fake update service live here.

- `ui_qt/views/portfolio_view.py`
  - `AddTradeDialog` owns manual trade inputs.
  - `PortfolioView._show_record_trade_dialog()` writes trades through `PortfolioService`.
  - `_update_monitoring_tab()` renders source, price, lifecycle, and chip-monitor UI.
  - `_on_drill_down_chip_clicked()` already searches parent widgets for `show_smart_money_flow_for_stock`.

- `app_module/portfolio_store.py`
  - `PortfolioJsonlStore` writes JSONL through direct `json.dumps()`, which currently fails on `Decimal`.

- `app_module/portfolio_chip_service.py`
  - Already exposes `lots_quality` on branch rows and aggregate counts such as observed / estimated / unavailable in summaries.
  - Batch 1 only renders available quality and source indicators. Full Top N concentration recalculation belongs to the Smart Money semantic batch.

- `ui_qt/views/runtime_view.py`
  - Pure render component for Runtime Observatory.
  - Several user-facing strings are still English, including `FSM State Machine`, `Objective`, `IDLE`, `Rejection Rate`, and raw event types.

- `ui_qt/views/backtest/config_panel.py`
  - Research Lab mode dropdown and `QDateEdit` inputs are already present.

- `ui_qt/views/backtest_view.py`
  - Save, promote, Registry compare, report export, and validation result rendering live here.

- `app_module/report_export_service.py`
  - Excel export service has safe value conversion and report writing helpers.

- `app_module/research_run_comparison_service.py`
  - Generates comparison summaries and difference reasons.

- `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`
  - Must be updated after implementation to mark Batch 1 fixed items as `已修正待驗證`, not `通過`.

- `docs/07_guides/APPLICATION_MANUAL.md`
  - Must receive minimal updates for visible UI behavior changes.

---

## Safety Rules

- [ ] Before editing implementation files, run `git status --short` and note that many files are already dirty. Do not revert, overwrite, or stage unrelated user changes.
- [ ] Do not edit `ui_qt/widgets/sqlite_inspector_widget.py` unless a Batch 1 task explicitly requires it. It was dirty before this work.
- [ ] Do not run data rebuilds, force merges, raw CSV cleanup, or commands that modify `D:/Min/Python/Project/FA_Data`.
- [ ] Do not add core financial calculations with naked `float`. UI display conversion is allowed only at a presentation boundary with a comment or obvious label.
- [ ] For any backtest, recommendation, or strategy-adjacent change, confirm that no code reads records after the decision date. Batch 1 should only change UI labels, report text, JSON serialization, and navigation.

---

## Implementation Tasks

### 1. Batch 0 Baseline and Issue Ledger Preflight

- [ ] Run a read-only status check:

```powershell
git status --short
git log --oneline --max-count=5
```

- [ ] Read the current issue rows and keep this list nearby:

```powershell
rg -n "UPDATE-ISSUE-030|UPDATE-ISSUE-031|PORTFOLIO-ISSUE-00[1-9]|RUNTIME-ISSUE-00[1-4]|BACKTEST-ISSUE-00[2-5]|BACKTEST-ISSUE-010|BACKTEST-ISSUE-014|BACKTEST-ISSUE-015|BACKTEST-ISSUE-019|BACKTEST-ISSUE-02[1-4]" docs\06_qa\FULL_APP_HEALTHCHECK_2026_06_16.md
```

- [ ] Run the existing focused tests once to capture baseline behavior. If failures are unrelated to Batch 1 edits, record them in the final handoff instead of fixing unrelated areas.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py tests/test_ui_qt_research_workflow.py tests/test_report_export_service.py tests/test_research_run_comparison_service.py tests/test_portfolio_chip_monitor.py tests/test_portfolio_numeric_governance.py -q -o addopts=
```

Expected result after Batch 1 implementation: all selected tests pass. If baseline already fails, the final result must identify the pre-existing failing test names.

### 2. UpdateView Source Status Visibility Tests

- [ ] In `tests/test_ui_qt_update_view_workbench.py`, add tests that fail before the implementation:

```python
def test_source_detail_check_renders_daily_status_inside_source_page(qt_app):
    view = UpdateView(config=FakeConfig(), update_service=FakeUpdateService())

    view._on_source_detail_checked({
        "source": "daily",
        "status": {
            "daily_data": {
                "latest_date": "2026-06-22",
                "total_records": 123456,
                "status": "ok",
                "csv_file_count": 2890,
                "missing_dates": ["2026-06-18"],
                "warnings": ["TWSE 休市日已略過"],
            }
        },
    })

    text = view.daily_detail_status_label.text()
    assert "最新日期：2026-06-22" in text
    assert "SQLite 筆數：123,456" in text
    assert "CSV 日檔數：2,890" in text
    assert "缺漏日期：2026-06-18" in text
```

```python
def test_source_detail_check_renders_broker_branch_status_inside_source_page(qt_app):
    view = UpdateView(config=FakeConfig(), update_service=FakeUpdateService())

    view._on_source_detail_checked({
        "source": "broker_branch",
        "status": {
            "broker_branch": {
                "latest_date": "2026-06-22",
                "total_records": 98765,
                "date_count": 120,
                "dual_count": 55,
                "e_only_count": 10,
                "b_only_count": 5,
                "status": "warning",
            }
        },
    })

    text = view.broker_branch_detail_status_label.text()
    assert "最新日期：2026-06-22" in text
    assert "SQLite 筆數：98,765" in text
    assert "實際天數：120" in text
    assert "雙榜紀錄：55" in text
```

- [ ] Use the exact attribute names `daily_detail_status_label` and `broker_branch_detail_status_label` in the implementation so tests and UI remain discoverable.

### 3. UpdateView Source Status Visibility Implementation

- [ ] In `ui_qt/views/update_view.py`, add a small status label or compact card inside the daily source page and broker branch source page near each `檢查此資料源狀態` button.

- [ ] Add helpers on `UpdateView`:

```python
def _format_source_detail_summary(self, source: str, detail: dict[str, Any]) -> str:
    latest_date = detail.get("latest_date") or "未知"
    total_records = int(detail.get("total_records") or 0)
    status_text = self._format_status_token(detail.get("status"))
    lines = [
        f"最新日期：{latest_date}",
        f"SQLite 筆數：{total_records:,}",
        f"狀態：{status_text}",
    ]
    if source == "daily":
        csv_count = detail.get("csv_file_count") or detail.get("file_count")
        if csv_count is not None:
            lines.append(f"CSV 日檔數：{int(csv_count):,}")
        missing_dates = detail.get("missing_dates") or []
        if missing_dates:
            lines.append("缺漏日期：" + "、".join(str(date) for date in missing_dates[:8]))
    if source == "broker_branch":
        lines.append(f"實際天數：{int(detail.get('date_count') or 0):,}")
        lines.append(f"雙榜紀錄：{int(detail.get('dual_count') or 0):,}")
        lines.append(f"張數榜專屬：{int(detail.get('e_only_count') or 0):,}")
        lines.append(f"金額榜專屬：{int(detail.get('b_only_count') or 0):,}")
    warnings = detail.get("warnings") or detail.get("quality_warnings") or []
    if warnings:
        lines.append("提醒：" + "；".join(str(item) for item in warnings[:3]))
    return "\n".join(lines)

def _format_status_token(self, status: Any) -> str:
    mapping = {
        "ok": "正常",
        "warning": "需注意",
        "error": "異常",
        "missing": "缺漏",
        "unknown": "未知",
    }
    return mapping.get(str(status).lower(), str(status or "未知"))
```

- [ ] In `_on_source_detail_checked()`, after `_on_status_checked(status)`, render the source-page label:

```python
def _on_source_detail_checked(self, payload: dict[str, Any]):
    source = payload.get("source")
    status = payload.get("status", {})
    if source:
        self._loaded_detail_sources.add(source)
    self._on_status_checked(status)
    self._render_source_detail_status(str(source or ""), status)
```

```python
def _render_source_detail_status(self, source: str, status: dict[str, Any]) -> None:
    source_to_key = {
        "daily": "daily_data",
        "broker_branch": "broker_branch",
    }
    source_to_label = {
        "daily": getattr(self, "daily_detail_status_label", None),
        "broker_branch": getattr(self, "broker_branch_detail_status_label", None),
    }
    key = source_to_key.get(source)
    label = source_to_label.get(source)
    if not key or label is None:
        return
    detail = status.get(key) or {}
    label.setText(self._format_source_detail_summary(source, detail))
```

- [ ] Keep the existing all-data status cards updated through `_on_status_checked()`. The new labels supplement the source page, not replace the existing cards.

### 4. UpdateView Force Merge Confirmation Tests

- [ ] In `tests/test_ui_qt_update_view_workbench.py`, add a test that intercepts the dialog instance and verifies explicit button text and raw CSV safety copy.

```python
def test_force_merge_confirmation_uses_explicit_buttons_and_raw_csv_safety_copy(qt_app, monkeypatch):
    view = UpdateView(config=FakeConfig(), update_service=FakeUpdateService())
    captured = {}

    class CapturingMessageBox(QMessageBox):
        def exec(self):
            captured["text"] = self.text()
            captured["informative"] = self.informativeText()
            captured["buttons"] = [button.text() for button in self.buttons()]
            self.setClickedButton(next(button for button in self.buttons() if "取消" in button.text()))
            return QMessageBox.Cancel

    monkeypatch.setattr("ui_qt.views.update_view.QMessageBox", CapturingMessageBox)

    view._execute_force_merge()

    assert "確認強制合併" in captured["buttons"]
    assert "取消" in captured["buttons"]
    assert "不會修改或刪除" in captured["informative"]
    assert "raw CSV 原始檔案" in captured["informative"]
    assert ("merge_daily_data", True) not in view.update_service.calls
```

- [ ] Add a second test where the confirm button is clicked and assert `_do_merge(force_all=True)` is invoked. Prefer monkeypatching `_do_merge` over running the worker.

### 5. UpdateView Force Merge Confirmation Implementation

- [ ] Replace the current `QMessageBox.warning()` path in `_execute_force_merge()` with an explicit `QMessageBox` instance:

```python
def _execute_force_merge(self):
    data_root = getattr(getattr(self, "config", None), "data_root", None) or "{DATA_ROOT}"
    msg_box = QMessageBox(self)
    msg_box.setIcon(QMessageBox.Warning)
    msg_box.setWindowTitle("確認強制合併")
    msg_box.setText("強制重新合併所有每日股價會重建 SQLite 匯入與索引。")
    msg_box.setInformativeText(
        "此操作會重新讀取 CSV 並重建每日股價相關 SQLite 資料，可能需要較長時間。"
        f"\n\n強制合併是針對 SQLite 資料庫重新進行 CSV 匯入與索引建立，"
        f"不應亦不會修改或刪除 {data_root} 底下的 raw CSV 原始檔案，以保障資料安全性。"
        "\n\n建議在執行前確認近期備份狀態；若只是測試取消流程，請按「取消」。"
    )
    cancel_button = msg_box.addButton("取消", QMessageBox.RejectRole)
    confirm_button = msg_box.addButton("確認強制合併", QMessageBox.DestructiveRole)
    msg_box.setDefaultButton(cancel_button)
    msg_box.exec()
    if msg_box.clickedButton() is not confirm_button:
        return
    self._do_merge(force_all=True)
```

- [ ] Ensure no code path touches raw CSV files directly in this method.

### 6. Portfolio Manual Trade Dialog Tests

- [ ] Add a focused UI test file if none exists: `tests/test_ui_qt_portfolio_view.py`.

- [ ] Create a fake recommendation service with `industry_mapper.get_stock_name(code)` returning a known stock name and `None` for unknown codes.

- [ ] Add failing tests for `PORTFOLIO-ISSUE-001`:

```python
def test_add_trade_dialog_autofills_stock_name_and_rejects_unknown_code(qt_app):
    dialog = AddTradeDialog(recommendation_service=FakeRecommendationService())

    dialog.code_input.setText("2330")
    assert dialog.name_input.text() == "台積電"
    assert dialog.code_error_label.text() == ""

    dialog.code_input.setText("999999")
    assert "找不到正式股票代號" in dialog.code_error_label.text()
```

```python
def test_add_trade_dialog_prefills_taiwan_fee_and_sell_tax(qt_app):
    dialog = AddTradeDialog(recommendation_service=FakeRecommendationService())

    dialog.qty_input.setValue(1000)
    dialog.price_input.setValue(100)
    dialog.side_combo.setCurrentIndex(dialog.side_combo.findData("buy"))
    assert dialog.fees_input.value() == 143
    assert dialog.taxes_input.value() == 0

    dialog.side_combo.setCurrentIndex(dialog.side_combo.findData("sell"))
    assert dialog.fees_input.value() == 143
    assert dialog.taxes_input.value() == 300
```

- [ ] The fee expectation uses a presentation rounded integer value: `1000 * 100 * 0.001425 = 142.5`, rounded half up to `143`.

### 7. Portfolio Manual Trade Dialog Implementation

- [ ] In `ui_qt/views/portfolio_view.py`, import `Decimal` and `ROUND_HALF_UP`.

- [ ] Add a visible error label under stock code or name:

```python
self.code_error_label = QLabel("")
self.code_error_label.setStyleSheet("color: #c53030;")
self.code_error_label.setWordWrap(True)
form_layout.addRow("", self.code_error_label)
```

- [ ] Add fee/tax recalculation hooks after `qty_input`, `price_input`, and `side_combo` are created:

```python
self._fees_manually_edited = False
self._taxes_manually_edited = False
self.qty_input.valueChanged.connect(self._refresh_default_costs)
self.price_input.valueChanged.connect(self._refresh_default_costs)
self.side_combo.currentIndexChanged.connect(self._refresh_default_costs)
self.fees_input.valueChanged.connect(lambda _value: setattr(self, "_fees_manually_edited", True))
self.taxes_input.valueChanged.connect(lambda _value: setattr(self, "_taxes_manually_edited", True))
self._refresh_default_costs()
```

- [ ] Add helper methods:

```python
def _money_to_spin_value(self, value: Decimal) -> float:
    rounded = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(rounded)

def _refresh_default_costs(self) -> None:
    notional = Decimal(str(self.qty_input.value())) * Decimal(str(self.price_input.value()))
    fee = notional * Decimal("0.001425")
    tax = notional * Decimal("0.003") if self.side_combo.currentData() == "sell" else Decimal("0")
    if not self._fees_manually_edited:
        self.fees_input.blockSignals(True)
        self.fees_input.setValue(self._money_to_spin_value(fee))
        self.fees_input.blockSignals(False)
    if not self._taxes_manually_edited:
        self.taxes_input.blockSignals(True)
        self.taxes_input.setValue(self._money_to_spin_value(tax))
        self.taxes_input.blockSignals(False)
```

- [ ] In `_auto_query_stock_name()`, clear the error label when a formal name is found. If code length is at least 4 and no name is found, set `找不到正式股票代號，請確認代號或手動補入名稱。`

- [ ] In `_validate_and_accept()`, block accept when `code_error_label` contains the unknown-code message and `name_input` is empty.

- [ ] Keep `QDoubleSpinBox` values at the UI boundary. Convert to existing service input types at `get_trade_data()`.

### 8. Portfolio Summary, Filter, Price, Source, Chip, and Drill-Down Tests

- [ ] In `tests/test_ui_qt_portfolio_view.py`, add tests for the user-visible Portfolio issues:

```python
def test_portfolio_active_summary_lists_position_count_and_top_symbols(qt_app):
    view = PortfolioView(config=FakeConfig(), portfolio_service=FakePortfolioService())

    view.refresh_all()

    assert "活躍持倉：2 檔" in view.active_positions_summary_label.text()
    assert "2330 台積電" in view.active_positions_summary_label.text()
```

```python
def test_trade_history_filter_label_and_clear_button(qt_app):
    view = PortfolioView(config=FakeConfig(), portfolio_service=FakePortfolioService())

    view.selected_stock_code = "2330"
    view._load_trades_history()
    assert "目前只顯示：2330" in view.trade_filter_status_label.text()

    view.clear_trade_filter_button.click()
    assert view.selected_stock_code == ""
    assert "顯示全部交易歷史" in view.trade_filter_status_label.text()
```

```python
def test_portfolio_monitoring_shows_price_as_of_and_manual_source_label(qt_app):
    view = PortfolioView(config=FakeConfig(), portfolio_service=FakePortfolioService())
    view.selected_stock_code = "2330"

    view._update_monitoring_tab()

    assert "價格日期" in view.lbl_mon_current_price.text()
    assert "手動建立，無推薦 / 回測來源" in view.lbl_strat_id.text()
```

```python
def test_chip_monitor_renders_chinese_risk_and_quality_tooltip(qt_app):
    view = PortfolioView(config=FakeConfig(), portfolio_service=FakePortfolioService())
    view.selected_stock_code = "2330"

    view._update_monitoring_tab()

    assert view.lbl_chip_risk_level.text() in {"偏多", "中性", "偏空", "低", "中", "高"}
    assert "observed" in view.lbl_chip_concentration.toolTip()
    assert "張數" in view.lbl_chip_concentration.toolTip()
```

```python
def test_chip_drill_down_passes_selected_stock_to_parent(qt_app):
    parent = FakeMainWindowWithSmartMoneyNavigation()
    view = PortfolioView(config=FakeConfig(), portfolio_service=FakePortfolioService(), parent=parent)
    view.selected_stock_code = "2330"

    view._on_drill_down_chip_clicked()

    assert parent.smart_money_stock_code == "2330"
```

- [ ] Keep fake services small and explicit. Use only DTO fields the existing `PortfolioView` reads.

### 9. Portfolio Summary, Filter, Price, Source, Chip, and Drill-Down Implementation

- [ ] In `ui_qt/views/portfolio_view.py`, add `active_positions_summary_label` to the top summary area. It should show:

```text
活躍持倉：{count} 檔｜{code1} {name1}、{code2} {name2}、{code3} {name3}
```

- [ ] Update this label from the same list used by positions table refresh. If there are no positions, show `活躍持倉：0 檔｜目前沒有持倉`.

- [ ] Add `trade_filter_status_label` and `clear_trade_filter_button` near the transaction history table. The button text must be `顯示全部交易歷史`. It should set `selected_stock_code = ""`, reload trades and journal entries, and update the label.

- [ ] In the monitoring tab, render current price with date and quality:

```text
{price}（價格日期：{as_of_date}；來源：{quality_label}）
```

If the DTO does not expose a date, show `價格日期：未知` and add a tooltip that the latest available price source did not provide an as-of date.

- [ ] Change manual source display from `未知` to:

```text
手動建立，無推薦 / 回測來源
```

The source ID can remain in a secondary line or tooltip if present.

- [ ] Map chip risk labels in UI:

```python
CHIP_RISK_LABELS = {
    "bullish": "偏多",
    "neutral": "中性",
    "bearish": "偏空",
    "low": "低",
    "medium": "中",
    "high": "高",
}
```

- [ ] Keep raw keys in tooltips:

```python
raw_risk = str(chip_summary.get("risk_level", "neutral"))
self.lbl_chip_risk_level.setText(CHIP_RISK_LABELS.get(raw_risk, raw_risk))
self.lbl_chip_risk_level.setToolTip(f"raw risk_level: {raw_risk}")
```

- [ ] Add concentration tooltip with quantity and quality contract:

```python
quality = chip_summary.get("quality_counts") or {}
tooltip = (
    "集中度以張數 / 股數等價 quantity 計算；不直接使用千元金額。"
    f"\nobserved: {quality.get('observed', 0)}"
    f"\nestimated: {quality.get('estimated', 0)}"
    f"\nunavailable: {quality.get('unavailable', 0)}"
)
self.lbl_chip_concentration.setToolTip(tooltip)
```

- [ ] If `concentration_status == "unavailable"` or usable row count is 0, show `資料不足` instead of `0.00%`.

- [ ] Preserve the existing parent search in `_on_drill_down_chip_clicked()`. If `show_smart_money_flow_for_stock` exists, pass `self.selected_stock_code` exactly. Do not introduce direct dependency from PortfolioView to Market Watch internals.

### 10. Portfolio Decimal JSON Serialization Tests

- [ ] Add `tests/test_portfolio_jsonl_store_serialization.py`.

- [ ] Add tests that fail before the implementation:

```python
from decimal import Decimal
from app_module.portfolio_store import PortfolioJsonlStore


def test_portfolio_jsonl_store_serializes_decimal_without_float(tmp_path):
    store = PortfolioJsonlStore(tmp_path)

    store.append_trade({
        "stock_code": "2330",
        "quantity": Decimal("1000"),
        "price": Decimal("123.45"),
        "metadata": {
            "score": Decimal("0.12345678901234567890"),
            "weights": [Decimal("1.25")],
        },
    })

    raw = store.trades_file.read_text(encoding="utf-8")
    assert '"0.12345678901234567890"' in raw
    assert "0.12345678901234568" not in raw

    loaded = store.load_trades()[0]
    assert loaded["metadata"]["score"] == "0.12345678901234567890"
```

```python
def test_portfolio_jsonl_store_overwrite_serializes_nested_decimals(tmp_path):
    store = PortfolioJsonlStore(tmp_path)

    store.overwrite_trades([
        {"stock_code": "2330", "source_summary": {"total_score": Decimal("88.0001")}},
    ])

    assert '"88.0001"' in store.trades_file.read_text(encoding="utf-8")
```

- [ ] The test expects `Decimal` values to serialize as strings, because Portfolio JSONL is a persistence boundary and should not introduce binary float precision drift.

### 11. Portfolio Decimal JSON Serialization Implementation

- [ ] In `app_module/portfolio_store.py`, add a small recursive sanitizer:

```python
from decimal import Decimal


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value
```

- [ ] Use this sanitizer in `_append_jsonl()`, `overwrite_trades()`, and `overwrite_journal_entries()`:

```python
handle.write(json.dumps(_json_safe(item), ensure_ascii=False, sort_keys=True))
```

- [ ] Do not alter `load_trades()` to parse strings back to `Decimal` in Batch 1. Existing domain constructors already validate their own numeric inputs. The Batch 1 defect is write failure and precision drift prevention.

### 12. Runtime Observatory Tests

- [ ] Add `tests/test_ui_qt_runtime_view.py`.

- [ ] Add tests for `RUNTIME-ISSUE-001` through `RUNTIME-ISSUE-004`:

```python
def test_runtime_view_static_labels_are_chinese_and_scope_is_explicit(qt_app):
    view = RuntimeView()

    assert "任務狀態機" in view.state_group.title()
    assert "Runtime Observatory 不監控資料更新背景任務" in view.scope_label.text()
    assert "資料更新、回測與推薦長任務" in view.scope_label.text()
```

```python
def test_runtime_state_snapshot_renders_chinese_idle_text(qt_app):
    view = RuntimeView()
    dto = RuntimeStateSnapshotDTO(
        task_objective="No task assigned",
        task_status="IDLE",
        active_context_files=[],
    )

    view.on_state_updated(dto)

    assert "目前治理目標：尚未指派治理任務" in view.objective_label.text()
    assert "任務流程狀態：閒置" in view.status_label.text()
```

```python
def test_runtime_health_halted_uses_red_warning_and_chinese_labels(qt_app):
    view = RuntimeView()
    dto = make_runtime_health_dto(state="HALTED", rejection_rate=0.8, consecutive_failures=4)

    view.on_health_updated(dto)

    assert "治理暫停" in view.health_state_label.text()
    assert "驗證拒絕率：80.0%" in view.rejection_rate_label.text()
    assert "連續失敗次數：4" in view.rejection_rate_label.text()
    assert "不代表主 App 一般功能失敗" in view.health_scope_note_label.text()
```

```python
def test_runtime_event_stream_shows_chinese_summary_and_raw_tooltip(qt_app):
    view = RuntimeView()
    dto = make_runtime_event_dto(event_type="validation_rejected", message="JSONDecodeError")

    view.on_event_received(dto)

    item = view.event_list.item(0)
    assert "驗證拒絕" in item.text()
    assert "JSON 格式錯誤" in item.text()
    assert "validation_rejected" in item.toolTip()
```

- [ ] Build `make_runtime_health_dto()` and `make_runtime_event_dto()` from the actual DTO signatures in `app_module/dtos/runtime_dtos.py`.

### 13. Runtime Observatory Implementation

- [ ] In `ui_qt/views/runtime_view.py`, store the group boxes as attributes:

```python
self.state_group = QGroupBox("任務狀態機")
self.context_group = QGroupBox("Runtime Context 環境")
self.health_group = QGroupBox("治理健康狀態")
self.events_group = QGroupBox("事件流")
```

- [ ] Add a scope label below the title:

```python
self.scope_label = QLabel(
    "Runtime Observatory 不監控資料更新背景任務；資料更新、回測與推薦長任務仍由各自頁面顯示狀態。"
)
self.scope_label.setWordWrap(True)
main_layout.addWidget(self.scope_label)
```

- [ ] Add a warning scope note in the health group:

```python
self.health_scope_note_label = QLabel("治理暫停或拒絕率升高只代表 agent / governance workflow 狀態，不代表主 App 一般功能失敗。")
self.health_scope_note_label.setWordWrap(True)
health_layout.addWidget(self.health_scope_note_label)
```

- [ ] Add mapping helpers:

```python
STATE_LABELS = {
    "IDLE": "閒置",
    "RUNNING": "執行中",
    "ERROR": "錯誤",
    "HALTED": "治理暫停",
}

EVENT_LABELS = {
    "test_start": "測試開始",
    "agent_output_received": "收到 agent 輸出",
    "validation_passed": "驗證通過",
    "validation_rejected": "驗證拒絕",
}

ERROR_LABELS = {
    "JSONDecodeError": "JSON 格式錯誤",
    "SchemaViolation": "Schema 違規",
    "GovernanceViolation": "治理規則違反",
}
```

- [ ] Render state snapshot:

```python
objective = dto.task_objective
if not objective or objective == "No task assigned":
    objective = "尚未指派治理任務"
status = STATE_LABELS.get(str(dto.task_status), str(dto.task_status))
self.objective_label.setText(f"目前治理目標：{objective}")
self.status_label.setText(f"任務流程狀態：{status}")
```

- [ ] Render health snapshot with red warning for `ERROR`, `HALTED`, rejection rate >= `0.5`, or consecutive failures >= `3`.

- [ ] Render event stream with Chinese summary as item text and raw details in tooltip:

```python
raw_type = str(dto.event_type)
event_label = EVENT_LABELS.get(raw_type, raw_type)
message = str(dto.human_readable_message or "")
for raw, label in ERROR_LABELS.items():
    message = message.replace(raw, label)
item_text = f"[{time_str}] {severity_label}｜{dto.actor}｜{event_label}：{message}"
item = QListWidgetItem(item_text)
item.setToolTip(f"raw event_type: {raw_type}\npayload: {getattr(dto, 'payload', {})}\nmessage: {dto.human_readable_message}")
self.event_list.addItem(item)
```

### 14. Research Lab Batch 1 Tests

- [ ] Update existing Research tests instead of creating scattered new files unless a focused service test is cleaner.

- [ ] In `tests/test_ui_qt_research_workflow.py`, add or update tests for:

```python
def test_research_lab_mode_hint_explains_batch_fixed_replay_and_strategy_modes(qt_app):
    view = BacktestView(config=FakeConfig())

    labels = [view.research_lab_mode_combo.itemText(i) for i in range(view.research_lab_mode_combo.count())]
    assert "批次股票回測" in labels

    for index in range(view.research_lab_mode_combo.count()):
        view.research_lab_mode_combo.setCurrentIndex(index)
        hint = view.research_lab_mode_hint.text()
        assert "適合" in hint
        assert "輸入來源" in hint
```

```python
def test_research_lab_date_edits_use_calendar_popup_and_expected_defaults(qt_app):
    view = BacktestView(config=FakeConfig())

    assert view.start_date.calendarPopup()
    assert view.end_date.calendarPopup()
    assert view.end_date.date() == QDate.currentDate()
    assert view.start_date.date().daysTo(QDate.currentDate()) in range(360, 371)
```

```python
def test_research_registry_refreshes_after_save_delete_and_promote(qt_app, monkeypatch):
    view = BacktestView(config=FakeConfig())
    calls = []
    monkeypatch.setattr(view, "_refresh_research_registry", lambda: calls.append("refresh"))

    view._on_research_run_saved("run-1")
    view._on_research_run_deleted("run-1")
    view._on_strategy_version_promoted("version-1")

    assert calls == ["refresh", "refresh", "refresh"]
```

Use actual method names if the existing implementation has different hooks; if no hooks exist, add small hooks and call them from save/delete/promote success paths.

- [ ] In `tests/test_report_export_service.py`, add a test that missing metadata fields render Chinese diagnostics in the summary sheet.

- [ ] In `tests/test_research_run_comparison_service.py`, add tests that comparison reasons are localized, for example `sizing mode differs` becomes `部位 sizing 模式不同`.

### 15. Research Lab Batch 1 Implementation

- [ ] In `ui_qt/views/backtest/config_panel.py`, keep the current mode hint label and strengthen `_research_lab_mode_hint_text()` so each mode contains:
  - What it is for.
  - Expected input source.
  - Output interpretation.

Example labels:

```python
MODE_HINTS = {
    "single_stock": "適合檢查單一股票策略假設；輸入來源為單一股票代號與日期區間；結果用來看該股票在此策略下的交易紀錄與風險。",
    "batch_stock": "適合比較多檔股票同一策略；輸入來源為選股清單或手動代號；結果用來排序候選股與檢查樣本差異。",
    "fixed_portfolio": "適合固定股票組合的研究；輸入來源為一組固定股票；結果用來觀察組合層級報酬、回撤與持倉限制。",
    "recommendation_replay": "適合檢查推薦系統歷史回放；輸入來源為推薦分析送入的候選池；結果用來評估推薦排序與交易假設。",
    "strategy_research": "適合研究策略參數與驗證流程；輸入來源為策略、日期與參數；結果用來保存 Research Run 或升級策略版本。",
}
```

- [ ] Ensure `start_date` and `end_date` both call `setCalendarPopup(True)`. Set defaults to one year ago and current date, using `QDate.currentDate().addYears(-1)` and `QDate.currentDate()`.

- [ ] In `ui_qt/views/backtest_view.py`, add small hooks if they do not already exist:

```python
def _on_research_run_saved(self, run_id: str) -> None:
    self._refresh_research_registry()
    self.progress_label.setText(f"已保存 Research Run：{run_id}。下一步可在 Registry 比較，或升級為策略版本。")

def _on_research_run_deleted(self, run_id: str) -> None:
    self._refresh_research_registry()
    self.progress_label.setText(f"已刪除 Research Run：{run_id}，Registry 已更新。")

def _on_strategy_version_promoted(self, version_id: str) -> None:
    self._refresh_research_registry()
    self.progress_label.setText(f"已升級策略版本：{version_id}。下一步可到推薦分析啟用策略版本 Profile。")
```

- [ ] Call those hooks from the existing save/delete/promote success paths.

- [ ] In `app_module/report_export_service.py`, add a mapping for missing fields in the exported diagnostic section:

```python
FIELD_LABELS = {
    "run_id": "執行 ID",
    "run_name": "執行名稱",
    "strategy_id": "策略 ID",
    "start_date": "開始日期",
    "end_date": "結束日期",
    "validation_status": "驗證狀態",
}
```

When metadata is missing, write a Chinese row such as `缺少欄位：開始日期（start_date）` instead of only the raw key.

- [ ] In `app_module/research_run_comparison_service.py`, localize comparison reason strings:

```python
REASON_LABELS = {
    "sizing mode differs": "部位 sizing 模式不同",
    "cost model differs": "交易成本模型不同",
    "strategy differs": "策略不同",
    "date range differs": "日期區間不同",
}
```

Keep the raw reason in a `raw_reason` field if the DTO already supports metadata. If it does not, append raw reason in parentheses only when useful for debugging.

### 16. Portfolio / Research Lab Source Semantics

- [ ] For `PORTFOLIO-ISSUE-009`, inspect existing Research Lab actions that record trades into Portfolio:

```powershell
rg -n "record_trade|PortfolioService|source_type|source_summary|recommendation_result|backtest_run" ui_qt\views\backtest_view.py ui_qt\views\recommendation_view.py app_module portfolio_module
```

- [ ] Define and enforce this source support in UI text:
  - Single-stock backtest trade rows may record to Portfolio with `source_type="backtest_run"`.
  - Recommendation replay trade rows may record to Portfolio with `source_type="recommendation_result"` or the existing equivalent.
  - Batch leaderboard rows do not directly represent one concrete trade ledger. If an entry point exists there, disable it or label it as `先開啟該 run 的交易紀錄後再記錄持倉`.

- [ ] Add a test in `tests/test_ui_qt_research_workflow.py` that a batch leaderboard row does not expose a misleading direct `記錄持倉` action, while trade rows keep the action.

- [ ] Keep healthcheck wording aligned with the final behavior.

### 17. Documentation Updates

- [ ] Update `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`:
  - Mark `UPDATE-ISSUE-030` and `UPDATE-ISSUE-031` as `已修正待驗證`.
  - Mark `PORTFOLIO-ISSUE-001` through `PORTFOLIO-ISSUE-009` as `已修正待驗證`.
  - Mark `RUNTIME-ISSUE-001` through `RUNTIME-ISSUE-004` as `已修正待驗證`.
  - For Research Lab Batch 1 issue rows, mark only the directly implemented readability pieces as `已修正待驗證`; keep result-page redesign, performance, cancellation, and validation metric diagnosis in later batches.
  - Do not mark any item as `通過` unless the user manually verifies it.

- [ ] In the healthcheck, keep later-batch items explicit:
  - Daily Dashboard and Smart Money semantic layer remain planned under Batch 2.
  - Recommendation Profile remains planned under Batch 3.
  - Research Lab result-page redesign remains planned under Batch 4.
  - Performance and SQLite writer investigations remain planned under Batch 5.

- [ ] Update `docs/07_guides/APPLICATION_MANUAL.md` minimally:
  - Data Update: source-page status summary and force merge safety/cancel behavior.
  - Portfolio: manual trade stock lookup, default Taiwan fee/tax values, trade filter clear button, price as-of display, manual source label, chip risk labels, and drill-down behavior.
  - Runtime Observatory: it monitors governance/runtime workflows, not data update/backtest/recommendation background tasks.
  - Research Lab: mode hint, date calendar behavior, Registry refresh after save/delete/promote, and Excel missing-field diagnostics.

### 18. Verification

- [ ] Run focused tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py tests/test_ui_qt_portfolio_view.py tests/test_portfolio_jsonl_store_serialization.py tests/test_ui_qt_runtime_view.py tests/test_ui_qt_research_workflow.py tests/test_report_export_service.py tests/test_research_run_comparison_service.py -q -o addopts=
```

- [ ] Run required UI verification from `AGENTS.md`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

- [ ] Run syntax checks on changed Python files. Replace the file list with the actual changed Python files:

```powershell
.\.venv\Scripts\python.exe -m py_compile ui_qt\views\update_view.py ui_qt\views\portfolio_view.py ui_qt\views\runtime_view.py ui_qt\views\backtest\config_panel.py ui_qt\views\backtest_view.py app_module\portfolio_store.py app_module\report_export_service.py app_module\research_run_comparison_service.py tests\test_ui_qt_update_view_workbench.py tests\test_ui_qt_portfolio_view.py tests\test_portfolio_jsonl_store_serialization.py tests\test_ui_qt_runtime_view.py tests\test_ui_qt_research_workflow.py tests\test_report_export_service.py tests\test_research_run_comparison_service.py
```

- [ ] If `qa_validate_update_tab.py` performs UI-level checks only, it is safe to run. Do not trigger force merge or data rebuild operations during manual verification.

### 19. Final Git Hygiene

- [ ] Review changed files:

```powershell
git diff --stat
git diff -- docs\06_qa\FULL_APP_HEALTHCHECK_2026_06_16.md docs\07_guides\APPLICATION_MANUAL.md
```

- [ ] Stage only files changed for Batch 1. Do not stage unrelated dirty files that existed before implementation.

- [ ] Confirm staged file list:

```powershell
git diff --cached --name-only
```

Expected staged implementation files:

```text
ui_qt/views/update_view.py
tests/test_ui_qt_update_view_workbench.py
ui_qt/views/portfolio_view.py
app_module/portfolio_store.py
tests/test_ui_qt_portfolio_view.py
tests/test_portfolio_jsonl_store_serialization.py
ui_qt/views/runtime_view.py
tests/test_ui_qt_runtime_view.py
ui_qt/views/backtest/config_panel.py
ui_qt/views/backtest_view.py
app_module/report_export_service.py
app_module/research_run_comparison_service.py
tests/test_ui_qt_research_workflow.py
tests/test_report_export_service.py
tests/test_research_run_comparison_service.py
docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md
docs/07_guides/APPLICATION_MANUAL.md
```

- [ ] Commit after tests pass:

```powershell
git commit -m "fix: resolve healthcheck batch 1 direct issues"
```

---

## Later Batch Notes

The following design commitments are already captured in `docs/superpowers/specs/2026-06-23-healthcheck-issue-resolution-design.md` and should be converted into separate implementation plans:

- Batch 2 Daily Dashboard / Smart Money:
  - Market-first, sector-first answer dashboard.
  - Smart Money 5 / 20 / 60 day semantic states.
  - Top N concentration uses quantity, not thousand-dollar amount.
  - Observed / estimated / unavailable quality contract.
  - Look-ahead self-check for 60-day price percentile and 60-day high relative to `decision_date` or T-1.
  - UI renders DTOs only; `DecisionDeskService`, `BrokerFlowService`, or `SmartMoneyService` own classification.

- Batch 3 Recommendation Profile / Regime:
  - Built-in, custom, and strategy-version profiles in one dropdown.
  - Custom profiles marked as unverified.
  - JSON serialization defense for thresholds, weights, percentile parameters, and other quantitative settings.
  - Regime mismatch explains score impact but does not exclude candidates.

- Batch 5 Performance / SQLite writer investigation:
  - Broker branch controlled concurrency needs rate-limit and retry investigation.
  - Technical indicator multi-core may parallelize CPU-bound calculation only.
  - SQLite writes must return to the main thread or a single writer process to avoid `database is locked`.
