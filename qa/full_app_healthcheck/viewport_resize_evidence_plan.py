from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES


FORBIDDEN_VIEWPORT_RESIZE_ACTIONS = frozenset(
    {
        "data write",
        "database write",
        "migration",
        "backfill apply",
        "external fetch",
        "network update",
        "high-risk dry-run",
        "bridge execution",
        "live window show",
        "mainwindow execution",
        "real widget resize",
        "screenshot creation",
    }
)

VALID_VIEWPORT_SIZES = frozenset(
    {
        "1366x768",
        "1440x900",
        "1920x1080",
    }
)


@dataclass(frozen=True)
class ViewportResizeEvidencePlan:
    evidence_id: str
    feature_id: str
    purpose: str
    viewport_sizes: tuple[str, ...]
    allowed_observations: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    non_destructive: bool
    requires_explicit_user_confirmation: bool = True

    def __post_init__(self) -> None:
        if self.feature_id not in FEATURE_ROUTES:
            raise ValueError(f"Unknown feature_id '{self.feature_id}' for evidence plan '{self.evidence_id}'.")
        if not self.non_destructive:
            raise ValueError(f"Evidence plan '{self.evidence_id}' must be non-destructive.")
        if not self.requires_explicit_user_confirmation:
            raise ValueError(f"Evidence plan '{self.evidence_id}' must require explicit user confirmation.")
        if not self.allowed_observations:
            raise ValueError(f"Evidence plan '{self.evidence_id}' must describe allowed observations.")
        if not self.forbidden_actions:
            raise ValueError(f"Evidence plan '{self.evidence_id}' must describe forbidden actions.")
        if not self.viewport_sizes:
            raise ValueError(f"Evidence plan '{self.evidence_id}' must describe viewport sizes.")

        # Check viewport sizes
        for size in self.viewport_sizes:
            if size not in VALID_VIEWPORT_SIZES:
                raise ValueError(f"Invalid viewport size '{size}'. Allowed: {VALID_VIEWPORT_SIZES}")

        # Check forbidden actions
        forbidden_text = " ".join(self.forbidden_actions).lower()
        for forbidden_action in FORBIDDEN_VIEWPORT_RESIZE_ACTIONS:
            if forbidden_action not in forbidden_text:
                raise ValueError(
                    f"Evidence plan '{self.evidence_id}' must explicitly forbid '{forbidden_action}'."
                )


COMMON_FORBIDDEN_ACTIONS = tuple(sorted(FORBIDDEN_VIEWPORT_RESIZE_ACTIONS))

VIEWPORT_RESIZE_EVIDENCE_PLAN: tuple[ViewportResizeEvidencePlan, ...] = (
    ViewportResizeEvidencePlan(
        evidence_id="update_view_viewport_evidence",
        feature_id="update_view",
        purpose="Plan offscreen viewport observations at various sizes to check update view table stretching.",
        viewport_sizes=("1366x768", "1440x900", "1920x1080"),
        allowed_observations=(
            "Inspect columns table headers auto-wrap state",
            "Ensure update status labels are not occluded at 1366x768",
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS,
        non_destructive=True,
    ),
    ViewportResizeEvidencePlan(
        evidence_id="decision_desk_viewport_evidence",
        feature_id="decision_desk",
        purpose="Plan offscreen viewport observations for Daily Decision Desk dashboard grid layouts.",
        viewport_sizes=("1366x768", "1440x900", "1920x1080"),
        allowed_observations=(
            "Inspect sector focus cards wrapping and spacing",
            "Verify risk warning layout at 1920x1080",
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS,
        non_destructive=True,
    ),
)


def get_viewport_resize_evidence_plan() -> tuple[ViewportResizeEvidencePlan, ...]:
    """取得所有內建的 Viewport / resize 驗收計畫。"""
    return VIEWPORT_RESIZE_EVIDENCE_PLAN


def get_viewport_resize_evidence_plan_for_feature(feature_id: str) -> tuple[ViewportResizeEvidencePlan, ...]:
    """取得特定 feature_id 的 ViewportResizeEvidencePlan 列表。"""
    return tuple(plan for plan in VIEWPORT_RESIZE_EVIDENCE_PLAN if plan.feature_id == feature_id)


def render_viewport_resize_evidence_plan_markdown(plans: Sequence[ViewportResizeEvidencePlan]) -> str:
    """將 ViewportResizeEvidencePlan 列表渲染為 Markdown 格式。"""
    if not plans:
        return "- (None)"

    lines = [
        "> D-3 is plan-only metadata. Do not execute MainWindow, create screenshots, or resize widgets from unit tests."
    ]
    for plan in plans:
        sizes = ", ".join(f"`{size}`" for size in plan.viewport_sizes)
        observations = ", ".join(f"`{item}`" for item in plan.allowed_observations)
        forbidden = ", ".join(f"`{item}`" for item in plan.forbidden_actions)
        lines.append(
            f"- **Evidence ID**: `{plan.evidence_id}` (Feature: `{plan.feature_id}`, Viewports: {sizes})\n"
            f"  - *Purpose*: {plan.purpose}\n"
            f"  - *Allowed Observations*: {observations}\n"
            f"  - *Forbidden Actions*: {forbidden}\n"
            f"  - *Requires Explicit Confirmation*: `{plan.requires_explicit_user_confirmation}`"
        )
    return "\n".join(lines)
