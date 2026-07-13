import json
from pathlib import Path

from scripts.verify_gate_2_to_7_closeout import main


def test_cli_emits_separate_engineering_and_external_status(tmp_path: Path) -> None:
    output = tmp_path / "closeout.json"
    assert main(["--output", str(output)]) in {0, 1}
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "engineering_package_status" in payload
    assert "external_validation_status" in payload
    assert payload["formal_product_closeout"] is False
