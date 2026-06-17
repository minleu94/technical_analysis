"""Month 6 strategy lifecycle contract and rule engine.

本模組只讀已保存的 Research Run metadata，產生策略生命週期建議。
它不重新跑回測、不抓取當前資料、不修改 ScoringEngine，也不寫入儲存層。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Sequence

from app_module.research_run_dtos import ResearchRunMetadataDTO


class LifecycleAction(str, Enum):
    """Strategy lifecycle action."""

    PROMOTE = "promote"
    HOLD = "hold"
    DEMOTE = "demote"
    RETIRE = "retire"


class GateStatus(str, Enum):
    """Individual gate status."""

    PASS = "pass"
    FAIL = "fail"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class LifecycleGateResult:
    gate_name: str
    status: GateStatus
    reason: str
    observed: str = ""
    threshold: str = ""


@dataclass(frozen=True)
class LifecyclePolicy:
    """Integer/Decimal based lifecycle thresholds.

    `*_bp` fields are basis points. `*_x100` fields store decimal metrics
    multiplied by 100, e.g. Sharpe 0.50 is represented as 50.
    """

    min_trades: int = 20
    min_total_return_bp: int = 0
    min_excess_return_bp: int = 0
    min_sharpe_x100: int = 50
    min_win_rate_bp: int = 5000
    max_drawdown_bp: int = 3000
    demote_drawdown_bp: int = 4000
    retire_drawdown_bp: int = 6000
    max_degraded_factor_ratio_bp: int = 3500
    required_regime_coverage_bp: int = 5000


@dataclass(frozen=True)
class RegimeCompatibilityResult:
    status: GateStatus
    compatible_regimes: tuple[str, ...] = ()
    incompatible_regimes: tuple[str, ...] = ()
    coverage_bp: int = 0
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class LifecycleDecision:
    run_id: str
    action: LifecycleAction
    status: GateStatus
    reasons: tuple[str, ...]
    gates: tuple[LifecycleGateResult, ...]
    regime_compatibility: RegimeCompatibilityResult


@dataclass(frozen=True)
class StrategyDriftReport:
    baseline_run_id: str
    current_run_id: str
    status: GateStatus
    drift_reasons: tuple[str, ...]
    metric_changes: Mapping[str, str] = field(default_factory=dict)
    factor_warnings: tuple[str, ...] = ()


class StrategyLifecycleService:
    """Evaluate strategy lifecycle decisions from saved registry metadata."""

    def __init__(self, policy: LifecyclePolicy | None = None) -> None:
        self.policy = policy or LifecyclePolicy()

    def evaluate_run(
        self,
        run: ResearchRunMetadataDTO,
        *,
        expected_regimes: Sequence[str] | None = None,
    ) -> LifecycleDecision:
        gates = [
            self._trade_count_gate(run),
            self._total_return_gate(run),
            self._sharpe_gate(run),
            self._drawdown_gate(run),
            self._win_rate_gate(run),
            self._excess_return_gate(run),
            self._factor_quality_gate(run),
        ]
        regime_result = self.evaluate_regime_compatibility(
            run,
            expected_regimes=expected_regimes,
        )
        if regime_result.status != GateStatus.PASS:
            gates.append(
                LifecycleGateResult(
                    "regime_compatibility",
                    regime_result.status,
                    "regime coverage 未達策略生命週期門檻",
                    observed=f"{regime_result.coverage_bp}bp",
                    threshold=f"{self.policy.required_regime_coverage_bp}bp",
                )
            )

        action = self._decide_action(run, gates)
        status = GateStatus.PASS if action == LifecycleAction.PROMOTE else (
            GateStatus.FAIL if action in {LifecycleAction.DEMOTE, LifecycleAction.RETIRE} else GateStatus.DEGRADED
        )
        reasons = tuple(gate.reason for gate in gates if gate.status != GateStatus.PASS)
        if action == LifecycleAction.PROMOTE:
            reasons = ("所有 lifecycle gates 通過，可進入 promote 候選",)
        elif action == LifecycleAction.HOLD and not reasons:
            reasons = ("證據不足以 promote，也未達 demote / retire 條件",)

        return LifecycleDecision(
            run_id=run.run_id,
            action=action,
            status=status,
            reasons=reasons,
            gates=tuple(gates),
            regime_compatibility=regime_result,
        )

    def evaluate_regime_compatibility(
        self,
        run: ResearchRunMetadataDTO,
        *,
        expected_regimes: Sequence[str] | None = None,
    ) -> RegimeCompatibilityResult:
        breakdown = run.regime_breakdown
        if not breakdown:
            return RegimeCompatibilityResult(
                GateStatus.DEGRADED,
                warnings=("regime_breakdown_missing",),
            )

        total_trades = Decimal("0")
        compatible_trades = Decimal("0")
        expected = {str(item).lower() for item in expected_regimes or () if str(item)}
        compatible: list[str] = []
        incompatible: list[str] = []

        for regime, payload in breakdown.items():
            trades = self._decimal_from_mapping(payload, "trades")
            total_trades += trades
            regime_key = str(regime).lower()
            if not expected or regime_key in expected:
                compatible_trades += trades
                compatible.append(str(regime))
            else:
                incompatible.append(str(regime))

        if total_trades <= 0:
            return RegimeCompatibilityResult(
                GateStatus.DEGRADED,
                warnings=("regime_trade_count_missing",),
            )

        coverage_bp = int(
            (compatible_trades / total_trades * Decimal("10000")).to_integral_value()
        )
        status = (
            GateStatus.PASS
            if coverage_bp >= self.policy.required_regime_coverage_bp
            else GateStatus.FAIL
        )
        return RegimeCompatibilityResult(
            status,
            compatible_regimes=tuple(compatible),
            incompatible_regimes=tuple(incompatible),
            coverage_bp=coverage_bp,
        )

    def detect_drift(
        self,
        baseline: ResearchRunMetadataDTO,
        current: ResearchRunMetadataDTO,
    ) -> StrategyDriftReport:
        metric_changes: dict[str, str] = {}
        reasons: list[str] = []

        sharpe_delta = self._metric(current, "sharpe_ratio") - self._metric(baseline, "sharpe_ratio")
        metric_changes["sharpe_ratio_delta"] = self._format_decimal(sharpe_delta)
        if sharpe_delta <= Decimal("-0.25"):
            reasons.append("sharpe_ratio_degraded")

        drawdown_delta_bp = self._ratio_delta_bp(
            current,
            baseline,
            "max_drawdown",
        )
        metric_changes["max_drawdown_delta_bp"] = str(drawdown_delta_bp)
        if drawdown_delta_bp >= 1000:
            reasons.append("drawdown_worsened")

        factor_warnings = self._factor_drift_warnings(baseline, current)
        reasons.extend(factor_warnings)

        status = GateStatus.FAIL if reasons else GateStatus.PASS
        return StrategyDriftReport(
            baseline_run_id=baseline.run_id,
            current_run_id=current.run_id,
            status=status,
            drift_reasons=tuple(reasons),
            metric_changes=metric_changes,
            factor_warnings=tuple(factor_warnings),
        )

    def _decide_action(
        self,
        run: ResearchRunMetadataDTO,
        gates: Sequence[LifecycleGateResult],
    ) -> LifecycleAction:
        drawdown_bp = self._ratio_metric_bp(run, "max_drawdown")
        total_return_bp = self._ratio_metric_bp(run, "total_return")
        if drawdown_bp >= self.policy.retire_drawdown_bp or total_return_bp < -1000:
            return LifecycleAction.RETIRE
        if drawdown_bp >= self.policy.demote_drawdown_bp:
            return LifecycleAction.DEMOTE
        if any(gate.status == GateStatus.FAIL for gate in gates):
            return LifecycleAction.HOLD
        if any(gate.status == GateStatus.DEGRADED for gate in gates):
            return LifecycleAction.HOLD
        return LifecycleAction.PROMOTE

    def _trade_count_gate(self, run: ResearchRunMetadataDTO) -> LifecycleGateResult:
        trades = int(self._metric(run, "total_trades"))
        if trades >= self.policy.min_trades:
            return LifecycleGateResult("total_trades", GateStatus.PASS, "交易次數通過", str(trades), str(self.policy.min_trades))
        return LifecycleGateResult("total_trades", GateStatus.FAIL, "交易次數不足，不能只靠少數交易 promote", str(trades), str(self.policy.min_trades))

    def _total_return_gate(self, run: ResearchRunMetadataDTO) -> LifecycleGateResult:
        value_bp = self._ratio_metric_bp(run, "total_return")
        return self._bp_gate(
            "total_return",
            value_bp,
            self.policy.min_total_return_bp,
            "總報酬未達 lifecycle 門檻",
            lower_bound=True,
        )

    def _excess_return_gate(self, run: ResearchRunMetadataDTO) -> LifecycleGateResult:
        value_bp = self._best_excess_return_bp(run.benchmark_results)
        if value_bp is None:
            return LifecycleGateResult(
                "excess_return",
                GateStatus.DEGRADED,
                "缺少已保存 benchmark excess return，不能宣稱優於 benchmark",
            )
        return self._bp_gate(
            "excess_return",
            value_bp,
            self.policy.min_excess_return_bp,
            "benchmark 相對報酬未達門檻",
            lower_bound=True,
        )

    def _sharpe_gate(self, run: ResearchRunMetadataDTO) -> LifecycleGateResult:
        sharpe_x100 = int((self._metric(run, "sharpe_ratio") * Decimal("100")).to_integral_value())
        if sharpe_x100 >= self.policy.min_sharpe_x100:
            return LifecycleGateResult("sharpe_ratio", GateStatus.PASS, "Sharpe 通過", str(sharpe_x100), str(self.policy.min_sharpe_x100))
        return LifecycleGateResult("sharpe_ratio", GateStatus.FAIL, "Sharpe 未達 lifecycle 門檻", str(sharpe_x100), str(self.policy.min_sharpe_x100))

    def _drawdown_gate(self, run: ResearchRunMetadataDTO) -> LifecycleGateResult:
        value_bp = self._ratio_metric_bp(run, "max_drawdown")
        return self._bp_gate(
            "max_drawdown",
            value_bp,
            self.policy.max_drawdown_bp,
            "最大回撤超過 promote 門檻",
            lower_bound=False,
        )

    def _win_rate_gate(self, run: ResearchRunMetadataDTO) -> LifecycleGateResult:
        value_bp = self._ratio_metric_bp(run, "win_rate")
        return self._bp_gate(
            "win_rate",
            value_bp,
            self.policy.min_win_rate_bp,
            "勝率未達 lifecycle 門檻",
            lower_bound=True,
        )

    def _factor_quality_gate(self, run: ResearchRunMetadataDTO) -> LifecycleGateResult:
        records = run.factor_snapshot.get("records", [])
        if not records:
            return LifecycleGateResult(
                "factor_quality",
                GateStatus.DEGRADED,
                "缺少 factor snapshot，策略生命週期只能保守 hold",
            )
        total = len(records)
        degraded = 0
        for record in records:
            if not isinstance(record, Mapping):
                degraded += 1
                continue
            quality = str(record.get("quality", "")).lower()
            if quality in {"degraded", "missing", "stale", "unavailable"}:
                degraded += 1
        degraded_ratio_bp = int(
            (Decimal(degraded) / Decimal(total) * Decimal("10000")).to_integral_value()
        )
        status = (
            GateStatus.PASS
            if degraded_ratio_bp <= self.policy.max_degraded_factor_ratio_bp
            else GateStatus.FAIL
        )
        return LifecycleGateResult(
            "factor_quality",
            status,
            "factor quality degraded ratio 檢查",
            f"{degraded_ratio_bp}bp",
            f"{self.policy.max_degraded_factor_ratio_bp}bp",
        )

    def _bp_gate(
        self,
        name: str,
        observed_bp: int,
        threshold_bp: int,
        failure_reason: str,
        *,
        lower_bound: bool,
    ) -> LifecycleGateResult:
        passed = observed_bp >= threshold_bp if lower_bound else observed_bp <= threshold_bp
        return LifecycleGateResult(
            name,
            GateStatus.PASS if passed else GateStatus.FAIL,
            f"{name} 通過" if passed else failure_reason,
            f"{observed_bp}bp",
            f"{threshold_bp}bp",
        )

    def _metric(self, run: ResearchRunMetadataDTO, key: str) -> Decimal:
        return self._to_decimal(run.metrics.get(key))

    def _ratio_metric_bp(self, run: ResearchRunMetadataDTO, key: str) -> int:
        return int((self._metric(run, key) * Decimal("10000")).to_integral_value())

    def _ratio_delta_bp(
        self,
        current: ResearchRunMetadataDTO,
        baseline: ResearchRunMetadataDTO,
        key: str,
    ) -> int:
        return self._ratio_metric_bp(current, key) - self._ratio_metric_bp(baseline, key)

    def _best_excess_return_bp(self, benchmark_results: Mapping[str, Any]) -> int | None:
        candidates: list[int] = []
        for value in benchmark_results.values():
            if not isinstance(value, Mapping):
                continue
            if "excess_return_bp" in value:
                candidates.append(int(self._to_decimal(value.get("excess_return_bp"))))
            elif "excess_return" in value:
                candidates.append(int((self._to_decimal(value.get("excess_return")) * Decimal("10000")).to_integral_value()))
        return max(candidates) if candidates else None

    def _decimal_from_mapping(self, payload: Any, key: str) -> Decimal:
        if not isinstance(payload, Mapping):
            return Decimal("0")
        return self._to_decimal(payload.get(key))

    def _to_decimal(self, value: Any) -> Decimal:
        if value is None or value == "":
            return Decimal("0")
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return Decimal("0")

    def _format_decimal(self, value: Decimal) -> str:
        return format(value.quantize(Decimal("0.0001")), "f")

    def _factor_drift_warnings(
        self,
        baseline: ResearchRunMetadataDTO,
        current: ResearchRunMetadataDTO,
    ) -> list[str]:
        baseline_names = self._factor_names(baseline)
        current_names = self._factor_names(current)
        warnings: list[str] = []
        if baseline_names and current_names and baseline_names != current_names:
            warnings.append("factor_set_changed")
        if baseline.factor_contributions and not current.factor_contributions:
            warnings.append("factor_contributions_missing")
        return warnings

    def _factor_names(self, run: ResearchRunMetadataDTO) -> tuple[str, ...]:
        records = run.factor_snapshot.get("records", [])
        names = {
            str(record.get("factor_name"))
            for record in records
            if isinstance(record, Mapping) and record.get("factor_name")
        }
        return tuple(sorted(names))
