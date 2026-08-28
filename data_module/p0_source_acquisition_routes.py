"""Governed multi-route acquisition catalog for the thirteen P0 sources.

The catalog records *ways to obtain candidate evidence*.  A route being
listed or implemented never grants source acceptance, downstream eligibility,
formal credit, scheduler authority, or production ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from data_module.p0_source_contract_registry import P0_SOURCE_IDS


TWSE_TERMS_URL = "https://www.twse.com.tw/zh/terms/use.html"
TPEX_TERMS_URL = "https://www.tpex.org.tw/web/inc/gtsm_disclaimer.php?l=zh-tw"
TDCC_OPENAPI_URL = "https://openapi.tdcc.com.tw/"


@dataclass(frozen=True)
class P0AcquisitionRoute:
    source_id: str
    route_id: str
    provider: str
    market_scope: str
    endpoint: str
    transport: str
    evidence_role: str
    implementation_status: str
    availability_evidence: str
    license_evidence_url: str
    official: bool = True
    formal_eligible: bool = False

    def __post_init__(self) -> None:
        if self.source_id not in P0_SOURCE_IDS:
            raise ValueError(f"unknown P0 source route: {self.source_id}")
        for value_name in (
            "route_id",
            "provider",
            "market_scope",
            "endpoint",
            "transport",
            "evidence_role",
            "implementation_status",
            "availability_evidence",
            "license_evidence_url",
        ):
            if not str(getattr(self, value_name)).strip():
                raise ValueError(f"P0 acquisition route {value_name} is required")
        if self.formal_eligible:
            raise ValueError("candidate acquisition routes cannot grant formal eligibility")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "route_id": self.route_id,
            "provider": self.provider,
            "market_scope": self.market_scope,
            "endpoint": self.endpoint,
            "transport": self.transport,
            "evidence_role": self.evidence_role,
            "implementation_status": self.implementation_status,
            "availability_evidence": self.availability_evidence,
            "license_evidence_url": self.license_evidence_url,
            "official": self.official,
            "formal_eligible": self.formal_eligible,
        }


class P0AcquisitionRouteRegistry:
    def __init__(self, routes: Iterable[P0AcquisitionRoute]) -> None:
        materialized = tuple(routes)
        identities = {(item.source_id, item.route_id) for item in materialized}
        if len(identities) != len(materialized):
            raise ValueError("duplicate P0 acquisition route")
        by_source: dict[str, list[P0AcquisitionRoute]] = {
            source_id: [] for source_id in P0_SOURCE_IDS
        }
        for item in materialized:
            by_source[item.source_id].append(item)
        missing = [source_id for source_id, items in by_source.items() if not items]
        if missing:
            raise ValueError(f"P0 sources are missing acquisition routes: {missing}")
        self._by_source = {
            source_id: tuple(by_source[source_id]) for source_id in P0_SOURCE_IDS
        }

    def for_source(self, source_id: str) -> tuple[P0AcquisitionRoute, ...]:
        if source_id not in self._by_source:
            raise KeyError(source_id)
        return self._by_source[source_id]

    def to_dict(self) -> dict[str, Any]:
        routes = [
            route.to_dict()
            for source_id in P0_SOURCE_IDS
            for route in self._by_source[source_id]
        ]
        return {
            "schema_version": "p0-source-acquisition-routes.v1",
            "p0_source_count": len(P0_SOURCE_IDS),
            "route_count": len(routes),
            "sources_with_multiple_routes": sum(
                len(self._by_source[source_id]) > 1 for source_id in P0_SOURCE_IDS
            ),
            "boundary": {
                "candidate_evidence_only": True,
                "source_acceptance_granted": False,
                "formal_eligible": False,
                "production_ingestion_allowed": False,
                "scheduler_allowed": False,
            },
            "routes": routes,
        }


def build_p0_acquisition_route_registry() -> P0AcquisitionRouteRegistry:
    return P0AcquisitionRouteRegistry(_ROUTES)


def _route(
    source_id: str,
    route_id: str,
    provider: str,
    market_scope: str,
    endpoint: str,
    *,
    transport: str = "json_api",
    evidence_role: str = "candidate_numeric_and_state",
    implementation_status: str = "discovered_official_alternate",
    availability_evidence: str = "first_observed_with_source_date",
    license_evidence_url: str = TWSE_TERMS_URL,
) -> P0AcquisitionRoute:
    return P0AcquisitionRoute(
        source_id=source_id,
        route_id=route_id,
        provider=provider,
        market_scope=market_scope,
        endpoint=endpoint,
        transport=transport,
        evidence_role=evidence_role,
        implementation_status=implementation_status,
        availability_evidence=availability_evidence,
        license_evidence_url=license_evidence_url,
    )


_ROUTES = (
    _route("corporate_action.ex_dividend_timeline", "twse.TWT49U", "TWSE", "listed", "https://www.twse.com.tw/exchangeReport/TWT49U", implementation_status="implemented_live_probe", evidence_role="event_state"),
    _route("corporate_action.ex_dividend_timeline", "tpex.tpex_exright_daily", "TPEx", "otc", "https://www.tpex.org.tw/openapi/v1/tpex_exright_daily", license_evidence_url=TPEX_TERMS_URL, evidence_role="event_state"),
    _route("corporate_action.reduction_split_par_value", "twse.TWTAUU", "TWSE", "listed", "https://www.twse.com.tw/exchangeReport/TWTAUU", implementation_status="implemented_live_probe", evidence_role="event_state"),
    _route("corporate_action.reduction_split_par_value", "operator.official_capture", "Owner-supplied official capture", "listed_and_otc", "file-import://corporate-action-reduction", transport="verified_file_import", implementation_status="implemented_file_import", evidence_role="event_state_and_provenance", availability_evidence="explicit_official_date_or_first_observed"),
    _route("microstructure.suspended_halt_resume", "twse.TWTAWU", "TWSE", "listed", "https://www.twse.com.tw/exchangeReport/TWTAWU", implementation_status="implemented_live_probe", evidence_role="restriction_state"),
    _route("microstructure.suspended_halt_resume", "tpex.tpex_spendi_history", "TPEx", "otc", "https://www.tpex.org.tw/openapi/v1/tpex_spendi_history", license_evidence_url=TPEX_TERMS_URL, evidence_role="restriction_state"),
    _route("microstructure.disposition_stock", "twse.announcement.punish", "TWSE", "listed", "https://www.twse.com.tw/announcement/punish", implementation_status="implemented_live_probe", evidence_role="restriction_state"),
    _route("microstructure.disposition_stock", "tpex.tpex_disposal_information", "TPEx", "otc", "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information", license_evidence_url=TPEX_TERMS_URL, evidence_role="restriction_state"),
    _route("microstructure.periodic_call_auction", "twse.announcement.punish", "TWSE", "listed", "https://www.twse.com.tw/announcement/punish", implementation_status="implemented_live_probe", evidence_role="derived_restriction_state"),
    _route("microstructure.periodic_call_auction", "tpex.tpex_cmode", "TPEx", "otc", "https://www.tpex.org.tw/openapi/v1/tpex_cmode", license_evidence_url=TPEX_TERMS_URL, evidence_role="restriction_state"),
    _route("microstructure.full_delivery", "twse.TWT85U", "TWSE", "listed", "https://www.twse.com.tw/exchangeReport/TWT85U", implementation_status="implemented_live_probe", evidence_role="restriction_state"),
    _route("microstructure.full_delivery", "tpex.tpex_cmode", "TPEx", "otc", "https://www.tpex.org.tw/openapi/v1/tpex_cmode", license_evidence_url=TPEX_TERMS_URL, evidence_role="restriction_state"),
    _route("microstructure.limit_lock", "twse.TWT84U", "TWSE", "listed", "https://www.twse.com.tw/exchangeReport/TWT84U", implementation_status="implemented_live_probe", evidence_role="daily_limit_and_quote_state", availability_evidence="market_session_date_and_first_observed"),
    _route("microstructure.limit_lock", "tpex.tpex_ceil_non_trading", "TPEx", "otc", "https://www.tpex.org.tw/openapi/v1/tpex_ceil_non_trading", license_evidence_url=TPEX_TERMS_URL, evidence_role="official_unmatched_limit_state", availability_evidence="market_session_date_and_first_observed"),
    _route("institutional_flows", "twse.T86", "TWSE", "listed", "https://www.twse.com.tw/fund/T86", implementation_status="implemented_live_probe", evidence_role="daily_flow"),
    _route("institutional_flows", "tpex.tpex_3insti_daily_trading", "TPEx", "otc", "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading", license_evidence_url=TPEX_TERMS_URL, evidence_role="daily_flow"),
    _route("credit_transactions", "twse.MI_MARGN", "TWSE", "listed", "https://www.twse.com.tw/exchangeReport/MI_MARGN", implementation_status="implemented_live_probe", evidence_role="daily_credit_balance"),
    _route("credit_transactions", "tpex.tpex_mainboard_margin_balance", "TPEx", "otc", "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance", license_evidence_url=TPEX_TERMS_URL, evidence_role="daily_credit_balance"),
    _route("tdcc_shareholding", "tdcc.legacy_1-5_csv", "TDCC", "listed_and_otc", "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5", transport="csv", implementation_status="implemented_live_probe", evidence_role="weekly_distribution", availability_evidence="weekly_period_end_and_first_observed", license_evidence_url=TDCC_OPENAPI_URL),
    _route("tdcc_shareholding", "tdcc.openapi_1-5", "TDCC", "listed_and_otc", "https://openapi.tdcc.com.tw/v1/opendata/1-5", implementation_status="implemented_live_fallback", evidence_role="weekly_distribution", availability_evidence="weekly_period_end_and_first_observed", license_evidence_url=TDCC_OPENAPI_URL),
    _route("twse.monthly_revenue_announcement", "twse.openapi.t187ap05_L", "TWSE", "listed", "https://openapi.twse.com.tw/v1/opendata/t187ap05_L", implementation_status="implemented_live_probe", evidence_role="monthly_numeric_and_report_date", availability_evidence="official_report_date_and_first_observed"),
    _route("twse.monthly_revenue_announcement", "mopsfin.csv.t187ap05_L", "MOPS/TWSE", "listed", "https://mopsfin.twse.com.tw/opendata/t187ap05_L.csv", transport="csv", implementation_status="implemented_live_fallback", evidence_role="monthly_numeric_and_report_date", availability_evidence="official_report_date_and_first_observed"),
    _route("tpex.monthly_revenue_announcement", "tpex.openapi.mopsfin_t187ap05_O", "TPEx", "otc", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O", implementation_status="implemented_live_probe", evidence_role="monthly_numeric_and_report_date", availability_evidence="official_report_date_and_first_observed", license_evidence_url=TPEX_TERMS_URL),
    _route("tpex.monthly_revenue_announcement", "mopsfin.csv.t187ap05_O", "MOPS/TWSE", "otc", "https://mopsfin.twse.com.tw/opendata/t187ap05_O.csv", transport="csv", implementation_status="implemented_live_fallback", evidence_role="monthly_numeric_and_report_date", availability_evidence="official_report_date_and_first_observed"),
    _route("pit.quarterly_financials", "mops.ezsearch.statement_publication", "MOPS/TWSE", "listed_and_otc", "https://mops.twse.com.tw/mops/web/ezsearch", transport="html_json_capture", implementation_status="implemented_file_import", evidence_role="availability_only", availability_evidence="official_announcement_timestamp"),
    _route("pit.quarterly_financials", "mops.t163sb06.financial_ratio", "MOPS/TWSE", "listed_and_otc", "https://mops.twse.com.tw/mops/web/t163sb06", transport="html_capture", implementation_status="implemented_file_import", evidence_role="numeric_only", availability_evidence="requires_separate_listing_timestamp"),
    _route("pit.quarterly_financials", "twse.openapi.latest_statement", "TWSE OpenAPI", "listed", "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci", evidence_role="latest_numeric_capability_only", availability_evidence="latest_report_date_not_historical_revision_lineage"),
)
