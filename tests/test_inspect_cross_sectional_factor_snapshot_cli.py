from __future__ import annotations

from datetime import date
import json

from app_module.cross_sectional_factor_dtos import (
    CrossSectionalFactorRow,
    CrossSectionalFactorSnapshot,
)
from app_module.cross_sectional_factor_repository import CrossSectionalFactorRepository
from decision_module.factors.factor_dtos import FactorQuality, MissingPolicy
from scripts.inspect_cross_sectional_factor_snapshot import main


def test_cli_outputs_latest_json_summary(tmp_path, capsys):
    db_path = tmp_path / "factors.db"
    repository = CrossSectionalFactorRepository(db_path)
    repository.save_snapshot(
        CrossSectionalFactorSnapshot(
            snapshot_id="csf_20260705_test",
            decision_date=date(2026, 7, 5),
            factor_set_version="v1.6-test",
            universe_id="test-universe",
            source_version="unit-test",
            rows=(
                CrossSectionalFactorRow(
                    row_id="row-1",
                    stock_code="2330",
                    factor_name="technical.total_score",
                    as_of_date=date(2026, 7, 4),
                    available_date=date(2026, 7, 5),
                    value="80",
                    score_bp=8000,
                    rank=1,
                    quantile_bp=10000,
                    universe_size=1,
                    quality=FactorQuality.OBSERVED,
                    missing_policy=MissingPolicy.FAIL_CLOSED,
                    source_version="technical-v1",
                ),
            ),
        )
    )

    exit_code = main(["--db-path", str(db_path), "--latest", "--json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["snapshot_id"] == "csf_20260705_test"
    assert output["row_count"] == 1


def test_cli_missing_db_does_not_create_file(tmp_path, capsys):
    db_path = tmp_path / "missing.db"

    exit_code = main(["--db-path", str(db_path), "--latest", "--json"])

    assert exit_code == 2
    assert not db_path.exists()
    assert "db_path_missing" in capsys.readouterr().err
