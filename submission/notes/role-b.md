# Vai trò B — Tracing & Prompt Version

Bàn giao cho D để đưa vào `submission/REPORT.md` §4 (và một phần §3). Không ghi
trực tiếp vào `REPORT.md` theo quy ước trong [docs/TEAM_ASSIGNMENT.md](../../docs/TEAM_ASSIGNMENT.md).

Project Langfuse: `cloud.langfuse.com`, project id `cmsocq40u01lyad0duqx8wy1t`.

## 1. Đã làm

| Việc | Trạng thái | Bằng chứng |
|---|---|---|
| Cấu hình Langfuse, `auth_check()` pass | Xong | `prompt-status.json` |
| Prompt `day13-chat` v1, labels `baseline` + `production` | Xong | `prompt-ensure.json` |
| Prompt `day13-chat` v2, label `candidate` | Xong | `prompt-ensure.json` |
| Chạy cùng input với 2 label | Xong | 10 trace trong `traces.jsonl` |
| Đổi label `production` → v2 | Xong | `prompt-promote-v2.json` |
| Rollback `production` → v1 | Xong | `prompt-promote-rollback.json` |
| ≥ 10 trace có metadata | Xong (12 trace ghi lại, 15 trace trên project) | `traces.jsonl` |
| Mọi trace `prompt_source=langfuse` | Xong, 0 fallback | `traces.jsonl` |
| Nối được Logs ↔ Traces | Xong (thêm mới, xem §4) | trace `01971248bfd82ff06d2b171e4619487a` |

## 2. Prompt versioning

Prompt name `day13-chat`, type `text`, giữ nguyên ba biến `{{feature}} {{docs}} {{message}}`.

- **v1 (baseline)** — đúng `DEFAULT_PROMPT_TEMPLATE` mà app dùng khi chạy local, để v1 và v2 chỉ khác đúng phần thay đổi.
- **v2 (candidate)** — thêm 1 dòng chỉ dẫn format: `You are an observability assistant. Answer in at most three sentences and name the document you used.`

Trạng thái label cuối buổi:

```
production  version 1  labels=['baseline', 'production']
baseline    version 1  labels=['baseline', 'production']
candidate   version 2  labels=['candidate', 'latest']
```

Nội dung prompt của từng version nằm trong `prompt-ensure.json` nên chấm được mà không cần mở UI.

## 3. Trace ID

Hai trace chứng minh hai version/label khác nhau — dùng cặp này cho §4 của report:

| Mục đích | Label | Version | Trace ID |
|---|---|---|---|
| **Baseline** | `baseline` | v1 | `09a7b41e6623e8a26ff77b625f6be806` |
| **Candidate** | `candidate` | v2 | `bdbb5717ebda49f38c2ab0efd1c57759` |
| **Sau khi đổi label** | `production` | v2 | `545be89e8741bdd21875975fffc29761` |
| **Sau khi rollback** | `production` | v1 | `9c7bead5ed32fbf7206ddf8ff5edc1b5` |

Ba trace cuối là bằng chứng rollback: cùng label `production` nhưng version đổi từ 1 → 2 → 1, và request thật sau mỗi lần đổi đã lấy đúng version tương ứng. Danh sách đủ 12 trace kèm latency/token/cost nằm trong `submission/evidence/traces.jsonl`.

URL mẫu: `https://cloud.langfuse.com/project/cmsocq40u01lyad0duqx8wy1t/traces/<trace_id>`

## 4. Thay đổi code — cầu nối Logs ↔ Traces

Sau khi vai trò A merge, tôi kiểm tra và phát hiện **log và trace không có khoá chung theo từng request**: log có `correlation_id`, trace có `session_id` + `user_id_hash`. Với challenge, mỗi query một session nên tạm nối được, nhưng hai request cùng session thì không phân biệt được — trong khi `RULES.md` bắt buộc mọi kết luận phải kèm trace ID hoặc log line cụ thể.

Sửa trong `app/agent.py` (file của vai trò B, không đụng file của A):

1. Đọc `correlation_id` từ structlog contextvars mà middleware của A đã bind.
2. Gắn tag `cid:<correlation_id>` lên trace → tìm được trace từ một dòng log ngay trên UI Langfuse.
3. Thêm `correlation_id` vào generation metadata.
4. `AgentResult` trả thêm `prompt_name/label/version/source`, `correlation_id`, `trace_id` (đều có default nên không phá caller nào).

Không sửa `update_current_trace(metadata=...)` để public test `test_agent_prompt_trace.py` giữ nguyên assert 4 khoá.

Kiểm chứng end-to-end với Langfuse thật:

```
correlation_id tu response header: req-990aada2
log line   : response_sent | req-990aada2 | 1147 ms
trace tim duoc bang tag cid: 01971248bfd82ff06d2b171e4619487a
  tags     : ['cid:req-990aada2', 'claude-sonnet-4-5', 'lab', 'monitoring']
  metadata : prompt_name=day13-chat, prompt_label=production, prompt_version=1,
             prompt_source=langfuse, correlation_id=req-990aada2
```

## 5. Cách chạy lại

```bash
python scripts/prompt_lifecycle.py status              # version dang gan voi tung label
python scripts/prompt_lifecycle.py ensure              # tao v1 + v2 (idempotent)
python scripts/prompt_lifecycle.py promote --version 2 # doi production sang v2
python scripts/prompt_lifecycle.py promote --to-baseline  # rollback

python scripts/trace_evidence.py --label baseline --count 5
python scripts/trace_evidence.py --label candidate --count 5
python scripts/trace_evidence.py --find-cid req-990aada2   # log -> trace
```

`trace_evidence.py` chạy agent trong tiến trình nên **không ghi vào `data/logs.jsonl`** — không đụng dữ liệu dashboard của C, không cần API đang chạy.

Cả hai script tự vô hiệu cache prompt 60 giây của SDK, nên `status` và request ngay sau khi đổi label luôn đọc trạng thái thật.

## 6. Việc cần nhờ vai trò khác

**Gửi A — một dòng, không bắt buộc:** `AgentResult` giờ có `result.trace_id`. Nếu A thêm vào log `response_sent`:

```python
log.info("response_sent", ..., trace_id=result.trace_id)
```

thì chiều Traces → Logs cũng tra được trực tiếp, không phải search tag. Chiều Logs → Traces đã chạy sẵn.

**Gửi A — một cảnh báo nhỏ, đã tái hiện được:** `_scrub_value` scrub toàn bộ event_dict, mà pattern `cccd` là `\b\d{12}\b`. `hash_user_id()` trả 12 ký tự hex, nên hash nào rơi vào trường hợp toàn chữ số sẽ bị nuốt:

```python
>>> hash_user_id("user-258")
'389011725167'
>>> scrub_event(None, "info", {"event": "response_sent", "user_id_hash": "389011725167"})
{'event': 'response_sent', 'user_id_hash': '[REDACTED_CCCD]'}
```

Xác suất khoảng 0,5% mỗi user (`(10/16)^12`). Không làm rớt `validate_logs.py` vì khoá vẫn tồn tại, nhưng làm mất khả năng nhóm log theo user. Cách xử lý gọn nhất là bỏ qua các khoá đã hash (`user_id_hash`) khi scrub.

**Gửi D:** dùng `--find-cid` để lấy trace ID từ log line của challenge; đó chính là bước "Logs → Traces" trong demo.

## 7. Chuẩn bị trả lời khi chấm (rubric B1)

- **Correlation ID khác trace ID thế nào?** Correlation ID do middleware của app sinh, sống trong log và response header, dùng để nối các dòng log của cùng một request. Trace ID do Langfuse sinh, sống trong hệ thống tracing, dùng để xem cây span. Hai không gian tách nhau — nên tôi phải chủ động gắn tag `cid:` để bắc cầu.
- **`prompt_source` khác nhau thế nào?** `langfuse` = lấy được prompt managed thật. `local` = chưa bật Langfuse (thiếu key). `local-fallback` = đã bật nhưng fetch lỗi hoặc SDK trả fallback — trace vẫn ghi rõ để không giả vờ là managed prompt.
- **Vì sao rollback bằng label chứ không sửa prompt?** Label chỉ là con trỏ; đổi label không tạo version mới và không xoá lịch sử, nên rollback là thao tác một bước và luôn quay lại đúng nội dung cũ. Langfuse tự gỡ label khỏi version cũ nên không bao giờ có hai version cùng giữ `production`.
- **Cache 60 giây ảnh hưởng gì?** `resolve_prompt` gọi `get_prompt(cache_ttl_seconds=60)`, nên ngay sau khi đổi label, request vẫn có thể dùng version cũ tới 60 giây. Script chủ động invalidate cache để evidence phản ánh đúng thời điểm.
- **Vì sao app vẫn chạy khi Langfuse chết?** `resolve_prompt` có fallback local và bọc try/except, `fetch_timeout_seconds=2`, `max_retries=0` — observability không được phép làm sập đường request.
