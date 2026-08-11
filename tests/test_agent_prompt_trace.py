from __future__ import annotations

from structlog.contextvars import bound_contextvars

from app import agent as agent_module


class ManagedPrompt:
    version = 3

    def compile(self, **variables: str) -> str:
        return (
            f"Feature={variables['feature']}\n"
            f"Docs={variables['docs']}\n"
            f"Question={variables['message']}"
        )


class RecordingLangfuseClient:
    def __init__(self) -> None:
        self.prompt = ManagedPrompt()
        self.trace_updates: list[dict] = []
        self.generation_updates: list[dict] = []

    def get_prompt(self, name: str, **kwargs):
        return self.prompt

    def update_current_trace(self, **kwargs) -> None:
        self.trace_updates.append(kwargs)

    def update_current_generation(self, **kwargs) -> None:
        self.generation_updates.append(kwargs)


def test_agent_links_prompt_version_to_trace_and_generation(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-public-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)

    agent = agent_module.LabAgent()
    agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Explain traces",
    )

    trace_metadata = client.trace_updates[-1]["metadata"]
    generation_update = client.generation_updates[-1]
    assert trace_metadata == {
        "prompt_name": "day13-chat",
        "prompt_label": "production",
        "prompt_version": "3",
        "prompt_source": "langfuse",
    }
    assert generation_update["prompt"] is client.prompt
    assert generation_update["metadata"]["prompt_version"] == "3"


def _run_with_recording_client(monkeypatch, client) -> agent_module.AgentResult:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-public-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    return agent_module.LabAgent.run.__wrapped__(
        agent_module.LabAgent(),
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Explain traces",
    )


def test_trace_carries_correlation_id_so_logs_and_traces_can_be_joined(monkeypatch) -> None:
    """Không có khoá chung thì report chỉ nối Logs <-> Traces bằng phỏng đoán."""
    client = RecordingLangfuseClient()

    with bound_contextvars(correlation_id="req-deadbeef"):
        result = _run_with_recording_client(monkeypatch, client)

    assert "cid:req-deadbeef" in client.trace_updates[-1]["tags"]
    assert client.generation_updates[-1]["metadata"]["correlation_id"] == "req-deadbeef"
    assert result.correlation_id == "req-deadbeef"


def test_agent_result_exposes_prompt_version_without_a_second_fetch(monkeypatch) -> None:
    result = _run_with_recording_client(monkeypatch, RecordingLangfuseClient())

    assert (result.prompt_name, result.prompt_label) == ("day13-chat", "production")
    assert result.prompt_version == "3"
    assert result.prompt_source == "langfuse"


def test_missing_correlation_id_does_not_add_an_empty_tag(monkeypatch) -> None:
    """Chạy ngoài HTTP request (script evidence) vẫn phải tạo trace sạch."""
    client = RecordingLangfuseClient()
    result = _run_with_recording_client(monkeypatch, client)

    assert result.correlation_id == ""
    assert not any(tag.startswith("cid:") for tag in client.trace_updates[-1]["tags"])
