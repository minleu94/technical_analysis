from __future__ import annotations

from datetime import date, datetime, timezone
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pytest

import scripts.capture_p0_license_evidence as capture
from data_module.source_acceptance_decision_registry import (
    MACHINE_DECISION_ACTOR,
    SourceAcceptanceDecisionRegistry,
)
from data_module.source_acceptance_governance import SourceAcceptanceGovernance
from scripts.append_source_acceptance_decision import (
    append_decision,
    build_machine_decision_from_evidence,
)
from scripts.run_p0_source_evidence_audit import (
    _parse_independent_listed_universe,
    build_machine_evidence_bundle,
)


SOURCE_ID = "twse.monthly_revenue_announcement"
TODAY = datetime.now(timezone.utc).date()


class _Response:
    status = 200

    def __init__(
        self,
        url: str,
        body: bytes,
        *,
        content_type: str = "application/json; charset=utf-8",
        last_modified: str | None = None,
    ) -> None:
        self._url = url
        self._body = body
        self.headers = {
            "Date": "Mon, 07 Sep 2026 08:00:00 GMT",
            "Content-Type": content_type,
        }
        if last_modified is not None:
            self.headers["Last-Modified"] = last_modified

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def geturl(self) -> str:
        return self._url


def _license_opener(request: object, *, timeout: float) -> _Response:
    del timeout
    body = "同意政府資料開放，來源引用與完整性要求。".encode("utf-8")
    return _Response(
        "https://www.twse.com.tw/zh/terms/use.html",
        body,
        content_type="text/html",
        last_modified="Mon, 07 Sep 2026 00:00:00 GMT",
    )


def _fake_government_dataset_bytes() -> bytes:
    metadata = {
        "success": True,
        "result": {
            "datasetId": 18420,
            "identifier": "A45020000D-000354",
            "title": "上市公司每月營業收入彙總表",
            "dataProvider": "N121467221",
            "publisherOID": "2.16.886.101.20003.20052.20004",
            "license": "1",
            "modifiedDate": "2026-09-07 00:00:00",
            "notes": "OAS標準之API說明文件網址 https://openapi.twse.com.tw/v1/swagger.json",
            "distribution": [
                {
                    "resourceDownloadUrl": (
                        "https://mopsfin.twse.com.tw/opendata/t187ap05_L.csv"
                    )
                }
            ],
        },
    }
    return json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


@pytest.fixture(autouse=True)
def _test_license_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """以受控 bytes 建立 deterministic policy；live E2E 仍使用正式 policy。"""

    terms_body = "同意政府資料開放，來源引用與完整性要求。".encode("utf-8")
    policy = deepcopy(
        capture.MACHINE_LICENSE_SCOPE_POLICIES[
            "https://www.twse.com.tw/zh/terms/use.html"
        ]
    )
    document = deepcopy(policy["official_document"])
    document.update(
        {
            "document_version": "test-last-modified-2026-09-07",
            "content_sha256": f"sha256:{sha256(terms_body).hexdigest()}",
            "content_bytes": len(terms_body),
            "last_modified": "Mon, 07 Sep 2026 00:00:00 GMT",
        }
    )
    policy["official_document"] = document
    source_scopes = deepcopy(policy["source_scopes"])
    government_dataset = deepcopy(
        source_scopes[SOURCE_ID]["government_dataset"]
    )
    metadata_bytes = _fake_government_dataset_bytes()
    government_dataset.update(
        {
            "metadata_content_sha256": (
                f"sha256:{sha256(metadata_bytes).hexdigest()}"
            ),
            "metadata_content_bytes": len(metadata_bytes),
            "metadata_modified": "2026-09-07 00:00:00",
        }
    )
    source_scopes[SOURCE_ID]["government_dataset"] = government_dataset
    policy["source_scopes"] = source_scopes
    monkeypatch.setitem(
        capture.MACHINE_LICENSE_SCOPE_POLICIES,
        "https://www.twse.com.tw/zh/terms/use.html",
        policy,
    )


def _source_opener(request: object, *, timeout: float) -> _Response:
    del timeout
    url = str(getattr(request, "full_url"))
    if url == "https://data.gov.tw/api/v2/rest/dataset/18420":
        return _Response(url, _fake_government_dataset_bytes())
    if url == "https://openapi.twse.com.tw/v1/swagger.json":
        return _Response(
            url,
            json.dumps({"paths": {"/v1/opendata/t187ap05_L": {}}}).encode(
                "utf-8"
            ),
        )
    if url.endswith("t187ap05_L"):
        rows = [
            {
                "出表日期": "1150817",
                "資料年月": "11507",
                "公司代號": "1101",
                "公司名稱": "台泥",
                "產業別": "01",
                "營業收入-當月營收": "13744103",
            },
            {
                "出表日期": "1150817",
                "資料年月": "11507",
                "公司代號": "2330",
                "公司名稱": "台積電",
                "產業別": "24",
                "營業收入-當月營收": "100",
            },
        ]
    elif url.endswith("t187ap03_L"):
        rows = [
            {"出表日期": "1150906", "公司代號": "1101"},
            {"出表日期": "1150906", "公司代號": "2330"},
        ]
    else:
        raise AssertionError(f"unexpected producer URL: {url}")
    return _Response(url, json.dumps(rows, ensure_ascii=False).encode("utf-8"))


def _capture(tmp_path: Path) -> Path:
    path = tmp_path / "license.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    capture.capture_p0_license_evidence(
        TODAY,
        confirmed=True,
        opener=_license_opener,
        output_path=path,
    )
    return path


def test_official_source_producer_builds_and_appends_machine_bundle(
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "bundle"
    output = evidence_dir / "machine-evidence.json"
    payload = build_machine_evidence_bundle(
        TODAY,
        source_id=SOURCE_ID,
        license_capture_path=_capture(tmp_path),
        output_path=output,
        audit_payload={"schema_version": "p0-source-evidence-audit.v1", "items": []},
        opener=_source_opener,
    )

    review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        payload, evidence_root=evidence_dir
    )
    assert review.status == "machine_verified"
    assert review.decision is not None
    assert review.decision.status == "limited"
    assert review.decision.owner_role == MACHINE_DECISION_ACTOR
    assert review.decision.reviewer_role == ""
    assert payload["allowed_use_cases"] == ["research_shadow", "diagnostics"]
    assert payload["coverage"]["numerator"] == 2
    assert payload["coverage"]["denominator"] == 2
    assert payload["maturity"]["completed_periods"] == 1
    assert payload["maturity"]["minimum_periods"] == 1

    license_artifact = json.loads(
        (evidence_dir / "artifacts" / "license.json").read_text(encoding="utf-8")
    )
    assert license_artifact["status"] == "machine_scope_verified"
    assert license_artifact["objective_checks"]["official_document_hash_verified"] is True
    assert license_artifact["government_dataset_evidence"]["license_version"] == (
        "政府資料開放授權條款-第1版"
    )
    assert license_artifact["scope_policy"]["legal_acceptance_inferred"] is False
    assert license_artifact["capture_artifact"]["path"].endswith(
        "inputs/license_capture.json"
    )

    candidate_registry = tmp_path / "candidate.sqlite"
    revision = build_machine_decision_from_evidence(payload, evidence_root=evidence_dir)
    appended = append_decision(
        revision,
        registry_path=candidate_registry,
        machine_evidence_path=output,
    )
    assert appended["status"] == "appended"
    stored = SourceAcceptanceDecisionRegistry(candidate_registry).current(SOURCE_ID)
    assert stored == revision


def test_license_keyword_alone_cannot_create_machine_scope(tmp_path: Path) -> None:
    capture_path = tmp_path / "weak-license.json"

    def weak_opener(request: object, *, timeout: float) -> _Response:
        del timeout
        return _Response(
            "https://www.twse.com.tw/zh/terms/use.html",
            b"license terms only",
        )

    capture_payload = capture.capture_p0_license_evidence(
        TODAY,
        confirmed=True,
        opener=weak_opener,
        output_path=capture_path,
    )
    artifact_path = tmp_path / "weak-license-artifact.json"
    envelope = capture.build_machine_license_artifact(
        capture_payload,
        source_id=SOURCE_ID,
        output_path=artifact_path,
        capture_path=capture_path,
    )
    assert envelope["status"] == "blocked"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["status"] == "blocked"
    assert artifact["objective_checks"]["scope_policy_known"] is True
    assert artifact["objective_checks"]["official_document_hash_verified"] is False


def test_negated_license_clauses_cannot_create_machine_scope(tmp_path: Path) -> None:
    capture_path = tmp_path / "negated-license.json"

    def negated_opener(request: object, *, timeout: float) -> _Response:
        del timeout
        return _Response(
            "https://www.twse.com.tw/zh/terms/use.html",
            "本資料不適用政府資料開放授權，禁止以來源引用作為授權依據，未經同意不得使用。".encode(
                "utf-8"
            ),
            content_type="text/html",
            last_modified="Mon, 07 Sep 2026 00:00:00 GMT",
        )

    capture_payload = capture.capture_p0_license_evidence(
        TODAY,
        confirmed=True,
        opener=negated_opener,
        output_path=capture_path,
    )
    artifact_path = tmp_path / "negated-license-artifact.json"
    envelope = capture.build_machine_license_artifact(
        capture_payload,
        source_id=SOURCE_ID,
        output_path=artifact_path,
        capture_path=capture_path,
    )
    assert envelope["status"] == "blocked"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert all(
        artifact["keyword_flags"][group]["matched"] is True
        for group in (
            "open_data_or_government_exception",
            "source_attribution_or_integrity",
            "agreement_or_license",
        )
    )
    assert artifact["objective_checks"]["official_document_hash_verified"] is False


def test_machine_bundle_fails_if_source_input_bytes_are_tampered(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "tampered"
    output = evidence_dir / "machine-evidence.json"
    payload = build_machine_evidence_bundle(
        TODAY,
        source_id=SOURCE_ID,
        license_capture_path=_capture(tmp_path),
        output_path=output,
        opener=_source_opener,
    )
    source_path = evidence_dir / "inputs" / "official_source_payload.bin"
    source_path.write_bytes(source_path.read_bytes() + b"tampered")
    review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        payload, evidence_root=evidence_dir
    )
    assert review.decision is None
    assert "machine_evidence_quality_input_hash_mismatch" in review.blockers
    assert "machine_evidence_pit_input_hash_mismatch" in review.blockers
    assert "machine_evidence_availability_input_hash_mismatch" in review.blockers


def test_machine_bundle_rejects_tampered_government_metadata(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "government-tampered"
    output = evidence_dir / "machine-evidence.json"
    payload = build_machine_evidence_bundle(
        TODAY,
        source_id=SOURCE_ID,
        license_capture_path=_capture(tmp_path),
        output_path=output,
        opener=_source_opener,
    )
    metadata_path = evidence_dir / "inputs" / "data_gov_dataset_18420.json"
    metadata_path.write_bytes(metadata_path.read_bytes() + b"tampered")

    review = SourceAcceptanceGovernance().evaluate_machine_evidence(
        payload, evidence_root=evidence_dir
    )

    assert review.decision is None
    assert "machine_evidence_government_dataset_hash_mismatch" in review.blockers


def test_duplicate_official_rows_are_not_silently_used_as_coverage(
    tmp_path: Path,
) -> None:
    def duplicate_opener(request: object, *, timeout: float) -> _Response:
        del timeout
        url = str(getattr(request, "full_url"))
        if url == "https://data.gov.tw/api/v2/rest/dataset/18420":
            return _Response(url, _fake_government_dataset_bytes())
        if url == "https://openapi.twse.com.tw/v1/swagger.json":
            return _Response(
                url,
                json.dumps({"paths": {"/v1/opendata/t187ap05_L": {}}}).encode(
                    "utf-8"
                ),
            )
        if url.endswith("t187ap05_L"):
            rows: list[dict[str, Any]] = [
                {
                    "出表日期": "1150817",
                    "資料年月": "11507",
                    "公司代號": "1101",
                    "營業收入-當月營收": "1",
                },
                {
                    "出表日期": "1150817",
                    "資料年月": "11507",
                    "公司代號": "1101",
                    "營業收入-當月營收": "2",
                },
            ]
        else:
            rows = [{"出表日期": "1150906", "公司代號": "1101"}]
        return _Response(url, json.dumps(rows, ensure_ascii=False).encode("utf-8"))

    with pytest.raises(ValueError, match="duplicate stock symbols"):
        build_machine_evidence_bundle(
            TODAY,
            source_id=SOURCE_ID,
            license_capture_path=_capture(tmp_path),
            output_path=(
                tmp_path / "duplicate" / "machine-evidence.json"
            ),
            opener=duplicate_opener,
        )


def test_independent_universe_preserves_six_digit_depository_receipts() -> None:
    payload = json.dumps(
        [
            {"出表日期": "1150906", "公司代號": "1101"},
            {"出表日期": "1150906", "公司代號": "910322"},
        ],
        ensure_ascii=False,
    ).encode("utf-8")

    codes, as_of = _parse_independent_listed_universe(payload)

    assert codes == {"1101", "910322"}
    assert as_of == "2026-09-06"


def test_independent_universe_rejects_unrecognised_code_width() -> None:
    payload = json.dumps(
        [{"出表日期": "1150906", "公司代號": "12345"}],
        ensure_ascii=False,
    ).encode("utf-8")

    with pytest.raises(ValueError, match="invalid stock code"):
        _parse_independent_listed_universe(payload)
