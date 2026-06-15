import pytest

from decision_module.factors.factor_dtos import FactorDefinition, MissingPolicy
from decision_module.factors.factor_registry import FactorRegistry, UnknownFactorError


def test_default_registry_contains_month3_v1_factors():
    registry = FactorRegistry.default()

    technical = registry.get("technical.total_score")
    assert technical.display_name == "技術總分"
    assert technical.category == "technical"
    assert technical.source_version == "technical-v1"
    assert technical.default_missing_policy == MissingPolicy.FAIL_CLOSED
    assert technical.neutral_score_bp is None
    assert technical.stale_after_days == 1

    volume = registry.get("volume.volume_ratio")
    assert volume.display_name == "量能比率"
    assert volume.category == "volume"
    assert volume.source_version == "volume-v1"
    assert volume.default_missing_policy == MissingPolicy.NEUTRAL
    assert volume.neutral_score_bp == 5000
    assert volume.stale_after_days == 5

    broker_flow = registry.get("broker_flow.net_lots")
    assert broker_flow.display_name == "券商分點淨買賣超"
    assert broker_flow.category == "broker_flow"
    assert broker_flow.source_version == "broker-flow-v1"
    assert broker_flow.default_missing_policy == MissingPolicy.SKIP
    assert broker_flow.neutral_score_bp is None
    assert broker_flow.stale_after_days == 5


def test_registry_rejects_unknown_factor():
    with pytest.raises(UnknownFactorError, match="unknown.factor"):
        FactorRegistry.default().get("unknown.factor")


def test_registry_definitions_are_immutable_after_construction():
    registry = FactorRegistry.default()

    with pytest.raises(TypeError):
        registry.definitions["x"] = registry.get("technical.total_score")


def test_registry_defensively_copies_source_definitions():
    technical = FactorRegistry.default().get("technical.total_score")
    extra = FactorDefinition(
        factor_name="custom.extra",
        display_name="額外因子",
        category="custom",
        source_version="custom-v1",
        default_missing_policy=MissingPolicy.SKIP,
    )
    source = {"technical.total_score": technical}
    registry = FactorRegistry(definitions=source)

    source["custom.extra"] = extra

    assert "custom.extra" not in registry.definitions


def test_unknown_factor_error_lists_available_factor_keys():
    with pytest.raises(UnknownFactorError) as exc_info:
        FactorRegistry.default().get("unknown.factor")

    message = str(exc_info.value)
    assert "unknown.factor" in message
    assert "technical.total_score" in message
