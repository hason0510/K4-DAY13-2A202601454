# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm:
- Repository URL:
- Commit SHA cuối:
- Thành viên và vai trò:

## 2. Kết quả kỹ thuật

- Điểm `validate_logs.py`: 100/100
- Tổng số traces:
- Số PII leak còn lại: 0
- Link/đường dẫn dashboard:

## 3. Logging và tracing

- Evidence correlation ID: [`evidence/role1-redacted-log.json`](evidence/role1-redacted-log.json) (`req-cafebabe`)
- Evidence PII redaction: [`evidence/role1-redacted-log.json`](evidence/role1-redacted-log.json) và [kết quả validator](evidence/role1-validation.txt)
- Evidence trace waterfall:
- Giải thích một span đáng chú ý:

## 4. Prompt versioning

- Prompt name:
- Version/label baseline:
- Version/label candidate:
- Trace ID của mỗi version:
- Bằng chứng đổi label hoặc rollback:

## 5. Dashboard, SLO và alerts

- Kết quả `validate_dashboard.py`:
- Evidence dashboard:
- SLO đã chọn và lý do:
- Alert rules và runbook:

## 6. Điều tra challenge

- Challenge ID: day13-k4-observability-v1
- Triệu chứng từ metrics: P95 latency tăng vọt > 2000ms, hệ thống xử lý các request bị nghẽn và thời gian phản hồi tăng lên tới ~14.8s (ở chế độ đồng thời).
- Trace ID liên quan: req-c960ff3a (hoặc req-78353376)
- Log line/correlation ID liên quan: correlation_id="req-c960ff3a", sự kiện request_received và response_sent ghi nhận latency_ms=3549.
- Root cause: Incident `rag_slow` được kích hoạt làm hàm `retrieve()` trong `app/mock_rag.py` gọi `time.sleep(2.5)`. Vì sử dụng hàm sleep đồng bộ (`time.sleep`) trong event loop, nó gây ra tình trạng block toàn bộ hệ thống (head-of-line blocking), khiến các request chạy song song bị tắc nghẽn dây chuyền.
- Fix action: Tắt incident bằng cách chạy `python scripts/inject_incident.py --disable` hoặc gỡ bỏ đoạn code block luồng `time.sleep` ra khỏi `mock_rag.py`.
- Preventive measure: Thiết lập Alert cho P95 Latency; rà soát source code để đảm bảo không sử dụng code blocking (như `time.sleep`) trong hàm xử lý, thay vào đó dùng `asyncio.sleep()` hoặc offload sang thread pool.

## 7. Đóng góp cá nhân

Với mỗi thành viên, ghi rõ nhiệm vụ và link commit/PR tương ứng.

| Thành viên | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|
| | | | |
