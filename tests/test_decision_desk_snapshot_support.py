from app_module.decision_desk_dtos import DecisionDeskQuality
from app_module.decision_desk_snapshot_support import compute_overall_quality

class Section:
    def __init__(self, quality): self.quality=quality

def test_quality_preserves_degraded_precedence():
    assert compute_overall_quality((Section(DecisionDeskQuality.OBSERVED), Section(DecisionDeskQuality.DEGRADED))) is DecisionDeskQuality.DEGRADED
