from scripts.validate_mops_quarterly_artifact import validate_artifact


def _sha256_reference(seed: str) -> str:
    return f"sha256:{seed * 64}"[:71]


def test_mops_artifact_requires_announcement_and_revision_parent() -> None:
    payload = {"source_id": "mops.statement.publication", "source_version": "mops-v1", "captured_at": "2026-07-18T00:00:00Z", "rows": [{"stock_code": "2330", "statement_type": "income_statement", "statement_scope": "consolidated", "period": "2026-Q1", "period_end": "2026-03-31", "announcement_date": "2026-05-10", "available_date": "2026-05-10", "revision": 1, "content_hash": "a" * 64}]}
    rows = validate_artifact(payload)
    assert rows[0]["evidence_tier"] == "research_candidate"
    assert rows[0]["source_id"] == "pit.quarterly_financials"
    assert rows[0]["artifact_source_id"] == "mops.statement.publication"
    assert rows[0]["source_contract_mapping_version"] == "p0-candidate-source-alignment.v1"


def test_individual_artifact_must_declare_matching_report_scope() -> None:
    payload = {
        "source_id": "mops.statement.publication",
        "source_version": "mops-t164-individual-v1",
        "captured_at": "2026-09-07T16:10:55Z",
        "report_basis": "individual",
        "rows": [{
            "stock_code": "1777",
            "statement_type": "income_statement",
            "statement_scope": "individual",
            "report_basis": "individual",
            "period": "2026-Q2",
            "period_end": "2026-06-30",
            "announcement_date": "2026-08-06",
            "available_date": "2026-09-09",
            "revision": 1,
            "content_hash": "a" * 64,
        }],
    }
    assert validate_artifact(payload)[0]["report_basis"] == "individual"


def test_numeric_pit_claim_requires_separate_raw_and_availability_lineage() -> None:
    payload = {
        "source_id": "mops.statement.publication",
        "source_version": "mops-v1",
        "captured_at": "2026-07-18T00:00:00Z",
        "pit_coverage_summary": {"numeric_pit_ratios_supplied": True},
        "rows": [{
            "stock_code": "2330", "statement_type": "income_statement", "statement_scope": "consolidated",
            "period": "2026-Q1", "period_end": "2026-03-31", "announcement_date": "2026-05-10T10:00:00+08:00",
            "available_date": "2026-05-11", "revision": 1, "content_hash": "a" * 64,
            "publication_timestamp": "2026-05-10T10:00:00+08:00",
            "numeric_source_row_sha256": _sha256_reference("a"),
            "availability_event_sha256": _sha256_reference("b"),
            "statement_items": {"roe_bp": 1234},
        }],
    }

    try:
        validate_artifact(payload)
    except ValueError as exc:
        assert str(exc) == "numeric PIT claim missing raw numeric and canonical-dataset lineage"
    else:
        raise AssertionError("numeric PIT claim without raw-source lineage must fail closed")


def test_numeric_pit_claim_with_immutable_lineage_is_research_candidate() -> None:
    payload = {
        "source_id": "mops.statement.publication",
        "source_version": "mops-v1",
        "captured_at": "2026-07-18T00:00:00Z",
        "pit_coverage_summary": {"numeric_pit_ratios_supplied": True},
        "lineage": {
            "numeric_statement_source": {
                "source_id": "mops.financial_statement.raw",
                "source_version": "mops-financial-statement.v1",
                "artifact_sha256": _sha256_reference("c"),
            },
            "availability_artifact_sha256": _sha256_reference("d"),
            "canonical_dataset_lineage": {
                "manifest_sha256": _sha256_reference("e"),
                "dataset_sha256": _sha256_reference("f"),
            },
        },
        "rows": [{
            "stock_code": "2330", "statement_type": "income_statement", "statement_scope": "consolidated",
            "period": "2026-Q1", "period_end": "2026-03-31", "announcement_date": "2026-05-10T10:00:00+08:00",
            "available_date": "2026-05-11", "revision": 1, "content_hash": "a" * 64,
            "publication_timestamp": "2026-05-10T10:00:00+08:00",
            "numeric_source_row_sha256": _sha256_reference("a"),
            "availability_event_sha256": _sha256_reference("b"),
            "statement_items": {"roe_bp": 1234, "eps_cents": 567},
        }],
    }

    rows = validate_artifact(payload)
    assert rows[0]["evidence_tier"] == "research_candidate"
    assert rows[0]["source_id"] == "pit.quarterly_financials"
    assert rows[0]["artifact_source_id"] == "mops.statement.publication"
