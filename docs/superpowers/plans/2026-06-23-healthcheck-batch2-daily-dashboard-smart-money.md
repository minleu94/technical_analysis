# Healthcheck Batch 2 Daily Dashboard / Smart Money Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve Healthcheck Batch 2 by upgrading Daily Decision Desk to an answer-first dashboard and adding a governed Smart Money semantic layer for 5 / 20 / 60 day chip diagnostics.

**Architecture:** Add Smart Money semantics in application DTO/service boundaries, not in Qt UI. Daily Decision Desk consumes service snapshots and renders action level, sector focus, stock focus, and drill-down controls. Smart Money table renders precomputed semantic DTOs and diagnostics; UI does not recompute concentration, price percentile, or risk labels.

**Tech Stack:** Python 3.12, PySide6, pytest, mypy, SQLite read-only query providers, existing `BrokerFlowService`, existing `DecisionDeskSnapshotBuilder`, Midnight Analyst widgets, repository docs under `docs/`.

---

## Scope Boundary

Implement in this plan:

- `DECISION-ISSUE-002`: Daily Decision Desk answer-first visual hierarchy and main conclusion.
- `DECISION-ISSUE-003`: Dashboard-style market / sector / stock cards with drill-down to Market Watch / Smart Money.
- `MARKET-ISSUE-006`: Replace unclear Smart Money micro chart dependency with clearer 5 / 20 / 60 day summaries and diagnostics.
- `MARKET-ISSUE-007`: Add Smart Money semantic states: `初轉買`, `買超延續`, `初轉賣`, `賣超延續`, `高檔出貨疑慮`, `分點集中異常`.
- Healthcheck and Manual updates for the Batch 2 visible behavior.

Do not implement in this plan:

- Recommendation Profile / Regime lifecycle (`RECOMMEND-ISSUE-001` to `004`, `008`).
- Performance investigations (`MARKET-ISSUE-002`, `MARKET-ISSUE-003`, `UPDATE-ISSUE-013`, `UPDATE-ISSUE-014`, `BACKTEST-ISSUE-011` to `013`).
- Strategy scoring changes, recommendation scoring changes, auto-trading, auto-position changes, data rebuilds, or raw CSV mutations.
- Full redesign of all Market Watch subtabs. Batch 2 only touches Daily Decision Desk and Smart Money semantics needed by the dashboard.

## Preconditions

- Current branch: `codex/healthcheck-batch1-direct-fixes`.
- Latest known Batch 1 commit: `0e9a29a fix: resolve healthcheck batch 1 direct issues`.
- `git status --short` must be clean before implementation starts, or any dirty files must be explicitly protected and excluded from Batch 2 edits.
- Read before implementation:
  - `docs/agents/README.md`
  - `docs/agents/shared_context.md`
  - `docs/agents/git_exclusions.md`
  - `docs/00_core/PROJECT_SNAPSHOT.md`
  - `docs/00_core/DEVELOPMENT_ROADMAP.md`
  - `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - `docs/01_architecture/system_architecture.md`
  - `docs/07_guides/APPLICATION_MANUAL.md`
  - `docs/superpowers/specs/2026-06-23-healthcheck-issue-resolution-design.md`
  - `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`

## Look-Ahead / Numeric Boundary Self-Check

- Smart Money event windows must only use broker flow events with `event.date <= decision_date`.
- 5 / 20 / 60 windows must be selected from distinct observed event dates on or before the decision date. Do not use future rows to fill a window.
- Price position for `高檔出貨疑慮` must query only prices with `日期 <= decision_date`, sorted descending, limited to the latest 60 trading observations.
- Concentration uses quantity (`net_qty`, lots / share-equivalent quantity) only. Thousand-dollar amount is not allowed as the concentration metric.
- `unavailable` quantity rows are excluded from concentration numerator and denominator, and counts are exposed in quality flags.
- Use integer basis points for percentages and confidence. Do not add naked `float` to core Smart Money semantic calculations. UI display conversion may format integers into percentages.

## File Map

- Create: `app_module/dtos/smart_money_semantic_dtos.py`
  - Semantic DTOs for Smart Money window stats, per-stock semantic summary, and dashboard-level summary.

- Create: `app_module/smart_money_semantic_service.py`
  - Application service for 5 / 20 / 60 day chip diagnostics, semantic state classification, quantity concentration, quality counts, and price-position risk flags.

- Create: `app_module/decision_desk_dashboard_service.py`
  - Composes answer-first Daily Decision action level, sector focus, and stock focus from existing section DTOs plus optional Smart Money semantic summary.

- Modify: `app_module/decision_desk_dtos.py`
  - Add optional dashboard DTOs to `DecisionDeskSnapshot` while keeping existing fields backward compatible.

- Modify: `app_module/decision_desk_service.py`
  - Inject `DecisionDeskDashboardComposer` and optional Smart Money semantic dashboard provider.

- Modify: `app_module/broker_flow_service.py`
  - Add a public read-only event accessor and optional semantic service hook. Do not expose raw mutation.

- Modify: `ui_qt/views/decision_desk_view.py`
  - Render answer-first top conclusion, sector focus cards, stock focus cards, and drill-down buttons.

- Modify: `ui_qt/views/smart_money/smart_money_flow_view.py`
  - Request semantic summaries and pass them to the table model; show empty-state text when no semantic data exists.

- Modify: `ui_qt/views/smart_money/terminal_table_model.py`
  - Add semantic columns / tooltips from DTOs. Keep existing sorting working.

- Modify: `ui_qt/main.py`
  - Instantiate `SmartMoneySemanticService` and pass the Smart Money drill-down callback to `DecisionDeskView`.

- Test: `tests/test_smart_money_semantic_service.py`
- Test: `tests/test_decision_desk_dashboard_service.py`
- Test: `tests/test_decision_desk_service.py`
- Test: `tests/test_ui_qt_decision_desk_view.py`
- Test: `tests/test_ui_qt_decision_desk_main_integration.py`
- Test: `tests/test_ui_qt_smart_money_flow_view.py`
- Test: `tests/test_decision_desk_ui_contract.py`

- Docs:
  - Modify: `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`
  - Modify: `docs/07_guides/APPLICATION_MANUAL.md`
  - Modify if architecture text changes materially: `docs/01_architecture/system_architecture.md`
  - Modify if a new plan entry must be indexed: `docs/00_core/DOCUMENTATION_INDEX.md`

## Rollback List

| File path | Change type | Summary | Rollback method | Risk |
|---|---|---|---|---|
| `app_module/dtos/smart_money_semantic_dtos.py` | Create | Smart Money semantic DTOs | Delete file | Low; no existing dependency before Batch 2 |
| `app_module/smart_money_semantic_service.py` | Create | Smart Money semantic service | Delete file | Low; remove injection sites too |
| `app_module/decision_desk_dashboard_service.py` | Create | Daily dashboard composer | Delete file | Low; remove injection sites too |
| `app_module/decision_desk_dtos.py` | Modify | Optional dashboard fields | `git checkout HEAD -- app_module/decision_desk_dtos.py` | Medium; snapshot serialization tests must be rerun |
| `app_module/decision_desk_service.py` | Modify | Dashboard composer integration | `git checkout HEAD -- app_module/decision_desk_service.py` | Medium; Daily Decision Desk reverts to v1 |
| `app_module/broker_flow_service.py` | Modify | Public read-only event accessor | `git checkout HEAD -- app_module/broker_flow_service.py` | Low; no data writes |
| `ui_qt/views/decision_desk_view.py` | Modify | Answer-first dashboard UI | `git checkout HEAD -- ui_qt/views/decision_desk_view.py` | Medium; UI reverts to v1 |
| `ui_qt/views/smart_money/smart_money_flow_view.py` | Modify | Semantic summary rendering | `git checkout HEAD -- ui_qt/views/smart_money/smart_money_flow_view.py` | Medium; Smart Money reverts to old display |
| `ui_qt/views/smart_money/terminal_table_model.py` | Modify | Semantic columns and tooltips | `git checkout HEAD -- ui_qt/views/smart_money/terminal_table_model.py` | Medium; Smart Money table contract changes |
| `ui_qt/main.py` | Modify | Service wiring and drill-down callback | `git checkout HEAD -- ui_qt/main.py` | Medium; app integration must be retested |
| `tests/...` | Create/Modify | Batch 2 regression tests | Delete or checkout test files | Low |
| `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md` | Modify | Mark Batch 2 items fixed pending verification | `git checkout HEAD -- docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md` | Low |
| `docs/07_guides/APPLICATION_MANUAL.md` | Modify | Manual updates for Batch 2 | `git checkout HEAD -- docs/07_guides/APPLICATION_MANUAL.md` | Low |

## Implementation Tasks

### Task 1: Baseline and Dirty-Change Guard

**Files:**
- No code edits.

- [ ] **Step 1: Confirm branch and dirty state**

Run:

```powershell
git status --short --branch
git log --oneline --max-count=5
```

Expected:

```text
## codex/healthcheck-batch1-direct-fixes...origin/codex/healthcheck-batch1-direct-fixes
0e9a29a fix: resolve healthcheck batch 1 direct issues
```

If `git status --short` lists files, inspect them before editing and do not overwrite unrelated changes.

- [ ] **Step 2: Capture current issue rows**

Run:

```powershell
rg -n "DECISION-ISSUE-00[2-3]|MARKET-ISSUE-00[6-7]|PORTFOLIO-ISSUE-00[6-7]" docs\06_qa\FULL_APP_HEALTHCHECK_2026_06_16.md
```

Expected: Batch 2 decision / market issues are still `已記錄` or `待設計`; Batch 1 portfolio issues are `已修正待驗證`.

- [ ] **Step 3: Run baseline focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_decision_desk_service.py tests/test_ui_qt_decision_desk_view.py tests/test_ui_qt_decision_desk_main_integration.py tests/test_ui_qt_smart_money_flow_view.py tests/test_broker_flow_units.py -q -o addopts=
```

Expected after implementation: all pass. If baseline fails before edits, record the failing tests in the handoff and do not fix unrelated failures.

### Task 2: Smart Money Semantic DTOs and Service Tests

**Files:**
- Create: `tests/test_smart_money_semantic_service.py`
- Create: `app_module/dtos/smart_money_semantic_dtos.py`
- Create: `app_module/smart_money_semantic_service.py`
- Modify: `app_module/broker_flow_service.py`

- [ ] **Step 1: Write failing semantic service tests**

Add `tests/test_smart_money_semantic_service.py`:

```python
from datetime import date, timedelta

from app_module.dtos.broker_flow_dtos import BrokerFlowEvent
from app_module.smart_money_semantic_service import SmartMoneySemanticService


class FakeBrokerFlowService:
    def __init__(self, events):
        self.events = events

    def get_events(self, force_reload=False):
        return list(self.events)


class FakePriceProvider:
    def __init__(self, prices):
        self.prices = prices

    def load_recent_prices(self, stock_code, decision_date, limit):
        rows = [
            row for row in self.prices.get(stock_code, [])
            if row[0] <= decision_date
        ]
        return sorted(rows, key=lambda item: item[0], reverse=True)[:limit]


def _event(day, branch, code, net, quality="observed"):
    return BrokerFlowEvent(
        date=day.isoformat(),
        branch_system_key=branch,
        branch_display_name=branch,
        stock_code=code,
        stock_name=f"股票{code}",
        buy_qty=max(net, 0) if quality != "unavailable" else None,
        sell_qty=abs(min(net, 0)) if quality != "unavailable" else None,
        net_qty=net if quality != "unavailable" else None,
        lots_quality=quality,
        lots_available=quality != "unavailable",
        has_estimated_lots=quality == "estimated",
        lots_observed=quality == "observed",
    )


def test_semantic_service_classifies_initial_buy_without_future_events():
    decision = date(2026, 6, 20)
    events = [
        _event(decision - timedelta(days=idx), "A", "2330", 120)
        for idx in range(5)
    ]
    events += [
        _event(decision - timedelta(days=idx), "B", "2330", -80)
        for idx in range(5, 20)
    ]
    events.append(_event(decision + timedelta(days=1), "C", "2330", -9999))
    service = SmartMoneySemanticService(FakeBrokerFlowService(events), price_provider=FakePriceProvider({}))

    summary = service.build_stock_semantics("2330", decision)

    assert summary.primary_state == "初轉買"
    assert summary.window_5.net_qty == 600
    assert summary.window_20.net_qty == -600
    assert all("9999" not in reason for reason in summary.reasons)


def test_semantic_service_uses_quantity_concentration_and_excludes_unavailable():
    decision = date(2026, 6, 20)
    events = [
        _event(decision, "A", "2330", 700),
        _event(decision, "B", "2330", 200),
        _event(decision, "C", "2330", 100, quality="estimated"),
        _event(decision, "D", "2330", 10000, quality="unavailable"),
    ]
    service = SmartMoneySemanticService(FakeBrokerFlowService(events), price_provider=FakePriceProvider({}))

    summary = service.build_stock_semantics("2330", decision)

    assert summary.window_5.top_concentration_bp == 7000
    assert summary.window_5.observed_count == 2
    assert summary.window_5.estimated_count == 1
    assert summary.window_5.unavailable_count == 1
    assert summary.window_5.usable_coverage_bp == 7500
    assert "分點集中異常" in summary.semantic_flags


def test_semantic_service_high_position_distribution_is_no_lookahead():
    decision = date(2026, 6, 20)
    prices = {
        "2330": [(decision - timedelta(days=idx), 100 + idx) for idx in range(60)]
        + [(decision + timedelta(days=1), 999)]
    }
    events = [_event(decision, "A", "2330", -500), _event(decision - timedelta(days=1), "A", "2330", -300)]
    service = SmartMoneySemanticService(FakeBrokerFlowService(events), price_provider=FakePriceProvider(prices))

    summary = service.build_stock_semantics("2330", decision)

    assert summary.price_position_bp is not None
    assert summary.price_position_bp < 10000
    assert "999" not in " ".join(summary.reasons)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_smart_money_semantic_service.py -q -o addopts=
```

Expected: fails because DTOs and service do not exist.

- [ ] **Step 3: Add Smart Money semantic DTOs**

Create `app_module/dtos/smart_money_semantic_dtos.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SmartMoneyWindowStats:
    window_days: int
    net_qty: int
    buy_qty: int
    sell_qty: int
    direction: str
    continuous_buy_days: int
    continuous_sell_days: int
    top_n: int
    top_concentration_bp: int | None
    observed_count: int
    estimated_count: int
    unavailable_count: int
    usable_coverage_bp: int


@dataclass(frozen=True)
class SmartMoneySemanticSummary:
    stock_code: str
    stock_name: str
    decision_date: date
    primary_state: str
    semantic_flags: tuple[str, ...]
    confidence_bp: int
    quality: str
    warnings: tuple[str, ...]
    window_5: SmartMoneyWindowStats
    window_20: SmartMoneyWindowStats
    window_60: SmartMoneyWindowStats
    price_position_bp: int | None = None
    distance_to_60d_high_bp: int | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SmartMoneyDashboardSummary:
    decision_date: date
    priority_summaries: tuple[SmartMoneySemanticSummary, ...]
    risk_summaries: tuple[SmartMoneySemanticSummary, ...]
    quality: str
    warnings: tuple[str, ...] = ()
```

- [ ] **Step 4: Add public read-only event accessor**

Modify `app_module/broker_flow_service.py`:

```python
    def get_events(self, force_reload: bool = False) -> list[BrokerFlowEvent]:
        """回傳唯讀用途的分點事件快照；不得由呼叫端修改正式資料。"""
        return list(self._load_data(force_reload=force_reload))
```

- [ ] **Step 5: Add semantic service implementation**

Create `app_module/smart_money_semantic_service.py` with these public signatures:

```python
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol

from app_module.dtos.broker_flow_dtos import BrokerFlowEvent
from app_module.dtos.smart_money_semantic_dtos import (
    SmartMoneyDashboardSummary,
    SmartMoneySemanticSummary,
    SmartMoneyWindowStats,
)


class BrokerFlowEventProvider(Protocol):
    def get_events(self, force_reload: bool = False) -> list[BrokerFlowEvent]: ...


class SmartMoneyPriceProvider(Protocol):
    def load_recent_prices(self, stock_code: str, decision_date: date, limit: int) -> list[tuple[date, Decimal]]: ...
```

Implement helpers:

```python
def _parse_event_date(raw: str) -> date:
    text = str(raw).replace("/", "-")
    return datetime.strptime(text, "%Y-%m-%d").date()


def _bp(numerator: int, denominator: int) -> int | None:
    if denominator <= 0:
        return None
    value = (Decimal(numerator) * Decimal(10000) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(value)
```

Core service behavior:

```python
class SmartMoneySemanticService:
    def __init__(self, broker_flow_provider: BrokerFlowEventProvider, *, price_provider: SmartMoneyPriceProvider | None = None):
        self.broker_flow_provider = broker_flow_provider
        self.price_provider = price_provider

    def build_stock_semantics(self, stock_code: str, decision_date: date) -> SmartMoneySemanticSummary:
        events = self._events_for_stock(stock_code, decision_date)
        stock_name = next((event.stock_name for event in events if event.stock_name), stock_code)
        w5 = self._window_stats(events, decision_date, 5, top_n=3)
        w20 = self._window_stats(events, decision_date, 20, top_n=5)
        w60 = self._window_stats(events, decision_date, 60, top_n=5)
        price_position_bp, distance_to_high_bp = self._price_position(stock_code, decision_date)
        primary_state, flags = self._classify(w5, w20, w60, price_position_bp, distance_to_high_bp)
        warnings = self._quality_warnings(w5, w20, w60)
        quality = "degraded" if warnings else "observed"
        confidence_bp = min(w5.usable_coverage_bp, w20.usable_coverage_bp, w60.usable_coverage_bp)
        reasons = self._reasons(primary_state, flags, w5, w20, w60, price_position_bp, distance_to_high_bp)
        return SmartMoneySemanticSummary(
            stock_code=str(stock_code),
            stock_name=stock_name,
            decision_date=decision_date,
            primary_state=primary_state,
            semantic_flags=tuple(flags),
            confidence_bp=confidence_bp,
            quality=quality,
            warnings=tuple(warnings),
            window_5=w5,
            window_20=w20,
            window_60=w60,
            price_position_bp=price_position_bp,
            distance_to_60d_high_bp=distance_to_high_bp,
            reasons=tuple(reasons),
        )

    def build_dashboard_summary(self, decision_date: date, stock_codes: tuple[str, ...] = ()) -> SmartMoneyDashboardSummary:
        codes = stock_codes or tuple(sorted({event.stock_code for event in self._events_for_stock(None, decision_date)}))
        summaries = tuple(self.build_stock_semantics(code, decision_date) for code in codes)
        priority = tuple(item for item in summaries if item.primary_state in {"初轉買", "買超延續"})[:10]
        risk = tuple(item for item in summaries if item.primary_state in {"初轉賣", "賣超延續"} or "高檔出貨疑慮" in item.semantic_flags)[:10]
        warnings = tuple(w for item in summaries for w in item.warnings)
        quality = "degraded" if warnings else "observed"
        return SmartMoneyDashboardSummary(decision_date=decision_date, priority_summaries=priority, risk_summaries=risk, quality=quality, warnings=warnings)
```

Classification rules:

```python
    def _classify(self, w5, w20, w60, price_position_bp, distance_to_high_bp):
        flags: list[str] = []
        prior_20_net = w20.net_qty - w5.net_qty
        if w5.net_qty > 0 and prior_20_net <= 0:
            primary = "初轉買"
        elif w5.net_qty > 0 and w20.net_qty > 0:
            primary = "買超延續"
        elif w5.net_qty < 0 and prior_20_net >= 0:
            primary = "初轉賣"
        elif w5.net_qty < 0 and w20.net_qty < 0:
            primary = "賣超延續"
        else:
            primary = "中性觀察"
        same_direction = w5.direction == w20.direction and w5.direction in {"buy", "sell"}
        if same_direction and (w5.top_concentration_bp or 0) >= 6000 and (w20.top_concentration_bp or 0) >= 6000:
            flags.append("分點集中異常")
        if (
            primary in {"初轉賣", "賣超延續"}
            and (price_position_bp or 0) >= 8000
            and distance_to_high_bp is not None
            and distance_to_high_bp <= 1000
        ):
            flags.append("高檔出貨疑慮")
        return primary, flags
```

- [ ] **Step 6: Add SQLite price provider**

In the same service file, add:

```python
class SQLiteSmartMoneyPriceProvider:
    def __init__(self, db_file):
        self.db_file = db_file

    def load_recent_prices(self, stock_code: str, decision_date: date, limit: int) -> list[tuple[date, Decimal]]:
        from data_module.db_manager import DBManager
        from data_module.config import TWStockConfig

        config = TWStockConfig()
        config.db_file = self.db_file
        db = DBManager(config)
        df = db.execute_query(
            "SELECT 日期, 收盤價 FROM daily_prices WHERE 證券代號 = ? AND 日期 <= ? ORDER BY 日期 DESC LIMIT ?",
            (str(stock_code), decision_date.strftime("%Y%m%d"), int(limit)),
        )
        rows: list[tuple[date, Decimal]] = []
        for _, row in df.iterrows():
            raw_date = str(row["日期"])
            parsed = datetime.strptime(raw_date.replace("-", ""), "%Y%m%d").date()
            rows.append((parsed, Decimal(str(row["收盤價"]))))
        return rows
```

If `TWStockConfig.db_file` cannot be assigned in this repo version, follow the existing provider style in `market_breadth_service.py` and use the same read-only DB helper pattern.

- [ ] **Step 7: Run semantic tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_smart_money_semantic_service.py tests/test_broker_flow_units.py -q -o addopts=
```

Expected: pass.

### Task 3: Daily Dashboard Composer Tests and DTO Integration

**Files:**
- Create: `tests/test_decision_desk_dashboard_service.py`
- Create: `app_module/decision_desk_dashboard_service.py`
- Modify: `app_module/decision_desk_dtos.py`
- Modify: `app_module/decision_desk_service.py`
- Modify: `tests/test_decision_desk_service.py`

- [ ] **Step 1: Write failing composer tests**

Add `tests/test_decision_desk_dashboard_service.py`:

```python
from datetime import date

from app_module.decision_desk_dashboard_service import DecisionDeskDashboardComposer
from app_module.decision_desk_dtos import DecisionDeskQuality, MarketBreadthSummary, MarketRegimeSummary, SectorRotationSummary, RelativeStrengthLiquiditySummary, WatchlistTriggerSummary, PortfolioAlertSummary
from app_module.dtos.smart_money_semantic_dtos import SmartMoneyDashboardSummary, SmartMoneySemanticSummary, SmartMoneyWindowStats


def _window(net_qty):
    return SmartMoneyWindowStats(5, net_qty, max(net_qty, 0), abs(min(net_qty, 0)), "buy" if net_qty > 0 else "sell", 2, 0, 3, 7000, 3, 0, 0, 10000)


def _semantic(code, state):
    day = date(2026, 6, 20)
    return SmartMoneySemanticSummary(code, f"股票{code}", day, state, (), 10000, "observed", (), _window(500), _window(1000), _window(2000), reasons=(state,))


def test_dashboard_composer_outputs_answer_first_action_and_sector_focus():
    day = date(2026, 6, 20)
    composer = DecisionDeskDashboardComposer()
    action, sector_focus, stock_focus = composer.compose(
        as_of_date=day,
        market_regime=MarketRegimeSummary(day, DecisionDeskQuality.OBSERVED, (), regime_label="risk-on", regime_score=76, regime_confidence=8600),
        market_breadth=MarketBreadthSummary(day, DecisionDeskQuality.OBSERVED, (), breadth_ratio_bp=6200, advancing=700, declining=300),
        sector_rotation=SectorRotationSummary(day, DecisionDeskQuality.OBSERVED, (), leading_sector="半導體", trailing_sector="金融", rotation_intensity_bp=1800),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(day, DecisionDeskQuality.OBSERVED, (), top_strength_codes=("2330",), weak_strength_codes=("1101",)),
        watchlist_triggers=WatchlistTriggerSummary(day, DecisionDeskQuality.OBSERVED, (), trigger_count=1, triggered_codes=("2330",)),
        portfolio_alerts=PortfolioAlertSummary(day, DecisionDeskQuality.OBSERVED, (), alert_count=0, alert_codes=()),
        smart_money=SmartMoneyDashboardSummary(day, (_semantic("2330", "初轉買"),), (_semantic("1101", "賣超延續"),), "observed"),
    )

    assert action.action_level == "積極研究"
    assert "研究模式" in action.research_mode_note
    assert sector_focus.priority_sectors[0].sector_name == "半導體"
    assert sector_focus.risk_sectors[0].sector_name == "金融"
    assert stock_focus.priority_stocks[0].stock_code == "2330"
    assert stock_focus.risk_stocks[0].stock_code == "1101"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_decision_desk_dashboard_service.py -q -o addopts=
```

Expected: fails because composer and DTOs do not exist.

- [ ] **Step 3: Add dashboard DTOs**

In `app_module/decision_desk_dtos.py`, add:

```python
@dataclass(frozen=True)
class DecisionDeskActionSummary:
    action_level: str
    confidence_bp: int
    headline: str
    supporting_reasons: tuple[str, ...]
    research_mode_note: str = "這是研究模式，不是交易建議。"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_level": self.action_level,
            "confidence_bp": self.confidence_bp,
            "headline": self.headline,
            "supporting_reasons": list(self.supporting_reasons),
            "research_mode_note": self.research_mode_note,
        }


@dataclass(frozen=True)
class DecisionDeskSectorCard:
    sector_name: str
    reason: str
    drilldown_target: str

    def to_dict(self) -> dict[str, str]:
        return {"sector_name": self.sector_name, "reason": self.reason, "drilldown_target": self.drilldown_target}


@dataclass(frozen=True)
class DecisionDeskSectorFocusSummary:
    priority_sectors: tuple[DecisionDeskSectorCard, ...] = ()
    risk_sectors: tuple[DecisionDeskSectorCard, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority_sectors": [item.to_dict() for item in self.priority_sectors],
            "risk_sectors": [item.to_dict() for item in self.risk_sectors],
        }


@dataclass(frozen=True)
class DecisionDeskStockCard:
    stock_code: str
    stock_name: str
    reason: str
    semantic_state: str
    drilldown_target: str = "smart_money"

    def to_dict(self) -> dict[str, str]:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "reason": self.reason,
            "semantic_state": self.semantic_state,
            "drilldown_target": self.drilldown_target,
        }


@dataclass(frozen=True)
class DecisionDeskStockFocusSummary:
    priority_stocks: tuple[DecisionDeskStockCard, ...] = ()
    risk_stocks: tuple[DecisionDeskStockCard, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority_stocks": [item.to_dict() for item in self.priority_stocks],
            "risk_stocks": [item.to_dict() for item in self.risk_stocks],
        }
```

Extend `DecisionDeskSnapshot` with defaulted fields after `warnings`:

```python
    action_summary: DecisionDeskActionSummary | None = None
    sector_focus: DecisionDeskSectorFocusSummary | None = None
    stock_focus: DecisionDeskStockFocusSummary | None = None
```

Extend `to_dict()`:

```python
            "action_summary": self.action_summary.to_dict() if self.action_summary else None,
            "sector_focus": self.sector_focus.to_dict() if self.sector_focus else None,
            "stock_focus": self.stock_focus.to_dict() if self.stock_focus else None,
```

- [ ] **Step 4: Add composer implementation**

Create `app_module/decision_desk_dashboard_service.py`:

```python
from __future__ import annotations

from datetime import date

from app_module.decision_desk_dtos import (
    DecisionDeskActionSummary,
    DecisionDeskSectorCard,
    DecisionDeskSectorFocusSummary,
    DecisionDeskStockCard,
    DecisionDeskStockFocusSummary,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    RelativeStrengthLiquiditySummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
)
from app_module.dtos.smart_money_semantic_dtos import SmartMoneyDashboardSummary


class DecisionDeskDashboardComposer:
    def compose(
        self,
        *,
        as_of_date: date,
        market_regime: MarketRegimeSummary,
        market_breadth: MarketBreadthSummary,
        sector_rotation: SectorRotationSummary,
        relative_strength_liquidity: RelativeStrengthLiquiditySummary,
        watchlist_triggers: WatchlistTriggerSummary,
        portfolio_alerts: PortfolioAlertSummary,
        smart_money: SmartMoneyDashboardSummary | None = None,
    ) -> tuple[DecisionDeskActionSummary, DecisionDeskSectorFocusSummary, DecisionDeskStockFocusSummary]:
        action = self._action_summary(market_regime, market_breadth)
        sectors = self._sector_focus(sector_rotation)
        stocks = self._stock_focus(relative_strength_liquidity, watchlist_triggers, portfolio_alerts, smart_money)
        return action, sectors, stocks
```

Use deterministic action rules:

```python
    def _action_summary(self, market_regime, market_breadth):
        regime = str(market_regime.regime_label or "").lower()
        confidence = int(market_regime.regime_confidence or 0)
        breadth = int(market_breadth.breadth_ratio_bp or 0)
        if ("risk-on" in regime or "多" in regime) and breadth >= 5500 and confidence >= 7000:
            level = "積極研究"
        elif ("risk-off" in regime or "bear" in regime or "空" in regime) and breadth <= 4500:
            level = "保守觀察"
        elif breadth <= 3500:
            level = "暫停新進場"
        else:
            level = "正常研究"
        return DecisionDeskActionSummary(
            action_level=level,
            confidence_bp=min(max(confidence, 0), 10000),
            headline=f"今日主結論：{level}",
            supporting_reasons=(f"市場狀態 {market_regime.regime_label or '未定義'}", f"市況廣度 {breadth} bp"),
        )
```

Sector and stock focus rules:

```python
    def _sector_focus(self, sector_rotation):
        priority = ()
        risk = ()
        if sector_rotation.leading_sector:
            priority = (DecisionDeskSectorCard(sector_rotation.leading_sector, "產業輪動領先", "market_sector_rotation"),)
        if sector_rotation.trailing_sector:
            risk = (DecisionDeskSectorCard(sector_rotation.trailing_sector, "產業輪動落後", "market_sector_rotation"),)
        return DecisionDeskSectorFocusSummary(priority_sectors=priority, risk_sectors=risk)

    def _stock_focus(self, relative_strength_liquidity, watchlist_triggers, portfolio_alerts, smart_money):
        priority: list[DecisionDeskStockCard] = []
        risk: list[DecisionDeskStockCard] = []
        if smart_money is not None:
            for item in smart_money.priority_summaries[:5]:
                priority.append(DecisionDeskStockCard(item.stock_code, item.stock_name, "Smart Money " + item.primary_state, item.primary_state))
            for item in smart_money.risk_summaries[:5]:
                risk.append(DecisionDeskStockCard(item.stock_code, item.stock_name, "Smart Money " + item.primary_state, item.primary_state))
        for code in relative_strength_liquidity.top_strength_codes[:5]:
            if all(card.stock_code != code for card in priority):
                priority.append(DecisionDeskStockCard(code, code, "20 日相對強勢", "相對強勢"))
        for code in relative_strength_liquidity.weak_strength_codes[:5]:
            if all(card.stock_code != code for card in risk):
                risk.append(DecisionDeskStockCard(code, code, "20 日相對弱勢", "相對弱勢"))
        for code in portfolio_alerts.alert_codes[:5]:
            if all(card.stock_code != code for card in risk):
                risk.append(DecisionDeskStockCard(code, code, "持倉警示", "持倉警示"))
        return DecisionDeskStockFocusSummary(priority_stocks=tuple(priority[:8]), risk_stocks=tuple(risk[:8]))
```

- [ ] **Step 5: Integrate composer into snapshot builder**

In `app_module/decision_desk_service.py`, add protocols:

```python
class SmartMoneyDashboardSectionService(Protocol):
    def build_dashboard_summary(self, decision_date: date, stock_codes: tuple[str, ...] = ()) -> object: ...
```

Add constructor parameters:

```python
        dashboard_composer: DecisionDeskDashboardComposer | None = None,
        smart_money_service: SmartMoneyDashboardSectionService | None = None,
```

After `risk_prompts`:

```python
        smart_money = None
        if self.smart_money_service is not None:
            try:
                stock_codes = tuple(relative_strength_liquidity.top_strength_codes[:20] + relative_strength_liquidity.weak_strength_codes[:20])
                smart_money = self.smart_money_service.build_dashboard_summary(as_of_date, stock_codes=stock_codes)
            except Exception:
                smart_money = None
        action_summary, sector_focus, stock_focus = self.dashboard_composer.compose(
            as_of_date=as_of_date,
            market_regime=market_regime,
            market_breadth=market_breadth,
            sector_rotation=sector_rotation,
            relative_strength_liquidity=relative_strength_liquidity,
            watchlist_triggers=watchlist_triggers,
            portfolio_alerts=portfolio_alerts,
            smart_money=smart_money,
        )
```

Pass those to `DecisionDeskSnapshot`.

- [ ] **Step 6: Update service serialization tests**

In `tests/test_decision_desk_service.py`, add assertions:

```python
assert snapshot.action_summary is not None
assert snapshot.action_summary.research_mode_note == "這是研究模式，不是交易建議。"
assert "action_summary" in snapshot.to_dict()
```

- [ ] **Step 7: Run composer and service tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_decision_desk_dashboard_service.py tests/test_decision_desk_service.py -q -o addopts=
```

Expected: pass.

### Task 4: Decision Desk Answer-First UI and Drill-Down

**Files:**
- Modify: `tests/test_ui_qt_decision_desk_view.py`
- Modify: `ui_qt/views/decision_desk_view.py`
- Modify: `tests/test_ui_qt_decision_desk_main_integration.py`
- Modify: `ui_qt/main.py`

- [ ] **Step 1: Write failing UI tests**

In `tests/test_ui_qt_decision_desk_view.py`, extend `_snapshot()` to include `action_summary`, `sector_focus`, and `stock_focus`. Then add:

```python
def test_decision_desk_view_renders_answer_first_dashboard():
    app()
    view = rendered_view(FakeBuilder(_snapshot()))

    assert "今日主結論" in view.action_headline_label.text()
    assert "研究模式，不是交易建議" in view.action_note_label.text()
    assert "優先產業" in view.priority_sector_label.text()
    assert "避開產業 / 風險區" in view.risk_sector_label.text()


def test_decision_desk_stock_card_drilldown_uses_callback():
    app()
    called = []
    view = DecisionDeskView(
        FakeBuilder(_snapshot()),
        auto_refresh=False,
        async_refresh=False,
        navigate_to_smart_money_callback=lambda code: called.append(code),
    )
    view.refresh_snapshot()

    view._navigate_to_smart_money("2330")

    assert called == ["2330"]
```

- [ ] **Step 2: Run UI tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_decision_desk_view.py -q -o addopts=
```

Expected: fails because answer-first widgets and callback are missing.

- [ ] **Step 3: Add callback and widgets**

In `ui_qt/views/decision_desk_view.py`, extend `__init__`:

```python
        navigate_to_smart_money_callback=None,
```

Store:

```python
        self.navigate_to_smart_money_callback = navigate_to_smart_money_callback
```

Create top dashboard widgets before existing module status:

```python
self.action_headline_label = QLabel("今日主結論：尚未載入")
self.action_note_label = QLabel("這是研究模式，不是交易建議。")
self.priority_sector_label = QLabel("優先產業：尚未載入")
self.risk_sector_label = QLabel("避開產業 / 風險區：尚未載入")
self.priority_stock_label = QLabel("優先研究股票：尚未載入")
self.risk_stock_label = QLabel("風險股票：尚未載入")
```

Add them to a `SectionPanel("今日主結論")` and `SectionPanel("市場焦點")`.

- [ ] **Step 4: Render dashboard DTOs**

Add helpers:

```python
def _render_answer_first_dashboard(self, snapshot: DecisionDeskSnapshot) -> None:
    action = snapshot.action_summary
    if action is None:
        self.action_headline_label.setText("今日主結論：尚未產生")
        self.action_note_label.setText("這是研究模式，不是交易建議。")
    else:
        self.action_headline_label.setText(action.headline)
        self.action_note_label.setText(action.research_mode_note)
    sector_focus = snapshot.sector_focus
    if sector_focus is not None:
        self.priority_sector_label.setText("優先產業：" + self._format_sector_cards(sector_focus.priority_sectors))
        self.risk_sector_label.setText("避開產業 / 風險區：" + self._format_sector_cards(sector_focus.risk_sectors))
    stock_focus = snapshot.stock_focus
    if stock_focus is not None:
        self.priority_stock_label.setText("優先研究股票：" + self._format_stock_cards(stock_focus.priority_stocks))
        self.risk_stock_label.setText("風險股票：" + self._format_stock_cards(stock_focus.risk_stocks))

def _navigate_to_smart_money(self, stock_code: str) -> None:
    if self.navigate_to_smart_money_callback is not None:
        self.navigate_to_smart_money_callback(str(stock_code))
```

Call `_render_answer_first_dashboard(snapshot)` at the beginning of `_render_snapshot()`.

- [ ] **Step 5: Wire main window callback and service**

In `ui_qt/main.py`, import:

```python
from app_module.smart_money_semantic_service import SmartMoneySemanticService, SQLiteSmartMoneyPriceProvider
```

In `_create_decision_desk_builder()`:

```python
smart_money_semantic_service = None
try:
    smart_money_semantic_service = SmartMoneySemanticService(
        self.broker_flow_service,
        price_provider=SQLiteSmartMoneyPriceProvider(self.config.db_file),
    )
except Exception as exc:
    print(f"[MainWindow] 決策桌面 SmartMoneySemanticService 初始化失敗：{exc}")
```

Pass to builder:

```python
smart_money_service=smart_money_semantic_service,
```

When creating `DecisionDeskView`, pass:

```python
navigate_to_smart_money_callback=self.show_smart_money_flow_for_stock,
```

- [ ] **Step 6: Update main integration test**

In `tests/test_ui_qt_decision_desk_main_integration.py`, assert:

```python
assert target_window.tabs.widget(decision_idx).navigate_to_smart_money_callback == target_window.show_smart_money_flow_for_stock
```

- [ ] **Step 7: Run UI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_decision_desk_view.py tests/test_ui_qt_decision_desk_main_integration.py -q -o addopts=
```

Expected: pass.

### Task 5: Smart Money UI Semantic Rendering

**Files:**
- Modify: `tests/test_ui_qt_smart_money_flow_view.py`
- Modify: `ui_qt/views/smart_money/smart_money_flow_view.py`
- Modify: `ui_qt/views/smart_money/terminal_table_model.py`

- [ ] **Step 1: Write failing UI/model tests**

In `tests/test_ui_qt_smart_money_flow_view.py`, add:

```python
class FakeSemanticService:
    def build_stock_semantics(self, stock_code, decision_date):
        from datetime import date
        from app_module.dtos.smart_money_semantic_dtos import SmartMoneySemanticSummary, SmartMoneyWindowStats
        window = SmartMoneyWindowStats(5, 500, 700, 200, "buy", 2, 0, 3, 7000, 3, 0, 0, 10000)
        return SmartMoneySemanticSummary(
            stock_code=stock_code,
            stock_name=f"股票{stock_code}",
            decision_date=date(2026, 6, 20),
            primary_state="初轉買",
            semantic_flags=("分點集中異常",),
            confidence_bp=10000,
            quality="observed",
            warnings=(),
            window_5=window,
            window_20=window,
            window_60=window,
            reasons=("5 日轉為買超",),
        )


def test_smart_money_table_model_renders_semantic_state_and_diagnostics():
    app()
    signal = _signal("2330", 88, 500)
    semantic_service = FakeSemanticService()
    view = SmartMoneyFlowView(FakeSmartMoneyService(), smart_money_semantic_service=semantic_service)

    view._apply_scanner_signals([signal])

    model = view.scanner_table.model()
    headers = [model.headerData(i, Qt.Horizontal) for i in range(model.columnCount())]
    assert "語意狀態" in headers
    assert "5/20/60 日診斷" in headers
    semantic_col = headers.index("語意狀態")
    assert "初轉買" in model.data(model.index(0, semantic_col), Qt.DisplayRole)
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_smart_money_flow_view.py -q -o addopts=
```

Expected: fails because `smart_money_semantic_service` and columns are missing.

- [ ] **Step 3: Pass semantic summaries into table model**

In `SmartMoneyFlowView.__init__`, add:

```python
    def __init__(self, broker_flow_service: BrokerFlowService, watchlist_service: WatchlistService = None, smart_money_semantic_service=None, parent=None):
        ...
        self.smart_money_semantic_service = smart_money_semantic_service
```

In `_apply_scanner_signals()`:

```python
        semantics_by_code = {}
        if self.smart_money_semantic_service is not None:
            from datetime import date
            for signal in filtered_signals:
                try:
                    semantics_by_code[signal.stock_code] = self.smart_money_semantic_service.build_stock_semantics(signal.stock_code, date.today())
                except Exception:
                    continue
        self.scanner_model = TerminalTableModel(filtered_signals, semantics_by_code=semantics_by_code)
```

- [ ] **Step 4: Add table model columns**

In `TerminalTableModel.__init__`:

```python
def __init__(self, signals: List[FlowSignalDTO], parent=None, semantics_by_code=None):
    super().__init__(parent)
    self.signals = signals
    self.semantics_by_code = semantics_by_code or {}
    self.headers = ["分數", "股票", "淨量", "集中度", "語意狀態", "5/20/60 日診斷", "信號 (Badges)", "近期趨勢 (Trend)"]
```

In `data()`:

```python
semantic = self.semantics_by_code.get(signal.stock_code)
if role == Qt.DisplayRole:
    if col == 4:
        return semantic.primary_state if semantic else "未計算"
    if col == 5:
        if semantic is None:
            return "無語意診斷"
        return f"5日 {semantic.window_5.net_qty:+,}｜20日 {semantic.window_20.net_qty:+,}｜60日 {semantic.window_60.net_qty:+,}"
    if col == 6:
        return ""
    if col == 7:
        return ""
if role == Qt.ToolTipRole and semantic is not None:
    return "\n".join([
        f"語意狀態：{semantic.primary_state}",
        f"旗標：{'、'.join(semantic.semantic_flags) if semantic.semantic_flags else '無'}",
        f"5日 Top {semantic.window_5.top_n} 集中度：{semantic.window_5.top_concentration_bp or 0} bp",
        f"資料品質：observed={semantic.window_5.observed_count} estimated={semantic.window_5.estimated_count} unavailable={semantic.window_5.unavailable_count}",
        *semantic.reasons,
    ])
```

Update column numbers for ROLE_BADGES and ROLE_SPARKLINE from old `4` / `5` to new `6` / `7`.

- [ ] **Step 5: Preserve sorting**

Update `sort()`:

```python
elif column == 4:
    self.signals.sort(key=lambda x: getattr(self.semantics_by_code.get(x.stock_code), "primary_state", ""), reverse=reverse)
```

- [ ] **Step 6: Run Smart Money UI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_smart_money_flow_view.py -q -o addopts=
```

Expected: pass.

### Task 6: UI Boundary Contract and Financial Guard

**Files:**
- Modify: `tests/test_decision_desk_ui_contract.py`
- Run existing financial guard.

- [ ] **Step 1: Extend UI boundary test**

Ensure `tests/test_decision_desk_ui_contract.py` still rejects direct domain imports from `ui_qt/views/decision_desk_view.py`. Add `decision_module.flow_signal_engine`, `data_module.db_manager`, and `portfolio_module.core` to the disallowed imports if not already present.

Expected assertion pattern:

```python
assert "decision_module.flow_signal_engine" not in imported_modules
assert "data_module.db_manager" not in imported_modules
assert "portfolio_module.core" not in imported_modules
```

- [ ] **Step 2: Run contract and financial boundary tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_decision_desk_ui_contract.py tests/test_smart_money_semantic_service.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

Expected: pass. If the float boundary checker flags DTO display fields that already existed, do not silence them without checking category comments. New Smart Money semantic service core must not introduce unmarked naked `float`.

### Task 7: Documentation and Healthcheck Updates

**Files:**
- Modify: `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify if needed: `docs/01_architecture/system_architecture.md`
- Modify if needed: `docs/00_core/DOCUMENTATION_INDEX.md`

- [ ] **Step 1: Update healthcheck status**

In `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`:

- Mark `DECISION-ISSUE-002` as `已修正待驗證`.
- Mark `DECISION-ISSUE-003` as `已修正待驗證`.
- Mark `MARKET-ISSUE-006` as `已修正待驗證`.
- Mark `MARKET-ISSUE-007` as `已修正待驗證`.
- Keep Batch 1 items as `已修正待驗證`, not `驗證通過`, unless the user has manually verified them.

Use wording:

```markdown
Daily Decision Desk 已新增 answer-first 主結論、研究模式註記、優先 / 風險產業與股票卡片，股票卡可下鑽至市場觀察 > 主力流向。
```

```markdown
Smart Money 已新增 5 / 20 / 60 日語意診斷、quantity-based Top N 集中度與 observed / estimated / unavailable 品質揭露；高檔出貨疑慮使用 decision_date 前 60 筆價格資料。
```

- [ ] **Step 2: Update Manual**

In `docs/07_guides/APPLICATION_MANUAL.md`:

- Market Watch / Smart Money section:
  - Add semantic states and 5 / 20 / 60 diagnostics.
  - Explain concentration uses quantity, not thousand-dollar amount.
  - Explain `高檔出貨疑慮` is a risk prompt, not sell advice.

- Daily Decision section:
  - Add answer-first action levels: `積極研究`, `正常研究`, `保守觀察`, `暫停新進場`.
  - Explain Watchlist / Portfolio / individual stock risks do not directly lower market action level.
  - Explain sector and stock cards drill down to Smart Money / Market Watch.

- Update changelog with:

```markdown
- 2026-06-23：完成 Healthcheck Batch 2 計畫範圍實作後的操作說明：Daily Decision Desk answer-first dashboard、Smart Money 5 / 20 / 60 日語意診斷、quantity concentration 與卡片下鑽。
```

- [ ] **Step 3: Architecture and Index coverage**

If new service files are added:

- Update `docs/01_architecture/system_architecture.md` Application Layer / Broker Flow / Daily Decision Desk paragraphs to mention `SmartMoneySemanticService` and `DecisionDeskDashboardComposer`.
- Update `docs/00_core/DOCUMENTATION_INDEX.md` only if the new Batch 2 plan should be indexed under Superpowers plans.

Do not update Snapshot or Roadmap Hub unless Batch 2 changes current project priority or month-level roadmap status. It does not change the 6M direction; it closes healthcheck UX issues within existing Month 4 / healthcheck scope.

### Task 8: Verification

**Files:**
- All changed files.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_smart_money_semantic_service.py tests/test_decision_desk_dashboard_service.py tests/test_decision_desk_service.py tests/test_ui_qt_decision_desk_view.py tests/test_ui_qt_decision_desk_main_integration.py tests/test_ui_qt_smart_money_flow_view.py tests/test_decision_desk_ui_contract.py tests/test_broker_flow_units.py -q -o addopts=
```

Expected: pass.

- [ ] **Step 2: Run required UI verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

Expected: pass.

- [ ] **Step 3: Run financial and syntax checks**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m py_compile app_module\dtos\smart_money_semantic_dtos.py app_module\smart_money_semantic_service.py app_module\decision_desk_dashboard_service.py app_module\decision_desk_dtos.py app_module\decision_desk_service.py app_module\broker_flow_service.py ui_qt\views\decision_desk_view.py ui_qt\views\smart_money\smart_money_flow_view.py ui_qt\views\smart_money\terminal_table_model.py ui_qt\main.py
```

Expected: pass.

- [ ] **Step 4: Manual smoke test checklist**

Manual verification must not run destructive data operations.

1. Open `ui_qt/main.py`.
2. Open `每日決策`.
3. Confirm top section shows `今日主結論`, action level, research-mode note, priority sectors, risk sectors, priority stocks, and risk stocks.
4. Click a stock card drill-down and confirm it switches to `市場觀察 > 主力流向` and selects the stock.
5. Open `市場觀察 > 主力流向`.
6. Click `開始掃描`.
7. Confirm table shows `語意狀態` and `5/20/60 日診斷`.
8. Hover rows and confirm tooltip includes observed / estimated / unavailable counts and concentration unit.
9. Confirm no UI text presents this as buy / sell advice.

### Task 9: Final Git Hygiene

**Files:**
- All changed files.

- [ ] **Step 1: Review diff**

Run:

```powershell
git status --short
git diff --stat
```

Expected changed files are only Batch 2 implementation, tests, and docs.

- [ ] **Step 2: Review docs diff**

Run:

```powershell
git diff -- docs\06_qa\FULL_APP_HEALTHCHECK_2026_06_16.md docs\07_guides\APPLICATION_MANUAL.md docs\01_architecture\system_architecture.md docs\00_core\DOCUMENTATION_INDEX.md
```

Expected: Batch 2 status and usage updates only.

- [ ] **Step 3: Stage intentionally**

Run:

```powershell
git add app_module\dtos\smart_money_semantic_dtos.py app_module\smart_money_semantic_service.py app_module\decision_desk_dashboard_service.py app_module\decision_desk_dtos.py app_module\decision_desk_service.py app_module\broker_flow_service.py ui_qt\views\decision_desk_view.py ui_qt\views\smart_money\smart_money_flow_view.py ui_qt\views\smart_money\terminal_table_model.py ui_qt\main.py tests\test_smart_money_semantic_service.py tests\test_decision_desk_dashboard_service.py tests\test_decision_desk_service.py tests\test_ui_qt_decision_desk_view.py tests\test_ui_qt_decision_desk_main_integration.py tests\test_ui_qt_smart_money_flow_view.py tests\test_decision_desk_ui_contract.py docs\06_qa\FULL_APP_HEALTHCHECK_2026_06_16.md docs\07_guides\APPLICATION_MANUAL.md
```

Also stage architecture / index files only if actually changed.

- [ ] **Step 4: Confirm staged files**

Run:

```powershell
git diff --cached --name-only
```

Expected: no `output/qa/update_tab/*`, no `.superpowers/`, no `meta_data/`, no raw data files.

- [ ] **Step 5: Commit**

Run:

```powershell
git commit -m "feat: add healthcheck batch 2 dashboard semantics"
```

## Execution Notes

- Prefer subagent-driven execution by task. Task 2 and Task 3 can be implemented independently after baseline. Task 4 depends on Task 3. Task 5 depends on Task 2. Task 7 should run after UI behavior is final.
- If Smart Money semantic service becomes too broad, do not split into performance optimization in this batch. Keep the first version deterministic, testable, and bounded to the healthcheck issues.
- If exact price provider wiring is blocked by local `DBManager` construction, use the established provider pattern from `market_breadth_service.py` or `relative_strength_liquidity_service.py`; do not query SQLite directly from Qt UI.
- If manual healthcheck shows Batch 1 portfolio drill-down already works, do not modify Portfolio in Batch 2.

## Self-Review

- Spec coverage:
  - `DECISION-ISSUE-002`: covered by Task 3 / Task 4 answer-first action summary.
  - `DECISION-ISSUE-003`: covered by Task 4 drill-down and sector / stock focus.
  - `MARKET-ISSUE-006`: covered by Task 2 / Task 5 diagnostic summaries replacing unclear micro chart dependence.
  - `MARKET-ISSUE-007`: covered by Task 2 semantic classification and Task 5 UI rendering.
- Placeholder scan: no unfinished placeholder markers and no unspecified tests.
- Type consistency: DTO names used by services and tests match the definitions in Tasks 2 and 3.
