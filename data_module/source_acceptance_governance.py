"""Fail-closed, non-applying governance for EV2 source dossiers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from data_module.source_acceptance_decision_registry import (
    MACHINE_ALLOWED_USE_CASES,
    MACHINE_DECISION_ACTOR,
    MACHINE_DECISION_POLICY_VERSION,
    SourceAcceptanceDecisionRevision,
    validate_source_acceptance_decision_revision,
)


BROKER_REVALIDATION_SOURCE_ID = "broker_branch.revalidation"
MACHINE_EVIDENCE_SCHEMA_VERSION = "source-acceptance-machine-evidence.v1"
MACHINE_MINIMUM_COVERAGE_BP = 8000
MACHINE_MINIMUM_QUALITY_BP = 9500
_MACHINE_EVIDENCE_KEYS = frozenset(
    {
        "schema_version",
        "source_id",
        "policy_version",
        "content_sha256",
        "decision_date",
        "decision_timestamp",
        "decision_revision_id",
        "parent_revision_id",
        "source_version",
        "license",
        "quality",
        "pit",
        "coverage",
        "row_conservation",
        "quarantine",
        "availability",
        "maturity",
        "allowed_use_cases",
        "rollback_reference",
    }
)
_MACHINE_ARTIFACT_SCHEMAS = {
    "license": frozenset(
        {"p0-license-evidence-capture.v1", "source-acceptance-license-evidence.v1"}
    ),
    "quality": frozenset(
        {"p0-source-evidence-audit.v1", "source-acceptance-quality-evidence.v1"}
    ),
    "pit": frozenset(
        {"p0-source-evidence-audit.v1", "source-acceptance-pit-evidence.v1"}
    ),
    "availability": frozenset(
        {"p0-source-evidence-audit.v1", "source-acceptance-availability-evidence.v1"}
    ),
}
_MACHINE_ARTIFACT_PRODUCERS = {
    "license": frozenset({"capture_p0_license_evidence.py"}),
    "quality": frozenset({"run_p0_source_evidence_audit.py"}),
    "pit": frozenset({"run_p0_source_evidence_audit.py"}),
    "availability": frozenset({"run_p0_source_evidence_audit.py"}),
}
_MACHINE_ARTIFACT_PRODUCER_PATHS = {
    "license": "scripts/capture_p0_license_evidence.py",
    "quality": "scripts/run_p0_source_evidence_audit.py",
    "pit": "scripts/run_p0_source_evidence_audit.py",
    "availability": "scripts/run_p0_source_evidence_audit.py",
}
_MACHINE_ALLOWED_LICENSE_URLS = frozenset(
    {
        "https://www.twse.com.tw/zh/terms/use.html",
        "https://www.tpex.org.tw/web/inc/gtsm_disclaimer.php?l=zh-tw",
        "https://openapi.tdcc.com.tw/",
    }
)
# 只有在這裡登錄過的官方條款版本與端點範圍才可形成 machine scope。
# 完整頁面雜湊、Last-Modified、大小與條款輪廓是同一個版本指紋；關鍵字
# 只可作為 capture 的診斷欄位，不能把含有否定句的頁面誤判為允許。
# 這不是法律意見，也不是人類授權或正式資料接受。
MACHINE_LICENSE_SCOPE_POLICIES: dict[str, dict[str, Any]] = {
    "https://www.twse.com.tw/zh/terms/use.html": {
        "policy_version": "twse-open-data-research-shadow.v2",
        "official_document": {
            "document_id": "twse-use-terms",
            "document_version": "last-modified-2026-06-26",
            "content_sha256": (
                "sha256:ae9fa0704103fbae0ed61173a83cf55dca36dba2f7c86936fc018c4c39fb0c2c"
            ),
            "content_bytes": 15304,
            "last_modified": "Fri, 26 Jun 2026 02:46:42 GMT",
            "content_type": "text/html",
            "clause_profile_id": (
                "twse-use-terms-consent-open-data-exception-"
                "attribution-integrity-v1"
            ),
            # 已由官方頁面版本指紋核對的條款輪廓：自動下載需同意、政府
            # 資料開放例外、引用來源並保持完整性。此清單不是關鍵字判定。
            "verified_clause_ids": (
                "automated_download_requires_consent",
                "government_open_data_exception",
                "source_attribution_and_integrity",
            ),
        },
        "source_scopes": {
            "twse.monthly_revenue_announcement": {
                "endpoint_id": "twse:opendata:t187ap05_L",
                "endpoint_url": (
                    "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
                ),
                "acquisition_route_id": "twse.openapi.t187ap05_L",
                "allowed_use_cases": ("research_shadow", "diagnostics"),
                "government_dataset": {
                    "dataset_id": 18420,
                    "dataset_url": "https://data.gov.tw/dataset/18420",
                    "metadata_url": (
                        "https://data.gov.tw/api/v2/rest/dataset/18420"
                    ),
                    "identifier": "A45020000D-000354",
                    "title": "上市公司每月營業收入彙總表",
                    "data_provider_id": "N121467221",
                    "publisher_oid": "2.16.886.101.20003.20052.20004",
                    "license_code": "1",
                    "license_version": "政府資料開放授權條款-第1版",
                    "license_url": "https://data.gov.tw/license",
                    "endpoint_url": (
                        "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
                    ),
                    "resource_url": (
                        "https://mopsfin.twse.com.tw/opendata/t187ap05_L.csv"
                    ),
                    "api_documentation_url": (
                        "https://openapi.twse.com.tw/v1/swagger.json"
                    ),
                    "metadata_content_sha256": (
                        "sha256:2be48c7bd7385fbb3522df0e3c1e479dc92a8c66b85bbf1bc115e55182b9e4c7"
                    ),
                    "metadata_content_bytes": 3054,
                    "metadata_modified": "2024-12-31 20:35:27",
                },
            }
        },
        "allowed_use_cases": ("research_shadow", "diagnostics"),
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "redistribution_allowed": False,
        "legal_acceptance_inferred": False,
    },
}

# 私有名稱保留給既有 evaluator 呼叫點；所有 producer／consumer 共用上方
# 的同一份 mapping，避免條款版本與端點範圍在兩個表中漂移。
_MACHINE_LICENSE_SCOPE_RULES = MACHINE_LICENSE_SCOPE_POLICIES
_MACHINE_LICENSE_VERIFIED_STATUSES = frozenset(
    {"approved", "machine_scope_verified"}
)
_MACHINE_REQUIRED_AUTO_EVIDENCE = frozenset(
    {
        "schema_validation_passed",
        "row_conservation_verified",
        "isolation_guaranteed",
        "payload_hash_verified",
    }
)


@dataclass(frozen=True)
class SourceAcceptanceDossier:
    """資料源接受審查封包，僅供審查準備使用，絕不授權下游實際使用。"""

    source_id: str
    source_owner_role: str
    license_owner_role: str
    license_status: str
    license_scope: str
    redistribution_policy: str
    source_status: str
    publication_time_policy: str
    timezone: str
    available_date_policy: str
    revision_policy: str
    pit_coverage_window: str
    coverage_numerator: int
    coverage_denominator: int
    missing_policy: str
    row_conservation_counts: Mapping[str, int]
    quarantine_policy: str
    quality_thresholds: Mapping[str, Any]
    downstream_use_cases: tuple[str, ...]
    disable_conditions: tuple[str, ...]
    rollback_reference: str
    evidence_artifact_ids: tuple[str, ...]
    downstream_eligibility: str = "none"
    reviewer_role: str = ""
    decision_timestamp: str = ""
    decision_revision_id: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SourceAcceptanceDossier":
        values = dict(payload)
        schema_version = values.pop("schema_version", "source-acceptance-dossier.v1")
        if schema_version != "source-acceptance-dossier.v1":
            raise ValueError(f"unsupported source acceptance dossier schema: {schema_version}")
        values["downstream_use_cases"] = tuple(values.get("downstream_use_cases", ()))
        values["disable_conditions"] = tuple(values.get("disable_conditions", ()))
        values["evidence_artifact_ids"] = tuple(values.get("evidence_artifact_ids", ()))
        values["row_conservation_counts"] = dict(values.get("row_conservation_counts", {}))
        values["quality_thresholds"] = dict(values.get("quality_thresholds", {}))
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "source-acceptance-dossier.v1",
            "source_id": self.source_id,
            "source_owner_role": self.source_owner_role,
            "license_owner_role": self.license_owner_role,
            "license_status": self.license_status,
            "license_scope": self.license_scope,
            "redistribution_policy": self.redistribution_policy,
            "source_status": self.source_status,
            "publication_time_policy": self.publication_time_policy,
            "timezone": self.timezone,
            "available_date_policy": self.available_date_policy,
            "revision_policy": self.revision_policy,
            "pit_coverage_window": self.pit_coverage_window,
            "coverage_numerator": self.coverage_numerator,
            "coverage_denominator": self.coverage_denominator,
            "missing_policy": self.missing_policy,
            "row_conservation_counts": dict(self.row_conservation_counts),
            "quarantine_policy": self.quarantine_policy,
            "quality_thresholds": dict(self.quality_thresholds),
            "downstream_use_cases": list(self.downstream_use_cases),
            "downstream_eligibility": self.downstream_eligibility,
            "disable_conditions": list(self.disable_conditions),
            "rollback_reference": self.rollback_reference,
            "evidence_artifact_ids": list(self.evidence_artifact_ids),
            "reviewer_role": self.reviewer_role,
            "decision_timestamp": self.decision_timestamp,
            "decision_revision_id": self.decision_revision_id,
        }

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True)
class SourceAcceptanceProjection:
    p0_source_count: int
    p0_source_ids: tuple[str, ...]
    broker_lane_source_id: str
    decisions: tuple[SourceAcceptanceDecisionRevision, ...]


@dataclass(frozen=True)
class SourceAcceptanceMachineReview:
    """機器證據裁決結果；成功時只產生 research-shadow 限定決議。"""

    source_id: str
    status: str
    blockers: tuple[str, ...]
    policy_version: str
    evidence_content_hash: str
    reason: str
    decision: SourceAcceptanceDecisionRevision | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MACHINE_EVIDENCE_SCHEMA_VERSION,
            "source_id": self.source_id,
            "status": self.status,
            "blockers": list(self.blockers),
            "policy_version": self.policy_version,
            "evidence_content_hash": self.evidence_content_hash,
            "reason": self.reason,
            "decision": self.decision.to_dict() if self.decision is not None else None,
            # 缺少或無效的 machine 封包是證據 blocker，不重新命名為必須人工
            # 審查的 Gate。
            "human_review_required": False,
            "evidence_remediation_required": self.decision is None,
            "downstream_eligibility": "none",
            "formal_acceptance_applied": False,
        }


@dataclass(frozen=True)
class SourceAcceptanceDiagnosis:
    """不可變的資料源診斷評估結果。"""

    source_id: str
    checklist: tuple[Mapping[str, Any], ...]
    missing_programmatic_evidence: tuple[str, ...]
    missing_authority_evidence: tuple[str, ...]
    active_blockers: tuple[str, ...]
    checklist_complete: bool
    status: str
    allowed_use_cases: tuple[str, ...]
    downstream_eligibility: str


class SourceAcceptanceGovernance:
    """資料源評估治理類別，不論檢核是否通過，始終保持 deferred 及 none 的 fail-closed 邊界。"""

    def evaluate(self, dossier: SourceAcceptanceDossier) -> SourceAcceptanceDecisionRevision:
        blockers = _required_blockers(dossier)
        blockers.append("source_acceptance_not_authorized")
        revision_id = dossier.decision_revision_id or (
            f"candidate:{dossier.source_id}:{dossier.content_hash.removeprefix('sha256:')[:16]}"
        )
        return SourceAcceptanceDecisionRevision(
            source_id=dossier.source_id,
            decision_revision_id=revision_id,
            parent_revision_id=None,
            status="deferred",
            allowed_use_cases=(),
            blockers=tuple(sorted(set(blockers))),
            license_evidence_ids=_evidence_ids(dossier, "license:"),
            quality_evidence_ids=_evidence_ids(dossier, "quality:"),
            pit_evidence_ids=_evidence_ids(dossier, "pit:"),
            owner_role=dossier.source_owner_role,
            reviewer_role=dossier.reviewer_role,
            decided_at=dossier.decision_timestamp,
            rollback_reference=dossier.rollback_reference,
        )

    def evaluate_machine_evidence(
        self,
        payload: Mapping[str, Any],
        *,
        evidence_root: Path | None = None,
    ) -> SourceAcceptanceMachineReview:
        """以固定 schema 執行唯讀 machine evidence 裁決。

        這是與既有 owner-review ``evaluate`` 分離的入口。它只在完整、可
        驗證且 hash 綁定的證據封套上建立 ``limited`` 決議，並把用途限制
        在 ``research_shadow``／``diagnostics``；任何缺失或矛盾都回傳
        具體 blocker，不會產生 accepted 決議。
        """

        return _evaluate_machine_evidence(payload, evidence_root=evidence_root)

    def diagnose_dossier(self, dossier: SourceAcceptanceDossier) -> SourceAcceptanceDiagnosis:
        """執行 dossier 唯讀結構化檢查，返回檢核清單與缺失證據的不可變診斷結果。"""
        blockers = _required_blockers(dossier)

        # 1. 建立詳細資訊：發布政策
        pub_detail = f"目前政策: {dossier.publication_time_policy}"
        if not is_policy_evidenced(dossier.publication_time_policy):
            pub_detail += " (缺失原因: 包含未驗證/無效關鍵字)"

        # 2. 建立詳細資訊：可得日政策
        avail_detail = f"目前政策: {dossier.available_date_policy}"
        if not is_policy_evidenced(dossier.available_date_policy):
            avail_detail += " (缺失原因: 包含 first_observed_only 或 not_official_announcement)"

        # 3. 建立詳細資訊：修訂政策
        rev_detail = f"目前政策: {dossier.revision_policy}"
        if not is_policy_evidenced(dossier.revision_policy):
            rev_detail += " (缺失原因: 未能證明修訂機制)"

        # 4. 建立詳細資訊：PIT 覆蓋窗口
        pit_detail = f"目前窗口: {dossier.pit_coverage_window}"
        if not is_policy_evidenced(dossier.pit_coverage_window):
            pit_detail += " (缺失原因: 未能證明 PIT 覆蓋)"

        # 5. 建立詳細資訊：隔離政策
        quar_detail = f"目前政策: {dossier.quarantine_policy}"
        if not is_policy_evidenced(dossier.quarantine_policy):
            quar_detail += " (缺失原因: 未驗證隔離機制)"

        # 6. 建立詳細資訊：覆蓋率數值與型別硬化 (整數除法，不經過 float)
        num = dossier.coverage_numerator
        den = dossier.coverage_denominator
        raw_threshold = dossier.quality_thresholds.get("minimum_coverage_bp", 0)
        threshold_valid = isinstance(raw_threshold, int) and raw_threshold >= 0

        if den <= 0 or num < 0 or num > den or not threshold_valid:
            if den <= 0:
                cov_detail = f"覆蓋率: {num}/{den} (原因: 分母必須大於 0)"
            elif num < 0:
                cov_detail = f"覆蓋率: {num}/{den} (原因: 分子不得為負數)"
            elif num > den:
                cov_detail = f"覆蓋率: {num}/{den} (原因: 分子不得大於分母)"
            else:
                cov_detail = f"覆蓋率: {num}/{den} (原因: 品質門檻最低覆蓋基點必須為非負整數，目前為 {raw_threshold})"
        else:
            cov_bp = (num * 10000) // den
            cov_detail = f"覆蓋率: {num}/{den} ({cov_bp} bp, 門檻: {raw_threshold} bp)"
            if num == 0:
                cov_detail += " (缺失原因: 分子必須大於 0)"
            elif cov_bp < raw_threshold:
                cov_detail += " (缺失原因: 覆蓋率未達最低品質門檻)"

        # 建立檢核清單，並依據 blockers 清單決定 status，確保兩者完全同步
        checklist = []

        def add_item(name: str, desc: str, is_prog: bool, blocker_name: str, detail: str):
            failed = blocker_name in blockers
            status = "verified" if not failed else ("missing_programmatic_evidence" if is_prog else "missing_authority_evidence")
            checklist.append({
                "name": name,
                "description": desc,
                "is_programmatic": is_prog,
                "status": status,
                "detail": detail
            })

        add_item("source_owner_role", "驗證資料源擁有者角色是否已填寫", False, "missing_source_owner", f"目前擁有者角色: {dossier.source_owner_role}")
        add_item("license_owner_role", "驗證法務/授權擁有者角色是否已填寫", False, "missing_license_owner", f"目前法務角色: {dossier.license_owner_role}")
        add_item("license_status", "驗證資料授權狀態是否已由合規或法務擁有者核准", False, "license_not_accepted", f"目前狀態: {dossier.license_status} (範圍: {dossier.license_scope})")
        add_item("redistribution_policy", "驗證資料再分發限制是否已記錄於文件", False, "missing_redistribution_policy", f"目前政策: {dossier.redistribution_policy}")
        add_item("publication_time_policy", "驗證官方發布窗口與 SLA 參數", False, "missing_publication_time_policy", pub_detail)
        add_item("timezone", "驗證資料時區設定是否已記錄", False, "missing_timezone", f"目前時區: {dossier.timezone}")
        add_item("available_date_policy", "驗證可得日是否早於或等於決策日以防止未來函數", True, "missing_available_date_policy", avail_detail)
        add_item("revision_policy", "驗證歷史資料補正與更正政策是否具備治理機制", False, "missing_revision_policy", rev_detail)
        add_item("pit_coverage_window", "驗證點對點歷史覆蓋時間窗口", False, "missing_pit_coverage", pit_detail)
        add_item("coverage_bp", "驗證程式覆蓋率是否滿足最低品質閾值", True, "missing_coverage_bp", cov_detail)
        add_item("row_conservation", "驗證原始行數與被接受候選行數之保存性", True, "missing_row_conservation", f"數量: {dict(dossier.row_conservation_counts)}")
        add_item("quarantine_policy", "驗證異常或格式損壞資料之程式隔離規則", True, "missing_quarantine_policy", quar_detail)
        add_item("quality_thresholds", "驗證資料品質門檻配置是否存在", True, "missing_quality_thresholds", f"目前門檻: {dict(dossier.quality_thresholds)}")
        add_item("downstream_eligibility", "驗證資料源下游授權資格是否已填寫", False, "missing_downstream_eligibility", f"目前資格: {dossier.downstream_eligibility}")
        add_item("rollback_reference", "驗證回滾參考是否設定為有效的註冊表修訂版或禁用參考", False, "missing_rollback_reference", f"目前參考: {dossier.rollback_reference}")

        # 缺失證據清單
        missing_prog: list[str] = [str(item["name"]) for item in checklist if item["is_programmatic"] and item["status"] != "verified"]
        missing_auth: list[str] = [str(item["name"]) for item in checklist if not item["is_programmatic"] and item["status"] != "verified"]

        is_ready = len(missing_prog) == 0 and len(missing_auth) == 0 and len(blockers) == 0

        # 不論 checklist_complete 為何，status 固定為 deferred，allowed_use_cases 固定為空，eligibility 固定為 none
        return SourceAcceptanceDiagnosis(
            source_id=dossier.source_id,
            checklist=tuple(checklist),
            missing_programmatic_evidence=tuple(missing_prog),
            missing_authority_evidence=tuple(missing_auth),
            active_blockers=tuple(blockers),
            checklist_complete=is_ready,
            status="deferred",
            allowed_use_cases=(),
            downstream_eligibility="none"
        )

    def generate_owner_review_template(self, dossier: SourceAcceptanceDossier, diagnostics: SourceAcceptanceDiagnosis) -> str:
        """產生供擁有者進行審查與核准的 Markdown 範本。"""
        checklist_md = []
        for item in diagnostics.checklist:
            status_symbol = "✅" if item["status"] == "verified" else "❌"
            item_type = "程式驗證 (Programmatic)" if item["is_programmatic"] else "管理權限 (Authority/Legal)"
            checklist_md.append(
                f"- {status_symbol} **{item['name']}** [{item_type}]: {item['description']}\n"
                f"  - *詳細資訊 (Detail)*: {item['detail']}\n"
                f"  - *狀態 (Status)*: {item['status']}"
            )

        checklist_str = "\n".join(checklist_md)
        blockers_md = "\n".join(f"- {b}" for b in diagnostics.active_blockers) if diagnostics.active_blockers else "- 無"

        template = f"""# 來源接受擁有者審查範本 (Source Acceptance Owner Review Template)

> **[重要說明]** 此為資料源 `{dossier.source_id}` 的唯讀、非套用審查範本。
> 在擁有者審查並向註冊表註冊有效決議之前，所有下游授權均保持為 `none` 且所有使用場景均被阻擋。

## 1. 來源元數據 (Source Metadata)
- **來源識別碼 (Source ID)**: {dossier.source_id}
- **來源擁有者角色 (Source Owner Role)**: {dossier.source_owner_role}
- **審查者角色 (Reviewer Role)**: {dossier.reviewer_role}
- **決策時間戳記 (Decision Timestamp)**: {dossier.decision_timestamp}
- **內容雜湊值 (Content Hash)**: {dossier.content_hash}

## 2. 證據接受檢核清單 (Evidence Acceptance Checklist)
{checklist_str}

## 3. 診斷與作用中阻擋器 (Diagnostics & Active Blockers)
{blockers_md}

## 4. 擁有者核准與待辦清單 (Owner Attestation & Action Items)
若要接受此資料源，擁有者必須提供並驗證上方列出的所有缺失證據。
若有任何未解決項目，審查狀態必須維持為 **deferred**，且下游 eligibility 為 **none**。

### 擁有者審查輸入 JSON 範本 (Draft Owner Review Input Schema)
```json
{{
  "source_id": "{dossier.source_id}",
  "decision_revision_id": "decision:{dossier.source_id}:YYYYMMDD-rev1",
  "parent_revision_id": null,
  "status": "deferred",
  "allowed_use_cases": [],
  "blockers": ["source_acceptance_owner_review_required"],
  "license_evidence_ids": [],
  "quality_evidence_ids": [],
  "pit_evidence_ids": [],
  "owner_role": "{dossier.source_owner_role}",
  "reviewer_role": "{dossier.reviewer_role}",
  "decided_at": "{dossier.decision_timestamp}",
  "rollback_reference": "{dossier.rollback_reference}"
}}
```
"""
        return template

    def project(
        self, contracts: Iterable[Any], decisions: Iterable[SourceAcceptanceDecisionRevision]
    ) -> SourceAcceptanceProjection:
        p0_source_ids = tuple(contract.source_id for contract in contracts)
        if len(p0_source_ids) != 13 or len(set(p0_source_ids)) != 13:
            raise ValueError("P0 source denominator must remain exactly thirteen")
        if BROKER_REVALIDATION_SOURCE_ID in p0_source_ids:
            raise ValueError("broker revalidation must remain outside the P0 denominator")
        return SourceAcceptanceProjection(
            p0_source_count=len(p0_source_ids),
            p0_source_ids=p0_source_ids,
            broker_lane_source_id=BROKER_REVALIDATION_SOURCE_ID,
            decisions=tuple(decisions),
        )


def calculate_machine_evidence_hash(payload: Mapping[str, Any]) -> str:
    """計算 machine evidence 封套的 canonical SHA-256。

    ``content_sha256`` 本身不參與 hash，讓產生器可以先 canonicalize 其餘
    欄位再填入宣告值。這是完整性綁定，不是人類簽名或法律授權。
    """

    if not isinstance(payload, Mapping):
        raise TypeError("machine evidence must be an object")
    canonical_payload = dict(payload)
    canonical_payload.pop("content_sha256", None)
    canonical = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"


def _evaluate_machine_evidence(
    payload: Mapping[str, Any],
    *,
    evidence_root: Path | None = None,
) -> SourceAcceptanceMachineReview:
    if not isinstance(payload, Mapping):
        raise TypeError("machine evidence must be an object")

    raw = dict(payload)
    artifact_root = evidence_root.resolve() if evidence_root is not None else Path.cwd()
    blockers: list[str] = []
    source_id = _machine_text(raw.get("source_id"))
    if not source_id:
        blockers.append("machine_evidence_source_id_missing")
    elif source_id not in P0_SOURCE_IDS:
        blockers.append("machine_evidence_source_outside_p0_denominator")

    if raw.get("schema_version") != MACHINE_EVIDENCE_SCHEMA_VERSION:
        blockers.append("machine_evidence_schema_unsupported")
    if raw.get("policy_version") != MACHINE_DECISION_POLICY_VERSION:
        blockers.append("machine_evidence_policy_version_unsupported")
    unknown_keys = set(raw) - _MACHINE_EVIDENCE_KEYS
    if unknown_keys:
        blockers.append("machine_evidence_unsupported_fields")

    declared_hash = raw.get("content_sha256")
    if not _machine_digest(declared_hash):
        blockers.append("machine_evidence_content_hash_invalid")
        evidence_hash = ""
    else:
        evidence_hash = str(declared_hash)
        try:
            expected_hash = calculate_machine_evidence_hash(raw)
        except (TypeError, ValueError):
            blockers.append("machine_evidence_not_canonicalizable")
        else:
            if evidence_hash != expected_hash:
                blockers.append("machine_evidence_content_hash_mismatch")

    decision_date_value = _machine_text(raw.get("decision_date"))
    decision_date = _machine_date(decision_date_value)
    if decision_date is None:
        blockers.append("machine_evidence_decision_date_invalid")
    decision_timestamp = _machine_text(raw.get("decision_timestamp"))
    parsed_timestamp = _machine_datetime(decision_timestamp)
    if parsed_timestamp is None:
        blockers.append("machine_evidence_decision_timestamp_invalid")
    elif decision_date is not None and parsed_timestamp.date() != decision_date:
        blockers.append("machine_evidence_decision_timestamp_date_mismatch")

    source_version = _machine_text(raw.get("source_version"))
    if not source_version:
        blockers.append("machine_evidence_source_version_missing")

    license_envelope = _machine_mapping(raw.get("license"), "license", blockers)
    license_payload = _load_machine_artifact(
        license_envelope,
        section="license",
        source_id=source_id,
        artifact_root=artifact_root,
        blockers=blockers,
    )
    license_id = _machine_evidence_id(
        license_payload, "license", "machine_evidence_license_id_missing", blockers
    )
    if license_payload.get("status") not in _MACHINE_LICENSE_VERIFIED_STATUSES:
        blockers.append("machine_evidence_license_status_not_approved")
    license_url = _machine_text(license_payload.get("source_url"))
    parsed_url = urlparse(license_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        blockers.append("machine_evidence_license_url_invalid")
    if license_url not in _MACHINE_ALLOWED_LICENSE_URLS:
        blockers.append("machine_evidence_license_url_not_allowlisted")
    final_url = _machine_text(license_payload.get("final_url"))
    if final_url not in _MACHINE_ALLOWED_LICENSE_URLS:
        blockers.append("machine_evidence_license_final_url_not_allowlisted")
    if license_url and final_url and final_url != license_url:
        blockers.append("machine_evidence_license_final_url_mismatch")
    if not _machine_digest(license_payload.get("content_sha256")):
        blockers.append("machine_evidence_license_content_hash_invalid")
    license_capture_time = _machine_datetime(
        _machine_text(license_payload.get("captured_at_utc"))
    )
    if license_capture_time is None:
        blockers.append("machine_evidence_license_capture_timestamp_invalid")
    elif parsed_timestamp is not None and license_capture_time > parsed_timestamp:
        blockers.append("machine_evidence_license_capture_after_decision")
    if license_payload.get("http_status") not in range(200, 300):
        blockers.append("machine_evidence_license_http_status_invalid")
    if license_payload.get("truncated") is not False:
        blockers.append("machine_evidence_license_content_incomplete")
    keyword_flags = _machine_mapping(
        license_payload.get("keyword_flags"), "license_keyword_flags", blockers
    )
    agreement_flags = _machine_mapping(
        keyword_flags.get("agreement_or_license"),
        "license_agreement_keyword_flags",
        blockers,
    )
    if agreement_flags.get("matched") is not True:
        blockers.append("machine_evidence_license_terms_not_verified")
    if license_payload.get("final_host_allowlisted") is not True:
        blockers.append("machine_evidence_license_host_not_allowlisted")
    if license_payload.get("agreement_or_license_present") is not True:
        blockers.append("machine_evidence_license_terms_not_verified")
    if license_payload.get("content_persisted") is not False:
        blockers.append("machine_evidence_license_content_persistence_forbidden")
    _validate_machine_license_scope_policy(license_payload, blockers)
    _validate_machine_license_capture_binding(
        license_payload,
        source_id=source_id,
        artifact_root=artifact_root,
        blockers=blockers,
    )
    _validate_machine_government_dataset_binding(
        license_payload,
        source_id=source_id,
        artifact_root=artifact_root,
        decision_timestamp=parsed_timestamp,
        blockers=blockers,
    )
    require_source_input_bindings = (
        license_payload.get("status") == "machine_scope_verified"
        and isinstance(license_payload.get("scope_policy"), Mapping)
    )

    quality_envelope = _machine_mapping(raw.get("quality"), "quality", blockers)
    quality_payload = _load_machine_artifact(
        quality_envelope,
        section="quality",
        source_id=source_id,
        artifact_root=artifact_root,
        blockers=blockers,
    )
    _validate_machine_source_scope_binding(
        license_payload,
        quality_payload,
        source_id=source_id,
        section="quality",
        blockers=blockers,
    )
    quality_input_hash = _validate_machine_artifact_input_binding(
        quality_payload,
        section="quality",
        artifact_root=artifact_root,
        blockers=blockers,
    )
    if (
        require_source_input_bindings
        and quality_payload.get("schema_version")
        == "source-acceptance-quality-evidence.v1"
        and quality_input_hash is None
    ):
        blockers.append("machine_evidence_quality_input_binding_required")
    quality_id = _machine_evidence_id(
        quality_payload, "quality", "machine_evidence_quality_id_missing", blockers
    )
    if _machine_text(quality_payload.get("source_version")) != source_version:
        blockers.append("machine_evidence_quality_source_version_mismatch")
    if quality_payload.get("status") != "verified":
        blockers.append("machine_evidence_quality_status_unverified")
    quality_score = _machine_int_value(
        quality_payload.get("quality_score_bp"), lower=0, upper=10000
    )
    if quality_score is None:
        blockers.append("machine_evidence_quality_score_invalid")
    elif quality_score < MACHINE_MINIMUM_QUALITY_BP:
        blockers.append("machine_evidence_quality_below_minimum")
    quality_hash = quality_payload.get("content_sha256")
    if not _machine_digest(quality_hash):
        blockers.append("machine_evidence_quality_content_hash_invalid")
    if quality_input_hash is not None and _normalize_machine_digest(str(quality_hash)) != quality_input_hash:
        blockers.append("machine_evidence_quality_content_hash_not_bound_to_input")
    auto_evidence = quality_payload.get("auto_verifiable")
    if isinstance(auto_evidence, (str, bytes)) or not isinstance(auto_evidence, Sequence):
        blockers.append("machine_evidence_quality_auto_evidence_missing")
        auto_evidence_values: tuple[str, ...] = ()
    else:
        auto_evidence_values = tuple(item for item in auto_evidence if isinstance(item, str))
    if not _MACHINE_REQUIRED_AUTO_EVIDENCE.issubset(set(auto_evidence_values)):
        blockers.append("machine_evidence_quality_auto_evidence_incomplete")
    quality_checks = _machine_mapping(quality_payload.get("checks"), "quality_checks", blockers)
    for check_name in ("schema_valid", "reconciled", "quarantine_complete"):
        if quality_checks.get(check_name) is not True:
            blockers.append(f"machine_evidence_quality_check_{check_name}_failed")

    pit_envelope = _machine_mapping(raw.get("pit"), "pit", blockers)
    pit_payload = _load_machine_artifact(
        pit_envelope,
        section="pit",
        source_id=source_id,
        artifact_root=artifact_root,
        blockers=blockers,
    )
    _validate_machine_source_scope_binding(
        license_payload,
        pit_payload,
        source_id=source_id,
        section="pit",
        blockers=blockers,
    )
    pit_input_hash = _validate_machine_artifact_input_binding(
        pit_payload,
        section="pit",
        artifact_root=artifact_root,
        blockers=blockers,
    )
    if (
        require_source_input_bindings
        and pit_payload.get("schema_version") == "source-acceptance-pit-evidence.v1"
        and pit_input_hash is None
    ):
        blockers.append("machine_evidence_pit_input_binding_required")
    pit_id = _machine_evidence_id(
        pit_payload, "pit", "machine_evidence_pit_id_missing", blockers
    )
    if pit_payload.get("status") != "verified":
        blockers.append("machine_evidence_pit_status_unverified")
    if pit_payload.get("lineage_complete") is not True:
        blockers.append("machine_evidence_pit_lineage_incomplete")
    if not _machine_digest(pit_payload.get("content_sha256")):
        blockers.append("machine_evidence_pit_content_hash_invalid")
    if pit_input_hash is not None and _normalize_machine_digest(str(pit_payload.get("content_sha256"))) != pit_input_hash:
        blockers.append("machine_evidence_pit_content_hash_not_bound_to_input")
    pit_auto_evidence = pit_payload.get("auto_verifiable")
    if isinstance(pit_auto_evidence, (str, bytes)) or not isinstance(
        pit_auto_evidence, Sequence
    ):
        blockers.append("machine_evidence_pit_auto_evidence_missing")
    elif "payload_hash_verified" not in {
        item for item in pit_auto_evidence if isinstance(item, str)
    }:
        blockers.append("machine_evidence_pit_auto_evidence_incomplete")
    lineage_hashes = pit_payload.get("lineage_artifact_hashes")
    if isinstance(lineage_hashes, (str, bytes)) or not isinstance(
        lineage_hashes, Sequence
    ) or not lineage_hashes or any(not _machine_digest(item) for item in lineage_hashes):
        blockers.append("machine_evidence_pit_lineage_hashes_invalid")
    observations = pit_payload.get("observations")
    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        blockers.append("machine_evidence_pit_observations_missing")
        observations = ()
    if not observations:
        blockers.append("machine_evidence_pit_observations_missing")
    for observation in observations:
        if not isinstance(observation, Mapping):
            blockers.append("machine_evidence_pit_observation_invalid")
            continue
        if observation.get("source_id", source_id) != source_id:
            blockers.append("machine_evidence_pit_source_id_mismatch")
        observation_version = _machine_text(observation.get("source_version"))
        if not observation_version or observation_version != source_version:
            blockers.append("machine_evidence_pit_source_version_mismatch")
        available_date = _machine_date(_machine_text(observation.get("available_date")))
        if available_date is None:
            blockers.append("machine_evidence_pit_available_date_invalid")
        elif decision_date is not None and available_date > decision_date:
            blockers.append("machine_evidence_pit_future_available_date")
        available_at = _machine_datetime(_machine_text(observation.get("available_at")))
        if available_at is None:
            blockers.append("machine_evidence_pit_available_timestamp_missing")
        elif parsed_timestamp is not None and available_at > parsed_timestamp:
            blockers.append("machine_evidence_pit_available_after_decision")
        elif available_date is not None and available_at.date() != available_date:
            blockers.append("machine_evidence_pit_available_timestamp_date_mismatch")
        if observation.get("status") not in {"verified", "shadow_ready"}:
            blockers.append("machine_evidence_pit_observation_unavailable")

    coverage_payload = _machine_artifact_claim(
        raw,
        quality_payload,
        "coverage",
        "machine_evidence_quality_coverage_missing",
        "machine_evidence_quality_coverage_claim_mismatch",
        blockers,
    )
    coverage_bp = coverage_payload.get("coverage_bp")
    numerator = coverage_payload.get("numerator")
    denominator = coverage_payload.get("denominator")
    universe_payload = _machine_mapping(
        quality_payload.get("expected_universe"),
        "expected_universe",
        blockers,
    )
    universe_input_hash = _validate_machine_artifact_input_binding(
        universe_payload,
        section="expected_universe",
        artifact_root=artifact_root,
        blockers=blockers,
    )
    if (
        require_source_input_bindings
        and quality_payload.get("schema_version")
        == "source-acceptance-quality-evidence.v1"
        and isinstance(universe_payload, Mapping)
        and universe_input_hash is None
    ):
        blockers.append("machine_evidence_expected_universe_input_binding_required")
    if universe_payload.get("source_id") != source_id:
        blockers.append("machine_evidence_expected_universe_source_id_mismatch")
    if not _machine_text(universe_payload.get("evidence_id")).startswith("universe:"):
        blockers.append("machine_evidence_expected_universe_id_invalid")
    if not _machine_digest(universe_payload.get("content_sha256")):
        blockers.append("machine_evidence_expected_universe_hash_invalid")
    if universe_input_hash is not None and _normalize_machine_digest(
        str(universe_payload.get("content_sha256"))
    ) != universe_input_hash:
        blockers.append("machine_evidence_expected_universe_hash_not_bound_to_input")
    universe_date = _machine_date(_machine_text(universe_payload.get("as_of_date")))
    if universe_date is None:
        blockers.append("machine_evidence_expected_universe_date_invalid")
    elif decision_date is not None and universe_date > decision_date:
        blockers.append("machine_evidence_expected_universe_future_date")
    expected_universe = coverage_payload.get("expected_universe_count")
    coverage_bp_value = _machine_int_value(coverage_bp, lower=0, upper=10000)
    numerator_value = _machine_int_value(numerator, lower=0)
    denominator_value = _machine_int_value(denominator, lower=1)
    expected_universe_value = _machine_int_value(expected_universe, lower=1)
    universe_count_value = _machine_int_value(universe_payload.get("count"), lower=1)
    if expected_universe_value is not None and universe_count_value is not None:
        if expected_universe_value != universe_count_value:
            blockers.append("machine_evidence_expected_universe_count_mismatch")
    elif expected_universe_value is not None:
        blockers.append("machine_evidence_expected_universe_count_invalid")
    if coverage_bp_value is None:
        blockers.append("machine_evidence_coverage_invalid")
    if numerator_value is None or denominator_value is None or expected_universe_value is None:
        blockers.append("machine_evidence_coverage_counts_invalid")
    elif coverage_bp_value is not None:
        if denominator_value != expected_universe_value:
            blockers.append("machine_evidence_expected_universe_mismatch")
        elif numerator_value > denominator_value:
            blockers.append("machine_evidence_coverage_counts_invalid")
        elif coverage_bp_value != (numerator_value * 10000) // denominator_value:
            blockers.append("machine_evidence_coverage_claim_mismatch")
    if coverage_bp_value is not None and coverage_bp_value < MACHINE_MINIMUM_COVERAGE_BP:
        blockers.append("machine_evidence_coverage_below_minimum")
    coverage_basis = _machine_text(coverage_payload.get("basis"))
    if not coverage_basis or any(
        token in coverage_basis.lower() for token in ("inferred", "estimated", "unknown", "synthetic")
    ):
        blockers.append("machine_evidence_coverage_basis_unverified")

    row_payload = _machine_artifact_claim(
        raw,
        quality_payload,
        "row_conservation",
        "machine_evidence_quality_row_conservation_missing",
        "machine_evidence_quality_row_conservation_claim_mismatch",
        blockers,
    )
    counts: dict[str, int] = {}
    for count_name in ("raw", "accepted", "quarantine", "blocked"):
        value = row_payload.get(count_name)
        value_int = _machine_int_value(value, lower=0)
        if value_int is None:
            blockers.append(f"machine_evidence_row_conservation_{count_name}_invalid")
        else:
            counts[count_name] = value_int
    if len(counts) == 4:
        if counts["raw"] <= 0 or counts["accepted"] <= 0:
            blockers.append("machine_evidence_row_conservation_empty")
        if counts["accepted"] > counts["raw"] or sum(
            counts[name] for name in ("accepted", "quarantine", "blocked")
        ) != counts["raw"]:
            blockers.append("machine_evidence_row_conservation_mismatch")

    quarantine_payload = _machine_artifact_claim(
        raw,
        quality_payload,
        "quarantine",
        "machine_evidence_quality_quarantine_missing",
        "machine_evidence_quality_quarantine_claim_mismatch",
        blockers,
    )
    if quarantine_payload.get("status") != "verified":
        blockers.append("machine_evidence_quarantine_status_unverified")
    if not _machine_text(quarantine_payload.get("policy")):
        blockers.append("machine_evidence_quarantine_policy_missing")
    if counts:
        if quarantine_payload.get("quarantined_rows") != counts.get("quarantine"):
            blockers.append("machine_evidence_quarantine_count_mismatch")
        if quarantine_payload.get("blocked_rows") != counts.get("blocked"):
            blockers.append("machine_evidence_quarantine_blocked_count_mismatch")

    availability_envelope = _machine_mapping(raw.get("availability"), "availability", blockers)
    availability_payload = _load_machine_artifact(
        availability_envelope,
        section="availability",
        source_id=source_id,
        artifact_root=artifact_root,
        blockers=blockers,
    )
    _validate_machine_source_scope_binding(
        license_payload,
        availability_payload,
        source_id=source_id,
        section="availability",
        blockers=blockers,
    )
    availability_input_hash = _validate_machine_artifact_input_binding(
        availability_payload,
        section="availability",
        artifact_root=artifact_root,
        blockers=blockers,
    )
    if (
        require_source_input_bindings
        and availability_payload.get("schema_version")
        == "source-acceptance-availability-evidence.v1"
        and availability_input_hash is None
    ):
        blockers.append("machine_evidence_availability_input_binding_required")
    availability_id = _machine_evidence_id(
        availability_payload,
        "availability",
        "machine_evidence_availability_id_missing",
        blockers,
    )
    if availability_payload.get("status") != "available":
        blockers.append("machine_evidence_availability_unavailable")
    if not _machine_digest(availability_payload.get("content_sha256")):
        blockers.append("machine_evidence_availability_content_hash_invalid")
    if availability_input_hash is not None and _normalize_machine_digest(str(availability_payload.get("content_sha256"))) != availability_input_hash:
        blockers.append("machine_evidence_availability_content_hash_not_bound_to_input")
    available_date = _machine_date(_machine_text(availability_payload.get("available_date")))
    if available_date is None:
        blockers.append("machine_evidence_availability_date_invalid")
    elif decision_date is not None and available_date > decision_date:
        blockers.append("machine_evidence_availability_future_date")
    availability_time = _machine_datetime(_machine_text(availability_payload.get("available_at")))
    if availability_time is None:
        blockers.append("machine_evidence_availability_timestamp_invalid")
    elif parsed_timestamp is not None and availability_time > parsed_timestamp:
        blockers.append("machine_evidence_availability_after_decision")
    elif available_date is not None and availability_time.date() != available_date:
        blockers.append("machine_evidence_availability_timestamp_date_mismatch")
    observed_at = _machine_datetime(_machine_text(availability_payload.get("observed_at")))
    if observed_at is None:
        blockers.append("machine_evidence_availability_timestamp_invalid")
    elif parsed_timestamp is not None and observed_at > parsed_timestamp:
        blockers.append("machine_evidence_availability_observed_after_decision")

    maturity_payload = _machine_artifact_claim(
        raw,
        quality_payload,
        "maturity",
        "machine_evidence_quality_maturity_missing",
        "machine_evidence_quality_maturity_claim_mismatch",
        blockers,
    )
    if maturity_payload.get("status") != "mature":
        blockers.append("machine_evidence_maturity_incomplete")
    completed_periods = maturity_payload.get("completed_periods")
    minimum_periods = maturity_payload.get("minimum_periods")
    completed_periods_value = _machine_int_value(completed_periods, lower=1)
    minimum_periods_value = _machine_int_value(minimum_periods, lower=1)
    if completed_periods_value is None or minimum_periods_value is None:
        blockers.append("machine_evidence_maturity_periods_invalid")
    elif completed_periods_value < minimum_periods_value:
        blockers.append("machine_evidence_maturity_periods_incomplete")
    if maturity_payload.get("lineage_complete") is not True:
        blockers.append("machine_evidence_maturity_lineage_incomplete")
    if "maturity_window_verified" not in set(auto_evidence_values):
        blockers.append("machine_evidence_maturity_auto_evidence_incomplete")

    allowed_use_cases = _machine_strings(raw.get("allowed_use_cases"))
    if not allowed_use_cases:
        blockers.append("machine_evidence_use_scope_missing")
    elif not set(allowed_use_cases).issubset(MACHINE_ALLOWED_USE_CASES):
        blockers.append("machine_evidence_use_scope_unauthorized")

    rollback_reference = _machine_text(raw.get("rollback_reference"))
    if not rollback_reference or rollback_reference == "decision:future-disable-revision":
        blockers.append("machine_evidence_rollback_reference_missing")
    decision_revision_id = _machine_text(raw.get("decision_revision_id"))
    if not decision_revision_id:
        decision_revision_id = (
            f"machine:{source_id}:{evidence_hash.removeprefix('sha256:')[:16]}"
            if evidence_hash
            else ""
        )
    parent_revision_id = raw.get("parent_revision_id")
    if parent_revision_id is not None and not _machine_text(parent_revision_id):
        blockers.append("machine_evidence_parent_revision_invalid")
        parent_revision_id = None
    elif parent_revision_id is not None:
        parent_revision_id = str(parent_revision_id).strip()

    unique_blockers = tuple(sorted(set(blockers)))
    if unique_blockers:
        reason = "machine evidence blocked: " + ", ".join(unique_blockers)
        return SourceAcceptanceMachineReview(
            source_id=source_id,
            status="blocked",
            blockers=unique_blockers,
            policy_version=MACHINE_DECISION_POLICY_VERSION,
            evidence_content_hash=evidence_hash,
            reason=reason,
            decision=None,
        )

    # 前面的驗證已保證成功決議一定有可用的整數覆蓋率。
    assert coverage_bp_value is not None
    reason = (
        "machine evidence verified by "
        f"{MACHINE_DECISION_POLICY_VERSION}; license={license_id}, quality={quality_id}, "
        f"pit={pit_id}, availability={availability_id}, coverage={coverage_bp_value}bp; "
        "research_shadow and diagnostics scope only; no human attestation inferred"
    )
    decision = SourceAcceptanceDecisionRevision(
        source_id=source_id,
        decision_revision_id=decision_revision_id,
        parent_revision_id=parent_revision_id,
        status="limited",
        allowed_use_cases=allowed_use_cases,
        blockers=(),
        license_evidence_ids=(license_id,),
        quality_evidence_ids=(quality_id,),
        pit_evidence_ids=(pit_id,),
        owner_role=MACHINE_DECISION_ACTOR,
        reviewer_role="",
        decided_at=decision_timestamp,
        rollback_reference=rollback_reference,
        decision_actor=MACHINE_DECISION_ACTOR,
        decision_policy_version=MACHINE_DECISION_POLICY_VERSION,
        decision_evidence_hash=evidence_hash,
        decision_reason=reason,
    )
    try:
        validate_source_acceptance_decision_revision(decision)
    except (TypeError, ValueError) as error:
        blocker = "machine_evidence_decision_revision_invalid"
        return SourceAcceptanceMachineReview(
            source_id=source_id,
            status="blocked",
            blockers=(blocker,),
            policy_version=MACHINE_DECISION_POLICY_VERSION,
            evidence_content_hash=evidence_hash,
            reason=f"machine evidence blocked: {blocker}: {error}",
            decision=None,
        )
    return SourceAcceptanceMachineReview(
        source_id=source_id,
        status="machine_verified",
        blockers=(),
        policy_version=MACHINE_DECISION_POLICY_VERSION,
        evidence_content_hash=evidence_hash,
        reason=reason,
        decision=decision,
    )


def _load_machine_artifact(
    envelope: Mapping[str, Any],
    *,
    section: str,
    source_id: str,
    artifact_root: Path,
    blockers: list[str],
) -> Mapping[str, Any]:
    """讀取並重新計算一個 evidence producer 產出的 artifact。

    外層封套的布林欄位不具權威；真正的 status、source identity 與 evidence
    fields 只從這個已讀取且以 bytes 重算 hash 的 artifact 取得。
    """

    artifact_path_value = _machine_text(envelope.get("artifact_path"))
    if not artifact_path_value:
        blockers.append(f"machine_evidence_{section}_artifact_path_missing")
        return {}
    declared_hash = envelope.get("content_sha256")
    if not _machine_digest(declared_hash):
        blockers.append(f"machine_evidence_{section}_artifact_hash_invalid")
        return {}
    artifact_path = _resolve_machine_custody_path(
        artifact_path_value,
        artifact_root,
        f"{section}_artifact",
        blockers,
    )
    if artifact_path is None:
        return {}
    try:
        raw_bytes = artifact_path.read_bytes()
    except OSError:
        blockers.append(f"machine_evidence_{section}_artifact_unavailable")
        return {}
    if len(raw_bytes) > 8 * 1024 * 1024:
        blockers.append(f"machine_evidence_{section}_artifact_too_large")
        return {}
    actual_hash = f"sha256:{sha256(raw_bytes).hexdigest()}"
    if _normalize_machine_digest(str(declared_hash)) != actual_hash:
        blockers.append(f"machine_evidence_{section}_artifact_hash_mismatch")
        return {}
    try:
        artifact = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        blockers.append(f"machine_evidence_{section}_artifact_json_invalid")
        return {}
    if not isinstance(artifact, Mapping):
        blockers.append(f"machine_evidence_{section}_artifact_not_object")
        return {}
    schema_version = artifact.get("schema_version")
    if schema_version not in _MACHINE_ARTIFACT_SCHEMAS.get(section, frozenset()):
        blockers.append(f"machine_evidence_{section}_artifact_schema_unsupported")
    producer = artifact.get("producer")
    if producer not in _MACHINE_ARTIFACT_PRODUCERS.get(section, frozenset()):
        blockers.append(f"machine_evidence_{section}_artifact_producer_unsupported")
    producer_path = Path(__file__).resolve().parents[1] / _MACHINE_ARTIFACT_PRODUCER_PATHS[section]
    try:
        producer_code_hash = f"sha256:{sha256(producer_path.read_bytes()).hexdigest()}"
    except OSError:
        blockers.append(f"machine_evidence_{section}_producer_unavailable")
    else:
        if artifact.get("producer_code_sha256") != producer_code_hash:
            blockers.append(f"machine_evidence_{section}_producer_hash_mismatch")
    if artifact.get("source_id") != source_id:
        blockers.append(f"machine_evidence_{section}_artifact_source_id_mismatch")
    envelope_id = _machine_text(envelope.get("evidence_id"))
    artifact_id = _machine_text(artifact.get("evidence_id"))
    if not envelope_id:
        blockers.append(f"machine_evidence_{section}_id_missing")
    elif artifact_id != envelope_id:
        blockers.append(f"machine_evidence_{section}_artifact_evidence_id_mismatch")
    return artifact


def _machine_producer_code_sha256(section: str) -> str:
    path_value = _MACHINE_ARTIFACT_PRODUCER_PATHS.get(section)
    if not path_value:
        return ""
    try:
        return f"sha256:{sha256((Path(__file__).resolve().parents[1] / path_value).read_bytes()).hexdigest()}"
    except OSError:
        return ""


def _validate_machine_license_scope_policy(
    artifact: Mapping[str, Any],
    blockers: list[str],
) -> None:
    """驗證已核對的官方條款版本與明確 endpoint 用途範圍。

    關鍵字只保留在 capture 的診斷資料中；這裡只接受 policy registry 已
    登錄的完整官方文件指紋、條款輪廓與 source endpoint scope。文件內容、
    Last-Modified 或端點任一變更都必須回到 blocked，不能藉由新增關鍵字
    或自填布林值恢復 machine scope。
    """

    policy = artifact.get("scope_policy")
    if policy is None and artifact.get("status") == "approved":
        # 舊版 fixture／已持久化 payload 沒有新 policy 封套，維持讀取相容性；
        # 新 producer 使用 machine_scope_verified 時則必須帶完整規則。
        return
    if not isinstance(policy, Mapping):
        blockers.append("machine_evidence_license_scope_policy_missing")
        return
    policy_version = _machine_text(policy.get("policy_version"))
    if not policy_version:
        blockers.append("machine_evidence_license_scope_policy_version_missing")
    source_url = _machine_text(artifact.get("source_url"))
    known_rule = _MACHINE_LICENSE_SCOPE_RULES.get(source_url)
    if known_rule is None:
        blockers.append("machine_evidence_license_scope_policy_unknown_source")
        return
    if policy_version != known_rule["policy_version"]:
        blockers.append("machine_evidence_license_scope_policy_version_mismatch")

    expected_document = known_rule.get("official_document")
    document = policy.get("official_document")
    if not isinstance(expected_document, Mapping) or not isinstance(
        document, Mapping
    ):
        blockers.append("machine_evidence_license_document_fingerprint_missing")
    else:
        for field_name in (
            "document_id",
            "document_version",
            "last_modified",
            "content_type",
            "clause_profile_id",
        ):
            if document.get(field_name) != expected_document.get(field_name):
                blockers.append(
                    f"machine_evidence_license_document_{field_name}_mismatch"
                )
        expected_document_hash = _normalize_machine_digest(
            str(expected_document.get("content_sha256"))
        )
        document_hash = _normalize_machine_digest(
            str(document.get("content_sha256"))
        )
        if not expected_document_hash or document_hash != expected_document_hash:
            blockers.append("machine_evidence_license_document_hash_mismatch")
        expected_bytes = expected_document.get("content_bytes")
        if (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or document.get("content_bytes") != expected_bytes
        ):
            blockers.append("machine_evidence_license_document_size_mismatch")
        if set(_machine_strings(document.get("verified_clause_ids"))) != set(
            _machine_strings(expected_document.get("verified_clause_ids"))
        ):
            blockers.append("machine_evidence_license_clause_profile_mismatch")
        artifact_hash = _normalize_machine_digest(
            str(artifact.get("content_sha256"))
        )
        if not expected_document_hash or artifact_hash != expected_document_hash:
            blockers.append("machine_evidence_license_content_not_policy_version")

    source_id = _machine_text(artifact.get("source_id"))
    source_scopes = known_rule.get("source_scopes")
    expected_scope = (
        source_scopes.get(source_id)
        if isinstance(source_scopes, Mapping)
        else None
    )
    declared_scope = policy.get("source_scope")
    if not isinstance(expected_scope, Mapping) or not isinstance(
        declared_scope, Mapping
    ):
        blockers.append("machine_evidence_license_endpoint_scope_missing")
    else:
        for field_name in ("endpoint_id", "endpoint_url", "acquisition_route_id"):
            if declared_scope.get(field_name) != expected_scope.get(field_name):
                blockers.append(
                    f"machine_evidence_license_endpoint_{field_name}_mismatch"
                )
        if set(_machine_strings(declared_scope.get("allowed_use_cases"))) != set(
            _machine_strings(expected_scope.get("allowed_use_cases"))
        ):
            blockers.append("machine_evidence_license_endpoint_use_scope_mismatch")
        expected_government_dataset = expected_scope.get("government_dataset")
        declared_government_dataset = declared_scope.get("government_dataset")
        if isinstance(expected_government_dataset, Mapping):
            if not isinstance(declared_government_dataset, Mapping):
                blockers.append("machine_evidence_license_government_dataset_scope_missing")
            else:
                for field_name in (
                    "dataset_id",
                    "dataset_url",
                    "metadata_url",
                    "identifier",
                    "title",
                    "data_provider_id",
                    "publisher_oid",
                    "license_code",
                    "license_version",
                    "license_url",
                    "endpoint_url",
                    "resource_url",
                    "api_documentation_url",
                    "metadata_content_bytes",
                    "metadata_modified",
                ):
                    if declared_government_dataset.get(field_name) != (
                        expected_government_dataset.get(field_name)
                    ):
                        blockers.append(
                            "machine_evidence_license_government_dataset_scope_mismatch"
                        )
                if _normalize_machine_digest(
                    str(declared_government_dataset.get("metadata_content_sha256"))
                ) != _normalize_machine_digest(
                    str(expected_government_dataset.get("metadata_content_sha256"))
                ):
                    blockers.append(
                        "machine_evidence_license_government_dataset_hash_mismatch"
                    )
    if policy.get("source_id") != source_id:
        blockers.append("machine_evidence_license_scope_source_id_mismatch")

    allowed_use_cases = _machine_strings(policy.get("allowed_use_cases"))
    expected_allowed_use_cases = _machine_strings(known_rule.get("allowed_use_cases"))
    if not allowed_use_cases or not set(allowed_use_cases).issubset(
        MACHINE_ALLOWED_USE_CASES
    ) or set(allowed_use_cases) != set(expected_allowed_use_cases):
        blockers.append("machine_evidence_license_scope_policy_unauthorized")
    for field_name in (
        "formal_oos_allowed",
        "production_scheduler_allowed",
        "redistribution_allowed",
        "legal_acceptance_inferred",
    ):
        if policy.get(field_name) is not known_rule.get(field_name):
            blockers.append(f"machine_evidence_license_scope_{field_name}_forbidden")
    if policy.get("machine_policy_only") is not True:
        blockers.append("machine_evidence_license_scope_policy_not_machine_only")


def _validate_machine_license_capture_binding(
    artifact: Mapping[str, Any],
    *,
    source_id: str,
    artifact_root: Path,
    blockers: list[str],
) -> None:
    """重新讀取 license capture，確認 child artifact 沒有錯綁另一份 JSON。"""

    binding = artifact.get("capture_artifact")
    if binding is None and artifact.get("status") == "approved":
        return
    if not isinstance(binding, Mapping):
        blockers.append("machine_evidence_license_capture_binding_missing")
        return
    path = _resolve_machine_custody_path(
        binding.get("path"), artifact_root, "license_capture", blockers
    )
    declared_hash = binding.get("content_sha256")
    if path is None or not _machine_digest(declared_hash):
        blockers.append("machine_evidence_license_capture_binding_invalid")
        return
    try:
        raw_bytes = path.read_bytes()
    except OSError:
        blockers.append("machine_evidence_license_capture_unavailable")
        return
    actual_hash = f"sha256:{sha256(raw_bytes).hexdigest()}"
    if _normalize_machine_digest(str(declared_hash)) != actual_hash:
        blockers.append("machine_evidence_license_capture_hash_mismatch")
        return
    bytes_value = binding.get("bytes")
    if bytes_value is not None and (
        isinstance(bytes_value, bool)
        or not isinstance(bytes_value, int)
        or bytes_value != len(raw_bytes)
    ):
        blockers.append("machine_evidence_license_capture_size_mismatch")
    try:
        decoded = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        blockers.append("machine_evidence_license_capture_json_invalid")
        return
    if not isinstance(decoded, Mapping):
        blockers.append("machine_evidence_license_capture_not_object")
        return
    if decoded.get("schema_version") != "p0-license-evidence-capture.v1":
        blockers.append("machine_evidence_license_capture_schema_unsupported")
    for field_name in ("candidate_only", "source_acceptance_granted", "license_accepted"):
        expected = True if field_name == "candidate_only" else False
        if decoded.get(field_name) is not expected:
            blockers.append(f"machine_evidence_license_capture_{field_name}_boundary_invalid")
    targets = decoded.get("targets")
    if isinstance(targets, (str, bytes)) or not isinstance(targets, Sequence):
        blockers.append("machine_evidence_license_capture_targets_invalid")
        return
    expected_url = _machine_text(artifact.get("source_url"))
    matching = [
        item
        for item in targets
        if isinstance(item, Mapping)
        and source_id in _machine_strings(item.get("source_ids"))
        and item.get("license_evidence_url") == expected_url
    ]
    if len(matching) != 1:
        blockers.append("machine_evidence_license_capture_target_mismatch")
        return
    target = matching[0]
    expected_policy = _MACHINE_LICENSE_SCOPE_RULES.get(expected_url)
    expected_document = (
        expected_policy.get("official_document")
        if isinstance(expected_policy, Mapping)
        else None
    )
    expected_scope = None
    if isinstance(expected_policy, Mapping):
        source_scopes = expected_policy.get("source_scopes")
        if isinstance(source_scopes, Mapping):
            expected_scope = source_scopes.get(source_id)
    target_headers = target.get("headers")
    target_headers_mapping: Mapping[str, Any] = (
        target_headers if isinstance(target_headers, Mapping) else {}
    )
    target_content_type = str(target_headers_mapping.get("content_type") or "")
    target_media_type = target_content_type.split(";", 1)[0].strip().casefold()
    expected_media_type = (
        str(expected_document.get("content_type") or "").casefold()
        if isinstance(expected_document, Mapping)
        else ""
    )
    expected_document_hash = (
        _normalize_machine_digest(str(expected_document.get("content_sha256")))
        if isinstance(expected_document, Mapping)
        else ""
    )
    target_hash = _normalize_machine_digest(str(target.get("content_sha256")))
    expected_document_bytes = (
        expected_document.get("content_bytes")
        if isinstance(expected_document, Mapping)
        else None
    )
    government_evidence = artifact.get("government_dataset_evidence")
    government_expected = (
        expected_scope.get("government_dataset")
        if isinstance(expected_scope, Mapping)
        else None
    )
    government_evidence_bound = (
        not isinstance(government_expected, Mapping)
        or (
            isinstance(government_evidence, Mapping)
            and _normalize_machine_digest(
                str(government_evidence.get("content_sha256"))
            )
            == _normalize_machine_digest(
                str(government_expected.get("metadata_content_sha256"))
            )
            and government_evidence.get("metadata_url")
            == government_expected.get("metadata_url")
            and government_evidence.get("dataset_id")
            == government_expected.get("dataset_id")
            and government_evidence.get("resource_url")
            == government_expected.get("resource_url")
        )
    )
    recomputed_checks = {
        "captured": target.get("status") == "captured",
        "http_success": (
            isinstance(target.get("http_status"), int)
            and not isinstance(target.get("http_status"), bool)
            and 200 <= target["http_status"] < 300
        ),
        "requested_url_allowlisted": expected_url in _MACHINE_LICENSE_SCOPE_RULES,
        "final_url_exact_allowlisted": (
            target.get("final_url") == expected_url
            and expected_url in _MACHINE_LICENSE_SCOPE_RULES
        ),
        "response_complete": target.get("truncated") is False,
        "capture_producer_verified": (
            decoded.get("producer") == "capture_p0_license_evidence.py"
            and decoded.get("producer_code_sha256")
            == _machine_producer_code_sha256("license")
        ),
        "official_document_hash_verified": (
            bool(expected_document_hash) and target_hash == expected_document_hash
        ),
        "official_document_version_verified": (
            isinstance(expected_document, Mapping)
            and target_headers_mapping.get("last_modified")
            == expected_document.get("last_modified")
        ),
        "official_document_size_verified": (
            isinstance(expected_document_bytes, int)
            and not isinstance(expected_document_bytes, bool)
            and target.get("bytes_captured") == expected_document_bytes
        ),
        "official_document_type_verified": (
            bool(expected_media_type) and target_media_type == expected_media_type
        ),
        "scope_policy_known": expected_policy is not None,
        "source_scope_known": isinstance(expected_scope, Mapping),
        "final_host_allowlisted": target.get("final_host_allowlisted") is True,
        "government_dataset_evidence_bound": government_evidence_bound,
        "content_not_persisted": target.get("content_persisted") is False,
    }
    objective_checks = artifact.get("objective_checks")
    if not isinstance(objective_checks, Mapping):
        blockers.append("machine_evidence_license_objective_checks_missing")
    else:
        for check_name, expected_check in recomputed_checks.items():
            if objective_checks.get(check_name) is not expected_check:
                blockers.append(
                    f"machine_evidence_license_objective_check_{check_name}_mismatch"
                )
    for field_name in (
        "status",
        "http_status",
        "final_url",
        "captured_at_utc",
        "truncated",
        "content_persisted",
        "final_host_allowlisted",
        "keyword_flags",
    ):
        if field_name == "status":
            if target.get(field_name) != "captured":
                blockers.append("machine_evidence_license_capture_status_mismatch")
            continue
        expected_value: Any = target.get(field_name)
        actual_value: Any = artifact.get(field_name)
        if actual_value != expected_value:
            blockers.append(f"machine_evidence_license_capture_{field_name}_mismatch")
    artifact_hash = artifact.get("capture_target_content_sha256")
    if _machine_digest(artifact_hash) and _machine_digest(target_hash):
        if _normalize_machine_digest(str(artifact_hash)) != _normalize_machine_digest(
            str(target_hash)
        ):
            blockers.append("machine_evidence_license_capture_content_hash_mismatch")
    elif artifact.get("status") == "machine_scope_verified":
        blockers.append("machine_evidence_license_capture_content_hash_missing")


def _validate_machine_government_dataset_binding(
    artifact: Mapping[str, Any],
    *,
    source_id: str,
    artifact_root: Path,
    decision_timestamp: datetime | None,
    blockers: list[str],
) -> None:
    """重新讀取 data.gov.tw metadata，核對 dataset／resource／授權版本。"""

    expected_policy = _MACHINE_LICENSE_SCOPE_RULES.get(
        _machine_text(artifact.get("source_url"))
    )
    expected_scopes = (
        expected_policy.get("source_scopes")
        if isinstance(expected_policy, Mapping)
        else None
    )
    expected_scope = (
        expected_scopes.get(source_id)
        if isinstance(expected_scopes, Mapping)
        else None
    )
    expected = (
        expected_scope.get("government_dataset")
        if isinstance(expected_scope, Mapping)
        else None
    )
    binding = artifact.get("government_dataset_evidence")
    if not isinstance(expected, Mapping):
        # 沒有政府平台 mapping 的舊 approved fixture 保持向後相容；新
        # machine_scope policy 會在 scope validator 中要求這個 mapping。
        return
    if not isinstance(binding, Mapping):
        blockers.append("machine_evidence_government_dataset_binding_missing")
        return
    path = _resolve_machine_custody_path(
        binding.get("path"), artifact_root, "government_dataset", blockers
    )
    declared_hash = binding.get("content_sha256")
    if path is None or not _machine_digest(declared_hash):
        blockers.append("machine_evidence_government_dataset_binding_invalid")
        return
    try:
        raw_bytes = path.read_bytes()
    except OSError:
        blockers.append("machine_evidence_government_dataset_unavailable")
        return
    actual_hash = f"sha256:{sha256(raw_bytes).hexdigest()}"
    if _normalize_machine_digest(str(declared_hash)) != actual_hash:
        blockers.append("machine_evidence_government_dataset_hash_mismatch")
    expected_hash = _normalize_machine_digest(
        str(expected.get("metadata_content_sha256"))
    )
    if actual_hash != expected_hash:
        blockers.append("machine_evidence_government_dataset_content_not_policy_version")
    expected_bytes = expected.get("metadata_content_bytes")
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or len(raw_bytes) != expected_bytes
        or binding.get("bytes") != expected_bytes
    ):
        blockers.append("machine_evidence_government_dataset_size_mismatch")
    if binding.get("metadata_url") != expected.get("metadata_url"):
        blockers.append("machine_evidence_government_dataset_url_mismatch")
    if binding.get("dataset_url") != expected.get("dataset_url"):
        blockers.append("machine_evidence_government_dataset_page_mismatch")
    if binding.get("final_url") != expected.get("metadata_url"):
        blockers.append("machine_evidence_government_dataset_final_url_mismatch")
    captured_at = _machine_datetime(_machine_text(binding.get("fetched_at_utc")))
    if captured_at is None:
        blockers.append("machine_evidence_government_dataset_capture_timestamp_invalid")
    elif decision_timestamp is not None and captured_at > decision_timestamp:
        blockers.append("machine_evidence_government_dataset_capture_after_decision")
    if binding.get("http_status") not in range(200, 300):
        blockers.append("machine_evidence_government_dataset_http_status_invalid")
    api_binding = binding.get("api_documentation_evidence")
    if not isinstance(api_binding, Mapping):
        blockers.append("machine_evidence_government_api_binding_missing")
    else:
        # 先初始化，讓缺檔／壞 JSON 只留下具體 blocker，不因後續路徑
        # 比對讀取未初始化區域變成 evaluator 例外。
        api_decoded: Any = None
        api_path = _resolve_machine_custody_path(
            api_binding.get("path"), artifact_root, "government_api", blockers
        )
        api_declared_hash = api_binding.get("content_sha256")
        if api_path is None or not _machine_digest(api_declared_hash):
            blockers.append("machine_evidence_government_api_binding_invalid")
        else:
            try:
                api_raw_bytes = api_path.read_bytes()
            except OSError:
                blockers.append("machine_evidence_government_api_unavailable")
            else:
                api_actual_hash = f"sha256:{sha256(api_raw_bytes).hexdigest()}"
                if _normalize_machine_digest(str(api_declared_hash)) != api_actual_hash:
                    blockers.append("machine_evidence_government_api_hash_mismatch")
                try:
                    api_decoded = json.loads(api_raw_bytes.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    blockers.append("machine_evidence_government_api_json_invalid")
                else:
                    endpoint_url = _machine_text(expected.get("endpoint_url"))
                    endpoint_path = urlparse(endpoint_url).path
                    api_paths = (
                        api_decoded.get("paths")
                        if isinstance(api_decoded, Mapping)
                        else None
                    )
                    base_path = (
                        _machine_text(api_decoded.get("basePath")).rstrip("/")
                        if isinstance(api_decoded, Mapping)
                        else ""
                    )
                    candidate_paths = [endpoint_path]
                    if base_path and endpoint_path.startswith(base_path + "/"):
                        candidate_paths.append(endpoint_path[len(base_path) :])
                    if not isinstance(api_paths, Mapping) or not any(
                        candidate in api_paths for candidate in candidate_paths
                    ):
                        blockers.append("machine_evidence_government_api_endpoint_missing")
                if api_binding.get("metadata_url") != expected.get(
                    "api_documentation_url"
                ):
                    blockers.append("machine_evidence_government_api_url_mismatch")
                if api_binding.get("endpoint_url") != expected.get("endpoint_url"):
                    blockers.append("machine_evidence_government_api_endpoint_mismatch")
                if api_binding.get("endpoint_path") != urlparse(
                    _machine_text(expected.get("endpoint_url"))
                ).path:
                    blockers.append("machine_evidence_government_api_path_mismatch")
                endpoint_path = urlparse(
                    _machine_text(expected.get("endpoint_url"))
                ).path
                base_path = ""
                if isinstance(api_decoded, Mapping):
                    base_path = _machine_text(api_decoded.get("basePath")).rstrip("/")
                expected_swagger_path = endpoint_path
                if base_path and endpoint_path.startswith(base_path + "/"):
                    expected_swagger_path = endpoint_path[len(base_path) :]
                if api_binding.get("swagger_path") not in {
                    endpoint_path,
                    expected_swagger_path,
                }:
                    blockers.append("machine_evidence_government_api_swagger_path_mismatch")
                api_captured_at = _machine_datetime(
                    _machine_text(api_binding.get("fetched_at_utc"))
                )
                if api_captured_at is None:
                    blockers.append(
                        "machine_evidence_government_api_capture_timestamp_invalid"
                    )
                elif decision_timestamp is not None and api_captured_at > decision_timestamp:
                    blockers.append("machine_evidence_government_api_capture_after_decision")
    try:
        decoded = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        blockers.append("machine_evidence_government_dataset_json_invalid")
        return
    if not isinstance(decoded, Mapping) or decoded.get("success") is not True:
        blockers.append("machine_evidence_government_dataset_response_invalid")
        return
    result = decoded.get("result")
    if not isinstance(result, Mapping):
        blockers.append("machine_evidence_government_dataset_result_missing")
        return
    expected_fields = {
        "datasetId": "dataset_id",
        "identifier": "identifier",
        "title": "title",
        "dataProvider": "data_provider_id",
        "publisherOID": "publisher_oid",
        "license": "license_code",
        "modifiedDate": "metadata_modified",
    }
    for result_field, expected_field in expected_fields.items():
        if result.get(result_field) != expected.get(expected_field):
            blockers.append(
                f"machine_evidence_government_dataset_{expected_field}_mismatch"
            )
    distribution = result.get("distribution")
    if isinstance(distribution, (str, bytes)) or not isinstance(
        distribution, Sequence
    ):
        blockers.append("machine_evidence_government_dataset_distribution_missing")
    else:
        resource_urls = {
            str(item.get("resourceDownloadUrl"))
            for item in distribution
            if isinstance(item, Mapping) and item.get("resourceDownloadUrl")
        }
        if expected.get("resource_url") not in resource_urls:
            blockers.append("machine_evidence_government_dataset_resource_mismatch")
    api_documentation_url = _machine_text(expected.get("api_documentation_url"))
    if not api_documentation_url or api_documentation_url not in str(
        result.get("notes") or ""
    ):
        blockers.append("machine_evidence_government_dataset_api_mapping_missing")
    for binding_field, expected_field in (
        ("dataset_id", "dataset_id"),
        ("identifier", "identifier"),
        ("title", "title"),
        ("data_provider_id", "data_provider_id"),
        ("publisher_oid", "publisher_oid"),
        ("license_code", "license_code"),
        ("license_version", "license_version"),
        ("license_url", "license_url"),
        ("endpoint_url", "endpoint_url"),
        ("resource_url", "resource_url"),
        ("api_documentation_url", "api_documentation_url"),
        ("metadata_modified", "metadata_modified"),
    ):
        if binding.get(binding_field) != expected.get(expected_field):
            blockers.append(
                f"machine_evidence_government_dataset_binding_{binding_field}_mismatch"
            )


def _validate_machine_source_scope_binding(
    license_artifact: Mapping[str, Any],
    evidence_artifact: Mapping[str, Any],
    *,
    source_id: str,
    section: str,
    blockers: list[str],
) -> None:
    """把 quality／PIT／availability 的 raw input 綁回 license endpoint。"""

    scope_policy = license_artifact.get("scope_policy")
    if not isinstance(scope_policy, Mapping):
        # 舊版 owner fixture 沒有 machine scope；其相容性由各自 schema
        # 檢核維持。新 machine artifact 會在 input binding 檢核中要求 raw input。
        return
    declared_source_id = _machine_text(scope_policy.get("source_id"))
    if declared_source_id != source_id:
        blockers.append(f"machine_evidence_{section}_scope_source_id_mismatch")
    source_scope = scope_policy.get("source_scope")
    input_artifact = evidence_artifact.get("input_artifact")
    if not isinstance(source_scope, Mapping) or not isinstance(input_artifact, Mapping):
        return
    for field_name in ("endpoint_id", "endpoint_url", "acquisition_route_id"):
        expected = source_scope.get(field_name)
        actual = input_artifact.get(
            "source_url" if field_name == "endpoint_url" else field_name
        )
        if actual != expected:
            blockers.append(f"machine_evidence_{section}_source_scope_{field_name}_mismatch")


def _validate_machine_artifact_input_binding(
    artifact: Mapping[str, Any],
    *,
    section: str,
    artifact_root: Path,
    blockers: list[str],
) -> str | None:
    """驗證 producer child artifact 指向的原始 bytes 與宣告 hash。"""

    binding = artifact.get("input_artifact")
    if binding is None:
        return None
    if not isinstance(binding, Mapping):
        blockers.append(f"machine_evidence_{section}_input_binding_invalid")
        return None
    path = _resolve_machine_custody_path(
        binding.get("path"), artifact_root, f"{section}_input", blockers
    )
    declared_hash = binding.get("content_sha256")
    if path is None or not _machine_digest(declared_hash):
        blockers.append(f"machine_evidence_{section}_input_binding_invalid")
        return None
    try:
        raw_bytes = path.read_bytes()
    except OSError:
        blockers.append(f"machine_evidence_{section}_input_unavailable")
        return None
    actual_hash = f"sha256:{sha256(raw_bytes).hexdigest()}"
    if _normalize_machine_digest(str(declared_hash)) != actual_hash:
        blockers.append(f"machine_evidence_{section}_input_hash_mismatch")
        return None
    bytes_value = binding.get("bytes")
    if bytes_value is not None and (
        isinstance(bytes_value, bool)
        or not isinstance(bytes_value, int)
        or bytes_value != len(raw_bytes)
    ):
        blockers.append(f"machine_evidence_{section}_input_size_mismatch")
    return actual_hash


def _resolve_machine_custody_path(
    value: Any,
    artifact_root: Path,
    field_name: str,
    blockers: list[str],
) -> Path | None:
    path_value = _machine_text(value)
    if not path_value:
        blockers.append(f"machine_evidence_{field_name}_path_missing")
        return None
    candidate = Path(path_value)
    resolved_root = artifact_root.resolve()
    try:
        resolved = candidate.resolve() if candidate.is_absolute() else (resolved_root / candidate).resolve()
        resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        blockers.append(f"machine_evidence_{field_name}_path_outside_root")
        return None
    return resolved


def _machine_artifact_claim(
    outer: Mapping[str, Any],
    artifact: Mapping[str, Any],
    field_name: str,
    missing_code: str,
    mismatch_code: str,
    blockers: list[str],
) -> Mapping[str, Any]:
    value = artifact.get(field_name)
    if not isinstance(value, Mapping):
        blockers.append(missing_code)
        return {}
    outer_value = outer.get(field_name)
    if outer_value is not None and outer_value != value:
        blockers.append(mismatch_code)
    return value


def _machine_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _machine_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return ()
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return ()
    return tuple(dict.fromkeys(item.strip() for item in value))


def _machine_mapping(value: Any, field_name: str, blockers: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        blockers.append(f"machine_evidence_{field_name}_missing")
        return {}
    return value


def _machine_evidence_id(
    payload: Mapping[str, Any],
    prefix: str,
    missing_code: str,
    blockers: list[str],
) -> str:
    evidence_id = _machine_text(payload.get("evidence_id"))
    if not evidence_id:
        blockers.append(missing_code)
    elif not evidence_id.startswith(f"{prefix}:"):
        blockers.append(f"machine_evidence_{prefix}_id_prefix_invalid")
    return evidence_id


def _machine_int(value: Any, *, lower: int, upper: int | None = None) -> bool:
    return _machine_int_value(value, lower=lower, upper=upper) is not None


def _machine_int_value(
    value: Any, *, lower: int, upper: int | None = None
) -> int | None:
    """只回傳已完成邊界檢查的整數，避免對任意 Any 做隱式轉型。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < lower:
        return None
    if upper is not None and value > upper:
        return None
    return value


def _machine_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _machine_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _machine_digest(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    digest = value.removeprefix("sha256:")
    if len(digest) != 64:
        return False
    try:
        int(digest, 16)
    except ValueError:
        return False
    return True


def _normalize_machine_digest(value: str) -> str:
    return f"sha256:{value.removeprefix('sha256:')}"


def _required_blockers(dossier: SourceAcceptanceDossier) -> list[str]:
    """收集資料源所缺少的所有必要證據與阻擋條件。"""
    blockers: list[str] = []

    # 1. source_owner_role
    if not dossier.source_owner_role.strip():
        blockers.append("missing_source_owner")

    # 2. license_owner_role
    if not dossier.license_owner_role.strip():
        blockers.append("missing_license_owner")

    # 3. license_status
    if dossier.license_status.strip().lower() != "approved":
        blockers.append("license_not_accepted")

    # 4. redistribution_policy
    if dossier.redistribution_policy.strip().lower() in {"", "not_decided", "unverified"}:
        blockers.append("missing_redistribution_policy")

    # 5. publication_time_policy
    if not is_policy_evidenced(dossier.publication_time_policy):
        blockers.append("missing_publication_time_policy")

    # 6. timezone
    if not dossier.timezone.strip():
        blockers.append("missing_timezone")

    # 7. available_date_policy
    if not is_policy_evidenced(dossier.available_date_policy):
        blockers.append("missing_available_date_policy")

    # 8. revision_policy
    if not is_policy_evidenced(dossier.revision_policy):
        blockers.append("missing_revision_policy")

    # 9. pit_coverage_window
    if not is_policy_evidenced(dossier.pit_coverage_window):
        blockers.append("missing_pit_coverage")

    # 10. coverage_bp (整數硬化計算與防禦)
    num = dossier.coverage_numerator
    den = dossier.coverage_denominator
    raw_threshold = dossier.quality_thresholds.get("minimum_coverage_bp", 0)
    threshold_valid = isinstance(raw_threshold, int) and raw_threshold >= 0
    if den <= 0 or num < 0 or num > den or not threshold_valid:
        blockers.append("missing_coverage_bp")
    else:
        cov_bp = (num * 10000) // den
        if cov_bp < raw_threshold or num == 0:
            blockers.append("missing_coverage_bp")

    # 11. row_conservation_counts
    if not dossier.row_conservation_counts:
        blockers.append("missing_row_conservation")

    # 12. quarantine_policy
    if not is_policy_evidenced(dossier.quarantine_policy):
        blockers.append("missing_quarantine_policy")

    # 13. quality_thresholds
    if not dossier.quality_thresholds:
        blockers.append("missing_quality_thresholds")

    # 14. downstream_eligibility
    if not dossier.downstream_eligibility.strip():
        blockers.append("missing_downstream_eligibility")

    # 15. rollback_reference
    val = dossier.rollback_reference.strip()
    if not val or val == "decision:future-disable-revision":
        blockers.append("missing_rollback_reference")

    return blockers


def is_policy_evidenced(value: str) -> bool:
    """唯一共用的嚴格未驗證判定規則，適用於發布、可得日、PIT 覆蓋、修訂與隔離政策。"""
    val = value.strip().lower()
    for forbidden in ["unverified", "not_evidenced", "not_decided", "requires_review", "first_observed_only", "not_official_announcement"]:
        if forbidden in val:
            return False
    if not val:
        return False
    return True


def _evidence_ids(dossier: SourceAcceptanceDossier, prefix: str) -> tuple[str, ...]:
    return tuple(item for item in dossier.evidence_artifact_ids if item.startswith(prefix))
