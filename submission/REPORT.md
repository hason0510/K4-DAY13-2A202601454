# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm: **ChillGuys**
- Repository URL: https://github.com/hason0510/K4-DAY13-2A202601454
- Commit SHA cuối: 52f0a0853fe9da20a5040bb95b17cb75f49b5150
- Thành viên và vai trò:

| Thành viên | MSSV | Vai trò | Tài khoản Git |
|---|---|---|---|
| Nguyễn Thành Vinh | 2A202601556 | A — Logging & PII | `vinz0369` |
| Bế Nguyễn Hà Sơn | 2A202601454 | B — Tracing & Prompt Version | `hason123` |
| Phạm Tùng Dương | 2A202601404 | C — Dashboard, SLO & Alert | `PhamDuong2705` |
| Hồ Lương An | 2A202601332 | D — Incident, Report & Demo | `holuonganwork` |

## 2. Kết quả kỹ thuật

- Điểm `validate_logs.py`: 100/100 — xem [`evidence/role1-validation.txt`](evidence/role1-validation.txt)
- Tổng số traces: 137 trace trên project Langfuse `cmsocq40u01lyad0duqx8wy1t`, tất cả gắn tag `lab`; 12 trace chính thức được ghi kèm metadata trong [`evidence/traces.jsonl`](evidence/traces.jsonl)
- Số PII leak còn lại: 0
- Link/đường dẫn dashboard: chạy cục bộ bằng `streamlit run dashboard\app.py` (mặc định `http://localhost:8501`); nguồn dữ liệu là `data/logs.jsonl` theo contract trong [`config/dashboard.yaml`](../config/dashboard.yaml)

## 3. Logging và tracing

- Evidence correlation ID: [`evidence/role1-redacted-log.json`](evidence/role1-redacted-log.json) (`req-cafebabe`)
- Evidence PII redaction: [`evidence/role1-redacted-log.json`](evidence/role1-redacted-log.json) và [kết quả validator](evidence/role1-validation.txt)
- Evidence trace waterfall: trace `ec7da60f077222ecf258f290ab839294` (bình thường) và `becbc33db72e2c6e6b0ecfe898798bab` (lúc `rag_slow`). Mỗi trace có 4 span lồng nhau: `chat` → `run` → (`retrieve`, `llm_generate`).
- Giải thích một span đáng chú ý: span `retrieve`. Lúc bình thường span này mất 0 ms; khi incident `rag_slow` bật, nó nhảy lên **2500 ms** trong khi `llm_generate` vẫn giữ nguyên 151 ms. Đây là span cho phép khẳng định nút thắt nằm ở bước retrieval chứ không phải ở LLM — nếu trace chỉ có một span bao trọn request thì không phân biệt được hai khả năng này.

Liên kết Logs ↔ Traces: mỗi trace được gắn tag `cid:<correlation_id>` và `correlation_id` cũng nằm trong metadata của generation, nên từ một dòng log tra ngược ra trace bằng:

```bash
python scripts/trace_evidence.py --find-cid req-c960ff3a
```

## 4. Prompt versioning

- Prompt name: `day13-chat` (text prompt, giữ nguyên ba biến `{{feature}}`, `{{docs}}`, `{{message}}`)
- Version/label baseline: **v1** — labels `baseline` + `production`. Nội dung đúng `DEFAULT_PROMPT_TEMPLATE` mà app dùng khi chạy local.
- Version/label candidate: **v2** — label `candidate`. Khác v1 đúng một dòng chỉ dẫn format: *"You are an observability assistant. Answer in at most three sentences and name the document you used."*
- Trace ID của mỗi version:
  - baseline v1: `d73ff9d0fb4b4fc3281926406ebcd80d`
  - candidate v2: `9058c071628cebe9f147b5645f35cda1`
- Bằng chứng đổi label hoặc rollback: `production` được chuyển sang v2 rồi rollback về v1, mỗi lần đều chạy một request thật để xác nhận version được áp dụng đúng:

| Bước | Label | Version | Trace ID | Evidence |
|---|---|---|---|---|
| Trước khi đổi | `production` | v1 | — | [`evidence/prompt-ensure.json`](evidence/prompt-ensure.json) |
| Sau khi đổi label | `production` | v2 | `0cdec6c7a56f755d01c8ce0cea3e5a97` | [`evidence/prompt-promote-v2.json`](evidence/prompt-promote-v2.json) |
| Sau khi rollback | `production` | v1 | `f13649989e9e8e3895e8b70d2a5cea5d` | [`evidence/prompt-promote-rollback.json`](evidence/prompt-promote-rollback.json) |

Mỗi file evidence ghi lại trạng thái label **trước và sau** thao tác, đọc trực tiếp từ Langfuse API nên kiểm chứng được mà không cần mở UI. Toàn bộ 12 trace đều có `prompt_source=langfuse`, không có trace nào rơi về `local-fallback`.

Thao tác thực hiện bằng `scripts/prompt_lifecycle.py`:

```bash
python scripts/prompt_lifecycle.py status
python scripts/prompt_lifecycle.py promote --version 2      # doi label
python scripts/prompt_lifecycle.py promote --to-baseline    # rollback
```

## 5. Dashboard, SLO và alerts

- Kết quả `validate_dashboard.py`: `HỢP LỆ: 6/6 panel có trong dashboard contract.` — xem [`evidence/dashboard-validator.png`](evidence/dashboard-validator.png)
- Evidence dashboard: baseline tại [`evidence/dashboard-baseline-latency.png`](evidence/dashboard-baseline-latency.png); lúc incident tại [`evidence/dashboard-rag-slow-overview.png`](evidence/dashboard-rag-slow-overview.png) cùng ba ảnh chi tiết [`01-latency-traffic`](evidence/dashboard-rag-slow-01-latency-traffic.png), [`02-errors-cost`](evidence/dashboard-rag-slow-02-errors-cost.png), [`03-tokens-quality`](evidence/dashboard-rag-slow-03-tokens-quality.png). Dashboard dựng bằng Streamlit (`dashboard/app.py`), đọc `data/logs.jsonl`, time range 60 phút, refresh 30 giây.
- SLO đã chọn và lý do (`config/slo.yaml`, cửa sổ 28 ngày):

| SLI | Mục tiêu | Target | Lý do |
|---|---|---|---|
| `latency_p95_ms` | ≤ 3000 ms | 99.5% | P95 dưới 3000 ms giúp phần lớn người dùng nhận phản hồi trong thời gian chấp nhận được |
| `error_rate_pct` | ≤ 2% | 99.0% | Giữ độ tin cậy của API |
| `daily_cost_usd` | ≤ 2.5 USD | 100% | Kiểm soát chi phí vận hành |
| `quality_score_avg` | ≥ 0.75 | 95% | Phát hiện sớm phản hồi kém chất lượng |

- Alert rules và runbook: ba alert trong [`config/alert_rules.yaml`](../config/alert_rules.yaml), mỗi alert có điều kiện kèm thời gian duy trì, severity và owner; runbook tương ứng trong [`docs/alerts.md`](../docs/alerts.md).

| Alert | Severity | Điều kiện | Owner |
|---|---|---|---|
| `high_p95_latency` | warning | `latency_p95_ms > 3000 for 5m` | observability-owner |
| `high_error_rate` | critical | `error_rate_pct > 2 for 5m` | api-owner |
| `daily_cost_budget_exceeded` | warning | `daily_cost_usd > 2.5 for 15m` | cost-owner |

## 6. Điều tra challenge

- Challenge ID: day13-k4-observability-v1
- Triệu chứng từ metrics: P95 latency tăng vọt > 2000ms, hệ thống xử lý các request bị nghẽn và thời gian phản hồi tăng lên tới ~14.8s (ở chế độ đồng thời).
- Trace ID liên quan: `4e38c2300b16d7d932e6ed893d5392a0` (correlation_id `req-c960ff3a`) và `915140a41c1f03fff133e10e322a60f2` (correlation_id `req-78353376`). Tra ngược từ log sang trace bằng `python scripts/trace_evidence.py --find-cid req-c960ff3a`.
- Log line/correlation ID liên quan: `correlation_id="req-c960ff3a"`, cặp sự kiện `request_received` và `response_sent` với `latency_ms=3549` — trích nguyên văn trong [`evidence/challenge-trace.json`](evidence/challenge-trace.json).
- Bằng chứng ở lớp trace: trong trace `rag_slow`, span `retrieve` mất **2500 ms** còn span `llm_generate` chỉ **151 ms** — retrieval chiếm ~94% thời gian request. Đây là bước khoanh vùng, xác nhận nút thắt không nằm ở LLM.
- Root cause: Incident `rag_slow` làm `retrieve()` trong `app/mock_rag.py` gọi `time.sleep(2.5)`. Endpoint `/chat` trong `app/main.py` khai báo `async def` nên chạy trực tiếp trên event loop; một lời gọi blocking đồng bộ ở đó chặn cả loop, khiến các request đồng thời bị xếp hàng (head-of-line blocking). Hệ quả: một request phía server mất ~3,5 s nhưng client chạy `--concurrency 5` quan sát thấy tới ~14,8 s.
- Fix action: đưa lời gọi blocking ra khỏi event loop — đổi `async def chat(...)` thành `def chat(...)` để FastAPI tự chạy trong threadpool, hoặc giữ `async def` và bọc `agent.run(...)` bằng `starlette.concurrency.run_in_threadpool`. Trong phạm vi lab, tắt incident bằng `python scripts/inject_incident.py --scenario rag_slow --disable`; lưu ý đây là gỡ đoạn giả lập sự cố, không phải sửa nguyên nhân.
- Preventive measure:
  1. Alert `high_p95_latency` (`latency_p95_ms > 3000 for 5m`) đã cấu hình sẵn trong `config/alert_rules.yaml` để phát hiện triệu chứng sớm.
  2. Rà soát để không còn lời gọi blocking (`time.sleep`, I/O đồng bộ) trong các handler `async def`; dùng `asyncio.sleep` hoặc offload sang threadpool.
  3. Giữ span riêng cho từng bước (`retrieve`, `llm_generate`) để lần sau khoanh vùng được ngay từ trace thay vì phải đoán.

## 7. Đóng góp cá nhân

Với mỗi thành viên, ghi rõ nhiệm vụ và link commit/PR tương ứng.

| Thành viên | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|
| Nguyễn Thành Vinh — 2A202601556 | Vai trò A — Logging & PII: correlation ID middleware, enrich log context, PII redaction processor | `89b7289` | |
| Bế Nguyễn Hà Sơn — 2A202601454 | Vai trò B — Tracing & Prompt Version: prompt v1/v2 + label/rollback, span `retrieve`/`llm_generate`, cầu nối `cid:` giữa log và trace, `scripts/prompt_lifecycle.py`, `scripts/trace_evidence.py` | `51958b6` và commit span tiếp theo | Correlation ID và trace ID nằm ở hai hệ thống tách biệt; muốn nối được phải chủ động gắn khoá chung. Trace một span phẳng thì không khoanh vùng được root cause. |
| Phạm Tùng Dương — 2A202601404 | Vai trò C — Dashboard, SLO & Alert: 6 panel Streamlit, `config/slo.yaml`, `config/alert_rules.yaml`, `docs/alerts.md` | `a013ebb`, `8afa51e`, `759bf26`, `8fbb925`, `53fc166`, `3957646`, `73c3a47` | |
| Hồ Lương An — 2A202601332 | Vai trò D — Incident, Report & Demo: chạy challenge, điều tra root cause, tổng hợp report và evidence | `d21c1f6` | |
