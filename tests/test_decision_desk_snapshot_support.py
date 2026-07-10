from app_module.decision_desk_dtos import DecisionDeskQuality
from app_module.decision_desk_snapshot_support import (
    collect_smart_money_candidate_codes,
    collect_snapshot_warnings,
    compute_overall_quality,
)

class Section:
    def __init__(self, quality): self.quality=quality

def test_quality_preserves_degraded_precedence():
    assert compute_overall_quality((Section(DecisionDeskQuality.OBSERVED), Section(DecisionDeskQuality.DEGRADED))) is DecisionDeskQuality.DEGRADED


def test_quality_warnings_and_candidate_codes_preserve_contract_order() -> None:
    sections = tuple(Section(DecisionDeskQuality.OBSERVED) for _ in range(7))
    for section, warning in zip(sections, ("m", "b", "s", "r", "w", "p", "q")):
        section.warnings = (warning,)

    assert compute_overall_quality((Section(DecisionDeskQuality.ESTIMATED), Section(DecisionDeskQuality.MISSING))) is DecisionDeskQuality.MISSING
    assert collect_snapshot_warnings(sections) == (
        "market_regime:m", "market_breadth:b", "sector_rotation:s", "relative_strength_liquidity:r", "watchlist_triggers:w", "portfolio_alerts:p", "risk_prompts:q",
    )

    relative = type("Relative", (), {"top_strength_codes": ("A", "B"), "weak_strength_codes": ("B", "C"), "low_liquidity_codes": ("", "D")})()
    watchlist = type("Watchlist", (), {"triggered_codes": tuple(str(index) for index in range(30))})()
    portfolio = type("Portfolio", (), {"alert_codes": ("A", "Z")})()
    codes = collect_smart_money_candidate_codes(relative, watchlist, portfolio)
    assert codes[:4] == ("A", "B", "C", "D")
    assert len(codes) == 20
