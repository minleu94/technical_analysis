"""配置型 ML 的 PIT、資料集與推論邊界契約。

本模組只保存可重播的整數／Decimal 資料。模型內部可以在隔離邊界使用
浮點數，但任何進出本模組的金融數值都必須先量化。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
import hashlib
import json
from types import MappingProxyType
from typing import Literal, Mapping
from zoneinfo import ZoneInfo


FeatureQuality = Literal["observed", "estimated", "degraded", "missing"]
EventTimeSemantics = Literal["realized_observation", "announced_future_event"]
_TAIPEI = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True)
class AllocationWeightContract:
    """Long-only 投組權重；持倉與現金必須嚴格守恆為 10,000 bp。"""

    positions_bp: tuple[tuple[str, int], ...]
    cash_bp: int

    def __post_init__(self) -> None:
        _require_bp("cash_bp", self.cash_bp)
        symbols = tuple(symbol for symbol, _ in self.positions_bp)
        if any(not symbol or not symbol.strip() for symbol in symbols):
            raise ValueError("position symbols must be non-empty")
        if len(symbols) != len(set(symbols)):
            raise ValueError("position symbols must be unique")
        for symbol, weight_bp in self.positions_bp:
            _require_bp(f"positions_bp[{symbol}]", weight_bp, minimum=1)
        if sum(weight for _, weight in self.positions_bp) + self.cash_bp != 10_000:
            raise ValueError("position weights plus cash_bp must equal 10000")

    @property
    def invested_bp(self) -> int:
        return 10_000 - self.cash_bp

    def as_mapping(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self.positions_bp))


@dataclass(frozen=True)
class PITFeatureValue:
    """單一可稽核 PIT 特徵值；缺值以 ``None`` 與 observed=False 表示。"""

    feature_id: str
    family_id: str
    source_id: str
    value_int: int | None
    scale: int
    event_at: str
    available_at: str
    revision_id: str
    quality: FeatureQuality
    content_hash: str
    observed: bool
    event_time_semantics: EventTimeSemantics = "realized_observation"

    def __post_init__(self) -> None:
        _require_text(
            feature_id=self.feature_id,
            family_id=self.family_id,
            source_id=self.source_id,
            event_at=self.event_at,
            available_at=self.available_at,
            revision_id=self.revision_id,
        )
        if isinstance(self.scale, bool) or not isinstance(self.scale, int) or self.scale <= 0:
            raise TypeError("scale must be a positive integer")
        if not isinstance(self.observed, bool):
            raise TypeError("observed must be bool")
        if self.value_int is not None and (
            isinstance(self.value_int, bool) or not isinstance(self.value_int, int)
        ):
            raise TypeError("value_int must be integer units or explicit missing")
        if self.observed and self.value_int is None:
            raise ValueError("observed feature requires value_int")
        if not self.observed and self.value_int is not None:
            raise ValueError("unobserved feature value_int must be missing")
        if self.quality == "missing" and self.observed:
            raise ValueError("missing quality cannot be marked observed")
        if self.quality != "missing" and not self.observed:
            raise ValueError("unobserved feature quality must be missing")
        if self.quality not in {"observed", "estimated", "degraded", "missing"}:
            raise ValueError("quality is unsupported")
        if self.event_time_semantics not in {
            "realized_observation",
            "announced_future_event",
        }:
            raise ValueError("event_time_semantics is unsupported")
        if (
            self.event_time_semantics == "announced_future_event"
            and self.family_id != "corporate_microstructure"
        ):
            raise ValueError(
                "announced_future_event is restricted to corporate_microstructure"
            )
        _parse_temporal(self.event_at, field_name="event_at")
        _available_datetime(self.available_at, field_name="available_at")
        _require_sha256(self.content_hash, field_name="content_hash")


@dataclass(frozen=True)
class CausalPortfolioState:
    """只允許決策前已落帳的投組狀態。"""

    as_of_date: str
    weights: AllocationWeightContract
    weekly_turnover_used_bp: int
    state_hash: str

    def __post_init__(self) -> None:
        _parse_date(self.as_of_date, field_name="as_of_date")
        _require_bp("weekly_turnover_used_bp", self.weekly_turnover_used_bp)
        _require_sha256(self.state_hash, field_name="state_hash")
        expected_hash = self.compute_state_hash(
            as_of_date=self.as_of_date,
            weights=self.weights,
            weekly_turnover_used_bp=self.weekly_turnover_used_bp,
        )
        if self.state_hash != expected_hash:
            raise ValueError("causal portfolio state hash mismatch")

    @classmethod
    def create(
        cls,
        *,
        as_of_date: str,
        weights: AllocationWeightContract,
        weekly_turnover_used_bp: int,
    ) -> "CausalPortfolioState":
        return cls(
            as_of_date=as_of_date,
            weights=weights,
            weekly_turnover_used_bp=weekly_turnover_used_bp,
            state_hash=cls.compute_state_hash(
                as_of_date=as_of_date,
                weights=weights,
                weekly_turnover_used_bp=weekly_turnover_used_bp,
            ),
        )

    @staticmethod
    def compute_state_hash(
        *,
        as_of_date: str,
        weights: AllocationWeightContract,
        weekly_turnover_used_bp: int,
    ) -> str:
        _parse_date(as_of_date, field_name="as_of_date")
        _require_bp("weekly_turnover_used_bp", weekly_turnover_used_bp)
        if not isinstance(weights, AllocationWeightContract):
            raise TypeError("weights must be AllocationWeightContract")
        payload = {
            "schema_version": "causal-portfolio-state.v1",
            "as_of_date": as_of_date,
            "weights": {
                "positions_bp": [
                    [symbol, weight_bp]
                    for symbol, weight_bp in sorted(weights.positions_bp)
                ],
                "cash_bp": weights.cash_bp,
            },
            "weekly_turnover_used_bp": weekly_turnover_used_bp,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class AllocationTargets:
    """由 causal teacher 產生、成熟後才可 fit 的投組配置標籤。"""

    decision_date: str
    horizon_end_date: str
    available_at: str
    target_weights: AllocationWeightContract
    delta_weights_bp: tuple[tuple[str, int], ...]
    risk_contributions_bp: tuple[tuple[str, int], ...]
    risky_budget_bp: int
    cash_bp: int
    rebalance_worthwhile: bool

    def __post_init__(self) -> None:
        decision = _parse_date(self.decision_date, field_name="decision_date")
        horizon_end = _parse_date(self.horizon_end_date, field_name="horizon_end_date")
        if horizon_end <= decision:
            raise ValueError("horizon_end_date must be after decision_date")
        available = _available_datetime(self.available_at, field_name="available_at")
        if available.date() < horizon_end:
            raise ValueError("target available_at must not precede horizon_end_date")
        _require_bp("risky_budget_bp", self.risky_budget_bp)
        _require_bp("cash_bp", self.cash_bp)
        if self.target_weights.cash_bp != self.cash_bp:
            raise ValueError("cash_bp must match target_weights.cash_bp")
        if self.target_weights.invested_bp != self.risky_budget_bp:
            raise ValueError("risky_budget_bp must equal target invested weight")
        if not isinstance(self.rebalance_worthwhile, bool):
            raise TypeError("rebalance_worthwhile must be bool")

        delta_symbols = tuple(symbol for symbol, _ in self.delta_weights_bp)
        if (
            any(not symbol or not symbol.strip() for symbol in delta_symbols)
            or len(delta_symbols) != len(set(delta_symbols))
        ):
            raise ValueError("delta weight symbols must be non-empty and unique")
        for symbol, delta_bp in self.delta_weights_bp:
            _require_integer(f"delta_weights_bp[{symbol}]", delta_bp)
            if not -10_000 <= delta_bp <= 10_000:
                raise ValueError("delta weight must be within -10000..10000")

        risk_symbols = tuple(symbol for symbol, _ in self.risk_contributions_bp)
        target_symbols = tuple(symbol for symbol, _ in self.target_weights.positions_bp)
        if set(risk_symbols) != set(target_symbols) or len(risk_symbols) != len(set(risk_symbols)):
            raise ValueError("risk contribution symbols must match target position symbols")
        for symbol, contribution_bp in self.risk_contributions_bp:
            _require_bp(
                f"risk_contributions_bp[{symbol}]",
                contribution_bp,
                maximum=self.risky_budget_bp,
            )
        if sum(value for _, value in self.risk_contributions_bp) != self.risky_budget_bp:
            raise ValueError("risk contributions must sum to risky_budget_bp")

    @property
    def target_weight_bp(self) -> Mapping[str, int]:
        return self.target_weights.as_mapping()

    @property
    def delta_weight_bp(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self.delta_weights_bp))

    @property
    def risk_contribution_bp(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self.risk_contributions_bp))

    def is_fit_eligible(self, *, training_as_of: str) -> bool:
        cutoff = _available_datetime(training_as_of, field_name="training_as_of")
        return _available_datetime(self.available_at, field_name="available_at") <= cutoff


@dataclass(frozen=True)
class PortfolioMLDatasetRow:
    """配置模型的一列；特徵與投組狀態都必須符合決策時點。"""

    row_id: str
    decision_at: str
    symbol: str
    features: tuple[PITFeatureValue, ...]
    missing_family_ids: tuple[str, ...]
    portfolio_state: CausalPortfolioState
    dataset_identity_hash: str
    feature_registry_hash: str
    source_manifest_hashes: tuple[tuple[str, str], ...]
    targets: AllocationTargets | None = None

    def __post_init__(self) -> None:
        _require_text(row_id=self.row_id, decision_at=self.decision_at, symbol=self.symbol)
        decision_at = _decision_datetime(self.decision_at)
        if _parse_date(
            self.portfolio_state.as_of_date, field_name="portfolio_state.as_of_date"
        ) >= decision_at.date():
            raise ValueError("portfolio state must be a T-1-or-earlier state")
        if not self.features:
            raise ValueError("features are required")
        feature_ids = tuple(feature.feature_id for feature in self.features)
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("feature ids must be unique within a dataset row")
        for feature in self.features:
            if _available_datetime(
                feature.available_at, field_name=f"{feature.feature_id}.available_at"
            ) > decision_at:
                raise ValueError("feature available_at must not exceed decision_at")
            if (
                feature.event_time_semantics == "realized_observation"
                and _temporal_datetime(
                    feature.event_at,
                    field_name=f"{feature.feature_id}.event_at",
                )
                > decision_at
            ):
                raise ValueError(
                    "realized feature event_at must not exceed decision_at"
                )

        if (
            len(self.missing_family_ids) != len(set(self.missing_family_ids))
            or any(not family.strip() for family in self.missing_family_ids)
        ):
            raise ValueError("missing_family_ids must be non-empty and unique")
        unobserved_families = {
            feature.family_id for feature in self.features if not feature.observed
        }
        if not unobserved_families.issubset(set(self.missing_family_ids)):
            raise ValueError("unobserved feature families require missing-family masks")
        _require_sha256(
            self.dataset_identity_hash,
            field_name="dataset_identity_hash",
        )
        _require_sha256(self.feature_registry_hash, field_name="feature_registry_hash")
        source_ids = tuple(source_id for source_id, _ in self.source_manifest_hashes)
        if (
            not source_ids
            or len(source_ids) != len(set(source_ids))
            or any(not source_id.strip() for source_id in source_ids)
        ):
            raise ValueError("source manifest ids must be non-empty and unique")
        for source_id, source_hash in self.source_manifest_hashes:
            _require_sha256(source_hash, field_name=f"source_manifest_hashes[{source_id}]")
        if not {feature.source_id for feature in self.features}.issubset(set(source_ids)):
            raise ValueError("every feature source requires a source manifest hash")

        if self.targets is not None:
            if self.targets.decision_date != decision_at.date().isoformat():
                raise ValueError("targets must share the dataset decision date")
            current = dict(self.portfolio_state.weights.positions_bp)
            target = dict(self.targets.target_weights.positions_bp)
            expected_delta = {
                symbol: target.get(symbol, 0) - current.get(symbol, 0)
                for symbol in sorted(set(current) | set(target))
                if target.get(symbol, 0) != current.get(symbol, 0)
            }
            if dict(self.targets.delta_weights_bp) != expected_delta:
                raise ValueError("target delta weights must match the T-1 portfolio state")


@dataclass(frozen=True)
class MLAllocationPrediction:
    """模型數值邊界量化後的單股配置預測。"""

    prediction_id: str
    decision_at: str
    symbol: str
    expected_excess_return_bp: int
    downside_probability_bp: int
    predicted_mae_bp: int
    rank_bp: int
    confidence_bp: int
    feature_snapshot_hash: str
    missing_family_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(
            prediction_id=self.prediction_id,
            decision_at=self.decision_at,
            symbol=self.symbol,
        )
        _decision_datetime(self.decision_at)
        _require_integer("expected_excess_return_bp", self.expected_excess_return_bp)
        _require_bp("downside_probability_bp", self.downside_probability_bp)
        _require_bp("predicted_mae_bp", self.predicted_mae_bp)
        _require_bp("rank_bp", self.rank_bp)
        _require_bp("confidence_bp", self.confidence_bp)
        _require_sha256(self.feature_snapshot_hash, field_name="feature_snapshot_hash")
        if (
            len(self.missing_family_ids) != len(set(self.missing_family_ids))
            or any(not family.strip() for family in self.missing_family_ids)
        ):
            raise ValueError("missing_family_ids must be non-empty and unique")


@dataclass(frozen=True)
class MLAllocationProposal:
    """ML requested weights；不代表已通過 production promotion。"""

    proposal_id: str
    decision_at: str
    model_id: str
    dataset_id: str
    universe_id: str
    policy_id: str
    model_artifact_hash: str
    dataset_identity_hash: str
    dataset_manifest_file_hash: str
    policy_hash: str
    requested_weights: AllocationWeightContract
    predictions: tuple[MLAllocationPrediction, ...]
    feature_family_weights_bp: tuple[tuple[str, int], ...]
    estimated_turnover_bp: int
    estimated_transaction_cost: Decimal
    calibration_ece_bp: int
    drift_psi_bp: int
    coverage_bp: int
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(
            proposal_id=self.proposal_id,
            decision_at=self.decision_at,
            model_id=self.model_id,
            dataset_id=self.dataset_id,
            universe_id=self.universe_id,
            policy_id=self.policy_id,
        )
        decision_at = _decision_datetime(self.decision_at)
        for field_name, value in (
            ("model_artifact_hash", self.model_artifact_hash),
            ("dataset_identity_hash", self.dataset_identity_hash),
            ("dataset_manifest_file_hash", self.dataset_manifest_file_hash),
            ("policy_hash", self.policy_hash),
        ):
            _require_sha256(value, field_name=field_name)
        prediction_ids = tuple(row.prediction_id for row in self.predictions)
        prediction_symbols = tuple(row.symbol for row in self.predictions)
        if (
            len(prediction_ids) != len(set(prediction_ids))
            or len(prediction_symbols) != len(set(prediction_symbols))
        ):
            raise ValueError("proposal predictions require unique ids and symbols")
        if any(_decision_datetime(row.decision_at) != decision_at for row in self.predictions):
            raise ValueError("proposal predictions must share decision_at")

        family_ids = tuple(family_id for family_id, _ in self.feature_family_weights_bp)
        if (
            not family_ids
            or any(not family_id.strip() for family_id in family_ids)
            or len(family_ids) != len(set(family_ids))
        ):
            raise ValueError("feature family weights require unique non-empty ids")
        for family_id, weight_bp in self.feature_family_weights_bp:
            _require_bp(f"feature_family_weights_bp[{family_id}]", weight_bp)
        if sum(value for _, value in self.feature_family_weights_bp) != 10_000:
            raise ValueError("feature family weights must equal 10000")

        _require_bp("estimated_turnover_bp", self.estimated_turnover_bp)
        if (
            isinstance(self.estimated_transaction_cost, bool)
            or not isinstance(self.estimated_transaction_cost, Decimal)
            or not self.estimated_transaction_cost.is_finite()
            or self.estimated_transaction_cost < Decimal("0")
        ):
            raise TypeError("estimated_transaction_cost must be a non-negative Decimal")
        _require_bp("calibration_ece_bp", self.calibration_ece_bp)
        _require_bp("drift_psi_bp", self.drift_psi_bp)
        _require_bp("coverage_bp", self.coverage_bp)
        if any(not blocker or not blocker.strip() for blocker in self.blockers):
            raise ValueError("blockers must be non-empty strings")


def _require_text(**values: str) -> None:
    for field_name, value in values.items():
        if not value or not value.strip():
            raise ValueError(f"{field_name} is required")


def _require_integer(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be integer units")
    return value


def _require_bp(
    field_name: str,
    value: object,
    *,
    minimum: int = 0,
    maximum: int = 10_000,
) -> int:
    numeric = _require_integer(field_name, value)
    if not minimum <= numeric <= maximum:
        raise ValueError(f"{field_name} must be within {minimum}..{maximum} bp")
    return numeric


def _require_sha256(value: str, *, field_name: str) -> None:
    digest = value[7:] if value.startswith("sha256:") else ""
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field_name} must be a sha256: digest")


def _parse_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _parse_temporal(value: str, *, field_name: str) -> date | datetime:
    if len(value) == 10:
        return _parse_date(value, field_name=field_name)
    return _aware_datetime(value, field_name=field_name)


def _aware_datetime(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return parsed.astimezone(_TAIPEI)


def _available_datetime(value: str, *, field_name: str) -> datetime:
    if len(value) == 10:
        parsed_date = _parse_date(value, field_name=field_name)
        return datetime.combine(parsed_date, time.max, tzinfo=_TAIPEI)
    return _aware_datetime(value, field_name=field_name)


def _temporal_datetime(value: str, *, field_name: str) -> datetime:
    """將事件日期保守視為該日結束；避免 08:30 決策讀到同日已實現值。"""

    if len(value) == 10:
        parsed_date = _parse_date(value, field_name=field_name)
        return datetime.combine(parsed_date, time.max, tzinfo=_TAIPEI)
    return _aware_datetime(value, field_name=field_name)


def _decision_datetime(value: str) -> datetime:
    parsed = _aware_datetime(value, field_name="decision_at")
    if parsed.timetz().replace(tzinfo=None) != time(8, 30):
        raise ValueError("decision_at must be 08:30 Asia/Taipei")
    return parsed
