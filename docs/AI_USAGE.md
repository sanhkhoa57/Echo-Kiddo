# Nhật Ký & Tuyên Bố Sử Dụng Trợ Lý AI (AI Usage Transparency)

> **Dự án EC - Echo Kiddo — Minh bạch quá trình sử dụng trợ lý AI**

---

## 1. Bảng Kê Chi Tiết Mức Độ Sử Dụng AI Theo Hạng Mục

| Hạng mục / Phân hệ | Công cụ AI sử dụng | Mục đích sử dụng | Phương pháp kiểm chứng & Rà soát của sinh viên |
| :--- | :--- | :--- | :--- |
| **Đặc tả kiến trúc & Tài liệu thiết kế** (`docs/*.md`) | Claude / Gemini | Tổng hợp yêu cầu từ `DoAn01.docx`, chuẩn hóa sơ đồ kiến trúc, lược đồ CSDL và bảng phân tích STRIDE/ASVS | Đối chiếu từng mục với đề bài gốc, kiểm tra lại quyết định kỹ thuật (`ADR-01` đến `ADR-03`) và tên hàm thực tế trong mã nguồn |
| **EC Server (FastAPI + SQLAlchemy)** (`server/`) | Claude / Gemini | Sinh khung API REST, mô hình dữ liệu SQLite WAL, logic ký HMAC chính sách và kiểm soát IDOR/CSRF | Chạy bộ kiểm thử `tests/test_server_api.py`, `tests/test_server_db.py`, `tests/test_schemas.py` và kiểm tra từng endpoint bằng `TestClient` |
| **EC Agent (Core, DNS Proxy, Platform)** (`agent/`) | Claude / Gemini | Cài đặt DNS Proxy `127.0.0.1:53`, Suffix Trie, bộ đếm giờ monotonic, snapshot/rollback mạng và IPC Named Pipe | Chạy `tests/test_agent_core.py`, `tests/test_dns_proxy.py`, `tests/test_agent_lifecycle.py` và kiểm tra logic khôi phục trên `ogk_cleanup.py` |
| **Danh mục tên miền mẫu** (`server/seeds/domain_catalog.json`) | Claude / Gemini | Sinh bộ dữ liệu 235 tên miền an toàn theo 6 nhóm phân loại | Chạy `tests/test_seed_catalog.py` để xác nhận nhóm `inappropriate` chỉ dùng đuôi `.test` / `.example` và 0 dương tính giả trên 20 miền giáo dục |
| **Web Dashboard & Màn hình cho trẻ** (`dashboard/`) | Claude / Gemini | Thiết kế giao diện Jinja2 + CSS + JS cho phụ huynh và màn hình minh bạch cho trẻ, tối ưu trên màn hình 390px | Chạy công cụ kiểm tra giao diện tự động, đối chiếu tên trường với `server/routers/web.py` và thử trực tiếp trên trình duyệt |
| **Kiểm thử & Kịch bản báo cáo** (`tests/`, `scripts/gen_*.py`) | Claude / Gemini | Viết unit test, test đồng bộ Phase 1, script đo hiệu năng M4 và script xuất báo cáo `.docx`/`.pdf` | Chạy `pytest` trên máy thật, rà soát số liệu đo thực tế và tự điền phần phân công đóng góp thành viên nhóm |
| **Đợt chỉnh sửa giao diện dashboard** (`dashboard/templates/`, `dashboard/static/`) | OpenAI Codex CLI (viết mã) + Claude Code (giao việc, rà soát) | Dọn CSS, nhật ký dạng thẻ trên điện thoại, phím Home/End cho tab, tiêu điểm an toàn cho hộp xác nhận xóa, hiệu ứng thanh lưu/hộp thoại, chỉnh trang đăng nhập và màn hình cho trẻ | Đọc toàn bộ diff, phát hiện và yêu cầu sửa 5 lỗi hồi quy (xem mục 2), chạy lại `pytest` trên máy thật (143/143 đạt), `node --check` cho `app.js`, so sánh với bản gốc qua `git diff` |

---

## 2. Quy Trình Đợt Chỉnh Sửa Giao Diện Bằng Codex (27/11/2026)

1. **Giao việc có giới hạn.** Codex chỉ được sửa 3 vị trí: `dashboard/templates/*.html`, `styles.css`, `app.js`. Các ràng buộc ghi rõ: giữ nguyên chuỗi tiếng Việt mà kiểm thử và đề bài dựa vào, giữ token màu, không đổi `id`/`data-*`, không thêm thư viện, không thêm tính năng theo dõi.
2. **Lưu bản gốc trước khi sửa.** Bản trước khi Codex sửa được commit riêng (`4eb58bf`), nên mọi thay đổi của Codex đều xem được bằng `git diff`.
3. **Rà soát và trả lại lỗi.** Vòng đầu có 5 lỗi hồi quy, tất cả đã được sửa ở vòng hai:
   - Biểu đồ chỉ hiện khi JavaScript chạy được (điều kiện `@supports` luôn sai).
   - Thông báo lỗi mất màu đỏ.
   - Màn hình cho trẻ mất trạng thái "hết giờ" màu đỏ.
   - Mất câu "Con luôn xem được mọi thứ bố mẹ xem." trên trang đăng nhập.
   - Mất tên trẻ trên nút giao máy cho trẻ xem.
4. **Kiểm chứng.** `pytest -q` trên máy thật: 143 passed. Trong sandbox của Codex có 1 bài DNS không đạt vì sandbox không có Internet; bài này đạt khi chạy trên máy thật.
5. **Chưa kiểm chứng tự động.** Công cụ kiểm tra giao diện của Codex không kết nối được trình duyệt, nên bố cục ở bề rộng 390px được nhóm kiểm tra thủ công bằng chế độ giả lập thiết bị của trình duyệt (DevTools).

---

## 3. Cam Kết Minh Bạch
- Toàn bộ quyết định kiến trúc (`ADR-01` đến `ADR-03`), lược đồ CSDL, quy tắc nghiệp vụ và luồng xử lý mạng đều do nhóm sinh viên rà soát, hiểu rõ và chịu trách nhiệm khi vấn đáp trước giảng viên.
- Không sử dụng AI để bịa số liệu đo đạc, lời chứng thực hay vi phạm đạo đức học thuật.
- Phần phân công công việc và tỷ lệ đóng góp (%) trong báo cáo do nhóm tự điền và thống nhất.
