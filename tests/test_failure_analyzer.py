import pytest
from src.services.failure_analyzer import FailureAnalysisService


def test_classify_error_locator_broken():
    service = FailureAnalysisService()
    stderr = "TimeoutError: waiting for locator('#non-existent-button')"
    stdout = ""
    error_type = service._classify_error(stderr, stdout)
    assert error_type == "locator_broken"


def test_classify_error_timeout():
    service = FailureAnalysisService()
    stderr = "Test execution exceeded timeout of 30000ms"
    stdout = ""
    error_type = service._classify_error(stderr, stdout)
    assert error_type == "timeout"


def test_classify_error_assertion_failed():
    service = FailureAnalysisService()
    stderr = "AssertionError: Expected 'Dashboard' but got 'Login'"
    stdout = ""
    error_type = service._classify_error(stderr, stdout)
    assert error_type == "assertion_failed"


def test_classify_error_unknown():
    service = FailureAnalysisService()
    stderr = "Uncategorized execution issue occurred"
    stdout = ""
    error_type = service._classify_error(stderr, stdout)
    assert error_type == "unknown"


def test_extract_broken_locator():
    service = FailureAnalysisService()
    stderr = "TimeoutError: waiting for locator(\"#submit-btn\")"
    code = "page.locator('#submit-btn').click()"
    locator = service._extract_broken_locator(stderr, code)
    assert locator == "#submit-btn"
