# Daily Decision Desk Relative Strength Liquidity Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Daily Decision Desk Relative Strength / Liquidity Ranking v1 so the desk can surface strong research candidates and low-liquidity risk warnings from governed SQLite data.

**Architecture:** Add a new application service, `RelativeStrengthLiquidityService`, with an injectable provider pattern matching the existing Market Breadth and Sector Rotation services. The service reads a historical price/volume snapshot, computes 5-day and 20-day relative strength plus average turnover using `Decimal`, and returns a new `RelativeStrengthLiquiditySummary` DTO through `DecisionDeskSnapshotBuilder`. The Qt view renders only DTO fields and never recomputes ranking, liquidity, screening, or recommendation logic.

**Tech Stack:** Python, PySide6, pandas, SQLite read-only URI connections, Decimal arithmetic, pytest, mypy.

---

## File Structure

- Modify: `app_module/decision_desk_dtos.py`
  - Add `RelativeStrengthLiquiditySummary`.
  - Add the new section to `DecisionDeskSnapshot.to_dict()`.
- Modify: `app_module/decision_desk_service.py`
  - Add protocol and optional service injection for Relative Strength / Liquidity Ranking.
  - Include the section in quality aggregation and warning collection.
- Create: `app_module/relative_strength_liquidity_service.py`
  - Implement `RelativeStrengthLiquidityService`.
  - Implement `SQLiteDailyPriceRelativeStrengthLiquidityProvider`.
  - Preserve fallback date, quality, and warnings behavior.
- Modify: `ui_qt/main.py`
  - Instantiate and inject the new service into `DecisionDeskSnapshotBuilder`.
- Modify: `ui_qt/views/decision_desk_view.py`
  - Render the new section in the Daily Decision Desk UI.
- Modify: tests:
  - `tests/test_relative_strength_liquidity_service.py`
  - `tests/test_decision_desk_service.py`
  - `tests/test_ui_qt_decision_desk_main_integration.py`
  - `tests/test_ui_qt_decision_desk_view.py`
- Modify docs after behavior lands:
  - `docs/00_core/PROJECT_SNAPSHOT.md`
  - `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - `docs/01_architecture/system_architecture.md`
  - `docs/07_guides/APPLICATION_MANUAL.md`
  - `docs/00_core/DOCUMENTATION_INDEX.md`

---

### Task 1: Add Relative Strength / Liquidity DTO and Snapshot Builder Contract

**Files:**
- Modify: `app_module/decision_desk_dtos.py`
- Modify: `app_module/decision_desk_service.py`
- Test: `tests/test_decision_desk_service.py`

- [ ] **Step 1: Write the failing DTO serialization test**

Append this test to `tests/test_decision_desk_service.py`:

```python
def test_decision_desk_snapshot_serializes_relative_strength_liquidity_section():
    sample_date = date(2026, 6, 15)
    builder = DecisionDeskSnapshotBuilder(
        provider=FakeProvider(),
        relative_strength_liquidity_service=FakeSectionService(
            "relative_strength_liquidity",
            RelativeStrengthLiquiditySummary(
                as_of_date=sample_date,
                quality=DecisionDeskQuality.OBSERVED,
                warnings=(),
                top_strength_codes=("2330", "2454"),
                low_liquidity_codes=("1101",),
                meta={
                    "ranking": [
                        {"stock_code": "2330", "strength_20d_bp": 1200, "avg_turnover": 900000000},
                        {"stock_code": "2454", "strength_20d_bp": 900, "avg_turnover": 700000000},
                    ]
                },
            ),
        ),
    )

    snapshot = builder.build_snapshot(sample_date)
    payload = snapshot.to_dict()

    assert snapshot.relative_strength_liquidity.quality == DecisionDeskQuality.OBSERVED
    assert payload["relative_strength_liquidity"]["top_strength_codes"] == ["2330", "2454"]
    assert payload["relative_strength_liquidity"]["low_liquidity_codes"] == ["1101"]
    assert payload["relative_strength_liquidity"]["meta"]["ranking"][0]["stock_code"] == "2330"
```

At the top of `tests/test_decision_desk_service.py`, add `RelativeStrengthLiquiditySummary` to the import from `app_module.decision_desk_dtos`.

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_service.py::test_decision_desk_snapshot_serializes_relative_strength_liquidity_section -q
```

Expected: FAIL with import or constructor error because `RelativeStrengthLiquiditySummary` and `relative_strength_liquidity_service` do not exist yet.

- [ ] **Step 3: Add RelativeStrengthLiquiditySummary DTO**

In `app_module/decision_desk_dtos.py`, add this dataclass after `SectorRotationSummary` and before `WatchlistTriggerSummary`:

```python
@dataclass(frozen=True)
class RelativeStrengthLiquiditySummary:
    as_of_date: date | None
    quality: DecisionDeskQuality
    warnings: tuple[str, ...]
    top_strength_codes: tuple[str, ...] = ()
    weak_strength_codes: tuple[str, ...] = ()
    low_liquidity_codes: tuple[str, ...] = ()
    meta: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", _normalize_warnings(self.warnings))
        object.__setattr__(self, "top_strength_codes", tuple(str(code) for code in self.top_strength_codes))
        object.__setattr__(self, "weak_strength_codes", tuple(str(code) for code in self.weak_strength_codes))
        object.__setattr__(self, "low_liquidity_codes", tuple(str(code) for code in self.low_liquidity_codes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "quality": self.quality.value,
            "warnings": list(self.warnings),
            "top_strength_codes": list(self.top_strength_codes),
            "weak_strength_codes": list(self.weak_strength_codes),
            "low_liquidity_codes": list(self.low_liquidity_codes),
            "meta": _as_dict(self.meta) if self.meta is not None else None,
        }
```

Update `DecisionDeskSnapshot`:

```python
    relative_strength_liquidity: RelativeStrengthLiquiditySummary
```

Place it after `sector_rotation` and before `watchlist_triggers`.

In `DecisionDeskSnapshot.__post_init__`, update the required-section guard:

```python
        if (
            self.market_regime is None
            or self.market_breadth is None
            or self.sector_rotation is None
            or self.relative_strength_liquidity is None
        ):
            raise ValueError("all decision sections must be provided")
```

In `DecisionDeskSnapshot.to_dict()`, add:

```python
            "relative_strength_liquidity": self.relative_strength_liquidity.to_dict(),
```

Place it after `"sector_rotation"`.

- [ ] **Step 4: Add builder protocol and fallback section**

In `app_module/decision_desk_service.py`, add `RelativeStrengthLiquiditySummary` to the DTO imports.

Add this protocol after `SectorRotationSectionService`:

```python
class RelativeStrengthLiquiditySectionService(Protocol):
    def build_snapshot(self, as_of_date: date) -> RelativeStrengthLiquiditySummary: ...
```

Add a constructor parameter:

```python
        relative_strength_liquidity_service: RelativeStrengthLiquiditySectionService | None = None,
```

Assign it:

```python
        self.relative_strength_liquidity_service = relative_strength_liquidity_service
```

In `build_snapshot`, insert:

```python
        relative_strength_liquidity = self._build_relative_strength_liquidity(as_of_date)
```

Place it after sector rotation. Include it in `sections` and pass it into `DecisionDeskSnapshot(...)`:

```python
            relative_strength_liquidity=relative_strength_liquidity,
```

Add this method after `_build_sector_rotation`:

```python
    def _build_relative_strength_liquidity(self, as_of_date: date) -> RelativeStrengthLiquiditySummary:
        if self.relative_strength_liquidity_service is not None:
            try:
                snapshot = self.relative_strength_liquidity_service.build_snapshot(as_of_date)
            except Exception as exc:  # noqa: BLE001
                return RelativeStrengthLiquiditySummary(
                    as_of_date=as_of_date,
                    quality=DecisionDeskQuality.DEGRADED,
                    warnings=(f"relative_strength_liquidity_fetch_error:{exc}",),
                )
            if snapshot is not None:
                return snapshot

        return RelativeStrengthLiquiditySummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.MISSING,
            warnings=("relative_strength_liquidity_missing",),
        )
```

Update `_collect_snapshot_warnings` by adding:

```python
            ("relative_strength_liquidity", relative_strength_liquidity.warnings),
```

Place it after sector rotation.

- [ ] **Step 5: Run focused builder test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_service.py::test_decision_desk_snapshot_serializes_relative_strength_liquidity_section -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```powershell
git add app_module\decision_desk_dtos.py app_module\decision_desk_service.py tests\test_decision_desk_service.py
git commit -m "feat: add decision desk relative strength liquidity section"
```

---

### Task 2: Implement RelativeStrengthLiquidityService

**Files:**
- Create: `app_module/relative_strength_liquidity_service.py`
- Test: `tests/test_relative_strength_liquidity_service.py`

- [ ] **Step 1: Create failing service tests**

Create `tests/test_relative_strength_liquidity_service.py` with:

```python
from datetime import date, timedelta

import pandas as pd

from app_module.decision_desk_dtos import DecisionDeskQuality
from app_module.relative_strength_liquidity_service import RelativeStrengthLiquidityService


DATE_COL = "日期"
CODE_COL = "證券代號"
CLOSE_COL = "收盤價"
VOLUME_COL = "成交股數"


class FakeProvider:
    def __init__(self, frame):
        self.frame = frame

    def fetch(self, as_of_date: date):
        return self.frame


def _rows_for_stock(stock_code: str, start_close: int, end_close: int, volume: int) -> list[dict[str, str]]:
    start = date(2026, 5, 26)
    rows = []
    for offset in range(21):
        day = start + timedelta(days=offset)
        close = start_close + ((end_close - start_close) * offset // 20)
        rows.append(
            {
                DATE_COL: day.isoformat(),
                CODE_COL: stock_code,
                CLOSE_COL: str(close),
                VOLUME_COL: str(volume),
            }
        )
    return rows


def test_relative_strength_liquidity_service_ranks_strength_and_low_liquidity():
    frame = pd.DataFrame(
        _rows_for_stock("2330", 100, 120, 10_000_000)
        + _rows_for_stock("1101", 50, 48, 1_000)
        + _rows_for_stock("2454", 200, 215, 5_000_000)
    )
    service = RelativeStrengthLiquidityService(
        FakeProvider(frame),
        top_n=2,
        min_avg_turnover=20_000_000,
    )

    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.top_strength_codes == ("2330", "2454")
    assert snapshot.weak_strength_codes == ("1101",)
    assert snapshot.low_liquidity_codes == ("1101",)
    ranking = snapshot.meta["ranking"]
    assert ranking[0]["stock_code"] == "2330"
    assert ranking[0]["strength_20d_bp"] == 2000
    assert ranking[0]["strength_5d_bp"] == 435
```

Append this fallback/quality test:

```python
def test_relative_strength_liquidity_service_marks_degraded_when_history_is_insufficient():
    frame = pd.DataFrame(
        [
            {DATE_COL: "2026-06-10", CODE_COL: "2330", CLOSE_COL: "116", VOLUME_COL: "10000000"},
            {DATE_COL: "2026-06-11", CODE_COL: "2330", CLOSE_COL: "117", VOLUME_COL: "10000000"},
            {DATE_COL: "2026-06-12", CODE_COL: "2330", CLOSE_COL: "118", VOLUME_COL: "10000000"},
            {DATE_COL: "2026-06-13", CODE_COL: "2330", CLOSE_COL: "119", VOLUME_COL: "10000000"},
            {DATE_COL: "2026-06-14", CODE_COL: "2330", CLOSE_COL: "120", VOLUME_COL: "10000000"},
            {DATE_COL: "2026-06-15", CODE_COL: "2330", CLOSE_COL: "121", VOLUME_COL: "10000000"},
        ]
    )
    service = RelativeStrengthLiquidityService(FakeProvider(frame), top_n=3)

    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.DEGRADED
    assert snapshot.top_strength_codes == ()
    assert "relative_strength_liquidity_insufficient_history" in snapshot.warnings
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_relative_strength_liquidity_service.py -q
```

Expected: FAIL because `app_module.relative_strength_liquidity_service` does not exist.

- [ ] **Step 3: Create service implementation**

Create `app_module/relative_strength_liquidity_service.py`:

```python
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from app_module.decision_desk_dtos import DecisionDeskQuality, RelativeStrengthLiquiditySummary


class RelativeStrengthLiquidityProvider(Protocol):
    def fetch(self, as_of_date: date) -> pd.DataFrame: ...


class RelativeStrengthLiquidityService:
    """Build stock relative strength and liquidity ranking for Daily Decision Desk."""

    def __init__(
        self,
        provider: RelativeStrengthLiquidityProvider,
        *,
        top_n: int = 10,
        min_avg_turnover: int = 20_000_000,
    ) -> None:
        self.provider = provider
        self.top_n = top_n
        self.min_avg_turnover = Decimal(int(min_avg_turnover))

    def build_snapshot(self, as_of_date: date) -> RelativeStrengthLiquiditySummary:
        try:
            frame = self.provider.fetch(as_of_date)
        except Exception as exc:  # noqa: BLE001
            return RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=(f"relative_strength_liquidity_provider_error:{exc}",),
            )

        if frame is None or frame.empty:
            return RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("relative_strength_liquidity_missing",),
            )

        result = self._build_from_frame(frame, as_of_date)
        return result

    def _build_from_frame(self, frame: pd.DataFrame, as_of_date: date) -> RelativeStrengthLiquiditySummary:
        required = {"日期", "證券代號", "收盤價", "成交股數"}
        if not required.issubset(set(frame.columns)):
            return RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=("relative_strength_liquidity_missing_required_columns",),
            )

        data = frame.copy()
        data["_date"] = data["日期"].map(self._parse_date)
        data["_close"] = data["收盤價"].map(self._to_decimal)
        data["_volume"] = data["成交股數"].map(self._to_decimal)
        data["_code"] = data["證券代號"].map(lambda value: str(value).strip())
        data = data.dropna(subset=["_date", "_close", "_volume", "_code"])

        if data.empty:
            return RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("relative_strength_liquidity_missing",),
            )

        eligible_dates = [item for item in data["_date"].unique() if item <= as_of_date]
        if not eligible_dates:
            return RelativeStrengthLiquiditySummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("relative_strength_liquidity_missing",),
            )
        effective_date = max(eligible_dates)
        warnings: list[str] = []
        if effective_date != as_of_date:
            warnings.append(f"relative_strength_liquidity_as_of_fallback:{effective_date.isoformat()}")

        ranking: list[dict[str, Any]] = []
        skipped = 0
        for stock_code, stock_frame in data.groupby("_code", sort=False):
            item = self._rank_stock(str(stock_code), stock_frame, effective_date)
            if item is None:
                skipped += 1
                continue
            ranking.append(item)

        if not ranking:
            return RelativeStrengthLiquiditySummary(
                as_of_date=effective_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=tuple(warnings + ["relative_strength_liquidity_insufficient_history"]),
            )

        ranking = sorted(ranking, key=lambda item: (-int(item["strength_20d_bp"]), -int(item["strength_5d_bp"]), item["stock_code"]))
        weak = sorted(ranking, key=lambda item: (int(item["strength_20d_bp"]), int(item["strength_5d_bp"]), item["stock_code"]))
        low_liquidity = tuple(
            item["stock_code"]
            for item in ranking
            if Decimal(str(item["avg_turnover"])) < self.min_avg_turnover
        )

        if skipped:
            warnings.append(f"relative_strength_liquidity_skipped_symbols:{skipped}")

        quality = DecisionDeskQuality.OBSERVED if not warnings else DecisionDeskQuality.DEGRADED
        return RelativeStrengthLiquiditySummary(
            as_of_date=effective_date,
            quality=quality,
            warnings=tuple(warnings),
            top_strength_codes=tuple(item["stock_code"] for item in ranking[: self.top_n]),
            weak_strength_codes=tuple(item["stock_code"] for item in weak[: self.top_n] if int(item["strength_20d_bp"]) < 0),
            low_liquidity_codes=low_liquidity,
            meta={
                "source": "relative_strength_liquidity_service",
                "min_avg_turnover": int(self.min_avg_turnover),
                "ranking": ranking[: self.top_n],
            },
        )

    def _rank_stock(self, stock_code: str, frame: pd.DataFrame, effective_date: date) -> dict[str, Any] | None:
        history = frame.sort_values("_date").drop_duplicates(subset=["_date"], keep="last")
        history = history.loc[history["_date"] <= effective_date]
        if len(history) < 21:
            return None
        current_rows = history.loc[history["_date"] == effective_date]
        if current_rows.empty:
            return None
        current = current_rows.iloc[-1]
        close_now = current["_close"]
        if close_now is None or close_now <= 0:
            return None

        close_5 = self._lookback_close(history, effective_date, 5)
        close_20 = self._lookback_close(history, effective_date, 20)
        if close_5 is None or close_20 is None or close_5 <= 0 or close_20 <= 0:
            return None

        strength_5d_bp = self._return_bp(close_now, close_5)
        strength_20d_bp = self._return_bp(close_now, close_20)
        avg_turnover = self._avg_turnover(history)
        if avg_turnover is None:
            return None

        return {
            "stock_code": stock_code,
            "strength_5d_bp": strength_5d_bp,
            "strength_20d_bp": strength_20d_bp,
            "avg_turnover": int(avg_turnover),
        }

    @staticmethod
    def _lookback_close(history: pd.DataFrame, effective_date: date, target_days: int) -> Decimal | None:
        prior = history.loc[history["_date"] < effective_date]
        if len(prior) < target_days:
            return None
        value = prior.iloc[-target_days]["_close"]
        return value if isinstance(value, Decimal) else None

    @staticmethod
    def _avg_turnover(history: pd.DataFrame) -> Decimal | None:
        turnovers: list[Decimal] = []
        for _, row in history.tail(20).iterrows():
            close_value = row["_close"]
            volume_value = row["_volume"]
            if isinstance(close_value, Decimal) and isinstance(volume_value, Decimal):
                turnovers.append(close_value * volume_value)
        if not turnovers:
            return None
        return sum(turnovers, Decimal("0")) / Decimal(len(turnovers))

    @staticmethod
    def _return_bp(current: Decimal, base: Decimal) -> int:
        value = ((current - base) / base) * Decimal("10000")
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @staticmethod
    def _to_decimal(value: object) -> Decimal | None:
        if value is None or isinstance(value, bool) or pd.isna(value):
            return None
        try:
            parsed = Decimal(str(value).replace(",", ""))
        except (InvalidOperation, ValueError, TypeError):
            return None
        return parsed if parsed.is_finite() else None

    @staticmethod
    def _parse_date(value: object) -> date | None:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        text = str(value).strip().replace("-", "").replace("/", "")
        if len(text) != 8 or not text.isdigit():
            return None
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None


class SQLiteDailyPriceRelativeStrengthLiquidityProvider:
    """Read-only provider that supplies price and volume history from SQLite daily_prices."""

    def __init__(self, db_path: str | Path, *, lookback_days: int = 40) -> None:
        self.db_path = Path(db_path)
        self.lookback_days = lookback_days

    def fetch(self, as_of_date: date) -> pd.DataFrame:
        if not self.db_path.exists():
            return pd.DataFrame()
        target_key = as_of_date.strftime("%Y%m%d")
        try:
            db_uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(db_uri, uri=True) as conn:
                conn.execute("PRAGMA query_only=ON")
                date_rows = pd.read_sql_query(
                    """
                    SELECT DISTINCT 日期
                    FROM daily_prices
                    WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') <= ?
                    ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') DESC
                    LIMIT ?
                    """,
                    conn,
                    params=(target_key, self.lookback_days),
                )
                if date_rows.empty:
                    return pd.DataFrame()
                normalized_dates = [
                    str(item).replace("-", "").replace("/", "")
                    for item in date_rows["日期"].tolist()
                ]
                placeholders = ",".join("?" for _ in normalized_dates)
                return pd.read_sql_query(
                    f"""
                    SELECT 日期, 證券代號, 收盤價, 成交股數
                    FROM daily_prices
                    WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') IN ({placeholders})
                    ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') ASC, 證券代號 ASC
                    """,
                    conn,
                    params=tuple(normalized_dates),
                )
        except sqlite3.OperationalError:
            return pd.DataFrame()
```

- [ ] **Step 4: Run focused service tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_relative_strength_liquidity_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add app_module\relative_strength_liquidity_service.py tests\test_relative_strength_liquidity_service.py
git commit -m "feat: add relative strength liquidity service"
```

---

### Task 3: Inject Service into MainWindow and Render in Daily Decision Desk

**Files:**
- Modify: `ui_qt/main.py`
- Modify: `ui_qt/views/decision_desk_view.py`
- Test: `tests/test_ui_qt_decision_desk_main_integration.py`
- Test: `tests/test_ui_qt_decision_desk_view.py`

- [ ] **Step 1: Add failing main injection test**

Append to `tests/test_ui_qt_decision_desk_main_integration.py`:

```python
def test_relative_strength_liquidity_service_is_injected_into_decision_desk_builder(monkeypatch):
    app()
    _TrackingDecisionDeskBuilder.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)

    target_window = _build_main_window()
    target_window.config = types.SimpleNamespace(db_file="C:/tmp/not-used.db")
    target_window._setup_ui()

    assert _TrackingDecisionDeskBuilder.instances
    builder = _TrackingDecisionDeskBuilder.instances[-1]
    assert builder.kwargs["relative_strength_liquidity_service"] is not None
    assert callable(getattr(builder.kwargs["relative_strength_liquidity_service"], "build_snapshot", None))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_main_integration.py::test_relative_strength_liquidity_service_is_injected_into_decision_desk_builder -q
```

Expected: FAIL because `relative_strength_liquidity_service` is not passed into the builder.

- [ ] **Step 3: Inject service in ui_qt/main.py**

In `ui_qt/main.py`, add imports:

```python
from app_module.relative_strength_liquidity_service import (
    RelativeStrengthLiquidityService,
    SQLiteDailyPriceRelativeStrengthLiquidityProvider,
)
```

In `_create_decision_desk_builder`, after `sector_rotation_service` initialization and before `portfolio_alert_service`, add:

```python
        relative_strength_liquidity_service = None
        try:
            relative_strength_liquidity_service = RelativeStrengthLiquidityService(
                SQLiteDailyPriceRelativeStrengthLiquidityProvider(self.config.db_file)
            )
        except Exception as exc:
            print(f"[MainWindow] 決策桌面 RelativeStrengthLiquidityService 初始化失敗：{exc}")
```

In the `DecisionDeskSnapshotBuilder(...)` call, add:

```python
            relative_strength_liquidity_service=relative_strength_liquidity_service,
```

Place it after `sector_rotation_service=sector_rotation_service`.

- [ ] **Step 4: Add UI render support**

In `ui_qt/views/decision_desk_view.py`, add labels in `_setup_ui()` after sector rotation labels:

```python
        self.relative_strength_liquidity_status = QLabel("")
        self.relative_strength_liquidity_value = QLabel("")
```

Add a section row after 產業輪動:

```python
        sections_layout.addWidget(self._make_section_row("強弱與流動性", self.relative_strength_liquidity_status, self.relative_strength_liquidity_value))
```

In `_render_snapshot()`, after sector rotation rendering, add:

```python
        self.relative_strength_liquidity_status.setText(
            f"品質：{self._quality_label(snapshot.relative_strength_liquidity.quality)}"
        )
        self.relative_strength_liquidity_value.setText(
            f"強勢：{', '.join(snapshot.relative_strength_liquidity.top_strength_codes) if snapshot.relative_strength_liquidity.top_strength_codes else '無'}；"
            f"弱勢：{', '.join(snapshot.relative_strength_liquidity.weak_strength_codes) if snapshot.relative_strength_liquidity.weak_strength_codes else '無'}；"
            f"低流動性：{', '.join(snapshot.relative_strength_liquidity.low_liquidity_codes) if snapshot.relative_strength_liquidity.low_liquidity_codes else '無'}"
        )
```

In `_collect_warnings()`, add:

```python
            ("強弱與流動性", snapshot.relative_strength_liquidity.warnings),
```

In `_display_exception_snapshot()`, pass an empty degraded section:

```python
            relative_strength_liquidity=_EmptySection(DecisionDeskQuality.DEGRADED, warnings=(f"強弱與流動性:{error_message}",)),
```

In `_EmptySection.__init__`, add:

```python
        self.top_strength_codes: tuple[str, ...] = ()
        self.weak_strength_codes: tuple[str, ...] = ()
        self.low_liquidity_codes: tuple[str, ...] = ()
```

- [ ] **Step 5: Update UI tests to include section in fake snapshots**

In `tests/test_ui_qt_decision_desk_view.py`, import `RelativeStrengthLiquiditySummary` and add this field to every `DecisionDeskSnapshot(...)` constructor:

```python
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            top_strength_codes=("2330",),
            weak_strength_codes=("1101",),
            low_liquidity_codes=("2409",),
        ),
```

In `tests/test_ui_qt_decision_desk_main_integration.py`, update `_snapshot()` to include:

```python
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.MISSING,
            warnings=("relative_strength_liquidity_missing",),
        ),
```

- [ ] **Step 6: Run UI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_main_integration.py tests\test_ui_qt_decision_desk_view.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```powershell
git add ui_qt\main.py ui_qt\views\decision_desk_view.py tests\test_ui_qt_decision_desk_main_integration.py tests\test_ui_qt_decision_desk_view.py
git commit -m "feat: show relative strength liquidity in decision desk"
```

---

### Task 4: Documentation Coverage

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`

- [ ] **Step 1: Update PROJECT_SNAPSHOT.md**

In the Daily Decision Desk current-state bullet, add this sentence:

```markdown
Relative Strength / Liquidity Ranking v1 已由 SQLite `daily_prices` 推導 5 / 20 日相對強度與平均成交金額，並揭露低流動性代碼；若歷史不足或非交易日 fallback，會透過 `quality / warnings` 降級。
```

- [ ] **Step 2: Update ROADMAP_6M_ENGINEERING.md**

Update Month 4 status so Relative Strength / Liquidity Ranking is marked as v1 connected. Replace immediate todo item 2 with:

```markdown
2. 將 Why Not / 風險提示銜接到 Daily Decision Desk 的 Watchlist Trigger、Relative Strength / Liquidity Ranking 與 Portfolio Alert，不在 UI 層重算 scoring、screening 或 portfolio logic。
```

Add an update record:

```markdown
- 2026-06-15：完成 Daily Decision Desk Relative Strength / Liquidity Ranking v1，從 SQLite `daily_prices` 推導強弱排名與低流動性警示，並以 quality / warnings 呈現資料缺口。
```

- [ ] **Step 3: Update system_architecture.md**

In the Application Layer Daily Decision Desk paragraph, add:

```markdown
Relative Strength / Liquidity Ranking v1 由 `RelativeStrengthLiquidityService` 與 `SQLiteDailyPriceRelativeStrengthLiquidityProvider` 自 SQLite `daily_prices` 唯讀推導 5 / 20 日相對強度與平均成交金額，輸出強勢、弱勢與低流動性代碼，不在 UI 層重算。
```

- [ ] **Step 4: Update APPLICATION_MANUAL.md**

In section 8.2, add:

```markdown
Relative Strength / Liquidity Ranking v1 會從 SQLite `daily_prices` 推導 5 / 20 日相對強度與平均成交金額，顯示強勢代碼、弱勢代碼與低流動性代碼。低流動性提示不是賣出或買進訊號，而是提醒研究或回測時需要檢查成交量、可成交金額與部位大小。
```

Update the “目前不能保證” Daily Decision Desk bullet so it no longer lists Relative Strength / Liquidity Ranking as future work after this task lands.

- [ ] **Step 5: Update DOCUMENTATION_INDEX.md**

Add this row near the other 2026-06-15 Daily Decision Desk plans:

```markdown
| [2026-06-15-decision-desk-relative-strength-liquidity-ranking.md](../superpowers/plans/2026-06-15-decision-desk-relative-strength-liquidity-ranking.md) | Daily Decision Desk Relative Strength / Liquidity Ranking v1 實作計畫，從 SQLite `daily_prices` 推導強弱排名、低流動性代碼與 quality / warnings 降級契約。 |
```

Add an update record:

```markdown
- 2026-06-15：補列 Daily Decision Desk Relative Strength / Liquidity Ranking v1 實作計畫至 Superpowers plans 索引。
```

- [ ] **Step 6: Commit Task 4**

```powershell
git add docs\00_core\PROJECT_SNAPSHOT.md docs\00_core\ROADMAP_6M_ENGINEERING.md docs\01_architecture\system_architecture.md docs\07_guides\APPLICATION_MANUAL.md docs\00_core\DOCUMENTATION_INDEX.md
git commit -m "docs: document relative strength liquidity decision desk section"
```

---

### Task 5: Final Verification Gate

**Files:**
- Verify only; no planned code changes.

- [ ] **Step 1: Run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_relative_strength_liquidity_service.py tests\test_decision_desk_service.py tests\test_ui_qt_decision_desk_main_integration.py tests\test_ui_qt_decision_desk_view.py -q
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
.\.venv\Scripts\python.exe -m py_compile app_module\decision_desk_dtos.py app_module\decision_desk_service.py app_module\relative_strength_liquidity_service.py ui_qt\main.py ui_qt\views\decision_desk_view.py
```

Expected: exit code 0.

- [ ] **Step 7: Inspect git status**

```powershell
git status --short
```

Expected: only intended files are modified, and tracked QA outputs are not staged unless explicitly requested.

---

## Self-Review

- Spec coverage: This plan adds the new DTO, service/provider, builder integration, main UI injection, Qt rendering, docs coverage, and final verification.
- Placeholder scan: No `TBD`, `TODO`, or vague “handle edge cases” steps remain.
- Type consistency: `RelativeStrengthLiquiditySummary`, `RelativeStrengthLiquidityService`, and `SQLiteDailyPriceRelativeStrengthLiquidityProvider` names are consistent across tasks.
