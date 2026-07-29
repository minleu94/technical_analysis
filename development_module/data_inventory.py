"""Field-level Development Data Inventory module for Terra Development Dataset V0.

本模組提供獨立、Sanitized、Machine-readable 的欄位與資料源盤點能力。
僅供研究與開發用途，不寫入正式 DB、不改變排程，也不改寫 Formal Acceptance 狀態。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Literal, Mapping, Sequence

from data_module.config import TWStockConfig
from development_module.contracts import DevelopmentDatasetManifest
from development_module.dataset_integrity import validate_persisted_dataset_v0
from development_module.output_guard import validate_development_output_root
from ml_module.feature_registry import CORE_LONG_HISTORY_FEATURE_REGISTRY
from ml_module.label_registry import CORE_LONG_HISTORY_LABEL_REGISTRY

INVENTORY_SCHEMA_VERSION = "mops-development-data-inventory.v1"

FieldFamily = Literal[
    "price",
    "technical",
    "market",
    "industry",
    "broker",
    "fundamental",
    "microstructure",
    "corporate_action",
    "availability_gate",
]

FieldRole = Literal[
    "feature",
    "label",
    "metadata",
    "availability_gate",
    "candidate_feature",
]

TrainingStatus = Literal[
    "included_in_current_fit",
    "included_evaluation_only",
    "available_not_materialized",
    "candidate_research_only",
    "excluded_by_policy",
    "blocked_missing_artifact",
    "blocked_insufficient_history",
    "blocked_pit_contract",
]


@dataclass(frozen=True)
class DataInventoryField:
    field_id: str
    display_name: str
    family: FieldFamily
    dtype: str
    unit: str
    role: FieldRole
    current_training_status: TrainingStatus
    source_id: str
    source_version: str | None = None
    artifact_citation: str | None = None
    fingerprint: str | None = None
    feature_as_of_policy: str = "feature_as_of_before_decision"
    available_date_policy: str = "available_date_before_or_on_decision"
    coverage_summary: dict[str, Any] = None  # type: ignore[assignment]
    blockers: tuple[str, ...] = ()
    formal_eligible: Literal[False] = False
    production_eligible: Literal[False] = False
    promotion_eligible: Literal[False] = False
    is_numeric_model_feature: bool = True

    def __post_init__(self) -> None:
        if self.coverage_summary is None:
            object.__setattr__(self, "coverage_summary", {})
        if self.formal_eligible is not False:
            raise ValueError("formal_eligible must remain False")
        if self.production_eligible is not False:
            raise ValueError("production_eligible must remain False")
        if self.promotion_eligible is not False:
            raise ValueError("promotion_eligible must remain False")


@dataclass(frozen=True)
class DevelopmentDataInventoryResult:
    inventory_id: str
    generated_at: str
    fields: tuple[DataInventoryField, ...]
    summary: dict[str, Any]
    lineage: dict[str, Any]
    projection: dict[str, Any]
    report: dict[str, Any]
    report_file_path: Path
    report_file_sha256: str
    sanitized_projection_path: Path
    sanitized_projection_sha256: str


def build_development_data_inventory(
    *,
    manifest_path: str | Path,
    dataset_path: str | Path,
    output_root: str | Path,
    candidate_artifacts: Sequence[str | Path] | None = None,
    candidate_expected_hashes: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> DevelopmentDataInventoryResult:
    """產出可重現、Sanitized 的 Development Data Inventory 報告與 Projection。"""
    config = TWStockConfig()
    safe_root = validate_development_output_root(
        Path(output_root),
        data_root=Path(config.data_root),
        formal_db=Path(config.db_file),
    )
    _verify_no_symlink_escape(safe_root)

    manifest_file = Path(manifest_path).resolve()
    dataset_file = Path(dataset_path).resolve()
    manifest = _load_json_object(manifest_file)
    dataset = _load_json_object(dataset_file)

    # 全面比對 Manifest 與 Dataset 的完整性 (Defect 5)
    validate_persisted_dataset_v0(
        manifest_file=manifest_file,
        dataset_file=dataset_file,
        manifest=manifest,
        dataset=dataset,
    )

    expected_hash_map = dict(candidate_expected_hashes or {})
    candidate_hashes: dict[str, str] = {}
    validated_candidate_sources: set[str] = set()

    if candidate_artifacts:
        for raw_p in candidate_artifacts:
            file_p = Path(raw_p).resolve()
            if not file_p.is_file():
                raise ValueError(f"candidate artifact file not found: {file_p}")
            content = file_p.read_bytes()
            computed_hash = "sha256:" + sha256(content).hexdigest()

            # (Strict Requirement) 強制顯式 expected SHA-256 驗證，不可缺失
            expected_h = expected_hash_map.get(str(file_p)) or expected_hash_map.get(file_p.name) or expected_hash_map.get(str(raw_p))
            if not expected_h:
                raise ValueError(f"candidate artifact expected SHA-256 is required for {file_p.name}")

            norm_exp = expected_h if expected_h.startswith("sha256:") else f"sha256:{expected_h}"
            if computed_hash != norm_exp:
                raise ValueError(f"candidate artifact hash mismatch for {file_p.name}: computed {computed_hash} != expected {norm_exp}")

            candidate_hashes[file_p.name] = computed_hash

            # (Defect 7) 以內容 Schema 與 source_id 決定資格，非檔名比對
            cand_json = _load_json_object(file_p)
            src_id = str(cand_json.get("source_id") or cand_json.get("source") or "")
            if src_id:
                validated_candidate_sources.add(src_id)

    fields: list[DataInventoryField] = []

    # 1. 盤點 Core 20 個 Features
    fit_rows = dataset.get("fit_rows", [])
    fit_count = len(fit_rows) if isinstance(fit_rows, list) else 0

    for spec in CORE_LONG_HISTORY_FEATURE_REGISTRY.specs:
        fields.append(
            DataInventoryField(
                field_id=spec.feature_id,
                display_name=spec.feature_id.replace("_", " ").title(),
                family=spec.family,
                dtype=spec.dtype,
                unit=spec.unit,
                role="feature",
                current_training_status="included_in_current_fit",
                source_id=f"core_long_history.{spec.family}",
                source_version="v0-core",
                artifact_citation=f"TerraDatasetV0.manifest.{manifest.get('generation_id')}",
                feature_as_of_policy=spec.availability_policy,
                available_date_policy="available_date_before_or_on_decision",
                coverage_summary={
                    "fit_sample_count": fit_count,
                    "missing_policy": spec.missing_policy,
                },
                blockers=(),
                is_numeric_model_feature=True,
            )
        )

    # 2. 盤點 Core 4 個 Labels
    baseline_fit_labels = {"relative_return_20d_bp", "downside_20d_flag"}
    for label_spec in CORE_LONG_HISTORY_LABEL_REGISTRY.specs:
        is_fit_baseline = label_spec.label_id in baseline_fit_labels
        fields.append(
            DataInventoryField(
                field_id=label_spec.label_id,
                display_name=label_spec.label_id.replace("_", " ").title(),
                family="technical" if "return" in label_spec.label_id else "market",
                dtype=label_spec.dtype,
                unit=label_spec.unit,
                role="label",
                current_training_status="included_in_current_fit"
                if is_fit_baseline
                else "included_evaluation_only",
                source_id="core_long_history.labels",
                source_version="v0-labels",
                artifact_citation=f"TerraDatasetV0.manifest.{manifest.get('generation_id')}",
                feature_as_of_policy="label_horizon_end_date",
                available_date_policy="available_date_after_horizon_end",
                coverage_summary={
                    "fit_sample_count": fit_count if is_fit_baseline else 0,
                    "evaluation_sample_count": len(dataset.get("evaluation_rows", [])),
                    "horizon_trading_days": label_spec.horizon_trading_days,
                },
                blockers=() if is_fit_baseline else ("not_in_first_pass_frozen_baseline_fitting",),
                is_numeric_model_feature=True,
            )
        )

    # 3. MOPS EZSearch 季報發布時間 (Availability Gate, NOT Numeric Fundamental)
    mops_has_artifact = "mops.ezsearch.statement_publication" in validated_candidate_sources or "pit.quarterly_financials" in validated_candidate_sources
    fields.append(
        DataInventoryField(
            field_id="mops.ezsearch.statement_publication",
            display_name="MOPS 季報秒級發布時間軸",
            family="fundamental",
            dtype="timestamp",
            unit="none",
            role="availability_gate",
            current_training_status="candidate_research_only"
            if mops_has_artifact
            else "blocked_missing_artifact",
            source_id="mops.ezsearch.statement_publication",
            source_version="mops-ezsearch-statement-publication.v1",
            artifact_citation="validated_mops_candidate_artifact" if mops_has_artifact else "mops_candidate_artifact_not_supplied",
            feature_as_of_policy="official_announcement_at",
            available_date_policy="next_calendar_day_available_date",
            coverage_summary={
                "research_pit_gate_only": True,
                "is_numeric_financial_ratio": False,
            },
            blockers=(
                "availability_timestamp_only_no_numeric_financial_ratios",
                "limited_research_acceptance_only",
            ),
            is_numeric_model_feature=False,
        )
    )

    # 4. Broker 資料族群
    fields.append(
        DataInventoryField(
            field_id="broker.branch_flows",
            display_name="券商分點進出金額與買賣超",
            family="broker",
            dtype="int",
            unit="minor_currency_unit",
            role="candidate_feature",
            current_training_status="excluded_by_policy",
            source_id="broker_dataset",
            source_version="broker-research-v1",
            feature_as_of_policy="t_minus_1_broker_closing",
            available_date_policy="decision_time_available",
            coverage_summary={"excluded_from_v0_long_history_core": True},
            blockers=(
                "excluded_from_core_long_history_v0_policy",
                "broker_license_and_terms_review_pending",
            ),
            is_numeric_model_feature=True,
        )
    )

    # 5. Fundamental 季度財務比率
    fields.append(
        DataInventoryField(
            field_id="fundamental.quarterly_financial_ratios",
            display_name="基本面季度財務比率 (EPS/ROE/資產負債)",
            family="fundamental",
            dtype="int",
            unit="bp",
            role="candidate_feature",
            current_training_status="blocked_missing_artifact",
            source_id="pit.quarterly_financials",
            source_version="mops-financial-ratios.candidate",
            feature_as_of_policy="statement_available_date",
            available_date_policy="available_date_before_or_on_decision",
            coverage_summary={"numeric_pit_ratios_supplied": False},
            blockers=(
                "fundamental_pit_numeric_data_missing",
                "statement_publication_timestamp_does_not_forge_financial_ratios",
            ),
            is_numeric_model_feature=True,
        )
    )

    # 6. DEV-69 TWSE Microstructure 5 個 Source
    microstructure_sources = (
        ("microstructure.suspended_halt_resume", "TWSE 停牌/復牌生效狀態", "event_and_effective_dates"),
        ("microstructure.disposition_stock", "TWSE 處置股公告與期間", "disposition_period_dates"),
        ("microstructure.periodic_call_auction", "TWSE 處置分盤撮合措施", "disposition_derived_measures"),
        ("microstructure.full_delivery", "TWSE 全額交割與變更交易當日快照", "session_snapshot_date"),
        ("microstructure.limit_lock", "TWSE 漲跌停鎖死行情觀測", "session_observation_date"),
    )
    for src_id, name, time_policy in microstructure_sources:
        has_micro = src_id in validated_candidate_sources or "twse_microstructure" in validated_candidate_sources
        fields.append(
            DataInventoryField(
                field_id=src_id,
                display_name=name,
                family="microstructure",
                dtype="flag",
                unit="flag",
                role="candidate_feature",
                current_training_status="candidate_research_only"
                if has_micro
                else "blocked_pit_contract",
                source_id=src_id,
                source_version="twse-microstructure-v1",
                artifact_citation="validated_twse_microstructure_artifact" if has_micro else "twse_microstructure_evidence_report_not_supplied",
                feature_as_of_policy=time_policy,
                available_date_policy="decision_time_observation_date",
                coverage_summary={"twse_microstructure_audit_harden_v1": True},
                blockers=(
                    "market_session_or_date_only_observation",
                    "requires_human_acceptance_in_p0_register",
                ),
                is_numeric_model_feature=False,
            )
        )

    captured_time = now or datetime.now(timezone.utc)
    inventory_id = f"inventory-{captured_time.strftime('%Y%m%dT%H%M%SZ')}-{sha256(json.dumps([f.field_id for f in fields]).encode()).hexdigest()[:8]}"

    # Summaries
    family_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for f in fields:
        family_counts[f.family] = family_counts.get(f.family, 0) + 1
        role_counts[f.role] = role_counts.get(f.role, 0) + 1
        status_counts[f.current_training_status] = status_counts.get(f.current_training_status, 0) + 1

    summary = {
        "total_fields": len(fields),
        "numeric_model_features": sum(1 for f in fields if f.is_numeric_model_feature and f.role == "feature"),
        "included_in_current_fit_count": status_counts.get("included_in_current_fit", 0),
        "family_counts": family_counts,
        "role_counts": role_counts,
        "status_counts": status_counts,
        "formal_eligible_count": 0,
        "production_eligible_count": 0,
        "promotion_eligible_count": 0,
    }

    manifest_hash = _file_sha256(manifest_file)
    dataset_hash = _file_sha256(dataset_file)

    # Internal Lineage (Full details for report)
    report_lineage = {
        "manifest_path": str(manifest_file),
        "manifest_file_sha256": manifest_hash,
        "dataset_path": str(dataset_file),
        "dataset_file_sha256": dataset_hash,
        "generation_id": str(manifest.get("generation_id")),
        "dataset_id": str(manifest.get("dataset_id")),
        "candidate_artifact_hashes": candidate_hashes,
        "generated_at": captured_time.isoformat(),
    }

    # (Defect 5) Sanitized Lineage strictly containing NO raw local file paths!
    sanitized_lineage = {
        "manifest_file_basename": manifest_file.name,
        "manifest_file_sha256": manifest_hash,
        "dataset_file_basename": dataset_file.name,
        "dataset_file_sha256": dataset_hash,
        "generation_id": str(manifest.get("generation_id")),
        "dataset_id": str(manifest.get("dataset_id")),
        "candidate_artifact_hashes": candidate_hashes,
        "generated_at": captured_time.isoformat(),
    }

    sanitized_fields = [
        {
            "field_id": f.field_id,
            "display_name": f.display_name,
            "family": f.family,
            "role": f.role,
            "training_status": f.current_training_status,
            "is_numeric_model_feature": f.is_numeric_model_feature,
            "blockers": list(f.blockers),
        }
        for f in fields
    ]

    sanitized_projection = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "inventory_id": inventory_id,
        "dataset_id": str(manifest.get("dataset_id")),
        "generation_id": str(manifest.get("generation_id")),
        "summary": summary,
        "sanitized_fields": sanitized_fields,
        "identity": {
            "dataset_id": str(manifest.get("dataset_id")),
            "generation_id": str(manifest.get("generation_id")),
            "research_run_id": inventory_id,
        },
        "status": {
            "scope": "historical_research_seen_development_data",
            "formal_oos": False,
            "alpha_bp": 0,
            "promotion_eligible": False,
            "apply_flags": {
                "apply_to_scoring": False,
                "apply_to_recommendation": False,
                "apply_to_portfolio": False,
                "apply_to_exit": False,
            },
        },
        "lineage": sanitized_lineage,
        "frozen_metrics": {
            "total_fields": len(fields),
            "numeric_model_features": summary["numeric_model_features"],
            "fit_sample_count": fit_count,
        },
        "blockers": ["development_only_data_inventory"],
        "sources": [
            {
                "source_id": "pit.quarterly_financials",
                "label": "MOPS 季報發布 (F26-F29 官方秒級時間軸)",
                "lane": "p0",
                "status": "candidate",
                "allowed_use": "research_pit_statement_availability, development_shadow_projection",
                "observed_rows": 0,
                "revision": "inventory-v1",
                "owner": "archi",
                "degraded_reason": "availability_gate_only",
            }
        ],
    }

    report = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "inventory_id": inventory_id,
        "generated_at": captured_time.isoformat(),
        "summary": summary,
        "fields": [asdict(f) for f in fields],
        "lineage": report_lineage,
        "safety_flags": {
            "formal_oos_allowed": False,
            "formal_evidence_credit_authorized": False,
            "production_allowed": False,
            "production_blend_alpha_bp": 0,
            "training_allowed": True,
            "promotion_allowed": False,
            "scheduler_allowed": False,
            "broker_allowed": False,
            "unblind_allowed": False,
        },
    }

    reports_dir = safe_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"{inventory_id}.json"
    report_bytes = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    report_sha256 = "sha256:" + sha256(report_bytes).hexdigest()

    # (Defect 6) 獨占寫入不可變報告 (Exclusive Write)
    _exclusive_write_bytes(report_file, report_bytes)

    # (Defect 6) 原子覆寫最新 Projection (Atomic Replace with Temp File Cleanup)
    latest_proj_file = safe_root / "latest_data_inventory_projection.json"
    proj_bytes = (json.dumps(sanitized_projection, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    proj_sha256 = "sha256:" + sha256(proj_bytes).hexdigest()
    _atomic_write_bytes(latest_proj_file, proj_bytes)

    return DevelopmentDataInventoryResult(
        inventory_id=inventory_id,
        generated_at=captured_time.isoformat(),
        fields=tuple(fields),
        summary=summary,
        lineage=report_lineage,
        projection=sanitized_projection,
        report=report,
        report_file_path=report_file,
        report_file_sha256=report_sha256,
        sanitized_projection_path=latest_proj_file,
        sanitized_projection_sha256=proj_sha256,
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON artifact must be an object")
    return data


def _file_sha256(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _exclusive_write_bytes(path: Path, data: bytes) -> None:
    """(Defect 6) Exclusive creation with fsync; errors if file already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY  # Windows compatibility
    try:
        fd = os.open(path, flags)
    except FileExistsError:
        raise ValueError(f"immutable report file already exists: {path}") from None
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """(Defect 6) Atomic write using temporary file and fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_path_str = tempfile.mkstemp(dir=path.parent, prefix=f".tmp_{path.name}_")
    temp_path = Path(temp_path_str)
    try:
        os.write(temp_fd, data)
        os.fsync(temp_fd)
        os.close(temp_fd)
        os.replace(temp_path, path)
    except Exception:
        os.close(temp_fd) if 'temp_fd' in locals() else None
        if temp_path.exists():
            temp_path.unlink()
        raise


def _verify_no_symlink_escape(root: Path) -> None:
    resolved = root.resolve()
    for parent in (resolved, *resolved.parents):
        if parent.is_symlink():
            raise ValueError(f"symlink path detected: {parent}")
