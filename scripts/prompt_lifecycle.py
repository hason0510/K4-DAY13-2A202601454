"""Quản lý vòng đời prompt trên Langfuse — vai trò B (Tracing & Prompt Version).

Script làm đúng các bước trong docs/PROMPT_VERSIONING.md và ghi lại evidence
kiểm chứng được, thay vì thao tác tay trên UI rồi chỉ chụp màn hình.

    python scripts/prompt_lifecycle.py status
    python scripts/prompt_lifecycle.py ensure
    python scripts/prompt_lifecycle.py promote --version 2
    python scripts/prompt_lifecycle.py promote --to-baseline   # rollback

Prompt không bao giờ bị ghi đè: Langfuse tạo version mới cho mỗi lần create,
và label chỉ được trỏ lại chứ không xoá lịch sử.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.prompt_management import DEFAULT_PROMPT_TEMPLATE

REQUIRED_VARIABLES = ("{{feature}}", "{{docs}}", "{{message}}")
TRACKED_LABELS = ("production", "baseline", "candidate")
EVIDENCE_DIR = REPO_ROOT / "submission" / "evidence"

# v1 giữ nguyên template mà app dùng khi chạy local, để so sánh v1/v2 chỉ khác
# đúng phần thay đổi của candidate.
BASELINE_PROMPT = DEFAULT_PROMPT_TEMPLATE

# v2 thay đổi nhỏ về format/độ dài theo yêu cầu của PROMPT_VERSIONING.md.
CANDIDATE_PROMPT = (
    "You are an observability assistant. Answer in at most three sentences "
    "and name the document you used.\n" + DEFAULT_PROMPT_TEMPLATE
)


class PromptContractError(ValueError):
    """Prompt vi phạm contract ba biến của lab."""


def require_variables(text: str, *, what: str) -> str:
    """Chặn việc đẩy lên Langfuse một prompt thiếu biến app đang compile."""
    missing = [variable for variable in REQUIRED_VARIABLES if variable not in text]
    if missing:
        raise PromptContractError(f"{what} thiếu biến bắt buộc: {', '.join(missing)}")
    return text


def _invalidate_cache(client: Any, name: str) -> None:
    """Bỏ cache 60 giây của SDK để status/promote luôn đọc trạng thái thật."""
    cache = getattr(getattr(client, "_resources", None), "prompt_cache", None)
    invalidate = getattr(cache, "invalidate", None)
    if callable(invalidate):
        invalidate(name)


def fetch_by_label(client: Any, name: str, label: str) -> dict[str, Any]:
    """Đọc prompt theo label. Không truyền fallback để label thiếu thì lộ ra."""
    try:
        prompt = client.get_prompt(name, label=label, type="text", cache_ttl_seconds=0)
    except Exception as exc:  # SDK ném nhiều loại lỗi khác nhau khi label chưa có
        return {"label": label, "found": False, "error": type(exc).__name__}
    return {
        "label": label,
        "found": True,
        "version": prompt.version,
        "labels": sorted(getattr(prompt, "labels", []) or []),
        "prompt": prompt.prompt,
    }


def snapshot(client: Any, name: str) -> dict[str, Any]:
    _invalidate_cache(client, name)
    return {
        "prompt_name": name,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "labels": [fetch_by_label(client, name, label) for label in TRACKED_LABELS],
    }


def print_snapshot(state: dict[str, Any]) -> None:
    print(f"Prompt: {state['prompt_name']}  ({state['checked_at']})")
    for entry in state["labels"]:
        if not entry["found"]:
            print(f"  - {entry['label']:<11} CHUA CO ({entry['error']})")
            continue
        print(
            f"  - {entry['label']:<11} version {entry['version']}"
            f"  labels={entry['labels']}"
        )


def display_path(path: Path) -> str:
    """Rút gọn theo repo khi có thể; --evidence vẫn nhận đường dẫn ngoài repo."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def write_evidence(state: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Evidence: {display_path(path)}")
    return path


def ensure(client: Any, name: str) -> dict[str, Any]:
    """Tạo v1 (baseline + production) và v2 (candidate) nếu chưa tồn tại."""
    require_variables(BASELINE_PROMPT, what="BASELINE_PROMPT")
    require_variables(CANDIDATE_PROMPT, what="CANDIDATE_PROMPT")
    _invalidate_cache(client, name)

    actions: list[str] = []
    if fetch_by_label(client, name, "baseline")["found"]:
        actions.append("baseline da ton tai, bo qua")
    else:
        created = client.create_prompt(
            name=name,
            prompt=BASELINE_PROMPT,
            type="text",
            labels=["baseline", "production"],
            commit_message="Day 13 lab v1 - template goc",
        )
        actions.append(f"tao version {created.version} voi labels baseline+production")

    _invalidate_cache(client, name)
    if fetch_by_label(client, name, "candidate")["found"]:
        actions.append("candidate da ton tai, bo qua")
    else:
        created = client.create_prompt(
            name=name,
            prompt=CANDIDATE_PROMPT,
            type="text",
            labels=["candidate"],
            commit_message="Day 13 lab v2 - gioi han 3 cau va trich dan doc",
        )
        actions.append(f"tao version {created.version} voi label candidate")

    for action in actions:
        print(f"[ensure] {action}")
    return snapshot(client, name)


def promote(client: Any, name: str, version: int, label: str = "production") -> dict[str, Any]:
    """Trỏ một label sang version khác. Langfuse tự gỡ label khỏi version cũ."""
    before = snapshot(client, name)
    client.update_prompt(name=name, version=version, new_labels=[label])
    _invalidate_cache(client, name)
    after = snapshot(client, name)
    print(f"[promote] {label} -> version {version}")
    return {"action": f"promote {label} to v{version}", "before": before, "after": after}


def _resolve_baseline_version(client: Any, name: str) -> int:
    entry = fetch_by_label(client, name, "baseline")
    if not entry["found"]:
        raise PromptContractError(
            "Chua co label 'baseline'. Chay 'prompt_lifecycle.py ensure' truoc."
        )
    return int(entry["version"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--name",
        default=None,
        help="Prompt name; mac dinh lay tu LANGFUSE_PROMPT_NAME hoac 'day13-chat'.",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=None,
        help="Duong dan file evidence JSON; mac dinh nam trong submission/evidence/.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="In version dang gan voi tung label")
    sub.add_parser("ensure", help="Tao v1 (baseline+production) va v2 (candidate)")

    promote_parser = sub.add_parser("promote", help="Doi label sang version khac")
    target = promote_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--version", type=int, help="Version dich")
    target.add_argument(
        "--to-baseline",
        action="store_true",
        help="Rollback: tra label ve dung version dang giu label 'baseline'",
    )
    promote_parser.add_argument("--label", default="production")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    args = build_parser().parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:  # pragma: no cover - dotenv nam trong requirements
        pass

    import os

    from app.tracing import tracing_enabled

    name = args.name or os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    if not tracing_enabled():
        print(
            "KHONG CHAY DUOC: thieu LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY.\n"
            "Prompt versioning bat buoc phai co Langfuse; xem SETUP.md muc 2."
        )
        return 1

    from langfuse import get_client

    client = get_client()
    if not client.auth_check():
        print("KHONG CHAY DUOC: Langfuse tu choi cap key hien tai.")
        return 1

    try:
        if args.command == "status":
            state = snapshot(client, name)
            print_snapshot(state)
            write_evidence(state, args.evidence or EVIDENCE_DIR / "prompt-status.json")
        elif args.command == "ensure":
            state = ensure(client, name)
            print_snapshot(state)
            write_evidence(state, args.evidence or EVIDENCE_DIR / "prompt-ensure.json")
        else:
            version = (
                _resolve_baseline_version(client, name)
                if args.to_baseline
                else int(args.version)
            )
            result = promote(client, name, version, label=args.label)
            print_snapshot(result["after"])
            suffix = "rollback" if args.to_baseline else f"v{version}"
            write_evidence(
                result,
                args.evidence or EVIDENCE_DIR / f"prompt-promote-{suffix}.json",
            )
    except PromptContractError as exc:
        print(f"KHONG HOP LE: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
