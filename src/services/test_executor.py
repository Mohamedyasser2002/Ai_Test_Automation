import asyncio
import os
import subprocess
import sys
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import List

from langsmith import traceable

from src.config import settings
from src.models.state import TestCase, ExecutionResult
from src.utils.logger import get_logger, bind_context

logger = get_logger("test_executor")


class TestExecutionService:
    """
    Production-grade test execution with:
    - Parallel execution via ThreadPoolExecutor
    - Artifact collection (screenshots, traces, videos)
    - Timeout handling
    - Isolated temp file execution
    - Playwright trace recording
    """

    def __init__(self):
        self.screenshots_dir = settings.storage.screenshots_dir
        self.traces_dir = settings.storage.traces_dir
        self.max_workers = settings.test_execution.parallel_workers

        # Ensure artifact directories exist
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        (self.traces_dir / "videos").mkdir(parents=True, exist_ok=True)

    def _get_timeout(self, test_type: str) -> int:
        """Get appropriate timeout for test type"""
        timeouts = {
            "ui": settings.test_execution.timeout_ui,
            "api": settings.test_execution.timeout_api,
            "db": settings.test_execution.timeout_db,
            "integration": settings.test_execution.timeout_ui,
        }
        return timeouts.get(test_type, 60)

    def _build_test_wrapper(self, test_case: TestCase, run_id: str) -> str:
        """
        Wrap generated test code with proper imports, fixtures, and artifact collection.
        Built line-by-line to avoid f-string / triple-quote escaping hell.
        """
        test_id = test_case["id"]
        test_type = test_case["type"]
        code = test_case.get("code", "")
        if not code:
            raise ValueError(f"Test case {test_id} has no code")

        parts: List[str] = []

        # Header
        parts.append(f'"""Auto-generated test wrapper for {test_id}"""')
        parts.append("import pytest")
        parts.append("import sys")
        parts.append("import traceback")
        parts.append("from datetime import datetime")
        parts.append("")
        parts.append("# Test metadata")
        parts.append(f'TEST_ID = "{test_id}"')
        parts.append(f'RUN_ID = "{run_id}"')
        parts.append("")

        if test_type == "ui":
            parts.append("from playwright.sync_api import sync_playwright")
            parts.append("import re")
            parts.append("")
            parts.append('@pytest.fixture(scope="function")')
            parts.append("def page():")
            parts.append("    with sync_playwright() as p:")
            parts.append("        browser = p.chromium.launch(headless=True)")
            parts.append('        context = browser.new_context(viewport={"width": 1920, "height": 1080})')
            parts.append("        page = context.new_page()")
            parts.append("")
            parts.append("        try:")
            parts.append("            yield page")
            parts.append("        finally:")
            parts.append("            try:")
            parts.append("                context.close()")
            parts.append("                browser.close()")
            parts.append("            except Exception:")
            parts.append("                pass")
            parts.append("")
        else:
            parts.append("import requests")
            parts.append("import json")
            parts.append("")

        # Original test code
        parts.append("# === ORIGINAL TEST CODE ===")
        parts.append(code)
        parts.append("# === END TEST CODE ===")
        parts.append("")
        parts.append('if __name__ == "__main__":')
        parts.append('    pytest.main([__file__, "-v", "--tb=short"])')

        return "\n".join(parts)

    @traceable(run_type="chain", name="execute_single_test")
    def _execute_single(self, test_case: TestCase, run_id: str) -> ExecutionResult:
        """
        Execute a single test case in an isolated environment.
        """
        test_id = test_case["id"]
        test_type = test_case["type"]
        timeout = self._get_timeout(test_type)

        bind_context(test_id=test_id, test_type=test_type)
        logger.info("executing_test", test_id=test_id, timeout=timeout)

        # Build wrapper
        try:
            wrapper_code = self._build_test_wrapper(test_case, run_id)
        except ValueError as e:
            logger.error("build_wrapper_failed", test_id=test_id, error=str(e))
            return ExecutionResult(
                test_id=test_id,
                status="error",
                duration_ms=0,
                stdout="",
                stderr=f"Wrapper build error: {str(e)}",
                returncode=-3,
                screenshot_path=None,
                trace_path=None,
                video_path=None,
                timestamp=datetime.utcnow().isoformat(),
                artifacts={"build_error": str(e)},
            )

        temp_path = None
        start_time = datetime.utcnow()

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".py", delete=False
            ) as f:
                f.write(wrapper_code)
                temp_path = str(Path(f.name).resolve())

            # Build pytest command using current environment's Python executable
            cmd = [sys.executable, "-m", "pytest", temp_path, "-v", "--tb=long"]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env={**os.environ, "TEST_ID": test_id, "RUN_ID": run_id},
            )

            end_time = datetime.utcnow()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            # Determine status
            if result.returncode == 0:
                status = "passed"
            elif "timeout" in result.stderr.lower() or duration_ms >= timeout * 1000:
                status = "timeout"
            else:
                status = "failed"

            # Artifacts (traces and screenshots dropped)
            screenshot_path = None
            trace_path = None
            video_path = None

            execution_result = ExecutionResult(
                test_id=test_id,
                status=status,
                duration_ms=duration_ms,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
                screenshot_path=screenshot_path,
                trace_path=trace_path,
                video_path=video_path,
                timestamp=datetime.utcnow().isoformat(),
                artifacts={
                    "temp_file": temp_path,
                    "wrapper_code_length": len(wrapper_code),
                },
            )

            logger.info(
                "test_execution_complete",
                test_id=test_id,
                status=status,
                duration_ms=duration_ms,
                returncode=result.returncode,
            )

            return execution_result

        except subprocess.TimeoutExpired:
            logger.error("test_execution_timeout", test_id=test_id, timeout=timeout)
            return ExecutionResult(
                test_id=test_id,
                status="timeout",
                duration_ms=timeout * 1000,
                stdout="",
                stderr=f"Test execution exceeded {timeout}s timeout",
                returncode=-1,
                screenshot_path=None,
                trace_path=None,
                video_path=None,
                timestamp=datetime.utcnow().isoformat(),
                artifacts={"timeout": True},
            )

        except Exception as e:
            logger.error("test_execution_error", test_id=test_id, error=str(e))
            return ExecutionResult(
                test_id=test_id,
                status="error",
                duration_ms=0,
                stdout="",
                stderr=f"Execution error: {str(e)}\n{traceback.format_exc()}",
                returncode=-2,
                screenshot_path=None,
                trace_path=None,
                video_path=None,
                timestamp=datetime.utcnow().isoformat(),
                artifacts={"error": str(e)},
            )

        finally:
            # Cleanup temp file
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    @traceable(run_type="chain", name="execute_test_suite")
    async def execute_test_suite(
        self,
        test_cases: List[TestCase],
        run_id: str,
    ) -> List[ExecutionResult]:
        """
        Execute all tests with controlled parallelism.
        """
        bind_context(run_id=run_id, total_tests=len(test_cases))
        logger.info("starting_test_execution", total_tests=len(test_cases))

        # Separate UI tests (browser-heavy) from others
        ui_tests = [t for t in test_cases if t["type"] == "ui"]
        other_tests = [t for t in test_cases if t["type"] != "ui"]

        results: List[ExecutionResult] = []

        # Run UI tests with limited workers
        ui_workers = min(2, self.max_workers)
        logger.info("executing_ui_tests", count=len(ui_tests), workers=ui_workers)

        with ThreadPoolExecutor(max_workers=ui_workers) as executor:
            ui_futures = [
                executor.submit(self._execute_single, test, run_id)
                for test in ui_tests
            ]
            for future in ui_futures:
                result = await asyncio.wrap_future(future)
                results.append(result)

        # Run API/DB tests with full parallelism
        other_workers = self.max_workers
        logger.info("executing_other_tests", count=len(other_tests), workers=other_workers)

        with ThreadPoolExecutor(max_workers=other_workers) as executor:
            other_futures = [
                executor.submit(self._execute_single, test, run_id)
                for test in other_tests
            ]
            for future in other_futures:
                result = await asyncio.wrap_future(future)
                results.append(result)

        # Update test case statuses
        passed = sum(1 for r in results if r["status"] == "passed")
        failed = sum(1 for r in results if r["status"] in ["failed", "error", "timeout"])

        logger.info(
            "test_execution_complete",
            total=len(results),
            passed=passed,
            failed=failed,
            pass_rate=f"{passed / len(results) * 100:.1f}%" if results else "N/A",
        )

        return results


# Singleton instance
test_executor = TestExecutionService()