"""從 V2.4 paper baseline 建立 fail-closed V2.5 health review 基線。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any


class PositionHealthBaselineService:
    """缺真實 thesis 時固定 WATCH；不修改持倉或執行動作。"""

    _REQUIRED_FIELDS = (
        "entry_thesis",
        "invalidation",
        "holding_horizon",
        "review_date",
    )

    def build(self, source_path: str | Path) -> dict[str, Any]:
        path = Path(source_path)
        source = json.loads(path.read_text(encoding="utf-8"))
        return self._build_payload(source, source_path=path)

    def build_from_paper_snapshot(
        self,
        *,
        decision_date: str,
        source_result_id: str,
        allocations: Sequence[Mapping[str, Any]],
        source_path: str | Path,
    ) -> dict[str, Any]:
        """Build the same fail-closed contract from a verified Paper snapshot.

        The daily refresh producer reads the snapshot itself in a single
        read-only transaction, then delegates the position contract to this
        service.  It therefore cannot silently introduce a second health
        schema or treat a Paper quantity as a human thesis.
        """

        source = {
            "decision_date": decision_date,
            "source_result_id": source_result_id,
            "allocations": list(allocations),
        }
        return self._build_payload(source, source_path=Path(source_path))

    def _build_payload(
        self,
        source: Mapping[str, Any],
        *,
        source_path: Path,
    ) -> dict[str, Any]:
        allocations = source.get("allocations")
        if not isinstance(allocations, list):
            raise ValueError("paper baseline allocations must be a list")

        positions = []
        for allocation in allocations:
            if not isinstance(allocation, dict):
                continue
            shares = allocation.get("executable_shares")
            if isinstance(shares, bool) or not isinstance(shares, int) or shares <= 0:
                continue
            positions.append(
                {
                    "stock_code": str(allocation.get("stock_code") or ""),
                    "stock_name": str(allocation.get("stock_name") or ""),
                    "paper_shares": shares,
                    "paper_weight_bp": int(allocation.get("constrained_weight_bp") or 0),
                    "state": "WATCH",
                    "entry_thesis": None,
                    "invalidation": None,
                    "holding_horizon": None,
                    "review_date": None,
                    "required_human_fields": list(self._REQUIRED_FIELDS),
                    "reasons": [f"missing_{field}" for field in self._REQUIRED_FIELDS],
                    "source_trace": [
                        f"paper_baseline:{source.get('source_result_id') or source_path.stem}"
                    ],
                    "auto_action_allowed": False,
                }
            )

        diagnostics = [] if positions else ["no_active_paper_positions"]
        return {
            "source_path": str(source_path.resolve()),
            "decision_date": str(source.get("decision_date") or ""),
            "research_only": True,
            "writes_positions_db": False,
            "auto_action_allowed": False,
            "positions": positions,
            "diagnostics": diagnostics,
            "warnings": [
                "human_thesis_required_before_health_transition_validation",
                "position_health_baseline_is_not_an_exit_instruction",
            ],
        }
