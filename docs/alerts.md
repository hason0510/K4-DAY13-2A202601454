# Alert và Runbook

Các alert trong tài liệu này bám theo SLI/SLO của hệ thống. Quá trình điều tra phải sử dụng bằng chứng theo luồng Metrics → Traces → Logs trước khi kết luận root cause.

## Alert 1

- Tên: High P95 Latency
- Severity: Warning
- SLI/SLO liên quan: `latency_p95_ms <= 3000`
- Điều kiện và thời gian duy trì: `latency_p95_ms > 3000` liên tục trong 5 phút.
- Ảnh hưởng tới người dùng: Người dùng phải chờ lâu để nhận phản hồi; request có thể timeout hoặc bị gửi lại.

### Ba bước kiểm tra đầu tiên

1. Mở panel Latency, xác nhận P95 vượt 3000 ms và ghi lại khoảng thời gian xảy ra.
2. Mở một trace chậm trong khoảng thời gian đó, kiểm tra waterfall để xác định span retrieval, LLM hoặc thành phần nào chiếm nhiều thời gian nhất.
3. Dùng correlation ID của trace để tìm log liên quan và kiểm tra `latency_ms`, `feature`, `model` cùng các lỗi hoặc metadata bất thường.

- Mitigation tạm thời: Bật cache hoặc fallback, giảm công việc không cần thiết trong request và giới hạn timeout để tránh request bị treo.
- Điều kiện khôi phục: P95 trở lại dưới 3000 ms liên tục ít nhất 10 phút.
- Owner: `observability-owner`

## Alert 2

- Tên: High Error Rate
- Severity: Critical
- SLI/SLO liên quan: `error_rate_pct <= 2`
- Điều kiện và thời gian duy trì: `error_rate_pct > 2` liên tục trong 5 phút.
- Ảnh hưởng tới người dùng: Nhiều request thất bại và người dùng không nhận được câu trả lời.

### Ba bước kiểm tra đầu tiên

1. Mở panel Errors, xác nhận error rate vượt 2% và xem breakdown theo `error_type`.
2. Mở một trace thất bại trong cùng khoảng thời gian, xác định span đầu tiên báo lỗi.
3. Dùng correlation ID để tìm log `request_failed`, kiểm tra `error_type`, feature bị ảnh hưởng và chi tiết lỗi đã được redact.

- Mitigation tạm thời: Rollback thay đổi gần nhất, tắt tạm tính năng gây lỗi hoặc chuyển sang fallback an toàn.
- Điều kiện khôi phục: Error rate trở lại dưới 2% liên tục ít nhất 10 phút.
- Owner: `api-owner`

## Alert 3

- Tên: Daily Cost Budget Exceeded
- Severity: Warning
- SLI/SLO liên quan: `daily_cost_usd <= 2.5`
- Điều kiện và thời gian duy trì: `daily_cost_usd > 2.5` liên tục trong 15 phút.
- Ảnh hưởng tới người dùng: Không gây lỗi trực tiếp nhưng có thể buộc nhóm giới hạn traffic, giảm quota hoặc tắt tính năng nếu ngân sách tiếp tục tăng.

### Ba bước kiểm tra đầu tiên

1. Mở panel Cost và Traffic để xác định chi phí tăng do traffic tăng hay cost trên mỗi request tăng.
2. Kiểm tra panel Tokens, sau đó mở các trace có `tokens_in`, `tokens_out` hoặc cost cao bất thường.
3. Dùng correlation ID để tìm log `response_sent`, so sánh `feature`, `model`, `tokens_in`, `tokens_out` và `cost_usd`.

- Mitigation tạm thời: Giới hạn output token, áp dụng rate limit, dùng prompt ngắn hơn hoặc chuyển sang model có chi phí thấp hơn sau khi kiểm tra chất lượng.
- Điều kiện khôi phục: Chi phí dự báo trở lại trong ngân sách và không còn request có token/cost bất thường trong ít nhất 30 phút.
- Owner: `cost-owner`
