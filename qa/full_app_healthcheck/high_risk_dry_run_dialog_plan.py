from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES


REQUIRED_FORBIDDEN_ACTIONS = frozenset(
    {
        "confirm/apply click",
        "data write",
        "database write",
        "migration",
        "backfill apply",
        "external fetch",
        "network update",
        "high-risk dry-run execution",
        "service invocation",
        "mainwindow execution",
        "bridge execution",
    }
)


@dataclass(frozen=True)
class HighRiskDryRunDialogPlan:
    plan_id: str
    feature_id: str
    purpose: str
    target_dialog_name: str
    allowed_observations: tuple[str, ...]
    cancel_path_observations: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    non_destructive: bool
    requires_explicit_user_confirmation: bool = True
    requires_cancel_path: bool = True
    mock_service_not_called: bool = True

    def __post_init__(self) -> None:
        if self.feature_id not in FEATURE_ROUTES:
            raise ValueError(f"Unknown feature_id '{self.feature_id}' for dialog plan '{self.plan_id}'.")
        if not self.non_destructive:
            raise ValueError(f"Dialog plan '{self.plan_id}' must be non-destructive.")
        if not self.requires_explicit_user_confirmation:
            raise ValueError(f"Dialog plan '{self.plan_id}' must require explicit user confirmation.")
        if not self.requires_cancel_path:
            raise ValueError(f"Dialog plan '{self.plan_id}' must require a cancel path.")
        if not self.mock_service_not_called:
            raise ValueError(f"Dialog plan '{self.plan_id}' must guarantee mock_service_not_called.")
        if not self.allowed_observations:
            raise ValueError(f"Dialog plan '{self.plan_id}' must describe allowed observations.")
        if not self.cancel_path_observations:
            raise ValueError(f"Dialog plan '{self.plan_id}' must describe cancel path observations.")
        if not self.forbidden_actions:
            raise ValueError(f"Dialog plan '{self.plan_id}' must describe forbidden actions.")

        # Check forbidden actions
        forbidden_text = " ".join(self.forbidden_actions).lower()
        for action in REQUIRED_FORBIDDEN_ACTIONS:
            if action not in forbidden_text:
                raise ValueError(f"Dialog plan '{self.plan_id}' must explicitly forbid '{action}'.")


COMMON_FORBIDDEN_ACTIONS = tuple(sorted(REQUIRED_FORBIDDEN_ACTIONS))

HIGH_RISK_DRY_RUN_DIALOG_PLAN: tuple[HighRiskDryRunDialogPlan, ...] = (
    HighRiskDryRunDialogPlan(
        plan_id="sqlite_sync_confirm_dialog_plan",
        feature_id="update_view",
        purpose="Plan dry-run dialog observations for SQLite daily price data sync confirmation.",
        target_dialog_name="SyncConfirmDialog",
        allowed_observations=(
            "Inspect dialog title and warning text about potential overwrites",
            "Verify presence of Cancel and OK buttons",
        ),
        cancel_path_observations=(
            "Cancel control is present and is the required exit path for any later approved executor",
            "Expected cancel outcome records no scheduled sync action and no service call",
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS,
        non_destructive=True,
    ),
    HighRiskDryRunDialogPlan(
        plan_id="monthly_revenue_apply_confirm_dialog_plan",
        feature_id="update_view",
        purpose="Plan dry-run dialog observations for monthly revenue apply confirmation.",
        target_dialog_name="MonthlyRevenueApplyConfirmDialog",
        allowed_observations=(
            "Inspect apply prompt text and affected monthly revenue range details",
            "Verify Cancel and Apply buttons are visible",
        ),
        cancel_path_observations=(
            "Cancel control is present and is the required exit path for any later approved executor",
            "Expected cancel outcome records no apply action and no service call",
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS,
        non_destructive=True,
    ),
)


def get_high_risk_dry_run_dialog_plan() -> tuple[HighRiskDryRunDialogPlan, ...]:
    """取得所有內建的 High-risk dry-run dialog 驗證計畫。"""
    return HIGH_RISK_DRY_RUN_DIALOG_PLAN


def get_high_risk_dry_run_dialog_plan_for_feature(feature_id: str) -> tuple[HighRiskDryRunDialogPlan, ...]:
    """取得特定 feature_id 的 HighRiskDryRunDialogPlan 列表。"""
    return tuple(plan for plan in HIGH_RISK_DRY_RUN_DIALOG_PLAN if plan.feature_id == feature_id)


def render_high_risk_dry_run_dialog_plan_markdown(plans: Sequence[HighRiskDryRunDialogPlan]) -> str:
    """將 HighRiskDryRunDialogPlan 列表渲染為 Markdown 格式。"""
    if not plans:
        return "- (None)"

    lines = [
        "> D-4 is plan-only metadata. Do not execute MainWindow, run dialogs, click confirm, or invoke real services from unit tests."
    ]
    for plan in plans:
        allowed = ", ".join(f"`{item}`" for item in plan.allowed_observations)
        cancel_obs = ", ".join(f"`{item}`" for item in plan.cancel_path_observations)
        forbidden = ", ".join(f"`{item}`" for item in plan.forbidden_actions)
        lines.append(
            f"- **Plan ID**: `{plan.plan_id}` (Feature: `{plan.feature_id}`, Dialog: `{plan.target_dialog_name}`)\n"
            f"  - *Purpose*: {plan.purpose}\n"
            f"  - *Allowed Observations*: {allowed}\n"
            f"  - *Cancel Path Observations*: {cancel_obs}\n"
            f"  - *Forbidden Actions*: {forbidden}\n"
            f"  - *Requires Explicit Confirmation*: `{plan.requires_explicit_user_confirmation}`\n"
            f"  - *Requires Cancel Path*: `{plan.requires_cancel_path}`\n"
            f"  - *Mock Service Not Called*: `{plan.mock_service_not_called}`"
        )
    return "\n".join(lines)
