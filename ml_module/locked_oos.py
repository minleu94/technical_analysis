"""Fail-closed preflight that runs before any locked-OOS payload is loaded."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable


@dataclass(frozen=True)
class LockedOOSPreflightRequest:
    confirm_locked_oos: bool
    dataset_content_hash: str
    model_artifact_hash: str
    max_train_decision_date: str
    max_train_label_available_date: str
    max_blend_selection_label_available_date: str
    training_as_of: str
    formal_oos_allowed: bool
    production_alpha_bp: int


@dataclass(frozen=True)
class LockedOOSExecutionResult:
    executed: bool
    blockers: tuple[str, ...]
    payload: tuple[object, ...]
    production_alpha_bp: int = 0
    shadow_only: bool = True
    production_action_allowed: bool = False


class LockedOOSPreflight:
    def execute(
        self,
        request: LockedOOSPreflightRequest,
        *,
        oos_loader: Callable[[], tuple[object, ...]],
    ) -> LockedOOSExecutionResult:
        blockers: list[str] = []
        cutoff = _date(request.training_as_of)
        if not request.confirm_locked_oos:
            blockers.append("confirm_locked_oos_required")
        if not request.formal_oos_allowed:
            blockers.append("dataset_not_formal_oos_eligible")
        if _date(request.max_train_decision_date) > cutoff:
            blockers.append("train_decision_after_training_cutoff")
        if _date(request.max_train_label_available_date) > cutoff:
            blockers.append("train_label_after_training_cutoff")
        if _date(request.max_blend_selection_label_available_date) > cutoff:
            blockers.append("blend_selection_label_after_training_cutoff")
        if not _is_sha256(request.dataset_content_hash):
            blockers.append("dataset_content_hash_missing")
        if not _is_sha256(request.model_artifact_hash):
            blockers.append("model_artifact_hash_missing")
        if request.production_alpha_bp != 0:
            blockers.append("production_alpha_must_be_zero")
        if blockers:
            return LockedOOSExecutionResult(False, tuple(blockers), ())
        return LockedOOSExecutionResult(True, (), oos_loader())


def _date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _is_sha256(value: str) -> bool:
    digest = value[7:] if value.startswith("sha256:") else ""
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)
