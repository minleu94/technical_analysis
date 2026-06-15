# Watchlist Trigger Provider Connection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect Watchlist Trigger service to real data sources, retrieving active watchlists from WatchlistService and scoring/risk alerts from SQLite technical_indicators.

**Architecture:** Create two provider classes wrapping the existing WatchlistService and SQLite query logic for technical_indicators (mapping RSI * 100 to score_bp and detecting risk alerts when RSI is extreme or price is below lower Bollinger Band). Inject them into MainWindow's DecisionDeskSnapshotBuilder and implement date-fallback warning logic.

**Tech Stack:** Python, Pandas, SQLite, PySide6, Pytest.

---

### Task 1: Add Providers and imports to Watchlist Trigger Service

**Files:**
- Modify: `app_module/watchlist_trigger_service.py`
- Test: `tests/test_watchlist_trigger_service.py`

- [ ] **Step 1: Write the failing test**

Open `tests/test_watchlist_trigger_service.py` and append:

```python
def test_watchlist_trigger_providers_can_be_imported():
    from app_module.watchlist_trigger_service import (
        WatchlistServiceWatchlistProvider,
        SQLiteRankingProvider,
    )
    assert WatchlistServiceWatchlistProvider is not None
    assert SQLiteRankingProvider is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_watchlist_trigger_service.py::test_watchlist_trigger_providers_can_be_imported -v
```
Expected output:
```text
ImportError: cannot import name 'WatchlistServiceWatchlistProvider' from 'app_module.watchlist_trigger_service'
```

- [ ] **Step 3: Write minimal implementation**

Open `app_module/watchlist_trigger_service.py` and update the imports and class definitions:

Replace the top imports:
```python
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Protocol, Sequence
from numbers import Integral, Real

import pandas as pd

from app_module.decision_desk_dtos import DecisionDeskQuality, WatchlistTriggerSummary
```

Append the following classes at the end of `app_module/watchlist_trigger_service.py`:
```python
class WatchlistServiceWatchlistProvider:
    """Watchlist provider that loads active watchlist from WatchlistService."""

    def __init__(self, watchlist_service: Any, watchlist_id: str = "default") -> None:
        self.watchlist_service = watchlist_service
        self.watchlist_id = watchlist_id

    def fetch(self, as_of_date: date) -> Sequence[object]:
        if self.watchlist_service is None:
            return []
        return self.watchlist_service.get_stocks(self.watchlist_id)


class SQLiteRankingProvider:
    """Ranking provider that fetches technical indicators from SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.actual_date: date | None = None

    def fetch(self, as_of_date: date) -> dict[str, dict[str, Any]]:
        self.actual_date = as_of_date
        if not self.db_path.exists():
            return {}

        target_key = as_of_date.strftime("%Y%m%d")
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT DISTINCT 日期
                FROM technical_indicators
                WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') <= ?
                ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') DESC
                LIMIT 1
                """,
                (target_key,),
            )
            row = cursor.fetchone()
            if row is None or not row[0]:
                return {}
            actual_key = str(row[0]).replace("-", "").replace("/", "")
            try:
                self.actual_date = datetime.strptime(actual_key, "%Y%m%d").date()
            except ValueError:
                pass

            df = pd.read_sql_query(
                """
                SELECT 證券代號, RSI, Close, lowerband
                FROM technical_indicators
                WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') = ?
                """,
                conn,
                params=(actual_key,),
            )

        if df.empty:
            return {}

        result = {}
        for _, r in df.iterrows():
            code = str(r["證券代號"]).strip()
            rsi_val = r["RSI"]
            close_val = r["Close"]
            lower_val = r["lowerband"]

            score_bp = None
            if rsi_val is not None and not pd.isna(rsi_val):
                try:
                    score_bp = int(float(rsi_val) * 100)
                except (ValueError, TypeError):
                    pass

            risk_alert = False
            if rsi_val is not None and not pd.isna(rsi_val):
                if float(rsi_val) > 80 or float(rsi_val) < 20:
                    risk_alert = True
            if close_val is not None and not pd.isna(close_val) and lower_val is not None and not pd.isna(lower_val):
                if float(close_val) < float(lower_val):
                    risk_alert = True

            result[code] = {
                "score_bp": score_bp,
                "risk_alert": risk_alert,
            }
        return result

    def fetch_previous(self, as_of_date: date) -> dict[str, dict[str, Any]] | None:
        if not self.db_path.exists():
            return None

        target_key = as_of_date.strftime("%Y%m%d")
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT DISTINCT 日期
                FROM technical_indicators
                WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') < ?
                ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') DESC
                LIMIT 1
                """,
                (target_key,),
            )
            row = cursor.fetchone()
            if row is None or not row[0]:
                return None
            prev_key = str(row[0]).replace("-", "").replace("/", "")

            df = pd.read_sql_query(
                """
                SELECT 證券代號, RSI, Close, lowerband
                FROM technical_indicators
                WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') = ?
                """,
                conn,
                params=(prev_key,),
            )

        if df.empty:
            return {}

        result = {}
        for _, r in df.iterrows():
            code = str(r["證券代號"]).strip()
            rsi_val = r["RSI"]
            close_val = r["Close"]
            lower_val = r["lowerband"]

            score_bp = None
            if rsi_val is not None and not pd.isna(rsi_val):
                try:
                    score_bp = int(float(rsi_val) * 100)
                except (ValueError, TypeError):
                    pass

            risk_alert = False
            if rsi_val is not None and not pd.isna(rsi_val):
                if float(rsi_val) > 80 or float(rsi_val) < 20:
                    risk_alert = True
            if close_val is not None and not pd.isna(close_val) and lower_val is not None and not pd.isna(lower_val):
                if float(close_val) < float(lower_val):
                    risk_alert = True

            result[code] = {
                "score_bp": score_bp,
                "risk_alert": risk_alert,
            }
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_watchlist_trigger_service.py::test_watchlist_trigger_providers_can_be_imported -v
```
Expected output:
```text
PASSED [100%]
```

- [ ] **Step 5: Commit**

```bash
git add app_module/watchlist_trigger_service.py tests/test_watchlist_trigger_service.py
git commit -m "feat: add WatchlistServiceWatchlistProvider and SQLiteRankingProvider"
```

---

### Task 2: Implement Date Fallback and Warning Logic in Watchlist Trigger Service

**Files:**
- Modify: `app_module/watchlist_trigger_service.py`
- Test: `tests/test_watchlist_trigger_service.py`

- [ ] **Step 1: Write the failing test**

Open `tests/test_watchlist_trigger_service.py` and append:

```python
def test_watchlist_trigger_service_uses_actual_date_fallback_and_warning():
    from app_module.watchlist_trigger_service import WatchlistTriggerService, WatchlistProvider, RankingProvider
    from app_module.decision_desk_dtos import DecisionDeskQuality
    
    class FakeWatchlistForFallback:
        def fetch(self, as_of_date):
            return ["2330"]
            
    class FakeRankingForFallback:
        def __init__(self):
            self.actual_date = date(2026, 6, 12)
        def fetch(self, as_of_date):
            return {"2330": {"score_bp": 7000}}
        def fetch_previous(self, as_of_date):
            return {"2330": {"score_bp": 6800}}

    service = WatchlistTriggerService(FakeWatchlistForFallback(), FakeRankingForFallback())
    snapshot = service.build_snapshot(date(2026, 6, 15))
    
    assert snapshot.quality == DecisionDeskQuality.DEGRADED
    assert snapshot.as_of_date == date(2026, 6, 12)
    assert "watchlist_trigger_as_of_fallback:2026-06-12" in snapshot.warnings
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_watchlist_trigger_service.py::test_watchlist_trigger_service_uses_actual_date_fallback_and_warning -v
```
Expected output:
```text
AssertionError: assert <DecisionDeskQuality.OBSERVED: 'observed'> == <DecisionDeskQuality.DEGRADED: 'degraded'>
```

- [ ] **Step 3: Write minimal implementation**

Open `app_module/watchlist_trigger_service.py` and replace `build_snapshot`:

```python
    def build_snapshot(self, as_of_date: date) -> WatchlistTriggerSummary:
        try:
            watchlist_codes = self._normalize_watchlist(self.watchlist_provider.fetch(as_of_date))
        except Exception as exc:  # noqa: BLE001
            return WatchlistTriggerSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=(f"watchlist_trigger_watchlist_provider_error:{exc}",),
            )

        if not watchlist_codes:
            return WatchlistTriggerSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("watchlist_trigger_watchlist_missing",),
                trigger_count=0,
                triggered_codes=(),
            )

        try:
            current_scores = self._normalize_ranking(self.ranking_provider.fetch(as_of_date))
        except Exception as exc:  # noqa: BLE001
            return WatchlistTriggerSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=(f"watchlist_trigger_ranking_provider_error:{exc}",),
                trigger_count=0,
                triggered_codes=(),
            )

        previous_scores = self._load_previous_scores(as_of_date)

        new_candidates: list[str] = []
        increases: list[str] = []
        decreases: list[str] = []
        data_insufficient_codes: list[str] = []
        risk_codes: list[str] = []
        warnings: list[str] = []

        actual_date = getattr(self.ranking_provider, "actual_date", as_of_date)
        if isinstance(actual_date, str):
            try:
                actual_date = datetime.strptime(str(actual_date).replace("-", "").replace("/", ""), "%Y%m%d").date()
            except ValueError:
                actual_date = as_of_date

        is_fallback = False
        if actual_date != as_of_date:
            is_fallback = True
            warnings.append(f"watchlist_trigger_as_of_fallback:{actual_date.isoformat()}")

        for code in watchlist_codes:
            current = self._read_score(current_scores.get(code))
            if current is None:
                data_insufficient_codes.append(code)
                warnings.append(f"watchlist_trigger_data_insufficient:{code}")
                continue

            if self._is_risk(current_scores.get(code)):
                risk_codes.append(code)
                warnings.append(f"watchlist_trigger_risk_alert:{code}")

            previous = self._read_score(previous_scores.get(code))
            if current < self.entry_threshold_bp:
                continue

            if previous is None or previous < self.entry_threshold_bp:
                new_candidates.append(code)
            elif current > previous:
                increases.append(code)
            elif current < previous:
                decreases.append(code)

        triggered_codes = tuple(dict.fromkeys(new_candidates + increases + decreases))
        top_signal = self._build_top_signal(new_candidates, increases, decreases)
        has_data_gap = len(data_insufficient_codes) > 0
        has_any_warning = bool(warnings)

        if is_fallback:
            quality = DecisionDeskQuality.DEGRADED
        elif has_any_warning:
            # Degraded is reserved for hard errors. Data gaps remain estimated.
            quality = DecisionDeskQuality.ESTIMATED
        else:
            quality = DecisionDeskQuality.OBSERVED

        return WatchlistTriggerSummary(
            as_of_date=actual_date,
            quality=quality,
            warnings=tuple(warnings),
            trigger_count=len(triggered_codes),
            triggered_codes=triggered_codes,
            top_signal=top_signal,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_watchlist_trigger_service.py::test_watchlist_trigger_service_uses_actual_date_fallback_and_warning -v
```
Expected output:
```text
PASSED [100%]
```

- [ ] **Step 5: Commit**

```bash
git add app_module/watchlist_trigger_service.py tests/test_watchlist_trigger_service.py
git commit -m "feat: add fallback date tracking and warnings to WatchlistTriggerService"
```

---

### Task 3: Inject Watchlist Trigger Providers into Main UI Window

**Files:**
- Modify: `ui_qt/main.py`
- Test: `tests/test_ui_qt_decision_desk_main_integration.py`

- [ ] **Step 1: Write the failing test**

Open `tests/test_ui_qt_decision_desk_main_integration.py` and append:

```python
def test_watchlist_trigger_service_is_injected_into_decision_desk_builder(monkeypatch):
    app()
    _TrackingDecisionDeskBuilder.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)

    target_window = _build_main_window()
    target_window.config = types.SimpleNamespace(db_file="C:/tmp/not-used.db")
    target_window._setup_ui()

    assert _TrackingDecisionDeskBuilder.instances
    builder = _TrackingDecisionDeskBuilder.instances[-1]
    assert builder.kwargs["watchlist_trigger_service"] is not None
    assert callable(getattr(builder.kwargs["watchlist_trigger_service"], "build_snapshot", None))
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_decision_desk_main_integration.py::test_watchlist_trigger_service_is_injected_into_decision_desk_builder -v
```
Expected output:
```text
AssertionError: assert None is not None
```

- [ ] **Step 3: Write minimal implementation**

Open `ui_qt/main.py` and modify `_create_decision_desk_builder` method.

Add imports near the top of the file:
```python
from app_module.watchlist_trigger_service import WatchlistTriggerService, WatchlistServiceWatchlistProvider, SQLiteRankingProvider
```

Replace `_create_decision_desk_builder` method:
```python
    def _create_decision_desk_builder(self) -> DecisionDeskSnapshotBuilder:
        provider = self._DecisionDeskMarketRegimeProvider(self.regime_service)
        market_breadth_service = None
        try:
            market_breadth_service = MarketBreadthService(
                SQLiteDailyPriceMarketBreadthProvider(self.config.db_file)
            )
        except Exception as exc:
            print(f"[MainWindow] 決策桌面 MarketBreadthService 初始化失敗：{exc}")

        sector_rotation_service = None
        try:
            sector_rotation_service = SectorRotationService(
                SQLiteIndustryIndexSectorRotationProvider(self.config.db_file)
            )
        except Exception as exc:
            print(f"[MainWindow] 決策桌面 SectorRotationService 初始化失敗：{exc}")

        watchlist_trigger_service = None
        try:
            watchlist_trigger_service = WatchlistTriggerService(
                WatchlistServiceWatchlistProvider(self.watchlist_service),
                SQLiteRankingProvider(self.config.db_file),
            )
        except Exception as exc:
            print(f"[MainWindow] 決策桌面 WatchlistTriggerService 初始化失敗：{exc}")

        portfolio_alert_service = None
        try:
            condition_monitor = PortfolioConditionMonitor()
            chip_summary_provider = None
            if hasattr(self, "broker_flow_service") and self.broker_flow_service is not None:
                provider_candidate = getattr(self.broker_flow_service, "get_stock_chip_summary", None)
                if callable(provider_candidate):
                    chip_summary_provider = self.broker_flow_service
            portfolio_alert_service = PortfolioAlertService(
                portfolio_service=self.portfolio_service,
                condition_monitor=condition_monitor,
                chip_summary_provider=chip_summary_provider,
            )
        except Exception as exc:
            print(f"[MainWindow] 決策桌面 PortfolioAlertService 初始化失敗：{exc}")

        return DecisionDeskSnapshotBuilder(
            provider=provider,
            market_breadth_service=market_breadth_service,
            sector_rotation_service=sector_rotation_service,
            watchlist_trigger_service=watchlist_trigger_service,
            portfolio_alert_service=portfolio_alert_service,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_decision_desk_main_integration.py::test_watchlist_trigger_service_is_injected_into_decision_desk_builder -v
```
Expected output:
```text
PASSED [100%]
```

- [ ] **Step 5: Commit**

```bash
git add ui_qt/main.py tests/test_ui_qt_decision_desk_main_integration.py
git commit -m "feat: inject WatchlistTriggerService into Main Window"
```

---

### Task 4: Add Comprehensive Tests for New Providers

**Files:**
- Modify: `tests/test_watchlist_trigger_service.py`

- [ ] **Step 1: Write the failing test**

Open `tests/test_watchlist_trigger_service.py` and append:

```python
def test_watchlist_service_watchlist_provider_fetches_stocks(tmp_path):
    import json
    from app_module.watchlist_service import WatchlistService
    from app_module.watchlist_trigger_service import WatchlistServiceWatchlistProvider
    
    class FakeConfig:
        def __init__(self, path):
            self.output_root = path
        def resolve_output_path(self, name):
            return self.output_root / name

    config = FakeConfig(tmp_path)
    watchlist_dir = tmp_path / "watchlist"
    watchlist_dir.mkdir(parents=True, exist_ok=True)
    default_json = watchlist_dir / "default.json"
    default_json.write_text(
        json.dumps({
            "version": 1,
            "name": "預設觀察清單",
            "description": "系統預設觀察清單",
            "created_at": "2026-06-15T12:00:00",
            "updated_at": "2026-06-15T12:00:00",
            "items": [
                {
                    "stock_code": "2330",
                    "stock_name": "台積電",
                    "added_at": "2026-06-15T12:00:00",
                    "source": "manual",
                    "notes": "",
                    "tags": []
                }
            ]
        }),
        encoding="utf-8"
    )
    watchlist_service = WatchlistService(config)
    provider = WatchlistServiceWatchlistProvider(watchlist_service)
    stocks = provider.fetch(date(2026, 6, 15))
    assert len(stocks) == 1
    assert stocks[0]["stock_code"] == "2330"


def test_sqlite_ranking_provider_queries_technical_indicators(tmp_path):
    import sqlite3
    from app_module.watchlist_trigger_service import SQLiteRankingProvider
    
    db_path = tmp_path / "twstock.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE technical_indicators (
                日期 TEXT,
                證券代號 TEXT,
                RSI REAL,
                Close REAL,
                lowerband REAL,
                PRIMARY KEY (證券代號, 日期)
            )
            """
        )
        conn.executemany(
            "INSERT INTO technical_indicators (日期, 證券代號, RSI, Close, lowerband) VALUES (?, ?, ?, ?, ?)",
            [
                ("20260612", "2330", 75.0, 100.0, 95.0),
                ("20260612", "2603", 15.0, 50.0, 52.0),
                ("20260615", "2330", 82.0, 110.0, 98.0),
                ("20260615", "2603", 18.0, 48.0, 50.0),
            ]
        )

    provider = SQLiteRankingProvider(db_path)
    scores = provider.fetch(date(2026, 6, 15))
    
    assert scores["2330"]["score_bp"] == 8200
    assert scores["2330"]["risk_alert"] is True
    assert scores["2603"]["score_bp"] == 1800
    assert scores["2603"]["risk_alert"] is True
    
    prev_scores = provider.fetch_previous(date(2026, 6, 15))
    assert prev_scores["2330"]["score_bp"] == 7500
    assert prev_scores["2330"]["risk_alert"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_watchlist_trigger_service.py::test_watchlist_service_watchlist_provider_fetches_stocks tests/test_watchlist_trigger_service.py::test_sqlite_ranking_provider_queries_technical_indicators -v
```
Expected output:
```text
PASSED [ 50%]
PASSED [100%]
```

- [ ] **Step 3: Write minimal implementation**

No implementation is needed as these test the existing code.

- [ ] **Step 4: Run test to verify it passes**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_watchlist_trigger_service.py -v
```
Expected output:
```text
5 passed in 0.5s
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_watchlist_trigger_service.py
git commit -m "test: add comprehensive integration tests for Watchlist and SQLite Ranking providers"
```

---

### Task 5: Documentations Synchronization

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [ ] **Step 1: Write the failing test**

Run:
```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```
Expected output:
```text
Success: no issues found in 169 source files
```

- [ ] **Step 2: Run test to verify it fails**

N/A

- [ ] **Step 3: Write minimal implementation**

Update `docs/00_core/PROJECT_SNAPSHOT.md` around lines 49-51 to update the status of Watchlist Trigger v1:
```diff
-Sector Rotation v1 與 Portfolio Alert 已接主 UI。... Watchlist Trigger 若 provider 尚未接線會以 MISSING / DEGRADED / ESTIMATED 表示缺口
+Sector Rotation v1、Watchlist Trigger v1 與 Portfolio Alert 已接主 UI。... Watchlist Trigger v1 由 WatchlistService 結合 SQLite technical_indicators 動態追蹤新進與強度變化。
```

Update `docs/00_core/ROADMAP_6M_ENGINEERING.md` under Section 5 list:
```diff
-下一步補齊 Watchlist Trigger 的主 UI 真實資料來源
+下一步補齊 Portfolio Alert 的主 UI 真實資料來源
```

Update `docs/01_architecture/system_architecture.md`:
```diff
-其餘 Watchlist / Portfolio Alert 仍保留缺口降級機制。
+Watchlist Trigger v1 已由 WatchlistService 與 SQLite technical_indicators 獲取真實資料源，其餘 Portfolio Alert 仍保留缺口降級機制。
```

Update `docs/07_guides/APPLICATION_MANUAL.md`:
```diff
-Watchlist Trigger 目前仍為逐步接線；缺口時只會降級，不會強制補值。
+Watchlist Trigger v1 已對接真實資料。系統將載入當前觀察清單，並依據 SQLite 中的技術指標計算 RSI 評分 (RSI * 100) 與風險警示 (RSI > 80 或 RSI < 20，或收盤價低於布林通道下軌)。若該日無資料會 fallback 採用最近交易日並在 warnings 顯示。
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```powershell
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```
Expected output:
```text
通過: 21
失敗: 0
```

- [ ] **Step 5: Commit**

```bash
git add docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/01_architecture/system_architecture.md docs/07_guides/APPLICATION_MANUAL.md
git commit -m "docs: synchronize documentation for Watchlist Trigger v1 connection"
```
