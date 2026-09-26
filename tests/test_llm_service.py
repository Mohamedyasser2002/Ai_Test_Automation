import pytest
from src.services.llm_service import LLMService


def test_extract_code_python_block():
    content = "Here is code:\n```python\ndef test_fn(): pass\n```\nExplanation."
    extracted = LLMService._extract_code(content)
    assert extracted == "def test_fn(): pass"


def test_extract_code_generic_block():
    content = "```\nassert True\n```"
    extracted = LLMService._extract_code(content)
    assert extracted == "assert True"


def test_extract_json_payload():
    content = "Response:\n```json\n{\"status\": \"ok\"}\n```"
    payload = LLMService._extract_json_payload(content)
    assert payload == '{"status": "ok"}'
