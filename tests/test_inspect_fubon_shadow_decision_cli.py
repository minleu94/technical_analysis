import json
from pathlib import Path
import tempfile
import pytest

from scripts.inspect_fubon_shadow_decision import main, validate_output_root


def test_cli_stdout_execution(tmp_path: Path) -> None:
    obs_file = tmp_path / "obs.json"
    obs_file.write_text(json.dumps([{"symbol": "2330", "available_at": "2026-07-25T00:00:00+00:00", "quantities": {"is_disposition": 1}}]), encoding="utf-8")
    universe_file = tmp_path / "universe.json"
    universe_file.write_text(json.dumps([{"股票代號": "2330", "證券名稱": "台積電", "收盤價": 1000.0, "TotalScore": 85.0, "FinalScore": 85.0}]), encoding="utf-8")
    strategy_file = tmp_path / "strategy.json"
    strategy_file.write_text(
        json.dumps(
            {
                "filters": {
                    "pe_ratio_max": 999,
                    "monthly_revenue_yoy_min": -100,
                },
                "signals": {
                    "weights": {
                        "pattern": 3000,
                        "technical": 5000,
                        "volume": 2000,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--input",
            str(obs_file),
            "--universe",
            str(universe_file),
            "--strategy-config",
            str(strategy_file),
            "--decision-timestamp",
            "2026-07-26T00:00:00+00:00",
        ]
    )
    assert exit_code == 0


def test_cli_fails_closed_when_input_or_universe_missing() -> None:
    exit_code = main(["--decision-timestamp", "2026-07-26T00:00:00+00:00"])
    assert exit_code == 1


def test_cli_rejects_unsafe_output_root() -> None:
    data_root = Path("D:/Min/Python/Project/FA_Data").resolve()
    with pytest.raises(ValueError, match="output_root cannot be inside formal data root"):
        validate_output_root(data_root)


def test_cli_accepts_temp_output_root() -> None:
    temp_dir = Path(tempfile.gettempdir()) / "technical_analysis_fubon_shadow_test"
    temp_dir.mkdir(parents=True, exist_ok=True)
    validated = validate_output_root(temp_dir)
    assert validated == temp_dir.resolve()
