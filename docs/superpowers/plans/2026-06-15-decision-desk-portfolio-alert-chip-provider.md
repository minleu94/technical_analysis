# Daily Decision Desk Portfolio Alert Chip Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect Daily Decision Desk Portfolio Alert to the real `PortfolioChipService`, and surface chip data quality gaps through `quality / warnings`.

**Architecture:** Keep `DecisionDeskSnapshotBuilder` as the aggregation boundary. `ui_qt/main.py` will instantiate `PortfolioChipService` and inject it into `PortfolioAlertService`; `PortfolioAlertService` will remain the single place that interprets position condition status plus chip summary risk/quality. The UI will continue to display only `PortfolioAlertSummary`, without recomputing broker flow or portfolio logic.

**Tech Stack:** Python, PySide6, pytest, Decimal-based portfolio/chip services, SQLite/CSV fallback through existing services.

---

## File Structure

- Modify: `app_module/portfolio_alert_service.py`
  - Interpret `PortfolioChipService.get_stock_chip_summary()` quality fields.
  - Emit warnings for missing, estimated, unavailable, or invalid chip summaries.
  - Preserve existing alert ordering and severity semantics.
- Modify: `ui_qt/main.py`
  - Import `PortfolioChipService`.
  - Instantiate `PortfolioChipService(self.config, self.broker_flow_service)` for Daily Decision Desk Portfolio Alert injection.
  - Fail gracefully if chip provider initialization fails.
- Modify: `tests/test_portfolio_alert_service.py`
  - Add focused regression tests for chip quality warnings and bearish chip risk.
- Modify: `tests/test_ui_qt_decision_desk_main_integration.py`
  - Verify `MainWindow._create_decision_desk_builder()` injects a real chip provider object into `PortfolioAlertService`.
- Modify if behavior wording changes: `docs/07_guides/APPLICATION_MANUAL.md`, `docs/00_core/PROJECT_SNAPSHOT.md`, `docs/00_core/ROADMAP_6M_ENGINEERING.md`, `docs/01_architecture/system_architecture.md`
  - Only update if implementation changes user-visible Portfolio Alert status from “逐步補齊” to “chip provider 已接線”.

---

### Task 1: Portfolio Alert Interprets Chip Summary Quality

**Files:**
- Modify: `app_module/portfolio_alert_service.py`
- Test: `tests/test_portfolio_alert_service.py`

- [ ] **Step 1: Write the failing test for bearish chip risk and estimated chip quality**

Append this test to `tests/test_portfolio_alert_service.py`:

```python
def test_portfolio_alert_service_marks_estimated_when_chip_summary_has_estimated_lots():
    positions = [
        make_position("2330", "manual", ""),
    ]
    chip_provider = FakeChipSummaryProvider(
        {
            "2330": {
                "risk_level": "bearish",
                "lots_available": True,
                "has_estimated_lots": True,
                "observed_event_count": 1,
                "estimated_event_count": 2,
                "unavailable_event_count": 0,
                "risk_reasons": ["估計股數資料"],
            }
        }
    )
    service = PortfolioAlertService(
        FakePortfolioService(positions),
        FakeConditionMonitor({"2330": "valid"}),
        chip_provider,
    )

    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.ESTIMATED
    assert snapshot.alert_count == 1
    assert snapshot.alert_codes == ("2330",)
    assert snapshot.alert_level == "high"
    assert "portfolio_alerts_chip_estimated:2330" in snapshot.warnings
```

- [ ] **Step 2: Write the failing test for missing chip lots**

Append this test to `tests/test_portfolio_alert_service.py`:

```python
def test_portfolio_alert_service_warns_when_chip_lots_are_missing():
    positions = [
        make_position("1101", "manual", ""),
    ]
    chip_provider = FakeChipSummaryProvider(
        {
            "1101": {
                "risk_level": "neutral",
                "lots_available": False,
                "has_estimated_lots": False,
                "observed_event_count": 0,
                "estimated_event_count": 0,
                "unavailable_event_count": 3,
                "risk_reasons": ["無主力分點交易數據"],
            }
        }
    )
    service = PortfolioAlertService(
        FakePortfolioService(positions),
        FakeConditionMonitor({"1101": "valid"}),
        chip_provider,
    )

    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.ESTIMATED
    assert snapshot.alert_count == 0
    assert snapshot.alert_codes == ()
    assert snapshot.alert_level == "low"
    assert "portfolio_alerts_chip_data_missing:1101" in snapshot.warnings
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_alert_service.py::test_portfolio_alert_service_marks_estimated_when_chip_summary_has_estimated_lots tests\test_portfolio_alert_service.py::test_portfolio_alert_service_warns_when_chip_lots_are_missing -q
```

Expected: both tests fail because current service does not emit `portfolio_alerts_chip_estimated:*` or `portfolio_alerts_chip_data_missing:*`.

- [ ] **Step 4: Add chip summary quality warnings**

Modify `app_module/portfolio_alert_service.py`.

Replace `_chip_risk_severity` with this implementation:

```python
    def _chip_risk_severity(self, stock_code: str, warnings: list[str]) -> int:
        provider = self.chip_summary_provider
        if provider is None:
            return 0
        try:
            summary = provider.get_stock_chip_summary(stock_code, period_days=self.chip_lookback_days)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"portfolio_alerts_chip_provider_error:{stock_code}:{exc}")
            return 1

        if not isinstance(summary, Mapping):
            warnings.append(f"portfolio_alerts_chip_summary_invalid:{stock_code}")
            return 0

        lots_available = bool(summary.get("lots_available", True))
        has_estimated_lots = bool(summary.get("has_estimated_lots", False))
        unavailable_count = self._read_non_negative_int(summary.get("unavailable_event_count"))
        estimated_count = self._read_non_negative_int(summary.get("estimated_event_count"))

        if not lots_available:
            warnings.append(f"portfolio_alerts_chip_data_missing:{stock_code}")
        if has_estimated_lots or estimated_count > 0:
            warnings.append(f"portfolio_alerts_chip_estimated:{stock_code}")
        if unavailable_count > 0:
            warnings.append(f"portfolio_alerts_chip_unavailable_events:{stock_code}:{unavailable_count}")

        risk_level = str(summary.get("risk_level", "")).lower().strip()
        if risk_level in {"bearish", "extreme", "risk"}:
            return 80
        return 0
```

Add this helper below `_chip_risk_severity`:

```python
    def _read_non_negative_int(self, value: Any) -> int:
        if isinstance(value, bool) or value is None:
            return 0
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return parsed if parsed > 0 else 0
```

- [ ] **Step 5: Run focused service tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_alert_service.py -q
```

Expected: all portfolio alert service tests pass.

- [ ] **Step 6: Commit Task 1**

```powershell
git add app_module\portfolio_alert_service.py tests\test_portfolio_alert_service.py
git commit -m "fix: surface portfolio alert chip data quality"
```

---

### Task 2: Inject PortfolioChipService into Daily Decision Desk

**Files:**
- Modify: `ui_qt/main.py`
- Test: `tests/test_ui_qt_decision_desk_main_integration.py`

- [ ] **Step 1: Write the failing UI integration test**

Append this test to `tests/test_ui_qt_decision_desk_main_integration.py`:

```python
class _FakePortfolioChipService:
    instances = []

    def __init__(self, config, broker_flow_service=None):
        self.config = config
        self.broker_flow_service = broker_flow_service
        _FakePortfolioChipService.instances.append(self)

    def get_stock_chip_summary(self, stock_code: str, period_days: int = 5):
        return {"risk_level": "neutral", "lots_available": True}


def test_portfolio_alert_service_receives_portfolio_chip_provider(monkeypatch):
    app()
    _TrackingDecisionDeskBuilder.instances = []
    _FakePortfolioChipService.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)
    monkeypatch.setattr(main_module, "PortfolioChipService", _FakePortfolioChipService)

    target_window = _build_main_window()
    target_window.config = types.SimpleNamespace(db_file="C:/tmp/not-used.db")
    target_window._setup_ui()

    assert _TrackingDecisionDeskBuilder.instances
    assert _FakePortfolioChipService.instances
    portfolio_alert_service = _TrackingDecisionDeskBuilder.instances[-1].kwargs["portfolio_alert_service"]
    assert portfolio_alert_service is not None
    assert portfolio_alert_service.chip_summary_provider is _FakePortfolioChipService.instances[-1]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_main_integration.py::test_portfolio_alert_service_receives_portfolio_chip_provider -q
```

Expected: FAIL because `ui_qt/main.py` does not expose/import `PortfolioChipService` and currently does not instantiate it for the decision desk.

- [ ] **Step 3: Import PortfolioChipService**

In `ui_qt/main.py`, add this import near the existing portfolio imports:

```python
from app_module.portfolio_chip_service import PortfolioChipService
```

- [ ] **Step 4: Replace the current chip provider selection logic**

In `MainWindow._create_decision_desk_builder`, replace:

```python
            chip_summary_provider = None
            if hasattr(self, "broker_flow_service") and self.broker_flow_service is not None:
                provider_candidate = getattr(self.broker_flow_service, "get_stock_chip_summary", None)
                if callable(provider_candidate):
                    chip_summary_provider = self.broker_flow_service
```

with:

```python
            chip_summary_provider = None
            try:
                chip_summary_provider = PortfolioChipService(
                    self.config,
                    broker_flow_service=getattr(self, "broker_flow_service", None),
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[MainWindow] 決策桌面 PortfolioChipService 初始化失敗：{exc}")
```

Keep the existing `PortfolioAlertService(...)` construction unchanged after this block.

- [ ] **Step 5: Run focused UI integration test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_main_integration.py::test_portfolio_alert_service_receives_portfolio_chip_provider -q
```

Expected: PASS.

- [ ] **Step 6: Run full decision desk main integration tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_main_integration.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 2**

```powershell
git add ui_qt\main.py tests\test_ui_qt_decision_desk_main_integration.py
git commit -m "feat: inject portfolio chip provider into decision desk"
```

---

### Task 3: Documentation Coverage for Portfolio Alert Chip Provider

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [ ] **Step 1: Update PROJECT_SNAPSHOT.md**

In `docs/00_core/PROJECT_SNAPSHOT.md`, find the Daily Decision Desk current-state bullet that says Portfolio Alert true chip provider is still being filled. Replace that sentence with:

```markdown
Portfolio Alert v1 已接 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService`，可把條件監控與籌碼風險彙總成每日持倉警示；若籌碼資料缺失、估算或不可用，會透過 `quality / warnings` 降級揭露，不補值。
```

- [ ] **Step 2: Update ROADMAP_6M_ENGINEERING.md**

In `docs/00_core/ROADMAP_6M_ENGINEERING.md`, update Month 4 Daily Decision Desk status to state:

```markdown
Portfolio Alert v1 已接 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService`；下一步聚焦 Relative Strength / Liquidity Ranking 與 Portfolio Alert 後續來源差異歸因。
```

Also update the immediate todo list item that currently asks to “補齊 Portfolio Alert 的真實 chip provider” so it no longer lists this as open.

- [ ] **Step 3: Update system_architecture.md**

In `docs/01_architecture/system_architecture.md`, update the Application Layer Daily Decision Desk paragraph with:

```markdown
Portfolio Alert v1 由 `PortfolioAlertService` 聚合 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService`，將持倉條件狀態與籌碼風險整理為 `PortfolioAlertSummary`；籌碼缺資料、估算股數與 unavailable 事件都以 warnings 與 quality 降級揭露。
```

- [ ] **Step 4: Update APPLICATION_MANUAL.md**

In `docs/07_guides/APPLICATION_MANUAL.md` section 8.2, add this paragraph under Portfolio Alert:

```markdown
Portfolio Alert v1 會整合持倉條件監控與 `PortfolioChipService` 籌碼摘要。當持倉條件失效、警告，或個股籌碼風險為 bearish / extreme / risk 時，會列入持倉警示；若籌碼股數資料缺失、估算或部分事件不可用，會在 warnings 顯示 `portfolio_alerts_chip_*`，並將 quality 降級為 `ESTIMATED` 或 `DEGRADED`。
```

- [ ] **Step 5: Commit Task 3**

```powershell
git add docs\00_core\PROJECT_SNAPSHOT.md docs\00_core\ROADMAP_6M_ENGINEERING.md docs\01_architecture\system_architecture.md docs\07_guides\APPLICATION_MANUAL.md
git commit -m "docs: document portfolio alert chip provider connection"
```

---

### Task 4: Final Verification Gate

**Files:**
- Verify only; no planned code changes.

- [ ] **Step 1: Run Portfolio Alert tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_alert_service.py tests\test_ui_qt_decision_desk_main_integration.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run UI workbench test**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 3: Run QA validation script**

```powershell
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

Expected: `21 passed, 0 failed, 4 skipped`.

- [ ] **Step 4: Run mypy**

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

Expected: `Success: no issues found`.

- [ ] **Step 5: Run financial float boundary checker**

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

Expected: exit code 0 with no violations.

- [ ] **Step 6: Run py_compile for changed Python files**

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\portfolio_alert_service.py ui_qt\main.py
```

Expected: exit code 0.

- [ ] **Step 7: Inspect git status**

```powershell
git status --short
```

Expected: only intended files are modified, and no tracked QA output files are staged unless explicitly requested.

---

## Self-Review

- Spec coverage: This plan connects the real chip provider, preserves service snapshot aggregation, adds quality/warnings for chip data gaps, updates tests, and includes documentation coverage.
- Placeholder scan: No `TBD`, `TODO`, or vague “add appropriate handling” steps remain.
- Type consistency: `PortfolioChipService.get_stock_chip_summary(stock_code, period_days)` matches `ChipSummaryProviderProtocol`; `PortfolioAlertService.chip_summary_provider` remains a provider object with that method.
