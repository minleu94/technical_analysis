from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from decision_module.factors.factor_dtos import FactorDefinition, MissingPolicy


class UnknownFactorError(KeyError):
    pass


@dataclass(frozen=True)
class FactorRegistry:
    definitions: Mapping[str, FactorDefinition]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "definitions",
            MappingProxyType(dict(self.definitions)),
        )

    @classmethod
    def default(cls) -> FactorRegistry:
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
        return cls(definitions=definitions)

    def get(self, factor_name: str) -> FactorDefinition:
        try:
            return self.definitions[factor_name]
        except KeyError as exc:
            available = ", ".join(sorted(self.definitions))
            raise UnknownFactorError(
                f"unknown factor: {factor_name}; available factors: {available}"
            ) from exc
