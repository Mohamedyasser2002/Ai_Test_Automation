import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from langsmith import traceable

from src.config import settings
from src.models.state import TestCase
from src.services.llm_service import llm_service
from src.utils.logger import get_logger, bind_context

logger = get_logger("test_generator")


class TestGenerationService:
    """
    Generates test cases using the configured LLM's agentic coding capabilities.
    Supports UI, API, DB, and Integration test generation.
    """
    
    def __init__(self):
        self.max_context_files = 15
        self.max_context_chars = 8000
    
    def _build_context(self, source_code: Dict[str, str], api_docs: Optional[str]) -> str:
        """
        Build optimized context string from source code.
        Prioritizes relevant files and truncates large files.
        """
        # Prioritize files likely to contain testable logic
        priority_patterns = [
            "page", "component", "controller", "service",
            "handler", "route", "endpoint", "api", "form",
            "login", "auth", "checkout", "cart", "user"
        ]
        
        sorted_files = sorted(
            source_code.items(),
            key=lambda x: (
                -sum(1 for p in priority_patterns if p.lower() in x[0].lower()),
                len(x[1])
            )
        )
        
        context_parts = []
        total_chars = 0
        
        for filepath, content in sorted_files[:self.max_context_files]:
            # Truncate large files
            if len(content) > 2000:
                content = content[:2000] + "\n... [truncated]"
            
            part = f"=== {filepath} ===\n{content}\n"
            if total_chars + len(part) > self.max_context_chars:
                break
            
            context_parts.append(part)
            total_chars += len(part)
        
        return "\n".join(context_parts)
    
    @traceable(run_type="chain", name="generate_test_suite")
    async def generate_test_suite(
        self,
        requirements: str,
        source_code: Dict[str, str],
        api_docs: Optional[str] = None,
        test_plan: Optional[str] = None,
    ) -> List[TestCase]:
        """
        Generate a complete test suite from inputs.
        
        Strategy:
        1. Analyze requirements to identify test scenarios
        2. Map scenarios to source code components
        3. Generate test cases for each type (UI/API/DB)
        4. Generate automation code for each test case
        """
        bind_context(
            operation="generate_test_suite",
            requirement_length=len(requirements),
            source_files=len(source_code),
        )
        
        logger.info("starting_test_generation", source_files=len(source_code))
        
        # Step 1: Identify test scenarios from requirements
        scenarios = await self._identify_scenarios(requirements, test_plan)
        logger.info("scenarios_identified", count=len(scenarios))
        
        # Step 2: Build source context
        code_context = self._build_context(source_code, api_docs)
        
        # Step 3: Generate test cases for each scenario
        test_cases: List[TestCase] = []
        
        for scenario in scenarios:
            try:
                test_case = await self._generate_single_test(
                    scenario=scenario,
                    code_context=code_context,
                    api_docs=api_docs,
                )
                test_cases.append(test_case)
                logger.info(
                    "test_generated",
                    test_id=test_case["id"],
                    test_type=test_case["type"],
                    name=test_case["name"],
                )
            except Exception as e:
                logger.error(
                    "test_generation_failed",
                    scenario=scenario.get("name", "unknown"),
                    error=str(e),
                )
        
        logger.info("test_suite_generation_complete", total_tests=len(test_cases))
        return test_cases

    @traceable(run_type="llm", name="identify_scenarios")
    async def _identify_scenarios(self, requirements: str, test_plan: Optional[str]) -> list[dict[str, Any]]:
        """
        Use the configured LLM to identify test scenarios from requirements.
        Returns structured scenario definitions.
        """
        system_prompt = """You are a Test Architect. Analyze requirements and identify comprehensive test scenarios.

For each scenario, provide:
- name: Short descriptive name
- type: ui | api | db | integration
- description: What this test validates
- priority: critical | high | medium | low
- steps: List of user/system actions
- expected_result: Expected outcome

Output as JSON array."""
        
        human_prompt = f"""Requirements:
{requirements}

Test Plan Guidance:
{test_plan or 'Focus on critical paths and edge cases. Cover positive and negative scenarios.'}

Identify all test scenarios. Output JSON array."""
        
        result = await llm_service.generate(system_prompt, human_prompt, temperature=0.2)
        json_payload = llm_service._extract_json_payload(result["content"])
        
        try:
            scenarios = json.loads(json_payload)
            if not isinstance(scenarios, list):
                scenarios = [scenarios]
            return scenarios
        except json.JSONDecodeError:
            logger.warning("scenario_parse_failed", raw=result["content"][:500])
            # Fallback: create basic scenarios
            return [{
                "name": "Basic Smoke Test",
                "type": "ui",
                "description": "Verify application loads successfully",
                "priority": "critical",
                "steps": ["Navigate to application", "Verify page loads"],
                "expected_result": "Page loads without errors",
            }]
    
    @traceable(run_type="llm", name="generate_single_test")
    async def _generate_single_test(
        self,
        scenario: dict[str, Any],
        code_context: str,
        api_docs: Optional[str],
    ) -> TestCase:
        """
        Generate a single test case with automation code.
        """
        test_type = scenario.get("type", "ui")
        test_id = f"TEST_{uuid.uuid4().hex[:8].upper()}"
        
        # Generate automation code
        code = await llm_service.generate_test_code(
            context={
                "requirements": scenario.get("description", ""),
                "source_snippet": code_context,
                "api_docs": api_docs or "N/A",
                "description": scenario.get("description", ""),
                "steps": scenario.get("steps", []),
                "expected_result": scenario.get("expected_result", ""),
            },
            test_type=test_type,
        )
        
        now = datetime.now(timezone.utc).isoformat()
        
        return TestCase(
            id=test_id,
            name=scenario.get("name", "Unnamed Test"),
            type=test_type,
            description=scenario.get("description", ""),
            steps=scenario.get("steps", []),
            expected_result=scenario.get("expected_result", ""),
            code=code,
            status="pending",
            metadata={
                "priority": scenario.get("priority", "medium"),
                "generated_by": settings.llm.model,
                "scenario_source": "llm",
            },
            created_at=now,
            updated_at=now,
        )


# Singleton instance
test_generator = TestGenerationService()

