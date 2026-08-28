"""唯讀 Portfolio Scenario & Stress Lab v1。

這個模組只把目前已標記的持倉市值套用明確、靜態的壓力情境，
不預測市場、不改寫持倉、不產生訂單，也不把結果當成投資有效性證據。
核心金額計算使用 ``Decimal``；輸出 DTO 以字串序列化，避免在核心邏輯引入
裸 ``float``。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable


STRESS_LAB_SCHEMA_VERSION = "portfolio-stress-lab.v1"
_BP_DENOMINATOR = Decimal("10000")
_MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class StressScenarioDefinition:
    scenario_id: str
    label: str
    description: str
    shock_mode: str
    default_shock_bp: int | None
    supported: bool = True
    required_inputs: tuple[str, ...] = ()


STRESS_SCENARIOS: tuple[StressScenarioDefinition, ...] = (
    StressScenarioDefinition(
        scenario_id="fast_drop",
        label="快速下跌 -10%",
        description="對所有有最新價格的持倉套用靜態 -10% 價格情境。",
        shock_mode="uniform_price",
        default_shock_bp=-1000,
    ),
    StressScenarioDefinition(
        scenario_id="gap_limit_down",
        label="跳空跌停 -10%",
        description="用靜態 -10% 價格衝擊揭露跳空／跌停敏感度；不是跌停預測。",
        shock_mode="uniform_price",
        default_shock_bp=-1000,
    ),
    StressScenarioDefinition(
        scenario_id="correlated_selloff",
        label="相關股同跌 -15%",
        description="對所有有最新價格的持倉套用同向 -15% 情境。",
        shock_mode="uniform_price",
        default_shock_bp=-1500,
    ),
    StressScenarioDefinition(
        scenario_id="concentration_event",
        label="最大持倉事件 -20%",
        description="只對目前標記市值最大的單一持倉套用 -20% 情境。",
        shock_mode="largest_position",
        default_shock_bp=-2000,
    ),
    StressScenarioDefinition(
        scenario_id="liquidity_disappears",
        label="流動性消失",
        description="將可標記持倉的可變現價值壓至 0；這是流動性可得性 proxy，不是 P&L 預測。",
        shock_mode="liquidation_capacity",
        default_shock_bp=None,
    ),
    StressScenarioDefinition(
        scenario_id="rotation_failure",
        label="輪動失敗",
        description="需要持倉的產業／概念曝險標籤；目前資料契約尚未提供。",
        shock_mode="unsupported",
        default_shock_bp=None,
        supported=False,
        required_inputs=("sector_or_concept_exposures",),
    ),
    StressScenarioDefinition(
        scenario_id="source_outage",
        label="來源中斷",
        description="模擬價格來源不可用；沒有價格時不補值、不估算。",
        shock_mode="source_outage",
        default_shock_bp=None,
        supported=False,
        required_inputs=("price_source_availability",),
    ),
)

_SCENARIOS_BY_ID = {item.scenario_id: item for item in STRESS_SCENARIOS}


@dataclass(frozen=True)
class StressPositionResult:
    stock_code: str
    stock_name: str
    quantity: Decimal
    mark_price: Decimal
    base_value: Decimal
    shock_bp: int
    stressed_value: Decimal
    value_delta: Decimal
    status: str = "ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "quantity": str(self.quantity),
            "mark_price": str(self.mark_price),
            "base_value": str(self.base_value),
            "shock_bp": self.shock_bp,
            "stressed_value": str(self.stressed_value),
            "value_delta": str(self.value_delta),
            "status": self.status,
        }


@dataclass(frozen=True)
class PortfolioStressResult:
    scenario: StressScenarioDefinition
    status: str
    priced_position_count: int
    total_position_count: int
    base_market_value: Decimal | None
    stressed_market_value: Decimal | None
    value_delta: Decimal | None
    positions: tuple[StressPositionResult, ...] = ()
    missing_price_codes: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    as_of_date: str | None = None
    research_only: bool = True
    investment_effectiveness_claim: bool = False
    schema_version: str = STRESS_LAB_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scenario": {
                "scenario_id": self.scenario.scenario_id,
                "label": self.scenario.label,
                "description": self.scenario.description,
                "shock_mode": self.scenario.shock_mode,
                "default_shock_bp": self.scenario.default_shock_bp,
            },
            "status": self.status,
            "priced_position_count": self.priced_position_count,
            "total_position_count": self.total_position_count,
            "base_market_value": _decimal_or_none(self.base_market_value),
            "stressed_market_value": _decimal_or_none(self.stressed_market_value),
            "value_delta": _decimal_or_none(self.value_delta),
            "positions": [item.to_dict() for item in self.positions],
            "missing_price_codes": list(self.missing_price_codes),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "as_of_date": self.as_of_date,
            "research_only": self.research_only,
            "investment_effectiveness_claim": self.investment_effectiveness_claim,
        }


class PortfolioStressLabService:
    """對持倉 DTO 做可重播的靜態壓力投影；此服務永遠不寫入資料。"""

    def list_scenarios(self) -> tuple[StressScenarioDefinition, ...]:
        return STRESS_SCENARIOS

    def evaluate_positions(
        self,
        positions: Iterable[Any],
        *,
        scenario_id: str = "fast_drop",
        as_of_date: str | None = None,
    ) -> PortfolioStressResult:
        scenario = _SCENARIOS_BY_ID.get(str(scenario_id))
        if scenario is None:
            raise ValueError(f"unsupported stress scenario: {scenario_id}")

        all_positions = tuple(
            position
            for position in positions
            if bool(getattr(position, "is_holding", True))
        )
        total_count = len(all_positions)
        if not total_count:
            return self._not_computable(
                scenario,
                total_position_count=0,
                blocker="active_positions_missing",
                as_of_date=as_of_date,
            )
        if not scenario.supported:
            return self._not_computable(
                scenario,
                total_position_count=total_count,
                blocker=f"scenario_requires:{','.join(scenario.required_inputs)}",
                as_of_date=as_of_date,
            )
        if scenario.shock_mode == "source_outage":
            return self._not_computable(
                scenario,
                total_position_count=total_count,
                blocker="price_source_unavailable",
                as_of_date=as_of_date,
            )

        priced: list[tuple[Any, Decimal, Decimal, Decimal]] = []
        missing_codes: list[str] = []
        for position in all_positions:
            code = str(getattr(position, "stock_code", "")).strip() or "<unknown>"
            quantity = _decimal(getattr(position, "quantity", None))
            price = _decimal(getattr(position, "current_price", None))
            if quantity is None or price is None or quantity < 0 or price <= 0:
                missing_codes.append(code)
                continue
            base_value = _money(quantity * price)
            priced.append((position, quantity, price, base_value))

        if not priced:
            return self._not_computable(
                scenario,
                total_position_count=total_count,
                blocker="current_price_missing",
                missing_price_codes=tuple(dict.fromkeys(missing_codes)),
                as_of_date=as_of_date,
            )

        largest_code: str | None = None
        if scenario.shock_mode == "largest_position":
            largest_code = max(
                priced,
                key=lambda item: (item[3], str(getattr(item[0], "stock_code", ""))),
            )[0]
            largest_code = str(getattr(largest_code, "stock_code", ""))

        results: list[StressPositionResult] = []
        for position, quantity, price, base_value in priced:
            code = str(getattr(position, "stock_code", "")).strip()
            shock_bp = self._shock_for(
                scenario,
                code=code,
                largest_code=largest_code,
            )
            stressed_value = self._stressed_value(base_value, scenario.shock_mode, shock_bp)
            results.append(
                StressPositionResult(
                    stock_code=code,
                    stock_name=str(getattr(position, "stock_name", "")),
                    quantity=quantity,
                    mark_price=price,
                    base_value=base_value,
                    shock_bp=shock_bp,
                    stressed_value=stressed_value,
                    value_delta=_money(stressed_value - base_value),
                )
            )

        base_total = _money(sum((item.base_value for item in results), Decimal("0")))
        stressed_total = _money(sum((item.stressed_value for item in results), Decimal("0")))
        status = "partial" if missing_codes else "ready"
        warnings = tuple(
            [f"current_price_missing:{code}" for code in dict.fromkeys(missing_codes)]
            + (["partial_positions_only_no_extrapolation"] if missing_codes else [])
        )
        if scenario.shock_mode == "liquidation_capacity":
            warnings = (*warnings, "liquidation_capacity_is_not_pnl")
        return PortfolioStressResult(
            scenario=scenario,
            status=status,
            priced_position_count=len(priced),
            total_position_count=total_count,
            base_market_value=base_total,
            stressed_market_value=stressed_total,
            value_delta=_money(stressed_total - base_total),
            positions=tuple(results),
            missing_price_codes=tuple(dict.fromkeys(missing_codes)),
            warnings=tuple(dict.fromkeys(warnings)),
            as_of_date=as_of_date,
        )

    @staticmethod
    def _shock_for(
        scenario: StressScenarioDefinition,
        *,
        code: str,
        largest_code: str | None,
    ) -> int:
        if scenario.shock_mode == "liquidation_capacity":
            return -10000
        if scenario.shock_mode == "largest_position" and code != largest_code:
            return 0
        return int(scenario.default_shock_bp or 0)

    @staticmethod
    def _stressed_value(base_value: Decimal, shock_mode: str, shock_bp: int) -> Decimal:
        if shock_mode == "liquidation_capacity":
            return Decimal("0.00")
        multiplier = (_BP_DENOMINATOR + Decimal(shock_bp)) / _BP_DENOMINATOR
        return _money(base_value * multiplier)

    @staticmethod
    def _not_computable(
        scenario: StressScenarioDefinition,
        *,
        total_position_count: int,
        blocker: str,
        missing_price_codes: tuple[str, ...] = (),
        as_of_date: str | None,
    ) -> PortfolioStressResult:
        return PortfolioStressResult(
            scenario=scenario,
            status="not_computable",
            priced_position_count=0,
            total_position_count=total_position_count,
            base_market_value=None,
            stressed_market_value=None,
            value_delta=None,
            missing_price_codes=missing_price_codes,
            blockers=(blocker,),
            as_of_date=as_of_date,
        )


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _decimal_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


__all__ = [
    "PortfolioStressLabService",
    "PortfolioStressResult",
    "StressPositionResult",
    "StressScenarioDefinition",
    "STRESS_LAB_SCHEMA_VERSION",
    "STRESS_SCENARIOS",
]
