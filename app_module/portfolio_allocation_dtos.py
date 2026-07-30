"""Rule/ML 同單位配置與確定性投影的中立契約。

本模組只保存整數 bp、整數股數與 Decimal 金額。它不依賴 ``ml_module``，
也不提供任何券商送單能力。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import hashlib
import json
from types import MappingProxyType
from typing import Any, Iterable, Mapping, cast


TOTAL_WEIGHT_BP = 10000
ALLOWED_BLEND_ALPHA_BP = frozenset({0, 2000, 3500, 5000})
POSITION_HEALTH_STATES = frozenset(
    {
        "HEALTHY",
        "WATCH",
        "REDUCE_CANDIDATE",
        "EXIT_CANDIDATE",
        "CLOSED",
    }
)


def _validate_int(
    field_name: str,
    value: object,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return value


def _validate_bp(field_name: str, value: object) -> int:
    return _validate_int(field_name, value, minimum=0, maximum=TOTAL_WEIGHT_BP)


def _validate_decimal(
    field_name: str,
    value: object,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise ValueError(f"{field_name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if positive and value <= Decimal("0"):
        raise ValueError(f"{field_name} must be positive")
    if non_negative and value < Decimal("0"):
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _validate_non_empty(field_name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _validate_sha256(field_name: str, value: object) -> str:
    text = _validate_non_empty(field_name, value)
    digest = text[7:] if text.startswith("sha256:") else ""
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{field_name} must be a sha256: digest")
    return text


def _payload_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _validate_iso_date(field_name: str, value: object) -> str:
    text = _validate_non_empty(field_name, value)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    return text


def _validate_string_tuple(field_name: str, values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must be an iterable of strings, not one string")
    normalized = tuple(values)
    if any(not isinstance(item, str) or not item.strip() for item in normalized):
        raise ValueError(f"{field_name} must contain non-empty strings")
    return tuple(dict.fromkeys(item.strip() for item in normalized))


@dataclass(frozen=True)
class AllocationWeightContract:
    """持倉權重與現金嚴格守恆的 10,000 bp 契約。"""

    symbol_weights_bp: Mapping[str, int]
    cash_weight_bp: int

    def __post_init__(self) -> None:
        raw: object = self.symbol_weights_bp
        if isinstance(raw, Mapping):
            items = list(raw.items())
        elif isinstance(raw, tuple):
            items = list(raw)
        else:
            raise ValueError("symbol_weights_bp must be a mapping or tuple of pairs")

        normalized: dict[str, int] = {}
        for item in items:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError("symbol_weights_bp must contain symbol/weight pairs")
            raw_symbol, raw_weight = item
            symbol = _validate_non_empty("stock_code", raw_symbol)
            if symbol.upper() == "CASH":
                raise ValueError("CASH must be represented by cash_weight_bp")
            if symbol in normalized:
                raise ValueError(f"duplicate stock_code: {symbol}")
            normalized[symbol] = _validate_bp(f"symbol_weights_bp[{symbol}]", raw_weight)

        cash_bp = _validate_bp("cash_weight_bp", self.cash_weight_bp)
        if sum(normalized.values()) + cash_bp != TOTAL_WEIGHT_BP:
            raise ValueError("symbol weights plus cash_weight_bp must equal 10000")

        object.__setattr__(
            self,
            "symbol_weights_bp",
            cast(Mapping[str, int], MappingProxyType(dict(sorted(normalized.items())))),
        )

    @classmethod
    def cash_only(cls) -> AllocationWeightContract:
        return cls(symbol_weights_bp={}, cash_weight_bp=TOTAL_WEIGHT_BP)

    def weight_for(self, stock_code: str) -> int:
        return self.symbol_weights_bp.get(stock_code, 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol_weights_bp": dict(self.symbol_weights_bp),
            "cash_weight_bp": self.cash_weight_bp,
            "total_weight_bp": TOTAL_WEIGHT_BP,
        }


@dataclass(frozen=True)
class MLAllocationSignalRow:
    """ML 每檔配置訊號；所有比例與風險值皆為整數 bp。"""

    stock_code: str
    expected_excess_return_bp: int
    downside_probability_bp: int
    predicted_mae_bp: int
    rank_bp: int
    confidence_bp: int
    coverage_bp: int
    feature_manifest_hash: str
    expected_sector_excess_return_bp: int | None = None
    predicted_mfe_bp: int = 0
    predicted_realized_volatility_bp: int = 0
    predicted_max_drawdown_bp: int = 0
    predicted_tail_loss_bp: int = 0
    fill_feasibility_probability_bp: int = 5_000
    missing_head_ids: tuple[str, ...] = ()
    missing_family_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", _validate_non_empty("stock_code", self.stock_code))
        _validate_int("expected_excess_return_bp", self.expected_excess_return_bp)
        for field_name in (
            "downside_probability_bp",
            "predicted_mae_bp",
            "rank_bp",
            "confidence_bp",
            "coverage_bp",
            "predicted_mfe_bp",
            "predicted_realized_volatility_bp",
            "predicted_max_drawdown_bp",
            "predicted_tail_loss_bp",
            "fill_feasibility_probability_bp",
        ):
            _validate_bp(field_name, getattr(self, field_name))
        if self.expected_sector_excess_return_bp is not None:
            _validate_int(
                "expected_sector_excess_return_bp",
                self.expected_sector_excess_return_bp,
            )
        object.__setattr__(
            self,
            "feature_manifest_hash",
            _validate_non_empty("feature_manifest_hash", self.feature_manifest_hash),
        )
        object.__setattr__(
            self,
            "missing_head_ids",
            _validate_string_tuple("missing_head_ids", self.missing_head_ids),
        )
        if (
            self.expected_sector_excess_return_bp is None
        ) != (
            "expected_sector_excess_return_bp" in self.missing_head_ids
        ):
            raise ValueError(
                "sector excess value and missing-head mask are inconsistent"
            )
        object.__setattr__(
            self,
            "missing_family_ids",
            _validate_string_tuple("missing_family_ids", self.missing_family_ids),
        )
        object.__setattr__(self, "reasons", _validate_string_tuple("reasons", self.reasons))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "expected_excess_return_bp": self.expected_excess_return_bp,
            "downside_probability_bp": self.downside_probability_bp,
            "predicted_mae_bp": self.predicted_mae_bp,
            "rank_bp": self.rank_bp,
            "confidence_bp": self.confidence_bp,
            "coverage_bp": self.coverage_bp,
            "feature_manifest_hash": self.feature_manifest_hash,
            "expected_sector_excess_return_bp": (
                self.expected_sector_excess_return_bp
            ),
            "predicted_mfe_bp": self.predicted_mfe_bp,
            "predicted_realized_volatility_bp": (
                self.predicted_realized_volatility_bp
            ),
            "predicted_max_drawdown_bp": self.predicted_max_drawdown_bp,
            "predicted_tail_loss_bp": self.predicted_tail_loss_bp,
            "fill_feasibility_probability_bp": (
                self.fill_feasibility_probability_bp
            ),
            "missing_head_ids": list(self.missing_head_ids),
            "missing_family_ids": list(self.missing_family_ids),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class MLAllocationProposal:
    """不具執行權限的 ML 配置提案。"""

    decision_date: str
    model_id: str
    dataset_id: str
    universe_id: str
    policy_id: str
    requested_weights: AllocationWeightContract
    model_hash: str
    dataset_identity_hash: str
    dataset_manifest_file_hash: str
    universe_hash: str
    policy_hash: str
    coverage_bp: int
    feature_family_weights_bp: Mapping[str, int] = field(
        default_factory=lambda: {"unattributed": TOTAL_WEIGHT_BP}
    )
    estimated_turnover_bp: int = 0
    estimated_transaction_cost: Decimal = Decimal("0")
    fallback_reason: str | None = None
    signals: tuple[MLAllocationSignalRow, ...] = ()
    missing_family_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    formal_oos_allowed: bool = False
    production_action_allowed: bool = False
    production_blend_alpha_bp: int = 0
    broker_order_allowed: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "decision_date",
            "model_id",
            "dataset_id",
            "universe_id",
            "policy_id",
            "model_hash",
            "dataset_identity_hash",
            "dataset_manifest_file_hash",
            "universe_hash",
            "policy_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _validate_non_empty(field_name, getattr(self, field_name)),
            )
        if not isinstance(self.requested_weights, AllocationWeightContract):
            raise ValueError("requested_weights must be AllocationWeightContract")
        _validate_bp("coverage_bp", self.coverage_bp)
        raw_family_weights: object = self.feature_family_weights_bp
        if not isinstance(raw_family_weights, Mapping):
            raise ValueError("feature_family_weights_bp must be a mapping")
        family_weights: dict[str, int] = {}
        for raw_family_id, raw_weight_bp in raw_family_weights.items():
            family_id = _validate_non_empty("feature_family_id", raw_family_id)
            if family_id in family_weights:
                raise ValueError(f"duplicate feature_family_id: {family_id}")
            family_weights[family_id] = _validate_bp(
                f"feature_family_weights_bp[{family_id}]",
                raw_weight_bp,
            )
        if not family_weights or sum(family_weights.values()) != TOTAL_WEIGHT_BP:
            raise ValueError("feature family weights must equal 10000")
        object.__setattr__(
            self,
            "feature_family_weights_bp",
            cast(
                Mapping[str, int],
                MappingProxyType(dict(sorted(family_weights.items()))),
            ),
        )
        _validate_bp("estimated_turnover_bp", self.estimated_turnover_bp)
        _validate_decimal(
            "estimated_transaction_cost",
            self.estimated_transaction_cost,
            non_negative=True,
        )
        if self.fallback_reason is not None:
            object.__setattr__(
                self,
                "fallback_reason",
                _validate_non_empty("fallback_reason", self.fallback_reason),
            )
        if any(not isinstance(row, MLAllocationSignalRow) for row in self.signals):
            raise ValueError("signals must contain MLAllocationSignalRow values")
        signal_symbols = [row.stock_code for row in self.signals]
        if len(signal_symbols) != len(set(signal_symbols)):
            raise ValueError("signals must contain unique stock_code values")
        object.__setattr__(
            self,
            "missing_family_ids",
            _validate_string_tuple("missing_family_ids", self.missing_family_ids),
        )
        object.__setattr__(self, "reasons", _validate_string_tuple("reasons", self.reasons))
        if self.formal_oos_allowed is not False:
            raise ValueError("ML allocation proposal cannot authorize formal OOS")
        if self.production_action_allowed is not False:
            raise ValueError("ML allocation proposal cannot authorize production action")
        _validate_int(
            "production_blend_alpha_bp",
            self.production_blend_alpha_bp,
            minimum=0,
            maximum=TOTAL_WEIGHT_BP,
        )
        if self.production_blend_alpha_bp != 0:
            raise ValueError("ML allocation proposal cannot authorize non-zero alpha")
        if self.broker_order_allowed is not False:
            raise ValueError("ML allocation proposals cannot authorize broker orders")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_date": self.decision_date,
            "model_id": self.model_id,
            "dataset_id": self.dataset_id,
            "universe_id": self.universe_id,
            "policy_id": self.policy_id,
            "requested_weights": self.requested_weights.to_dict(),
            "model_hash": self.model_hash,
            "dataset_identity_hash": self.dataset_identity_hash,
            "dataset_manifest_file_hash": self.dataset_manifest_file_hash,
            "universe_hash": self.universe_hash,
            "policy_hash": self.policy_hash,
            "coverage_bp": self.coverage_bp,
            "feature_family_weights_bp": dict(self.feature_family_weights_bp),
            "estimated_turnover_bp": self.estimated_turnover_bp,
            "estimated_transaction_cost": str(self.estimated_transaction_cost),
            "fallback_reason": self.fallback_reason,
            "signals": [row.to_dict() for row in self.signals],
            "missing_family_ids": list(self.missing_family_ids),
            "reasons": list(self.reasons),
            "formal_oos_allowed": False,
            "production_action_allowed": False,
            "production_blend_alpha_bp": 0,
            "broker_order_allowed": False,
        }


@dataclass(frozen=True)
class PortfolioAllocationContextRow:
    """決策當下可得的持倉、健康與成交限制上下文。"""

    stock_code: str
    current_weight_bp: int | None
    stock_name: str = ""
    sector_id: str | None = None
    health_state: str = "HEALTHY"
    hard_risk_reasons: tuple[str, ...] = ()
    reference_price: Decimal | None = None
    current_shares: int | None = None
    median_volume_20d_shares: int | None = None
    market_data_as_of_date: str | None = None
    trading_days_since_last_trade: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", _validate_non_empty("stock_code", self.stock_code))
        if self.current_weight_bp is not None:
            _validate_bp("current_weight_bp", self.current_weight_bp)
        if self.sector_id is not None:
            object.__setattr__(self, "sector_id", _validate_non_empty("sector_id", self.sector_id))
        if self.health_state not in POSITION_HEALTH_STATES:
            raise ValueError(f"unsupported health_state: {self.health_state}")
        object.__setattr__(
            self,
            "hard_risk_reasons",
            _validate_string_tuple("hard_risk_reasons", self.hard_risk_reasons),
        )
        if self.reference_price is not None:
            _validate_decimal("reference_price", self.reference_price, positive=True)
        for field_name in ("current_shares", "median_volume_20d_shares"):
            value = getattr(self, field_name)
            if value is not None:
                _validate_int(field_name, value, minimum=0)
        if self.trading_days_since_last_trade is not None:
            _validate_int(
                "trading_days_since_last_trade",
                self.trading_days_since_last_trade,
                minimum=0,
            )
        if self.market_data_as_of_date is not None:
            object.__setattr__(
                self,
                "market_data_as_of_date",
                _validate_non_empty("market_data_as_of_date", self.market_data_as_of_date),
            )


@dataclass(frozen=True)
class CausalPortfolioState:
    """T-1 Paper ledger 的完整持倉快照與可重播 hash。"""

    as_of_date: str
    current_weights: AllocationWeightContract
    complete_symbol_universe: tuple[str, ...]
    state_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "as_of_date",
            _validate_iso_date("as_of_date", self.as_of_date),
        )
        if not isinstance(self.current_weights, AllocationWeightContract):
            raise ValueError("current_weights must be AllocationWeightContract")
        if any(weight <= 0 for weight in self.current_weights.symbol_weights_bp.values()):
            raise ValueError(
                "causal portfolio state must omit zero-weight symbols"
            )
        symbols = _validate_string_tuple(
            "complete_symbol_universe",
            self.complete_symbol_universe,
        )
        if symbols != tuple(sorted(symbols)):
            raise ValueError("complete_symbol_universe must use canonical sort order")
        if symbols != tuple(self.current_weights.symbol_weights_bp):
            raise ValueError(
                "complete_symbol_universe must equal every current held symbol"
            )
        object.__setattr__(self, "complete_symbol_universe", symbols)
        object.__setattr__(
            self,
            "state_hash",
            _validate_sha256("state_hash", self.state_hash),
        )
        if self.state_hash != _payload_hash(self._payload_without_hash()):
            raise ValueError("causal portfolio state hash mismatch")

    @classmethod
    def create(
        cls,
        *,
        as_of_date: str,
        current_weights: AllocationWeightContract,
    ) -> "CausalPortfolioState":
        if not isinstance(current_weights, AllocationWeightContract):
            raise ValueError("current_weights must be AllocationWeightContract")
        canonical_weights = AllocationWeightContract(
            symbol_weights_bp={
                symbol: weight
                for symbol, weight in current_weights.symbol_weights_bp.items()
                if weight > 0
            },
            cash_weight_bp=current_weights.cash_weight_bp,
        )
        symbols = tuple(canonical_weights.symbol_weights_bp)
        payload = {
            "schema_version": "causal-portfolio-state.v1",
            "as_of_date": as_of_date,
            "complete_symbol_universe": list(symbols),
            "current_weights": canonical_weights.to_dict(),
        }
        return cls(
            as_of_date=as_of_date,
            current_weights=canonical_weights,
            complete_symbol_universe=symbols,
            state_hash=_payload_hash(payload),
        )

    def _payload_without_hash(self) -> dict[str, object]:
        return {
            "schema_version": "causal-portfolio-state.v1",
            "as_of_date": self.as_of_date,
            "complete_symbol_universe": list(self.complete_symbol_universe),
            "current_weights": self.current_weights.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._payload_without_hash(),
            "state_hash": self.state_hash,
        }


@dataclass(frozen=True)
class PromotionAuthorizationReference:
    """指向受 custody 管理的完整 Promotion 證據鏈。

    這只是檔案定位與 expected hash，不代表授權；Portfolio consumer 仍須以
    部署時注入的可信 verifier 重讀所有檔案。
    """

    authorization_path: str
    evidence_path: str
    registry_revision_path: str
    model_artifact_path: str
    dataset_manifest_path: str
    oof_bundle_path: str
    shadow_evidence_path: str
    authorization_artifact_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "authorization_path",
            "evidence_path",
            "registry_revision_path",
            "model_artifact_path",
            "dataset_manifest_path",
            "oof_bundle_path",
            "shadow_evidence_path",
        ):
            object.__setattr__(
                self,
                field_name,
                _validate_non_empty(field_name, getattr(self, field_name)),
            )
        object.__setattr__(
            self,
            "authorization_artifact_hash",
            _validate_sha256(
                "authorization_artifact_hash",
                self.authorization_artifact_hash,
            ),
        )


@dataclass(frozen=True)
class PortfolioAllocationRequestV2:
    """Rule/ML 配置投影請求；不含任何 apply 或送單旗標。"""

    decision_date: str
    capital_amount: Decimal
    rule_requested_weights: AllocationWeightContract
    ml_proposal: MLAllocationProposal
    alpha_bp: int
    contexts: tuple[PortfolioAllocationContextRow, ...]
    current_cash_bp: int
    weekly_turnover_used_bp: int = 0
    rule_policy_hash: str = "rule-policy-unversioned"
    promotion_authorization: PromotionAuthorizationReference | None = None
    causal_portfolio_state: CausalPortfolioState | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_date", _validate_non_empty("decision_date", self.decision_date))
        _validate_decimal("capital_amount", self.capital_amount, positive=True)
        if not isinstance(self.rule_requested_weights, AllocationWeightContract):
            raise ValueError("rule_requested_weights must be AllocationWeightContract")
        if not isinstance(self.ml_proposal, MLAllocationProposal):
            raise ValueError("ml_proposal must be MLAllocationProposal")
        if self.ml_proposal.decision_date != self.decision_date:
            raise ValueError("ML proposal decision_date must match request decision_date")
        if self.promotion_authorization is not None and not isinstance(
            self.promotion_authorization,
            PromotionAuthorizationReference,
        ):
            raise ValueError(
                "promotion_authorization must be PromotionAuthorizationReference"
            )
        if self.causal_portfolio_state is not None and not isinstance(
            self.causal_portfolio_state,
            CausalPortfolioState,
        ):
            raise ValueError(
                "causal_portfolio_state must be CausalPortfolioState"
            )
        _validate_int("alpha_bp", self.alpha_bp)
        if self.alpha_bp not in ALLOWED_BLEND_ALPHA_BP:
            raise ValueError("alpha_bp must be one of 0, 2000, 3500, 5000")
        _validate_bp("current_cash_bp", self.current_cash_bp)
        _validate_bp("weekly_turnover_used_bp", self.weekly_turnover_used_bp)
        object.__setattr__(
            self,
            "rule_policy_hash",
            _validate_non_empty("rule_policy_hash", self.rule_policy_hash),
        )
        if any(not isinstance(row, PortfolioAllocationContextRow) for row in self.contexts):
            raise ValueError("contexts must contain PortfolioAllocationContextRow values")
        context_symbols = [row.stock_code for row in self.contexts]
        if len(context_symbols) != len(set(context_symbols)):
            raise ValueError("contexts must contain unique stock_code values")


@dataclass(frozen=True)
class PortfolioAllocationRowV2:
    """單一標的從請求權重到可執行研究提案的完整軌跡。"""

    stock_code: str
    stock_name: str
    rule_requested_weight_bp: int
    ml_requested_weight_bp: int
    blended_weight_bp: int
    target_weight_bp: int
    current_weight_bp: int | None
    gap_weight_bp: int | None
    executable_weight_bp: int | None
    executable_shares: int | None
    reference_price: Decimal | None
    executable_amount: Decimal
    estimated_cost: Decimal
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", _validate_non_empty("stock_code", self.stock_code))
        for field_name in (
            "rule_requested_weight_bp",
            "ml_requested_weight_bp",
            "blended_weight_bp",
            "target_weight_bp",
        ):
            _validate_bp(field_name, getattr(self, field_name))
        if self.current_weight_bp is not None:
            _validate_bp("current_weight_bp", self.current_weight_bp)
        if self.gap_weight_bp is not None:
            _validate_int("gap_weight_bp", self.gap_weight_bp)
        if self.executable_weight_bp is not None:
            _validate_bp("executable_weight_bp", self.executable_weight_bp)
        if self.executable_shares is not None:
            _validate_int("executable_shares", self.executable_shares, minimum=0)
        if self.reference_price is not None:
            _validate_decimal("reference_price", self.reference_price, positive=True)
        _validate_decimal("executable_amount", self.executable_amount, non_negative=True)
        _validate_decimal("estimated_cost", self.estimated_cost, non_negative=True)
        object.__setattr__(
            self,
            "diagnostics",
            _validate_string_tuple("diagnostics", self.diagnostics),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "rule_requested_weight_bp": self.rule_requested_weight_bp,
            "ml_requested_weight_bp": self.ml_requested_weight_bp,
            "blended_weight_bp": self.blended_weight_bp,
            "target_weight_bp": self.target_weight_bp,
            "current_weight_bp": self.current_weight_bp,
            "gap_weight_bp": self.gap_weight_bp,
            "executable_weight_bp": self.executable_weight_bp,
            "executable_shares": self.executable_shares,
            "reference_price": str(self.reference_price) if self.reference_price is not None else None,
            "executable_amount": str(self.executable_amount),
            "estimated_cost": str(self.estimated_cost),
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class PortfolioAllocationResultV2:
    """配置結果永遠是唯讀建議，不具下單或自動套用權限。"""

    decision_date: str
    alpha_bp: int
    rule_requested_weights: AllocationWeightContract
    ml_requested_weights: AllocationWeightContract
    blended_weights: AllocationWeightContract
    target_weights: AllocationWeightContract
    executable_weights: AllocationWeightContract | None
    rows: tuple[PortfolioAllocationRowV2, ...]
    current_cash_bp: int
    post_cost_cash_amount: Decimal
    total_estimated_cost: Decimal
    advice_action: str
    coverage_bp: int
    model_hash: str
    dataset_identity_hash: str
    dataset_manifest_file_hash: str
    universe_hash: str
    policy_hash: str
    rule_policy_hash: str
    causal_portfolio_state_hash: str | None = None
    missing_family_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    broker_order_allowed: bool = False
    apply_rebalance: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_date", _validate_non_empty("decision_date", self.decision_date))
        _validate_int("alpha_bp", self.alpha_bp)
        if self.alpha_bp not in ALLOWED_BLEND_ALPHA_BP:
            raise ValueError("alpha_bp must be one of 0, 2000, 3500, 5000")
        _validate_bp("coverage_bp", self.coverage_bp)
        for field_name in (
            "rule_requested_weights",
            "ml_requested_weights",
            "blended_weights",
            "target_weights",
        ):
            if not isinstance(getattr(self, field_name), AllocationWeightContract):
                raise ValueError(f"{field_name} must be AllocationWeightContract")
        if self.executable_weights is not None and not isinstance(
            self.executable_weights,
            AllocationWeightContract,
        ):
            raise ValueError("executable_weights must be AllocationWeightContract or None")
        _validate_bp("current_cash_bp", self.current_cash_bp)
        if any(not isinstance(row, PortfolioAllocationRowV2) for row in self.rows):
            raise ValueError("rows must contain PortfolioAllocationRowV2 values")
        row_symbols = [row.stock_code for row in self.rows]
        if len(row_symbols) != len(set(row_symbols)):
            raise ValueError("rows must contain unique stock_code values")
        _validate_decimal(
            "post_cost_cash_amount",
            self.post_cost_cash_amount,
            non_negative=True,
        )
        _validate_decimal(
            "total_estimated_cost",
            self.total_estimated_cost,
            non_negative=True,
        )
        if self.advice_action not in {
            "ADD_CANDIDATE",
            "HOLD",
            "REDUCE_CANDIDATE",
            "EXIT_CANDIDATE",
            "NO_NEW_POSITION",
            "AVOID",
        }:
            raise ValueError(f"unsupported advice_action: {self.advice_action}")
        for field_name in (
            "model_hash",
            "dataset_identity_hash",
            "dataset_manifest_file_hash",
            "universe_hash",
            "policy_hash",
            "rule_policy_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _validate_non_empty(field_name, getattr(self, field_name)),
            )
        if self.causal_portfolio_state_hash is not None:
            object.__setattr__(
                self,
                "causal_portfolio_state_hash",
                _validate_sha256(
                    "causal_portfolio_state_hash",
                    self.causal_portfolio_state_hash,
                ),
            )
        object.__setattr__(
            self,
            "missing_family_ids",
            _validate_string_tuple("missing_family_ids", self.missing_family_ids),
        )
        object.__setattr__(self, "reasons", _validate_string_tuple("reasons", self.reasons))
        if self.broker_order_allowed is not False or self.apply_rebalance is not False:
            raise ValueError("portfolio allocation result cannot authorize execution")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_date": self.decision_date,
            "alpha_bp": self.alpha_bp,
            "rule_requested_weights": self.rule_requested_weights.to_dict(),
            "ml_requested_weights": self.ml_requested_weights.to_dict(),
            "blended_weights": self.blended_weights.to_dict(),
            "target_weights": self.target_weights.to_dict(),
            "executable_weights": (
                self.executable_weights.to_dict() if self.executable_weights is not None else None
            ),
            "rows": [row.to_dict() for row in self.rows],
            "cash": {
                "rule_requested_weight_bp": self.rule_requested_weights.cash_weight_bp,
                "ml_requested_weight_bp": self.ml_requested_weights.cash_weight_bp,
                "blended_weight_bp": self.blended_weights.cash_weight_bp,
                "target_weight_bp": self.target_weights.cash_weight_bp,
                "current_weight_bp": self.current_cash_bp,
                "gap_weight_bp": self.target_weights.cash_weight_bp - self.current_cash_bp,
                "executable_weight_bp": (
                    self.executable_weights.cash_weight_bp
                    if self.executable_weights is not None
                    else None
                ),
                "post_cost_amount": str(self.post_cost_cash_amount),
            },
            "current_cash_bp": self.current_cash_bp,
            "post_cost_cash_amount": str(self.post_cost_cash_amount),
            "total_estimated_cost": str(self.total_estimated_cost),
            "advice_action": self.advice_action,
            "coverage_bp": self.coverage_bp,
            "model_hash": self.model_hash,
            "dataset_identity_hash": self.dataset_identity_hash,
            "dataset_manifest_file_hash": self.dataset_manifest_file_hash,
            "universe_hash": self.universe_hash,
            "policy_hash": self.policy_hash,
            "rule_policy_hash": self.rule_policy_hash,
            "causal_portfolio_state_hash": self.causal_portfolio_state_hash,
            "missing_family_ids": list(self.missing_family_ids),
            "reasons": list(self.reasons),
            "broker_order_allowed": False,
            "apply_rebalance": False,
        }
