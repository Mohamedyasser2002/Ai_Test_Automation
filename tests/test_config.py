import socket

from src.config import LLMConfig, get_available_port


def test_llm_config_accepts_openrouter_env_values(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-or-test-key")
    monkeypatch.setenv("LLM_API_BASE", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_MODEL", "google/gemma-4-31b-it:free")

    config = LLMConfig()

    assert config.api_key == "sk-or-test-key"
    assert config.api_base == "https://openrouter.ai/api/v1"
    assert config.model == "google/gemma-4-31b-it:free"


def test_get_available_port_skips_occupied_ports():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied_socket:
        occupied_socket.bind(("127.0.0.1", 0))
        occupied_port = occupied_socket.getsockname()[1]

        available_port = get_available_port(occupied_port, max_attempts=10)

        assert available_port != occupied_port
        assert available_port >= occupied_port


def test_llm_model_replaces_unsupported_openrouter_alias():
    config = LLMConfig(model="google/gemini-2.0-flash-exp:free")

    assert config.model == "openai/gpt-4o-mini"


def test_langsmith_accepts_langsmith_aliases(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls_test_key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "demo-project")
    monkeypatch.setenv("LANGSMITH_TRACING_V2", "true")

    from src.config import LangSmithConfig

    config = LangSmithConfig()

    assert config.api_key == "ls_test_key"
    assert config.project == "demo-project"
    assert config.tracing_v2 is True


def test_persist_run_artifacts_writes_report_files(tmp_path, monkeypatch):
    from src.api.dashboard import _persist_run_artifacts

    reports_dir = tmp_path / "reports"
    data_dir = tmp_path / "data"
    monkeypatch.setattr("src.api.dashboard.settings.storage.reports_dir", reports_dir)
    monkeypatch.setattr("src.api.dashboard.settings.storage.data_dir", data_dir)

    payload = {
        "run_id": "run-123",
        "status": "completed",
        "summary": {"passed": 1},
        "execution_results": [
            {"screenshot_path": "artifacts/screenshots/test-1.png", "trace_path": "artifacts/traces/test-1.zip", "video_path": "artifacts/traces/videos/test-1.webm"}
        ],
    }

    _persist_run_artifacts("run-123", payload)

    report_data = (reports_dir / "run-123.json").read_text(encoding="utf-8")
    latest_data = (data_dir / "latest_run.json").read_text(encoding="utf-8")

    assert (reports_dir / "run-123.json").exists()
    assert (data_dir / "latest_run.json").exists()
    assert "artifacts/screenshots/test-1.png" in report_data
    assert "artifacts/traces/test-1.zip" in latest_data
