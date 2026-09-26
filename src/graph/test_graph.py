"""
LangGraph Orchestrator
Coordinates all modules with conditional routing and state management
"""

from typing import Literal
from datetime import datetime, timezone
from uuid import uuid4

from langgraph.graph import StateGraph, END
from langsmith import traceable

from src.config import settings
from src.models.state import (
    TestAutomationState, TestCase, ExecutionResult,
    FailureAnalysis, HealResult, HumanReviewItem
)
from src.services.test_generator import test_generator
from src.services.test_executor import test_executor
from src.services.failure_analyzer import failure_analyzer
from src.services.self_healer import self_healer
from src.services.explainer import explainer
from src.utils.logger import get_logger, bind_context, clear_context

logger = get_logger("test_graph")


# ============================================
# Graph Nodes
async def _notify_step(run_id: str, step: str, message: str) -> None:
    """Helper to broadcast graph progress to dashboard clients via WebSocket."""
    try:
        from src.api.dashboard import manager
        await manager.broadcast({
            "type": "step_changed",
            "run_id": run_id,
            "step": step,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass


async def node_generate_tests(state: TestAutomationState) -> dict:
    """Module 1: Generate test suite from inputs."""
    logger.info("node_generate_tests", run_id=state["run_id"])
    await _notify_step(state["run_id"], "generate_tests", "Generating test suite from requirements & code...")
    
    tests = await test_generator.generate_test_suite(
        requirements=state["requirements"],
        source_code=state["source_code"],
        api_docs=state.get("api_docs"),
        test_plan=state.get("test_plan"),
    )
    
    return {
        "current_step": "test_generation",
        "generated_tests": tests,
        "metrics": {"generated_count": len(tests)},
    }


async def node_execute_tests(state: TestAutomationState) -> dict:
    """Module 2: Execute all generated tests."""
    logger.info("node_execute_tests", run_id=state["run_id"])
    await _notify_step(state["run_id"], "execute_tests", "Executing generated test cases in browser & HTTP runner...")
    
    results = await test_executor.execute_test_suite(
        test_cases=state["generated_tests"],
        run_id=state["run_id"],
    )
    
    # Update test statuses cleanly
    updated_tests = [dict(t) for t in state["generated_tests"]]
    for result in results:
        test = next((t for t in updated_tests if t["id"] == result["test_id"]), None)
        if test:
            test["status"] = result["status"] if result["status"] != "error" else "failed"
            test["updated_at"] = datetime.now(timezone.utc).isoformat()
            if result.get("screenshot_path"):
                test["screenshot_path"] = result["screenshot_path"]
            if result.get("trace_path"):
                test["trace_path"] = result["trace_path"]
            if result.get("video_path"):
                test["video_path"] = result["video_path"]
    
    return {
        "current_step": "test_execution",
        "generated_tests": updated_tests,
        "execution_results": results,
        "metrics": {"executed_count": len(results)},
    }


async def node_analyze_failures(state: TestAutomationState) -> dict:
    """Module 3A: Analyze all failures."""
    logger.info("node_analyze_failures", run_id=state["run_id"])
    await _notify_step(state["run_id"], "analyze_failures", "Analyzing failed test execution traces and root causes...")
    
    analyses = await failure_analyzer.analyze_all_failures(
        execution_results=state["execution_results"],
        test_cases=state["generated_tests"],
    )
    
    return {
        "current_step": "failure_analysis",
        "failures": analyses,
        "metrics": {"failure_count": len(analyses)},
    }


async def node_self_heal(state: TestAutomationState) -> dict:
    """Module 3B: Attempt self-healing on failures."""
    current_iteration = state.get("iteration_count", 0) + 1
    logger.info("node_self_heal", run_id=state["run_id"], iteration=current_iteration)
    await _notify_step(state["run_id"], "self_heal", f"Attempting self-healing iteration {current_iteration}...")
    
    heal_results = await self_healer.heal_all_failures(
        failures=state["failures"],
        test_cases=state["generated_tests"],
    )
    
    new_review_items: list[HumanReviewItem] = []
    
    # Queue low-confidence heals for human review
    for heal in heal_results:
        if heal["validation_status"] != "success" or heal["confidence"] < settings.app.confidence_threshold:
            failure = next((f for f in state["failures"] if f["test_id"] == heal["test_id"]), None)
            
            new_review_items.append(HumanReviewItem(
                test_id=heal["test_id"],
                heal_result=heal,
                failure_analysis=failure,
                reason=f"Low confidence ({heal['confidence']:.2f}) or validation failed" 
                    if heal["validation_status"] != "success" 
                    else f"Low confidence: {heal['confidence']:.2f}",
                priority="high" if failure and failure["error_type"] == "locator_broken" else "medium",
                submitted_at=datetime.now(timezone.utc).isoformat(),
                reviewed_at=None,
                reviewer_notes=None,
                approved=None,
            ))
    
    healed_count = sum(1 for h in heal_results if h["validation_status"] == "success")
    
    return {
        "current_step": "self_healing",
        "iteration_count": current_iteration,
        "healed_tests": heal_results,
        "human_review_queue": new_review_items,
        "metrics": {
            "healed_count": healed_count,
            "human_review_count": len(new_review_items),
        },
    }


async def node_explain(state: TestAutomationState) -> dict:
    """Module 4: Generate explanation report."""
    logger.info("node_explain", run_id=state["run_id"])
    await _notify_step(state["run_id"], "explain", "Generating executive explainability report...")
    
    report = await explainer.generate_report(
        test_cases=state["generated_tests"],
        execution_results=state["execution_results"],
        failures=state["failures"],
        healed_tests=state["healed_tests"],
        human_review_queue=state["human_review_queue"],
        run_id=state["run_id"],
    )
    
    return {
        "current_step": "explainability",
        "explanation": report,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


async def node_human_review(state: TestAutomationState) -> dict:
    """Human review placeholder - in production, this would pause for human input."""
    logger.info("node_human_review", queue_size=len(state["human_review_queue"]))
    await _notify_step(state["run_id"], "human_review", "Low-confidence repairs queued for human review.")
    
    updated_tests = [dict(t) for t in state["generated_tests"]]
    for item in state["human_review_queue"]:
        test = next((t for t in updated_tests if t["id"] == item["test_id"]), None)
        if test:
            test["status"] = "needs_review"
            test["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    return {
        "current_step": "human_review",
        "generated_tests": updated_tests,
    }


# ============================================
# Conditional Routing
# ============================================

def router_after_execution(state: TestAutomationState) -> Literal["analyze", "explain"]:
    """Route based on execution results."""
    failed = any(
        r["status"] in ["failed", "error", "timeout"] 
        for r in state["execution_results"]
    )
    return "analyze" if failed else "explain"


def router_after_healing(state: TestAutomationState) -> Literal["re_execute", "explain", "human_review"]:
    """Route after healing attempt."""
    iterations = state.get("iteration_count", 0)
    max_iter = state.get("max_iterations", 3)
    
    still_failing = any(
        t["status"] == "failed" for t in state["generated_tests"]
    )
    
    has_human_review = len(state.get("human_review_queue", [])) > 0
    
    if still_failing and iterations < max_iter:
        return "re_execute"
    elif has_human_review:
        return "human_review"
    else:
        return "explain"


# ============================================
# Graph Builder
# ============================================

def build_test_automation_graph():
    """
    Build the complete LangGraph workflow.
    
    Flow:
    generate_tests → execute_tests → [analyze_failures → self_heal → validate]*
                     ↓ (no failures)
                explainability → END
    """
    workflow = StateGraph(TestAutomationState)
    
    # Add nodes
    workflow.add_node("generate_tests", node_generate_tests)
    workflow.add_node("execute_tests", node_execute_tests)
    workflow.add_node("analyze_failures", node_analyze_failures)
    workflow.add_node("self_heal", node_self_heal)
    workflow.add_node("explain", node_explain)
    workflow.add_node("human_review", node_human_review)
    
    # Entry point
    workflow.set_entry_point("generate_tests")
    
    # Linear flow to execution
    workflow.add_edge("generate_tests", "execute_tests")
    
    # Conditional after execution
    workflow.add_conditional_edges(
        "execute_tests",
        router_after_execution,
        {
            "analyze": "analyze_failures",
            "explain": "explain",
        }
    )
    
    # Failure analysis → self-heal
    workflow.add_edge("analyze_failures", "self_heal")
    
    # Conditional after healing
    workflow.add_conditional_edges(
        "self_heal",
        router_after_healing,
        {
            "re_execute": "execute_tests",  # Loop back to re-run healed tests
            "explain": "explain",
            "human_review": "human_review",
        }
    )
    
    # Human review → explain
    workflow.add_edge("human_review", "explain")
    
    # End
    workflow.add_edge("explain", END)
    
    return workflow.compile()


# Compiled graph instance
test_automation_graph = build_test_automation_graph()