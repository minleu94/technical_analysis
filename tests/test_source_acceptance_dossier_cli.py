import json
from pathlib import Path

from scripts.build_source_acceptance_dossier import main


def test_cli_builds_read_only_deferred_dossier_projection(tmp_path: Path) -> None:
    source = tmp_path / "dossier.json"
    output = tmp_path / "projection.json"
    source.write_text(
        json.dumps(
            {
                "source_id": "institutional_flows",
                "source_owner_role": "Data Source Owner",
                "license_owner_role": "License/Legal Owner",
                "license_status": "requires_review",
                "license_scope": "not_decided",
                "redistribution_policy": "not_decided",
                "source_status": "candidate",
                "publication_time_policy": "unverified",
                "timezone": "Asia/Taipei",
                "available_date_policy": "unverified",
                "revision_policy": "unverified",
                "pit_coverage_window": "unverified",
                "coverage_numerator": 10,
                "coverage_denominator": 10,
                "missing_policy": "fail_closed",
                "row_conservation_counts": {"raw": 10},
                "quarantine_policy": "unverified",
                "quality_thresholds": {},
                "downstream_use_cases": ["research"],
                "disable_conditions": ["license_not_accepted"],
                "rollback_reference": "decision:future-disable-revision",
                "evidence_artifact_ids": ["http:200", "parser:passed"],
            }
        ),
        encoding="utf-8",
    )

    assert main(["--input", str(source), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["candidate_only"] is True
    assert "decision" not in payload
    assert payload["read_only"] is True
    assert payload["formal_oos_allowed"] is False
    assert payload["production_blend_alpha_bp"] == 0


def test_cli_rejects_output_under_the_configured_production_data_root(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "dossier.json"
    source.write_text("{}", encoding="utf-8")
    production_root = tmp_path / "FA_Data"
    monkeypatch.setenv("DATA_ROOT", str(production_root))

    try:
        main(["--input", str(source), "--output", str(production_root / "result.json")])
    except ValueError as error:
        assert "non-production" in str(error)
    else:
        raise AssertionError("production-root output must be rejected")
