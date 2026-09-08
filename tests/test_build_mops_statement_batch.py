import json
from pathlib import Path

import pytest

from scripts import build_mops_statement_batch as batch
from scripts.plan_mops_statement_universe import build_universe_plan, write_universe_plan


def _write_fake_child(output_root, kwargs) -> None:
    target = output_root / kwargs["run_id"]
    target.mkdir(parents=True)
    candidate = target / "statement-pit-candidate.json"
    manifest = target / "run-manifest.json"
    candidate_payload = {
        "schema_version": "mops-statement-pit-candidate.v1",
        "source_version": "mops-test-source.v1",
        "research_only": True,
        "formal_oos_allowed": False,
        "rows": [
            {
                "stock_code": kwargs["stock_code"],
                "market": kwargs["market"],
                "period": f"{kwargs['roc_year'] + 1911:04d}-Q{kwargs['season']}",
            }
        ],
        "pit_coverage_summary": {
            "stock_code": kwargs["stock_code"],
            "market_request": kwargs["market"],
            "period": f"{kwargs['roc_year'] + 1911:04d}-Q{kwargs['season']}",
        },
    }
    if kwargs.get("report_basis") not in (None, "consolidated"):
        candidate_payload["report_basis"] = kwargs["report_basis"]
        candidate_payload["statement_scope"] = kwargs["report_basis"]
        candidate_payload["rows"][0]["report_basis"] = kwargs["report_basis"]
        candidate_payload["rows"][0]["statement_scope"] = kwargs["report_basis"]
    candidate.write_text(json.dumps(candidate_payload), encoding="utf-8")
    manifest_payload = {
        "schema_version": "mops-statement-pit-run-manifest.v1",
        "run_id": kwargs["run_id"],
        "files": {"candidate": batch._file_sha256_reference(candidate)},
        "research_only": True,
        "formal_oos_allowed": False,
    }
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")


def _batch_args(tmp_path, output_root, manifest_path, *requests, resume=False):
    canonical_manifest = tmp_path / "canonical-manifest.json"
    canonical_dataset = tmp_path / "canonical-dataset.csv"
    canonical_manifest.write_text("manifest", encoding="utf-8")
    canonical_dataset.write_text("dataset", encoding="utf-8")
    values = []
    for request in requests:
        values.extend(["--request", request])
    values.extend(
        [
            "--output-root",
            str(output_root),
            "--batch-manifest",
            str(manifest_path),
            "--canonical-manifest",
            str(canonical_manifest),
            "--canonical-dataset",
            str(canonical_dataset),
            "--max-companies",
            str(len(requests)),
        ]
    )
    if resume:
        values.append("--resume")
    return values


def test_parse_request_requires_explicit_stock_market_and_period() -> None:
    assert batch._parse_request("2330:sii:2026-Q2") == ("2330", "sii", 2026, 2)
    with pytest.raises(ValueError, match="STOCK:MARKET:YYYY-Qn"):
        batch._parse_request("2330:sii")
    with pytest.raises(ValueError, match="valid YYYY-Qn"):
        batch._parse_request("2330:sii:2026-Q5")


def test_parse_listing_override_requires_company_and_path() -> None:
    assert batch._parse_listing_override("2317=C:/tmp/t57.html")[0] == "2317"
    with pytest.raises(ValueError, match="STOCK=PATH"):
        batch._parse_listing_override("2317")


def test_parse_listing_evidence_override_requires_company_and_path() -> None:
    assert batch._parse_listing_evidence_override("2317=C:/tmp/t57-evidence.json")[0] == "2317"
    with pytest.raises(ValueError, match="STOCK=PATH"):
        batch._parse_listing_evidence_override("2317")


def test_parse_listing_browser_evidence_override_requires_company_and_path() -> None:
    assert batch._parse_listing_browser_evidence_override(
        "2881=C:/tmp/t57-browser-evidence.json"
    )[0] == "2881"
    with pytest.raises(ValueError, match="STOCK=PATH"):
        batch._parse_listing_browser_evidence_override("2881")


def test_parse_statement_raw_dir_override_requires_company_and_path() -> None:
    assert batch._parse_statement_raw_dir_override("2317=C:/tmp/raw")[0] == "2317"
    with pytest.raises(ValueError, match="STOCK=PATH"):
        batch._parse_statement_raw_dir_override("2317")


def test_parse_xbrl_browser_overrides_require_company_and_path() -> None:
    assert batch._parse_xbrl_browser_dom_override("1240=C:/tmp/xbrl.html")[0] == "1240"
    assert batch._parse_xbrl_browser_evidence_override("1240=C:/tmp/xbrl.json")[0] == "1240"
    with pytest.raises(ValueError, match="STOCK=PATH"):
        batch._parse_xbrl_browser_dom_override("1240")
    with pytest.raises(ValueError, match="STOCK=PATH"):
        batch._parse_xbrl_browser_evidence_override("1240")


def test_batch_driver_is_bounded_and_emits_child_lineage(tmp_path, monkeypatch) -> None:
    output_root = tmp_path / "research-output"
    (tmp_path / "canonical-manifest.json").write_text("manifest", encoding="utf-8")
    (tmp_path / "canonical-dataset.csv").write_text("dataset", encoding="utf-8")
    calls: list[tuple[str, str, int, int, str]] = []

    def fake_build_candidate(**kwargs):
        calls.append(
            (
                kwargs["stock_code"],
                kwargs["market"],
                kwargs["roc_year"],
                kwargs["season"],
                kwargs["run_id"],
            )
        )
        _write_fake_child(output_root, kwargs)
        target = output_root / kwargs["run_id"]
        candidate = target / "statement-pit-candidate.json"
        manifest = target / "run-manifest.json"
        return {"candidate": candidate, "manifest": manifest}

    monkeypatch.setattr(batch, "build_candidate", fake_build_candidate)
    manifest_path = tmp_path / "batch-manifest.json"
    assert batch.main(
        [
            "--request",
            "2330:sii:2026-Q2",
            "--request",
            "6488:otc:2026-Q2",
            "--output-root",
            str(output_root),
            "--batch-manifest",
            str(manifest_path),
            "--canonical-manifest",
            str(tmp_path / "canonical-manifest.json"),
            "--canonical-dataset",
            str(tmp_path / "canonical-dataset.csv"),
            "--max-companies",
            "2",
        ]
    ) == 0
    assert calls == [
        ("2330", "sii", 115, 2, "v4-quarterly-batch-sii-2330-2026q2"),
        ("6488", "otc", 115, 2, "v4-quarterly-batch-otc-6488-2026q2"),
    ]
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["request_count"] == 2
    assert [row["stock_code"] for row in payload["child_runs"]] == ["2330", "6488"]
    assert payload["status"] == "completed"
    assert all(row["candidate_sha256"].startswith("sha256:") for row in payload["child_runs"])
    assert payload["research_only"] is True


def test_batch_driver_binds_individual_report_basis_to_operation_and_child(
    tmp_path, monkeypatch
) -> None:
    output_root = tmp_path / "research-output"
    manifest_path = tmp_path / "batch-manifest.json"
    seen: list[str] = []

    def fake_build_candidate(**kwargs):
        seen.append(str(kwargs["report_basis"]))
        _write_fake_child(output_root, kwargs)
        target = output_root / kwargs["run_id"]
        return {
            "candidate": target / "statement-pit-candidate.json",
            "manifest": target / "run-manifest.json",
        }

    monkeypatch.setattr(batch, "build_candidate", fake_build_candidate)
    args = _batch_args(tmp_path, output_root, manifest_path, "1777:otc:2026-Q2")
    args.extend(["--report-basis", "individual"])
    assert batch.main(args) == 0
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert seen == ["individual"]
    assert payload["batch_identity"]["report_basis"] == "individual"
    assert payload["child_runs"][0]["report_basis"] == "individual"


def test_batch_driver_persists_partial_results_and_resume_retries_only_failed_child(
    tmp_path, monkeypatch
) -> None:
    output_root = tmp_path / "research-output"
    manifest_path = tmp_path / "batch-manifest.json"
    calls: list[str] = []
    should_fail = {"6488": True}

    def fake_build_candidate(**kwargs):
        calls.append(kwargs["stock_code"])
        if should_fail.get(kwargs["stock_code"], False):
            raise RuntimeError("company-specific validation failure")
        _write_fake_child(output_root, kwargs)
        target = output_root / kwargs["run_id"]
        return {
            "candidate": target / "statement-pit-candidate.json",
            "manifest": target / "run-manifest.json",
        }

    monkeypatch.setattr(batch, "build_candidate", fake_build_candidate)
    args = _batch_args(
        tmp_path,
        output_root,
        manifest_path,
        "2330:sii:2026-Q2",
        "6488:otc:2026-Q2",
        "5274:otc:2026-Q2",
    )
    assert batch.main(args) == 2
    partial = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert partial["status"] == "partial"
    assert partial["succeeded_count"] == 2
    assert partial["failed_count"] == 1
    failed = next(row for row in partial["child_runs"] if row["stock_code"] == "6488")
    assert failed["status"] == "failed"
    assert failed["attempts"][0]["error_type"] == "RuntimeError"
    assert "validation" in failed["attempts"][0]["error"]
    assert calls == ["2330", "6488", "5274"]

    should_fail["6488"] = False
    assert batch.main(_batch_args(
        tmp_path,
        output_root,
        manifest_path,
        "2330:sii:2026-Q2",
        "6488:otc:2026-Q2",
        "5274:otc:2026-Q2",
        resume=True,
    )) == 0
    completed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert completed["status"] == "completed"
    assert calls == ["2330", "6488", "5274", "6488"]
    assert all(row["status"] == "succeeded" for row in completed["child_runs"])
    assert len(next(row for row in completed["child_runs"] if row["stock_code"] == "6488")["attempts"]) == 2


def test_batch_driver_opens_source_circuit_and_resume_starts_new_transport_window(
    tmp_path, monkeypatch
) -> None:
    output_root = tmp_path / "research-output"
    manifest_path = tmp_path / "batch-manifest.json"
    calls: list[str] = []
    should_fail = {"value": True}

    def fake_build_candidate(**kwargs):
        calls.append(kwargs["stock_code"])
        if should_fail["value"]:
            raise RuntimeError(
                "HTTPSConnectionPool(host='doc.twse.com.tw'): NameResolutionError"
            )
        _write_fake_child(output_root, kwargs)
        target = output_root / kwargs["run_id"]
        return {
            "candidate": target / "statement-pit-candidate.json",
            "manifest": target / "run-manifest.json",
        }

    monkeypatch.setattr(batch, "build_candidate", fake_build_candidate)
    args = _batch_args(
        tmp_path,
        output_root,
        manifest_path,
        "2330:sii:2026-Q2",
        "6488:otc:2026-Q2",
        "5274:otc:2026-Q2",
    )
    args.extend(["--max-source-transport-failures", "1"])
    assert batch.main(args) == 2
    partial = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert calls == ["2330"]
    assert partial["source_failure_counts"] == {"doc.twse.com.tw": 1}
    assert partial["source_circuit_breakers"]["doc.twse.com.tw"]["failure_count"] == 1
    assert partial["source_failure_events"][0]["stock_code"] == "2330"
    assert partial["child_runs"][0]["attempts"][0]["failure_source"] == "doc.twse.com.tw"
    assert [row["status"] for row in partial["child_runs"]] == ["failed", "pending", "pending"]

    should_fail["value"] = False
    assert batch.main([*args, "--resume"]) == 0
    completed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert calls == ["2330", "2330", "6488", "5274"]
    assert completed["status"] == "completed"
    assert completed["source_circuit_reset_at"]


def test_batch_resume_rejects_different_requests_before_fetch(tmp_path, monkeypatch) -> None:
    output_root = tmp_path / "research-output"
    manifest_path = tmp_path / "batch-manifest.json"
    calls: list[str] = []

    def fake_build_candidate(**kwargs):
        calls.append(kwargs["stock_code"])
        _write_fake_child(output_root, kwargs)
        target = output_root / kwargs["run_id"]
        return {
            "candidate": target / "statement-pit-candidate.json",
            "manifest": target / "run-manifest.json",
        }

    monkeypatch.setattr(batch, "build_candidate", fake_build_candidate)
    first_args = _batch_args(tmp_path, output_root, manifest_path, "2330:sii:2026-Q2")
    assert batch.main(first_args) == 0
    with pytest.raises(ValueError, match="operation identity"):
        batch.main(_batch_args(
            tmp_path,
            output_root,
            manifest_path,
            "6488:otc:2026-Q2",
            resume=True,
        ))
    assert calls == ["2330"]


def test_batch_driver_rejects_more_than_explicit_limit_before_fetch(tmp_path) -> None:
    with pytest.raises(ValueError, match="batch limit"):
        batch.main(
            [
                "--request",
                "2330:sii:2026-Q2",
                "--request",
                "6488:otc:2026-Q2",
                "--output-root",
                str(tmp_path / "output"),
                "--batch-manifest",
                str(tmp_path / "batch.json"),
                "--canonical-manifest",
                str(tmp_path / "manifest.json"),
                "--canonical-dataset",
                str(tmp_path / "dataset.csv"),
                "--max-companies",
                "1",
            ]
        )


def test_batch_driver_passes_saved_official_listing_to_single_stock_fetcher(tmp_path, monkeypatch) -> None:
    output_root = tmp_path / "research-output"
    listing = tmp_path / "t57-2317.html"
    listing.write_bytes(b"official listing bytes")
    (tmp_path / "canonical-manifest.json").write_text("manifest", encoding="utf-8")
    (tmp_path / "canonical-dataset.csv").write_text("dataset", encoding="utf-8")
    seen: list[object] = []

    def fake_build_candidate(**kwargs):
        seen.append(kwargs["listing_response_path"])
        _write_fake_child(output_root, kwargs)
        target = output_root / kwargs["run_id"]
        return {
            "candidate": target / "statement-pit-candidate.json",
            "manifest": target / "run-manifest.json",
        }

    monkeypatch.setattr(batch, "build_candidate", fake_build_candidate)
    assert batch.main(
        [
            "--request",
            "2317:sii:2026-Q2",
            "--listing-raw",
            f"2317={listing}",
            "--output-root",
            str(output_root),
            "--batch-manifest",
            str(tmp_path / "batch.json"),
            "--canonical-manifest",
            str(tmp_path / "canonical-manifest.json"),
            "--canonical-dataset",
            str(tmp_path / "canonical-dataset.csv"),
        ]
    ) == 0
    assert seen == [listing.resolve()]


def test_batch_driver_passes_matching_listing_evidence_to_single_stock_fetcher(
    tmp_path, monkeypatch
) -> None:
    output_root = tmp_path / "research-output"
    listing = tmp_path / "t57-2317.html"
    evidence = tmp_path / "t57-2317-evidence.json"
    listing.write_bytes(b"official listing bytes")
    evidence.write_text("{}", encoding="utf-8")
    (tmp_path / "canonical-manifest.json").write_text("manifest", encoding="utf-8")
    (tmp_path / "canonical-dataset.csv").write_text("dataset", encoding="utf-8")
    seen: list[object] = []

    def fake_build_candidate(**kwargs):
        seen.append((kwargs["listing_response_path"], kwargs["listing_evidence_path"]))
        _write_fake_child(output_root, kwargs)
        target = output_root / kwargs["run_id"]
        return {
            "candidate": target / "statement-pit-candidate.json",
            "manifest": target / "run-manifest.json",
        }

    monkeypatch.setattr(batch, "build_candidate", fake_build_candidate)
    assert batch.main(
        [
            "--request",
            "2317:sii:2026-Q2",
            "--listing-raw",
            f"2317={listing}",
            "--listing-evidence",
            f"2317={evidence}",
            "--output-root",
            str(output_root),
            "--batch-manifest",
            str(tmp_path / "batch.json"),
            "--canonical-manifest",
            str(tmp_path / "canonical-manifest.json"),
            "--canonical-dataset",
            str(tmp_path / "canonical-dataset.csv"),
        ]
    ) == 0
    assert seen == [(listing.resolve(), evidence.resolve())]


def test_batch_driver_passes_matching_browser_listing_evidence_to_single_stock_fetcher(
    tmp_path, monkeypatch
) -> None:
    output_root = tmp_path / "research-output"
    listing = tmp_path / "t57-2881.html"
    evidence = tmp_path / "t57-2881-browser-evidence.json"
    listing.write_bytes(b"browser observed listing replay")
    evidence.write_text("{}", encoding="utf-8")
    (tmp_path / "canonical-manifest.json").write_text("manifest", encoding="utf-8")
    (tmp_path / "canonical-dataset.csv").write_text("dataset", encoding="utf-8")
    seen: list[object] = []

    def fake_build_candidate(**kwargs):
        seen.append(
            (
                kwargs["listing_response_path"],
                kwargs["listing_browser_evidence_path"],
            )
        )
        _write_fake_child(output_root, kwargs)
        target = output_root / kwargs["run_id"]
        return {
            "candidate": target / "statement-pit-candidate.json",
            "manifest": target / "run-manifest.json",
        }

    monkeypatch.setattr(batch, "build_candidate", fake_build_candidate)
    assert batch.main(
        [
            "--request",
            "2881:sii:2026-Q2",
            "--listing-raw",
            f"2881={listing}",
            "--listing-browser-evidence",
            f"2881={evidence}",
            "--output-root",
            str(output_root),
            "--batch-manifest",
            str(tmp_path / "batch.json"),
            "--canonical-manifest",
            str(tmp_path / "canonical-manifest.json"),
            "--canonical-dataset",
            str(tmp_path / "canonical-dataset.csv"),
        ]
    ) == 0
    assert seen == [(listing.resolve(), evidence.resolve())]
    payload = json.loads((tmp_path / "batch.json").read_text(encoding="utf-8"))
    browser_identity = payload["batch_identity"]["listing_browser_evidence_overrides"]["2881"]
    assert browser_identity["path"] == str(evidence.resolve())
    assert browser_identity["sha256"].startswith("sha256:")


def test_batch_driver_passes_saved_statement_raw_dir_to_single_stock_fetcher(
    tmp_path, monkeypatch
) -> None:
    output_root = tmp_path / "research-output"
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "t164.html").write_bytes(b"saved official response")
    (tmp_path / "canonical-manifest.json").write_text("manifest", encoding="utf-8")
    (tmp_path / "canonical-dataset.csv").write_text("dataset", encoding="utf-8")
    seen: list[object] = []

    def fake_build_candidate(**kwargs):
        seen.append(kwargs["statement_raw_dir"])
        _write_fake_child(output_root, kwargs)
        target = output_root / kwargs["run_id"]
        return {
            "candidate": target / "statement-pit-candidate.json",
            "manifest": target / "run-manifest.json",
        }

    monkeypatch.setattr(batch, "build_candidate", fake_build_candidate)
    assert batch.main(
        [
            "--request",
            "2317:sii:2026-Q2",
            "--statement-raw-dir",
            f"2317={raw_dir}",
            "--output-root",
            str(output_root),
            "--batch-manifest",
            str(tmp_path / "batch.json"),
            "--canonical-manifest",
            str(tmp_path / "canonical-manifest.json"),
            "--canonical-dataset",
            str(tmp_path / "canonical-dataset.csv"),
        ]
    ) == 0
    assert seen == [raw_dir.resolve()]


def test_batch_driver_passes_matching_xbrl_browser_dom_and_evidence(
    tmp_path, monkeypatch
) -> None:
    output_root = tmp_path / "research-output"
    dom = tmp_path / "xbrl-dom.html"
    evidence = tmp_path / "xbrl-evidence.json"
    dom.write_text("dom", encoding="utf-8")
    evidence.write_text("{}", encoding="utf-8")
    (tmp_path / "canonical-manifest.json").write_text("manifest", encoding="utf-8")
    (tmp_path / "canonical-dataset.csv").write_text("dataset", encoding="utf-8")
    seen: list[object] = []

    def fake_build_candidate(**kwargs):
        seen.append((kwargs["xbrl_browser_dom_path"], kwargs["xbrl_browser_evidence_path"]))
        _write_fake_child(output_root, kwargs)
        target = output_root / kwargs["run_id"]
        return {
            "candidate": target / "statement-pit-candidate.json",
            "manifest": target / "run-manifest.json",
        }

    monkeypatch.setattr(batch, "build_candidate", fake_build_candidate)
    assert batch.main(
        [
            "--request",
            "1240:otc:2026-Q2",
            "--xbrl-browser-dom",
            f"1240={dom}",
            "--xbrl-browser-evidence",
            f"1240={evidence}",
            "--output-root",
            str(output_root),
            "--batch-manifest",
            str(tmp_path / "batch.json"),
            "--canonical-manifest",
            str(tmp_path / "canonical-manifest.json"),
            "--canonical-dataset",
            str(tmp_path / "canonical-dataset.csv"),
        ]
    ) == 0
    assert seen == [(dom.resolve(), evidence.resolve())]
    payload = json.loads((tmp_path / "batch.json").read_text(encoding="utf-8"))
    assert payload["batch_identity"]["xbrl_browser_dom_overrides"]["1240"]["path"] == str(dom.resolve())
    assert payload["batch_identity"]["xbrl_browser_evidence_overrides"]["1240"]["path"] == str(evidence.resolve())


def test_batch_driver_honors_per_child_attempt_budget_across_resume(
    tmp_path, monkeypatch
) -> None:
    output_root = tmp_path / "research-output"
    manifest_path = tmp_path / "batch-manifest.json"
    calls: list[str] = []

    def always_fail(**kwargs):
        calls.append(kwargs["stock_code"])
        raise RuntimeError("bounded test failure")

    monkeypatch.setattr(batch, "build_candidate", always_fail)
    args = _batch_args(
        tmp_path,
        output_root,
        manifest_path,
        "2330:sii:2026-Q2",
    )
    args.extend(["--max-attempts-per-child", "2"])
    assert batch.main(args) == 2
    first = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert first["attempts_used"] == 1
    assert first["attempts_remaining"] == 1
    assert first["child_runs"][0].get("attempt_budget_exhausted") is not True

    assert batch.main([*args, "--resume"]) == 2
    second = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert second["attempts_used"] == 2
    assert len(second["child_runs"][0]["attempts"]) == 2
    assert calls == ["2330", "2330"]

    assert batch.main([*args, "--resume"]) == 2
    third = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert third["child_runs"][0]["attempt_budget_exhausted"] is True
    assert third["child_runs"][0]["remaining_attempts"] == 0
    assert calls == ["2330", "2330"]


def test_batch_driver_plan_mode_binds_plan_hash_and_requests(tmp_path, monkeypatch) -> None:
    registry = tmp_path / "companies.csv"
    registry.write_text(
        "industry_category,stock_id,stock_name,type,date,download_time\n"
        "水泥工業,1101,測試公司,twse,2026-08-10,2026-08-11 08:13:44\n",
        encoding="utf-8",
    )
    plan = build_universe_plan(
        registry_path=registry,
        period="2026-Q2",
        profile="continuation",
        selected=[("1101", "twse")],
    )
    plan_path = write_universe_plan(tmp_path / "universe-plan.json", plan)
    output_root = tmp_path / "research-output"
    manifest_path = tmp_path / "batch-manifest.json"
    (tmp_path / "canonical-manifest.json").write_text("manifest", encoding="utf-8")
    (tmp_path / "canonical-dataset.csv").write_text("dataset", encoding="utf-8")
    calls: list[str] = []

    def fake_build_candidate(**kwargs):
        calls.append(kwargs["stock_code"])
        _write_fake_child(output_root, kwargs)
        target = output_root / kwargs["run_id"]
        return {
            "candidate": target / "statement-pit-candidate.json",
            "manifest": target / "run-manifest.json",
        }

    monkeypatch.setattr(batch, "build_candidate", fake_build_candidate)
    assert batch.main(
        [
            "--universe-plan",
            str(plan_path),
            "--output-root",
            str(output_root),
            "--batch-manifest",
            str(manifest_path),
            "--canonical-manifest",
            str(tmp_path / "canonical-manifest.json"),
            "--canonical-dataset",
            str(tmp_path / "canonical-dataset.csv"),
        ]
    ) == 0
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert calls == ["1101"]
    assert payload["batch_identity"]["universe_plan"]["sha256"].startswith("sha256:")
    assert payload["batch_identity"]["universe_plan"]["sha256"] == batch._file_sha256_reference(plan_path)
