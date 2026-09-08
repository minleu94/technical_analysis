"""預覽或明確確認 append 一筆 P0 source acceptance decision revision。

預設為 preview-only：只驗證 decision revision 與可選的 P0 intake dossier，
不建立 registry、不開啟 SQLite。只有同時提供 ``--registry`` 與
``--confirm-append`` 才會透過 append-only ``SourceAcceptanceDecisionRegistry``
保存 revision；這不會授予 downstream eligibility、formal OOS、scheduler 或
broker 權限。對 ``accepted``／``limited`` 決議，必須提供已通過
``inspect_p0_intake_readiness.py`` 的 intake dossier，且 decision evidence ids
必須能在 dossier evidence artifact ids 中找到，避免直接用手寫 JSON 升級來源。
外部 ``source-acceptance-owner-review-decision.v1`` 只允許以
``deferred``／``rejected``／``disabled`` 形式讀取；其 attestation 不會被推導成 evidence IDs。

另提供 ``--machine-evidence`` 唯讀入口：只有通過固定的
``source-acceptance-machine-evidence.v1`` 結構、PIT／可得日／覆蓋率／品質／
隔離／成熟度與 canonical hash 檢查，才會建立 machine actor 的
``limited`` research-shadow 決議。此入口不需要 named reviewer，但不會把
machine evidence 推導成正式、production、scheduler、broker 或投資有效性。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from data_module.source_acceptance_decision_registry import (
    MACHINE_DECISION_ACTOR,
    SourceAcceptanceDecisionRevision,
    SourceAcceptanceDecisionRegistry,
    parse_source_acceptance_decision_revision,
)
from data_module.source_acceptance_governance import (
    SourceAcceptanceDossier,
    SourceAcceptanceGovernance,
)
from scripts.inspect_p0_intake_readiness import inspect_p0_intake


_PREVIEW_SCHEMA_VERSION = "source-acceptance-decision-preview.v1"
_APPLYING_STATUSES = frozenset({"accepted", "limited"})
_PRODUCTION_DEFAULT = "D:/Min/Python/Project/FA_Data"


def load_decision(path: Path) -> SourceAcceptanceDecisionRevision:
    """讀取並驗證一筆 decision revision，不開啟 registry。"""

    payload = _read_json_object(path)
    raw = payload.get("decision", payload)
    if not isinstance(raw, Mapping):
        raise ValueError("decision JSON must be an object")
    revision = parse_source_acceptance_decision_revision(raw)
    if revision.source_id not in P0_SOURCE_IDS:
        raise ValueError(f"decision source is outside P0 denominator: {revision.source_id}")
    return revision


def build_machine_decision_from_evidence(
    payload: Mapping[str, Any],
    *,
    evidence_root: Path | None = None,
) -> SourceAcceptanceDecisionRevision:
    """由 machine evidence 封套建立一筆受限決議，不開啟 registry。"""

    review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        payload,
        evidence_root=evidence_root,
    )
    if review.decision is None:
        raise ValueError(review.reason)
    return review.decision


def load_machine_decision(path: Path) -> SourceAcceptanceDecisionRevision:
    """讀取、hash 驗證並建立 machine evidence 決議。"""

    return build_machine_decision_from_evidence(
        _read_json_object(path), evidence_root=path.parent
    )


def inspect_decision_input(
    revision: SourceAcceptanceDecisionRevision,
    *,
    intake_path: Path | None = None,
    machine_evidence_path: Path | None = None,
) -> dict[str, Any]:
    """建立不套用決議的 preview payload。"""

    if intake_path is not None and machine_evidence_path is not None:
        raise ValueError("--intake and --machine-evidence cannot be combined")
    machine_binding: dict[str, Any] | None = None
    is_machine_decision = revision.decision_actor == MACHINE_DECISION_ACTOR
    if is_machine_decision:
        if machine_evidence_path is None:
            raise ValueError(
                "machine evidence decision requires --machine-evidence for evidence binding"
            )
        machine_payload = _read_json_object(machine_evidence_path)
        machine_review = SourceAcceptanceGovernance().evaluate_machine_evidence(
            machine_payload,
            evidence_root=machine_evidence_path.parent,
        )
        if machine_review.decision is None:
            raise ValueError(machine_review.reason)
        if machine_review.decision.content_hash != revision.content_hash:
            raise ValueError("machine evidence decision content hash does not match revision")
        if machine_review.evidence_content_hash != revision.decision_evidence_hash:
            raise ValueError("machine evidence bundle hash does not match revision")
        machine_binding = {
            "path": str(machine_evidence_path.resolve()),
            "evidence_content_hash": machine_review.evidence_content_hash,
            "policy_version": machine_review.policy_version,
            "review_status": machine_review.status,
            "reason": machine_review.reason,
        }
    elif machine_evidence_path is not None:
        raise ValueError("--machine-evidence can only bind a machine evidence decision")

    intake_binding: dict[str, Any] | None = None
    if revision.status in _APPLYING_STATUSES and intake_path is None and not is_machine_decision:
        raise ValueError(
            f"{revision.status} decision requires --intake to bind owner-reviewed evidence"
        )
    if intake_path is not None:
        intake_payload = _read_json_object(intake_path)
        intake_result = inspect_p0_intake(intake_payload)
        if intake_result["status"] == "invalid_input":
            raise ValueError("intake artifact is invalid; repair the 13-source input first")
        row = next(
            (item for item in intake_result["rows"] if item["source_id"] == revision.source_id),
            None,
        )
        if row is None or row["status"] == "invalid_input":
            raise ValueError(f"intake dossier is invalid for source: {revision.source_id}")
        dossier = _find_dossier(intake_payload, revision.source_id)
        if dossier.source_id != revision.source_id:
            raise ValueError("intake dossier source_id does not match decision")
        if revision.status in _APPLYING_STATUSES:
            if not row["ready_for_owner_review"]:
                raise ValueError(
                    f"intake dossier is not ready_for_owner_review: {revision.source_id}"
                )
            _require_evidence_binding(revision, dossier)
        intake_binding = {
            "path": str(intake_path.resolve()),
            "dossier_content_hash": dossier.content_hash,
            "intake_status": intake_result["status"],
            "ready_for_owner_review": bool(row["ready_for_owner_review"]),
        }

    return {
        "schema_version": _PREVIEW_SCHEMA_VERSION,
        "status": "preview",
        "decision": revision.to_dict(),
        "decision_content_hash": revision.content_hash,
        "intake_binding": intake_binding,
        "machine_evidence_binding": machine_binding,
        "registry_append_confirmed": False,
        "safety_flags": {
            "read_only": True,
            "writes_allowed": False,
            "downstream_eligibility": "none",
            "formal_oos_allowed": False,
            "production_scheduler_allowed": False,
            "broker_order_allowed": False,
        },
    }


def append_decision(
    revision: SourceAcceptanceDecisionRevision,
    *,
    registry_path: Path,
    intake_path: Path | None = None,
    machine_evidence_path: Path | None = None,
) -> dict[str, Any]:
    """在所有 preview 檢查通過後，append 一筆 decision revision。"""

    preview = inspect_decision_input(
        revision,
        intake_path=intake_path,
        machine_evidence_path=machine_evidence_path,
    )
    _require_registry_path(registry_path)
    registry = SourceAcceptanceDecisionRegistry(registry_path)
    before = len(registry.list_revisions(revision.source_id))
    saved = registry.append(revision)
    after = len(registry.list_revisions(revision.source_id))
    append_state = "appended" if after > before else "already_present"
    return {
        **preview,
        "status": append_state,
        "registry_path": str(registry_path.resolve()),
        "registry_append_confirmed": True,
        "saved_decision_content_hash": saved.content_hash,
        "safety_flags": {
            **preview["safety_flags"],
            "read_only": False,
            "writes_allowed": True,
            "registry_append_confirmed": True,
        },
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    decision = payload.get("decision", {})
    safety = payload.get("safety_flags", {})
    lines = [
        "# Source Acceptance Decision Preview",
        "",
        "> append-only 治理結果；不授予 downstream、formal OOS、scheduler 或 broker 權限。",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Source: `{decision.get('source_id', 'unknown')}`",
        f"- Decision: `{decision.get('status', 'unknown')}`",
        f"- Revision: `{decision.get('decision_revision_id', 'unknown')}`",
        f"- Content hash: `{payload.get('decision_content_hash', 'unknown')}`",
        f"- Registry append confirmed: `{payload.get('registry_append_confirmed', False)}`",
        f"- Boundary: read_only={safety.get('read_only')} writes_allowed={safety.get('writes_allowed')} "
        f"downstream_eligibility={safety.get('downstream_eligibility')} formal_oos_allowed={safety.get('formal_oos_allowed')}",
        "",
    ]
    binding = payload.get("intake_binding")
    if isinstance(binding, Mapping):
        lines.extend(
            [
                "## Intake binding",
                "",
                f"- Dossier hash: `{binding.get('dossier_content_hash', 'unknown')}`",
                f"- Intake status: `{binding.get('intake_status', 'unknown')}`",
                f"- Ready for owner review: `{binding.get('ready_for_owner_review', False)}`",
                "",
            ]
        )
    machine_binding = payload.get("machine_evidence_binding")
    if isinstance(machine_binding, Mapping):
        lines.extend(
            [
                "## Machine evidence binding",
                "",
                f"- Evidence hash: `{machine_binding.get('evidence_content_hash', 'unknown')}`",
                f"- Policy version: `{machine_binding.get('policy_version', 'unknown')}`",
                f"- Review status: `{machine_binding.get('review_status', 'unknown')}`",
                f"- Reason: {machine_binding.get('reason', 'unknown')}",
                "",
            ]
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--decision", type=Path, help="decision revision JSON")
    mode.add_argument(
        "--machine-evidence",
        type=Path,
        help="source-acceptance-machine-evidence.v1 JSON；建立受限 machine 決議",
    )
    parser.add_argument(
        "--intake",
        type=Path,
        help="p0-source-intake.v1 JSON；accepted／limited 必須提供",
    )
    parser.add_argument("--registry", type=Path, help="append-only registry 路徑（確認模式必填）")
    parser.add_argument(
        "--confirm-append",
        action="store_true",
        help="明確確認後才建立／append registry；未提供時只 preview",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path, help="報告輸出路徑；未指定時輸出 stdout")
    args = parser.parse_args(argv)

    try:
        if args.machine_evidence is not None:
            if args.intake is not None:
                raise ValueError("--machine-evidence cannot be combined with --intake")
            revision = load_machine_decision(args.machine_evidence)
        else:
            assert args.decision is not None
            revision = load_decision(args.decision)
        if args.confirm_append:
            if args.registry is None:
                raise ValueError("--confirm-append requires --registry")
            result = append_decision(
                revision,
                registry_path=args.registry,
                intake_path=args.intake,
                machine_evidence_path=args.machine_evidence,
            )
        else:
            result = inspect_decision_input(
                revision,
                intake_path=args.intake,
                machine_evidence_path=args.machine_evidence,
            )
        rendered = (
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
            if args.format == "json"
            else render_markdown(result) + "\n"
        )
        if args.output is not None:
            _write_report(args.output, rendered)
        else:
            print(rendered, end="")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"source acceptance decision blocked: {error}", file=sys.stderr)
        return 2
    return 0


def _find_dossier(payload: Mapping[str, Any], source_id: str) -> SourceAcceptanceDossier:
    raw_dossiers = payload.get("dossiers")
    if not isinstance(raw_dossiers, list):
        raise ValueError("intake dossiers must be an array")
    matching = [
        item
        for item in raw_dossiers
        if isinstance(item, Mapping) and item.get("source_id") == source_id
    ]
    if len(matching) != 1:
        raise ValueError(f"intake must contain exactly one dossier for source: {source_id}")
    try:
        return SourceAcceptanceDossier.from_dict(matching[0])
    except (TypeError, ValueError) as error:
        raise ValueError(f"intake dossier cannot be decoded: {source_id}") from error


def _require_evidence_binding(
    revision: SourceAcceptanceDecisionRevision,
    dossier: SourceAcceptanceDossier,
) -> None:
    available = set(dossier.evidence_artifact_ids)
    for field_name in (
        "license_evidence_ids",
        "quality_evidence_ids",
        "pit_evidence_ids",
    ):
        missing = sorted(set(getattr(revision, field_name)) - available)
        if missing:
            raise ValueError(
                f"decision {field_name} is not bound to intake dossier evidence: {missing}"
            )


def _read_json_object(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return payload


def _write_report(path: Path, rendered: str) -> None:
    _require_non_production_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def _require_registry_path(path: Path) -> None:
    if path.exists() and path.is_dir():
        raise ValueError("registry path must be a file path")
    production_root = Path(os.environ.get("DATA_ROOT", _PRODUCTION_DEFAULT)).resolve()
    try:
        path.resolve().relative_to(production_root)
    except ValueError:
        return
    raise ValueError(
        "registry path under DATA_ROOT requires an explicit candidate registry outside the production root"
    )


def _require_non_production_output(path: Path) -> None:
    production_root = Path(os.environ.get("DATA_ROOT", _PRODUCTION_DEFAULT)).resolve()
    try:
        path.resolve().relative_to(production_root)
    except ValueError:
        return
    raise ValueError("report output must remain outside DATA_ROOT")


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            continue


if __name__ == "__main__":
    raise SystemExit(main())
