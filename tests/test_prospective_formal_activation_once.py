from __future__ import annotations

import shutil

import pytest

from scripts.run_prospective_formal_activation_once import (
    ProspectiveActivationOnceError,
    _create_staging_root,
    _formal_paths,
    _publish_staged_outputs,
    _rollback_published_outputs,
)


def _make_final_parents(root):
    for directory in (
        "pit_sector_membership",
        "rule_champion_history",
        "portfolio_ledger",
        "readiness",
    ):
        (root / directory).mkdir(parents=True, exist_ok=True)


def test_staged_outputs_publish_and_rollback_without_overwrite(tmp_path):
    final_root = tmp_path / "formal"
    _make_final_parents(final_root)
    final_paths = _formal_paths(final_root)
    staging_root = _create_staging_root(final_root)
    published = []
    try:
        staging_paths = _formal_paths(staging_root)
        for name in ("pit", "rule", "portfolio_sqlite", "portfolio"):
            staging_paths[name].write_bytes(name.encode("ascii"))

        _publish_staged_outputs(staging_paths, final_paths, published)

        assert all(final_paths[name].is_file() for name in ("pit", "rule", "portfolio_sqlite", "portfolio"))
        _rollback_published_outputs(published)
        assert all(not final_paths[name].exists() for name in ("pit", "rule", "portfolio_sqlite", "portfolio"))
        assert all(staging_paths[name].is_file() for name in ("pit", "rule", "portfolio_sqlite", "portfolio"))
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def test_staged_publish_refuses_existing_target(tmp_path):
    final_root = tmp_path / "formal"
    _make_final_parents(final_root)
    final_paths = _formal_paths(final_root)
    staging_root = _create_staging_root(final_root)
    try:
        staging_paths = _formal_paths(staging_root)
        for name in ("pit", "rule", "portfolio_sqlite", "portfolio"):
            staging_paths[name].write_bytes(name.encode("ascii"))
        final_paths["pit"].write_bytes(b"existing")

        with pytest.raises(ProspectiveActivationOnceError, match="appeared"):
            _publish_staged_outputs(staging_paths, final_paths, [])

        assert final_paths["pit"].read_bytes() == b"existing"
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
