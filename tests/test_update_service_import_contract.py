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
EXPECTED_EAGER_SERVICE_MODULES = [
    "app_module.recommendation_service",
    "app_module.screening_service",
    "app_module.regime_service",
    "app_module.update_service",
    "app_module.backtest_service",
    "app_module.portfolio_service",
    "app_module.journal_service",
]
EXPECTED_SERVICE_CLASS_MODULES = {
    "RecommendationService": "app_module.recommendation_service",
    "ScreeningService": "app_module.screening_service",
    "RegimeService": "app_module.regime_service",
    "UpdateService": "app_module.update_service",
    "BacktestService": "app_module.backtest_service",
    "PortfolioService": "app_module.portfolio_service",
    "JournalService": "app_module.journal_service",
}


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

loaded = [name for name in sys.modules if name.startswith("app_module.")]
print(
    json.dumps(
        {
            "update_service_module": update_service.UpdateService.__module__,
            "identity": app_module.UpdateService is update_service.UpdateService,
            "all": list(app_module.__all__),
            "loaded_service_modules": [
                name
                for name in loaded
                if name in {
                    "app_module.recommendation_service",
                    "app_module.screening_service",
                    "app_module.regime_service",
                    "app_module.update_service",
                    "app_module.backtest_service",
                    "app_module.portfolio_service",
                    "app_module.journal_service",
                }
            ],
            "service_class_modules": {
                class_name: getattr(app_module, class_name).__module__
                for class_name in [
                    "RecommendationService",
                    "ScreeningService",
                    "RegimeService",
                    "UpdateService",
                    "BacktestService",
                    "PortfolioService",
                    "JournalService",
                ]
            },
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
        "loaded_service_modules": EXPECTED_EAGER_SERVICE_MODULES,
        "service_class_modules": EXPECTED_SERVICE_CLASS_MODULES,
    }
