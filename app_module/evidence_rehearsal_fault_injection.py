"""Evidence rehearsal 的 immutable detector-path fault transforms。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import partial
from pathlib import Path
import sqlite3
from types import MappingProxyType

from app_module.evidence_rehearsal_orchestrator import (
    EvidenceRehearsalExecutionRequest,
    EvidenceRehearsalMLInputs,
)


class EvidenceRehearsalSourceOutageError(RuntimeError):
    """Source gateway 的受控 outage。"""


class EvidenceRehearsalFaultInjector:
    """只改變輸入／gateway；不直接寫 report blocker。"""

    def inject(
        self,
        request: EvidenceRehearsalExecutionRequest,
        failure: str,
    ) -> EvidenceRehearsalExecutionRequest:
        if failure == "source_outage":
            return replace(
                request,
                source_error=EvidenceRehearsalSourceOutageError("source_outage"),
                fault_diagnostics=MappingProxyType(
                    {
                        "target": "source_gateway",
                        "mutation": "raise_typed_source_outage",
                        "detector": "EvidenceRehearsalService.run",
                    }
                ),
            )
        if failure == "future_available_date":
            if not request.p0_observations:
                raise ValueError("future_available_date requires a P0 observation")
            first, *remaining = request.p0_observations
            future_date = (
                date.fromisoformat(request.scenario.decision_date) + timedelta(days=1)
            ).isoformat()
            return replace(
                request,
                p0_observations=(
                    replace(first, available_date=future_date),
                    *remaining,
                ),
                fault_diagnostics=MappingProxyType(
                    {
                        "target": f"p0_observation:{first.source_id}",
                        "mutation": "p0_available_date_plus_one_day",
                        "detector": "P0SourceShadowComparisonService",
                    }
                ),
            )
        if failure == "missing_day":
            return replace(
                request,
                working_copy_mutator=partial(
                    _remove_trading_day,
                    decision_date=request.scenario.decision_date,
                ),
                fault_diagnostics=MappingProxyType(
                    {
                        "target": "working_copy.daily_prices",
                        "mutation": "delete_scenario_decision_day",
                        "detector": "HistoricalEvidenceReplayService",
                    }
                ),
            )
        if failure == "schema_missing":
            return replace(
                request,
                working_copy_mutator=_rename_daily_prices,
                fault_diagnostics=MappingProxyType(
                    {
                        "target": "working_copy.daily_prices",
                        "mutation": "rename_required_daily_prices_table",
                        "detector": "HistoricalEvidenceReplayService",
                    }
                ),
            )
        if failure == "immature_label":
            return replace(
                request,
                ml_provider=_ImmatureLabelProvider(),
                fault_diagnostics=MappingProxyType(
                    {
                        "target": "ml_boundary.label",
                        "mutation": "inject_rejected_immature_label_row",
                        "detector": "MLRehearsalComparisonService",
                    }
                ),
            )
        raise ValueError(f"unsupported independent fault injection: {failure}")


def _remove_trading_day(working_copy: Path, *, decision_date: str) -> None:
    decision_key = decision_date.replace("-", "")
    with sqlite3.connect(working_copy) as connection:
        connection.execute(
            """
            DELETE FROM daily_prices
            WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') = ?
            """,
            (decision_key,),
        )


def _rename_daily_prices(working_copy: Path) -> None:
    with sqlite3.connect(working_copy) as connection:
        connection.execute(
            "ALTER TABLE daily_prices RENAME TO injected_missing_daily_prices"
        )


@dataclass(frozen=True)
class _ImmatureManifest:
    dataset_id: str = "injected-immature-label"
    created_at: str = "2026-07-13"
    row_count: int = 1
    frozen: bool = True
    shadow_only: bool = True
    production_eligible: bool = False


@dataclass(frozen=True)
class _ImmatureBoundary:
    accepted_rows: tuple[object, ...] = ()
    rejected_row_ids: tuple[str, ...] = ("immature-label-row",)
    diagnostics_by_row: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("immature-label-row", ("label_not_mature",)),
    )


class _ImmatureLabelProvider:
    def load(self) -> EvidenceRehearsalMLInputs:
        return EvidenceRehearsalMLInputs(
            manifest=_ImmatureManifest(),
            boundary_report=_ImmatureBoundary(),
            predictions=(),
        )
