import json
from pathlib import Path

import pytest

from scripts.plan_mops_statement_universe import (
    _sha256_reference,
    build_universe_plan,
    validate_universe_plan,
    write_universe_plan,
)


_FIELDS = (
    "industry_category",
    "stock_id",
    "stock_name",
    "type",
    "date",
    "download_time",
)


def _write_registry(path: Path) -> Path:
    path.write_text(
        "industry_category,stock_id,stock_name,type,date,download_time\n"
        "金融保險,2881,富邦金,twse,2026-08-10,2026-08-11 08:13:44\n"
        "水泥工業,1101,台泥,twse,2026-08-10,2026-08-11 08:13:44\n"
        "塑膠工業,1301,台塑,twse,2026-08-10,2026-08-11 08:13:44\n"
        "航運業,2603,長榮,twse,2026-08-10,2026-08-11 08:13:44\n"
        "半導體業,3105,穩懋,tpex,2026-08-10,2026-08-11 08:13:44\n"
        "文化創意業,3293,鈊象,tpex,2026-08-10,2026-08-11 08:13:44\n"
        "生技醫療業,6547,高端疫苗,tpex,2026-08-10,2026-08-11 08:13:44\n"
        "存託憑證,9103,美德醫療-DR,twse,2026-08-10,2026-08-11 08:13:44\n"
        "食品工業,1001,測試新興,emerging,2026-08-10,2026-08-11 08:13:44\n",
        encoding="utf-8",
    )
    return path


def _write_child_manifest(root: Path, stock_code: str, market: str) -> Path:
    child = root / f"child-{stock_code}"
    child.mkdir()
    candidate = child / "statement-pit-candidate.json"
    period = "2026-Q2"
    candidate.write_text(
        json.dumps(
            {
                "schema_version": "mops-statement-pit-candidate.v1",
                "source_version": "test-source-v1",
                "research_only": True,
                "formal_oos_allowed": False,
                "rows": [
                    {"stock_code": stock_code, "market": market, "period": period}
                ],
                "pit_coverage_summary": {
                    "stock_code": stock_code,
                    "market_request": market,
                    "period": period,
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = child / "run-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "mops-statement-pit-run-manifest.v1",
                "run_id": f"test-{stock_code}",
                "files": {"candidate": _sha256_reference(candidate)},
                "research_only": True,
                "formal_oos_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_representative_profile_keeps_initial_coverage_requirements(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path / "companies.csv")
    payload = build_universe_plan(
        registry_path=registry,
        period="2026-Q2",
        profile="representative_initial",
        selected=[
            ("2881", "twse"),
            ("1101", "twse"),
            ("3105", "tpex"),
            ("3293", "tpex"),
        ],
        minimum_distinct_industries=4,
    )
    assert payload["scope"]["selected_company_count"] == 4
    assert payload["scope"]["selected_industry_count"] == 4
    assert payload["scope"]["registry_markets"] == ["tpex", "twse"]
    assert payload["selection_policy"]["representative_requirements"]["stock_code"] == "2881"

    with pytest.raises(ValueError, match="both TWSE and TPEx"):
        build_universe_plan(
            registry_path=registry,
            period="2026-Q2",
            profile="representative_initial",
            selected=[("2881", "twse"), ("1101", "twse")],
        )


def test_continuation_auto_selection_does_not_force_2881_or_two_markets(
    tmp_path: Path,
) -> None:
    registry = _write_registry(tmp_path / "companies.csv")
    payload = build_universe_plan(
        registry_path=registry,
        period="2026-Q2",
        profile="continuation",
        verified_completed=[("2881", "twse"), ("3105", "tpex")],
        caller_excluded=[("1101", "twse")],
        max_selected_companies=2,
    )
    selected = payload["selected_companies"]
    assert [record["request"] for record in selected] == [
        "3293:otc:2026-Q2",
        "6547:otc:2026-Q2",
    ]
    assert payload["scope"]["registry_markets"] == ["tpex"]
    assert payload["scope"]["verified_completed_company_count"] == 2
    assert payload["scope"]["caller_excluded_company_count"] == 1
    assert payload["scope"]["unprocessed_eligible_company_count"] == 5
    assert payload["scope"]["deferred_unresolved_company_count"] == 1
    assert payload["scope"]["total_unfinished_company_count"] == 5
    assert payload["eligible_rows"][
        next(i for i, row in enumerate(payload["eligible_rows"]) if row["stock_code"] == "1101")
    ]["caller_excluded"] is True


def test_continuation_can_finish_single_market_tail(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path / "companies.csv")
    all_tpex = [("3105", "tpex"), ("3293", "tpex"), ("6547", "tpex")]
    payload = build_universe_plan(
        registry_path=registry,
        period="2026-Q2",
        profile="continuation",
        verified_completed=all_tpex,
        caller_excluded=[("2881", "twse"), ("1101", "twse"), ("1301", "twse")],
    )
    assert payload["scope"]["registry_markets"] == ["twse"]
    assert all(record["registry_market"] == "twse" for record in payload["selected_companies"])
    assert all(record["stock_code"] != "2881" for record in payload["selected_companies"])


def test_verified_artifact_binds_completion_to_candidate_hash(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path / "companies.csv")
    child_manifest = _write_child_manifest(tmp_path, "2881", "sii")
    payload = build_universe_plan(
        registry_path=registry,
        period="2026-Q2",
        profile="continuation",
        verified_artifacts=[child_manifest],
        max_selected_companies=2,
    )
    assert payload["scope"]["verified_completed_company_count"] == 1
    assert payload["verified_completed_keys"] == ["2881:twse"]
    assert payload["verified_completed_artifacts"][0]["candidate_sha256"].startswith("sha256:")
    assert all(record["stock_code"] != "2881" for record in payload["selected_companies"])

    candidate = child_manifest.parent / "statement-pit-candidate.json"
    candidate.write_text(candidate.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        build_universe_plan(
            registry_path=registry,
            period="2026-Q2",
            profile="continuation",
            verified_artifacts=[child_manifest],
        )


def test_plan_round_trip_and_caller_exclusion_is_not_completion(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path / "companies.csv")
    payload = build_universe_plan(
        registry_path=registry,
        period="2026-Q2",
        profile="continuation",
        caller_excluded=[("2881", "twse")],
        max_selected_companies=1,
    )
    output = write_universe_plan(tmp_path / "plan.json", payload)
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert validate_universe_plan(loaded)["plan_id"] == payload["plan_id"]
    assert loaded["scope"]["verified_completed_company_count"] == 0
    assert loaded["scope"]["caller_excluded_company_count"] == 1
    loaded["requests"][0] = "2881:sii:2026-Q2"
    with pytest.raises(ValueError, match="content hash mismatch"):
        validate_universe_plan(loaded)


def test_supersession_record_replaces_old_immutable_completion(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path / "companies.csv")
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    old_manifest = _write_child_manifest(old_root, "2881", "sii")
    new_manifest = _write_child_manifest(new_root, "2881", "sii")
    new_candidate = new_manifest.parent / "statement-pit-candidate.json"
    new_payload = json.loads(new_candidate.read_text(encoding="utf-8"))
    new_payload["source_version"] = "replacement-source-v2"
    new_candidate.write_text(json.dumps(new_payload), encoding="utf-8")
    new_manifest_payload = json.loads(new_manifest.read_text(encoding="utf-8"))
    new_manifest_payload["files"]["candidate"] = _sha256_reference(new_candidate)
    new_manifest.write_text(json.dumps(new_manifest_payload), encoding="utf-8")

    old_candidate = old_manifest.parent / "statement-pit-candidate.json"
    correction = tmp_path / "correction.json"
    correction.write_text(
        json.dumps(
            {
                "schema_version": "mops-statement-artifact-correction.v1",
                "research_only": True,
                "formal_oos_allowed": False,
                "status": "accepted_replacement",
                "target": {
                    "stock_code": "2881",
                    "registry_market": "twse",
                    "batch_market": "sii",
                    "period": "2026-Q2",
                    "report_basis": "consolidated",
                },
                "superseded": {
                    "candidate_path": str(old_candidate),
                    "candidate_sha256": _sha256_reference(old_candidate),
                    "manifest_path": str(old_manifest),
                    "manifest_sha256": _sha256_reference(old_manifest),
                },
                "replacement": {
                    "candidate_path": str(new_candidate),
                    "candidate_sha256": _sha256_reference(new_candidate),
                    "manifest_path": str(new_manifest),
                    "manifest_sha256": _sha256_reference(new_manifest),
                },
                "reason": "strict replacement fixture",
            }
        ),
        encoding="utf-8",
    )

    payload = build_universe_plan(
        registry_path=registry,
        period="2026-Q2",
        profile="continuation",
        verified_artifacts=[old_manifest],
        supersession_records=[correction],
        max_selected_companies=2,
    )
    assert validate_universe_plan(payload)["scope"][
        "verified_completed_company_count"
    ] == 1
    references = payload["verified_completed_artifacts"]
    assert not any(
        reference.get("candidate_sha256") == _sha256_reference(old_candidate)
        for reference in references
    )
    replacement_reference = next(
        reference
        for reference in references
        if reference.get("artifact_kind") == "supersession_record"
    )
    assert replacement_reference["candidate_sha256"] == _sha256_reference(new_candidate)
    assert payload["supersession_records"] == [replacement_reference]
    assert "2881:twse" in payload["verified_completed_keys"]
