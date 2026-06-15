# Month 3 Factor Layer v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Factor Layer v1 的 contract、registry、look-ahead gate、既有資料 adapter 與 Research Run 追溯保存，不接新資料源、不改 `ScoringEngine` 核心邏輯。

**Architecture:** 新增 `decision_module/factors/` 作為 domain-level factor contract 與 gate；新增 `app_module/factor_service.py` 作為 application orchestration。v1 只把既有技術、量能與券商分點資料包成 `FactorRecord`，通過 `FactorGate` 後保存到 Research Run metadata JSON。

**Tech Stack:** Python dataclasses、Enum、Decimal、pytest、pandas、既有 Research Run Registry、既有 broker flow service。

---

## File Structure

**Create**
- `decision_module/factors/__init__.py`：匯出 Factor Layer public API。
- `decision_module/factors/factor_dtos.py`：定義 `FactorQuality`、`MissingPolicy`、`FactorRecord`、`FactorDefinition`、`FactorGateResult`。
- `decision_module/factors/factor_registry.py`：定義 registry 與 v1 factor definitions。
- `decision_module/factors/factor_gate.py`：集中執行 `available_date <= decision_date`、`score_bp` 與品質政策。
- `decision_module/factors/factor_adapters.py`：定義 adapter protocol 與 v1 technical / volume / broker flow adapter helpers。
- `app_module/factor_service.py`：收集、gate、序列化 factor snapshot。
- `tests/test_factor_contract.py`
- `tests/test_factor_gate.py`
- `tests/test_factor_registry.py`
- `tests/test_factor_adapters.py`
- `tests/test_factor_service_research_run.py`

**Modify**
- `app_module/research_run_dtos.py`：新增 metadata helper properties / constants，不破壞現有欄位。
- `app_module/research_run_comparison_service.py`：新增讀取已保存 factor metadata 的方法，不重新抓取目前資料。
- `docs/00_core/PROJECT_SNAPSHOT.md`：標示 Month 3 進入 Factor Layer v1。
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`：更新 Month 3 進度。
- `docs/01_architecture/system_architecture.md`：把 Factor Layer 從未來設計推進為 v1 實作架構。
- `docs/00_core/DOCUMENTATION_INDEX.md`：索引本 plan。

---

## Task 1: Factor Contract DTOs

**Files:**
- Create: `decision_module/factors/__init__.py`
- Create: `decision_module/factors/factor_dtos.py`
- Test: `tests/test_factor_contract.py`

- [x] **Step 1: Write failing contract tests**

Create `tests/test_factor_contract.py`:

```python
from datetime import date
from decimal import Decimal

import pytest

from decision_module.factors.factor_dtos import (
    FactorDefinition,
    FactorQuality,
    FactorRecord,
    MissingPolicy,
)


def test_factor_record_accepts_integer_score_bp():
    record = FactorRecord(
        factor_name="technical.total_score",
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        value=Decimal("82.35"),
        score_bp=8235,
        quality=FactorQuality.OBSERVED,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="technical-v1",
        metadata={"window": 20},
    )

    assert record.score_bp == 8235
    assert record.to_dict()["quality"] == "observed"
    assert record.to_dict()["value"] == "82.35"


def test_factor_record_rejects_out_of_range_score_bp():
    with pytest.raises(ValueError, match="score_bp"):
        FactorRecord(
            factor_name="technical.total_score",
            stock_code="2330",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            value=Decimal("101"),
            score_bp=10001,
            quality=FactorQuality.OBSERVED,
            missing_policy=MissingPolicy.FAIL_CLOSED,
            source_version="technical-v1",
        )


def test_factor_definition_declares_neutral_score_and_stale_days():
    definition = FactorDefinition(
        factor_name="volume.volume_ratio",
        display_name="量能比率",
        category="volume",
        source_version="volume-v1",
        default_missing_policy=MissingPolicy.NEUTRAL,
        neutral_score_bp=5000,
        stale_after_days=5,
    )

    assert definition.neutral_score_bp == 5000
    assert definition.stale_after_days == 5
```

- [x] **Step 2: Run contract tests and confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_contract.py -q -o addopts=
```

Expected: fail with `ModuleNotFoundError: No module named 'decision_module.factors'`.

- [x] **Step 3: Implement `factor_dtos.py`**

Create `decision_module/factors/factor_dtos.py`:

```python
"""Factor Layer v1 DTO 與品質契約。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any


class FactorQuality(str, Enum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    MISSING = "missing"
    NEUTRAL = "neutral"
    STALE = "stale"


class MissingPolicy(str, Enum):
    FAIL_CLOSED = "fail_closed"
    NEUTRAL = "neutral"
    SKIP = "skip"


FactorValue = Decimal | int | str | None


@dataclass(frozen=True)
class FactorRecord:
    factor_name: str
    stock_code: str
    as_of_date: date
    available_date: date
    value: FactorValue
    score_bp: int | None
    quality: FactorQuality
    missing_policy: MissingPolicy
    source_version: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.factor_name:
            raise ValueError("factor_name 不可為空")
        if not self.stock_code:
            raise ValueError("stock_code 不可為空")
        if self.score_bp is not None and not 0 <= self.score_bp <= 10000:
            raise ValueError("score_bp 必須介於 0 到 10000")

    def to_dict(self) -> dict[str, Any]:
        value: Any = self.value
        if isinstance(value, Decimal):
            value = str(value)
        return {
            "factor_name": self.factor_name,
            "stock_code": self.stock_code,
            "as_of_date": self.as_of_date.isoformat(),
            "available_date": self.available_date.isoformat(),
            "value": value,
            "score_bp": self.score_bp,
            "quality": self.quality.value,
            "missing_policy": self.missing_policy.value,
            "source_version": self.source_version,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class FactorDefinition:
    factor_name: str
    display_name: str
    category: str
    source_version: str
    default_missing_policy: MissingPolicy
    neutral_score_bp: int | None = None
    stale_after_days: int | None = None

    def __post_init__(self) -> None:
        if self.neutral_score_bp is not None and not 0 <= self.neutral_score_bp <= 10000:
            raise ValueError("neutral_score_bp 必須介於 0 到 10000")


@dataclass(frozen=True)
class FactorDiagnostic:
    code: str
    factor_name: str
    stock_code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "factor_name": self.factor_name,
            "stock_code": self.stock_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class FactorGateResult:
    accepted: tuple[FactorRecord, ...] = ()
    neutralized: tuple[FactorRecord, ...] = ()
    skipped: tuple[FactorRecord, ...] = ()
    diagnostics: tuple[FactorDiagnostic, ...] = ()
```

Create `decision_module/factors/__init__.py`:

```python
"""Factor Layer v1 public API。"""

from decision_module.factors.factor_dtos import (
    FactorDefinition,
    FactorDiagnostic,
    FactorGateResult,
    FactorQuality,
    FactorRecord,
    MissingPolicy,
)

__all__ = [
    "FactorDefinition",
    "FactorDiagnostic",
    "FactorGateResult",
    "FactorQuality",
    "FactorRecord",
    "MissingPolicy",
]
```

- [x] **Step 4: Verify contract tests pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_contract.py -q -o addopts=
```

Expected: `3 passed`.

---

## Task 2: Factor Gate

**Files:**
- Create: `decision_module/factors/factor_gate.py`
- Test: `tests/test_factor_gate.py`

- [x] **Step 1: Write failing gate tests**

Create `tests/test_factor_gate.py`:

```python
from datetime import date
from decimal import Decimal

import pytest

from decision_module.factors.factor_dtos import FactorQuality, FactorRecord, MissingPolicy
from decision_module.factors.factor_gate import FactorGate, FactorLookAheadError


def _record(*, available_date, policy=MissingPolicy.FAIL_CLOSED, quality=FactorQuality.OBSERVED):
    return FactorRecord(
        factor_name="technical.total_score",
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=available_date,
        value=Decimal("80"),
        score_bp=8000,
        quality=quality,
        missing_policy=policy,
        source_version="technical-v1",
    )


def test_gate_accepts_available_factor():
    result = FactorGate().validate_for_decision(
        [_record(available_date=date(2026, 6, 12))],
        decision_date=date(2026, 6, 14),
    )

    assert len(result.accepted) == 1
    assert not result.diagnostics


def test_gate_rejects_future_factor_fail_closed():
    with pytest.raises(FactorLookAheadError, match="available_date"):
        FactorGate().validate_for_decision(
            [_record(available_date=date(2026, 6, 15))],
            decision_date=date(2026, 6, 14),
        )


def test_gate_neutralizes_future_factor_when_policy_is_neutral():
    result = FactorGate().validate_for_decision(
        [_record(available_date=date(2026, 6, 15), policy=MissingPolicy.NEUTRAL)],
        decision_date=date(2026, 6, 14),
        neutral_score_bp=5000,
    )

    assert result.neutralized[0].quality == FactorQuality.NEUTRAL
    assert result.neutralized[0].score_bp == 5000
    assert result.diagnostics[0].code == "factor.neutralized_lookahead"


def test_gate_skips_missing_factor_when_policy_is_skip():
    result = FactorGate().validate_for_decision(
        [_record(available_date=date(2026, 6, 12), policy=MissingPolicy.SKIP, quality=FactorQuality.MISSING)],
        decision_date=date(2026, 6, 14),
    )

    assert len(result.skipped) == 1
    assert result.diagnostics[0].code == "factor.skipped_missing"
```

- [x] **Step 2: Run gate tests and confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_gate.py -q -o addopts=
```

Expected: fail because `factor_gate.py` does not exist.

- [x] **Step 3: Implement `factor_gate.py`**

Create `decision_module/factors/factor_gate.py`:

```python
"""Factor Layer v1 Look-ahead 與 missing policy gate。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from decision_module.factors.factor_dtos import (
    FactorDiagnostic,
    FactorGateResult,
    FactorQuality,
    FactorRecord,
    MissingPolicy,
)


class FactorLookAheadError(ValueError):
    """Factor available_date 晚於 decision_date。"""


class FactorGate:
    def validate_for_decision(
        self,
        records: list[FactorRecord],
        *,
        decision_date: date,
        neutral_score_bp: int = 5000,
    ) -> FactorGateResult:
        accepted: list[FactorRecord] = []
        neutralized: list[FactorRecord] = []
        skipped: list[FactorRecord] = []
        diagnostics: list[FactorDiagnostic] = []

        for record in records:
            if record.available_date > decision_date:
                handled = self._handle_lookahead(record, neutral_score_bp)
                if isinstance(handled, FactorRecord):
                    neutralized.append(handled)
                    diagnostics.append(
                        self._diagnostic(
                            "factor.neutralized_lookahead",
                            record,
                            "factor available_date 晚於 decision_date，已轉為 neutral",
                        )
                    )
                    continue
                raise FactorLookAheadError(
                    f"factor available_date 晚於 decision_date: {record.factor_name} "
                    f"{record.stock_code} available_date={record.available_date} "
                    f"decision_date={decision_date}"
                )

            if record.quality == FactorQuality.MISSING and record.missing_policy == MissingPolicy.SKIP:
                skipped.append(record)
                diagnostics.append(
                    self._diagnostic("factor.skipped_missing", record, "missing factor 已跳過")
                )
                continue

            if record.quality == FactorQuality.MISSING and record.missing_policy == MissingPolicy.NEUTRAL:
                neutral = replace(record, quality=FactorQuality.NEUTRAL, score_bp=neutral_score_bp)
                neutralized.append(neutral)
                diagnostics.append(
                    self._diagnostic("factor.neutralized_missing", record, "missing factor 已轉為 neutral")
                )
                continue

            accepted.append(record)

        return FactorGateResult(
            accepted=tuple(accepted),
            neutralized=tuple(neutralized),
            skipped=tuple(skipped),
            diagnostics=tuple(diagnostics),
        )

    def _handle_lookahead(
        self,
        record: FactorRecord,
        neutral_score_bp: int,
    ) -> FactorRecord | None:
        if record.missing_policy == MissingPolicy.NEUTRAL:
            return replace(record, quality=FactorQuality.NEUTRAL, score_bp=neutral_score_bp)
        if record.missing_policy == MissingPolicy.SKIP:
            return replace(record, quality=FactorQuality.NEUTRAL, score_bp=None)
        return None

    def _diagnostic(self, code: str, record: FactorRecord, message: str) -> FactorDiagnostic:
        return FactorDiagnostic(
            code=code,
            factor_name=record.factor_name,
            stock_code=record.stock_code,
            message=message,
        )
```

- [x] **Step 4: Verify gate tests pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_gate.py tests\test_factor_contract.py -q -o addopts=
```

Expected: `7 passed`.

---

## Task 3: Factor Registry

**Files:**
- Create: `decision_module/factors/factor_registry.py`
- Test: `tests/test_factor_registry.py`

- [x] **Step 1: Write failing registry tests**

Create `tests/test_factor_registry.py`:

```python
import pytest

from decision_module.factors.factor_dtos import MissingPolicy
from decision_module.factors.factor_registry import FactorRegistry, UnknownFactorError


def test_default_registry_contains_month3_v1_factors():
    registry = FactorRegistry.default()

    assert registry.get("technical.total_score").category == "technical"
    assert registry.get("volume.volume_ratio").category == "volume"
    assert registry.get("broker_flow.net_lots").category == "broker_flow"


def test_registry_returns_missing_policy_and_neutral_score():
    definition = FactorRegistry.default().get("volume.volume_ratio")

    assert definition.default_missing_policy == MissingPolicy.NEUTRAL
    assert definition.neutral_score_bp == 5000


def test_registry_rejects_unknown_factor():
    with pytest.raises(UnknownFactorError, match="unknown.factor"):
        FactorRegistry.default().get("unknown.factor")
```

- [x] **Step 2: Run registry tests and confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_registry.py -q -o addopts=
```

Expected: fail because `factor_registry.py` does not exist.

- [x] **Step 3: Implement `factor_registry.py`**

Create `decision_module/factors/factor_registry.py`:

```python
"""Factor Layer v1 registry。"""

from __future__ import annotations

from dataclasses import dataclass

from decision_module.factors.factor_dtos import FactorDefinition, MissingPolicy


class UnknownFactorError(KeyError):
    """Registry 查無 factor definition。"""


@dataclass(frozen=True)
class FactorRegistry:
    definitions: dict[str, FactorDefinition]

    @classmethod
    def default(cls) -> "FactorRegistry":
        definitions = {
            "technical.total_score": FactorDefinition(
                factor_name="technical.total_score",
                display_name="技術總分",
                category="technical",
                source_version="technical-v1",
                default_missing_policy=MissingPolicy.FAIL_CLOSED,
                neutral_score_bp=None,
                stale_after_days=1,
            ),
            "volume.volume_ratio": FactorDefinition(
                factor_name="volume.volume_ratio",
                display_name="量能比率",
                category="volume",
                source_version="volume-v1",
                default_missing_policy=MissingPolicy.NEUTRAL,
                neutral_score_bp=5000,
                stale_after_days=5,
            ),
            "broker_flow.net_lots": FactorDefinition(
                factor_name="broker_flow.net_lots",
                display_name="券商分點淨買賣超",
                category="broker_flow",
                source_version="broker-flow-v1",
                default_missing_policy=MissingPolicy.SKIP,
                neutral_score_bp=None,
                stale_after_days=5,
            ),
        }
        return cls(definitions)

    def get(self, factor_name: str) -> FactorDefinition:
        try:
            return self.definitions[factor_name]
        except KeyError as exc:
            raise UnknownFactorError(factor_name) from exc
```

- [x] **Step 4: Verify registry tests pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_registry.py tests\test_factor_contract.py -q -o addopts=
```

Expected: `6 passed`.

---

## Task 4: v1 Factor Adapters

**Files:**
- Create: `decision_module/factors/factor_adapters.py`
- Test: `tests/test_factor_adapters.py`

- [x] **Step 1: Write failing adapter tests**

Create `tests/test_factor_adapters.py`:

```python
from datetime import date
from decimal import Decimal

from decision_module.factors.factor_adapters import (
    broker_flow_quality_to_factor_quality,
    build_broker_flow_factor,
    build_technical_total_score_factor,
    build_volume_ratio_factor,
)
from decision_module.factors.factor_dtos import FactorQuality, MissingPolicy


def test_technical_score_adapter_quantizes_to_basis_points():
    record = build_technical_total_score_factor(
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        total_score=Decimal("82.35"),
    )

    assert record.factor_name == "technical.total_score"
    assert record.score_bp == 8235
    assert record.quality == FactorQuality.OBSERVED


def test_volume_ratio_adapter_uses_neutral_policy_when_missing():
    record = build_volume_ratio_factor(
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        volume_ratio=None,
    )

    assert record.quality == FactorQuality.MISSING
    assert record.missing_policy == MissingPolicy.NEUTRAL


def test_broker_flow_quality_mapping_does_not_treat_unavailable_as_zero():
    assert broker_flow_quality_to_factor_quality("observed") == FactorQuality.OBSERVED
    assert broker_flow_quality_to_factor_quality("estimated") == FactorQuality.ESTIMATED
    assert broker_flow_quality_to_factor_quality("unavailable") == FactorQuality.MISSING


def test_broker_flow_adapter_preserves_rank_metadata():
    record = build_broker_flow_factor(
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        net_lots=120,
        quality="estimated",
        rank=7,
    )

    assert record.value == 120
    assert record.quality == FactorQuality.ESTIMATED
    assert record.metadata["rank"] == 7
```

- [x] **Step 2: Run adapter tests and confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_adapters.py -q -o addopts=
```

Expected: fail because adapter functions do not exist.

- [x] **Step 3: Implement `factor_adapters.py`**

Create `decision_module/factors/factor_adapters.py`:

```python
"""既有技術、量能與券商分點資料的 Factor v1 adapter。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from decision_module.factors.factor_dtos import FactorQuality, FactorRecord, MissingPolicy


def _score_to_bp(score: Decimal) -> int:
    score_bp = (score * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP)
    return max(0, min(10000, int(score_bp)))


def build_technical_total_score_factor(
    *,
    stock_code: str,
    as_of_date: date,
    available_date: date,
    total_score: Decimal,
) -> FactorRecord:
    return FactorRecord(
        factor_name="technical.total_score",
        stock_code=stock_code,
        as_of_date=as_of_date,
        available_date=available_date,
        value=total_score,
        score_bp=_score_to_bp(total_score),
        quality=FactorQuality.OBSERVED,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="technical-v1",
    )


def build_volume_ratio_factor(
    *,
    stock_code: str,
    as_of_date: date,
    available_date: date,
    volume_ratio: Decimal | None,
) -> FactorRecord:
    if volume_ratio is None:
        quality = FactorQuality.MISSING
        score_bp = None
    else:
        quality = FactorQuality.OBSERVED
        score_bp = _score_to_bp(min(volume_ratio, Decimal("1")))

    return FactorRecord(
        factor_name="volume.volume_ratio",
        stock_code=stock_code,
        as_of_date=as_of_date,
        available_date=available_date,
        value=volume_ratio,
        score_bp=score_bp,
        quality=quality,
        missing_policy=MissingPolicy.NEUTRAL,
        source_version="volume-v1",
    )


def broker_flow_quality_to_factor_quality(quality: str) -> FactorQuality:
    if quality == "observed":
        return FactorQuality.OBSERVED
    if quality == "estimated":
        return FactorQuality.ESTIMATED
    return FactorQuality.MISSING


def build_broker_flow_factor(
    *,
    stock_code: str,
    as_of_date: date,
    available_date: date,
    net_lots: int | None,
    quality: str,
    rank: int | None,
) -> FactorRecord:
    factor_quality = broker_flow_quality_to_factor_quality(quality)
    return FactorRecord(
        factor_name="broker_flow.net_lots",
        stock_code=stock_code,
        as_of_date=as_of_date,
        available_date=available_date,
        value=net_lots if factor_quality != FactorQuality.MISSING else None,
        score_bp=None,
        quality=factor_quality,
        missing_policy=MissingPolicy.SKIP,
        source_version="broker-flow-v1",
        metadata={"rank": rank, "source_quality": quality},
    )
```

- [x] **Step 4: Verify adapter tests pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_adapters.py tests\test_factor_gate.py tests\test_factor_registry.py tests\test_factor_contract.py -q -o addopts=
```

Expected: all factor tests pass.

---

## Task 5: Application Factor Service and Snapshot Serialization

**Files:**
- Create: `app_module/factor_service.py`
- Test: `tests/test_factor_service_research_run.py`

- [x] **Step 1: Write failing service tests**

Create `tests/test_factor_service_research_run.py`:

```python
from datetime import date
from decimal import Decimal

from app_module.factor_service import FactorService
from decision_module.factors.factor_adapters import build_technical_total_score_factor


def test_factor_service_builds_snapshot_with_gate_diagnostics():
    service = FactorService()
    records = [
        build_technical_total_score_factor(
            stock_code="2330",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            total_score=Decimal("80"),
        )
    ]

    snapshot = service.build_snapshot(records, decision_date=date(2026, 6, 14))

    assert snapshot["schema_version"] == 1
    assert snapshot["decision_date"] == "2026-06-14"
    assert snapshot["records"][0]["factor_name"] == "technical.total_score"
    assert snapshot["diagnostics"] == []


def test_factor_service_snapshot_keeps_neutralized_records():
    service = FactorService()
    record = build_technical_total_score_factor(
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 15),
        total_score=Decimal("80"),
    )
    neutral_record = record.__class__(
        factor_name=record.factor_name,
        stock_code=record.stock_code,
        as_of_date=record.as_of_date,
        available_date=record.available_date,
        value=record.value,
        score_bp=record.score_bp,
        quality=record.quality,
        missing_policy=record.missing_policy.__class__.NEUTRAL,
        source_version=record.source_version,
    )

    snapshot = service.build_snapshot([neutral_record], decision_date=date(2026, 6, 14))

    assert snapshot["neutralized"][0]["quality"] == "neutral"
    assert snapshot["diagnostics"][0]["code"] == "factor.neutralized_lookahead"
```

- [x] **Step 2: Run service tests and confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_service_research_run.py -q -o addopts=
```

Expected: fail because `app_module.factor_service` does not exist.

- [x] **Step 3: Implement `app_module/factor_service.py`**

Create `app_module/factor_service.py`:

```python
"""Factor Layer application service。"""

from __future__ import annotations

from datetime import date

from decision_module.factors.factor_dtos import FactorRecord
from decision_module.factors.factor_gate import FactorGate


class FactorService:
    """收集與序列化 factor snapshot，不修改 scoring 核心。"""

    def __init__(self, gate: FactorGate | None = None):
        self.gate = gate or FactorGate()

    def build_snapshot(
        self,
        records: list[FactorRecord],
        *,
        decision_date: date,
        factor_set_version: str = "factor-layer-v1",
    ) -> dict[str, object]:
        gate_result = self.gate.validate_for_decision(
            records,
            decision_date=decision_date,
        )
        return {
            "schema_version": 1,
            "decision_date": decision_date.isoformat(),
            "factor_set_version": factor_set_version,
            "records": [record.to_dict() for record in gate_result.accepted],
            "neutralized": [record.to_dict() for record in gate_result.neutralized],
            "skipped": [record.to_dict() for record in gate_result.skipped],
            "diagnostics": [item.to_dict() for item in gate_result.diagnostics],
        }
```

- [x] **Step 4: Verify service tests pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_service_research_run.py tests\test_factor_adapters.py tests\test_factor_gate.py -q -o addopts=
```

Expected: all selected tests pass.

---

## Task 6: Research Run Metadata Integration

**Files:**
- Modify: `app_module/research_run_dtos.py`
- Test: `tests/test_factor_service_research_run.py`

- [x] **Step 1: Add failing metadata helper test**

Append to `tests/test_factor_service_research_run.py`:

```python
from app_module.research_run_dtos import ResearchRunMetadataDTO


def test_research_run_metadata_stores_factor_snapshot_in_data_manifest():
    metadata = ResearchRunMetadataDTO(
        run_id="run-factor-1",
        run_name="factor run",
        run_type="backtest",
        data_manifest={
            "factor_snapshot": {
                "schema_version": 1,
                "decision_date": "2026-06-14",
                "records": [],
            }
        },
    )

    assert metadata.factor_snapshot["schema_version"] == 1
```

- [x] **Step 2: Run helper test and confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_service_research_run.py::test_research_run_metadata_stores_factor_snapshot_in_data_manifest -q -o addopts=
```

Expected: fail with `AttributeError: 'ResearchRunMetadataDTO' object has no attribute 'factor_snapshot'`.

- [x] **Step 3: Add non-breaking helper property**

Modify `app_module/research_run_dtos.py` inside `ResearchRunMetadataDTO`:

```python
    @property
    def factor_snapshot(self) -> JsonObject:
        snapshot = self.data_manifest.get("factor_snapshot", {})
        if not isinstance(snapshot, dict):
            raise ValueError("factor_snapshot 必須是 object")
        return snapshot

    @property
    def factor_contributions(self) -> JsonObject:
        contributions = self.data_manifest.get("factor_contributions", {})
        if not isinstance(contributions, dict):
            raise ValueError("factor_contributions 必須是 object")
        return contributions
```

- [x] **Step 4: Verify metadata helper test passes**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_service_research_run.py -q -o addopts=
```

Expected: all factor service tests pass.

---

## Task 7: Cross-run Factor Metadata Reads Saved Snapshot Only

**Files:**
- Modify: `app_module/research_run_comparison_service.py`
- Test: `tests/test_research_run_comparison_service.py`

- [x] **Step 1: Add failing comparison test**

Append to `tests/test_research_run_comparison_service.py`:

```python
def test_collect_factor_attribution_reads_saved_factor_snapshot_only():
    service = ResearchRunComparisonService()
    run = _metadata(
        "run-factor",
        data_manifest={
            "factor_snapshot": {
                "schema_version": 1,
                "decision_date": "2026-06-14",
                "records": [{"factor_name": "technical.total_score", "stock_code": "2330"}],
            }
        },
    )

    result = service.collect_factor_attribution([run])

    assert result["run-factor"]["factor_snapshot"]["records"][0]["factor_name"] == "technical.total_score"
```

If `_metadata` helper in the file does not accept `data_manifest`, update only that helper signature:

```python
def _metadata(run_id: str, **overrides):
    values = {...}
    values.update(overrides)
    return ResearchRunMetadataDTO(**values)
```

- [x] **Step 2: Run comparison test and confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_research_run_comparison_service.py::test_collect_factor_attribution_reads_saved_factor_snapshot_only -q -o addopts=
```

Expected: fail because `collect_factor_attribution` does not exist.

- [x] **Step 3: Implement saved metadata reader**

Modify `app_module/research_run_comparison_service.py`:

```python
    def collect_factor_attribution(
        self, runs: list[ResearchRunMetadataDTO]
    ) -> dict[str, dict[str, Any]]:
        return {
            run.run_id: {
                "factor_snapshot": dict(run.factor_snapshot),
                "factor_contributions": dict(run.factor_contributions),
            }
            for run in runs
        }
```

- [x] **Step 4: Verify comparison tests pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_research_run_comparison_service.py -q -o addopts=
```

Expected: all comparison service tests pass.

---

## Task 8: Quant Guard and Focused Regression

**Files:**
- No new files.

- [x] **Step 1: Run factor test group**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_contract.py tests\test_factor_gate.py tests\test_factor_registry.py tests\test_factor_adapters.py tests\test_factor_service_research_run.py tests\test_research_run_comparison_service.py -q -o addopts=
```

Expected: all selected tests pass.

- [x] **Step 2: Run quant guard**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
```

Expected: exit 0.

- [x] **Step 3: Run mypy on touched modules**

Run:

```powershell
.\.venv\Scripts\python.exe -m mypy decision_module app_module
```

Expected: success or only existing unrelated errors. If errors are related to new factor files, fix before continuing.

- [x] **Step 4: Run py_compile on changed Python files**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile decision_module\factors\__init__.py decision_module\factors\factor_dtos.py decision_module\factors\factor_registry.py decision_module\factors\factor_gate.py decision_module\factors\factor_adapters.py app_module\factor_service.py app_module\research_run_dtos.py app_module\research_run_comparison_service.py
```

Expected: exit 0.

---

## Task 9: Documentation Coverage

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify if user-visible UI changes were introduced: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] **Step 1: Update Snapshot**

Set Month 3 priority to current implementation state:

```markdown
1. Month 3 Factor Layer v1：Factor Contract、Registry、Look-ahead Gate 與既有技術 / 量能 / 券商分點 adapter 已進入實作。
```

- [x] **Step 2: Update 6M Roadmap Month 3**

Add status note under Month 3:

```markdown
> 2026-06-14 狀態：Factor Contract / Registry / Gate / v1 adapter 實作已開始；v1 不接營收、法人或估值新資料源。
```

- [x] **Step 3: Update Architecture**

Replace the "未來 Factor Layer" wording with "Factor Layer v1" once code lands, and list:

```text
decision_module/factors/factor_dtos.py
decision_module/factors/factor_registry.py
decision_module/factors/factor_gate.py
decision_module/factors/factor_adapters.py
app_module/factor_service.py
```

- [x] **Step 4: Update Index**

Add this implementation plan link if not present:

```markdown
| [2026-06-14-month-3-factor-layer.md](../superpowers/plans/2026-06-14-month-3-factor-layer.md) | Month 3 Factor Layer v1 實作計畫。 |
```

- [x] **Step 5: Verify docs**

Run:

```powershell
rg -n "Month 3|Factor Layer|factor_snapshot|available_date" docs\00_core docs\01_architecture docs\superpowers\plans\2026-06-14-month-3-factor-layer.md
git diff --check
```

Expected: Month 3 wording appears in scoped authority docs, and `git diff --check` exits 0.

---

## Task 10: Final Full Gate Before Completion

**Files:**
- No new files.

- [x] **Step 1: Run complete pytest**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -o addopts=
```

Expected: pass. Record count and warnings.

- [x] **Step 2: Run project mypy**

Run:

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

Expected: success.

- [x] **Step 3: Run quant guard**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
```

Expected: exit 0.

- [x] **Step 4: Run git review**

Run:

```powershell
git status --short
git diff --stat
git diff --check
```

Expected: only Month 3 factor files, tests, and scoped docs are modified; diff check exits 0.

- [ ] **Step 5: Commit only after user approval**

Before staging, re-read `docs/agents/git_exclusions.md`. Stage only Month 3 files:

```powershell
git add decision_module\factors app_module\factor_service.py app_module\research_run_dtos.py app_module\research_run_comparison_service.py tests\test_factor_contract.py tests\test_factor_gate.py tests\test_factor_registry.py tests\test_factor_adapters.py tests\test_factor_service_research_run.py tests\test_research_run_comparison_service.py docs\00_core\PROJECT_SNAPSHOT.md docs\00_core\ROADMAP_6M_ENGINEERING.md docs\00_core\DEVELOPMENT_ROADMAP.md docs\00_core\DOCUMENTATION_INDEX.md docs\01_architecture\system_architecture.md docs\superpowers\plans\2026-06-14-month-3-factor-layer.md docs\superpowers\specs\2026-06-14-month-3-factor-layer-design.md
git commit -m "feat(month3): add factor layer foundation"
```

Expected: commit succeeds.

---

## Self-review Notes

- This plan implements the approved spec without adding new data sources.
- It keeps factor output separate from `ScoringEngine`.
- It uses integer basis points and `Decimal` at factor boundaries.
- It stores factor metadata inside existing Research Run JSON fields first, avoiding schema migration in v1.
- It includes explicit no-look-ahead behavior through `FactorGate` tests.
