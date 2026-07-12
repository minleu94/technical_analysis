from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ALL = [
    "RecommendationService",
    "ScreeningService",
    "RegimeService",
    "UpdateService",
    "BacktestService",
    "PortfolioService",
    "JournalService",
    "RecommendationDTO",
    "RecommendationResultDTO",
    "RegimeResultDTO",
    "BacktestReportDTO",
]


def test_update_service_package_import_contract_is_stable_in_fresh_interpreter():
    witness_script = """
import json
import sys

try:
    import app_module.update_service as update_service
    import app_module
except Exception as exc:
    print(json.dumps({"exception": type(exc).__name__, "message": str(exc)}))
    raise

loaded = sorted(name for name in sys.modules if name.startswith("app_module."))
print(
    json.dumps(
        {
            "update_service_module": update_service.UpdateService.__module__,
            "identity": app_module.UpdateService is update_service.UpdateService,
            "all": list(app_module.__all__),
            "loaded_service_modules": [
                name
                for name in loaded
                if name in {"app_module.update_service", "app_module.backtest_service"}
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
)
"""

    result = subprocess.run(
        [sys.executable, "-c", witness_script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "update_service_module": "app_module.update_service",
        "identity": True,
        "all": EXPECTED_ALL,
        "loaded_service_modules": [
            "app_module.backtest_service",
            "app_module.update_service",
        ],
    }
