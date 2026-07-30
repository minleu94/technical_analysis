from __future__ import annotations

from pathlib import Path

from scripts.build_ml_research_shadow_union import build_parser
from scripts.train_ml_research_shadow_challenger import (
    build_parser as build_train_parser,
)


def test_union_cli_requires_all_three_custody_manifests() -> None:
    args = build_parser().parse_args(
        [
            "--formal-raw-manifest",
            "formal.json",
            "--shadow-raw-manifest",
            "shadow.json",
            "--base-training-manifest",
            "training.json",
            "--corporate-action-manifest",
            "official-events.json",
            "--output-dir",
            "out",
            "--symbols",
            "2330",
        ]
    )
    assert args.formal_raw_manifest == Path("formal.json")
    assert args.shadow_raw_manifest == Path("shadow.json")
    assert args.base_training_manifest == Path("training.json")
    assert args.corporate_action_manifest == Path("official-events.json")
    assert args.symbols == ["2330"]


def test_research_training_cli_has_no_alpha_or_promotion_override() -> None:
    parser = build_train_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert "--production-alpha-bp" not in option_strings
    assert "--formal-oos-allowed" not in option_strings
    assert "--promotion-eligible" not in option_strings
