"""V1.6 cross-sectional factor snapshot pipeline."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
from typing import Any, Iterable, Mapping

from app_module.cross_sectional_factor_dtos import (
    ConceptBasketDefinition,
    CrossSectionalFactorDiagnostic,
    CrossSectionalFactorRow,
    CrossSectionalFactorSnapshot,
    parse_factor_quality,
    parse_missing_policy,
)
from app_module.factor_service import FactorService
from app_module.research_run_dtos import canonical_json
from decision_module.factors.factor_dtos import FactorRecord


class CrossSectionalFactorPipeline:
    """Build daily cross-sectional factor snapshots without touching scoring."""

    def __init__(self, factor_service: FactorService | None = None) -> None:
        self.factor_service = factor_service or FactorService()

    def build_snapshot(
        self,
        records: Iterable[FactorRecord],
        *,
        decision_date: date,
        universe_id: str,
        factor_set_version: str = "cross-sectional-factor-v1",
        source_version: str = "v1.6-cross-sectional-factor-pipeline",
        sector_by_stock: Mapping[str, str] | None = None,
        concept_baskets: Iterable[ConceptBasketDefinition] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> CrossSectionalFactorSnapshot:
        concept_basket_items = tuple(concept_baskets)
        gated = self.factor_service.build_snapshot(
            list(records),
            decision_date=decision_date,
            factor_set_version=factor_set_version,
        )
        diagnostics = self._diagnostics_from_gate(gated)
        concept_by_stock, concept_diagnostics = self._concept_by_stock(
            concept_basket_items,
            decision_date=decision_date,
        )
        diagnostics.extend(concept_diagnostics)

        rows = self._build_rows(
            gated,
            decision_date=decision_date,
            sector_by_stock=sector_by_stock or {},
            concept_by_stock=concept_by_stock,
        )
        snapshot_metadata = {
            "gate_summary": {
                "accepted_count": len(gated.get("records", [])),
                "neutralized_count": len(gated.get("neutralized", [])),
                "skipped_count": len(gated.get("skipped", [])),
                "diagnostic_count": len(gated.get("diagnostics", [])),
            },
            "concept_basket_count": len(concept_basket_items),
        }
        snapshot_metadata.update(dict(metadata or {}))

        snapshot_id = self._snapshot_id(
            decision_date=decision_date,
            factor_set_version=factor_set_version,
            universe_id=universe_id,
            rows=rows,
            diagnostics=diagnostics,
        )
        return CrossSectionalFactorSnapshot(
            snapshot_id=snapshot_id,
            decision_date=decision_date,
            factor_set_version=factor_set_version,
            universe_id=universe_id,
            source_version=source_version,
            rows=tuple(rows),
            diagnostics=tuple(diagnostics),
            metadata=snapshot_metadata,
        )

    def _build_rows(
        self,
        gated: dict[str, Any],
        *,
        decision_date: date,
        sector_by_stock: Mapping[str, str],
        concept_by_stock: Mapping[str, ConceptBasketDefinition],
    ) -> list[CrossSectionalFactorRow]:
        source_records = [
            *self._records_from_snapshot(gated, "records"),
            *self._records_from_snapshot(gated, "neutralized"),
        ]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in source_records:
            grouped[str(record.get("factor_name", ""))].append(record)

        rows: list[CrossSectionalFactorRow] = []
        for factor_name in sorted(grouped):
            factor_records = sorted(
                grouped[factor_name],
                key=lambda item: (
                    -1 if (score_bp := item.get("score_bp")) is None else -int(score_bp),
                    str(item.get("stock_code", "")),
                ),
            )
            ranks = self._rank_records(factor_records)
            universe_size = len(factor_records)
            for record in factor_records:
                stock_code = str(record.get("stock_code", ""))
                rank = ranks.get(stock_code)
                concept = concept_by_stock.get(stock_code)
                metadata = dict(record.get("metadata") or {})
                if concept is not None:
                    metadata["concept_basket_version"] = concept.basket_version
                    metadata["concept_basket_available_date"] = concept.available_date.isoformat()
                row_id = self._row_id(
                    decision_date=decision_date,
                    stock_code=stock_code,
                    factor_name=factor_name,
                )
                rows.append(
                    CrossSectionalFactorRow(
                        row_id=row_id,
                        stock_code=stock_code,
                        factor_name=factor_name,
                        as_of_date=date.fromisoformat(str(record["as_of_date"])),
                        available_date=date.fromisoformat(str(record["available_date"])),
                        value=self._parse_value(record.get("value")),
                        score_bp=record.get("score_bp"),
                        rank=rank,
                        quantile_bp=self._quantile_bp(rank, universe_size),
                        universe_size=universe_size,
                        quality=parse_factor_quality(record["quality"]),
                        missing_policy=parse_missing_policy(record["missing_policy"]),
                        source_version=str(record.get("source_version", "")),
                        sector=sector_by_stock.get(stock_code),
                        concept_basket=concept.basket_id if concept is not None else None,
                        metadata=metadata,
                    )
                )
        return sorted(rows, key=lambda row: (row.factor_name, row.rank or 999999, row.stock_code))

    @staticmethod
    def _rank_records(records: list[dict[str, Any]]) -> dict[str, int | None]:
        ranks: dict[str, int | None] = {}
        previous_score: int | None = None
        previous_rank: int | None = None
        for index, record in enumerate(records, start=1):
            stock_code = str(record.get("stock_code", ""))
            raw_score = record.get("score_bp")
            if raw_score is None:
                ranks[stock_code] = None
                continue
            score = int(raw_score)
            rank = previous_rank if previous_score == score and previous_rank is not None else index
            ranks[stock_code] = rank
            previous_score = score
            previous_rank = rank
        return ranks

    @staticmethod
    def _quantile_bp(rank: int | None, universe_size: int) -> int | None:
        if rank is None:
            return None
        if universe_size <= 1:
            return 10000
        value = (Decimal(universe_size - rank) / Decimal(universe_size - 1)) * Decimal("10000")
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @staticmethod
    def _records_from_snapshot(snapshot: dict[str, Any], key: str) -> list[dict[str, Any]]:
        records = snapshot.get(key, [])
        if not isinstance(records, list):
            return []
        return [dict(item) for item in records if isinstance(item, dict)]

    @staticmethod
    def _diagnostics_from_gate(snapshot: dict[str, Any]) -> list[CrossSectionalFactorDiagnostic]:
        diagnostics: list[CrossSectionalFactorDiagnostic] = []
        for item in CrossSectionalFactorPipeline._records_from_snapshot(snapshot, "diagnostics"):
            diagnostics.append(
                CrossSectionalFactorDiagnostic(
                    code=str(item.get("code", "")),
                    factor_name=str(item.get("factor_name", "")),
                    stock_code=str(item.get("stock_code", "")),
                    message=str(item.get("message", "")),
                )
            )
        return diagnostics

    @staticmethod
    def _concept_by_stock(
        concept_baskets: Iterable[ConceptBasketDefinition],
        *,
        decision_date: date,
    ) -> tuple[dict[str, ConceptBasketDefinition], list[CrossSectionalFactorDiagnostic]]:
        concept_by_stock: dict[str, ConceptBasketDefinition] = {}
        diagnostics: list[CrossSectionalFactorDiagnostic] = []
        for basket in sorted(concept_baskets, key=lambda item: item.basket_id):
            if basket.available_date > decision_date:
                diagnostics.append(
                    CrossSectionalFactorDiagnostic(
                        code="concept_basket_unavailable",
                        message="concept basket available_date is after decision_date; assignment skipped",
                        metadata={
                            "basket_id": basket.basket_id,
                            "available_date": basket.available_date,
                            "decision_date": decision_date,
                        },
                    )
                )
                continue
            for stock_code in basket.members:
                concept_by_stock.setdefault(stock_code, basket)
        return concept_by_stock, diagnostics

    @staticmethod
    def _parse_value(value: Any) -> Decimal | int | str | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        text = str(value)
        try:
            return Decimal(text)
        except (InvalidOperation, ValueError):
            return text

    @staticmethod
    def _row_id(*, decision_date: date, stock_code: str, factor_name: str) -> str:
        payload = {
            "decision_date": decision_date.isoformat(),
            "stock_code": stock_code,
            "factor_name": factor_name,
        }
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        return f"csfr_{digest[:20]}"

    @staticmethod
    def _snapshot_id(
        *,
        decision_date: date,
        factor_set_version: str,
        universe_id: str,
        rows: list[CrossSectionalFactorRow],
        diagnostics: list[CrossSectionalFactorDiagnostic],
    ) -> str:
        payload = {
            "decision_date": decision_date.isoformat(),
            "factor_set_version": factor_set_version,
            "universe_id": universe_id,
            "rows": [row.to_dict() for row in rows],
            "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        }
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        return f"csf_{decision_date.strftime('%Y%m%d')}_{digest[:16]}"
