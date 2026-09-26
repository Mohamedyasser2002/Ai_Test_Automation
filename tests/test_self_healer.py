import pytest
from src.services.self_healer import SelfHealingService
from src.utils.ast_utils import ASTDiff


def test_calculate_heal_confidence_high():
    service = SelfHealingService()
    failure_analysis = {"confidence": 0.8}
    ast_diff = ASTDiff(
        similarity_ratio=0.85,
        added_nodes=["node1"],
        removed_nodes=["node2"],
        modified_nodes=[],
        diff_text="diff",
    )
    confidence = service._calculate_heal_confidence(
        failure_analysis, ast_diff, "locator_update"
    )
    assert 0.6 < confidence < 1.0


def test_calculate_heal_confidence_no_ast_diff():
    service = SelfHealingService()
    failure_analysis = {"confidence": 0.5}
    confidence = service._calculate_heal_confidence(
        failure_analysis, None, "unknown"
    )
    assert 0.0 < confidence < 0.6


def test_map_error_to_strategy():
    service = SelfHealingService()
    assert service._map_error_to_strategy("locator_broken") == "locator_update"
    assert service._map_error_to_strategy("timeout") == "wait_strategy"
    assert service._map_error_to_strategy("assertion_failed") == "assertion_fix"
    assert service._map_error_to_strategy("unregistered_error") == "unknown"
