from __future__ import annotations

import time
from dataclasses import dataclass

from structlog.contextvars import get_contextvars

from . import metrics
from .mock_llm import FakeLLM
from .mock_rag import retrieve
from .pii import hash_user_id, summarize_text
from .prompt_management import resolve_prompt
from .tracing import get_langfuse_client, observe, tracing_enabled


@dataclass
class AgentResult:
    answer: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    quality_score: float
    # Prompt đã dùng cho request này. Có default để không phá caller cũ; nhờ đó
    # scripts/trace_evidence.py ghi được version thật thay vì suy đoán lại.
    prompt_name: str = ""
    prompt_label: str = ""
    prompt_version: str = ""
    prompt_source: str = ""
    # Hai đầu của cầu nối Logs <-> Traces. Rỗng khi chạy ngoài request HTTP
    # (correlation_id) hoặc khi chưa bật Langfuse (trace_id).
    correlation_id: str = ""
    trace_id: str = ""


class LabAgent:
    def __init__(self, model: str = "claude-sonnet-4-5") -> None:
        self.model = model
        self.llm = FakeLLM(model=model)

    @observe(as_type="generation", capture_input=False, capture_output=False)
    def run(self, user_id: str, feature: str, session_id: str, message: str) -> AgentResult:
        started = time.perf_counter()
        # correlation_id do CorrelationIdMiddleware bind; đọc ra để trace và log
        # có chung một khoá tra cứu theo từng request.
        correlation_id = str(get_contextvars().get("correlation_id") or "")
        docs = retrieve(message)
        langfuse_client = get_langfuse_client()
        trace_id = self._current_trace_id(langfuse_client)
        prompt = resolve_prompt(
            langfuse_client,
            feature=feature,
            docs=docs,
            message=message,
            enabled=tracing_enabled(),
        )
        response = self.llm.generate(prompt.text)
        quality_score = self._heuristic_quality(message, response.text, docs)
        latency_ms = int((time.perf_counter() - started) * 1000)
        cost_usd = self._estimate_cost(response.usage.input_tokens, response.usage.output_tokens)

        langfuse_client.update_current_trace(
            user_id=hash_user_id(user_id),
            session_id=session_id,
            # Tag `cid:` cho phép tìm đúng trace từ một dòng log trên UI Langfuse.
            tags=["lab", feature, self.model]
            + ([f"cid:{correlation_id}"] if correlation_id else []),
            metadata={
                "prompt_name": prompt.name,
                "prompt_label": prompt.label,
                "prompt_version": prompt.version,
                "prompt_source": prompt.source,
            },
        )
        langfuse_client.update_current_generation(
            model=self.model,
            metadata={
                "correlation_id": correlation_id,
                "doc_count": len(docs),
                "query_preview": summarize_text(message),
                "prompt_name": prompt.name,
                "prompt_label": prompt.label,
                "prompt_version": prompt.version,
                "prompt_source": prompt.source,
                "prompt_fetch_error": prompt.fetch_error,
            },
            usage_details={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
            },
            cost_details={"total": cost_usd},
            prompt=prompt.managed_prompt,
        )

        metrics.record_request(
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            quality_score=quality_score,
        )

        return AgentResult(
            answer=response.text,
            latency_ms=latency_ms,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            cost_usd=cost_usd,
            quality_score=quality_score,
            prompt_name=prompt.name,
            prompt_label=prompt.label,
            prompt_version=prompt.version,
            prompt_source=prompt.source,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

    @staticmethod
    def _current_trace_id(client) -> str:
        """Trace ID của span đang chạy, rỗng nếu chưa bật Langfuse."""
        getter = getattr(client, "get_current_trace_id", None)
        if not callable(getter):
            return ""
        try:
            return str(getter() or "")
        except Exception:  # pragma: no cover - không để tracing làm hỏng request
            return ""

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        input_cost = (tokens_in / 1_000_000) * 3
        output_cost = (tokens_out / 1_000_000) * 15
        return round(input_cost + output_cost, 6)

    def _heuristic_quality(self, question: str, answer: str, docs: list[str]) -> float:
        score = 0.5
        if docs:
            score += 0.2
        if len(answer) > 40:
            score += 0.1
        if question.lower().split()[0:1] and any(token in answer.lower() for token in question.lower().split()[:3]):
            score += 0.1
        if "[REDACTED" in answer:
            score -= 0.2
        return round(max(0.0, min(1.0, score)), 2)
