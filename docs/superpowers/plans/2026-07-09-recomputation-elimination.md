# 重複計算消除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改變推薦、回測、Daily Decision Desk 與排程公開介面的前提下，統一推薦衍生特徵、重用契約相符的預存技術指標，並讓單次 Decision Desk snapshot 共用同一市場資料 frame。

**Architecture:** 推薦衍生欄位由純 helper 計算一次並沿資料流重用；技術指標以參數註冊表驗證後，僅對預設參數與完整既存欄位命中 reuse；Decision Desk 由 request-scoped loader 提供唯讀 DataFrame，各 SQLite provider 只做切片與既有聚合。所有既有 public service 方法保持相容。

**Tech Stack:** Python 3.11、pandas、Decimal、SQLite read-only URI、PySide6 composition root、pytest、mypy。

## Global Constraints

- 使用繁體中文撰寫文件、訊息與新增註解。
- 不修改正式資料，不新增 SQLite schema migration，不建立跨執行 cache。
- 不改 `run_recommendation()`、`run_backtest()`、`calculate_technical_indicators()`、`build_snapshot()` 的既有呼叫方式。
- 策略、回測、推薦核心計算使用 `Decimal`；numpy / pandas 數值轉換只能位於明確隔離的 DataFrame 分析邊界。
- 所有特徵、指標與市場 frame 只使用 `decision_date` / `as_of_date` 當下或之前的資料。
- 保留 schema v1+ 指標參數 fail-closed、DTO、quality、warnings、dry-run / confirm gate 與排程參數。
- 不覆寫或提交與本任務無關的使用者變更。

---

### Task 1: 建立單一推薦衍生市場特徵 helper

**Files:**
- Create: `decision_module/derived_market_features.py`
- Create: `tests/test_derived_market_features.py`

**Interfaces:**
- Consumes: 依日期排序或含 `日期` 欄位的單一股票 `pd.DataFrame`。
- Produces: `enrich_latest_market_features(frame: pd.DataFrame) -> pd.DataFrame`；回傳 copy，並在最新列提供 `漲幅%`、`成交量變化率%`。
- Produces: `latest_feature_decimal(frame: pd.DataFrame, column: str) -> Decimal | None`；只讀取已計算欄位供 negative evidence 使用。

- [ ] **Step 1: 寫入價格、成交量、短歷史與缺值的失敗測試**

```python
from decimal import Decimal

import pandas as pd

from decision_module.derived_market_features import (
    enrich_latest_market_features,
    latest_feature_decimal,
)


def test_enrich_latest_market_features_writes_only_latest_row():
    frame = pd.DataFrame(
        {
            "日期": pd.date_range("2026-01-01", periods=3),
            "收盤價": [Decimal("10"), Decimal("11"), Decimal("12.1")],
            "成交股數": [100, 200, 300],
        }
    )
    result = enrich_latest_market_features(frame)
    assert "漲幅%" not in frame.columns
    assert result["漲幅%"].isna().sum() == 2
    assert latest_feature_decimal(result, "漲幅%") == Decimal("10")
    assert latest_feature_decimal(result, "成交量變化率%") == Decimal("100")


def test_enrich_latest_market_features_uses_zero_for_invalid_denominator():
    frame = pd.DataFrame({"收盤價": [0, 12], "成交股數": [0, 100]})
    result = enrich_latest_market_features(frame)
    assert latest_feature_decimal(result, "漲幅%") == Decimal("0")
    assert latest_feature_decimal(result, "成交量變化率%") == Decimal("0")
```

- [ ] **Step 2: 執行測試並確認因模組不存在而失敗**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_derived_market_features.py -q -o addopts=`

Expected: FAIL，錯誤包含 `ModuleNotFoundError: decision_module.derived_market_features`。

- [ ] **Step 3: 實作最小 Decimal helper 與 DataFrame 邊界**

```python
from decimal import Decimal, InvalidOperation

import pandas as pd

from financial_module.units import to_decimal


def _valid_decimals(values: pd.Series) -> list[Decimal]:
    result: list[Decimal] = []
    for value in values:
        if pd.isna(value):
            continue
        try:
            result.append(to_decimal(value))
        except (InvalidOperation, TypeError, ValueError):
            continue
    return result


def enrich_latest_market_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.sort_values("日期").copy() if "日期" in frame.columns else frame.copy()
    if result.empty:
        return result
    latest_index = result.index[-1]
    result.loc[latest_index, "漲幅%"] = _price_change(result)
    result.loc[latest_index, "成交量變化率%"] = _volume_change(result)
    return result


def latest_feature_decimal(frame: pd.DataFrame, column: str) -> Decimal | None:
    if frame.empty or column not in frame.columns or pd.isna(frame.iloc[-1][column]):
        return None
    try:
        return to_decimal(frame.iloc[-1][column])
    except (InvalidOperation, TypeError, ValueError):
        return None
```

`_price_change()` 與 `_volume_change()` 必須以 `Decimal("100")` 計算，並保留現有零分母回傳零的契約。指派到 DataFrame 時只在此 helper 內執行分析邊界轉換。

- [ ] **Step 4: 執行 helper 測試確認通過**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_derived_market_features.py -q -o addopts=`

Expected: PASS。

- [ ] **Step 5: 檢查語法**

Run: `.\.venv\Scripts\python.exe -m py_compile decision_module/derived_market_features.py tests/test_derived_market_features.py`

Expected: exit 0。

- [ ] **Step 6: 提交單一衍生特徵 helper**

```powershell
git add decision_module/derived_market_features.py tests/test_derived_market_features.py
git commit -m "refactor: centralize recommendation market features"
```

### Task 2: 建立技術指標參數契約重用判定器

**Files:**
- Create: `decision_module/indicator_reuse.py`
- Create: `tests/test_indicator_reuse.py`

**Interfaces:**
- Consumes: 技術指標 DataFrame、section config、完整策略 config。
- Produces: `prepare_indicator_reuse(frame, technical_config, full_config) -> IndicatorReusePlan`。
- `IndicatorReusePlan.frame` 包含必要相容 alias；`IndicatorReusePlan.technical_config` 將可安全重用的個別指標設為 disabled；`reused_indicators` 記錄命中名稱。

- [ ] **Step 1: 寫入預設命中、自訂參數 miss、缺欄位 miss 與 fail-closed 測試**

```python
import pandas as pd
import pytest

from decision_module.indicator_parameter_registry import InvalidParameterError
from decision_module.indicator_reuse import prepare_indicator_reuse


def test_default_rsi_and_bollinger_reuse_existing_columns():
    frame = pd.DataFrame(
        {"RSI": [50], "upperband": [11], "middleband": [10], "lowerband": [9]}
    )
    config = {
        "momentum": {"enabled": True, "rsi": {"enabled": True}},
        "volatility": {"enabled": True, "bollinger": {"enabled": True}},
    }
    plan = prepare_indicator_reuse(frame, config, {"config_schema_version": 0})
    assert plan.reused_indicators == frozenset({"rsi", "bollinger"})
    assert plan.frame["BB_Upper"].tolist() == [11]


def test_custom_rsi_period_is_not_reused():
    frame = pd.DataFrame({"RSI": [50]})
    config = {"momentum": {"enabled": True, "rsi": {"enabled": True, "timeperiod": 7}}}
    plan = prepare_indicator_reuse(frame, config, {"config_schema_version": 0})
    assert "rsi" not in plan.reused_indicators


def test_schema_v1_missing_parameter_still_fails_closed():
    frame = pd.DataFrame({"RSI": [50]})
    config = {"momentum": {"enabled": True, "rsi": {"enabled": True}}}
    with pytest.raises(InvalidParameterError):
        prepare_indicator_reuse(frame, config, {"config_schema_version": 1})
```

- [ ] **Step 2: 執行測試並確認缺少 API 而失敗**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_indicator_reuse.py -q -o addopts=`

Expected: FAIL，錯誤包含 `ModuleNotFoundError: decision_module.indicator_reuse`。

- [ ] **Step 3: 實作 immutable plan、欄位契約與 alias mapping**

```python
from dataclasses import dataclass
from typing import Any

import pandas as pd

from decision_module.indicator_parameter_registry import IndicatorParameterRegistry


@dataclass(frozen=True)
class IndicatorReusePlan:
    frame: pd.DataFrame
    technical_config: dict[str, Any]
    reused_indicators: frozenset[str]


INDICATOR_COLUMNS = {
    "rsi": (("RSI",), {}),
    "macd": (("MACD", "MACD_signal", "MACD_hist"), {}),
    "kd": (("slowk", "slowd"), {"SlowK": "slowk", "SlowD": "slowd"}),
    "bollinger": (
        ("upperband", "middleband", "lowerband"),
        {"BB_Upper": "upperband", "BB_Middle": "middleband", "BB_Lower": "lowerband"},
    ),
    "sar": (("SAR",), {}),
    "tsf": (("TSF",), {}),
    "ma": (("MA5", "MA10", "MA20", "MA60"), {}),
}
```

對每個 enabled indicator 必須先呼叫 `validate_and_sanitize()`，再和 `get_default_config()` 對應項目比較；ATR、ADX 不列入 `INDICATOR_COLUMNS`。欄位存在但全為 NaN 時不得命中。

- [ ] **Step 4: 執行重用判定測試確認通過**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_indicator_reuse.py -q -o addopts=`

Expected: PASS。

- [ ] **Step 5: 提交指標重用判定器**

```powershell
git add decision_module/indicator_reuse.py tests/test_indicator_reuse.py
git commit -m "refactor: add indicator reuse contract"
```

### Task 3: 將單一特徵與指標重用整合進推薦／回測共用流程

**Files:**
- Modify: `decision_module/strategy_configurator.py`
- Modify: `app_module/recommendation_service.py`
- Modify: `tests/test_m2_a_integration.py`
- Modify: `tests/test_recommendation_v1_7_negative_evidence.py`
- Create: `tests/test_recommendation_recomputation.py`

**Interfaces:**
- Consumes: Task 1 的 `enrich_latest_market_features()`、`latest_feature_decimal()`。
- Consumes: Task 2 的 `prepare_indicator_reuse()`。
- Produces: public signatures 不變；成功、空結果與 backtest executor 仍取得原 DTO / DataFrame 契約。

- [ ] **Step 1: 寫入「每檔只算一次」與「預存預設指標不呼叫 calculator」失敗測試**

```python
from unittest.mock import MagicMock, patch

import pandas as pd

import app_module.recommendation_service as recommendation_service_module
from app_module.recommendation_service import RecommendationService
from decision_module.strategy_configurator import StrategyConfigurator


@patch("pandas.read_csv")
def test_recommendation_enriches_features_once_per_stock(mock_read_csv, monkeypatch):
    config = MagicMock()
    config.use_sqlite = False
    config.stock_data_file.exists.return_value = True
    config.stock_data_file.stat.return_value.st_size = 1024
    config.all_stocks_data_file.exists.return_value = False
    stock_frame = pd.DataFrame(
        {
            "日期": pd.date_range("2026-01-01", periods=20),
            "證券代號": ["2330"] * 20,
            "證券名稱": ["台積電"] * 20,
            "收盤價": list(range(100, 120)),
            "成交股數": [1000] * 20,
        }
    )
    mock_read_csv.return_value = stock_frame
    service = RecommendationService(config, industry_mapper=MagicMock())
    calls = 0
    original = recommendation_service_module.enrich_latest_market_features

    def counted(frame):
        nonlocal calls
        calls += 1
        return original(frame)

    monkeypatch.setattr(recommendation_service_module, "enrich_latest_market_features", counted)
    service.strategy_configurator.generate_recommendations = lambda frame, _config: pd.DataFrame()
    service.run_recommendation({}, max_stocks=1, top_n=1)
    assert calls == 1


def test_configurator_skips_default_rsi_calculator_when_joined_column_exists(monkeypatch):
    configurator = StrategyConfigurator()
    frame = _price_frame_with_default_rsi()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("default RSI must be reused")

    monkeypatch.setattr(
        configurator.technical_analyzer.calculator,
        "calculate_momentum_indicators",
        fail_if_called,
    )
    result = configurator.configure_technical_indicators(
        frame,
        {"momentum": {"enabled": True, "rsi": {"enabled": True}}},
        full_config={"config_schema_version": 0},
    )
    assert result["RSI"].equals(frame["RSI"])
```

- [ ] **Step 2: 執行新測試並確認目前重複呼叫或 calculator 被呼叫**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_recomputation.py -q -o addopts=`

Expected: FAIL；一次計算 assertion 或 `default RSI must be reused` 觸發。

- [ ] **Step 3: 整合 RecommendationService 單次 enrichment**

在每檔 `stock_df` 通過最小歷史檢查後立即執行：

```python
stock_df = enrich_latest_market_features(stock_df)
result_df = self.strategy_configurator.generate_recommendations(stock_df, config)
```

成功路徑直接讀 `latest_row["漲幅%"]` 與 `latest_row["成交量變化率%"]`。空結果路徑改用：

```python
observed_volume_change = latest_feature_decimal(stock_df, "成交量變化率%")
```

刪除 service 內第二套價格／成交量公式與 private `_observed_volume_change_percent()`；正式流程只讀取本次已 enrichment 的欄位。

- [ ] **Step 4: 整合 StrategyConfigurator fallback 與 indicator reuse plan**

`generate_recommendations()` 在欄位缺失時呼叫 Task 1 helper，不再保留內嵌公式。`configure_technical_indicators()` 先建立 plan：

```python
reuse_plan = prepare_indicator_reuse(df, config_copy, full_config)
df_result = reuse_plan.frame
config_copy = reuse_plan.technical_config
```

之後沿用現有 TechnicalAnalyzer section 呼叫，只計算 plan 未重用的指標。

- [ ] **Step 5: 執行推薦、參數治理與 negative evidence 測試**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_recomputation.py tests/test_m2_a_integration.py tests/test_recommendation_v1_7_negative_evidence.py tests/test_recommendation_ranking_service.py tests/test_backtest_factor_metadata.py -q -o addopts=`

Expected: PASS。

- [ ] **Step 7: 提交推薦／回測共用整合**

```powershell
git add decision_module/strategy_configurator.py app_module/recommendation_service.py tests/test_m2_a_integration.py tests/test_recommendation_v1_7_negative_evidence.py tests/test_recommendation_recomputation.py
git commit -m "refactor: reuse recommendation features and indicators"
```

- [ ] **Step 6: 檢查 Look-ahead 與輸出等價性**

在測試加入未來一列資料但使用截斷 decision frame，確認輸出只取截斷 frame 的最後一列；比較重用與強制重算的 RSI / MACD / MA 預設參數序列，在共同非 NaN 區間使用 `pd.testing.assert_series_equal(..., check_names=False)`。

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_recomputation.py tests/test_indicator_reuse.py -q -o addopts=`

Expected: PASS。

### Task 4: 建立單次 Decision Desk 市場資料 frame loader

**Files:**
- Create: `app_module/decision_market_frame.py`
- Create: `tests/test_decision_market_frame.py`

**Interfaces:**
- Produces: `DecisionMarketFrameLoader(db_path: str | Path)`。
- Produces: `reset(as_of_date: date) -> None`，每次 snapshot 開始時清除舊 frame。
- Produces: `load(as_of_date: date, lookback_days: int) -> pd.DataFrame`，唯讀載入 `日期 <= as_of_date` 的必要欄位並回傳 copy。
- Produces: `load_recent_prices(stock_code, decision_date, limit) -> list[tuple[date, Decimal]]`，供 Smart Money provider 委派。

- [ ] **Step 1: 寫入單次載入、reset 重載與日期上限測試**

```python
def test_loader_reuses_largest_frame_within_snapshot(tmp_path, monkeypatch):
    db_path = _seed_daily_prices(tmp_path)
    loader = DecisionMarketFrameLoader(db_path)
    calls = 0
    original = loader._read_frame

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(loader, "_read_frame", counted)
    target = date(2026, 1, 31)
    loader.reset(target)
    loader.load(target, 61)
    loader.load(target, 40)
    loader.load_recent_prices("2330", target, 60)
    assert calls == 1

    loader.reset(target)
    loader.load(target, 61)
    assert calls == 2
```

- [ ] **Step 2: 執行測試並確認模組不存在而失敗**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_decision_market_frame.py -q -o addopts=`

Expected: FAIL，錯誤包含 `ModuleNotFoundError: app_module.decision_market_frame`。

- [ ] **Step 3: 實作 read-only loader 與 snapshot-local cache**

```python
class DecisionMarketFrameLoader:
    COLUMNS = ("日期", "證券代號", "收盤價", "漲跌價差", "成交股數")

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._as_of_date: date | None = None
        self._lookback_days = 0
        self._frame: pd.DataFrame | None = None

    def reset(self, as_of_date: date) -> None:
        self._as_of_date = as_of_date
        self._lookback_days = 0
        self._frame = None

    def load(self, as_of_date: date, lookback_days: int) -> pd.DataFrame:
        if self._frame is None or self._as_of_date != as_of_date or lookback_days > self._lookback_days:
            self._frame = self._read_frame(as_of_date, lookback_days)
            self._as_of_date = as_of_date
            self._lookback_days = lookback_days
        return self._slice_to_lookback(self._frame, lookback_days).copy()
```

`_read_frame()` 使用 SQLite URI `mode=ro`、`PRAGMA query_only=ON`，先取得最近 N 個 distinct dates，再一次讀取必要欄位。SQL 必須使用 normalized date `<= target_key`。

- [ ] **Step 4: 執行 loader 測試確認通過**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_decision_market_frame.py -q -o addopts=`

Expected: PASS。

- [ ] **Step 5: 提交 snapshot-local 市場 frame loader**

```powershell
git add app_module/decision_market_frame.py tests/test_decision_market_frame.py
git commit -m "refactor: add decision market frame loader"
```

### Task 5: 將共享市場 frame 接入 Decision Desk providers 與 composition roots

**Files:**
- Modify: `app_module/market_breadth_service.py`
- Modify: `app_module/relative_strength_liquidity_service.py`
- Modify: `app_module/smart_money_semantic_service.py`
- Modify: `app_module/decision_desk_service.py`
- Modify: `app_module/decision_desk_builder_factory.py`
- Modify: `ui_qt/main.py`
- Modify: `tests/test_decision_desk_service.py`
- Modify: `tests/test_ui_qt_decision_desk_main_integration.py`
- Create: `tests/test_decision_desk_shared_market_frame.py`

**Interfaces:**
- Provider constructors新增 optional keyword `market_frame_loader: DecisionMarketFrameLoader | None = None`。
- `DecisionDeskSnapshotBuilder.__init__()` 新增 optional loader；`build_snapshot(as_of_date)` 簽名不變。
- 沒有 loader 時 providers 保持原 SQL 路徑。

- [ ] **Step 1: 寫入 factory 共用 loader 與每次 snapshot reset 的失敗測試**

```python
def test_service_backed_builder_shares_one_market_loader(config, monkeypatch):
    reads = 0
    original = DecisionMarketFrameLoader._read_frame

    def counted(self, *args, **kwargs):
        nonlocal reads
        reads += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DecisionMarketFrameLoader, "_read_frame", counted)
    builder = build_service_backed_decision_desk_snapshot_builder(config)
    builder.build_snapshot(date(2026, 1, 31))
    assert reads == 1
    builder.build_snapshot(date(2026, 1, 31))
    assert reads == 2
```

- [ ] **Step 2: 執行新測試並確認目前有多次 SQL 讀取或缺少注入參數**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_decision_desk_shared_market_frame.py -q -o addopts=`

Expected: FAIL。

- [ ] **Step 3: 修改三個 SQLite provider 優先使用共享 loader**

Market Breadth：

```python
if self.market_frame_loader is not None:
    prices = self.market_frame_loader.load(as_of_date, self.lookback_days + 1)
    return self._build_breadth_frame_from_loaded_prices(prices, as_of_date)
```

Relative Strength / Liquidity：`fetch()` 直接回傳 loader 的 40 日切片。Smart Money：`load_recent_prices()` 委派 loader 的 per-stock filter。未注入時保留現有 read-only SQL。

- [ ] **Step 4: Builder 在 section 執行前 reset，兩個 composition root 共用同一 loader**

```python
def build_snapshot(self, as_of_date: date) -> DecisionDeskSnapshot:
    if self.market_frame_loader is not None:
        self.market_frame_loader.reset(as_of_date)
    # 原 section 順序保持不變
```

`decision_desk_builder_factory.py` 建立一個 loader，注入三個 provider 與 builder。`ui_qt/main.py` 在建立 Market Breadth、Relative Strength / Liquidity 與 Smart Money provider 前建立 `self.decision_market_frame_loader`，並傳入 builder。

- [ ] **Step 5: 執行 Decision Desk service、provider 與 UI composition 測試**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_decision_market_frame.py tests/test_decision_desk_shared_market_frame.py tests/test_decision_desk_service.py tests/test_market_breadth_service.py tests/test_relative_strength_liquidity_service.py tests/test_smart_money_semantic_service.py tests/test_ui_qt_decision_desk_main_integration.py -q -o addopts=`

Expected: PASS。

- [ ] **Step 6: 提交 Decision Desk 共用市場 frame 整合**

```powershell
git add app_module/market_breadth_service.py app_module/relative_strength_liquidity_service.py app_module/smart_money_semantic_service.py app_module/decision_desk_service.py app_module/decision_desk_builder_factory.py ui_qt/main.py tests/test_decision_desk_service.py tests/test_ui_qt_decision_desk_main_integration.py tests/test_decision_desk_shared_market_frame.py
git commit -m "refactor: share decision desk market frame"
```

### Task 6: 排程相容、文檔同步與完整驗證

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`

**Interfaces:**
- Documentation records behavior-preserving optimization and safety boundaries.
- Scheduled command signatures and status payloads remain unchanged.

- [ ] **Step 1: 更新文件的目前狀態、架構與操作安全邊界**

記錄：推薦衍生欄位 single-source、預設參數指標重用、自訂參數 fail-closed 重算、Decision Desk snapshot-local frame、排程命令不變、無跨執行 cache、無 schema migration。

文件需加入以下明確邊界：

```markdown
- 推薦流程的最新價格／成交量衍生特徵由單一 helper 計算並由篩選、推薦 DTO 與 negative evidence 共用；不改門檻與排序。
- 預存技術指標只有在參數契約等於標準預設且欄位完整時重用；自訂參數與缺失欄位仍 fail-closed 或重新計算。
- Daily Decision Desk 僅在單次 snapshot 內共用 read-only 市場 frame；每次 snapshot 重新載入，不形成跨執行 stale cache。
- 既有推薦、回測、更新與排程入口不變，且未新增 SQLite schema migration。
```

- [ ] **Step 2: 執行排程與推薦／回測回歸測試**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_scheduled_recommendation_snapshot_wrapper.py `
  tests/test_scheduled_evidence_pipeline_dry_run_wrapper.py `
  tests/test_recommendation_recomputation.py `
  tests/test_recommendation_v1_7_negative_evidence.py `
  tests/test_recommendation_ranking_service.py `
  tests/test_backtest_factor_metadata.py `
  tests/test_backtest_diagnostics_and_date_adjustment.py `
  tests/test_decision_desk_shared_market_frame.py `
  tests/test_decision_desk_service.py `
  -q -o addopts=
```

Expected: 全部 PASS，排程 wrapper 不需要新參數。

- [ ] **Step 3: 執行 UI 強制測試與 Update QA**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=`

Run: `.\.venv\Scripts\python.exe scripts/qa_validate_update_tab.py`

Expected: 全部 PASS。

- [ ] **Step 4: 執行 mypy**

Run: `.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`

Expected: exit 0。

- [ ] **Step 5: 執行變更 Python 檔語法檢查**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile `
  decision_module/derived_market_features.py `
  decision_module/indicator_reuse.py `
  decision_module/strategy_configurator.py `
  app_module/recommendation_service.py `
  app_module/decision_market_frame.py `
  app_module/market_breadth_service.py `
  app_module/relative_strength_liquidity_service.py `
  app_module/smart_money_semantic_service.py `
  app_module/decision_desk_service.py `
  app_module/decision_desk_builder_factory.py `
  ui_qt/main.py
```

Expected: exit 0。

- [ ] **Step 6: 檢查 diff 與排程介面**

Run: `git diff --check`

Run:

```powershell
.\.venv\Scripts\python.exe -c "import inspect; from app_module.recommendation_service import RecommendationService; from app_module.backtest_service import BacktestService; from app_module.update_service import UpdateService; from app_module.decision_desk_service import DecisionDeskSnapshotBuilder; print(inspect.signature(RecommendationService.run_recommendation)); print(inspect.signature(BacktestService.run_backtest)); print(inspect.signature(UpdateService.calculate_technical_indicators)); print(inspect.signature(DecisionDeskSnapshotBuilder.build_snapshot))"
```

Expected: 四個公開入口保留既有必要參數，沒有排程呼叫端需要更新。

- [ ] **Step 7: 提交文件與驗證收口**

```powershell
git add docs/00_core/PROJECT_SNAPSHOT.md docs/01_architecture/system_architecture.md docs/07_guides/APPLICATION_MANUAL.md docs/00_core/DOCUMENTATION_INDEX.md docs/superpowers/plans/2026-07-09-recomputation-elimination.md
git commit -m "docs: record recomputation elimination boundaries"
```
