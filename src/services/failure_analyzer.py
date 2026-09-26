import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langsmith import traceable

from src.config import settings
from src.models.state import ExecutionResult, FailureAnalysis, TestCase
from src.services.llm_service import llm_service
from src.utils.ast_utils import extract_locators
from src.utils.logger import bind_context, get_logger

logger = get_logger("failure_analyzer")


class FailureAnalysisService:
    """
    Analyzes test execution failures using:
    1. Log pattern matching for known error types
    2. LLM-based root cause analysis
    3. DOM/screenshot analysis (if available)
    4. Locator extraction and validation
    """
    
    # Known error patterns for fast classification
    ERROR_PATTERNS = {
        "locator_broken": [
            r"TimeoutError.*waiting for locator",
            r"Error: strict mode violation",
            r"Error: locator.*resolved to",
            r"NoSuchElementException",
            r"ElementNotFound",
            r"could not find",
            r"selector.*not found",
        ],
        "timeout": [
            r"Timeout.*exceeded",
            r"page.waitFor.*timeout",
            r"waiting for.*failed: timeout",
            r"Test execution exceeded",
        ],
        "assertion_failed": [
            r"AssertionError",
            r"assert.*failed",
            r"Expected.*but got",
            r"expect.*to",
        ],
        "api_error": [
            r"requests.exceptions",
            r"ConnectionError",
            r"HTTPError",
            r"status code",
            r"404|500|502|503",
        ],
        "race_condition": [
            r"StaleElementReference",
            r"element is no longer attached",
            r"interactable",
            r"obscured",
        ],
    }
    
    def _classify_error(self, stderr: str, stdout: str) -> str:
        """
        Fast pattern-based error classification.
        Returns the most likely error type.
        """
        combined = f"{stderr} {stdout}".lower()
        
        scores = {}
        for error_type, patterns in self.ERROR_PATTERNS.items():
            score = 0
            for pattern in patterns:
                matches = len(re.findall(pattern, combined, re.IGNORECASE))
                score += matches
            scores[error_type] = score
        
        if max(scores.values(), default=0) > 0:
            return max(scores, key=scores.get)
        
        return "unknown"
    
    def _extract_broken_locator(self, stderr: str, test_code: str) -> Optional[str]:
        """
        Extract the specific locator that failed from error logs and code.
        """
        # Try to extract from error message
        patterns = [
            r'locator\(["\']([^"\']+)["\']\)',
            r'get_by_\w+\(["\']([^"\']+)["\']\)',
            r'selector\s*["\']?([^"\']+)["\']?',
            r'element\s*["\']?([^"\']+)["\']?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, stderr, re.IGNORECASE)
            if match:
                return match.group(1)
        
        # Fallback: extract all locators from code and return first
        locators = extract_locators(test_code)
        return locators[0] if locators else None
    
    @traceable(run_type="chain", name="analyze_single_failure")
    async def analyze_failure(
        self,
        execution_result: ExecutionResult,
        test_case: TestCase,
    ) -> FailureAnalysis:
        """
        Perform comprehensive failure analysis.
        
        Pipeline:
        1. Pattern-based classification
        2. LLM root cause analysis
        3. Locator extraction
        4. Confidence scoring
        """
        test_id = execution_result["test_id"]
        bind_context(test_id=test_id, operation="analyze_failure")
        
        logger.info("analyzing_failure", test_id=test_id, status=execution_result["status"])
        
        # Step 1: Fast pattern classification
        error_type = self._classify_error(
            execution_result["stderr"],
            execution_result["stdout"],
        )
        
        # Step 2: Extract broken locator
        broken_locator = self._extract_broken_locator(
            execution_result["stderr"],
            test_case["code"],
        )
        
        # Step 3: LLM-based deep analysis
        try:
            llm_analysis = await llm_service.analyze_failure(
                test_code=test_case["code"],
                error_logs=execution_result["stderr"],
                screenshot_description=None,  # Could add vision model here
            )
            
            # Merge LLM insights with pattern classification
            if llm_analysis.get("confidence", 0) > 0.6:
                error_type = llm_analysis.get("error_type", error_type)
                broken_locator = llm_analysis.get("broken_locator") or broken_locator
            
            root_cause = llm_analysis.get("root_cause", "Unknown root cause")
            confidence = llm_analysis.get("confidence", 0.5)
            
        except Exception as e:
            logger.error("llm_analysis_failed", test_id=test_id, error=str(e))
            root_cause = f"Pattern-based: {error_type}"
            confidence = 0.4
        
        analysis = FailureAnalysis(
            test_id=test_id,
            error_type=error_type,
            root_cause=root_cause,
            broken_locator=broken_locator,
            dom_diff=None,
            stack_trace=execution_result["stderr"][:2000] if execution_result["stderr"] else None,
            screenshot_path=execution_result.get("screenshot_path"),
            logs=execution_result["stderr"],
            confidence=confidence,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )
        
        logger.info(
            "failure_analysis_complete",
            test_id=test_id,
            error_type=error_type,
            confidence=confidence,
            has_broken_locator=broken_locator is not None,
        )
        
        return analysis
    
    @traceable(run_type="chain", name="analyze_all_failures")
    async def analyze_all_failures(
        self,
        execution_results: List[ExecutionResult],
        test_cases: List[TestCase],
    ) -> List[FailureAnalysis]:
        """
        Analyze all failed tests and return structured failure reports.
        """
        # Filter to failed tests only
        failed_results = [
            r for r in execution_results
            if r["status"] in ["failed", "error", "timeout"]
        ]
        
        logger.info("analyzing_failures", total_failed=len(failed_results))
        
        # Build test lookup
        test_lookup = {t["id"]: t for t in test_cases}
        
        analyses = []
        for result in failed_results:
            test_case = test_lookup.get(result["test_id"])
            if not test_case:
                logger.warning("test_case_not_found", test_id=result["test_id"])
                continue
            
            try:
                analysis = await self.analyze_failure(result, test_case)
                analyses.append(analysis)
            except Exception as e:
                logger.error(
                    "failure_analysis_error",
                    test_id=result["test_id"],
                    error=str(e),
                )
        
        logger.info("failure_analysis_batch_complete", analyses_count=len(analyses))
        return analyses


# Singleton instance
failure_analyzer = FailureAnalysisService()

