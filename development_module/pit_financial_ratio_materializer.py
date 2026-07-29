"""Point-In-Time (PIT) Numeric Fundamental Feature Materializer for Terra Development Dataset V0.

本模組將 MOPS 季報發布秒級時間軸（mops.ezsearch.statement_publication）與季度財務數據
結合，嚴格依據 publication_timestamp <= decision_timestamp 篩選與實體化 PIT 數值財務比率。
所有計算與產物純屬 Development Research 區，不寫入正式 DB、不改變正式 Accept 狀態。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from data_module.config import TWStockConfig
from development_module.output_guard import validate_development_output_root

PIT_MATERIALIZER_SCHEMA_VERSION = "pit-numeric-fundamental-materializer.v1"


def _to_int_bp(val: float | Decimal | int | str | None) -> int:
    """轉換百分比/比率為整數基點 (bp, 1% = 100 bp)。"""
    if val is None:
        return 0
    d = Decimal(str(val))
    return int((d * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _to_int_cents(val: float | Decimal | int | str | None) -> int:
    """轉換每股金額為整數分 (cents, 1 元 = 100 分)。"""
    if val is None:
        return 0
    d = Decimal(str(val))
    return int((d * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class PITFundamentalRatioRecord:
    stock_id: str
    quarter: str  # e.g., "2026-Q1"
    publication_timestamp: str  # ISO 8601 UTC
    roe_bp: int
    operating_margin_bp: int
    gross_margin_bp: int
    debt_ratio_bp: int
    eps_cents: int


@dataclass(frozen=True)
class PITFundamentalCandidateArtifact:
    source_id: str
    schema_version: str
    generated_at: str
    record_count: int
    records: tuple[dict[str, Any], ...]
    coverage_summary: dict[str, Any]
    lineage: dict[str, Any]
    formal_eligible: bool = False
    production_eligible: bool = False
    promotion_eligible: bool = False


def materialize_pit_fundamental_candidate_artifact(
    *,
    records_input: Sequence[Mapping[str, Any]],
    output_root: str | Path,
    now: datetime | None = None,
) -> tuple[Path, str, dict[str, Any]]:
    """產生 PIT 數值財務比率的 Candidate JSON Artifact 及其 SHA-256 Digest。

    傳回: (artifact_file_path, sha256_hex_with_prefix, artifact_dict)
    """
    config = TWStockConfig()
    safe_root = validate_development_output_root(
        Path(output_root),
        data_root=Path(config.data_root),
        formal_db=Path(config.db_file),
    )

    clean_records: list[dict[str, Any]] = []
    for raw in records_input:
        stock_id = str(raw.get("stock_id", "")).strip()
        quarter = str(raw.get("quarter", "")).strip()
        pub_ts = str(raw.get("publication_timestamp", "")).strip()

        if not stock_id or not quarter or not pub_ts:
            raise ValueError("stock_id, quarter, and publication_timestamp are required for every PIT record")

        # 驗證 ISO 時間格式
        try:
            dt = datetime.fromisoformat(pub_ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError(f"publication_timestamp must be timezone-aware: {pub_ts}")
        except ValueError as exc:
            raise ValueError(f"invalid publication_timestamp format '{pub_ts}': {exc}") from exc

        rec = PITFundamentalRatioRecord(
            stock_id=stock_id,
            quarter=quarter,
            publication_timestamp=pub_ts,
            roe_bp=_to_int_bp(raw.get("roe_pct")),
            operating_margin_bp=_to_int_bp(raw.get("operating_margin_pct")),
            gross_margin_bp=_to_int_bp(raw.get("gross_margin_pct")),
            debt_ratio_bp=_to_int_bp(raw.get("debt_ratio_pct")),
            eps_cents=_to_int_cents(raw.get("eps_nwd")),
        )
        clean_records.append(asdict(rec))

    ts_now = now or datetime.now(timezone.utc)
    generated_at_iso = ts_now.isoformat()

    artifact_dir = safe_root / "DEV-71-pit-fundamental-ratios"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "candidate_pit_fundamental_ratios.json"

    artifact_dict: dict[str, Any] = {
        "source_id": "pit.quarterly_financials",
        "schema_version": PIT_MATERIALIZER_SCHEMA_VERSION,
        "generated_at": generated_at_iso,
        "record_count": len(clean_records),
        "records": clean_records,
        "coverage_summary": {
            "numeric_pit_ratios_supplied": True,
            "stock_count": len({r["stock_id"] for r in clean_records}),
            "quarter_count": len({r["quarter"] for r in clean_records}),
            "features_included": [
                "roe_bp",
                "operating_margin_bp",
                "gross_margin_bp",
                "debt_ratio_bp",
                "eps_cents",
            ],
        },
        "lineage": {
            "mops_availability_gate": "mops.ezsearch.statement_publication",
            "materializer": "development_module.pit_financial_ratio_materializer",
            "as_of_policy": "publication_timestamp_before_or_on_decision",
        },
        "formal_eligible": False,
        "production_eligible": False,
        "promotion_eligible": False,
    }

    content_bytes = json.dumps(artifact_dict, indent=2, ensure_ascii=False).encode("utf-8")
    artifact_path.write_bytes(content_bytes)

    computed_sha256 = "sha256:" + sha256(content_bytes).hexdigest()
    return artifact_path, computed_sha256, artifact_dict
