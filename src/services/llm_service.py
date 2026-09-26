import asyncio
import json
import re
import time
from typing import Any, Dict, List, Optional, Type, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langsmith import traceable
from pydantic import BaseModel

from src.config import settings
from src.utils.logger import bind_context, get_logger

logger = get_logger("llm_service")

T = TypeVar("T", bound=BaseModel)


class LLMService:
    """
    Production-grade LLM service with:
    - Retry logic with exponential backoff
    - Structured output parsing
    - Token usage tracking
    - LangSmith automatic tracing
    - Circuit breaker pattern
    """
    
    def __init__(self):
        self.config = settings.llm
        self._client: Optional[ChatOpenAI] = None
        self._failure_count = 0
        self._circuit_open = False
        self._last_failure_time: Optional[float] = None
        
    @property
    def client(self) -> ChatOpenAI:
        """Lazy initialization of LLM client"""
        if self._client is None:
            headers = {}
            if getattr(self.config, "app_url", None):
                headers["HTTP-Referer"] = self.config.app_url
            if getattr(self.config, "app_name", None):
                headers["X-Title"] = self.config.app_name

            self._client = ChatOpenAI(
                model=self.config.model,
                api_key=self.config.api_key,
                base_url=self.config.api_base,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                timeout=self.config.timeout,
                default_headers=headers if headers else None,
                max_retries=0,
            )
            logger.info(
                "llm_client_initialized",
                model=self.config.model,
                api_base=self.config.api_base,
            )
        return self._client
    
    def _check_circuit_breaker(self) -> bool:
        """Simple circuit breaker to prevent cascading failures"""
        if not self._circuit_open:
            return True
        
        # Reset after 60 seconds
        if self._last_failure_time and (time.time() - self._last_failure_time) > 60:
            self._circuit_open = False
            self._failure_count = 0
            logger.info("circuit_breaker_reset")
            return True
        
        return False
    
    def _record_failure(self):
        """Record a failure and potentially open circuit"""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= 5:
            self._circuit_open = True
            logger.error("circuit_breaker_opened", failure_count=self._failure_count)
    
    @staticmethod
    def _extract_code(content: str) -> str:
        """Extract code from markdown code blocks safely"""
        match = re.search(r'```(?:python)?\n(.*?)```', content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return content.strip()

    @staticmethod
    def _extract_json_payload(content: str) -> str:
        """Extract JSON string payload, stripping markdown fences if present"""
        match = re.search(r'```(?:json)?\n(.*?)```', content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return content.strip()

    @staticmethod
    def _is_rate_limit_error(error: Exception) -> bool:
        """Recognize provider throttling across OpenAI-compatible clients."""
        return getattr(error, "status_code", None) == 429 or "429" in str(error)

    @traceable(run_type="llm", name="llm_generate")
    async def generate(
        self,
        system_prompt: str,
        human_prompt: str,
        output_schema: Optional[Type[T]] = None,
        temperature: Optional[float] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate a structured response from the configured LLM provider.
        """
        if not self._check_circuit_breaker():
            raise RuntimeError("Circuit breaker is open - LLM service temporarily unavailable")
        
        start_time = time.time()
        temp = temperature if temperature is not None else self.config.temperature
        
        bind_context(
            llm_model=self.config.model,
            llm_temperature=temp,
            prompt_length=len(system_prompt) + len(human_prompt),
        )
        
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt),
            ]
            
            usage = {}
            for attempt in range(3):
                try:
                    if output_schema:
                        structured_llm = self.client.with_structured_output(output_schema)
                        response = await structured_llm.ainvoke(messages)
                        if hasattr(response, "model_dump"):
                            parsed = response.model_dump(mode="json")
                        else:
                            parsed = response
                        content = json.dumps(parsed, default=str)
                    else:
                        response = await self.client.ainvoke(messages, temperature=temp)
                        content = getattr(response, "content", str(response))
                        parsed = None
                        if hasattr(response, "usage_metadata") and response.usage_metadata:
                            usage = dict(response.usage_metadata)
                    break
                except Exception as error:
                    if not self._is_rate_limit_error(error) or attempt == 2:
                        raise
                    delay = 2 ** (attempt + 1)
                    logger.warning(
                        "llm_rate_limited_retrying",
                        attempt=attempt + 1,
                        retry_in_seconds=delay,
                        model=self.config.model,
                    )
                    await asyncio.sleep(delay)
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            result = {
                "content": content,
                "parsed": parsed,
                "usage": usage,
                "latency_ms": latency_ms,
                "model": self.config.model,
            }
            
            logger.info(
                "llm_generation_success",
                latency_ms=latency_ms,
                output_length=len(content),
                **usage,
            )
            
            self._failure_count = max(0, self._failure_count - 1)
            return result
            
        except Exception as e:
            self._record_failure()
            logger.error("llm_generation_failed", error=str(e), exc_info=True)
            raise
    
    @traceable(run_type="llm", name="llm_generate_sync")
    def generate_sync(
        self,
        system_prompt: str,
        human_prompt: str,
        output_schema: Optional[Type[T]] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Synchronous wrapper for generate"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(
                self.generate(system_prompt, human_prompt, output_schema, temperature)
            )
        return asyncio.run(self.generate(system_prompt, human_prompt, output_schema, temperature))
    
    @traceable(run_type="llm", name="generate_test_code")
    async def generate_test_code(
        self,
        context: Dict[str, Any],
        test_type: str,
    ) -> str:
        """
        Specialized method for generating test automation code.
        Uses the configured LLM provider for agentic coding workflows.
        """
        system_prompt = f"""You are an expert QA Automation Engineer specializing in {test_type} testing.
Generate production-ready, maintainable test automation code.

Rules:
1. Use Playwright for UI tests, pytest for API tests
2. Include proper error handling and retries
3. Add descriptive comments and docstrings
4. Use data-testid attributes where possible
5. For UI tests, rely on the injected `page` fixture (e.g. `def test_name(page):`). Do NOT create a custom `sync_playwright()` context or launch browsers manually.
6. Make code idempotent and rerunnable
7. Output ONLY the code, no explanations outside code comments

Framework: {'Playwright + pytest' if test_type == 'ui' else 'pytest + requests'}"""
        
        human_prompt = f"""Generate a complete test based on the following context:

Requirements:
{context.get('requirements', 'N/A')}

Source Code Context:
{context.get('source_snippet', 'N/A')}

API Documentation:
{context.get('api_docs', 'N/A')}

Test Description:
{context.get('description', 'N/A')}

Steps to Cover:
{chr(10).join(f"- {step}" for step in context.get('steps', []))}

Expected Result:
{context.get('expected_result', 'N/A')}

Generate the complete test code now."""
        
        result = await self.generate(system_prompt, human_prompt, temperature=0.05)
        return self._extract_code(result["content"])
    
    @traceable(run_type="llm", name="analyze_failure")
    async def analyze_failure(
        self,
        test_code: str,
        error_logs: str,
        screenshot_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze test failure and provide structured diagnosis.
        """
        system_prompt = """You are an expert debugging AI. Analyze test failures and provide structured diagnosis.

Output MUST be valid JSON with this exact structure:
{
  "error_type": "locator_broken|assertion_failed|timeout|environment|api_error|db_error|race_condition|ui_changed|unknown",
  "root_cause": "Detailed explanation of what went wrong",
  "broken_locator": "The specific locator that failed, or null",
  "fix_strategy": "locator_update|wait_strategy|assertion_fix|flow_adjustment|api_mock_fix|data_update|unknown",
  "confidence": 0.0-1.0,
  "suggested_fix": "Brief description of the recommended fix"
}"""
        
        human_prompt = f"""Analyze this test failure:

Test Code:
```python
{test_code}
```

Error Logs:
```
{error_logs}
```

Screenshot Description:
{screenshot_description or 'No screenshot available'}

Provide your analysis as JSON."""
        
        result = await self.generate(system_prompt, human_prompt, temperature=0.1)
        json_payload = self._extract_json_payload(result["content"])
        
        try:
            parsed = json.loads(json_payload)
            return parsed
        except json.JSONDecodeError:
            logger.warning("failed_to_parse_json_analysis", raw=result["content"][:500])
            return {
                "error_type": "unknown",
                "root_cause": "Failed to parse LLM analysis",
                "broken_locator": None,
                "fix_strategy": "unknown",
                "confidence": 0.0,
                "suggested_fix": "Manual review required",
            }
    
    @traceable(run_type="llm", name="repair_test_code")
    async def repair_test_code(
        self,
        original_code: str,
        failure_analysis: Dict[str, Any],
        error_logs: str,
    ) -> Dict[str, Any]:
        """
        Repair broken test code using the model's self-healing capabilities.
        """
        system_prompt = """You are a Test Repair AI. Fix broken test automation code.

Repair strategies based on error_type:
- locator_broken: Update to data-testid, role-based, or text-based selectors
- assertion_failed: Update expected values or add tolerance
- timeout: Add explicit waits, increase timeout, check for loading states
- race_condition: Add synchronization, waits for network idle
- ui_changed: Update flow to match new UI structure
- api_error: Update endpoints, payloads, or headers

Rules:
1. Preserve the original test intent
2. Maintain the same test structure
3. Add comments explaining the fix
4. Output ONLY the fixed code block
5. Ensure the code is syntactically valid Python"""
        
        human_prompt = f"""Fix this broken test:

Error Type: {failure_analysis.get('error_type', 'unknown')}
Root Cause: {failure_analysis.get('root_cause', 'unknown')}
Broken Locator: {failure_analysis.get('broken_locator', 'N/A')}
Fix Strategy: {failure_analysis.get('fix_strategy', 'unknown')}
Suggested Fix: {failure_analysis.get('suggested_fix', 'N/A')}

Original Code:
```python
{original_code}
```

Error Logs:
```
{error_logs}
```

Provide the fixed code only."""
        
        result = await self.generate(system_prompt, human_prompt, temperature=0.05)
        
        # Extract code from markdown if present
        fixed_code = self._extract_code(result["content"])
        
        return {
            "fixed_code": fixed_code,
            "original_code": original_code,
            "fix_strategy": failure_analysis.get("fix_strategy", "unknown"),
        }
    
    @staticmethod
    def _extract_code(content: str) -> str:
        """Extract code from markdown code blocks"""
        import re
        
        # Try to extract from ```python blocks
        match = re.search(r'```python\n(.*?)```', content, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Try generic code blocks
        match = re.search(r'```\n(.*?)```', content, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Return as-is if no code blocks found
        return content.strip()


# Singleton instance
llm_service = LLMService()

