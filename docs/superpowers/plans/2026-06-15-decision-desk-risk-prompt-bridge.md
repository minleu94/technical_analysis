# Daily Decision Desk Risk Prompt Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Daily Decision Desk Risk Prompt Bridge v1 so existing section outputs become concise Why Not / risk prompts without recomputing scoring, screening, portfolio, chip, or liquidity logic in the UI.

**Architecture:** Add a pure application service, `DecisionDeskRiskPromptService`, that consumes already-built Daily Decision Desk DTOs and maps their codes, qualities, and warnings into a new `DecisionDeskRiskPromptSummary`. `DecisionDeskSnapshotBuilder` will build normal sections first, derive risk prompts from those DTOs, then attach the summary to the snapshot. The Qt view renders the DTO only.

**Tech Stack:** Python dataclasses, existing Daily Decision Desk DTOs, PySide6, pytest, mypy.

---

## File Structure

- Modify: `app_module/decision_desk_dtos.py`
  - Add `DecisionDeskRiskPrompt` and `DecisionDeskRiskPromptSummary`.
  - Add `risk_prompts` to `DecisionDeskSnapshot`.
  - Add `risk_prompts` to `DecisionDeskSnapshot.to_dict()`.
- Create: `app_module/decision_desk_risk_prompt_service.py`
  - Implement pure mapping from existing section DTOs to prompts.
  - No SQLite, no float, no UI dependencies.
- Modify: `app_module/decision_desk_service.py`
  - Build normal sections first.
  - Derive `risk_prompts`.
  - Include prompt warnings and quality in snapshot aggregation.
- Modify: `ui_qt/views/decision_desk_view.py`
  - Render risk prompt summary as a new Daily Decision Desk section.
  - Add fallback `_EmptySection` attributes.
- Modify tests:
  - `tests/test_decision_desk_risk_prompt_service.py`
  - `tests/test_decision_desk_service.py`
  - `tests/test_ui_qt_decision_desk_view.py`
- Modify docs after behavior lands:
  - `docs/00_core/PROJECT_SNAPSHOT.md`
  - `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - `docs/01_architecture/system_architecture.md`
  - `docs/07_guides/APPLICATION_MANUAL.md`
  - `docs/00_core/DOCUMENTATION_INDEX.md`

---

## Prompt Contract

`DecisionDeskRiskPromptService` must only read section DTO fields and warnings. It must not query SQLite, run recommendation scoring, inspect raw portfolio files, or recompute liquidity.

Prompt items use these severities:

- `info`: context worth seeing, not a blocker.
- `warning`: a research or trade-readiness concern.
- `critical`: a holding or candidate risk that should be checked before action.

Prompt categories:

- `data_quality`: section is `MISSING`, `DEGRADED`, or `ESTIMATED`.
- `liquidity`: `RelativeStrengthLiquiditySummary.low_liquidity_codes`.
- `weakness`: `RelativeStrengthLiquiditySummary.weak_strength_codes`.
- `watchlist_risk`: warnings such as `watchlist_trigger_risk_alert:<code>`.
- `portfolio_alert`: `PortfolioAlertSummary.alert_codes`.
- `market_context`: risk-off market regime labels.

Deduplication rule: prompts with the same `(category, code, source)` are emitted once, preserving first occurrence.

Quality rule:

- `MISSING` if all source sections are missing and no prompt can be derived.
- `DEGRADED` if any prompt is derived from degraded/missing/estimated section quality or warning text.
- `OBSERVED` if prompts are derived from observed source sections without data-quality warnings.

---

### Task 1: Add Risk Prompt DTO Contract

**Files:**
- Modify: `app_module/decision_desk_dtos.py`
- Test: `tests/test_decision_desk_service.py`

- [ ] **Step 1: Write failing serialization test**

Append this test to `tests/test_decision_desk_service.py`:

```python
def test_decision_desk_snapshot_serializes_risk_prompts_section():
    sample_date = date(2026, 6, 15)
    prompt = DecisionDeskRiskPrompt(
        category="liquidity",
        severity="warning",
        source="relative_strength_liquidity",
        code="1101",
        title="低流動性",
        reason="1101 低於平均成交金額門檻",
        action_hint="下單或加入研究前檢查可成交金額與部位大小",
    )
    summary = DecisionDeskRiskPromptSummary(
        as_of_date=sample_date,
        quality=DecisionDeskQuality.OBSERVED,
        warnings=(),
        prompts=(prompt,),
    )
    snapshot = DecisionDeskSnapshot(
        as_of_date=sample_date,
        generated_at=datetime(2026, 6, 15, 9, 0, 0),
        schema_version=1,
        overall_quality=DecisionDeskQuality.OBSERVED,
        warnings=(),
        market_regime=MarketRegimeSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        market_breadth=MarketBreadthSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        sector_rotation=SectorRotationSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        watchlist_triggers=WatchlistTriggerSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        portfolio_alerts=PortfolioAlertSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        risk_prompts=summary,
    )

    payload = snapshot.to_dict()

    assert payload["risk_prompts"]["quality"] == "observed"
    assert payload["risk_prompts"]["prompts"][0]["category"] == "liquidity"
    assert payload["risk_prompts"]["prompts"][0]["code"] == "1101"
```

Add these imports at the top of the file:

```python
from app_module.decision_desk_dtos import DecisionDeskRiskPrompt, DecisionDeskRiskPromptSummary
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_service.py::test_decision_desk_snapshot_serializes_risk_prompts_section -q
```

Expected: FAIL because `DecisionDeskRiskPrompt`, `DecisionDeskRiskPromptSummary`, and `risk_prompts` do not exist yet.

- [ ] **Step 3: Add DTOs**

In `app_module/decision_desk_dtos.py`, add this before `DecisionDeskSnapshot`:

```python
@dataclass(frozen=True)
class DecisionDeskRiskPrompt:
    category: str
    severity: str
    source: str
    code: str | None
    title: str
    reason: str
    action_hint: str

    def __post_init__(self) -> None:
        allowed = {"info", "warning", "critical"}
        if self.severity not in allowed:
            raise ValueError(f"unsupported risk prompt severity: {self.severity}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "source": self.source,
            "code": self.code,
            "title": self.title,
            "reason": self.reason,
            "action_hint": self.action_hint,
        }


@dataclass(frozen=True)
class DecisionDeskRiskPromptSummary:
    as_of_date: date | None
    quality: DecisionDeskQuality
    warnings: tuple[str, ...]
    prompts: tuple[DecisionDeskRiskPrompt, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", _normalize_warnings(self.warnings))
        object.__setattr__(self, "prompts", tuple(self.prompts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "quality": self.quality.value,
            "warnings": list(self.warnings),
            "prompts": [prompt.to_dict() for prompt in self.prompts],
        }
```

Update `DecisionDeskSnapshot`:

```python
risk_prompts: DecisionDeskRiskPromptSummary
```

Place the field after `portfolio_alerts`.

Update `__post_init__` so `risk_prompts` must not be `None`:

```python
if self.watchlist_triggers is None or self.portfolio_alerts is None or self.risk_prompts is None:
    raise ValueError("all decision sections must be provided")
```

Update `to_dict()`:

```python
"risk_prompts": self.risk_prompts.to_dict(),
```

- [ ] **Step 4: Run focused DTO test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_service.py::test_decision_desk_snapshot_serializes_risk_prompts_section -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```powershell
git add app_module\decision_desk_dtos.py tests\test_decision_desk_service.py
git commit -m "feat: add decision desk risk prompt dto"
```

---

### Task 2: Implement DecisionDeskRiskPromptService

**Files:**
- Create: `app_module/decision_desk_risk_prompt_service.py`
- Test: `tests/test_decision_desk_risk_prompt_service.py`

- [ ] **Step 1: Create failing service tests**

Create `tests/test_decision_desk_risk_prompt_service.py`:

```python
from datetime import date

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    RelativeStrengthLiquiditySummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
)
from app_module.decision_desk_risk_prompt_service import DecisionDeskRiskPromptService


def test_risk_prompt_service_maps_liquidity_watchlist_and_portfolio_risks():
    sample_date = date(2026, 6, 15)
    service = DecisionDeskRiskPromptService()

    summary = service.build_summary(
        as_of_date=sample_date,
        market_regime=MarketRegimeSummary(sample_date, DecisionDeskQuality.OBSERVED, (), regime_label="risk-off"),
        market_breadth=MarketBreadthSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        sector_rotation=SectorRotationSummary(sample_date, DecisionDeskQuality.OBSERVED, ()),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            sample_date,
            DecisionDeskQuality.OBSERVED,
            (),
            weak_strength_codes=("2409",),
            low_liquidity_codes=("1101",),
        ),
        watchlist_triggers=WatchlistTriggerSummary(
            sample_date,
            DecisionDeskQuality.DEGRADED,
            ("watchlist_trigger_risk_alert:2603",),
            triggered_codes=("2603",),
        ),
        portfolio_alerts=PortfolioAlertSummary(
            sample_date,
            DecisionDeskQuality.ESTIMATED,
            ("portfolio_alerts_chip_estimated:2330",),
            alert_codes=("2330",),
            alert_level="high",
        ),
    )

    prompts = summary.prompts
    assert summary.quality == DecisionDeskQuality.DEGRADED
    assert any(item.category == "liquidity" and item.code == "1101" for item in prompts)
    assert any(item.category == "weakness" and item.code == "2409" for item in prompts)
    assert any(item.category == "watchlist_risk" and item.code == "2603" for item in prompts)
    assert any(item.category == "portfolio_alert" and item.code == "2330" for item in prompts)
    assert any(item.category == "market_context" and item.code is None for item in prompts)
    assert "risk_prompt_source_quality:watchlist_triggers:degraded" in summary.warnings
    assert "risk_prompt_source_quality:portfolio_alerts:estimated" in summary.warnings


def test_risk_prompt_service_returns_missing_when_no_prompt_can_be_derived():
    sample_date = date(2026, 6, 15)
    service = DecisionDeskRiskPromptService()

    summary = service.build_summary(
        as_of_date=sample_date,
        market_regime=MarketRegimeSummary(sample_date, DecisionDeskQuality.MISSING, ("market_regime_missing",)),
        market_breadth=MarketBreadthSummary(sample_date, DecisionDeskQuality.MISSING, ("market_breadth_missing",)),
        sector_rotation=SectorRotationSummary(sample_date, DecisionDeskQuality.MISSING, ("sector_rotation_missing",)),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(sample_date, DecisionDeskQuality.MISSING, ("relative_strength_liquidity_missing",)),
        watchlist_triggers=WatchlistTriggerSummary(sample_date, DecisionDeskQuality.MISSING, ("watchlist_triggers_missing",)),
        portfolio_alerts=PortfolioAlertSummary(sample_date, DecisionDeskQuality.MISSING, ("portfolio_alerts_missing",)),
    )

    assert summary.quality == DecisionDeskQuality.MISSING
    assert summary.prompts == ()
    assert summary.warnings == ("risk_prompt_missing",)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_risk_prompt_service.py -q
```

Expected: FAIL because `app_module.decision_desk_risk_prompt_service` does not exist.

- [ ] **Step 3: Create service implementation**

Create `app_module/decision_desk_risk_prompt_service.py`:

```python
from __future__ import annotations

from datetime import date

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    DecisionDeskRiskPrompt,
    DecisionDeskRiskPromptSummary,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    RelativeStrengthLiquiditySummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
)


class DecisionDeskRiskPromptService:
    """Derive actionable risk prompts from existing Daily Decision Desk sections."""

    def build_summary(
        self,
        *,
        as_of_date: date,
        market_regime: MarketRegimeSummary,
        market_breadth: MarketBreadthSummary,
        sector_rotation: SectorRotationSummary,
        relative_strength_liquidity: RelativeStrengthLiquiditySummary,
        watchlist_triggers: WatchlistTriggerSummary,
        portfolio_alerts: PortfolioAlertSummary,
    ) -> DecisionDeskRiskPromptSummary:
        prompts: list[DecisionDeskRiskPrompt] = []
        warnings: list[str] = []

        sections = (
            ("market_regime", market_regime),
            ("market_breadth", market_breadth),
            ("sector_rotation", sector_rotation),
            ("relative_strength_liquidity", relative_strength_liquidity),
            ("watchlist_triggers", watchlist_triggers),
            ("portfolio_alerts", portfolio_alerts),
        )
        for section_name, section in sections:
            if section.quality != DecisionDeskQuality.OBSERVED:
                warnings.append(f"risk_prompt_source_quality:{section_name}:{section.quality.value}")

        prompts.extend(self._market_context_prompts(market_regime))
        prompts.extend(self._relative_strength_prompts(relative_strength_liquidity))
        prompts.extend(self._watchlist_prompts(watchlist_triggers))
        prompts.extend(self._portfolio_prompts(portfolio_alerts))

        prompts = self._dedupe(prompts)
        if not prompts:
            return DecisionDeskRiskPromptSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("risk_prompt_missing",),
                prompts=(),
            )

        quality = DecisionDeskQuality.OBSERVED if not warnings else DecisionDeskQuality.DEGRADED
        return DecisionDeskRiskPromptSummary(
            as_of_date=as_of_date,
            quality=quality,
            warnings=tuple(dict.fromkeys(warnings)),
            prompts=tuple(prompts),
        )

    @staticmethod
    def _market_context_prompts(section: MarketRegimeSummary) -> list[DecisionDeskRiskPrompt]:
        label = (section.regime_label or "").lower()
        if "risk-off" not in label and "bear" not in label and "空" not in label:
            return []
        return [
            DecisionDeskRiskPrompt(
                category="market_context",
                severity="warning",
                source="market_regime",
                code=None,
                title="市場風險偏高",
                reason=f"Market Regime 顯示 {section.regime_label}",
                action_hint="降低解讀強勢股的確定性，先檢查大盤與產業是否同步支持。",
            )
        ]

    @staticmethod
    def _relative_strength_prompts(section: RelativeStrengthLiquiditySummary) -> list[DecisionDeskRiskPrompt]:
        prompts: list[DecisionDeskRiskPrompt] = []
        for code in section.low_liquidity_codes:
            prompts.append(
                DecisionDeskRiskPrompt(
                    category="liquidity",
                    severity="warning",
                    source="relative_strength_liquidity",
                    code=code,
                    title="低流動性",
                    reason=f"{code} 被 Relative Strength / Liquidity Ranking 標記為低流動性。",
                    action_hint="加入研究或下單前檢查平均成交金額、部位大小與可成交性。",
                )
            )
        for code in section.weak_strength_codes:
            prompts.append(
                DecisionDeskRiskPrompt(
                    category="weakness",
                    severity="info",
                    source="relative_strength_liquidity",
                    code=code,
                    title="相對弱勢",
                    reason=f"{code} 位於 20 日相對弱勢清單。",
                    action_hint="避免只因短線反彈納入候選，先確認反轉條件或基本面催化。",
                )
            )
        return prompts

    @staticmethod
    def _watchlist_prompts(section: WatchlistTriggerSummary) -> list[DecisionDeskRiskPrompt]:
        prompts: list[DecisionDeskRiskPrompt] = []
        for warning in section.warnings:
            prefix = "watchlist_trigger_risk_alert:"
            if not warning.startswith(prefix):
                continue
            code = warning.removeprefix(prefix)
            prompts.append(
                DecisionDeskRiskPrompt(
                    category="watchlist_risk",
                    severity="warning",
                    source="watchlist_triggers",
                    code=code,
                    title="觀察清單風險觸發",
                    reason=f"{code} 觸發 Watchlist risk_alert。",
                    action_hint="查看 RSI、布林通道與近期量價變化，不把觸發視為自動買賣訊號。",
                )
            )
        return prompts

    @staticmethod
    def _portfolio_prompts(section: PortfolioAlertSummary) -> list[DecisionDeskRiskPrompt]:
        prompts: list[DecisionDeskRiskPrompt] = []
        severity = "critical" if section.alert_level in {"high", "critical", "extreme"} else "warning"
        for code in section.alert_codes:
            prompts.append(
                DecisionDeskRiskPrompt(
                    category="portfolio_alert",
                    severity=severity,
                    source="portfolio_alerts",
                    code=code,
                    title="持倉警示",
                    reason=f"{code} 出現在 Portfolio Alert 清單。",
                    action_hint="檢查條件監控、籌碼摘要與持倉風險，不直接自動調整部位。",
                )
            )
        return prompts

    @staticmethod
    def _dedupe(prompts: list[DecisionDeskRiskPrompt]) -> list[DecisionDeskRiskPrompt]:
        seen: set[tuple[str, str | None, str]] = set()
        result: list[DecisionDeskRiskPrompt] = []
        for prompt in prompts:
            key = (prompt.category, prompt.code, prompt.source)
            if key in seen:
                continue
            seen.add(key)
            result.append(prompt)
        return result
```

- [ ] **Step 4: Run focused service tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_risk_prompt_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add app_module\decision_desk_risk_prompt_service.py tests\test_decision_desk_risk_prompt_service.py
git commit -m "feat: derive decision desk risk prompts"
```

---

### Task 3: Integrate Risk Prompts into Snapshot Builder

**Files:**
- Modify: `app_module/decision_desk_service.py`
- Modify: `tests/test_decision_desk_service.py`

- [ ] **Step 1: Add failing builder integration test**

Append this test to `tests/test_decision_desk_service.py`:

```python
def test_decision_desk_builder_derives_risk_prompts_from_existing_sections():
    sample_date = date(2026, 6, 15)
    builder = DecisionDeskSnapshotBuilder(
        provider=FakeProvider(),
        relative_strength_liquidity_service=FakeSectionService(
            "relative_strength_liquidity",
            RelativeStrengthLiquiditySummary(
                as_of_date=sample_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                low_liquidity_codes=("1101",),
            ),
        ),
        watchlist_trigger_service=FakeSectionService(
            "watchlist",
            WatchlistTriggerSummary(
                as_of_date=sample_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=("watchlist_trigger_risk_alert:2603",),
                trigger_count=1,
                triggered_codes=("2603",),
            ),
        ),
        portfolio_alert_service=FakeSectionService(
            "portfolio_alert",
            PortfolioAlertSummary(
                as_of_date=sample_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                alert_count=1,
                alert_codes=("2330",),
                alert_level="high",
            ),
        ),
    )

    snapshot = builder.build_snapshot(sample_date)

    assert snapshot.risk_prompts.quality == DecisionDeskQuality.DEGRADED
    assert any(prompt.category == "liquidity" and prompt.code == "1101" for prompt in snapshot.risk_prompts.prompts)
    assert any(prompt.category == "watchlist_risk" and prompt.code == "2603" for prompt in snapshot.risk_prompts.prompts)
    assert any(prompt.category == "portfolio_alert" and prompt.code == "2330" for prompt in snapshot.risk_prompts.prompts)
    assert "risk_prompts:risk_prompt_source_quality:watchlist_triggers:degraded" in snapshot.warnings
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_service.py::test_decision_desk_builder_derives_risk_prompts_from_existing_sections -q
```

Expected: FAIL because builder does not derive or attach risk prompts yet.

- [ ] **Step 3: Integrate service into builder**

In `app_module/decision_desk_service.py`, import:

```python
from app_module.decision_desk_risk_prompt_service import DecisionDeskRiskPromptService
from app_module.decision_desk_dtos import DecisionDeskRiskPromptSummary
```

Add constructor argument:

```python
risk_prompt_service: DecisionDeskRiskPromptService | None = None,
```

Set:

```python
self.risk_prompt_service = risk_prompt_service or DecisionDeskRiskPromptService()
```

In `build_snapshot()`, after `portfolio_alerts = ...`, add:

```python
risk_prompts = self.risk_prompt_service.build_summary(
    as_of_date=as_of_date,
    market_regime=market_regime,
    market_breadth=market_breadth,
    sector_rotation=sector_rotation,
    relative_strength_liquidity=relative_strength_liquidity,
    watchlist_triggers=watchlist_triggers,
    portfolio_alerts=portfolio_alerts,
)
```

Add `risk_prompts` to `sections`, `DecisionDeskSnapshot(...)`, `_compute_overall_quality()` tuple typing, and `_collect_snapshot_warnings()` tuple typing.

Add this section prefix in `_collect_snapshot_warnings()`:

```python
("risk_prompts", risk_prompts.warnings),
```

- [ ] **Step 4: Run builder tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```powershell
git add app_module\decision_desk_service.py tests\test_decision_desk_service.py
git commit -m "feat: attach risk prompts to decision desk snapshots"
```

---

### Task 4: Render Risk Prompts in Daily Decision Desk UI

**Files:**
- Modify: `ui_qt/views/decision_desk_view.py`
- Modify: `tests/test_ui_qt_decision_desk_view.py`

- [ ] **Step 1: Add failing UI render test**

Append this test to `tests/test_ui_qt_decision_desk_view.py`:

```python
def test_decision_desk_view_renders_risk_prompts(qtbot):
    snapshot = make_snapshot()
    prompt = DecisionDeskRiskPrompt(
        category="liquidity",
        severity="warning",
        source="relative_strength_liquidity",
        code="1101",
        title="低流動性",
        reason="1101 低於平均成交金額門檻",
        action_hint="檢查可成交金額",
    )
    snapshot = replace(
        snapshot,
        risk_prompts=DecisionDeskRiskPromptSummary(
            as_of_date=snapshot.as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            prompts=(prompt,),
        ),
    )
    view = DecisionDeskView(decision_desk_builder=FakeBuilder(snapshot))
    qtbot.addWidget(view)

    assert "低流動性" in view.risk_prompts_value.text()
    assert "1101" in view.risk_prompts_value.text()
```

Add imports:

```python
from dataclasses import replace
from app_module.decision_desk_dtos import DecisionDeskRiskPrompt, DecisionDeskRiskPromptSummary
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_view.py::test_decision_desk_view_renders_risk_prompts -q
```

Expected: FAIL because view labels do not exist.

- [ ] **Step 3: Add UI labels and rendering**

In `_setup_ui()`, add:

```python
self.risk_prompts_status = QLabel("")
self.risk_prompts_value = QLabel("")
self.risk_prompts_value.setWordWrap(True)
```

Add a section row after Portfolio Alert:

```python
sections_layout.addWidget(self._make_section_row("Why Not / 風險提示", self.risk_prompts_status, self.risk_prompts_value))
```

In `_render_snapshot()`, add:

```python
self.risk_prompts_status.setText(f"品質：{self._quality_label(snapshot.risk_prompts.quality)}")
self.risk_prompts_value.setText(self._format_risk_prompts(snapshot.risk_prompts.prompts))
```

Add helper:

```python
@staticmethod
def _format_risk_prompts(prompts) -> str:
    if not prompts:
        return "無"
    parts = []
    for prompt in prompts[:5]:
        code = f"{prompt.code} " if prompt.code else ""
        parts.append(f"[{prompt.severity}] {code}{prompt.title}：{prompt.action_hint}")
    return "；".join(parts)
```

In `_display_exception_snapshot()`, add degraded `_EmptySection` for `risk_prompts`.

In `_collect_warnings()`, add:

```python
("Why Not / 風險提示", snapshot.risk_prompts.warnings),
```

In `_EmptySection.__init__()`, add:

```python
self.prompts: tuple[object, ...] = ()
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
git commit -m "feat: render decision desk risk prompts"
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

In `docs/00_core/PROJECT_SNAPSHOT.md`, update the Daily Decision Desk current-state paragraph to include:

```markdown
Why Not / 風險提示 v1 由 `DecisionDeskRiskPromptService` 從既有 section DTO 的 quality、warnings、低流動性、相對弱勢、watchlist risk alert 與 portfolio alert 推導，不在 UI 層重算 scoring、screening、portfolio 或 liquidity。
```

- [ ] **Step 2: Update 6M Roadmap**

In `docs/00_core/ROADMAP_6M_ENGINEERING.md`, update Month 4 acceptance notes and immediate todos:

```markdown
- Why Not / 風險提示 v1 已接 Daily Decision Desk，由既有 section DTO 推導可行動風險提示；下一步聚焦 Portfolio Alert 來源差異歸因。
```

- [ ] **Step 3: Update architecture**

In `docs/01_architecture/system_architecture.md`, update Daily Decision Desk architecture:

```markdown
`DecisionDeskRiskPromptService` 是純 application service，只讀取 section DTO，不讀取 raw data、不查 SQLite、不重算策略分數；它將低流動性、弱勢、Watchlist risk alert、Portfolio Alert 與資料品質缺口轉為 `DecisionDeskRiskPromptSummary`。
```

- [ ] **Step 4: Update Application Manual**

In `docs/07_guides/APPLICATION_MANUAL.md`, add to section 8:

```markdown
Why Not / 風險提示 v1 會把各 section 已揭露的低流動性、相對弱勢、watchlist risk alert、portfolio alert 與資料品質缺口整理成提示。這些提示不是自動買賣建議，而是提醒使用者在研究、加入候選或檢查持倉前應先看的風險。
```

- [ ] **Step 5: Update Documentation Index**

Add this row to `docs/00_core/DOCUMENTATION_INDEX.md`:

```markdown
| [2026-06-15-decision-desk-risk-prompt-bridge.md](../superpowers/plans/2026-06-15-decision-desk-risk-prompt-bridge.md) | Daily Decision Desk Why Not / 風險提示橋接 v1 實作計畫，將既有 section DTO 的低流動性、弱勢、watchlist risk alert、portfolio alert 與品質缺口整理成可行動提示。 |
```

Add changelog entry:

```markdown
- 2026-06-15：補列 Daily Decision Desk Why Not / 風險提示橋接 v1 實作計畫至 Superpowers plans 索引。
```

- [ ] **Step 6: Commit Task 5**

```powershell
git add docs\00_core\PROJECT_SNAPSHOT.md docs\00_core\ROADMAP_6M_ENGINEERING.md docs\01_architecture\system_architecture.md docs\07_guides\APPLICATION_MANUAL.md docs\00_core\DOCUMENTATION_INDEX.md
git commit -m "docs: document decision desk risk prompt bridge"
```

---

### Task 6: Final Verification Gate

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_risk_prompt_service.py tests\test_decision_desk_service.py tests\test_ui_qt_decision_desk_view.py tests\test_ui_qt_decision_desk_main_integration.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run UI workbench tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 3: Run Update Tab QA**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

Expected: `21 passed, 0 failed, 4 skipped`.

- [ ] **Step 4: Run mypy**

Run:

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

Expected: `Success: no issues found`.

- [ ] **Step 5: Run financial float boundary check**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

Expected: exit code 0 with no violations.

- [ ] **Step 6: Run look-ahead bias check**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\check_look_ahead_bias.py
```

Expected: exit code 0 with no violations.

- [ ] **Step 7: Run py_compile**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\decision_desk_dtos.py app_module\decision_desk_service.py app_module\decision_desk_risk_prompt_service.py ui_qt\views\decision_desk_view.py
```

Expected: exit code 0.

---

## Self-Review

- Spec coverage: Covers Why Not / risk prompt bridge, Daily Decision Desk DTO integration, UI rendering, docs, quality / warnings, and explicit no-recompute boundary.
- Placeholder scan: No TBD / TODO placeholders are present.
- Type consistency: `DecisionDeskRiskPrompt`, `DecisionDeskRiskPromptSummary`, `DecisionDeskRiskPromptService.build_summary()`, `risk_prompts`, and UI label names are consistent across tasks.
- Scope check: This plan intentionally does not implement Portfolio Alert source attribution; that should be a separate follow-up plan after risk prompts land.

