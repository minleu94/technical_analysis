# Research Lab Workflow Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize Recommendation, Research Lab, Watchlist, and Portfolio handoffs into clear research workflows without rewriting the backtest engines.

**Architecture:** Phase 1 adds a small provenance adapter for Phase 3 → Portfolio trades, then makes low-risk UI copy and action changes around existing RecommendationView, BacktestView, and WatchlistView entry points. Research Lab mode taxonomy is introduced as a lightweight UI/helper layer, while existing services remain the source of truth.

**Tech Stack:** Python, PySide6, pytest, existing `PortfolioService`, `RecommendationDTO`, `BacktestRunRepository`, `PandasTableModel`.

---

## Scope Boundary

This plan implements the first phase from `docs/superpowers/specs/2026-06-04-research-lab-workflow-redesign.md`.

In scope:

- Add source metadata generation for Recommendation and Backtest trades recorded into Portfolio.
- Rename and organize visible handoff actions so they match Candidate Pool / Research Lab / Portfolio semantics.
- Add a minimal Research Lab mode taxonomy in Backtest UI without moving core engines.
- Add tests for provenance metadata and no-regression smoke checks.
- Update docs that describe the first-phase behavior.

Out of scope:

- Full Strategy Center UI.
- Full Watchlist storage migration.
- Decimal/integer-unit refactor for the entire Portfolio module.
- Rewriting `BacktestService`, `RecommendationPortfolioBacktestService`, or StrategyRegistry.

## File Structure

- Create `app_module/portfolio_source_adapter.py`  
  Builds stable source metadata and snapshot hashes for portfolio trades. It does not write storage or calculate PnL.
- Create `tests/test_portfolio_source_adapter.py`  
  Verifies Recommendation and Backtest metadata generation.
- Modify `app_module/portfolio_service.py`  
  Accepts optional `source_summary` metadata and stores it in trade notes or DTO-compatible fields without changing trade rebuild logic.
- Modify `app_module/dtos/portfolio_dtos.py` and `portfolio_module/core.py`  
  Adds `source_summary` as descriptive metadata only.
- Modify `ui_qt/views/recommendation_view.py`  
  Changes result actions to Candidate Pool / Research Lab / Portfolio language and uses the adapter for Portfolio trade recording.
- Modify `ui_qt/views/backtest_view.py`  
  Introduces Research Lab mode copy and uses the adapter for Backtest trade-to-Portfolio recording.
- Modify `ui_qt/views/watchlist_view.py`  
  Reframes Watchlist as Candidate Pool in visible labels and primary action copy.
- Modify `tests/test_portfolio_mvp.py`  
  Adds coverage that metadata survives append-only storage and derived position rebuild.
- Modify `scripts/qa_validate_portfolio_tab.py`  
  Adds source metadata assertions.
- Modify `docs/00_core/PROJECT_SNAPSHOT.md`, `docs/00_core/DEVELOPMENT_ROADMAP.md`, and `docs/00_core/DOCUMENTATION_INDEX.md`  
  Documents the workflow redesign if UI behavior changes.

---

### Task 1: Add Portfolio Source Metadata Adapter

**Files:**
- Create: `app_module/portfolio_source_adapter.py`
- Create: `tests/test_portfolio_source_adapter.py`

- [ ] **Step 1: Write failing tests for Recommendation source metadata**

Create `tests/test_portfolio_source_adapter.py` with:

```python
from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.portfolio_source_adapter import (
    build_backtest_trade_source,
    build_recommendation_trade_source,
)


def make_recommendation() -> RecommendationDTO:
    return RecommendationDTO(
        stock_code="2330",
        stock_name="台積電",
        total_score=82.5,
        technical_score=80.0,
        pattern_score=75.0,
        volume_score=92.0,
        recommendation="強勢候選",
        reasons=["量能放大", "趨勢偏多"],
        risk_level="medium",
        suggested_strategy="momentum_aggressive_v1",
        why_not_reasons=["追價風險"],
    )


def test_build_recommendation_trade_source_contains_traceable_context():
    result = RecommendationResultDTO(
        result_id="rec_20260604_001",
        result_name="短線暴衝候選",
        created_at="2026-06-04T09:00:00",
        config={
            "profile_id": "aggressive_short",
            "profile_version": "1.0",
            "regime_snapshot": {"regime": "trend", "confidence": 0.81},
        },
        recommendations=[make_recommendation()],
        notes="日常推薦",
    )

    source = build_recommendation_trade_source(result, make_recommendation())

    assert source.source_type == "recommendation_result"
    assert source.source_id == "rec_20260604_001"
    assert source.source_snapshot_hash
    assert source.source_summary["stock_code"] == "2330"
    assert source.source_summary["profile_id"] == "aggressive_short"
    assert source.source_summary["regime"] == "trend"
    assert source.source_summary["total_score"] == 82.5
    assert "量能放大" in source.source_summary["reasons"]
```

- [ ] **Step 2: Write failing tests for Backtest source metadata**

Append to `tests/test_portfolio_source_adapter.py`:

```python
def test_build_backtest_trade_source_contains_run_and_strategy_context():
    row = {
        "股票代號": "2330",
        "股票名稱": "台積電",
        "買賣": "買入",
        "交易日期": "2026-06-04",
        "價格": 888.0,
        "數量": 1000,
    }
    source = build_backtest_trade_source(
        run_id="run_001",
        run_name="2330 momentum smoke",
        strategy_id="momentum_aggressive_v1",
        validation_status="PASS",
        trade_row=row,
    )

    assert source.source_type == "backtest_run"
    assert source.source_id == "run_001"
    assert source.source_snapshot_hash
    assert source.source_summary["strategy_id"] == "momentum_aggressive_v1"
    assert source.source_summary["validation_status"] == "PASS"
    assert source.source_summary["stock_code"] == "2330"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_source_adapter.py -q -o addopts=
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app_module.portfolio_source_adapter'`.

- [ ] **Step 4: Implement adapter**

Create `app_module/portfolio_source_adapter.py`:

```python
"""Build source metadata for Portfolio trades created from research artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from app_module.dtos import RecommendationDTO, RecommendationResultDTO


@dataclass(frozen=True)
class PortfolioTradeSource:
    """Traceable source metadata attached to append-only Portfolio trades."""

    source_type: str
    source_id: str
    source_snapshot_hash: str
    source_summary: Dict[str, Any]


def stable_snapshot_hash(payload: Mapping[str, Any]) -> str:
    """Return a deterministic hash for JSON-compatible metadata."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def build_recommendation_trade_source(
    result: RecommendationResultDTO,
    recommendation: RecommendationDTO,
) -> PortfolioTradeSource:
    """Create trace metadata for a trade recorded from a Recommendation row."""

    config = dict(result.config or {})
    regime_snapshot = dict(config.get("regime_snapshot") or {})
    summary: Dict[str, Any] = {
        "result_id": result.result_id,
        "result_name": result.result_name,
        "created_at": result.created_at,
        "stock_code": recommendation.stock_code,
        "stock_name": recommendation.stock_name,
        "profile_id": config.get("profile_id") or config.get("selected_profile") or "",
        "profile_version": config.get("profile_version") or "",
        "regime": regime_snapshot.get("regime") or config.get("regime") or "",
        "total_score": recommendation.total_score,
        "technical_score": recommendation.technical_score,
        "pattern_score": recommendation.pattern_score,
        "volume_score": recommendation.volume_score,
        "recommendation": recommendation.recommendation,
        "suggested_strategy": recommendation.suggested_strategy,
        "risk_level": recommendation.risk_level,
        "reasons": list(recommendation.reasons or []),
        "why_not_reasons": list(getattr(recommendation, "why_not_reasons", []) or []),
    }
    return PortfolioTradeSource(
        source_type="recommendation_result",
        source_id=result.result_id,
        source_snapshot_hash=stable_snapshot_hash(summary),
        source_summary=summary,
    )


def _row_value(row: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return default


def build_backtest_trade_source(
    run_id: str,
    run_name: str,
    strategy_id: str,
    validation_status: str,
    trade_row: Mapping[str, Any],
) -> PortfolioTradeSource:
    """Create trace metadata for a trade recorded from a Backtest trade row."""

    summary: Dict[str, Any] = {
        "run_id": run_id,
        "run_name": run_name,
        "strategy_id": strategy_id,
        "validation_status": validation_status,
        "stock_code": str(_row_value(trade_row, "股票代號", "stock_code")),
        "stock_name": str(_row_value(trade_row, "股票名稱", "stock_name")),
        "side": str(_row_value(trade_row, "買賣", "side")),
        "trade_date": str(_row_value(trade_row, "交易日期", "date", "trade_date")),
        "price": _row_value(trade_row, "價格", "price"),
        "quantity": _row_value(trade_row, "數量", "quantity", default=""),
    }
    return PortfolioTradeSource(
        source_type="backtest_run",
        source_id=run_id,
        source_snapshot_hash=stable_snapshot_hash(summary),
        source_summary=summary,
    )
```

- [ ] **Step 5: Run adapter tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_source_adapter.py -q -o addopts=
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add app_module\portfolio_source_adapter.py tests\test_portfolio_source_adapter.py
git commit -m "feat(portfolio): add research source metadata adapter"
```

---

### Task 2: Preserve Source Summary in Portfolio Trades

**Files:**
- Modify: `app_module/dtos/portfolio_dtos.py`
- Modify: `portfolio_module/core.py`
- Modify: `app_module/portfolio_service.py`
- Modify: `tests/test_portfolio_mvp.py`
- Modify: `scripts/qa_validate_portfolio_tab.py`

- [ ] **Step 1: Add failing service test**

Append to `tests/test_portfolio_mvp.py`:

```python
def test_portfolio_service_preserves_source_summary_on_trade_and_position(tmp_path):
    service = PortfolioService(make_config(tmp_path))

    service.record_trade(
        stock_code="2330",
        stock_name="TSMC",
        side="buy",
        quantity=10,
        price=100,
        trade_date="2026-01-02",
        source_type="recommendation_result",
        source_id="rec_001",
        source_snapshot_hash="hash001",
        source_summary={"profile_id": "aggressive_short", "total_score": 82.5},
        trade_id="trade_001",
    )

    trades = service.list_trades()
    assert trades[0].source_summary["profile_id"] == "aggressive_short"

    positions = service.list_positions()
    assert positions[0].source_type == "recommendation_result"
    assert positions[0].source_id == "rec_001"
    assert positions[0].source_snapshot_hash == "hash001"
    assert positions[0].source_summary["total_score"] == 82.5
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_mvp.py::test_portfolio_service_preserves_source_summary_on_trade_and_position -q -o addopts=
```

Expected: FAIL because `record_trade()` does not accept `source_summary`.

- [ ] **Step 3: Add `source_summary` to DTO and domain**

In `app_module/dtos/portfolio_dtos.py`, add `source_summary: Dict[str, Any] = field(default_factory=dict)` to `TradeDTO` and `PositionDTO`, then include it in `to_dict()` and `from_dict()`:

```python
source_summary: Dict[str, Any] = field(default_factory=dict)
```

In `TradeDTO.from_dict()`:

```python
source_summary=dict(data.get("source_summary", {}) or {}),
```

In `portfolio_module/core.py`, add `source_summary: Dict[str, Any] = field(default_factory=dict)` to `Trade` and `Position`, include it in `Trade.from_mapping()`, `Trade.to_dict()`, and `Position.to_dict()`.

In `rebuild_positions()`, when creating a new `Position`, pass:

```python
source_summary=dict(trade.source_summary or {}),
```

- [ ] **Step 4: Update service signature**

In `app_module/portfolio_service.py`, add the parameter:

```python
source_summary: Optional[Dict[str, Any]] = None,
```

When building `TradeDTO`, pass:

```python
source_summary=dict(source_summary or {}),
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_mvp.py tests\test_portfolio_delete.py tests\test_portfolio_source_adapter.py -q -o addopts=
```

Expected: PASS.

- [ ] **Step 6: Update QA script assertion**

In `scripts/qa_validate_portfolio_tab.py`, update the first `portfolio_service.record_trade()` call to include:

```python
source_snapshot_hash="hash_rec_001",
source_summary={"profile_id": "aggressive_short", "total_score": 82.5},
```

After `assert pos.invested_amount == 1220000.0`, add:

```python
assert pos.source_type == "recommendation"
assert pos.source_id == "rec_001"
assert pos.source_snapshot_hash == "hash_rec_001"
assert pos.source_summary["profile_id"] == "aggressive_short"
```

- [ ] **Step 7: Run Portfolio QA**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\qa_validate_portfolio_tab.py
```

Expected: script exits 0 and logs `All QA validations PASSED successfully!`.

- [ ] **Step 8: Commit**

Run:

```powershell
git add app_module\dtos\portfolio_dtos.py portfolio_module\core.py app_module\portfolio_service.py tests\test_portfolio_mvp.py scripts\qa_validate_portfolio_tab.py
git commit -m "feat(portfolio): persist research source summaries"
```

---

### Task 3: Wire Recommendation Result to Portfolio Source Metadata

**Files:**
- Modify: `ui_qt/views/recommendation_view.py`
- Test: `tests/test_portfolio_source_adapter.py`

- [ ] **Step 1: Add helper method for current recommendation result**

In `ui_qt/views/recommendation_view.py`, add an import near existing app imports:

```python
from app_module.portfolio_source_adapter import build_recommendation_trade_source
```

Add a method inside `RecommendationView`:

```python
def _build_current_result_snapshot(self) -> RecommendationResultDTO:
    """Build an unsaved recommendation result snapshot for provenance only."""

    return RecommendationResultDTO(
        result_id=getattr(self, "current_result_id", "") or "unsaved_recommendation_result",
        result_name=getattr(self, "current_result_name", "") or "未保存推薦結果",
        created_at=getattr(self, "current_result_created_at", "") or "",
        config=dict(self.current_config or {}),
        recommendations=list(self.current_recommendations or []),
        notes="Created for Portfolio source provenance",
    )
```

- [ ] **Step 2: Update context menu copy**

In `_show_results_table_context_menu`, change the action label:

```python
action_add_portfolio = menu.addAction("記錄到持倉管理（保留推薦來源）...")
```

Keep the existing Watchlist action but rename visible copy to:

```python
action_add_watchlist = menu.addAction("加入候選池 / 觀察清單")
```

- [ ] **Step 3: Attach source metadata when recording trade**

In the block that calls `main_window.portfolio_service.record_trade(...)`, build metadata before the call:

```python
selected_rec = self.current_recommendations[row]
source = build_recommendation_trade_source(
    self._build_current_result_snapshot(),
    selected_rec,
)
```

Add these arguments to `record_trade()`:

```python
source_type=source.source_type,
source_id=source.source_id,
source_snapshot_hash=source.source_snapshot_hash,
source_summary=source.source_summary,
```

Do not remove user-entered trade date, price, quantity, fees, taxes, or notes from `AddTradeDialog`.

- [ ] **Step 4: Run syntax check**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile ui_qt\views\recommendation_view.py
```

Expected: exits 0.

- [ ] **Step 5: Run relevant tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_source_adapter.py tests\test_portfolio_mvp.py -q -o addopts=
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add ui_qt\views\recommendation_view.py
git commit -m "feat(ui): preserve recommendation provenance in portfolio trades"
```

---

### Task 4: Wire Backtest Trade Rows to Portfolio Source Metadata

**Files:**
- Modify: `ui_qt/views/backtest_view.py`

- [ ] **Step 1: Add import**

In `ui_qt/views/backtest_view.py`, add:

```python
from app_module.portfolio_source_adapter import build_backtest_trade_source
```

- [ ] **Step 2: Update context menu copy**

In `_show_trades_table_context_menu`, change the Portfolio action label:

```python
action_add_portfolio = menu.addAction("記錄到持倉管理（保留回測來源）...")
```

- [ ] **Step 3: Build source metadata from current run context**

Before `main_window.portfolio_service.record_trade(...)`, add:

```python
run_id = getattr(self, "current_run_id", "") or "unsaved_backtest_run"
run_name = ""
if getattr(self, "current_run_params", None):
    run_name = f"{self.current_run_params.get('stock_code', '')} {self.current_run_params.get('strategy_id', '')}".strip()
strategy_id = ""
if getattr(self, "current_run_params", None):
    strategy_id = str(self.current_run_params.get("strategy_id", ""))
validation_status = ""
if getattr(self, "current_report", None) and getattr(self.current_report, "validation_status", None):
    validation_status = str(self.current_report.validation_status.value)
source = build_backtest_trade_source(
    run_id=run_id,
    run_name=run_name,
    strategy_id=strategy_id,
    validation_status=validation_status,
    trade_row=row_data,
)
```

Where `row_data` is the dictionary already derived from the selected table row. If the function currently reads values directly from the DataFrame, create:

```python
row_data = df.iloc[row].to_dict()
```

- [ ] **Step 4: Attach source metadata to `record_trade()`**

Add:

```python
source_type=source.source_type,
source_id=source.source_id,
source_snapshot_hash=source.source_snapshot_hash,
source_summary=source.source_summary,
```

- [ ] **Step 5: Run syntax check**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile ui_qt\views\backtest_view.py
```

Expected: exits 0.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_source_adapter.py tests\test_portfolio_mvp.py -q -o addopts=
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```powershell
git add ui_qt\views\backtest_view.py
git commit -m "feat(ui): preserve backtest provenance in portfolio trades"
```

---

### Task 5: Add Minimal Research Lab Mode Taxonomy to Backtest UI

**Files:**
- Modify: `ui_qt/views/backtest_view.py`
- Create: `tests/test_research_lab_mode_taxonomy.py`

- [ ] **Step 1: Add failing taxonomy tests**

Create `tests/test_research_lab_mode_taxonomy.py`:

```python
from ui_qt.views.backtest_view import RESEARCH_LAB_MODES


def test_research_lab_modes_are_distinct_and_named_for_user_intent():
    mode_ids = [mode["id"] for mode in RESEARCH_LAB_MODES]

    assert mode_ids == [
        "single_stock",
        "batch_stock",
        "fixed_basket",
        "recommendation_replay",
        "strategy_research",
    ]
    assert RESEARCH_LAB_MODES[0]["label"] == "單股回測"
    assert RESEARCH_LAB_MODES[1]["primary_input"] == "候選池 / 股票清單"
    assert RESEARCH_LAB_MODES[3]["primary_input"] == "推薦 Profile / Config"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_research_lab_mode_taxonomy.py -q -o addopts=
```

Expected: FAIL because `RESEARCH_LAB_MODES` is not defined.

- [ ] **Step 3: Add taxonomy constant**

Near the top of `ui_qt/views/backtest_view.py`, after imports, add:

```python
RESEARCH_LAB_MODES = [
    {
        "id": "single_stock",
        "label": "單股回測",
        "description": "測一檔股票套用指定策略後的交易表現。",
        "primary_input": "股票代號",
    },
    {
        "id": "batch_stock",
        "label": "批次股票回測",
        "description": "測候選池內每檔股票各自套用策略後的排名與比較。",
        "primary_input": "候選池 / 股票清單",
    },
    {
        "id": "fixed_basket",
        "label": "固定組合回測",
        "description": "測固定一批股票作為組合時的整體表現。",
        "primary_input": "固定股票組合",
    },
    {
        "id": "recommendation_replay",
        "label": "推薦系統回放",
        "description": "測推薦 Profile / Config 在歷史日期重播時的組合表現。",
        "primary_input": "推薦 Profile / Config",
    },
    {
        "id": "strategy_research",
        "label": "策略研究",
        "description": "測策略模板或策略版本是否值得優化或升級。",
        "primary_input": "策略模板 / 策略版本",
    },
]
```

- [ ] **Step 4: Add visible mode selector without hiding existing controls**

In the Backtest config panel setup, add a compact group above existing controls:

```python
mode_group = QGroupBox("Research Lab 模式")
mode_layout = QVBoxLayout()
self.research_lab_mode_combo = QComboBox()
for mode in RESEARCH_LAB_MODES:
    self.research_lab_mode_combo.addItem(mode["label"], mode["id"])
self.research_lab_mode_hint = QLabel(RESEARCH_LAB_MODES[0]["description"])
self.research_lab_mode_hint.setWordWrap(True)
self.research_lab_mode_hint.setStyleSheet("color: #666;")
self.research_lab_mode_combo.currentIndexChanged.connect(self._on_research_lab_mode_changed)
mode_layout.addWidget(self.research_lab_mode_combo)
mode_layout.addWidget(self.research_lab_mode_hint)
mode_group.setLayout(mode_layout)
config_layout.addWidget(mode_group)
```

Add method:

```python
def _on_research_lab_mode_changed(self, index: int) -> None:
    if index < 0 or index >= len(RESEARCH_LAB_MODES):
        return
    mode = RESEARCH_LAB_MODES[index]
    self.research_lab_mode_hint.setText(
        f"{mode['description']}｜主要輸入：{mode['primary_input']}"
    )
```

This task does not hide or disable existing controls. It adds taxonomy and language first.

- [ ] **Step 5: Run taxonomy and syntax tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_research_lab_mode_taxonomy.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile ui_qt\views\backtest_view.py
```

Expected: PASS and syntax check exits 0.

- [ ] **Step 6: Commit**

Run:

```powershell
git add ui_qt\views\backtest_view.py tests\test_research_lab_mode_taxonomy.py
git commit -m "feat(ui): introduce research lab mode taxonomy"
```

---

### Task 6: Reframe Watchlist UI as Candidate Pool

**Files:**
- Modify: `ui_qt/views/watchlist_view.py`
- Test: `tests/test_ui_qt_watchlist_candidate_pool_copy.py`

- [ ] **Step 1: Add failing copy test**

Create `tests/test_ui_qt_watchlist_candidate_pool_copy.py`:

```python
from pathlib import Path


def test_watchlist_view_uses_candidate_pool_language():
    text = Path("ui_qt/views/watchlist_view.py").read_text(encoding="utf-8")

    assert "候選池" in text
    assert "送 Research Lab 批次回測" in text
```

- [ ] **Step 2: Run test to verify current copy gap**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_watchlist_candidate_pool_copy.py -q -o addopts=
```

Expected: FAIL if the current WatchlistView does not contain both required phrases.

- [ ] **Step 3: Update visible labels and button text**

In `ui_qt/views/watchlist_view.py`, update the main title label to include:

```python
"觀察候選池"
```

Rename the batch backtest action button or menu item to:

```python
"送 Research Lab 批次回測"
```

If no direct batch action exists, add a disabled or informational button only when the destination service is unavailable:

```python
self.send_to_research_lab_btn = QPushButton("送 Research Lab 批次回測")
self.send_to_research_lab_btn.setToolTip("將目前候選池作為批次股票回測的輸入。")
```

Connect it to the existing batch/backtest handoff if one exists. If no handoff exists in this view, leave it disabled and set:

```python
self.send_to_research_lab_btn.setEnabled(False)
self.send_to_research_lab_btn.setToolTip("此入口將在 Research Lab 批次回測整合時啟用。")
```

- [ ] **Step 4: Run copy and syntax tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_watchlist_candidate_pool_copy.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile ui_qt\views\watchlist_view.py
```

Expected: PASS and syntax check exits 0.

- [ ] **Step 5: Commit**

Run:

```powershell
git add ui_qt\views\watchlist_view.py tests\test_ui_qt_watchlist_candidate_pool_copy.py
git commit -m "feat(ui): reframe watchlist as candidate pool"
```

---

### Task 7: Update Recommendation Next-Step Copy

**Files:**
- Modify: `ui_qt/views/recommendation_view.py`
- Test: `tests/test_ui_qt_recommendation_next_steps_copy.py`

- [ ] **Step 1: Add failing copy test**

Create `tests/test_ui_qt_recommendation_next_steps_copy.py`:

```python
from pathlib import Path


def test_recommendation_view_names_next_steps_as_research_workflow():
    text = Path("ui_qt/views/recommendation_view.py").read_text(encoding="utf-8")

    assert "加入候選池" in text
    assert "送 Research Lab 批次回測" in text
    assert "送 Research Lab 推薦回放" in text
    assert "記錄到持倉管理" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_recommendation_next_steps_copy.py -q -o addopts=
```

Expected: FAIL until copy is updated.

- [ ] **Step 3: Update Recommendation buttons and menu labels**

In `ui_qt/views/recommendation_view.py`:

Change the Watchlist button text to:

```python
self.add_to_watchlist_btn = QPushButton("加入候選池")
```

Change current batch/list handoff copy to:

```python
"送 Research Lab 批次回測"
```

Change recommendation portfolio replay button text to:

```python
self.send_profile_to_portfolio_backtest_btn = QPushButton("送 Research Lab 推薦回放")
```

Ensure Portfolio context action includes:

```python
"記錄到持倉管理"
```

- [ ] **Step 4: Run copy and syntax tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_recommendation_next_steps_copy.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile ui_qt\views\recommendation_view.py
```

Expected: PASS and syntax check exits 0.

- [ ] **Step 5: Commit**

Run:

```powershell
git add ui_qt\views\recommendation_view.py tests\test_ui_qt_recommendation_next_steps_copy.py
git commit -m "feat(ui): clarify recommendation research next steps"
```

---

### Task 8: Documentation Sync

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `docs/02_features/UI_FEATURES_DOCUMENTATION.md`

- [ ] **Step 1: Update Project Snapshot**

In `docs/00_core/PROJECT_SNAPSHOT.md`, add a short `2026-06-04` supplement:

```markdown
## 2026-06-04 Research Lab 工作流重整

- Research Lab 第一階段開始將回測頁定位為多模式研究實驗室，區分單股回測、批次股票回測、固定組合回測、推薦系統回放與策略研究。
- 觀察清單在研究流程中重新定位為候選池 / 實驗 Universe，用於回答「我要測哪一批」。
- Recommendation / Backtest 記錄到 Portfolio 時將保留來源 metadata，讓交易紀錄可追溯到推薦結果或回測 run。
```

- [ ] **Step 2: Update Roadmap Living Section**

In `docs/00_core/DEVELOPMENT_ROADMAP.md`, add under current Living Section updates:

```markdown
## 2026-06-04 Research Lab 工作流重整啟動

- Backtest / Research Lab 第一階段開始整理為多模式實驗室：策略研究、單股回測、批次股票回測、固定組合回測與推薦系統回放。
- Watchlist / 觀察清單在研究流程中明確定位為候選池，後續會承接推薦、強弱勢、主力流向與手動挑選來源。
- Phase 3 → Portfolio handoff 會以 append-only trade 為唯一主路徑，並保存 recommendation / backtest source metadata。
```

- [ ] **Step 3: Update Documentation Index**

In `docs/00_core/DOCUMENTATION_INDEX.md`, add this spec and plan under the Phase or core workflow section:

```markdown
| [2026-06-04-research-lab-workflow-redesign.md](../superpowers/specs/2026-06-04-research-lab-workflow-redesign.md) | Research Lab 多模式實驗室、候選池與 Phase 3 → Portfolio 來源追溯設計。 |
| [2026-06-04-research-lab-workflow-redesign.md](../superpowers/plans/2026-06-04-research-lab-workflow-redesign.md) | Research Lab 工作流重整第一階段實作計畫。 |
```

- [ ] **Step 4: Update UI features doc**

In `docs/02_features/UI_FEATURES_DOCUMENTATION.md`, add a section:

```markdown
### Research Lab 工作流

- Backtest / Research Lab 以模式區分不同實驗目的：單股、批次、固定組合、推薦回放與策略研究。
- Recommendation 的下一步行動分為加入候選池、送 Research Lab 批次回測、送 Research Lab 推薦回放與記錄到持倉管理。
- Watchlist 在研究流程中作為候選池，用於管理要送進批次或組合實驗的一批股票。
- Portfolio 只記錄使用者明確輸入的交易，並保留推薦或回測來源 metadata 供追溯。
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add docs\00_core\PROJECT_SNAPSHOT.md docs\00_core\DEVELOPMENT_ROADMAP.md docs\00_core\DOCUMENTATION_INDEX.md docs\02_features\UI_FEATURES_DOCUMENTATION.md
git commit -m "docs: sync research lab workflow redesign"
```

---

### Task 9: Final Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused Portfolio and UI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_source_adapter.py tests\test_portfolio_mvp.py tests\test_portfolio_delete.py tests\test_research_lab_mode_taxonomy.py tests\test_ui_qt_watchlist_candidate_pool_copy.py tests\test_ui_qt_recommendation_next_steps_copy.py -q -o addopts=
```

Expected: PASS.

- [ ] **Step 2: Run Portfolio QA script**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\qa_validate_portfolio_tab.py
```

Expected: exits 0 and logs all validations passed.

- [ ] **Step 3: Run UI update regression if UpdateView was untouched**

Run only if `ui_qt/views/update_view.py` was not modified:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

Expected: PASS. This is a guard against accidental cross-tab breakage.

- [ ] **Step 4: Run py_compile for changed Python files**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\portfolio_source_adapter.py app_module\portfolio_service.py app_module\dtos\portfolio_dtos.py portfolio_module\core.py ui_qt\views\recommendation_view.py ui_qt\views\backtest_view.py ui_qt\views\watchlist_view.py scripts\qa_validate_portfolio_tab.py
```

Expected: exits 0.

- [ ] **Step 5: Run mypy for touched modules**

Run:

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

Expected: no new errors. If the repository has pre-existing errors, record the exact output and verify none are caused by changed files.

- [ ] **Step 6: Check git status and exclusions**

Run:

```powershell
git status --short
```

Expected: only task-related files are modified. Do not stage `output/qa/update_tab/RUN_LOG.txt` or `output/qa/update_tab/VALIDATION_REPORT.md` unless this task intentionally updates QA output.

- [ ] **Step 7: Final commit if verification required cleanup**

If verification required small fixes, commit them:

```powershell
git add <changed task files only>
git commit -m "test: verify research lab workflow redesign"
```

Expected: commit succeeds.

