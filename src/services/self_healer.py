import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langsmith import traceable

from src.config import settings
from src.models.state import ExecutionResult, FailureAnalysis, HealResult, TestCase
from src.services.llm_service import llm_service
from src.services.test_executor import test_executor
from src.utils.ast_utils import compute_ast_diff, extract_locators, suggest_locator_strategy
from src.utils.logger import bind_context, get_logger

logger = get_logger("self_healer")


class SelfHealingService:
    """
    Self-healing test repair with multiple strategies:
    1. Locator update (most common)
    2. Wait strategy adjustment
    3. Assertion value update
    4. Flow adjustment
    5. API endpoint/payload fix
    
    Each fix is validated by re-execution before acceptance.
    """
    
    def __init__(self):
        self.confidence_threshold = settings.app.confidence_threshold
        self.max_healing_iterations = settings.app.max_healing_iterations
    
    def _calculate_heal_confidence(
        self,
        failure_analysis: FailureAnalysis,
        ast_diff: Any,
        fix_strategy: str,
    ) -> float:
        """
        Calculate confidence score for a healing attempt.
        """
        base_confidence = failure_analysis.get("confidence", 0.5)
        
        if ast_diff is not None:
            ast_similarity = getattr(ast_diff, "similarity_ratio", 0.5)
            if ast_similarity > 0.95:
                ast_factor = 0.3  # Too similar, probably didn't fix anything
            elif ast_similarity > 0.7:
                ast_factor = 0.9
            elif ast_similarity > 0.5:
                ast_factor = 0.6
            else:
                ast_factor = 0.3  # Too different, risky
        else:
            ast_factor = 0.3  # AST diff failed or unparseable
        
        # Strategy reliability
        strategy_reliability = {
            "locator_update": 0.85,
            "wait_strategy": 0.80,
            "assertion_fix": 0.75,
            "flow_adjustment": 0.60,
            "api_mock_fix": 0.70,
            "data_update": 0.65,
            "unknown": 0.30,
        }
        reliability = strategy_reliability.get(fix_strategy, 0.5)
        
        # Calculate weighted confidence
        confidence = (
            base_confidence * 0.30 +
            ast_factor * 0.20 +
            reliability * 0.25 +
            0.15 +  # Default complexity factor
            0.10    # Default historical factor
        )
        
        return min(confidence, 0.99)
    
    @traceable(run_type="chain", name="heal_single_test")
    async def heal_test(
        self,
        failure: FailureAnalysis,
        test_case: TestCase,
    ) -> HealResult:
        """
        Attempt to heal a single broken test.
        """
        test_id = failure["test_id"]
        bind_context(test_id=test_id, operation="heal_test")
        
        logger.info(
            "starting_heal",
            test_id=test_id,
            error_type=failure["error_type"],
            broken_locator=failure.get("broken_locator"),
        )
        
        original_code = test_case["code"]
        
        # Step 1: Generate fixed code via LLM
        try:
            repair_result = await llm_service.repair_test_code(
                original_code=original_code,
                failure_analysis={
                    "error_type": failure["error_type"],
                    "root_cause": failure["root_cause"],
                    "broken_locator": failure.get("broken_locator"),
                    "fix_strategy": self._map_error_to_strategy(failure["error_type"]),
                    "suggested_fix": f"Fix {failure['error_type']}",
                },
                error_logs=failure["logs"],
            )
            fixed_code = repair_result["fixed_code"]
            fix_strategy = repair_result["fix_strategy"]
            
        except Exception as e:
            logger.error("repair_generation_failed", test_id=test_id, error=str(e))
            return HealResult(
                test_id=test_id,
                original_code=original_code,
                fixed_code=original_code,
                fix_strategy="unknown",
                confidence=0.0,
                validation_status="error",
                ast_diff=None,
                healed_at=datetime.now(timezone.utc).isoformat(),
            )
        
        # Step 2: Compute AST diff
        try:
            ast_diff = compute_ast_diff(original_code, fixed_code)
            diff_text = ast_diff.diff_text
        except Exception as e:
            logger.warning("ast_diff_failed", test_id=test_id, error=str(e))
            ast_diff = None
            diff_text = None
        
        # Step 3: Calculate confidence
        confidence = self._calculate_heal_confidence(
            failure, ast_diff, fix_strategy
        )
        
        logger.info(
            "heal_generated",
            test_id=test_id,
            fix_strategy=fix_strategy,
            confidence=confidence,
            ast_similarity=getattr(ast_diff, "similarity_ratio", 0) if ast_diff else 0,
        )
        
        # Step 4: Validate if confidence is high enough
        validation_status = "pending"
        if confidence >= self.confidence_threshold:
            logger.info("validating_heal", test_id=test_id, confidence=confidence)
            
            temp_test = test_case.copy()
            temp_test["code"] = fixed_code
            temp_test["status"] = "pending"
            
            try:
                # Re-execute the fixed test in a worker thread to keep event loop non-blocking
                exec_result = await asyncio.to_thread(
                    test_executor._execute_single,
                    temp_test,
                    run_id=f"heal-validation-{test_id}",
                )
                
                if exec_result["status"] == "passed":
                    validation_status = "success"
                    logger.info("heal_validation_passed", test_id=test_id)
                else:
                    validation_status = "failed"
                    logger.warning(
                        "heal_validation_failed",
                        test_id=test_id,
                        new_status=exec_result["status"],
                        stderr=exec_result["stderr"][:200],
                    )
                    
            except Exception as e:
                validation_status = "error"
                logger.error("heal_validation_error", test_id=test_id, error=str(e))
        else:
            logger.info(
                "heal_skipped_validation",
                test_id=test_id,
                confidence=confidence,
                threshold=self.confidence_threshold,
            )
        
        heal_result = HealResult(
            test_id=test_id,
            original_code=original_code,
            fixed_code=fixed_code,
            fix_strategy=fix_strategy,
            confidence=confidence,
            validation_status=validation_status,
            ast_diff=diff_text,
            healed_at=datetime.now(timezone.utc).isoformat(),
        )
        
        return heal_result
    
    def _map_error_to_strategy(self, error_type: str) -> str:
        """Map error type to fix strategy"""
        mapping = {
            "locator_broken": "locator_update",
            "timeout": "wait_strategy",
            "assertion_failed": "assertion_fix",
            "race_condition": "wait_strategy",
            "ui_changed": "flow_adjustment",
            "api_error": "api_mock_fix",
            "db_error": "data_update",
        }
        return mapping.get(error_type, "unknown")
    
    @traceable(run_type="chain", name="heal_all_failures")
    async def heal_all_failures(
        self,
        failures: List[FailureAnalysis],
        test_cases: List[TestCase],
    ) -> List[HealResult]:
        """
        Heal all failures and return results.
        Updates test case code in-place for successful heals.
        """
        logger.info("starting_batch_heal", failure_count=len(failures))
        
        test_lookup = {t["id"]: t for t in test_cases}
        heal_results = []
        
        for failure in failures:
            test_case = test_lookup.get(failure["test_id"])
            if not test_case:
                logger.warning("test_case_not_found_for_heal", test_id=failure["test_id"])
                continue
            
            try:
                result = await self.heal_test(failure, test_case)
                heal_results.append(result)
                
                # Update test case if validation succeeded
                if result["validation_status"] == "success":
                    test_case["code"] = result["fixed_code"]
                    test_case["status"] = "healed"
                    test_case["updated_at"] = datetime.now(timezone.utc).isoformat()
                    logger.info("test_healed", test_id=result["test_id"])
                
            except Exception as e:
                logger.error(
                    "heal_test_error",
                    test_id=failure["test_id"],
                    error=str(e),
                )
        
        successful = sum(1 for h in heal_results if h["validation_status"] == "success")
        logger.info(
            "batch_heal_complete",
            total=len(heal_results),
            successful=successful,
            failed=len(heal_results) - successful,
        )
        
        return heal_results


# Singleton instance
self_healer = SelfHealingService()

