from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


BUY_SCORE_THRESHOLDS = (58, 60, 62, 65, 70)
SELL_SCORE_THRESHOLDS = (38, 40, 42, 45, 50)
CONFIRMATION_DAYS = (1, 2, 3)
COOLDOWN_DAYS = (2, 3, 5)
ROBUSTNESS_LABELS = (
    "stable_positive",
    "fragile",
    "inconclusive",
    "harmful_or_noisy",
)

READ_ONLY_THRESHOLD_ACCESS_BOUNDARY = {
    "writes_allowed": False,
    "threshold_promotion_allowed": False,
    "recommendation_defaults_change_allowed": False,
    "production_scheduler_allowed": False,
    "investment_effectiveness_claim": False,
}

THRESHOLD_REPORT_LIMITATIONS = (
    "此矩陣僅檢查鄰近固定參數是否方向一致，不挑選最佳參數，也不自動 promote threshold。",
    "缺少歷史 replay 或成熟 outcome 時一律標示 inconclusive，不以未成熟資料推論有效性。",
    "本報告不改推薦預設參數、不寫 DB、不啟用 scheduler，也不宣稱投資有效性。",
)


@dataclass(frozen=True)
class ThresholdRobustnessObservation:
    buy_score: int
    sell_score: int
    confirmation_days: int
    cooldown_days: int
    ready_outcome_count: int
    benchmark_excess_bp: int
    forward_return_bp: int | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThresholdRobustnessRow:
    buy_score: int
    sell_score: int
    confirmation_days: int
    cooldown_days: int
    ready_outcome_count: int
    forward_return_bp: int | None
    benchmark_excess_bp: int | None
    positive_neighbor_count: int
    label: str
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThresholdRobustnessReport:
    generated_at: str
    source_mode: str
    rows: tuple[ThresholdRobustnessRow, ...]
    access_boundary: dict[str, bool]
    limitations: tuple[str, ...]
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "source_mode": self.source_mode,
            "rows": [row.to_dict() for row in self.rows],
            "access_boundary": dict(self.access_boundary),
            "limitations": list(self.limitations),
            "diagnostics": list(self.diagnostics),
        }


class ThresholdRobustnessReadModel:
    """Read-only fixed-threshold neighborhood robustness matrix."""

    def __init__(
        self,
        *,
        observations: Iterable[ThresholdRobustnessObservation],
        min_sample_size: int = 1,
        source_mode: str = "in_memory",
    ) -> None:
        self.observations = tuple(observations)
        self.min_sample_size = int(min_sample_size)
        self.source_mode = source_mode

    def build_report(self) -> ThresholdRobustnessReport:
        by_config = {
            (
                int(item.buy_score),
                int(item.sell_score),
                int(item.confirmation_days),
                int(item.cooldown_days),
            ): item
            for item in self.observations
        }
        rows = []
        diagnostics: list[str] = []
        if not by_config:
            diagnostics.append("threshold_replay_input_missing")

        for buy_score in BUY_SCORE_THRESHOLDS:
            for sell_score in SELL_SCORE_THRESHOLDS:
                for confirmation_days in CONFIRMATION_DAYS:
                    for cooldown_days in COOLDOWN_DAYS:
                        config = (buy_score, sell_score, confirmation_days, cooldown_days)
                        observation = by_config.get(config)
                        positive_neighbor_count = self._positive_neighbor_count(config, by_config)
                        rows.append(
                            self._build_row(
                                buy_score=buy_score,
                                sell_score=sell_score,
                                confirmation_days=confirmation_days,
                                cooldown_days=cooldown_days,
                                observation=observation,
                                positive_neighbor_count=positive_neighbor_count,
                            )
                        )

        diagnostics.extend(
            sorted(
                {
                    diagnostic
                    for observation in self.observations
                    for diagnostic in observation.diagnostics
                }
            )
        )
        return ThresholdRobustnessReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            source_mode=self.source_mode,
            rows=tuple(rows),
            access_boundary=dict(READ_ONLY_THRESHOLD_ACCESS_BOUNDARY),
            limitations=THRESHOLD_REPORT_LIMITATIONS,
            diagnostics=tuple(diagnostics),
        )

    def _build_row(
        self,
        *,
        buy_score: int,
        sell_score: int,
        confirmation_days: int,
        cooldown_days: int,
        observation: ThresholdRobustnessObservation | None,
        positive_neighbor_count: int,
    ) -> ThresholdRobustnessRow:
        warnings: list[str] = []
        limitations: list[str] = []
        if observation is None:
            limitations.append("缺少此設定的歷史 replay / outcome 輸入，維持 inconclusive。")
            label = "inconclusive"
            ready_outcome_count = 0
            forward_return_bp = None
            benchmark_excess_bp = None
        else:
            ready_outcome_count = int(observation.ready_outcome_count)
            forward_return_bp = observation.forward_return_bp
            benchmark_excess_bp = int(observation.benchmark_excess_bp)
            if ready_outcome_count < self.min_sample_size:
                limitations.append("成熟樣本數低於最小門檻，維持 inconclusive。")
                label = "inconclusive"
            elif benchmark_excess_bp <= 0 or (forward_return_bp is not None and int(forward_return_bp) <= 0):
                label = "harmful_or_noisy"
            elif positive_neighbor_count >= 2:
                label = "stable_positive"
            else:
                warnings.append("positive_result_without_neighbor_support")
                label = "fragile"

        return ThresholdRobustnessRow(
            buy_score=buy_score,
            sell_score=sell_score,
            confirmation_days=confirmation_days,
            cooldown_days=cooldown_days,
            ready_outcome_count=ready_outcome_count,
            forward_return_bp=forward_return_bp,
            benchmark_excess_bp=benchmark_excess_bp,
            positive_neighbor_count=positive_neighbor_count,
            label=label,
            warnings=tuple(warnings),
            limitations=tuple(limitations),
        )

    @staticmethod
    def _positive_neighbor_count(
        config: tuple[int, int, int, int],
        by_config: dict[tuple[int, int, int, int], ThresholdRobustnessObservation],
    ) -> int:
        buy_score, sell_score, confirmation_days, cooldown_days = config
        count = 0
        for other_config, observation in by_config.items():
            if other_config == config:
                continue
            other_buy, other_sell, other_confirmation, other_cooldown = other_config
            distance = (
                abs(BUY_SCORE_THRESHOLDS.index(other_buy) - BUY_SCORE_THRESHOLDS.index(buy_score))
                + abs(SELL_SCORE_THRESHOLDS.index(other_sell) - SELL_SCORE_THRESHOLDS.index(sell_score))
                + abs(CONFIRMATION_DAYS.index(other_confirmation) - CONFIRMATION_DAYS.index(confirmation_days))
                + abs(COOLDOWN_DAYS.index(other_cooldown) - COOLDOWN_DAYS.index(cooldown_days))
            )
            if distance == 1 and int(observation.benchmark_excess_bp) > 0:
                count += 1
        return count


def sample_threshold_robustness_observations() -> tuple[ThresholdRobustnessObservation, ...]:
    return (
        ThresholdRobustnessObservation(60, 40, 2, 3, 12, 120, 150),
        ThresholdRobustnessObservation(58, 40, 2, 3, 8, 90, 110),
        ThresholdRobustnessObservation(62, 40, 2, 3, 9, 100, 130),
        ThresholdRobustnessObservation(65, 45, 2, 3, 7, 80, 95),
        ThresholdRobustnessObservation(70, 50, 3, 5, 10, -60, -40),
    )
