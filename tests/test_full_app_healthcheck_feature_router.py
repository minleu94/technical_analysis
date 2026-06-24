from __future__ import annotations

import pytest

from qa.full_app_healthcheck.feature_router import query_feature, FEATURE_ROUTES
from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.test_suite_bridge import build_existing_suite_registry


def test_query_all_six_features():
    expected_ids = {"update_view", "decision_desk", "research_lab", "market_regime", "smart_money", "registry_compare"}
    assert set(FEATURE_ROUTES.keys()) == expected_ids

    for fid in expected_ids:
        route = query_feature(fid)
        assert route is not None
        assert route.feature_id == fid


def test_keyword_mapping_chinese_and_english():
    # Test UpdateView
    r_up = query_feature("資料更新")
    assert r_up is not None
    assert r_up.feature_id == "update_view"

    r_up2 = query_feature("更新頁")
    assert r_up2 is r_up

    # Test Decision Desk
    r_dec = query_feature("每日決策")
    assert r_dec is not None
    assert r_dec.feature_id == "decision_desk"

    r_dec2 = query_feature("decision desk")
    assert r_dec2 is r_dec

    # Test Research Lab
    r_res = query_feature("策略實驗室")
    assert r_res is not None
    assert r_res.feature_id == "research_lab"

    r_res2 = query_feature("回測")
    assert r_res2 is r_res

    # Test Market Regime
    r_reg = query_feature("市場觀察")
    assert r_reg is not None
    assert r_reg.feature_id == "market_regime"

    # Test Smart Money
    r_sm = query_feature("主力流向")
    assert r_sm is not None
    assert r_sm.feature_id == "smart_money"

    # Test Registry Compare
    r_comp = query_feature("策略比較")
    assert r_comp is not None
    assert r_comp.feature_id == "registry_compare"


def test_quick_full_status_matches_bridge():
    suites = build_existing_suite_registry()
    suite_modes = {suite.id: suite.modes for suite in suites}

    for fid, route in FEATURE_ROUTES.items():
        # Check quick support
        if route.quick_supported:
            # At least one associated suite must support QUICK
            has_quick = any(
                HealthcheckMode.QUICK in suite_modes.get(sid, ())
                for sid in route.direct_bridge_suite_ids
            )
            assert has_quick, f"Feature '{fid}' claims quick support, but none of its direct bridge suites support QUICK!"
        else:
            # Reverse test: if quick_supported is False, none of its direct bridge suites should support QUICK mode
            for sid in route.direct_bridge_suite_ids:
                assert HealthcheckMode.QUICK not in suite_modes.get(sid, ()), f"Feature '{fid}' claims no quick support, but its direct bridge suite '{sid}' supports QUICK!"

        # All direct bridge suites must exist in suite_modes
        for sid in route.direct_bridge_suite_ids:
            assert sid in suite_modes, f"Feature '{fid}' references unregistered suite '{sid}'!"



def test_data_audit_policy_is_conditional_and_not_always_required():
    policies = [route.data_audit_policy for route in FEATURE_ROUTES.values()]

    # Policies shouldn't be all required
    assert "conditional" in policies
    assert "never" in policies
    assert "required" not in policies  # Per prompt, Data Audit should be conditional or never, not unconditionally required


def test_unknown_keywords_return_none():
    assert query_feature("unknown_feature") is None
    assert query_feature("") is None
    assert query_feature("   ") is None
