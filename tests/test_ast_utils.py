import pytest
from src.utils.ast_utils import (
    compute_ast_diff,
    extract_locators,
    parse_code_to_ast,
    suggest_locator_strategy,
)


def test_parse_code_to_ast_valid():
    code = "def test_func(): assert 1 == 1"
    ast_tree = parse_code_to_ast(code)
    assert ast_tree is not None


def test_parse_code_to_ast_invalid():
    code = "def test_func(: invalid python"
    ast_tree = parse_code_to_ast(code)
    assert ast_tree is None


def test_compute_ast_diff():
    code_a = "def test_foo(): page.click('#submit-btn')"
    code_b = "def test_foo(): page.click('[data-testid=\"submit\"]')"

    diff = compute_ast_diff(code_a, code_b)
    assert diff.similarity_ratio > 0.0
    assert isinstance(diff.diff_text, str)


def test_extract_locators():
    code = """
    page.locator("#username").fill("admin")
    page.get_by_role("button", name="Login").click()
    page.get_by_test_id("submit-button").click()
    """
    locators = extract_locators(code)
    assert "#username" in locators
    assert "button" in locators or "submit-button" in locators


def test_suggest_locator_strategy():
    suggestions_id = suggest_locator_strategy("#login-button")
    assert any('[data-testid="login-button"]' in s for s in suggestions_id)

    suggestions_xpath = suggest_locator_strategy("//button[@id='submit']")
    assert len(suggestions_xpath) > 0
