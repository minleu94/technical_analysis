"""Matured-label-only calibration monitoring for shadow predictions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN


@dataclass(frozen=True)
class CalibrationOutcomeObservation:
    prediction_id: str
    model_id: str
    dataset_id: str
    decision_date: str
    downside_probability_bp: int
    actual_downside: int | None
    maturity_status: str
    label_available_date: str

    def __post_init__(self) -> None:
        if not all((self.prediction_id, self.model_id, self.dataset_id, self.decision_date)):
            raise ValueError("calibration observation identity is required")
        if (
            isinstance(self.downside_probability_bp, bool)
            or not isinstance(self.downside_probability_bp, int)
            or not 0 <= self.downside_probability_bp <= 10000
        ):
            raise ValueError("downside_probability_bp must be integer bp within 0..10000")
        if self.maturity_status not in {"pending", "ready"}:
            raise ValueError("unsupported maturity_status")
        if self.maturity_status == "pending" and self.actual_downside is not None:
            raise ValueError("pending label cannot have an outcome")
        if self.maturity_status == "ready" and self.actual_downside not in {0, 1}:
            raise ValueError("ready downside outcome must be binary")
        _date(self.decision_date)
        _date(self.label_available_date)


@dataclass(frozen=True)
class CalibrationMonitoringReport:
    model_id: str
    dataset_id: str
    evaluated_as_of: str
    matured_sample_count: int
    excluded_immature_count: int
    downside_brier_bp: int | None
    status: str
    blockers: tuple[str, ...]
    recommended_human_action: str
    auto_retrain_allowed: bool = False
    auto_promotion_allowed: bool = False
    formal_rule_unchanged: bool = True
    production_action_allowed: bool = False


class MaturedLabelCalibrationMonitor:
    def evaluate(
        self,
        *,
        model_id: str,
        dataset_id: str,
        evaluated_as_of: str,
        observations: tuple[CalibrationOutcomeObservation, ...],
    ) -> CalibrationMonitoringReport:
        as_of = _date(evaluated_as_of)
        if not model_id or not dataset_id:
            raise ValueError("model_id and dataset_id are required")
        if any(row.model_id != model_id or row.dataset_id != dataset_id for row in observations):
            raise ValueError("calibration observation model/dataset identity mismatch")
        ids = tuple(row.prediction_id for row in observations)
        if len(ids) != len(set(ids)):
            raise ValueError("prediction_id values must be unique")
        matured = tuple(
            row
            for row in observations
            if row.maturity_status == "ready"
            and row.actual_downside is not None
            and _date(row.label_available_date) <= as_of
        )
        excluded = len(observations) - len(matured)
        if not matured:
            return CalibrationMonitoringReport(
                model_id=model_id,
                dataset_id=dataset_id,
                evaluated_as_of=evaluated_as_of,
                matured_sample_count=0,
                excluded_immature_count=excluded,
                downside_brier_bp=None,
                status="insufficient_matured_labels",
                blockers=("no_matured_labels_available",),
                recommended_human_action="wait_for_matured_labels",
            )
        squared_error_bp2 = 0
        for row in matured:
            actual_downside = row.actual_downside
            if actual_downside is None:
                raise AssertionError("matured calibration row requires an outcome")
            squared_error_bp2 += (
                row.downside_probability_bp - actual_downside * 10000
            ) ** 2
        brier_bp = int(
            (Decimal(squared_error_bp2) / (Decimal(len(matured)) * Decimal(10000))).quantize(
                Decimal("1"), rounding=ROUND_HALF_EVEN
            )
        )
        status = "passed" if brier_bp <= 2500 else "review_required"
        blockers = () if status == "passed" else ("calibration_brier_review_required",)
        return CalibrationMonitoringReport(
            model_id=model_id,
            dataset_id=dataset_id,
            evaluated_as_of=evaluated_as_of,
            matured_sample_count=len(matured),
            excluded_immature_count=excluded,
            downside_brier_bp=brier_bp,
            status=status,
            blockers=blockers,
            recommended_human_action=(
                "continue_shadow_monitoring" if status == "passed" else "review_calibration"
            ),
        )


def _date(value: str) -> date:
    return date.fromisoformat(value[:10])
