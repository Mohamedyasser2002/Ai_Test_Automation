import pytest
from pathlib import Path
from src.services.test_executor import TestExecutionService
from src.models.state import TestCase

def test_build_test_wrapper_uses_posix_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("src.services.test_executor.settings.storage.screenshots_dir", tmp_path / "artifacts" / "screenshots")
    monkeypatch.setattr("src.services.test_executor.settings.storage.traces_dir", tmp_path / "artifacts" / "traces")
    
    executor = TestExecutionService()
    
    test_case: TestCase = {
        "id": "UI_TEST_001",
        "name": "Sample UI Test",
        "type": "ui",
        "description": "Test UI button",
        "steps": ["Click button"],
        "expected_result": "Button clicked",
        "code": "def test_ui(page):\n    page.goto('https://example.com')",
        "status": "pending",
        "metadata": {},
        "created_at": "",
        "updated_at": "",
    }
    
    wrapper_code = executor._build_test_wrapper(test_case, "run-123")
    
    # Assert clean Playwright fixture and teardown present without traces/screenshots/videos
    assert "sync_playwright" in wrapper_code
    assert "try:" in wrapper_code
    assert "finally:" in wrapper_code
    assert "context.tracing.stop" not in wrapper_code
    assert "page.screenshot" not in wrapper_code
    assert "record_video_dir" not in wrapper_code
