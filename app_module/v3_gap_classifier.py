"""Deterministic V3.0 evidence gap classification."""

from __future__ import annotations

from app_module.v3_effectiveness_dtos import V3GapClassification


GAP_RULES: dict[str, tuple[str, str, str]] = {
    "source_missing_screening_matrix": (
        "warning",
        "payload_gap",
        "新推薦結果需保存 screening matrix；舊結果不回補、不重算。",
    ),
    "missing_industry_benchmark": (
        "warning",
        "accepted_residual",
        "缺產業映射時保留 degraded / residual disclosure。",
    ),
    "forward_outcome_missing": (
        "blocking",
        "forward_outcome_gap",
        "補齊已保存事件的 forward outcome 或標示資料尚未成熟。",
    ),
    "sample_below_minimum": (
        "warning",
        "sample_insufficiency",
        "累積更多真實樣本後再做 V3 review 判讀。",
    ),
    "live_gap_missing": (
        "warning",
        "live_gap_missing",
        "需要 live-vs-research gap observation 才能進一步驗證。",
    ),
    "manual_validation_missing": (
        "warning",
        "manual_validation_pending",
        "人工確認樣本門檻、文案與 dashboard disclosure。",
    ),
}


def classify_v3_gap(
    code: str, *, source_trace: str | None = None
) -> V3GapClassification:
    severity, classification, requirement = GAP_RULES.get(
        code,
        (
            "warning",
            "source_gap",
            "保留為待分類缺口；需人工確認 closeout requirement。",
        ),
    )
    manual_status = (
        "PENDING_MANUAL_VALIDATION"
        if classification == "manual_validation_pending"
        else "NOT_REQUIRED"
    )
    return V3GapClassification(
        gap_code=code,
        severity=severity,
        classification=classification,
        source_trace=source_trace,
        closeout_requirement=requirement,
        manual_validation_status=manual_status,
    )
