from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES


FORBIDDEN_MAINWINDOW_SMOKE_ACTIONS = frozenset(
    {
        "data write",
        "database write",
        "migration",
        "backfill apply",
        "external fetch",
        "network update",
        "high-risk dry-run",
        "bridge execution",
    }
)


@dataclass(frozen=True)
class MainWindowSmokePlanStep:
    step_id: str
    feature_id: str
    purpose: str
    allowed_observations: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    non_destructive: bool
    requires_explicit_user_confirmation: bool = True
    requires_main_window: bool = True

    def __post_init__(self) -> None:
        if self.feature_id not in FEATURE_ROUTES:
            raise ValueError(f"Unknown feature_id '{self.feature_id}' for smoke plan step '{self.step_id}'.")
        if not self.non_destructive:
            raise ValueError(f"Smoke plan step '{self.step_id}' must be non-destructive.")
        if not self.requires_explicit_user_confirmation:
            raise ValueError(f"Smoke plan step '{self.step_id}' must require explicit user confirmation.")
        if not self.requires_main_window:
            raise ValueError(f"Smoke plan step '{self.step_id}' must be marked as requiring MainWindow.")
        if not self.allowed_observations:
            raise ValueError(f"Smoke plan step '{self.step_id}' must describe allowed observations.")
        if not self.forbidden_actions:
            raise ValueError(f"Smoke plan step '{self.step_id}' must describe forbidden actions.")

        forbidden_text = " ".join(self.forbidden_actions).lower()
        for forbidden_action in FORBIDDEN_MAINWINDOW_SMOKE_ACTIONS:
            if forbidden_action not in forbidden_text:
                raise ValueError(
                    f"Smoke plan step '{self.step_id}' must explicitly forbid '{forbidden_action}'."
                )


COMMON_FORBIDDEN_ACTIONS = tuple(sorted(FORBIDDEN_MAINWINDOW_SMOKE_ACTIONS))

MAINWINDOW_SMOKE_PLAN: tuple[MainWindowSmokePlanStep, ...] = (
    MainWindowSmokePlanStep(
        step_id="mainwindow_startup_shell_observation",
        feature_id="update_view",
        purpose=(
            "Plan a future approved smoke observation for startup shell readiness without executing it "
            "from unit tests or the healthcheck runner."
        ),
        allowed_observations=(
            "MainWindow can be opened by a separately approved runner and immediately closed.",
            "Application title, central tab container, and status area are visible.",
            "Only passive shell visibility is recorded; no state-changing controls are invoked.",
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS,
        non_destructive=True,
    ),
    MainWindowSmokePlanStep(
        step_id="mainwindow_read_only_tab_presence",
        feature_id="decision_desk",
        purpose=(
            "Plan a future approved read-only tab presence check for high-traffic decision surfaces "
            "without triggering domain services."
        ),
        allowed_observations=(
            "Top-level tab labels for update, decision, research, market, and portfolio surfaces are visible.",
            "Switching, if separately approved later, is limited to read-only tab selection and immediate return.",
            "No form submission, refresh, save, delete, export, or data refresh command is invoked.",
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS,
        non_destructive=True,
    ),
    MainWindowSmokePlanStep(
        step_id="mainwindow_close_boundary",
        feature_id="update_view",
        purpose=(
            "Plan a future approved immediate-close smoke boundary for detecting startup hangs without "
            "mutating runtime state."
        ),
        allowed_observations=(
            "Window close can be requested after read-only visibility observations.",
            "The runner records startup and close outcome only as evidence metadata.",
            "No background worker, scheduler, update service, or persistence action is started.",
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS,
        non_destructive=True,
    ),
)


def get_mainwindow_smoke_plan() -> tuple[MainWindowSmokePlanStep, ...]:
    return MAINWINDOW_SMOKE_PLAN


def get_mainwindow_smoke_plan_for_feature(feature_id: str) -> tuple[MainWindowSmokePlanStep, ...]:
    return tuple(step for step in MAINWINDOW_SMOKE_PLAN if step.feature_id == feature_id)


def render_mainwindow_smoke_plan_markdown(steps: Sequence[MainWindowSmokePlanStep]) -> str:
    if not steps:
        return "- (None)"

    lines = [
        "> D-2 is plan-only metadata. Do not execute MainWindow from unit tests or quick/full runner bridge."
    ]
    for step in steps:
        observations = ", ".join(f"`{item}`" for item in step.allowed_observations)
        forbidden = ", ".join(f"`{item}`" for item in step.forbidden_actions)
        lines.append(
            f"- **Step ID**: `{step.step_id}` (Feature: `{step.feature_id}`)\n"
            f"  - *Purpose*: {step.purpose}\n"
            f"  - *Allowed Observations*: {observations}\n"
            f"  - *Forbidden Actions*: {forbidden}\n"
            f"  - *Requires Explicit Confirmation*: `{step.requires_explicit_user_confirmation}`"
        )
    return "\n".join(lines)
