from scripts.validate_mops_quarterly_artifact import validate_artifact


def test_mops_artifact_requires_announcement_and_revision_parent() -> None:
    payload = {"source_id": "mops.statement.publication", "source_version": "mops-v1", "captured_at": "2026-07-18T00:00:00Z", "rows": [{"stock_code": "2330", "statement_type": "income_statement", "statement_scope": "consolidated", "period": "2026-Q1", "period_end": "2026-03-31", "announcement_date": "2026-05-10", "available_date": "2026-05-10", "revision": 1, "content_hash": "a" * 64}]}
    rows = validate_artifact(payload)
    assert rows[0]["evidence_tier"] == "official"
