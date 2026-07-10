from app_module.decision_desk_dtos import DecisionDeskQuality

def compute_overall_quality(sections):
    qualities=[section.quality for section in sections]
    for value in (DecisionDeskQuality.DEGRADED, DecisionDeskQuality.MISSING, DecisionDeskQuality.ESTIMATED):
        if value in qualities: return value
    return DecisionDeskQuality.OBSERVED

def collect_snapshot_warnings(sections):
    names=("market_regime","market_breadth","sector_rotation","relative_strength_liquidity","watchlist_triggers","portfolio_alerts","risk_prompts")
    return tuple(f"{name}:{warning}" for name, section in zip(names, sections) for warning in section.warnings)

def collect_smart_money_candidate_codes(relative_strength_liquidity, watchlist_triggers, portfolio_alerts):
    codes=[]; seen=set()
    for raw in tuple(relative_strength_liquidity.top_strength_codes)+tuple(relative_strength_liquidity.weak_strength_codes)+tuple(relative_strength_liquidity.low_liquidity_codes)+tuple(watchlist_triggers.triggered_codes)+tuple(portfolio_alerts.alert_codes):
        code=str(raw).strip()
        if code and code not in seen: seen.add(code); codes.append(code)
    return tuple(codes[:20])
