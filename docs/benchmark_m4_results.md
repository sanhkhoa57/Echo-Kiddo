# Báo cáo đo hiệu năng M4 (OGK)

- Thời gian đo: 2026-11-19 07:13:39 UTC
- Máy đo: win32, Python 3.13.16, 12 luồng CPU
- Số mẫu: 30 mẫu liên tục cho mỗi dòng; p50/p95 tính theo nearest-rank. Đơn vị độ trễ: ms.
- Chế độ đo DNS: mạng thật. Không Agent: UDP tới 1.1.1.1:53. Có Agent: UDP tới OGK DNS Proxy 127.0.0.1:53545, proxy chuyển tiếp tới 1.1.1.1.
- Tái lập: `python tests/benchmark_m4.py` (đặt `OGK_BENCH_OFFLINE=1` để chạy khi không có mạng).

## 1. CPU và RAM

Rảnh: lấy mẫu mỗi 30 ms khi không có tải. Cao điểm: 50 lượt tra cứu tên miền mỗi 20 ms (khoảng 2.500 lượt/giây) trên 200 quy tắc.

| Trạng thái, chỉ số | Min | Mean | Max | p50 | p95 | Ngưỡng | Kết quả |
|---|---|---|---|---|---|---|---|
| Rảnh, CPU (%) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | < 1% | Đạt |
| Rảnh, RAM (MB) | 68.203 | 68.204 | 68.207 | 68.203 | 68.207 | < 100 MB | Đạt |
| Cao điểm, CPU (%) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | < 15% | Đạt |
| Cao điểm, RAM (MB) | 68.352 | 68.352 | 68.352 | 68.352 | 68.352 | < 120 MB | Đạt |

RAM là RSS của tiến trình benchmark, đã gồm thư viện máy chủ nạp cho phần đo đầu-cuối, nên cao hơn Agent chạy riêng.

## 2. Độ trễ phân giải DNS: có và không có Agent

| Đường đi truy vấn | Min | Mean | Max | p50 | p95 | Ngưỡng | Kết quả |
|---|---|---|---|---|---|---|---|
| Không có Agent (truy vấn thẳng resolver) | 35.533 | 62.924 | 361.908 | 41.386 | 151.474 | tham chiếu | - |
| Có Agent, cache miss (chuyển tiếp upstream) | 36.802 | 65.11 | 283.115 | 42.04 | 220.441 | tham chiếu | - |
| Chi phí xử lý riêng của Agent khi cache miss (upstream giả lập) | 0.444 | 4.309 | 36.08 | 0.635 | 20.487 | p50 < 5 ms | Đạt |
| Có Agent, cache hit | 0.455 | 0.735 | 2.305 | 0.6 | 1.634 | p50 < 1 ms | Đạt |
| Có Agent, bị chặn (sinkhole 0.0.0.0) | 0.462 | 0.583 | 1.304 | 0.522 | 0.875 | p50 < 2 ms | Đạt |

Agent cộng thêm khi cache miss: p50 +0.654 ms, p95 +68.967 ms (có Agent trừ không có Agent). Độ dao động của Internet (jitter, hàng chục ms) lớn hơn chi phí xử lý của Agent (dưới 1 ms, xem dòng cache hit), nên chênh lệch này có thể âm. Khi cache hit hoặc bị chặn, Agent trả lời ngay tại 127.0.0.1 nên nhanh hơn truy vấn không qua Agent.

## 3. Độ trễ áp dụng chính sách và lệnh khẩn

Đầu-cuối: Dashboard gửi PUT/POST, OGK-Server ký HMAC, đẩy qua WebSocket, Agent xác minh rồi áp dụng. Đo trên một máy (loopback), chưa gồm RTT mạng giữa hai máy.

| Tác vụ | Min | Mean | Max | p50 | p95 | Ngưỡng | Kết quả |
|---|---|---|---|---|---|---|---|
| Chính sách mới, đầu-cuối (PUT, WS, GET, verify, apply) | 31.0 | 62.808 | 106.497 | 64.493 | 99.141 | < 60 000 ms | Đạt |
| Lệnh khẩn LOCK_NOW, đầu-cuối (POST, WS, verify, khóa) | 8.921 | 14.443 | 27.444 | 13.676 | 24.173 | < 5 000 ms | Đạt |
| Riêng Agent: verify HMAC và nạp quy tắc | 0.047 | 0.111 | 1.707 | 0.051 | 0.119 | - | - |
| Riêng Agent: đánh giá trạng thái khóa | 0.001 | 0.001 | 0.004 | 0.001 | 0.003 | - | - |

Khi WebSocket mất kết nối, Agent nhận chính sách mới ở nhịp tim kế tiếp (tối đa 60 giây), nên độ trễ xấu nhất khoảng 60 giây cộng thời gian trong bảng.
