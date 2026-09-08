"""產生 13 項 P0 官方來源證據與就緒度 (Readiness) 稽核報告與 Owner 群組化決策包。

本 CLI 工具具備下列特性：
1. 預設模式僅讀取已知 fixture / 既有 artifact，不打網路。
2. Live 探測模式必須明確傳入 --live 且配合 --confirm-live-readonly 旗標。
3. 輸出路徑嚴格限制於 approved TEMP / candidate-safe 目錄，絕對不寫入正式 DB 或 repo。
4. 13 項 P0 來源收斂為最多 5 個群組化 Owner 決策問題，集中討論內部研究意圖/條款接受度。
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from data_module.p0_source_acquisition_routes import (
    P0AcquisitionRouteRegistry,
    build_p0_acquisition_route_registry,
)
from data_module.p0_official_source_parsers import (
    OfficialParserResult,
    RawFetchEnvelope,
    parse_monthly_revenue_open_data,
)
from data_module.source_acceptance_decision_registry import (
    MACHINE_DECISION_POLICY_VERSION,
)
from data_module.source_acceptance_governance import (
    MACHINE_EVIDENCE_SCHEMA_VERSION,
    SourceAcceptanceGovernance,
    calculate_machine_evidence_hash,
)
from scripts.capture_p0_license_evidence import (
    MACHINE_LICENSE_SCOPE_POLICIES,
    build_machine_license_artifact,
)
from scripts.run_p0_candidate_audit import (
    LIVE_PROBE_SOURCE_MAP,
    _probe_report_sha256,
    _validate_fubon_projection,
    _validate_mops_quarterly_artifact,
    _validate_probe_report,
    _validated_probe_counts,
)
from scripts.update_phase3c_candidates import run_bounded_official_probe


GROUPED_OWNER_PACKET_KEYS = (
    "twse_market_corporate",
    "twse_microstructure",
    "twse_flows_credit",
    "tdcc_distribution",
    "mops_monthly_quarterly",
)

GROUPED_OWNER_PACKET_DEFINITIONS: dict[str, dict[str, Any]] = {
    "twse_market_corporate": {
        "group_id": "twse_market_corporate",
        "title": "TWSE 除權息與減資/分割/面額變更事件時間軸",
        "covered_source_ids": [
            "corporate_action.ex_dividend_timeline",
            "corporate_action.reduction_split_par_value",
        ],
        "provider": "TWSE 臺灣證券交易所 (TWT49U / TWTAUU)",
        "owner_question": "是否核准將來自 TWSE (TWT49U/TWTAUU) 的除權息與減資／分割／面額變更資料作為內部量化研究與歷史回測備選源？（條款限制：僅供內部研究使用，不可對外再散布）",
    },
    "twse_microstructure": {
        "group_id": "twse_microstructure",
        "title": "TWSE 交易限制與成交可行性 Preflight",
        "covered_source_ids": [
            "microstructure.suspended_halt_resume",
            "microstructure.disposition_stock",
            "microstructure.periodic_call_auction",
            "microstructure.full_delivery",
            "microstructure.limit_lock",
        ],
        "provider": "TWSE 臺灣證券交易所 (TWTAWU / 處置公告 / TWT85U / TWT84U)",
        "owner_question": "是否核准將來自 TWSE (TWTAWU/處置公告/TWT85U/TWT84U) 的停復牌、處置、分盤撮合、全額交割與漲跌停鎖死觀測作為交易限制與成交可行性 preflight 備選源？（條款限制：僅供內部研究使用，不可對外再散布）",
    },
    "twse_flows_credit": {
        "group_id": "twse_flows_credit",
        "title": "TWSE 三大法人買賣超與信用交易",
        "covered_source_ids": [
            "institutional_flows",
            "credit_transactions",
        ],
        "provider": "TWSE 臺灣證券交易所 (T86 / MI_MARGN)",
        "owner_question": "是否核准將來自 TWSE (T86/MI_MARGN) 的三大法人買賣超與信用交易（融資融券）餘額資料作為內部量化研究與歷史回測備選源？（條款限制：僅供內部研究使用，不可對外再散布）",
    },
    "tdcc_distribution": {
        "group_id": "tdcc_distribution",
        "title": "TDCC 集保持股分散級距",
        "covered_source_ids": [
            "tdcc_shareholding",
        ],
        "provider": "TDCC 臺灣集中保管結算所 (OpenData 1-5)",
        "owner_question": "是否核准將來自 TDCC 1-5 開放資料的集保持股分散級距資料作為內部量化研究與歷史回測備選源？（條款限制：僅供內部研究使用，不可對外再散布）",
    },
    "mops_monthly_quarterly": {
        "group_id": "mops_monthly_quarterly",
        "title": "TWSE/TPEx 月營收公告與 MOPS 季度財報 Artifact",
        "covered_source_ids": [
            "twse.monthly_revenue_announcement",
            "tpex.monthly_revenue_announcement",
            "pit.quarterly_financials",
        ],
        "provider": "TWSE / TPEx OpenAPI (營收) & MOPS 公開資訊觀測站 (季報 Artifact)",
        "owner_question": "是否核准將來自 TWSE/TPEx OpenData 月營收公告與 MOPS 官方採集之合併未更正季報歷史 Artifact 作為 PIT 營收與財報比對備選源？（條款限制：僅供內部研究使用，不可對外再散布）",
    },
}

SOURCE_PROVIDER_INFO: dict[str, tuple[str, str, str]] = {
    "corporate_action.ex_dividend_timeline": ("TWSE", "exchangeReport:TWT49U", "bounded_live_probe"),
    "corporate_action.reduction_split_par_value": ("TWSE", "exchangeReport:TWTAUU", "bounded_live_probe"),
    "microstructure.suspended_halt_resume": ("TWSE", "exchangeReport:TWTAWU", "bounded_live_probe"),
    "microstructure.disposition_stock": ("TWSE", "announcement:punish", "bounded_live_probe"),
    "microstructure.periodic_call_auction": ("TWSE", "announcement:punish", "bounded_live_probe"),
    "microstructure.full_delivery": ("TWSE", "exchangeReport:TWT85U", "bounded_live_probe"),
    "microstructure.limit_lock": ("TWSE", "exchangeReport:TWT84U", "bounded_live_probe"),
    "institutional_flows": ("TWSE", "fund:T86", "bounded_live_probe"),
    "credit_transactions": ("TWSE", "exchangeReport:MI_MARGN", "bounded_live_probe"),
    "tdcc_shareholding": ("TDCC", "opendata:1-5", "bounded_live_probe"),
    "twse.monthly_revenue_announcement": ("TWSE", "opendata:t187ap05_L", "bounded_live_probe"),
    "tpex.monthly_revenue_announcement": ("TPEx", "openapi:mopsfin_t187ap05_O", "bounded_live_probe"),
    "pit.quarterly_financials": ("MOPS", "statement:publication_artifact", "existing_artifact"),
}

# 本輪只把一條已有 parser 的官方 source 接成 machine producer。其餘來源
# 仍由既有 P0 matrix 投影為 candidate／degraded，避免把未完成的三 formal
# inputs 或其他 route 誤標成已接線。
MACHINE_SOURCE_PRODUCER_CONFIG: dict[str, dict[str, Any]] = {
    "twse.monthly_revenue_announcement": {
        "source_version": "twse-t187ap05_L.v1",
        "endpoint_id": "twse:opendata:t187ap05_L",
        "acquisition_route_id": "twse.openapi.t187ap05_L",
        "source_url": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
        "universe_source_id": "twse.listed_company_registry",
        "universe_url": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        "license_url": "https://www.twse.com.tw/zh/terms/use.html",
    }
}
MACHINE_SOURCE_MAX_BYTES = 8 * 1024 * 1024
MACHINE_SOURCE_TIMEOUT_SECONDS = 30.0
MACHINE_ARTIFACT_DIRNAME = "artifacts"
MACHINE_INPUT_DIRNAME = "inputs"

REDACT_KEYS = {"api_key", "cookie", "credential", "password", "authorization", "secret", "token"}

MICROSTRUCTURE_SOURCE_IDS = (
    "microstructure.suspended_halt_resume",
    "microstructure.disposition_stock",
    "microstructure.periodic_call_auction",
    "microstructure.full_delivery",
    "microstructure.limit_lock",
)

MICROSTRUCTURE_TIMESTAMP_POLICIES: dict[str, dict[str, str]] = {
    "microstructure.suspended_halt_resume": {
        "primary_evidence_class": "first_observed_only",
        "primary_field": "first_observed_at",
        "pit_blocker": "official_publication_timestamp_missing",
        "research_use": "停牌／復牌有效狀態與事件順序的 research preflight",
    },
    "microstructure.disposition_stock": {
        "primary_evidence_class": "official_publication_date_only",
        "primary_field": "official_publication_date",
        "pit_blocker": "official_publication_timestamp_missing",
        "research_use": "處置公告日期、有效期間與措施內容的 research preflight",
    },
    "microstructure.periodic_call_auction": {
        "primary_evidence_class": "official_publication_date_only",
        "primary_field": "official_publication_date",
        "pit_blocker": "official_publication_timestamp_missing",
        "research_use": "由處置公告相符措施衍生的分盤撮合 research preflight",
    },
    "microstructure.full_delivery": {
        "primary_evidence_class": "market_session_observation",
        "primary_field": "market_session_date",
        "pit_blocker": "official_publication_timestamp_missing",
        "research_use": "全額交割／交易方法當日狀態的 research preflight",
    },
    "microstructure.limit_lock": {
        "primary_evidence_class": "market_session_observation",
        "primary_field": "market_session_date",
        "pit_blocker": "decision_time_availability_not_proven",
        "research_use": "漲跌停鎖死的交易日行情觀測與成交可行性 research preflight",
    },
}

TIMESTAMP_FIELDS = (
    "official_publication_timestamp",
    "official_publication_date",
    "effective_from",
    "effective_to",
    "market_session_date",
    "decision_time_observed_at",
    "first_observed_at",
    "captured_at",
    "http_date",
    "http_last_modified",
)


def _timestamp_field_projection(
    probe: Mapping[str, Any],
    *,
    field_name: str,
    evidence_class: str,
    pit_gate_allowed: bool,
    missing_reason: str,
) -> dict[str, Any]:
    source_field = field_name
    value = probe.get(field_name)
    if field_name == "http_last_modified" and value is None:
        source_field = "last_modified"
        value = probe.get(source_field)
    return {
        "raw_evidence_location": f"probe.{source_field}",
        "normalized_value": value,
        "timezone": "Asia/Taipei" if field_name not in {"http_date", "http_last_modified"} else "HTTP-header-defined",
        "evidence_class": evidence_class if value is not None else "missing",
        "quality": "verified" if value is not None else "missing",
        "pit_gate_allowed": pit_gate_allowed and value is not None,
        "reason_code": None if value is not None else missing_reason,
    }


def _build_microstructure_timestamp_semantics(
    source_id: str,
    probe: Mapping[str, Any],
    *,
    decision_date: date,
) -> dict[str, Any]:
    policy = MICROSTRUCTURE_TIMESTAMP_POLICIES[source_id]
    primary_class = policy["primary_evidence_class"]
    primary_field = policy["primary_field"]
    semantics: dict[str, dict[str, Any]] = {}

    for field_name in TIMESTAMP_FIELDS:
        if field_name in {"http_date", "http_last_modified"}:
            evidence_class = "capture_time_only"
            pit_gate_allowed = False
            missing_reason = "http_header_not_supplied"
        elif field_name == "official_publication_timestamp":
            evidence_class = "official_row_timestamp"
            pit_gate_allowed = True
            missing_reason = "official_publication_timestamp_not_proven"
        elif field_name == "official_publication_date":
            evidence_class = "official_publication_date_only"
            pit_gate_allowed = False
            missing_reason = "official_publication_date_not_exposed_by_probe"
        elif field_name in {"effective_from", "effective_to"}:
            evidence_class = "effective_date_only"
            pit_gate_allowed = False
            missing_reason = "effective_period_not_exposed_by_probe"
        elif field_name == "market_session_date":
            evidence_class = "market_session_observation"
            pit_gate_allowed = False
            missing_reason = "market_session_date_not_exposed_by_probe"
        elif field_name == "decision_time_observed_at":
            evidence_class = "market_session_observation"
            pit_gate_allowed = True
            missing_reason = "decision_time_observation_not_exposed_by_probe"
        elif field_name == "captured_at":
            evidence_class = "capture_time_only"
            pit_gate_allowed = False
            missing_reason = "capture_time_not_exposed_by_probe"
        elif field_name == "first_observed_at":
            evidence_class = "first_observed_only"
            pit_gate_allowed = False
            missing_reason = "first_observed_time_not_exposed_by_probe"
        else:
            evidence_class = "missing"
            pit_gate_allowed = False
            missing_reason = f"{field_name}_not_proven"
        semantics[field_name] = _timestamp_field_projection(
            probe,
            field_name=field_name,
            evidence_class=evidence_class,
            pit_gate_allowed=pit_gate_allowed,
            missing_reason=missing_reason,
        )

    if primary_field == "market_session_date" and semantics[primary_field]["normalized_value"] is None:
        semantics[primary_field] = {
            "raw_evidence_location": "probe.probe_date",
            "normalized_value": decision_date.isoformat(),
            "timezone": "Asia/Taipei",
            "evidence_class": "market_session_observation",
            "quality": "date_only",
            "pit_gate_allowed": False,
            "reason_code": "decision_time_within_session_not_proven",
        }

    return {
        "source_id": source_id,
        "primary_evidence_class": primary_class,
        "primary_field": primary_field,
        "fields": semantics,
        "http_headers_never_promoted_to_publication": True,
        "capture_time_never_promoted_to_publication": True,
        "first_observed_never_backfilled_as_publication": True,
    }


def _microstructure_owner_recommendation(
    item: Mapping[str, Any],
    *,
    fubon_shadow_usable: bool,
) -> dict[str, Any]:
    source_id = str(item["source_id"])
    policy = MICROSTRUCTURE_TIMESTAMP_POLICIES[source_id]
    machine_blockers = [str(item["remaining_blocker"])]
    return {
        "source_id": source_id,
        "proposed_decision": "deferred",
        "machine_recommendation": "deferred",
        "ready_for_owner_review": False,
        "timestamp_evidence_class": item["timestamp_kind"],
        "pit_gate_allowed": False,
        "permitted_research_use": policy["research_use"],
        "prohibited_use": [
            "formal_evidence_credit",
            "production_ingestion",
            "formal_score_or_advice",
            "broker_execution",
        ],
        "machine_blockers": machine_blockers,
        "human_blockers": ["legal_license_review", "owner_written_acceptance"],
        "fubon_shadow_usable": fubon_shadow_usable,
        "fubon_formal_credit_allowed": False,
        "production_blend_alpha_bp": 0,
        "rollback_path": "disable_or_supersede_future_owner_decision; preserve append-only evidence",
    }


def validate_approved_output_path(target_path: Path) -> bool:
    """確認輸出路徑是否位於 OS TEMP 內。

    本工具目前沒有受治理的 candidate-safe 輸出根目錄；因此不能僅憑
    路徑中含有 ``candidate``、``temp`` 或 ``handoff`` 等字串就放行。這可
    避免誤將報告寫回 repository 或任何正式資料根目錄。
    """
    resolved = target_path.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()

    # Allow inside OS temp directory
    try:
        resolved.relative_to(temp_root)
        return True
    except ValueError:
        pass

    return False


def redact_secrets(data: Any) -> Any:
    """遞迴過濾敏感資訊（API keys, credentials, cookies）。"""
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if str(k).lower() in REDACT_KEYS:
                result[k] = "[REDACTED]"
            else:
                result[k] = redact_secrets(v)
        return result
    if isinstance(data, list):
        return [redact_secrets(item) for item in data]
    return data


def build_machine_evidence_bundle(
    decision_date: date,
    *,
    source_id: str,
    license_capture_path: Path,
    output_path: Path,
    audit_payload: Mapping[str, Any] | None = None,
    opener: Callable[..., Any] | None = None,
    timeout_seconds: float = MACHINE_SOURCE_TIMEOUT_SECONDS,
    max_bytes: int = MACHINE_SOURCE_MAX_BYTES,
) -> dict[str, Any]:
    """由官方唯讀 response 產生一條 machine evidence producer 鏈。

    這個入口只支援本輪已具備 parser、官方資料端點與獨立上市 universe
    的月營收 source。它會把 response bytes、獨立 universe bytes、license
    capture、四個 artifact 與最外層 envelope 全部保存於呼叫端指定的 TEMP
    目錄；不讀寫正式資料根目錄。``audit_payload`` 僅作為同次 P0 audit 的
    provenance 參考，品質與 coverage 仍重新解析本次 response，不接受 caller
    自填的 accepted／coverage 布林值。

    ``available_at`` 固定使用本次實際 fetch 的 aware timestamp，並在 artifact
    中明示這是 first-observed shadow evidence；不得解讀為歷史 PIT 或官方
    發布時間。machine evaluator 只會因此建立 limited research-shadow /
    diagnostics 決議。
    """

    config = MACHINE_SOURCE_PRODUCER_CONFIG.get(source_id)
    if config is None:
        raise ValueError(
            f"machine producer is not implemented for source: {source_id}"
        )
    if not validate_approved_output_path(output_path):
        raise ValueError("machine evidence output must be inside the operating-system TEMP directory")
    if not validate_approved_output_path(license_capture_path):
        raise ValueError("license capture must be inside the operating-system TEMP directory")
    if timeout_seconds <= 0 or timeout_seconds > 60:
        raise ValueError("machine source timeout_seconds must be in (0, 60]")
    if max_bytes <= 0 or max_bytes > 32 * 1024 * 1024:
        raise ValueError("machine source max_bytes must be in (0, 32MiB]")

    output_dir = output_path.resolve().parent
    output_dir.mkdir(parents=True, exist_ok=True)
    input_dir = output_dir / MACHINE_INPUT_DIRNAME
    artifact_dir = output_dir / MACHINE_ARTIFACT_DIRNAME
    input_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    license_capture_bytes = license_capture_path.read_bytes()
    copied_license_path = input_dir / "license_capture.json"
    copied_license_path.write_bytes(license_capture_bytes)
    license_capture_payload = json.loads(license_capture_bytes.decode("utf-8"))
    if not isinstance(license_capture_payload, Mapping):
        raise ValueError("license capture JSON must be an object")

    selected_opener = opener or urlopen
    license_policy = MACHINE_LICENSE_SCOPE_POLICIES.get(str(config["license_url"]))
    if not isinstance(license_policy, Mapping):
        raise ValueError(
            "machine source license policy is not registered for this endpoint"
        )
    policy_source_scopes = license_policy.get("source_scopes")
    policy_source_scope = (
        policy_source_scopes.get(source_id)
        if isinstance(policy_source_scopes, Mapping)
        else None
    )
    if not isinstance(policy_source_scope, Mapping):
        raise ValueError(
            "machine source endpoint is outside the registered license scope"
        )
    government_dataset = policy_source_scope.get("government_dataset")
    if not isinstance(government_dataset, Mapping):
        raise ValueError(
            "machine source requires a government platform dataset mapping"
        )

    government_metadata_capture = _fetch_machine_source(
        str(government_dataset["metadata_url"]),
        opener=selected_opener,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
    )
    government_metadata_path = input_dir / "data_gov_dataset_18420.json"
    government_metadata_bytes = government_metadata_capture["payload"]
    government_metadata_path.write_bytes(government_metadata_bytes)
    government_api_doc_capture = _fetch_machine_source(
        str(government_dataset["api_documentation_url"]),
        opener=selected_opener,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
    )
    government_api_doc_path = input_dir / "twse_openapi_swagger.json"
    government_api_doc_path.write_bytes(government_api_doc_capture["payload"])
    government_api_doc_evidence = _validate_government_openapi_mapping(
        government_api_doc_capture,
        government_api_doc_path,
        expected=government_dataset,
        output_dir=output_dir,
    )
    government_dataset_binding = _validate_government_dataset_metadata(
        government_metadata_capture,
        government_metadata_path,
        expected=government_dataset,
        output_dir=output_dir,
        api_documentation_evidence=government_api_doc_evidence,
    )

    source_capture = _fetch_machine_source(
        str(config["source_url"]),
        opener=selected_opener,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
    )
    universe_capture = _fetch_machine_source(
        str(config["universe_url"]),
        opener=selected_opener,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
    )
    source_bytes = source_capture["payload"]
    universe_bytes = universe_capture["payload"]
    source_hash = _sha256_prefixed(source_bytes)
    universe_hash = _sha256_prefixed(universe_bytes)
    source_input_path = input_dir / "official_source_payload.bin"
    universe_input_path = input_dir / "official_listed_universe_payload.json"
    source_input_path.write_bytes(source_bytes)
    universe_input_path.write_bytes(universe_bytes)

    source_fetched_at = source_capture["fetched_at"]
    source_envelope = RawFetchEnvelope(
        source_id=source_id,
        source_version=str(config["source_version"]),
        endpoint_id=str(config["endpoint_id"]),
        request_parameters={},
        fetched_at=source_fetched_at,
        http_status=int(source_capture["http_status"]),
        http_headers=source_capture["headers"],
        payload=source_bytes,
    )
    parser_result = parse_monthly_revenue_open_data(source_envelope)
    universe_codes, universe_as_of_date = _parse_independent_listed_universe(
        universe_bytes
    )
    accepted_symbols = {
        observation.symbol.strip()
        for observation in parser_result.accepted
        if observation.symbol.strip()
    }
    covered_symbols = accepted_symbols.intersection(universe_codes)
    report_dates = {
        observation.observation_date
        for observation in parser_result.accepted
    }
    if not parser_result.accepted or len(report_dates) != 1:
        raise ValueError(
            "official monthly revenue response must contain accepted rows for exactly one report date"
        )
    if len(accepted_symbols) != len(parser_result.accepted):
        raise ValueError(
            "official monthly revenue response contains duplicate stock symbols; producer refuses to infer coverage"
        )
    if not covered_symbols:
        raise ValueError(
            "official monthly revenue response has no symbols in independent listed universe"
        )

    raw_count = parser_result.raw_row_count
    accepted_count = parser_result.accepted_row_count
    quarantine_count = parser_result.quarantine_row_count
    blocked_count = parser_result.blocked_row_count
    if raw_count <= 0 or accepted_count <= 0:
        raise ValueError("official source parser returned no usable rows")
    if accepted_count + quarantine_count + blocked_count != raw_count:
        raise ValueError("official source parser row conservation failed")
    if len(covered_symbols) * 10000 < len(universe_codes) * 8000:
        raise ValueError(
            "official source coverage is below the machine minimum of 8000bp"
        )
    coverage_bp = (len(covered_symbols) * 10000) // len(universe_codes)
    quality_score_bp = ((accepted_count - quarantine_count) * 10000) // raw_count
    quality_score_bp = max(0, min(10000, quality_score_bp))
    if quality_score_bp < 9500:
        raise ValueError(
            "official source quality is below the machine minimum of 9500bp"
        )

    source_observation_date = next(iter(report_dates))
    missing_symbols = sorted(universe_codes - covered_symbols)
    unexpected_symbols = sorted(accepted_symbols - universe_codes)

    # 統一以 producer 對原始 bytes 的 hash 作為 quality／PIT／availability
    # 的 subject content hash；artifact 檔案本身另由 envelope hash 綁定。
    source_binding = {
        "path": _relative_candidate_path(source_input_path, output_dir),
        "content_sha256": source_hash,
        "bytes": len(source_bytes),
        "kind": "official_source_payload",
        "source_url": str(config["source_url"]),
        "endpoint_id": str(config["endpoint_id"]),
        "acquisition_route_id": str(config["acquisition_route_id"]),
        "fetched_at_utc": source_fetched_at.isoformat(),
        "http_status": int(source_capture["http_status"]),
    }
    universe_binding = {
        "path": _relative_candidate_path(universe_input_path, output_dir),
        "content_sha256": universe_hash,
        "bytes": len(universe_bytes),
        "kind": "independent_official_universe_payload",
        "source_id": str(config["universe_source_id"]),
        "source_url": str(config["universe_url"]),
        "fetched_at_utc": universe_capture["fetched_at"].isoformat(),
        "http_status": int(universe_capture["http_status"]),
    }

    license_artifact_path = artifact_dir / "license.json"
    license_envelope = build_machine_license_artifact(
        license_capture_payload,
        source_id=source_id,
        output_path=license_artifact_path,
        capture_path=copied_license_path,
        capture_root=output_dir,
        government_dataset_evidence=government_dataset_binding,
    )
    license_envelope["artifact_path"] = _relative_candidate_path(
        license_artifact_path, output_dir
    )

    shadow_available_at = source_fetched_at.isoformat()
    shadow_available_date = source_fetched_at.date().isoformat()
    source_payload_digest = source_hash
    quality_id = f"quality:{source_id}:{source_payload_digest.removeprefix('sha256:')[:16]}"
    pit_id = f"pit:{source_id}:{source_payload_digest.removeprefix('sha256:')[:16]}"
    availability_id = (
        f"availability:{source_id}:{source_payload_digest.removeprefix('sha256:')[:16]}"
    )
    expected_universe = {
        "source_id": source_id,
        "evidence_id": (
            f"universe:{source_id}:"
            f"{universe_hash.removeprefix('sha256:')[:16]}"
        ),
        "content_sha256": universe_hash,
        "count": len(universe_codes),
        "as_of_date": universe_as_of_date,
        "basis": "independent_official_twse_listed_registry_unique_symbols",
        "input_artifact": universe_binding,
    }
    coverage = {
        "numerator": len(covered_symbols),
        "denominator": len(universe_codes),
        "expected_universe_count": len(universe_codes),
        "coverage_bp": coverage_bp,
        "basis": "official_twse_listed_registry_unique_symbol_intersection",
        "covered_symbol_sha256": _hash_symbol_set(covered_symbols),
        "missing_symbols": missing_symbols,
        "missing_count": len(missing_symbols),
        "missing_symbol_sha256": _hash_symbol_set(missing_symbols),
        "unexpected_symbols": unexpected_symbols,
        "unexpected_count": len(unexpected_symbols),
        "unexpected_symbol_sha256": _hash_symbol_set(unexpected_symbols),
        "source_observation_date": source_observation_date,
        "expected_universe_as_of_date": universe_as_of_date,
        "temporal_alignment": (
            "source_report_date_precedes_expected_universe_snapshot"
            if source_observation_date < universe_as_of_date
            else "source_report_date_matches_expected_universe_snapshot"
            if source_observation_date == universe_as_of_date
            else "source_report_date_follows_expected_universe_snapshot"
        ),
    }
    row_conservation = {
        "raw": raw_count,
        "accepted": accepted_count,
        "quarantine": quarantine_count,
        "blocked": blocked_count,
    }
    quarantine = {
        "status": "verified",
        "policy": "official parser quarantines malformed rows without dropping them",
        "quarantined_rows": quarantine_count,
        "blocked_rows": blocked_count,
        "reason_codes": sorted(
            record.reason_code for record in parser_result.quarantine
        ),
    }
    maturity = {
        "status": "mature",
        "completed_periods": 1,
        "minimum_periods": 1,
        "lineage_complete": True,
        "policy": "bounded_live_shadow_snapshot_only",
        "source_observation_date": source_observation_date,
        "formal_oos_allowed": False,
    }
    quality_artifact = {
        "schema_version": "source-acceptance-quality-evidence.v1",
        "producer": "run_p0_source_evidence_audit.py",
        "producer_code_sha256": _producer_code_sha256(),
        "source_id": source_id,
        "source_version": str(config["source_version"]),
        "evidence_id": quality_id,
        "status": "verified",
        "quality_score_bp": quality_score_bp,
        "content_sha256": source_payload_digest,
        "auto_verifiable": [
            "schema_validation_passed",
            "row_conservation_verified",
            "isolation_guaranteed",
            "payload_hash_verified",
            "maturity_window_verified",
            "official_source_payload_reparsed",
            "independent_universe_verified",
        ],
        "checks": {
            "schema_valid": True,
            "reconciled": True,
            "quarantine_complete": True,
            "source_payload_reparsed": True,
            "independent_universe_reconciled": True,
        },
        "expected_universe": expected_universe,
        "coverage": coverage,
        "row_conservation": row_conservation,
        "quarantine": quarantine,
        "maturity": maturity,
        "input_artifact": source_binding,
        "government_dataset_evidence": government_dataset_binding,
        "audit_provenance": {
            "audit_schema_version": "p0-source-evidence-audit.v1",
            "audit_payload_sha256": _canonical_mapping_hash(audit_payload)
            if audit_payload is not None
            else None,
            "selected_route_id": str(config["acquisition_route_id"]),
        },
    }
    quality_artifact_path = artifact_dir / "quality.json"
    quality_envelope = _write_machine_artifact(
        quality_artifact_path, quality_artifact, output_dir
    )

    lineage_hashes = [source_hash, universe_hash]
    pit_artifact = {
        "schema_version": "source-acceptance-pit-evidence.v1",
        "producer": "run_p0_source_evidence_audit.py",
        "producer_code_sha256": _producer_code_sha256(),
        "source_id": source_id,
        "source_version": str(config["source_version"]),
        "evidence_id": pit_id,
        "status": "verified",
        "lineage_complete": True,
        "content_sha256": source_payload_digest,
        "auto_verifiable": ["payload_hash_verified", "source_payload_reparsed"],
        "lineage_artifact_hashes": lineage_hashes,
        "input_artifact": source_binding,
        "observations": [
            {
                "source_id": source_id,
                "source_version": str(config["source_version"]),
                "available_date": shadow_available_date,
                "available_at": shadow_available_at,
                "status": "shadow_ready",
                "source_observation_date": source_observation_date,
                "availability_basis": "first_observed_at",
                "official_publication_timestamp_proven": False,
                "accepted_row_count": accepted_count,
                "accepted_symbol_sha256": _hash_symbol_set(accepted_symbols),
            }
        ],
    }
    pit_artifact_path = artifact_dir / "pit.json"
    pit_envelope = _write_machine_artifact(pit_artifact_path, pit_artifact, output_dir)

    availability_artifact = {
        "schema_version": "source-acceptance-availability-evidence.v1",
        "producer": "run_p0_source_evidence_audit.py",
        "producer_code_sha256": _producer_code_sha256(),
        "source_id": source_id,
        "evidence_id": availability_id,
        "status": "available",
        "content_sha256": source_payload_digest,
        "available_date": shadow_available_date,
        "available_at": shadow_available_at,
        "observed_at": shadow_available_at,
        "availability_basis": "first_observed_at",
        "official_publication_timestamp_proven": False,
        "input_artifact": source_binding,
    }
    availability_artifact_path = artifact_dir / "availability.json"
    availability_envelope = _write_machine_artifact(
        availability_artifact_path, availability_artifact, output_dir
    )

    decision_timestamp = datetime.now(timezone.utc)
    if decision_timestamp.date() != decision_date:
        raise ValueError(
            "machine evidence decision_date must equal the producer's current UTC date"
        )
    machine_payload: dict[str, Any] = {
        "schema_version": MACHINE_EVIDENCE_SCHEMA_VERSION,
        "policy_version": MACHINE_DECISION_POLICY_VERSION,
        "source_id": source_id,
        "decision_date": decision_date.isoformat(),
        "decision_timestamp": decision_timestamp.isoformat(),
        "decision_revision_id": (
            f"machine:{source_id}:"
            f"{source_payload_digest.removeprefix('sha256:')[:16]}"
        ),
        "parent_revision_id": None,
        "source_version": str(config["source_version"]),
        "license": license_envelope,
        "quality": quality_envelope,
        "pit": pit_envelope,
        "coverage": coverage,
        "row_conservation": row_conservation,
        "quarantine": quarantine,
        "availability": availability_envelope,
        "maturity": maturity,
        "allowed_use_cases": ["research_shadow", "diagnostics"],
        "rollback_reference": f"decision:disable:{source_id}:machine",
    }
    machine_payload["content_sha256"] = calculate_machine_evidence_hash(
        machine_payload
    )
    output_path.write_text(
        json.dumps(machine_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        machine_payload, evidence_root=output_dir
    )
    if review.decision is None:
        raise ValueError(
            "machine evidence producer output did not pass evaluator: "
            + ", ".join(review.blockers)
        )
    return machine_payload


def _fetch_machine_source(
    url: str,
    *,
    opener: Callable[..., Any],
    timeout_seconds: float,
    max_bytes: int,
) -> dict[str, Any]:
    """取得一個 bounded 官方 response，並保留真實抓取時間與 transport metadata。"""

    request = Request(
        url,
        headers={
            "User-Agent": "technical-analysis-p0-machine-producer/1.0",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        },
    )
    fetched_at = datetime.now(timezone.utc)
    with opener(request, timeout=timeout_seconds) as response:
        status_value = getattr(response, "status", None)
        if status_value is None:
            getcode = getattr(response, "getcode", None)
            status_value = getcode() if callable(getcode) else None
        if isinstance(status_value, bool) or not isinstance(status_value, int):
            raise ValueError(f"official response status is invalid: {url}")
        if status_value < 200 or status_value >= 300:
            raise ValueError(f"official response status is not successful: {url} ({status_value})")
        raw = response.read(max_bytes + 1)
        if not isinstance(raw, bytes):
            raw = bytes(raw)
        if len(raw) > max_bytes:
            raise ValueError(f"official response exceeded bounded size: {url}")
        headers = getattr(response, "headers", None)
        header_map: dict[str, object] = {}
        if isinstance(headers, Mapping):
            header_map = {
                name: value
                for name, value in headers.items()
                if str(name).lower() in {"date", "last-modified", "etag", "content-type"}
            }
        else:
            getter = getattr(headers, "get", None)
            if callable(getter):
                for name in ("Date", "Last-Modified", "ETag", "Content-Type"):
                    value = getter(name)
                    if value is not None:
                        header_map[name] = str(value)
        final_url = str(getattr(response, "geturl", lambda: url)() or url)
        if urlparse(final_url).netloc.lower() != urlparse(url).netloc.lower():
            raise ValueError(f"official response redirected outside its source host: {url}")
    return {
        "payload": raw,
        "fetched_at": fetched_at,
        "http_status": status_value,
        "headers": header_map,
        "requested_url": url,
        "final_url": final_url,
    }


def _validate_government_dataset_metadata(
    capture: Mapping[str, Any],
    path: Path,
    *,
    expected: Mapping[str, Any],
    output_dir: Path,
    api_documentation_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """核對 data.gov.tw dataset metadata 與已登錄的官方 source scope。"""

    payload = capture.get("payload")
    if not isinstance(payload, bytes):
        raise ValueError("government dataset metadata payload is not bytes")
    declared_hash = _sha256_prefixed(payload)
    if declared_hash != expected.get("metadata_content_sha256"):
        raise ValueError("government dataset metadata content hash changed")
    expected_bytes = expected.get("metadata_content_bytes")
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or len(payload) != expected_bytes
    ):
        raise ValueError("government dataset metadata size changed")
    if capture.get("http_status") not in range(200, 300):
        raise ValueError("government dataset metadata response is not successful")
    if capture.get("final_url") != expected.get("metadata_url"):
        raise ValueError("government dataset metadata redirected to an unexpected URL")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("government dataset metadata JSON is invalid") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError("government dataset metadata must be an object")
    result = decoded.get("result")
    if not isinstance(result, Mapping):
        raise ValueError("government dataset metadata result is missing")
    for field_name in (
        "datasetId",
        "identifier",
        "title",
        "dataProvider",
        "publisherOID",
        "license",
        "modifiedDate",
    ):
        expected_name = {
            "datasetId": "dataset_id",
            "identifier": "identifier",
            "title": "title",
            "dataProvider": "data_provider_id",
            "publisherOID": "publisher_oid",
            "license": "license_code",
            "modifiedDate": "metadata_modified",
        }[field_name]
        if result.get(field_name) != expected.get(expected_name):
            raise ValueError(
                f"government dataset metadata field changed: {field_name}"
            )
    distribution = result.get("distribution")
    if isinstance(distribution, (str, bytes)) or not isinstance(
        distribution, Sequence
    ):
        raise ValueError("government dataset distribution is missing")
    resource_urls = {
        str(item.get("resourceDownloadUrl"))
        for item in distribution
        if isinstance(item, Mapping) and item.get("resourceDownloadUrl")
    }
    if expected.get("resource_url") not in resource_urls:
        raise ValueError("government dataset resource URL is not the registered one")
    notes = str(result.get("notes") or "")
    if str(expected.get("api_documentation_url")) not in notes:
        raise ValueError("government dataset OpenAPI documentation mapping is missing")
    fetched_at_value = capture.get("fetched_at")
    if not isinstance(fetched_at_value, datetime):
        raise ValueError("government dataset metadata capture time is missing")
    binding = {
        "path": _relative_candidate_path(path, output_dir),
        "content_sha256": declared_hash,
        "bytes": len(payload),
        "kind": "official_data_gov_dataset_metadata",
        "metadata_url": expected.get("metadata_url"),
        "dataset_url": expected.get("dataset_url"),
        "dataset_id": result.get("datasetId"),
        "identifier": result.get("identifier"),
        "title": result.get("title"),
        "data_provider_id": result.get("dataProvider"),
        "publisher_oid": result.get("publisherOID"),
        "license_code": result.get("license"),
        "license_version": expected.get("license_version"),
        "license_url": expected.get("license_url"),
        "endpoint_url": expected.get("endpoint_url"),
        "resource_url": expected.get("resource_url"),
        "api_documentation_url": expected.get("api_documentation_url"),
        "api_documentation_evidence": dict(api_documentation_evidence),
        "metadata_modified": result.get("modifiedDate"),
        "http_status": capture.get("http_status"),
        "final_url": capture.get("final_url"),
        "fetched_at_utc": fetched_at_value.isoformat(),
    }
    return binding


def _validate_government_openapi_mapping(
    capture: Mapping[str, Any],
    path: Path,
    *,
    expected: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """確認官方 Swagger 確實列出本次採集的 OpenAPI resource path。"""

    payload = capture.get("payload")
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("government OpenAPI metadata payload is empty")
    if capture.get("http_status") not in range(200, 300):
        raise ValueError("government OpenAPI metadata response is not successful")
    if capture.get("final_url") != expected.get("api_documentation_url"):
        raise ValueError("government OpenAPI metadata redirected unexpectedly")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("government OpenAPI metadata JSON is invalid") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError("government OpenAPI metadata must be an object")
    endpoint_url = str(expected.get("endpoint_url") or "")
    endpoint_path = urlparse(endpoint_url).path
    paths = decoded.get("paths")
    base_path = str(decoded.get("basePath") or "").rstrip("/")
    candidate_paths = [endpoint_path]
    if base_path and endpoint_path.startswith(base_path + "/"):
        candidate_paths.append(endpoint_path[len(base_path) :])
    swagger_path = next(
        (candidate for candidate in candidate_paths if isinstance(paths, Mapping) and candidate in paths),
        None,
    )
    if swagger_path is None:
        raise ValueError("government OpenAPI metadata does not map the source endpoint")
    fetched_at_value = capture.get("fetched_at")
    if not isinstance(fetched_at_value, datetime):
        raise ValueError("government OpenAPI metadata capture time is missing")
    return {
        "path": _relative_candidate_path(path, output_dir),
        "content_sha256": _sha256_prefixed(payload),
        "bytes": len(payload),
        "kind": "official_twse_openapi_swagger",
        "metadata_url": expected.get("api_documentation_url"),
        "endpoint_url": endpoint_url,
        "endpoint_path": endpoint_path,
        "swagger_path": swagger_path,
        "http_status": capture.get("http_status"),
        "final_url": capture.get("final_url"),
        "fetched_at_utc": fetched_at_value.isoformat(),
    }


def _parse_independent_listed_universe(payload: bytes) -> tuple[set[str], str]:
    try:
        decoded = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("independent listed universe JSON is invalid") from exc
    if not isinstance(decoded, list):
        raise ValueError("independent listed universe must be a JSON array")
    codes: set[str] = set()
    as_of_dates: set[str] = set()
    for row in decoded:
        if not isinstance(row, Mapping):
            raise ValueError("independent listed universe row must be an object")
        code = str(row.get("公司代號") or row.get("SecuritiesCompanyCode") or "").strip()
        # TWSE 上市清冊同時包含四碼普通股與六碼存託憑證代號；
        # 兩者都屬於獨立的官方市場成分，不能為了四碼假設而漏掉六碼成分。
        if not code or not code.isdigit() or len(code) not in {4, 6}:
            raise ValueError("independent listed universe contains invalid stock code")
        codes.add(code)
        raw_date = str(row.get("出表日期") or row.get("Date") or "").strip()
        if len(raw_date) == 7 and raw_date.isdigit():
            as_of_dates.add(
                f"{int(raw_date[:3]) + 1911:04d}-{raw_date[3:5]}-{raw_date[5:7]}"
            )
        elif len(raw_date) == 8 and raw_date.isdigit():
            as_of_dates.add(f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}")
    if not codes:
        raise ValueError("independent listed universe is empty")
    if len(as_of_dates) != 1:
        raise ValueError("independent listed universe must have one as-of date")
    return codes, next(iter(as_of_dates))


def _write_machine_artifact(
    path: Path,
    payload: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    if not validate_approved_output_path(path):
        raise ValueError("machine artifact must be inside the operating-system TEMP directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json_bytes(payload))
    return {
        "evidence_id": payload.get("evidence_id"),
        "artifact_path": _relative_candidate_path(path, output_dir),
        "content_sha256": _sha256_prefixed(path.read_bytes()),
    }


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _canonical_mapping_hash(payload: Mapping[str, Any] | None) -> str | None:
    if payload is None:
        return None
    return _sha256_prefixed(_canonical_json_bytes(payload))


def _sha256_prefixed(value: bytes) -> str:
    return f"sha256:{sha256(value).hexdigest()}"


def _relative_candidate_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("candidate artifact path escaped its output root") from exc


def _producer_code_sha256() -> str:
    return _sha256_prefixed(Path(__file__).resolve().read_bytes())


def _hash_symbol_set(symbols: Sequence[str] | set[str]) -> str:
    canonical = "\n".join(sorted(str(symbol).strip() for symbol in symbols))
    return _sha256_prefixed(canonical.encode("utf-8"))


def _route_probe_status(
    *,
    network_status: Any = None,
    probe_outcome: Any = None,
    schema_status: Any = None,
) -> str:
    """將單一路徑的 probe 結果正規化成有限狀態集合。"""

    network = str(network_status or "").strip().lower()
    outcome = str(probe_outcome or "").strip().lower()
    schema = str(schema_status or "").strip().lower()
    if network == "failed" or outcome in {"network_error", "transport_error"}:
        return "failed"
    if outcome == "official_no_data" or schema == "no_data":
        return "official_no_data"
    if outcome in {"observed", "matched"} or schema == "matched":
        return "observed"
    if outcome in {"date_mismatch", "no_accepted_rows", "schema_mismatch"}:
        return outcome
    return "not_usable"


def _fallback_route_probe_status(item: Mapping[str, Any]) -> str:
    """從 fallback 欄位投影狀態；未嘗試時不猜測結果。"""

    if not item.get("fallback_attempted") and not item.get("fallback_used"):
        return "not_attempted"
    if item.get("fallback_used") is True:
        return "observed"
    return _route_probe_status(
        network_status=(
            "failed"
            if str(item.get("fallback_probe_outcome") or "").strip().lower()
            in {"network_error", "transport_error"}
            else "reachable"
        ),
        probe_outcome=item.get("fallback_probe_outcome"),
        schema_status=(
            "no_data"
            if item.get("fallback_probe_outcome") == "official_no_data"
            else "matched"
            if item.get("fallback_probe_outcome") == "matched"
            else None
        ),
    )


def _build_route_probe_summary(
    matrix: Sequence[Mapping[str, Any]],
    registry: P0AcquisitionRouteRegistry,
) -> dict[str, Any]:
    """標示每條候選 route 是否真的被本次 audit 嘗試。

    ``acquisition_routes`` 是設計／候選目錄；它本身不代表網路請求已發出。
    本投影只消費 audit 已保存的 primary／fallback lineage，其他 route 明確
    標成 ``not_attempted``，避免把路由註冊誤讀成資料可用性證據。
    """

    by_source: dict[str, list[dict[str, Any]]] = {}
    routes: list[dict[str, Any]] = []
    for item in matrix:
        source_id = str(item.get("source_id") or "")
        selected_route_id = str(item.get("acquisition_route_id") or "").strip()
        fallback_route_id = str(
            item.get("fallback_acquisition_route_id")
            or item.get("fallback_from_acquisition_route_id")
            or ""
        ).strip()
        source_rows: list[dict[str, Any]] = []
        for route in registry.for_source(source_id):
            route_id = route.route_id
            if route_id == selected_route_id and selected_route_id:
                if item.get("availability") == "artifact_verified":
                    status = "observed"
                    attempt_kind = "selected_artifact"
                elif "probe_outcome" not in item and "network_status" not in item:
                    status = "not_attempted"
                    attempt_kind = "not_attempted"
                else:
                    status = _route_probe_status(
                        network_status=item.get("network_status"),
                        probe_outcome=item.get("probe_outcome"),
                        schema_status=item.get("schema_status"),
                    )
                    attempt_kind = "selected"
            elif route_id == fallback_route_id and fallback_route_id:
                status = _fallback_route_probe_status(item)
                attempt_kind = "fallback"
            else:
                status = "not_attempted"
                attempt_kind = "not_attempted"
            row = {
                "source_id": source_id,
                "route_id": route_id,
                "provider": route.provider,
                "endpoint": route.endpoint,
                "implementation_status": route.implementation_status,
                "attempt_kind": attempt_kind,
                "status": status,
                "selected": route_id == selected_route_id and bool(selected_route_id),
                "fallback": route_id == fallback_route_id and bool(fallback_route_id),
            }
            source_rows.append(row)
            routes.append(row)
        by_source[source_id] = source_rows

    status_counts = {
        status: sum(1 for row in routes if row["status"] == status)
        for status in (
            "observed",
            "failed",
            "official_no_data",
            "date_mismatch",
            "no_accepted_rows",
            "schema_mismatch",
            "not_usable",
            "not_attempted",
        )
    }
    return {
        "route_count": len(routes),
        "attempted_route_count": len(routes) - status_counts["not_attempted"],
        "status_counts": status_counts,
        "by_source": by_source,
        "routes": routes,
        "candidate_evidence_only": True,
        "source_acceptance_granted": False,
        "formal_eligible": False,
        "production_ingestion_allowed": False,
    }


def build_p0_source_evidence_audit(
    decision_date: date,
    *,
    probe_report: Mapping[str, Any] | None = None,
    fubon_projection: Mapping[str, Any] | None = None,
    mops_quarterly_artifact: Mapping[str, Any] | Sequence[Any] | None = None,
    live_mode: bool = False,
    confirm_live_readonly: bool = False,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """產出 13 項 P0 官方來源證據矩陣與 5 個 Owner 群組化決策包。"""
    if live_mode and not confirm_live_readonly:
        raise ValueError("live 探測模式必須明確指定 --confirm-live-readonly 旗標")

    if output_path is not None:
        if not validate_approved_output_path(output_path):
            raise ValueError(
                f"輸出路徑 {output_path} 不位於 approved TEMP / candidate-safe 目錄，拒絕執行"
            )

    if probe_report is not None:
        report = dict(probe_report)
        live_executed = False
    elif live_mode:
        report = dict(run_bounded_official_probe(decision_date))
        live_executed = True
    else:
        # Default offline mode: mock unprobed or fixture report
        report = {
            "probe_date": decision_date.isoformat(),
            "probe_mode": "bounded_official_read_only",
            "license_accepted": False,
            "source_accepted": False,
            "downstream_eligibility": "none",
            "production_scheduler_allowed": False,
            "human_decision": "requires_human_acceptance",
            "sources": [],
        }
        live_executed = False

    probe_items = _validate_probe_report(report, decision_date)
    acquisition_routes = build_p0_acquisition_route_registry()
    fubon_items = _validate_fubon_projection(fubon_projection) if fubon_projection is not None else {}
    mops_rows = _validate_mops_quarterly_artifact(mops_quarterly_artifact) if mops_quarterly_artifact is not None else []

    matrix: list[dict[str, Any]] = []

    for source_id in P0_SOURCE_IDS:
        provider, endpoint_type, acquisition_mode = SOURCE_PROVIDER_INFO[source_id]

        if source_id == "pit.quarterly_financials":
            if mops_rows:
                item = {
                    "source_id": source_id,
                    "family": "pit",
                    "provider": provider,
                    "endpoint_or_artifact_type": endpoint_type,
                    "acquisition_mode": acquisition_mode,
                    "machine_status": "verified",
                    "pit_status": "pit_date_verified",
                    "timestamp_kind": "official_document_upload_timestamp",
                    "availability": "artifact_verified",
                    "schema_status": "matched",
                    "payload_sha256": mops_rows[0]["source_hash"],
                    # Keep the validated artifact's denominator visible to the
                    # downstream candidate-intake builder.  The MOPS branch is
                    # intentionally separate from live probe rows, so without
                    # these explicit counts an already-validated artifact would
                    # be projected as an unexplained 0/0 machine observation.
                    "raw_row_count": len(mops_rows),
                    "accepted_row_count": len(mops_rows),
                    "quarantine_row_count": 0,
                    "blocked_row_count": 0,
                    "remaining_blocker": "legal_and_license_acceptance_required",
                    "auto_verifiable": [
                        "schema_validation_passed",
                        "row_conservation_verified",
                        "isolation_guaranteed",
                        "payload_hash_verified",
                        "mops_artifact_provenance_verified",
                    ],
                    "non_auto_verifiable": [
                        "legal_license_review",
                        "owner_written_acceptance",
                    ],
                }
            else:
                item = {
                    "source_id": source_id,
                    "family": "pit",
                    "provider": provider,
                    "endpoint_or_artifact_type": endpoint_type,
                    "acquisition_mode": acquisition_mode,
                    "machine_status": "missing",
                    "pit_status": "unavailable",
                    "timestamp_kind": "unavailable",
                    "availability": "artifact_missing",
                    "schema_status": "unavailable",
                    "payload_sha256": None,
                    "remaining_blocker": "mops_candidate_artifact_not_supplied",
                    "auto_verifiable": ["adapter_contract_implemented"],
                    "non_auto_verifiable": ["mops_candidate_artifact_supply"],
                }
            item["acquisition_routes"] = [
                route.to_dict()
                for route in acquisition_routes.for_source(source_id)
            ]
            matrix.append(item)
            continue

        probe_source_id = LIVE_PROBE_SOURCE_MAP.get(source_id)
        probe = probe_items.get(probe_source_id) if probe_source_id else None

        if probe is None:
            availability = "probe_failed" if (live_executed or report["sources"]) else "not_probed"
            item = {
                "source_id": source_id,
                "family": source_id.split(".")[0],
                "provider": provider,
                "endpoint_or_artifact_type": endpoint_type,
                "acquisition_mode": acquisition_mode,
                "machine_status": "missing",
                "pit_status": "unavailable",
                "timestamp_kind": "unavailable",
                "availability": availability,
                "schema_status": "unavailable",
                "payload_sha256": None,
                "remaining_blocker": "official_probe_not_returned",
                "auto_verifiable": ["adapter_contract_implemented"],
                "non_auto_verifiable": ["network_probe_execution", "legal_license_review"],
            }
            item["acquisition_routes"] = [
                route.to_dict()
                for route in acquisition_routes.for_source(source_id)
            ]
            matrix.append(item)
            continue

        counts = _validated_probe_counts(probe)
        raw_timestamp_evidence = str(probe.get("timestamp_evidence", "unavailable"))
        schema_status = str(probe.get("schema_status", "mismatch"))
        network_status = str(probe.get("network_status", "reachable"))
        probe_outcome = str(probe.get("probe_outcome", "unknown"))

        if network_status == "failed":
            availability = "probe_failed"
        elif probe_outcome == "official_no_data" or schema_status == "no_data":
            availability = "official_no_data"
        else:
            availability = "network_probed"

        if network_status == "failed":
            machine_status = "missing"
            pit_status = "unavailable"
            timestamp_kind = "unavailable"
            remaining_blocker = "network_probe_failed"
        elif probe_outcome == "official_no_data" or schema_status == "no_data":
            machine_status = "missing"
            pit_status = "unavailable"
            timestamp_kind = "unavailable"
            remaining_blocker = "official_no_data_for_requested_date"
        elif schema_status == "matched" and raw_timestamp_evidence == "official_publication_timestamp":
            machine_status = "verified"
            pit_status = "pit_date_verified"
            timestamp_kind = "official_publication_timestamp"
            remaining_blocker = "legal_and_license_acceptance_required"
        elif schema_status == "matched":
            machine_status = "degraded"
            pit_status = "official_publication_timestamp_missing"
            timestamp_kind = "first_observed_only"
            remaining_blocker = "official_publication_timestamp_missing"
        else:
            machine_status = "missing"
            pit_status = "unavailable"
            timestamp_kind = "unavailable"
            remaining_blocker = "schema_mismatch_or_probe_failed"

        if schema_status == "matched" and network_status != "failed":
            auto_verifiable = [
                "schema_validation_passed",
                "row_conservation_verified",
                "isolation_guaranteed",
                "payload_hash_verified",
            ]
            non_auto_verifiable = [
                "legal_license_review",
                "owner_written_acceptance",
            ]
        else:
            auto_verifiable = ["adapter_contract_implemented"]
            if network_status != "failed" and probe.get("payload_sha256"):
                auto_verifiable.append("payload_hash_verified")
            non_auto_verifiable = [
                "completed_publication_probe_or_schema_repair",
                "legal_license_review",
                "owner_written_acceptance",
            ]

        item = {
            "source_id": source_id,
            "family": source_id.split(".")[0],
            "provider": provider,
            "endpoint_or_artifact_type": endpoint_type,
            "acquisition_mode": acquisition_mode,
            "machine_status": machine_status,
            "pit_status": pit_status,
            "timestamp_kind": timestamp_kind,
            "availability": availability,
            "schema_status": schema_status,
            "probe_outcome": probe_outcome,
            "payload_sha256": probe.get("payload_sha256"),
            "raw_row_count": counts["raw_row_count"],
            "accepted_row_count": counts["accepted_row_count"],
            "quarantine_row_count": counts["quarantine_row_count"],
            "blocked_row_count": counts["blocked_row_count"],
            "remaining_blocker": remaining_blocker,
            "auto_verifiable": auto_verifiable,
            "non_auto_verifiable": non_auto_verifiable,
        }
        if (
            source_id in MICROSTRUCTURE_SOURCE_IDS
            and schema_status == "matched"
            and network_status != "failed"
        ):
            policy = MICROSTRUCTURE_TIMESTAMP_POLICIES[source_id]
            timestamp_semantics = _build_microstructure_timestamp_semantics(
                source_id,
                probe,
                decision_date=decision_date,
            )
            primary_field = policy["primary_field"]
            primary_projection = timestamp_semantics["fields"][primary_field]
            official_timestamp = timestamp_semantics["fields"][
                "official_publication_timestamp"
            ]
            if (
                raw_timestamp_evidence == "official_publication_timestamp"
                and official_timestamp["normalized_value"] is not None
            ):
                timestamp_kind = "official_row_timestamp"
                pit_status = "pit_timestamp_verified"
                remaining_blocker = "legal_and_license_acceptance_required"
                item["machine_status"] = "verified"
            elif primary_projection["normalized_value"] is not None:
                timestamp_kind = str(primary_projection["evidence_class"])
                pit_status = (
                    "market_session_observation_only"
                    if timestamp_kind == "market_session_observation"
                    else "official_publication_date_only"
                )
                remaining_blocker = policy["pit_blocker"]
            else:
                timestamp_kind = "first_observed_only"
                pit_status = "official_publication_timestamp_missing"
                remaining_blocker = policy["pit_blocker"]
            item["timestamp_kind"] = timestamp_kind
            item["pit_status"] = pit_status
            item["remaining_blocker"] = remaining_blocker
            item["timestamp_semantics"] = timestamp_semantics
        if "request_parameters" in probe:
            item["request_parameters"] = probe["request_parameters"]
        for route_field in (
            "endpoint_id",
            "acquisition_route_id",
            # These are bounded transport observations only.  The timestamp
            # semantics builder deliberately marks them capture-time evidence
            # and never promotes them to official publication time.
            "http_date",
            "last_modified",
            "etag",
            "content_type",
            "fallback_used",
            "fallback_from_endpoint_id",
            "fallback_from_acquisition_route_id",
            "fallback_attempted",
            "fallback_endpoint_id",
            "fallback_acquisition_route_id",
            "fallback_probe_outcome",
            "fallback_official_status",
            "fallback_http_status",
            "fallback_payload_sha256",
            "fallback_payload_size_bytes",
            "fallback_observation_dates",
            "fallback_requested_date",
            "fallback_quarantine_reasons",
            "fallback_error_type",
            "fallback_error",
            "primary_official_status",
        ):
            if route_field in probe:
                item[route_field] = probe[route_field]
        item["acquisition_routes"] = [
            route.to_dict() for route in acquisition_routes.for_source(source_id)
        ]
        matrix.append(item)

    # Aggregate matrix into 5 grouped owner decision questions
    for item in matrix:
        if not str(item.get("acquisition_route_id") or "").strip():
            source_routes = acquisition_routes.for_source(
                str(item.get("source_id") or "")
            )
            if source_routes:
                # The registry order is the governed primary→alternate order.
                # A default route id is metadata only; the summary below still
                # marks it not_attempted when no probe result was supplied.
                item["acquisition_route_id"] = source_routes[0].route_id
    route_probe_summary = _build_route_probe_summary(matrix, acquisition_routes)
    for item in matrix:
        item["route_probe_statuses"] = route_probe_summary["by_source"].get(
            item["source_id"], []
        )
    grouped_packet: list[dict[str, Any]] = []
    matrix_by_id = {item["source_id"]: item for item in matrix}

    for group_key in GROUPED_OWNER_PACKET_KEYS:
        defn = GROUPED_OWNER_PACKET_DEFINITIONS[group_key]
        covered_ids = defn["covered_source_ids"]
        sub_items = [matrix_by_id[sid] for sid in covered_ids if sid in matrix_by_id]

        verified_count = sum(1 for item in sub_items if item["machine_status"] == "verified")
        degraded_count = sum(1 for item in sub_items if item["machine_status"] == "degraded")
        missing_count = sum(1 for item in sub_items if item["machine_status"] == "missing")

        grouped_packet.append(
            {
                "group_id": defn["group_id"],
                "title": defn["title"],
                "covered_source_ids": covered_ids,
                "provider": defn["provider"],
                "owner_question": defn["owner_question"],
                "group_status_summary": {
                    "total_sources": len(covered_ids),
                    "verified_sources": verified_count,
                    "degraded_sources": degraded_count,
                    "missing_sources": missing_count,
                },
                "decision_scope": "internal_research_only_intent_and_terms_acceptability",
                **(
                    {
                        "source_recommendations": [
                            _microstructure_owner_recommendation(
                                matrix_by_id[source_id],
                                fubon_shadow_usable=bool(fubon_items.get(source_id)),
                            )
                            for source_id in covered_ids
                        ],
                        "fubon_shadow_usable": any(
                            bool(fubon_items.get(source_id)) for source_id in covered_ids
                        ),
                        "fubon_formal_credit_allowed": False,
                        "production_blend_alpha_bp": 0,
                    }
                    if group_key == "twse_microstructure"
                    else {}
                ),
            }
        )

    verified_sources = sum(1 for item in matrix if item["machine_status"] == "verified")
    degraded_sources = sum(1 for item in matrix if item["machine_status"] == "degraded")
    missing_sources = sum(1 for item in matrix if item["machine_status"] == "missing")

    payload = {
        "schema_version": "p0-source-evidence-audit.v1",
        "task_id": "GEMINI-P0-13-OFFICIAL-EVIDENCE-AND-READINESS-HARDENING-V1",
        "decision_date": decision_date.isoformat(),
        "mode": "bounded_official_read_only",
        "live_probe_executed": live_executed,
        "machine_evidence_matrix": matrix,
        "grouped_owner_decision_packet": grouped_packet,
        "acquisition_route_summary": acquisition_routes.to_dict(),
        "acquisition_route_probe_summary": route_probe_summary,
        "machine_vs_owner_blocker_summary": {
            "total_sources": len(matrix),
            "machine_verified_sources": verified_sources,
            "degraded_sources": degraded_sources,
            "missing_sources": missing_sources,
            "grouped_owner_decision_count": len(grouped_packet),
        },
        "formal_clock_zeros": {
            "snapshot_count": 0,
            "observed_days": 0,
            "outcome_denominator": 0,
            "formal_credit": 0,
        },
        "safety_flags": {
            "formal_oos_allowed": False,
            "formal_evidence_credit_authorized": False,
            "production_allowed": False,
            "production_blend_alpha_bp": 0,
            "training_allowed": False,
            "promotion_allowed": False,
            "scheduler_allowed": False,
            "unblind_allowed": False,
            "formal_rule_only_path_unchanged": True,
            "downstream_eligibility": "none",
            "human_decision": "requires_human_acceptance",
        },
    }

    sanitized_payload = redact_secrets(payload)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(sanitized_payload, ensure_ascii=False, indent=2) + "\n"
        output_path.write_text(rendered, encoding="utf-8")

    return sanitized_payload


def export_p0_13_handoff_json(
    audit_payload: dict[str, Any],
    *,
    git_status_str: str = "unverified",
    test_results: dict[str, Any] | None = None,
) -> Path:
    """匯出真實 handoff JSON 至指定 %TEMP% 目錄。"""
    temp_dir = Path(tempfile.gettempdir())
    handoff_dir = temp_dir / "technical_analysis_gemini_handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    target_path = handoff_dir / "GEMINI-P0-13-OFFICIAL-EVIDENCE-AND-READINESS-HARDENING-V1.json"

    changed_files = [
        "data_module/p0_source_contract_registry.py",
        "data_module/p0_official_source_parsers.py",
        "scripts/run_p0_source_evidence_audit.py",
        "scripts/run_p0_candidate_audit.py",
        "scripts/update_phase3c_candidates.py",
        "tests/test_run_p0_source_evidence_audit.py",
        "tests/test_run_p0_candidate_audit.py",
        "tests/test_p0_official_source_parsers.py",
        "qa/full_app_healthcheck/test_inventory.py",
        "docs/06_qa/V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md",
        "docs/07_guides/APPLICATION_MANUAL.md",
    ]
    changed_file_entries: list[dict[str, str]] = []
    for rel_path in changed_files:
        abs_p = PROJECT_ROOT / rel_path
        if abs_p.exists():
            changed_file_entries.append(
                {"path": rel_path, "sha256": sha256(abs_p.read_bytes()).hexdigest()}
            )

    handoff = {
        "task_id": "GEMINI-P0-13-OFFICIAL-EVIDENCE-AND-READINESS-HARDENING-V1",
        # This CLI can validate a supplied evidence payload, but cannot know the
        # terminal result of pytest/mypy or the final Git state.  A reviewer must
        # add those facts to a separate handoff after independent verification.
        "status": "audit_generated_not_validation_handoff",
        "base_head": "6f245223f5c6c599a9e3341687cca10b0512ebe8",
        "timestamp": audit_payload.get("decision_date"),
        "live_probe_executed": audit_payload.get("live_probe_executed", False),
        "changed_files": changed_file_entries,
        "machine_evidence_matrix": audit_payload.get("machine_evidence_matrix", []),
        "grouped_owner_decision_packet": audit_payload.get("grouped_owner_decision_packet", []),
        "machine_vs_owner_blocker_summary": audit_payload.get("machine_vs_owner_blocker_summary", {}),
        "test_suite_results": test_results or {
            "status": "not_run_by_cli",
            "reason": "terminal validation must be recorded by the independent reviewer",
        },
        "formal_clock_zeros": {
            "snapshot_count": 0,
            "observed_days": 0,
            "outcome_denominator": 0,
            "formal_credit": 0,
            "production_blend_alpha_bp": 0,
        },
        "safety_flags": audit_payload.get("safety_flags", {}),
        "git_status": {
            "working_tree_clean_for_commit": False,
            "no_git_commit_performed": True,
            "details": git_status_str,
        },
        "blockers_and_known_limitations": [
            "13 P0 sources remain research_only with downstream_eligibility=none",
            "formal source acceptance by owner remains pending",
            "production scheduler and DB writes remain prohibited",
        ],
        "recommended_commit_batches": [
            {
                "batch_id": "batch-1-evidence-contracts-and-parsers",
                "title": "Harden P0 source contracts, publication timestamp semantics, and test inventory",
                "files": [
                    "data_module/p0_source_contract_registry.py",
                    "data_module/p0_official_source_parsers.py",
                    "qa/full_app_healthcheck/test_inventory.py",
                    "tests/test_run_p0_source_evidence_audit.py",
                ],
            },
            {
                "batch_id": "batch-2-audit-cli-and-grouped-packet",
                "title": "Add read-only P0-13 source evidence audit CLI and 5-group owner decision packet",
                "files": [
                    "scripts/run_p0_source_evidence_audit.py",
                    "scripts/run_p0_candidate_audit.py",
                    "scripts/update_phase3c_candidates.py",
                    "tests/test_run_p0_candidate_audit.py",
                ],
            },
            {
                "batch_id": "batch-3-acceptance-register-and-manual",
                "title": "Update V2.3 P0 acceptance register and application manual for P0-13 audit workflow",
                "files": [
                    "docs/06_qa/V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md",
                    "docs/07_guides/APPLICATION_MANUAL.md",
                ],
            },
        ],
    }

    sanitized_handoff = redact_secrets(handoff)
    rendered = json.dumps(sanitized_handoff, ensure_ascii=False, indent=2) + "\n"
    target_path.write_text(rendered, encoding="utf-8")
    return target_path


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-date", type=date.fromisoformat, required=True, help="決策日期 (YYYY-MM-DD)")
    parser.add_argument("--output", type=Path, help="指定輸出的 JSON 檔案路徑 (必須位於 TEMP 或 candidate Safe 目錄)")
    parser.add_argument("--live", action="store_true", help="啟用 live 探測模式 (必須同時傳入 --confirm-live-readonly)")
    parser.add_argument("--confirm-live-readonly", action="store_true", help="確認執行唯讀 bounded live 探測")
    parser.add_argument("--mops-quarterly-artifact", type=Path, help="唯讀載入已保存的 MOPS 季報 artifact JSON")
    parser.add_argument("--fubon-projection", type=Path, help="唯讀載入富邦 research projection JSON")
    parser.add_argument(
        "--license-capture",
        type=Path,
        help="machine producer 使用的 bounded license capture JSON（必須位於 TEMP）",
    )
    parser.add_argument(
        "--machine-evidence-output",
        type=Path,
        help="產出 source-acceptance-machine-evidence.v1（必須位於 TEMP；需搭配 --live）",
    )
    parser.add_argument(
        "--machine-source-id",
        choices=tuple(MACHINE_SOURCE_PRODUCER_CONFIG),
        default="twse.monthly_revenue_announcement",
        help="machine producer 本輪唯一支援的官方 source",
    )
    args = parser.parse_args(argv)

    fubon_projection = (
        json.loads(args.fubon_projection.read_text(encoding="utf-8"))
        if args.fubon_projection is not None
        else None
    )
    mops_quarterly_artifact = (
        json.loads(args.mops_quarterly_artifact.read_text(encoding="utf-8"))
        if args.mops_quarterly_artifact is not None
        else None
    )

    payload = build_p0_source_evidence_audit(
        args.decision_date,
        fubon_projection=fubon_projection,
        mops_quarterly_artifact=mops_quarterly_artifact,
        live_mode=args.live,
        confirm_live_readonly=args.confirm_live_readonly,
        output_path=args.output,
    )

    if args.machine_evidence_output is not None or args.license_capture is not None:
        if args.machine_evidence_output is None or args.license_capture is None:
            raise ValueError(
                "--machine-evidence-output and --license-capture must be provided together"
            )
        if not args.live:
            raise ValueError("machine producer requires --live for an official bounded fetch")
        machine_payload = build_machine_evidence_bundle(
            args.decision_date,
            source_id=args.machine_source_id,
            license_capture_path=args.license_capture,
            output_path=args.machine_evidence_output,
            audit_payload=payload,
        )
        # 只在 stdout 顯示 machine producer 的 hash／scope 摘要；完整 artifact
        # 留在 TEMP，避免把官方 raw bytes 或大筆 row lineage 展開到 console。
        payload["machine_producer"] = {
            "status": "machine_verified",
            "source_id": machine_payload["source_id"],
            "path": str(args.machine_evidence_output.resolve()),
            "content_sha256": machine_payload["content_sha256"],
            "allowed_use_cases": machine_payload["allowed_use_cases"],
            "formal_oos_allowed": False,
            "production_scheduler_allowed": False,
        }
        if args.output is not None:
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    export_p0_13_handoff_json(payload)

    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        print(rendered, end="")
    except UnicodeEncodeError:
        sys.stdout.buffer.write(rendered.encode("utf-8"))
    return 0


def _configure_utf8_stdio() -> None:
    """讓直接執行 audit CLI 的 Windows 主控台能顯示繁中說明。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            # 測試 capture stream 或外部 host 管理的 stream 可能禁止重設；
            # 這不應改變 audit 的資料取得與輸出契約。
            continue


if __name__ == "__main__":
    raise SystemExit(main())
