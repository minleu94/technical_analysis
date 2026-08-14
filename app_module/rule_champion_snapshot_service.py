"""Compatibility exports for the low-level Rule Champion custody service.

The implementation lives in data_module so ML and data assembly paths do not
depend on the application layer.
"""

from data_module.rule_champion_snapshot_service import (
    FORMAL_RULE_ONLY,
    FORMAL_RULE_ONLY_IMMUTABLE_DECISION_SNAPSHOT,
    RULE_CHAMPION_HISTORY_SCHEMA_VERSION,
    FormalRuleDecisionSnapshot,
    PersistedFormalDecisionArtifactLoader,
    PersistedFormalDecisionArtifactRepository,
    RuleChampionSnapshot,
    RuleChampionSnapshotHistoryCustody,
    RuleChampionSnapshotService,
    load_verified_rule_champion_snapshot_history,
)

__all__ = (
    "FORMAL_RULE_ONLY",
    "FORMAL_RULE_ONLY_IMMUTABLE_DECISION_SNAPSHOT",
    "RULE_CHAMPION_HISTORY_SCHEMA_VERSION",
    "FormalRuleDecisionSnapshot",
    "PersistedFormalDecisionArtifactLoader",
    "PersistedFormalDecisionArtifactRepository",
    "RuleChampionSnapshot",
    "RuleChampionSnapshotHistoryCustody",
    "RuleChampionSnapshotService",
    "load_verified_rule_champion_snapshot_history",
)
