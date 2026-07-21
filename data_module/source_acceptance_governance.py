"""Fail-closed, non-applying governance for EV2 source dossiers."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from data_module.source_acceptance_decision_registry import SourceAcceptanceDecisionRevision


BROKER_REVALIDATION_SOURCE_ID = "broker_branch.revalidation"


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
        missing_prog = [item["name"] for item in checklist if item["is_programmatic"] and item["status"] != "verified"]
        missing_auth = [item["name"] for item in checklist if not item["is_programmatic"] and item["status"] != "verified"]

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
