from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Iterable

from decision_module.factors.factor_dtos import (
    FactorDiagnostic,
    FactorGateResult,
    FactorQuality,
    FactorRecord,
    MissingPolicy,
)


class FactorLookAheadError(ValueError):
    pass


class FactorMissingError(ValueError):
    pass


class FactorGate:
    def validate_for_decision(
        self,
        records: Iterable[FactorRecord],
        *,
        decision_date: date,
        neutral_score_bp: int = 5000,
    ) -> FactorGateResult:
        self._validate_neutral_score_bp(neutral_score_bp)

        accepted: list[FactorRecord] = []
        neutralized: list[FactorRecord] = []
        skipped: list[FactorRecord] = []
        diagnostics: list[FactorDiagnostic] = []

        for record in records:
            if record.available_date > decision_date:
                if record.missing_policy == MissingPolicy.NEUTRAL:
                    neutralized.append(
                        replace(
                            record,
                            quality=FactorQuality.NEUTRAL,
                            score_bp=neutral_score_bp,
                        )
                    )
                    diagnostics.append(
                        self._diagnostic(
                            record,
                            "factor.neutralized_lookahead",
                            "factor available_date is after decision_date; neutralized",
                        )
                    )
                    continue
                if record.missing_policy == MissingPolicy.SKIP:
                    skipped.append(record)
                    diagnostics.append(
                        self._diagnostic(
                            record,
                            "factor.skipped_lookahead",
                            "factor available_date is after decision_date; skipped",
                        )
                    )
                    continue
                raise FactorLookAheadError(
                    "factor look-ahead rejected: "
                    f"factor_name={record.factor_name}, "
                    f"stock_code={record.stock_code}, "
                    f"as_of_date={record.as_of_date.isoformat()}, "
                    f"available_date={record.available_date.isoformat()}, "
                    f"decision_date={decision_date.isoformat()}, "
                    f"source_version={record.source_version}"
                )

            if record.quality == FactorQuality.MISSING:
                if record.missing_policy == MissingPolicy.SKIP:
                    skipped.append(record)
                    diagnostics.append(
                        self._diagnostic(
                            record,
                            "factor.skipped_missing",
                            "factor is missing; skipped",
                        )
                    )
                    continue
                if record.missing_policy == MissingPolicy.NEUTRAL:
                    neutralized.append(
                        replace(
                            record,
                            quality=FactorQuality.NEUTRAL,
                            score_bp=neutral_score_bp,
                        )
                    )
                    diagnostics.append(
                        self._diagnostic(
                            record,
                            "factor.neutralized_missing",
                            "factor is missing; neutralized",
                        )
                    )
                    continue
                raise FactorMissingError(
                    "factor missing rejected: "
                    f"factor_name={record.factor_name}, "
                    f"stock_code={record.stock_code}, "
                    "missing quality with fail-closed policy"
                )

            accepted.append(record)

        return FactorGateResult(
            accepted=tuple(accepted),
            neutralized=tuple(neutralized),
            skipped=tuple(skipped),
            diagnostics=tuple(diagnostics),
        )

    @staticmethod
    def _diagnostic(
        record: FactorRecord,
        code: str,
        message: str,
    ) -> FactorDiagnostic:
        return FactorDiagnostic(
            code=code,
            factor_name=record.factor_name,
            stock_code=record.stock_code,
            message=message,
        )

    @staticmethod
    def _validate_neutral_score_bp(neutral_score_bp: int) -> None:
        if isinstance(neutral_score_bp, bool):
            raise TypeError("neutral_score_bp must be int")
        if not isinstance(neutral_score_bp, int):
            raise TypeError("neutral_score_bp must be int")
        if not 0 <= neutral_score_bp <= 10000:
            raise ValueError("neutral_score_bp must be between 0 and 10000")
