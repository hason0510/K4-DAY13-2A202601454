"""Sinh trace có metadata và ghi lại trace ID — vai trò B.

Script chạy agent trong tiến trình để lấy được `trace_id` ngay tại chỗ, thứ mà
`load_test.py` qua HTTP không trả về. Mỗi lượt chạy ghi một dòng JSON vào
`submission/evidence/traces.jsonl` để báo cáo dẫn lại được thay vì chép tay ID.

    python scripts/trace_evidence.py --label baseline --count 5
    python scripts/trace_evidence.py --label candidate --count 5
    python scripts/trace_evidence.py --label production --count 1 --note after-rollback

Script không ghi vào `data/logs.jsonl` nên không đụng dữ liệu dashboard của vai
trò C và không phụ thuộc việc API có đang chạy hay không.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio

DEFAULT_QUERIES = REPO_ROOT / "data" / "sample_queries.jsonl"
DEFAULT_OUT = REPO_ROOT / "submission" / "evidence" / "traces.jsonl"


def display_path(path: Path) -> str:
    """Rút gọn theo repo khi có thể; --out vẫn nhận đường dẫn ngoài repo."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def load_queries(path: Path, count: int | None) -> list[dict[str, str]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError(f"Khong co query nao trong {path}")
    if count is None:
        return rows
    # Lặp lại danh sách khi cần nhiều trace hơn số query có sẵn.
    return [rows[index % len(rows)] for index in range(count)]


def run_one(client: Any, agent: Any, query: dict[str, str], label: str, note: str) -> dict[str, Any]:
    with client.start_as_current_span(name="chat") as span:
        trace_id = client.get_current_trace_id()
        result = agent.run(
            user_id=query["user_id"],
            feature=query["feature"],
            session_id=query["session_id"],
            message=query["message"],
        )
        span.update(
            input={"feature": query["feature"]},
            output={"quality_score": result.quality_score},
        )

    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "note": note,
        "requested_label": label,
        "trace_id": trace_id,
        "trace_url": client.get_trace_url(trace_id=trace_id),
        "prompt_name": result.prompt_name,
        "prompt_label": result.prompt_label,
        "prompt_version": result.prompt_version,
        "prompt_source": result.prompt_source,
        "user_id": query["user_id"],
        "session_id": query["session_id"],
        "feature": query["feature"],
        "latency_ms": result.latency_ms,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "cost_usd": result.cost_usd,
        "quality_score": result.quality_score,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--label",
        default=None,
        help="Prompt label can chay; mac dinh lay LANGFUSE_PROMPT_LABEL trong .env.",
    )
    parser.add_argument("--count", type=int, default=None, help="So trace can sinh")
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--note",
        default="",
        help="Ghi chu ngan de phan biet cac lot chay, vi du after-rollback.",
    )
    parser.add_argument(
        "--find-cid",
        default=None,
        metavar="req-xxxxxxxx",
        help="Tra cuu trace tu mot correlation_id trong log, khong sinh trace moi.",
    )
    return parser


def find_by_correlation_id(client: Any, correlation_id: str) -> int:
    """Đi ngược từ một dòng log sang trace tương ứng qua tag `cid:`."""
    traces = client.api.trace.list(tags=[f"cid:{correlation_id}"], limit=10).data
    if not traces:
        print(
            f"Khong tim thay trace nao co tag cid:{correlation_id}.\n"
            "Kiem tra: request do co di qua API dang bat Langfuse khong, "
            "va trace da duoc ingest chua (thuong tre vai giay)."
        )
        return 1

    for trace in traces:
        metadata = trace.metadata or {}
        print(f"trace_id : {trace.id}")
        print(f"url      : {client.get_trace_url(trace_id=trace.id)}")
        print(f"session  : {trace.session_id}")
        print(
            "prompt   : "
            f"{metadata.get('prompt_name')}@{metadata.get('prompt_label')} "
            f"v{metadata.get('prompt_version')} ({metadata.get('prompt_source')})"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    args = build_parser().parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:  # pragma: no cover - dotenv nam trong requirements
        pass

    label = args.label or os.getenv("LANGFUSE_PROMPT_LABEL", "production")
    # resolve_prompt doc bien nay moi lan chay nen doi label khong can sua code.
    os.environ["LANGFUSE_PROMPT_LABEL"] = label

    from app.tracing import tracing_enabled

    if not tracing_enabled():
        print(
            "KHONG CHAY DUOC: thieu LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY.\n"
            "Khong co key thi trace se ghi prompt_source=local va khong dung lam evidence."
        )
        return 1

    from langfuse import get_client

    from app.agent import LabAgent

    client = get_client()
    if not client.auth_check():
        print("KHONG CHAY DUOC: Langfuse tu choi cap key hien tai.")
        return 1

    if args.find_cid:
        return find_by_correlation_id(client, args.find_cid)

    # Label vua doi tren UI/CLI co the con nam trong cache 60 giay cua SDK.
    cache = getattr(getattr(client, "_resources", None), "prompt_cache", None)
    if cache is not None and hasattr(cache, "invalidate"):
        cache.invalidate(os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat"))

    agent = LabAgent()
    queries = load_queries(args.queries, args.count)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    with args.out.open("a", encoding="utf-8") as sink:
        for query in queries:
            row = run_one(client, agent, query, label, args.note)
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows.append(row)
            print(
                f"[{row['prompt_source']}] {row['trace_id']} | "
                f"{row['prompt_name']}@{row['prompt_label']} v{row['prompt_version']} | "
                f"{row['latency_ms']}ms"
            )

    client.flush()

    fallbacks = [row for row in rows if row["prompt_source"] != "langfuse"]
    print(f"\nDa ghi {len(rows)} trace vao {display_path(args.out)}")
    if fallbacks:
        print(
            f"CANH BAO: {len(fallbacks)} trace co prompt_source="
            f"{sorted({row['prompt_source'] for row in fallbacks})}. "
            "Kiem tra prompt name/label truoc khi dung lam evidence."
        )
        return 1

    versions = sorted({row["prompt_version"] for row in rows})
    print(f"Prompt label '{label}' -> version {versions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
