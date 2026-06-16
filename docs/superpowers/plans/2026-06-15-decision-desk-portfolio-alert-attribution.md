# Daily Decision Desk Portfolio Alert Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Portfolio Alert attribution v1 so Daily Decision Desk can explain whether each holding alert came from source drift, condition monitor status, chip risk, or data quality, without recomputing portfolio or chip logic in the UI.

**Architecture:** Extend `PortfolioAlertSummary` with structured attribution items produced by `PortfolioAlertService` while it already evaluates positions, conditions, and chip summaries. Keep attribution as DTO data only; `DecisionDeskRiskPromptService` and the Qt view may read it, but must not call portfolio, condition, or chip services themselves. Preserve existing warnings and quality semantics.

**Tech Stack:** Python dataclasses, existing Portfolio / ConditionMonitor / PortfolioChip services, PySide6, pytest, mypy.

---

## File Structure

- Modify: `app_module/decision_desk_dtos.py`
  - Add `PortfolioAlertAttribution`.
  - Add `attributions` to `PortfolioAlertSummary`.
  - Serialize attribution items via `PortfolioAlertSummary.to_dict()`.
- Modify: `app_module/portfolio_alert_service.py`
  - Build structured attribution items while collecting alert items.
  - Track condition status, chip risk level, source label, severity, and data-quality flags per stock.
  - Preserve existing alert_count / alert_codes / alert_level behavior.
- Modify: `app_module/decision_desk_risk_prompt_service.py`
  - Enrich portfolio risk prompts using attribution reason text when available.
  - Do not call portfolio or chip providers.
- Modify: `ui_qt/views/decision_desk_view.py`
  - Render compact attribution details under Portfolio Alert row.
- Modify tests:
  - `tests/test_portfolio_alert_service.py`
  - `tests/test_decision_desk_risk_prompt_service.py`
  - `tests/test_ui_qt_decision_desk_view.py`
- Modify docs after behavior lands:
  - `docs/00_core/PROJECT_SNAPSHOT.md`
  - `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - `docs/01_architecture/system_architecture.md`
  - `docs/07_guides/APPLICATION_MANUAL.md`
  - `docs/00_core/DOCUMENTATION_INDEX.md`

---

## Attribution Contract

Each attribution item represents one portfolio position observed during Portfolio Alert evaluation.

Fields:

- `stock_code`: stock code or `unknown_<index>`.
- `source_label`: existing position source label, such as `manual`, `recommendation_result:rec_watch`, or `backtest_run:bt_007`.
- `condition_status`: normalized condition monitor status (`valid`, `warning`, `invalid`, `error`, or `unknown`).
- `chip_risk_level`: normalized chip risk level (`neutral`, `bullish`, `bearish`, `extreme`, `risk`, `missing`, `invalid`, `error`, or `unavailable`).
- `severity`: integer alert severity already used by `PortfolioAlertService`; higher is more urgent.
- `reasons`: tuple of stable reason tokens, for example `condition:invalid`, `chip:risk_level:bearish`, `chip:data_missing`, `chip:estimated`, `chip:unavailable_events:3`, `condition:error`.
- `data_quality_flags`: tuple of stable quality flags, for example `chip_estimated`, `chip_data_missing`, `chip_unavailable_events`, `condition_error`, `chip_provider_error`.

Quality rules remain unchanged:

- Condition monitor exception makes summary `DEGRADED`.
- Chip provider exception or estimated / missing lots makes summary at least `ESTIMATED`, unless another hard failure makes it `DEGRADED`.
- Attribution must not hide existing warning strings.

Ordering:

- `alert_codes` keeps existing severity sorting.
- `attributions` are sorted by `severity DESC`, then `stock_code ASC`.

---

### Task 1: Add Portfolio Alert Attribution DTO

**Files:**
- Modify: `app_module/decision_desk_dtos.py`
- Test: `tests/test_portfolio_alert_service.py`

- [ ] **Step 1: Write failing serialization test**

Append this test to `tests/test_portfolio_alert_service.py`:

```python
def test_portfolio_alert_summary_serializes_attributions():
    attribution = PortfolioAlertAttribution(
        stock_code="2330",
        source_label="recommendation_result:rec_001",
        condition_status="warning",
        chip_risk_level="bearish",
        severity=80,
        reasons=("condition:warning", "chip:risk_level:bearish"),
        data_quality_flags=("chip_estimated",),
    )
    summary = PortfolioAlertSummary(
        as_of_date=date(2026, 6, 15),
        quality=DecisionDeskQuality.ESTIMATED,
        warnings=("portfolio_alerts_chip_estimated:2330",),
        alert_count=1,
        alert_codes=("2330",),
        alert_level="high",
        attributions=(attribution,),
    )

    payload = summary.to_dict()

    assert payload["attributions"][0]["stock_code"] == "2330"
    assert payload["attributions"][0]["source_label"] == "recommendation_result:rec_001"
    assert payload["attributions"][0]["condition_status"] == "warning"
    assert payload["attributions"][0]["chip_risk_level"] == "bearish"
    assert payload["attributions"][0]["reasons"] == ["condition:warning", "chip:risk_level:bearish"]
    assert payload["attributions"][0]["data_quality_flags"] == ["chip_estimated"]
```

Add these imports:

```python
from app_module.decision_desk_dtos import PortfolioAlertAttribution
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_alert_service.py::test_portfolio_alert_summary_serializes_attributions -q
```

Expected: FAIL because `PortfolioAlertAttribution` and `PortfolioAlertSummary.attributions` do not exist yet.

- [ ] **Step 3: Add DTO**

In `app_module/decision_desk_dtos.py`, add this before `PortfolioAlertSummary`:

```python
@dataclass(frozen=True)
class PortfolioAlertAttribution:
    stock_code: str
    source_label: str
    condition_status: str
    chip_risk_level: str
    severity: int
    reasons: tuple[str, ...] = ()
    data_quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", str(self.stock_code))
        object.__setattr__(self, "source_label", str(self.source_label))
        object.__setattr__(self, "condition_status", str(self.condition_status))
        object.__setattr__(self, "chip_risk_level", str(self.chip_risk_level))
        object.__setattr__(self, "severity", int(self.severity))
        object.__setattr__(self, "reasons", tuple(str(item) for item in self.reasons))
        object.__setattr__(self, "data_quality_flags", tuple(str(item) for item in self.data_quality_flags))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "source_label": self.source_label,
            "condition_status": self.condition_status,
            "chip_risk_level": self.chip_risk_level,
            "severity": self.severity,
            "reasons": list(self.reasons),
            "data_quality_flags": list(self.data_quality_flags),
        }
```

Update `PortfolioAlertSummary`:

```python
attributions: tuple[PortfolioAlertAttribution, ...] = ()
```

In `__post_init__()`:

```python
object.__setattr__(self, "attributions", tuple(self.attributions))
```

In `to_dict()`:

```python
"attributions": [item.to_dict() for item in self.attributions],
```

- [ ] **Step 4: Run focused DTO test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_alert_service.py::test_portfolio_alert_summary_serializes_attributions -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```powershell
git add app_module\decision_desk_dtos.py tests\test_portfolio_alert_service.py
git commit -m "feat: add portfolio alert attribution dto"
```

---

### Task 2: Build Attributions in PortfolioAlertService

**Files:**
- Modify: `app_module/portfolio_alert_service.py`
- Modify: `tests/test_portfolio_alert_service.py`

- [ ] **Step 1: Add failing attribution behavior test**

Append this test to `tests/test_portfolio_alert_service.py`:

```python
def test_portfolio_alert_service_builds_condition_and_chip_attributions():
    positions = [
        make_position("2330", "recommendation_result", "rec_001"),
        make_position("2603", "backtest_run", "bt_007"),
    ]
    service = PortfolioAlertService(
        FakePortfolioService(positions),
        FakeConditionMonitor(
            {
                "2330": "warning",
                "2603": "invalid",
            }
        ),
        FakeChipSummaryProvider(
            {
                "2330": {
                    "risk_level": "bearish",
                    "lots_available": True,
                    "has_estimated_lots": True,
                    "estimated_event_count": 1,
                    "unavailable_event_count": 0,
                },
                "2603": {
                    "risk_level": "neutral",
                    "lots_available": False,
                    "has_estimated_lots": False,
                    "estimated_event_count": 0,
                    "unavailable_event_count": 2,
                },
            }
        ),
    )

    snapshot = service.build_snapshot(date(2026, 6, 15))

    by_code = {item.stock_code: item for item in snapshot.attributions}
    assert tuple(by_code) == ("2603", "2330")
    assert by_code["2330"].source_label == "recommendation_result:rec_001"
    assert by_code["2330"].condition_status == "warning"
    assert by_code["2330"].chip_risk_level == "bearish"
    assert "condition:warning" in by_code["2330"].reasons
    assert "chip:risk_level:bearish" in by_code["2330"].reasons
    assert "chip_estimated" in by_code["2330"].data_quality_flags
    assert by_code["2603"].condition_status == "invalid"
    assert "condition:invalid" in by_code["2603"].reasons
    assert "chip_data_missing" in by_code["2603"].data_quality_flags
    assert "chip_unavailable_events" in by_code["2603"].data_quality_flags
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_alert_service.py::test_portfolio_alert_service_builds_condition_and_chip_attributions -q
```

Expected: FAIL because attributions are not populated.

- [ ] **Step 3: Extend internal alert item**

In `app_module/portfolio_alert_service.py`, import:

```python
from app_module.decision_desk_dtos import DecisionDeskQuality, PortfolioAlertAttribution, PortfolioAlertSummary
```

Update `_AlertItem`:

```python
@dataclass(frozen=True)
class _AlertItem:
    stock_code: str
    source_label: str
    severity: int
    reasons: tuple[str, ...]
    condition_status: str
    chip_risk_level: str
    data_quality_flags: tuple[str, ...]
```

- [ ] **Step 4: Return chip detail instead of severity only**

Add:

```python
@dataclass(frozen=True)
class _ChipRiskResult:
    severity: int
    risk_level: str
    reasons: tuple[str, ...]
    data_quality_flags: tuple[str, ...]
```

Replace `_chip_risk_severity()` with `_evaluate_chip_risk()`:

```python
def _evaluate_chip_risk(self, stock_code: str, warnings: list[str]) -> _ChipRiskResult:
    provider = self.chip_summary_provider
    if provider is None:
        return _ChipRiskResult(0, "unavailable", (), ())
    try:
        summary = provider.get_stock_chip_summary(stock_code, period_days=self.chip_lookback_days)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"portfolio_alerts_chip_provider_error:{stock_code}:{exc}")
        return _ChipRiskResult(1, "error", ("chip:provider_error",), ("chip_provider_error",))

    if not isinstance(summary, Mapping):
        warnings.append(f"portfolio_alerts_chip_summary_invalid:{stock_code}")
        return _ChipRiskResult(0, "invalid", ("chip:summary_invalid",), ("chip_summary_invalid",))

    reasons: list[str] = []
    data_quality_flags: list[str] = []
    lots_available = bool(summary.get("lots_available", True))
    has_estimated_lots = bool(summary.get("has_estimated_lots", False))
    unavailable_count = self._read_non_negative_int(summary.get("unavailable_event_count"))
    estimated_count = self._read_non_negative_int(summary.get("estimated_event_count"))

    if not lots_available:
        warnings.append(f"portfolio_alerts_chip_data_missing:{stock_code}")
        reasons.append("chip:data_missing")
        data_quality_flags.append("chip_data_missing")
    if has_estimated_lots or estimated_count > 0:
        warnings.append(f"portfolio_alerts_chip_estimated:{stock_code}")
        reasons.append("chip:estimated")
        data_quality_flags.append("chip_estimated")
    if unavailable_count > 0:
        warnings.append(f"portfolio_alerts_chip_unavailable_events:{stock_code}:{unavailable_count}")
        reasons.append(f"chip:unavailable_events:{unavailable_count}")
        data_quality_flags.append("chip_unavailable_events")

    risk_level = str(summary.get("risk_level", "")).lower().strip() or "neutral"
    if risk_level in {"bearish", "extreme", "risk"}:
        reasons.append(f"chip:risk_level:{risk_level}")
        return _ChipRiskResult(80, risk_level, tuple(reasons), tuple(data_quality_flags))
    return _ChipRiskResult(0, risk_level, tuple(reasons), tuple(data_quality_flags))
```

- [ ] **Step 5: Build `_AlertItem` with attribution fields**

In `_collect_alerts()`, replace the chip severity calls and item creation with:

```python
chip_result = self._evaluate_chip_risk(stock_code, warnings)
if chip_result.severity > 0:
    reasons.append("chip_alert")
reasons.extend(chip_result.reasons)

if status_severity > 0 or chip_result.severity > 0 or chip_result.data_quality_flags:
    severity = max(status_severity, chip_result.severity)
    items.append(
        _AlertItem(
            stock_code=stock_code,
            source_label=source_label,
            severity=severity,
            reasons=tuple(dict.fromkeys(reasons)),
            condition_status=status or "unknown",
            chip_risk_level=chip_result.risk_level,
            data_quality_flags=chip_result.data_quality_flags,
        )
    )
```

For condition monitor exception, append an item:

```python
items.append(
    _AlertItem(
        stock_code=stock_code,
        source_label=source_label,
        severity=100,
        reasons=("condition:error",),
        condition_status="error",
        chip_risk_level="unavailable",
        data_quality_flags=("condition_error",),
    )
)
```

Important: existing behavior currently continues after condition monitor exception, producing `alert_count=0` in `test_portfolio_alert_service_returns_degraded_on_condition_monitor_error`. Update that test expectation to `alert_count=1`, `alert_codes=("1101",)`, and `alert_level="high"` because the attribution-aware alert should surface the failed position.

- [ ] **Step 6: Add attribution conversion helper**

Add:

```python
def _build_attributions(self, alerts: list[_AlertItem]) -> tuple[PortfolioAlertAttribution, ...]:
    sorted_alerts = sorted(alerts, key=lambda item: (-item.severity, item.stock_code))
    return tuple(
        PortfolioAlertAttribution(
            stock_code=item.stock_code,
            source_label=item.source_label,
            condition_status=item.condition_status,
            chip_risk_level=item.chip_risk_level,
            severity=item.severity,
            reasons=item.reasons,
            data_quality_flags=item.data_quality_flags,
        )
        for item in sorted_alerts
    )
```

Pass `attributions=self._build_attributions(alerts)` in every `PortfolioAlertSummary` returned after positions exist.

For no positions or portfolio service failure, use default empty attributions.

- [ ] **Step 7: Run Portfolio Alert tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_alert_service.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```powershell
git add app_module\portfolio_alert_service.py tests\test_portfolio_alert_service.py
git commit -m "feat: attribute portfolio alert sources"
```

---

### Task 3: Enrich Risk Prompts from Portfolio Attribution

**Files:**
- Modify: `app_module/decision_desk_risk_prompt_service.py`
- Modify: `tests/test_decision_desk_risk_prompt_service.py`

- [ ] **Step 1: Add failing risk prompt enrichment test**

Append to `tests/test_decision_desk_risk_prompt_service.py`:

```python
def test_risk_prompt_service_uses_portfolio_attribution_reason_text():
    sample_date = date(2026, 6, 15)
    service = DecisionDeskRiskPromptService()
    portfolio = PortfolioAlertSummary(
        sample_date,
        DecisionDeskQuality.OBSERVED,
        (),
        alert_count=1,
        alert_codes=("2330",),
        alert_level="high",
        attributions=(
            PortfolioAlertAttribution(
                stock_code="2330",
                source_label="recommendation_result:rec_001",
                condition_status="warning",
                chip_risk_level="bearish",
                severity=80,
                reasons=("condition:warning", "chip:risk_level:bearish"),
                data_quality_flags=(),
            ),
        ),
    )

    summary = service.build_summary(
        as_of_date=sample_date,
        market_regime=MarketRegimeSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        market_breadth=MarketBreadthSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        sector_rotation=SectorRotationSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        watchlist_triggers=WatchlistTriggerSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        portfolio_alerts=portfolio,
    )

    prompt = next(item for item in summary.prompts if item.category == "portfolio_alert")
    assert "recommendation_result:rec_001" in prompt.reason
    assert "condition:warning" in prompt.reason
    assert "chip:risk_level:bearish" in prompt.reason
```

Add import:

```python
from app_module.decision_desk_dtos import PortfolioAlertAttribution
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_risk_prompt_service.py::test_risk_prompt_service_uses_portfolio_attribution_reason_text -q
```

Expected: FAIL because prompt reason does not use attributions.

- [ ] **Step 3: Update portfolio prompt generation**

In `_portfolio_prompts()`, build a lookup:

```python
attribution_by_code = {item.stock_code: item for item in section.attributions}
```

Use it when building each prompt:

```python
attribution = attribution_by_code.get(code)
if attribution is not None:
    reason = (
        f"{code} 出現在 Portfolio Alert 清單；來源 {attribution.source_label}；"
        f"condition={attribution.condition_status}；chip={attribution.chip_risk_level}；"
        f"reasons={', '.join(attribution.reasons) if attribution.reasons else '無'}。"
    )
else:
    reason = f"{code} 出現在 Portfolio Alert 清單。"
```

Keep existing severity rule.

- [ ] **Step 4: Run risk prompt tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_risk_prompt_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```powershell
git add app_module\decision_desk_risk_prompt_service.py tests\test_decision_desk_risk_prompt_service.py
git commit -m "feat: include portfolio attribution in risk prompts"
```

---

### Task 4: Render Portfolio Attribution in Daily Decision Desk

**Files:**
- Modify: `ui_qt/views/decision_desk_view.py`
- Modify: `tests/test_ui_qt_decision_desk_view.py`

- [ ] **Step 1: Add failing UI test**

Append to `tests/test_ui_qt_decision_desk_view.py`:

```python
def test_decision_desk_view_renders_portfolio_alert_attributions():
    snapshot = make_snapshot()
    snapshot = replace(
        snapshot,
        portfolio_alerts=PortfolioAlertSummary(
            as_of_date=snapshot.as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            alert_count=1,
            alert_codes=("2330",),
            alert_level="high",
            attributions=(
                PortfolioAlertAttribution(
                    stock_code="2330",
                    source_label="recommendation_result:rec_001",
                    condition_status="warning",
                    chip_risk_level="bearish",
                    severity=80,
                    reasons=("condition:warning", "chip:risk_level:bearish"),
                    data_quality_flags=(),
                ),
            ),
        ),
    )

    view = DecisionDeskView(decision_desk_builder=FakeBuilder(snapshot))

    assert "recommendation_result:rec_001" in view.portfolio_alerts_value.text()
    assert "condition=warning" in view.portfolio_alerts_value.text()
    assert "chip=bearish" in view.portfolio_alerts_value.text()
```

Add import:

```python
from app_module.decision_desk_dtos import PortfolioAlertAttribution
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_view.py::test_decision_desk_view_renders_portfolio_alert_attributions -q
```

Expected: FAIL because Portfolio Alert row does not display attributions.

- [ ] **Step 3: Add view formatter**

In `ui_qt/views/decision_desk_view.py`, update `portfolio_alerts_value` rendering:

```python
portfolio_attribution_text = self._format_portfolio_attributions(snapshot.portfolio_alerts.attributions)
self.portfolio_alerts_value.setText(
    f"警示數：{snapshot.portfolio_alerts.alert_count or 0}；"
    f"持倉代碼：{', '.join(snapshot.portfolio_alerts.alert_codes) if snapshot.portfolio_alerts.alert_codes else '無'}；"
    f"等級：{snapshot.portfolio_alerts.alert_level or '無'}；"
    f"來源歸因：{portfolio_attribution_text}"
)
```

Add helper:

```python
@staticmethod
def _format_portfolio_attributions(attributions) -> str:
    if not attributions:
        return "無"
    parts = []
    for item in attributions[:3]:
        parts.append(
            f"{item.stock_code} {item.source_label} "
            f"condition={item.condition_status} chip={item.chip_risk_level}"
        )
    return "；".join(parts)
```

Add to `_EmptySection.__init__()`:

```python
self.attributions: tuple[object, ...] = ()
```

- [ ] **Step 4: Run UI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_view.py tests\test_ui_qt_decision_desk_main_integration.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```powershell
git add ui_qt\views\decision_desk_view.py tests\test_ui_qt_decision_desk_view.py tests\test_ui_qt_decision_desk_main_integration.py
git commit -m "feat: render portfolio alert attribution"
```

---

### Task 5: Documentation Sync

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`

- [ ] **Step 1: Update Project Snapshot**

Add this to the Daily Decision Desk current-state paragraph:

```markdown
Portfolio Alert Attribution v1 已將每筆持倉警示拆為來源標籤、condition status、chip risk level、reason tokens 與 data quality flags，使 Daily Decision Desk 能辨識警示來自進場假設失效、籌碼風險或資料品質缺口。
```

- [ ] **Step 2: Update 6M Roadmap**

Update Month 4 immediate todos so Portfolio Alert source attribution is no longer listed as next. Replace with:

```markdown
1. Month 4 Daily Decision Desk v1 已完成主要 provider 接線、Why Not / 風險提示與 Portfolio Alert 來源差異歸因；後續聚焦 UI 密度整理與 Month 5 Fundamental Layer 前置規格。
```

- [ ] **Step 3: Update architecture**

Add:

```markdown
Portfolio Alert Attribution v1 屬於 `PortfolioAlertService` 的輸出責任，因為只有該 service 同時看得到 position source、condition monitor 結果與 chip summary。UI 與 Risk Prompt service 只能讀取 `PortfolioAlertSummary.attributions`，不得重新查詢或重算。
```

- [ ] **Step 4: Update Application Manual**

In Daily Decision Desk section, add:

```markdown
Portfolio Alert 的來源歸因會顯示每檔警示持倉的來源標籤、condition 狀態、chip risk level 與原因 token。這用於解釋警示來源，不代表自動賣出或調倉。
```

- [ ] **Step 5: Update Documentation Index**

Add row:

```markdown
| [2026-06-15-decision-desk-portfolio-alert-attribution.md](../superpowers/plans/2026-06-15-decision-desk-portfolio-alert-attribution.md) | Daily Decision Desk Portfolio Alert Attribution v1 實作計畫，將持倉警示拆為來源標籤、condition status、chip risk level、reason tokens 與 data quality flags。 |
```

Add changelog:

```markdown
- 2026-06-15：補列 Daily Decision Desk Portfolio Alert Attribution v1 實作計畫至 Superpowers plans 索引。
```

- [ ] **Step 6: Commit Task 5**

```powershell
git add docs\00_core\PROJECT_SNAPSHOT.md docs\00_core\ROADMAP_6M_ENGINEERING.md docs\01_architecture\system_architecture.md docs\07_guides\APPLICATION_MANUAL.md docs\00_core\DOCUMENTATION_INDEX.md
git commit -m "docs: document portfolio alert attribution"
```

---

### Task 6: Final Verification Gate

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_alert_service.py tests\test_decision_desk_risk_prompt_service.py tests\test_decision_desk_service.py tests\test_ui_qt_decision_desk_view.py tests\test_ui_qt_decision_desk_main_integration.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run full pytest**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run UI workbench tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 4: Run Update Tab QA**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

Expected: `21 passed, 0 failed, 4 skipped`.

- [ ] **Step 5: Run mypy**

Run:

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

Expected: `Success: no issues found`.

- [ ] **Step 6: Run financial float boundary check**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

Expected: exit code 0 with no violations.

- [ ] **Step 7: Run look-ahead bias check**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\check_look_ahead_bias.py
```

Expected: exit code 0 with no violations.

- [ ] **Step 8: Run py_compile**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\decision_desk_dtos.py app_module\portfolio_alert_service.py app_module\decision_desk_risk_prompt_service.py ui_qt\views\decision_desk_view.py
```

Expected: exit code 0.

---

## Self-Review

- Spec coverage: Covers Portfolio Alert source attribution, structured DTO serialization, service-level derivation, risk prompt enrichment, UI rendering, docs, and verification.
- Placeholder scan: No TBD / TODO placeholders are present.
- Type consistency: `PortfolioAlertAttribution`, `PortfolioAlertSummary.attributions`, `_ChipRiskResult`, and view formatter names are consistent across tasks.
- Scope check: This plan does not implement post-trade attribution or Month 6 strategy lifecycle attribution. It only explains current Daily Decision Desk Portfolio Alert sources.

