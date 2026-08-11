# Day 13 Runtime Dashboard

Dashboard này đọc trực tiếp `data/logs.jsonl`, chỉ giữ dữ liệu trong 60 phút
gần nhất và tự refresh mỗi 30 giây.

## Cài đặt

Từ thư mục gốc của repository:

```powershell
pip install -r requirements.txt
pip install -r dashboard\requirements.txt
```

## Chạy dashboard

```powershell
streamlit run dashboard\app.py
```

Dashboard vẫn hiển thị đủ sáu panel khi chưa có log. Sau khi API và load test
tạo `data/logs.jsonl`, các panel tự động hiển thị dữ liệu thật.

## Sáu panel theo contract

| Panel | Nguồn | Phép tổng hợp | Threshold |
|---|---|---|---|
| Latency | `response_sent.latency_ms` | P50, P95, P99 | P95 ≤ 3000 ms |
| Traffic | `request_received` | Count, rate/minute | ≥ 1 request/minute |
| Errors | `request_failed`, `error_type` | Error rate, breakdown | ≤ 2% |
| Cost | `response_sent.cost_usd` | Sum/minute, total | ≤ 2.5 USD |
| Tokens | `response_sent.tokens_in/tokens_out` | Sum by field | ≤ 50,000 |
| Quality | `response_sent.quality_score` | Mean | ≥ 0.75 |

## Evidence cần chụp

1. Chạy baseline load test và chụp toàn bộ sáu panel.
2. Bật challenge `rag_slow` và chạy lại load test cùng concurrency.
3. Chụp panel Latency khi P95 tăng và giữ ảnh toàn dashboard nếu có thể.
4. Lưu ảnh vào `submission/evidence/` và dẫn đường dẫn tương đối trong report.
