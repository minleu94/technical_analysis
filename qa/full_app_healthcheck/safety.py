from __future__ import annotations

from qa.full_app_healthcheck.manifest import HealthcheckManifest, RiskLevel


FORBIDDEN_NON_DESTRUCTIVE_RISKS = {
    RiskLevel.WRITES_DATA,
    RiskLevel.DESTRUCTIVE,
}


def validate_non_destructive_manifest(manifest: HealthcheckManifest) -> None:
    blocked = [
        step
        for step in manifest.steps
        if step.risk in FORBIDDEN_NON_DESTRUCTIVE_RISKS
    ]
    if blocked:
        ids = ", ".join(step.id for step in blocked)
        raise ValueError(f"非破壞模式禁止包含會寫資料或破壞資料的 step: {ids}")
