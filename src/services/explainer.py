"""
Module 4: Explainability Service
Generates natural language reports, traceability, and confidence scoring
"""

import json
from datetime import datetime
from typing import Dict, List, Any

from langsmith import traceable

from src.config import settings
from src.models.state import (
    TestCase, ExecutionResult, FailureAnalysis, 
    HealResult, HumanReviewItem, ExplanationReport
)
from src.services.llm_service import llm_service
from src.utils.logger import get_logger, bind_context

logger = get_logger("explainer")


class ExplainabilityService:
    """
    Generates comprehensive test reports with:
    - Natural language summaries
    - Root cause traceability
    - Confidence scoring
    - Actionable recommendations
    """
    
    @traceable(run_type="chain", name="generate_explanation_report")
    async def generate_report(
        self,
        test_cases: List[TestCase],
        execution_results: List[ExecutionResult],
        failures: List[FailureAnalysis],
        healed_tests: List[HealResult],
        human_review_queue: List[HumanReviewItem],
        run_id: str,
    ) -> ExplanationReport:
        """
        Generate comprehensive explanation report.
        """
        bind_context(run_id=run_id, operation="generate_report")
        
        # Calculate metrics
        total = len(test_cases)
        passed = sum(1 for t in test_cases if t["status"] == "passed")
        failed = sum(1 for t in test_cases if t["status"] == "failed")
        healed = sum(1 for t in test_cases if t["status"] == "healed")
        needs_review = len(human_review_queue)
        
        pass_rate = (passed / total * 100) if total else 0
        heal_rate = (healed / (failed + healed) * 100) if (failed + healed) else 0
        
        # Build detailed breakdown
        breakdown = []
        for test in test_cases:
            exec_result = next(
                (r for r in execution_results if r["test_id"] == test["id"]), None
            )
            failure = next(
                (f for f in failures if f["test_id"] == test["id"]), None
            )
            heal = next(
                (h for h in healed_tests if h["test_id"] == test["id"]), None
            )
            
            breakdown.append({
                "test_id": test["id"],
                "name": test["name"],
                "type": test["type"],
                "status": test["status"],
                "duration_ms": exec_result["duration_ms"] if exec_result else 0,
                "error_type": failure["error_type"] if failure else None,
                "fix_strategy": heal["fix_strategy"] if heal else None,
                "confidence": heal["confidence"] if heal else 1.0,
            })
        
        # Build LLM-powered executive summary
        system_prompt = """You are a QA Report AI. Generate an executive-friendly test report.
Be concise, data-driven, and actionable. Use bullet points and clear sections."""
        
        human_prompt = f"""Generate an executive summary for this test run:

Run ID: {run_id}
Total Tests: {total}
Passed: {passed} ({pass_rate:.1f}%)
Failed: {failed}
Self-Healed: {healed} ({heal_rate:.1f}%)
Needs Human Review: {needs_review}

Failure Breakdown:
{json.dumps([{"type": f["error_type"], "cause": f["root_cause"][:100]} for f in failures], indent=2)}

Healing Actions:
{json.dumps([{"test": h["test_id"], "strategy": h["fix_strategy"], "confidence": h["confidence"]} for h in healed_tests], indent=2)}

Provide:
1. Executive Summary (2-3 sentences)
2. Key Findings
3. Recommendations
4. Risk Assessment
"""
        
        try:
            llm_result = await llm_service.generate(system_prompt, human_prompt, temperature=0.2)
            executive_summary = llm_result["content"]
        except Exception as e:
            logger.error("llm_report_failed", error=str(e))
            executive_summary = f"Test run {run_id}: {passed}/{total} passed, {healed} auto-healed."
        
        # Confidence scores
        confidence_scores = {
            "overall_pass_rate": round(pass_rate, 2),
            "healing_success_rate": round(heal_rate, 2),
            "human_review_needed_rate": round((needs_review / total * 100), 2) if total else 0,
            "avg_heal_confidence": round(
                sum(h["confidence"] for h in healed_tests) / len(healed_tests), 2
            ) if healed_tests else 0,
        }
        
        report = ExplanationReport(
            executive_summary=executive_summary,
            detailed_breakdown=breakdown,
            root_causes=[f["root_cause"] for f in failures],
            healing_actions=[
                f"Healed {h['test_id']} using {h['fix_strategy']} (confidence: {h['confidence']:.2f})"
                for h in healed_tests
            ],
            human_review_items=[
                f"{item['test_id']}: {item['reason']}"
                for item in human_review_queue
            ],
            recommendations=self._generate_recommendations(failures, healed_tests),
            confidence_scores=confidence_scores,
            traceability={
                "run_id": run_id,
                "model": settings.llm.model,
                "generated_at": datetime.utcnow().isoformat(),
                "total_tests": total,
                "test_types": list(set(t["type"] for t in test_cases)),
            },
            generated_at=datetime.utcnow().isoformat(),
        )
        
        logger.info("report_generated", run_id=run_id, pass_rate=pass_rate)
        return report
    
    def _generate_recommendations(
        self,
        failures: List[FailureAnalysis],
        healed_tests: List[HealResult],
    ) -> List[str]:
        """Generate actionable recommendations based on patterns."""
        recommendations = []
        
        # Analyze failure patterns
        error_types = {}
        for f in failures:
            error_types[f["error_type"]] = error_types.get(f["error_type"], 0) + 1
        
        if error_types.get("locator_broken", 0) > 2:
            recommendations.append(
                "Add data-testid attributes to UI components to reduce locator fragility"
            )
        
        if error_types.get("timeout", 0) > 2:
            recommendations.append(
                "Review application performance - multiple tests timing out indicates slow page loads"
            )
        
        if error_types.get("race_condition", 0) > 1:
            recommendations.append(
                "Implement explicit wait strategies and page load state checks"
            )
        
        low_confidence_heals = [h for h in healed_tests if h["confidence"] < 0.8]
        if low_confidence_heals:
            recommendations.append(
                f"Review {len(low_confidence_heals)} low-confidence auto-heals for potential false positives"
            )
        
        if not recommendations:
            recommendations.append("No critical patterns detected. Continue current practices.")
        
        return recommendations


explainer = ExplainabilityService()