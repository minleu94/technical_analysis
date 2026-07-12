from typing import Any, get_args, get_type_hints

from app_module.broker_branch_update_service import BrokerBranchUpdateService
from app_module.decision_service_composition import build_decision_service_composition
from app_module.recommendation_save_coordinator import RecommendationSaveRequest
from app_module.recommendation_service import RecommendationService


def _contains_any(annotation: object) -> bool:
    if annotation is Any:
        return True
    return any(_contains_any(item) for item in get_args(annotation))


def test_new_application_ports_are_not_annotated_as_any() -> None:
    targets = (
        (RecommendationService.__init__, "market_data_provider"),
        (BrokerBranchUpdateService.__init__, "write_coordinator"),
        (RecommendationSaveRequest.build_result, "recommendation_service"),
        (RecommendationSaveRequest.build_result, "regime_service"),
        (RecommendationSaveRequest.persist, "recommendation_repository"),
        (RecommendationSaveRequest.persist, "universe_service"),
        (build_decision_service_composition, "industry_index_provider"),
        (build_decision_service_composition, "market_index_provider"),
    )

    for callable_object, parameter_name in targets:
        annotation = get_type_hints(callable_object)[parameter_name]
        assert not _contains_any(annotation), (
            f"{callable_object.__qualname__}.{parameter_name} must use a named port"
        )
