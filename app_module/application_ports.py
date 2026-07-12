"""Application orchestration 使用的最小結構型 ports。"""

from pathlib import Path
from typing import Protocol

import pandas as pd

from app_module.dtos import RecommendationResultDTO


class MarketFrameProvider(Protocol):
    def __call__(self) -> pd.DataFrame: ...


class RecommendationEvidencePort(Protocol):
    last_excluded_candidates_json: list[dict[str, object]]
    last_screening_matrix: list[dict[str, object]]
    last_why_not_payload_json: list[dict[str, object]]
    last_liquidity_gate_payload_json: list[dict[str, object]]
    last_exclusion_quality: str
    last_exclusion_warnings_json: list[str]


class RegimeResultPort(Protocol):
    regime: str
    regime_name_cn: str
    confidence: float
    details: dict[str, object]


class RegimeServicePort(Protocol):
    def detect_regime(self) -> RegimeResultPort: ...


class RecommendationRepositoryPort(Protocol):
    def save_result(self, result: RecommendationResultDTO) -> str: ...


class UniverseWatchlistPort(Protocol):
    def save_watchlist(
        self,
        *,
        name: str,
        codes: list[str],
        source: str,
        description: str,
    ) -> object: ...


class BrokerBranchWritePort(Protocol):
    def write_daily(self, frame: pd.DataFrame, path: Path) -> None: ...

    def write_merged(self, frame: pd.DataFrame, path: Path) -> None: ...
