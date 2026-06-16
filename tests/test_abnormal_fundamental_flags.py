from datetime import date
from decimal import Decimal

from decision_module.factors.abnormal_fundamental_flags import (
    AbnormalFundamentalFlag,
    build_abnormal_fundamental_diagnostics,
)


def test_abnormal_fundamental_flags_mark_revenue_and_profit_divergence():
    diagnostics = build_abnormal_fundamental_diagnostics(
        stock_code="2330",
        as_of_date=date(2026, 6, 15),
        revenue_yoy=Decimal("0.25"),
        operating_profit_yoy=Decimal("-0.10"),
        one_off_gain_ratio=None,
        quality_warnings=(),
        source_version="fundamental-diagnostics-v1",
    )

    assert diagnostics[0].code == AbnormalFundamentalFlag.REVENUE_PROFIT_DIVERGENCE.value
    assert "revenue_yoy=0.25" in diagnostics[0].message
    assert "operating_profit_yoy=-0.10" in diagnostics[0].message


def test_abnormal_fundamental_flags_mark_one_off_gain():
    diagnostics = build_abnormal_fundamental_diagnostics(
        stock_code="2330",
        as_of_date=date(2026, 6, 15),
        revenue_yoy=Decimal("0.05"),
        operating_profit_yoy=Decimal("0.04"),
        one_off_gain_ratio=Decimal("0.35"),
        quality_warnings=(),
        source_version="fundamental-diagnostics-v1",
    )

    assert diagnostics[0].code == AbnormalFundamentalFlag.ONE_OFF_GAIN_RISK.value


def test_abnormal_fundamental_flags_preserve_quality_warnings():
    diagnostics = build_abnormal_fundamental_diagnostics(
        stock_code="2330",
        as_of_date=date(2026, 6, 15),
        revenue_yoy=None,
        operating_profit_yoy=None,
        one_off_gain_ratio=None,
        quality_warnings=("fundamental_availability.missing_announced_date",),
        source_version="fundamental-diagnostics-v1",
    )

    assert diagnostics[0].code == AbnormalFundamentalFlag.DATA_QUALITY_GAP.value
    assert "missing_announced_date" in diagnostics[0].message
