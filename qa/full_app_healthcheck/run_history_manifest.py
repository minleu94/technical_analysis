from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES


ALLOWED_MODES = frozenset({"quick", "full", "partial", "closed-loop", "high-risk-dry-run"})
ALLOWED_STATUSES = frozenset({"passed", "failed", "skipped", "blocked", "manual-gap"})


@dataclass(frozen=True)
class SuiteRunRecord:
    suite_id: str
    status: str
    command: str
    duration_seconds: float | None
    evidence_path: str | None

    def __post_init__(self) -> None:
        if not self.suite_id:
            raise ValueError("suite_id is required.")
        if self.status not in ALLOWED_STATUSES:
            raise ValueError(f"Invalid status '{self.status}'. Allowed: {ALLOWED_STATUSES}")
        if not self.command:
            raise ValueError("command is required.")
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative.")


@dataclass(frozen=True)
class FeatureRunRecord:
    feature_id: str
    status: str
    route_mode: str
    evidence_summary: str

    def __post_init__(self) -> None:
        if self.feature_id not in FEATURE_ROUTES:
            raise ValueError(f"Unknown feature_id '{self.feature_id}'.")
        if self.status not in ALLOWED_STATUSES:
            raise ValueError(f"Invalid status '{self.status}'. Allowed: {ALLOWED_STATUSES}")
        if self.route_mode not in ALLOWED_MODES:
            raise ValueError(f"Invalid route_mode '{self.route_mode}'. Allowed: {ALLOWED_MODES}")
        if not self.evidence_summary:
            raise ValueError("evidence_summary is required.")


@dataclass(frozen=True)
class RunHistoryManifest:
    run_id: str
    commit: str
    mode: str
    viewport: str | None
    suite_results: tuple[SuiteRunRecord, ...]
    feature_results: tuple[FeatureRunRecord, ...]
    manual_gaps: tuple[str, ...]
    generated_at: str

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required.")
        if not self.commit:
            raise ValueError("commit is required.")
        if self.mode not in ALLOWED_MODES:
            raise ValueError(f"Invalid mode '{self.mode}'. Allowed: {ALLOWED_MODES}")
        if not self.generated_at:
            raise ValueError("generated_at is required.")

        for suite in self.suite_results:
            if not isinstance(suite, SuiteRunRecord):
                raise TypeError("All suite_results items must be SuiteRunRecord instances.")

        for feature in self.feature_results:
            if not isinstance(feature, FeatureRunRecord):
                raise TypeError("All feature_results items must be FeatureRunRecord instances.")


def build_run_history_manifest(
    *,
    run_id: str,
    commit: str,
    mode: str,
    viewport: str | None,
    suite_results: Sequence[SuiteRunRecord],
    feature_results: Sequence[FeatureRunRecord],
    manual_gaps: Sequence[str],
    generated_at: str,
) -> RunHistoryManifest:
    return RunHistoryManifest(
        run_id=run_id,
        commit=commit,
        mode=mode,
        viewport=viewport,
        suite_results=tuple(suite_results),
        feature_results=tuple(feature_results),
        manual_gaps=tuple(manual_gaps),
        generated_at=generated_at,
    )


def render_run_history_manifest_markdown(manifest: RunHistoryManifest) -> str:
    """將 RunHistoryManifest 渲染為 Markdown 格式。"""
    viewport_str = manifest.viewport if manifest.viewport else "N/A"

    lines = [
        f"# Run History Manifest - `{manifest.run_id}`",
        "",
        f"- **Commit**: `{manifest.commit}`",
        f"- **Mode**: `{manifest.mode}`",
        f"- **Viewport**: `{viewport_str}`",
        f"- **Generated At**: `{manifest.generated_at}`",
        "",
        "## Suite Results Summary",
        "",
        "| Suite ID | Status | Command | Duration (s) | Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for suite in manifest.suite_results:
        duration = f"{suite.duration_seconds:.2f}" if suite.duration_seconds is not None else "N/A"
        evidence = f"`{suite.evidence_path}`" if suite.evidence_path else "N/A"
        lines.append(f"| `{suite.suite_id}` | `{suite.status}` | `{suite.command}` | {duration} | {evidence} |")

    lines.extend(
        [
            "",
            "## Feature Results Summary",
            "",
            "| Feature ID | Status | Route Mode | Evidence Summary |",
            "| --- | --- | --- | --- |",
        ]
    )
    for feature in manifest.feature_results:
        lines.append(
            f"| `{feature.feature_id}` | `{feature.status}` | `{feature.route_mode}` | "
            f"{feature.evidence_summary} |"
        )

    lines.extend(["", "## Manual Gaps", ""])
    if manifest.manual_gaps:
        for gap in manifest.manual_gaps:
            lines.append(f"- {gap}")
    else:
        lines.append("- (None)")

    return "\n".join(lines)
