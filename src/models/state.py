
from typing import TypedDict, Annotated, List, Dict, Any, Optional, Literal
from dataclasses import dataclass, field


# ============================================
# Reducer Functions
# ============================================

def merge_dicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Merge two dictionaries, with b overwriting a on conflicts"""
    result = a.copy()
    result.update(b)
    return result


def upsert_by_id(items: list[dict[str, Any]], new_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge state updates while replacing entries from a retry."""
    merged = list(items)
    positions = {
        item.get("id", item.get("test_id", index)): index
        for index, item in enumerate(merged)
    }
    for item in new_items:
        item_id = item.get("id", item.get("test_id"))
        if item_id in positions:
            merged[positions[item_id]] = item
        else:
            positions[item_id] = len(merged)
            merged.append(item)
    return merged


# ============================================
# Core Data Structures
# ============================================

class TestCase(TypedDict):
    """Represents a single generated test case"""
    id: str
    name: str
    type: Literal["ui", "api", "db", "integration"]
    description: str
    steps: list[str]
    expected_result: str
    code: str
    status: Literal["pending", "running", "passed", "failed", "healed", "needs_review"]
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class ExecutionResult(TypedDict):
    """Result of executing a single test"""
    test_id: str
    status: Literal["passed", "failed", "error", "timeout", "skipped"]
    duration_ms: int
    stdout: str
    stderr: str
    returncode: int
    screenshot_path: Optional[str]
    trace_path: Optional[str]
    video_path: Optional[str]
    timestamp: str
    artifacts: dict[str, Any]


class FailureAnalysis(TypedDict):
    """Structured failure analysis output"""
    test_id: str
    error_type: Literal[
        "locator_broken", "assertion_failed", "timeout", "environment",
        "api_error", "db_error", "race_condition", "ui_changed", "unknown"
    ]
    root_cause: str
    broken_locator: Optional[str]
    dom_diff: Optional[str]
    stack_trace: Optional[str]
    screenshot_path: Optional[str]
    logs: str
    confidence: float
    analyzed_at: str


class HealResult(TypedDict):
    """Result of self-healing attempt"""
    test_id: str
    original_code: str
    fixed_code: str
    fix_strategy: Literal[
        "locator_update", "wait_strategy", "assertion_fix",
        "flow_adjustment", "api_mock_fix", "data_update", "unknown"
    ]
    confidence: float
    validation_status: Literal["pending", "success", "failed", "error"]
    ast_diff: Optional[str]
    healed_at: str


class HumanReviewItem(TypedDict):
    """Item queued for human review"""
    test_id: str
    heal_result: Optional[HealResult]
    failure_analysis: Optional[FailureAnalysis]
    reason: str
    priority: Literal["low", "medium", "high", "critical"]
    submitted_at: str
    reviewed_at: Optional[str]
    reviewer_notes: Optional[str]
    approved: Optional[bool]


class ExplanationReport(TypedDict):
    """Natural language explanation output"""
    executive_summary: str
    detailed_breakdown: list[dict[str, Any]]
    root_causes: list[str]
    healing_actions: list[str]
    human_review_items: list[str]
    recommendations: list[str]
    confidence_scores: dict[str, float]
    traceability: dict[str, Any]
    generated_at: str


# ============================================
# Master Graph State
# ============================================

class TestAutomationState(TypedDict):
    """
    Master state for the LangGraph workflow.
    All fields use Annotated reducers for proper state accumulation.
    """
    
    # Inputs
    requirements: str
    source_code: Dict[str, str]          # filepath -> content
    api_docs: Optional[str]
    test_plan: Optional[str]
    
    # Module 1: Test Generation
    generated_tests: Annotated[List[TestCase], upsert_by_id]
    
    # Module 2: Test Execution
    execution_results: Annotated[List[ExecutionResult], upsert_by_id]
    
    # Module 3: Failure Analysis & Self-Healing
    failures: Annotated[List[FailureAnalysis], upsert_by_id]
    healed_tests: Annotated[List[HealResult], upsert_by_id]
    human_review_queue: Annotated[List[HumanReviewItem], upsert_by_id]
    
    # Module 4: Explainability
    explanation: Optional[ExplanationReport]
    
    # Meta / Control
    current_step: str
    iteration_count: int
    max_iterations: int
    trace_id: str
    run_id: str
    started_at: str
    completed_at: Optional[str]
    
    # Metrics
    metrics: Annotated[Dict[str, Any], merge_dicts]
