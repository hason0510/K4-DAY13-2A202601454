"""Tests offline cho script prompt lifecycle của vai trò B.

Không gọi Langfuse thật: dùng client giả để kiểm tra đúng phần logic có thể sai
âm thầm — contract ba biến, cách nhận biết label đã tồn tại và thao tác rollback.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, REPO_ROOT / "scripts" / f"{module_name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


lifecycle = _load("prompt_lifecycle")
trace_evidence = _load("trace_evidence")


class FakePrompt:
    def __init__(self, version: int, labels: list[str], prompt: str = "") -> None:
        self.version = version
        self.labels = labels
        self.prompt = prompt


class FakeClient:
    """Client tối thiểu mô phỏng cách Langfuse xử lý label và version."""

    def __init__(self, versions: dict[int, list[str]] | None = None) -> None:
        self.versions: dict[int, list[str]] = dict(versions or {})
        self.created: list[dict] = []
        self.updated: list[dict] = []

    def get_prompt(self, name: str, *, label: str, **kwargs):
        for version, labels in self.versions.items():
            if label in labels:
                return FakePrompt(version, labels, prompt=f"{name} v{version}")
        raise LookupError(f"Prompt not found: {name} with label {label}")

    def create_prompt(self, *, name, prompt, type, labels, commit_message=None):
        version = max(self.versions, default=0) + 1
        self.versions[version] = list(labels)
        self.created.append({"version": version, "labels": list(labels), "prompt": prompt})
        return FakePrompt(version, list(labels), prompt)

    def update_prompt(self, *, name, version, new_labels):
        self.updated.append({"version": version, "new_labels": list(new_labels)})
        # Langfuse bảo đảm một label chỉ trỏ tới đúng một version.
        for existing, labels in self.versions.items():
            if existing != version:
                self.versions[existing] = [l for l in labels if l not in new_labels]
        self.versions[version] = sorted(set(self.versions.get(version, [])) | set(new_labels))


def test_prompt_contract_requires_all_three_variables() -> None:
    for text in (lifecycle.BASELINE_PROMPT, lifecycle.CANDIDATE_PROMPT):
        assert lifecycle.require_variables(text, what="test") is text

    with pytest.raises(lifecycle.PromptContractError) as excinfo:
        lifecycle.require_variables("Feature={{feature}}", what="prompt hong")
    assert "{{docs}}" in str(excinfo.value)
    assert "{{message}}" in str(excinfo.value)


def test_candidate_differs_from_baseline_but_keeps_template() -> None:
    assert lifecycle.CANDIDATE_PROMPT != lifecycle.BASELINE_PROMPT
    assert lifecycle.BASELINE_PROMPT in lifecycle.CANDIDATE_PROMPT


def test_fetch_by_label_reports_missing_label_instead_of_raising() -> None:
    entry = lifecycle.fetch_by_label(FakeClient(), "day13-chat", "production")
    assert entry == {"label": "production", "found": False, "error": "LookupError"}


def test_ensure_creates_two_versions_on_an_empty_project() -> None:
    client = FakeClient()
    state = lifecycle.ensure(client, "day13-chat")

    assert [entry["labels"] for entry in client.created] == [
        ["baseline", "production"],
        ["candidate"],
    ]
    by_label = {entry["label"]: entry for entry in state["labels"]}
    assert by_label["production"]["version"] == 1
    assert by_label["baseline"]["version"] == 1
    assert by_label["candidate"]["version"] == 2


def test_ensure_is_idempotent() -> None:
    client = FakeClient({1: ["baseline", "production"], 2: ["candidate"]})
    lifecycle.ensure(client, "day13-chat")
    assert client.created == []


def test_promote_moves_the_label_off_the_previous_version() -> None:
    client = FakeClient({1: ["baseline", "production"], 2: ["candidate"]})
    result = lifecycle.promote(client, "day13-chat", 2)

    assert client.updated == [{"version": 2, "new_labels": ["production"]}]
    before = {entry["label"]: entry.get("version") for entry in result["before"]["labels"]}
    after = {entry["label"]: entry.get("version") for entry in result["after"]["labels"]}
    assert before["production"] == 1
    assert after["production"] == 2
    assert after["baseline"] == 1, "rollback can label baseline giu nguyen o v1"


def test_rollback_returns_production_to_the_baseline_version() -> None:
    client = FakeClient({1: ["baseline"], 2: ["candidate", "production"]})
    version = lifecycle._resolve_baseline_version(client, "day13-chat")
    lifecycle.promote(client, "day13-chat", version)

    state = lifecycle.snapshot(client, "day13-chat")
    by_label = {entry["label"]: entry["version"] for entry in state["labels"]}
    assert by_label["production"] == 1
    assert by_label["candidate"] == 2


def test_rollback_without_baseline_label_fails_loudly() -> None:
    with pytest.raises(lifecycle.PromptContractError):
        lifecycle._resolve_baseline_version(FakeClient({1: ["production"]}), "day13-chat")


def test_write_evidence_produces_readable_json(tmp_path: Path) -> None:
    client = FakeClient({1: ["baseline", "production"], 2: ["candidate"]})
    target = tmp_path / "nested" / "prompt-status.json"
    lifecycle.write_evidence(lifecycle.snapshot(client, "day13-chat"), target)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["prompt_name"] == "day13-chat"
    assert {entry["label"] for entry in payload["labels"]} == set(lifecycle.TRACKED_LABELS)


def test_load_queries_cycles_when_more_traces_are_requested(tmp_path: Path) -> None:
    path = tmp_path / "queries.jsonl"
    path.write_text(
        '{"user_id":"u1","session_id":"s1","feature":"qa","message":"a"}\n'
        '{"user_id":"u2","session_id":"s2","feature":"qa","message":"b"}\n',
        encoding="utf-8",
    )

    assert len(trace_evidence.load_queries(path, None)) == 2
    cycled = trace_evidence.load_queries(path, 5)
    assert [row["user_id"] for row in cycled] == ["u1", "u2", "u1", "u2", "u1"]
