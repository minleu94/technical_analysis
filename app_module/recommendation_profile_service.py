"""Recommendation profile lifecycle service."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional

from decision_module.weight_contract import (
    LegacyWeightMigrationAdapter,
    RecommendationWeightContract,
)


PROFILE_TYPE_BUILTIN = "builtin"
PROFILE_TYPE_CUSTOM = "custom"
PROFILE_TYPE_STRATEGY_VERSION = "strategy_version"

CUSTOM_PROFILE_LABEL = "自訂，未經回測驗證"
STRATEGY_PROFILE_LABEL = "策略版本，已通過 gate"
BUILTIN_PROFILE_LABEL = "內建 Profile"

GATE_PASSED_STATUSES = {"validated", "approved", "gate_passed", "passed", "promoted"}


DEFAULT_BUILTIN_PROFILES: Dict[str, Dict[str, Any]] = {
    "momentum": {
        "name": "暴衝策略",
        "version": "1.0.0",
        "description": "偏向趨勢追蹤與量能放大的內建 Profile。",
        "regime": ["Trend", "Breakout"],
        "regime_not_suitable": ["Reversion"],
        "risk_warning": {
            "max_drawdown_expected": "高",
            "volatility": "高",
            "holding_period": "短線",
            "suitable_for": "可承受波動且會自行複核訊號的使用者",
        },
        "config": {
            "signals": {"weights": {"pattern": 2500, "technical": 5500, "volume": 2000}},
            "filters": {"price_change_min": "2.0", "price_change_max": "15.0"},
        },
    },
    "stable": {
        "name": "穩健策略",
        "version": "1.0.0",
        "description": "偏向均值回歸與風險控制的內建 Profile。",
        "regime": ["Reversion"],
        "regime_not_suitable": ["Trend", "Breakout"],
        "risk_warning": {
            "max_drawdown_expected": "中",
            "volatility": "中低",
            "holding_period": "中線",
            "suitable_for": "偏好降低波動的使用者",
        },
        "config": {
            "signals": {"weights": {"pattern": 3500, "technical": 4500, "volume": 2000}},
            "filters": {"price_change_min": "-3.0", "price_change_max": "8.0"},
        },
    },
    "long_term": {
        "name": "長期投資",
        "version": "1.0.0",
        "description": "偏向趨勢延續與較長持有期的內建 Profile。",
        "regime": ["Trend", "Breakout"],
        "regime_not_suitable": ["Reversion"],
        "risk_warning": {
            "max_drawdown_expected": "中",
            "volatility": "中",
            "holding_period": "長線",
            "suitable_for": "重視趨勢延續且可承受等待期的使用者",
        },
        "config": {
            "signals": {"weights": {"pattern": 2000, "technical": 6000, "volume": 2000}},
            "filters": {"price_change_min": "0.0", "price_change_max": "20.0"},
        },
    },
}


@dataclass(frozen=True)
class RecommendationProfile:
    profile_id: str
    profile_type: str
    name: str
    version: str
    description: str
    config: Dict[str, Any]
    applicable_regimes: List[str] = field(default_factory=list)
    not_suitable_regimes: List[str] = field(default_factory=list)
    validation_label: str = BUILTIN_PROFILE_LABEL
    risk_warning: Dict[str, Any] = field(default_factory=dict)
    source_version_id: Optional[str] = None
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def display_label(self) -> str:
        prefix = {
            PROFILE_TYPE_BUILTIN: "內建",
            PROFILE_TYPE_CUSTOM: "自訂",
            PROFILE_TYPE_STRATEGY_VERSION: "策略版本",
        }.get(self.profile_type, "Profile")
        return f"{prefix}｜{self.name}"

    def to_legacy_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "regime": list(self.applicable_regimes),
            "regime_not_suitable": list(self.not_suitable_regimes),
            "risk_warning": deepcopy(self.risk_warning),
            "config": deepcopy(self.config),
            "profile_type": self.profile_type,
            "validation_label": self.validation_label,
            "source_version_id": self.source_version_id,
        }


@dataclass(frozen=True)
class RegimeCompatibility:
    current_regime: Optional[str]
    applicable_regimes: List[str]
    status: str
    score_effect: str
    explanation: str
    excludes_results: bool = False


class RecommendationProfileService:
    """Loads built-in, custom, and gated strategy-version recommendation profiles."""

    def __init__(
        self,
        config: Any,
        builtin_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
        strategy_version_service: Any = None,
    ) -> None:
        self.config = config
        self.builtin_profiles = builtin_profiles or DEFAULT_BUILTIN_PROFILES
        self.strategy_version_service = strategy_version_service
        self.profile_dir = self._resolve_profile_dir()
        self.profile_file = self.profile_dir / "custom_profiles.json"

    def list_profiles(self) -> List[RecommendationProfile]:
        profiles: List[RecommendationProfile] = []
        profiles.extend(self.list_builtin_profiles())
        profiles.extend(self.list_custom_profiles())
        profiles.extend(self.list_strategy_version_profiles())
        return profiles

    def list_builtin_profiles(self) -> List[RecommendationProfile]:
        return [
            self._profile_from_builtin(profile_id, profile_data)
            for profile_id, profile_data in self.builtin_profiles.items()
        ]

    def list_custom_profiles(self) -> List[RecommendationProfile]:
        payload = self._read_custom_payload()
        profiles = []
        for raw_profile in payload.get("profiles", []):
            if raw_profile.get("enabled", True) is False:
                continue
            profiles.append(
                RecommendationProfile(
                    profile_id=str(raw_profile["profile_id"]),
                    profile_type=PROFILE_TYPE_CUSTOM,
                    name=str(raw_profile["name"]),
                    version=str(raw_profile.get("version", "1.0.0")),
                    description=str(raw_profile.get("description", "")),
                    config=deepcopy(raw_profile.get("config", {})),
                    applicable_regimes=list(raw_profile.get("applicable_regimes", [])),
                    not_suitable_regimes=list(raw_profile.get("not_suitable_regimes", [])),
                    validation_label=CUSTOM_PROFILE_LABEL,
                    risk_warning=deepcopy(raw_profile.get("risk_warning", {})),
                    enabled=True,
                    metadata=deepcopy(raw_profile.get("metadata", {})),
                )
            )
        return profiles

    def list_strategy_version_profiles(self) -> List[RecommendationProfile]:
        if self.strategy_version_service is None:
            return []

        profiles = []
        for version_data in self.strategy_version_service.list_versions():
            if not self._is_gate_passed(version_data):
                continue
            if not self._is_strategy_profile_enabled(version_data):
                continue

            strategy_id = str(version_data.get("strategy_id", "strategy"))
            strategy_version = str(version_data.get("strategy_version", "1.0.0"))
            version_id = str(version_data.get("version_id", f"{strategy_id}_{strategy_version}"))
            profiles.append(
                RecommendationProfile(
                    profile_id=f"strategy_version:{version_id}",
                    profile_type=PROFILE_TYPE_STRATEGY_VERSION,
                    name=f"{strategy_id} v{strategy_version}",
                    version=str(version_data.get("profile_version") or strategy_version),
                    description=str(version_data.get("notes") or "Research Lab 通過 gate 的策略版本 Profile。"),
                    config=deepcopy(version_data.get("config", {})),
                    applicable_regimes=list(version_data.get("regime", [])),
                    not_suitable_regimes=list(version_data.get("regime_not_suitable", [])),
                    validation_label=STRATEGY_PROFILE_LABEL,
                    risk_warning=deepcopy(version_data.get("risk_warning", {})),
                    source_version_id=version_id,
                    enabled=True,
                    metadata={"strategy_id": strategy_id, "validation_status": version_data.get("validation_status")},
                )
            )
        return profiles

    def save_custom_profile(
        self,
        name: str,
        description: str,
        config: Dict[str, Any],
        applicable_regimes: Iterable[str],
        not_suitable_regimes: Optional[Iterable[str]] = None,
        risk_warning: Optional[Dict[str, Any]] = None,
    ) -> RecommendationProfile:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().isoformat(timespec="seconds")
        profile_id = f"custom_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self._slugify(name)}"
        stored_config = self._prepare_config_for_storage(config)

        raw_profile = {
            "profile_id": profile_id,
            "name": name,
            "version": "1.0.0",
            "description": description,
            "config": stored_config,
            "applicable_regimes": list(applicable_regimes),
            "not_suitable_regimes": list(not_suitable_regimes or []),
            "risk_warning": self._json_safe(risk_warning or {}),
            "validation_label": CUSTOM_PROFILE_LABEL,
            "enabled": True,
            "metadata": {"created_at": now, "source": "recommendation_view"},
        }

        payload = self._read_custom_payload()
        payload.setdefault("version", 1)
        payload.setdefault("profiles", [])
        payload["profiles"].append(raw_profile)
        self._write_custom_payload(payload)

        return RecommendationProfile(
            profile_id=profile_id,
            profile_type=PROFILE_TYPE_CUSTOM,
            name=name,
            version="1.0.0",
            description=description,
            config=deepcopy(stored_config),
            applicable_regimes=list(applicable_regimes),
            not_suitable_regimes=list(not_suitable_regimes or []),
            validation_label=CUSTOM_PROFILE_LABEL,
            risk_warning=deepcopy(risk_warning or {}),
            metadata=deepcopy(raw_profile["metadata"]),
        )

    def evaluate_regime_compatibility(
        self,
        profile: RecommendationProfile,
        current_regime: Optional[str],
    ) -> RegimeCompatibility:
        applicable = list(profile.applicable_regimes)
        if not current_regime:
            return RegimeCompatibility(
                current_regime=None,
                applicable_regimes=applicable,
                status="neutral",
                score_effect="no_bonus",
                explanation="目前 Regime 尚未可用；不排除推薦結果，也不套用 Profile-Regime bonus。",
            )

        if current_regime in applicable:
            return RegimeCompatibility(
                current_regime=current_regime,
                applicable_regimes=applicable,
                status="match",
                score_effect="bonus",
                explanation="Profile 適用目前 Regime；既有 scoring 會以 regime 權重調整揭露 bonus 語意。",
            )

        return RegimeCompatibility(
            current_regime=current_regime,
            applicable_regimes=applicable,
            status="mismatch",
            score_effect="penalty",
            explanation="Profile 與目前 Regime 不匹配；不排除結果，只作排序、分數或原因揭露。",
        )

    def _profile_from_builtin(self, profile_id: str, profile_data: Dict[str, Any]) -> RecommendationProfile:
        return RecommendationProfile(
            profile_id=profile_id,
            profile_type=PROFILE_TYPE_BUILTIN,
            name=str(profile_data.get("name", profile_id)),
            version=str(profile_data.get("version", "1.0.0")),
            description=str(profile_data.get("description", "")),
            config=self._prepare_config_for_storage(profile_data.get("config", {})),
            applicable_regimes=list(profile_data.get("regime", [])),
            not_suitable_regimes=list(profile_data.get("regime_not_suitable", [])),
            validation_label=BUILTIN_PROFILE_LABEL,
            risk_warning=deepcopy(profile_data.get("risk_warning", {})),
            enabled=True,
        )

    def _prepare_config_for_storage(self, config: Dict[str, Any]) -> Dict[str, Any]:
        normalized = deepcopy(config)
        self._normalize_weight_containers(normalized)
        return self._json_safe(normalized)

    def _normalize_weight_containers(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in list(value.items()):
                if key == "weights" and isinstance(child, dict):
                    value[key] = self._normalize_weights(child)
                else:
                    self._normalize_weight_containers(child)
        elif isinstance(value, list):
            for child in value:
                self._normalize_weight_containers(child)

    def _normalize_weights(self, weights: Dict[str, Any]) -> Dict[str, int]:
        try:
            return RecommendationWeightContract.validate_and_enforce(weights)
        except Exception:
            pass

        if any(isinstance(weight, float) for weight in weights.values()):
            return LegacyWeightMigrationAdapter.migrate_float_to_bp(weights)

        return {key: int(value) for key, value in weights.items()}

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, float):
            return format(Decimal(str(value)), "f")
        if isinstance(value, dict):
            return {str(key): self._json_safe(child) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._json_safe(child) for child in value]
        return value

    def _resolve_profile_dir(self) -> Path:
        if self.config is not None and hasattr(self.config, "resolve_output_path"):
            return Path(self.config.resolve_output_path("recommendation/profiles"))
        return Path("recommendation") / "profiles"

    def _read_custom_payload(self) -> Dict[str, Any]:
        if not self.profile_file.exists():
            return {"version": 1, "profiles": []}
        try:
            return json.loads(self.profile_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"version": 1, "profiles": []}

    def _write_custom_payload(self, payload: Dict[str, Any]) -> None:
        temp_path = self.profile_file.with_suffix(".tmp.json")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        with temp_path.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(temp_path, self.profile_file)

    def _is_gate_passed(self, version_data: Dict[str, Any]) -> bool:
        return str(version_data.get("validation_status", "")).lower() in GATE_PASSED_STATUSES

    def _is_strategy_profile_enabled(self, version_data: Dict[str, Any]) -> bool:
        if version_data.get("profile_enabled") is False:
            return False
        if version_data.get("recommendation_profile_enabled") is False:
            return False

        config = version_data.get("config", {})
        if isinstance(config, dict):
            if config.get("profile_enabled") is False:
                return False
            metadata = config.get("metadata", {})
            if isinstance(metadata, dict) and metadata.get("recommendation_profile_enabled") is False:
                return False
        return True

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^0-9A-Za-z_-]+", "_", value).strip("_")
        return slug or "profile"
