# Bộ Prompt Chuẩn Hóa Cho Claude Code — Dự Án OGK (Open Guardian for Kids)

Tài liệu này được thiết kế chuyên biệt dựa trên kết quả đối chiếu trực tiếp toàn bộ mã nguồn bản demo hiện tại của bạn (`1. Đồ án.zip` — 12.564 dòng code) với từng yêu cầu chấm điểm trong đề bài `DoAn01.docx`.

Bạn có thể sử dụng tài liệu này theo 2 cách:
1. **Cách 1 (Khuyên dùng cho Claude Code)**: Lưu phần **Master Prompt** bên dưới thành file `CLAUDE.md` ở thư mục gốc dự án (hoặc dán thẳng vào Claude Code ở chế độ **Plan Mode** `Shift+Tab`), sau đó yêu cầu Claude Code thực thi lần lượt từ **Phase 1 đến Phase 5**.
2. **Cách 2 (Chạy từng chặng ngắn để tiết kiệm Context Window)**: Copy từng **Prompt theo Phase** ở Mục 3 dán vào Claude Code, đợi chạy pass `pytest` rồi mới qua Phase tiếp theo.

## 1. Tổng Hợp Kết Quả Rà Soát Bản Demo Hiện Tại (7 Nhóm Lỗi & Khoảng Trống Cần Sửa)

Trước khi giao việc cho Claude Code, đây là các điểm đứt gãy thực tế giữa các tầng trong bản demo hiện tại mà bộ prompt bên dưới sẽ chỉ đạo Claude Code sửa triệt để:

| Mã lỗi | Thành phần & File liên quan | Chi tiết lỗi trong bản Demo hiện tại | Yêu cầu đối chiếu từ `DoAn01.docx` |
| :--- | :--- | :--- | :--- |
| **BUG-01** | `server/services/policy_service.py`, `server/services/enrollment.py`, `server/schemas/policy.py`, `agent/core/policy_verifier.py`, `agent/sync/server_client.py` | **Lệch chữ ký HMAC-SHA256 khi đồng bộ Policy thực tế**: Server ký 9 trường (không có `id`), `enrollment.py` trả về `policy` thiếu `child_id`, trong khi `GET /api/v1/policy` (`PolicyResponse`) lại trả thêm trường `id`. Ngoài ra `AgentServerClient` mặc định dùng `device_secret="ogk-agent-default-secret"` còn Server ký bằng `JWT_SECRET`. Khi chạy thật, `verify_policy()` trên Agent luôn từ chối chính sách vì lệch HMAC. | **F4 (BẮT BUỘC)**: Chính sách có đánh số phiên bản và ký hiệu toàn vẹn (HMAC) để agent xác minh và áp dụng trong vòng 60s. |
| **BUG-02** | `server/schemas/policy.py`, `agent/core/screen_time.py`, `agent/core/policy_verifier.py`, `agent/service/win_service.py`, `dashboard/templates/dashboard.html` | **Lệch tên trường JSON Policy giữa 4 tầng**: Server dùng `daily_limit_weekday_min`, `daily_limit_weekend_min`, `schedule_matrix_7x48`, `category_budgets_json`, `app_rules_json`, `domain_rules_json`. Nhưng `screen_time.py` và `policy_verifier.py` lại đọc `schedule_matrix`, `daily_limit_minutes_weekday`, `daily_limit_minutes_weekend`, `category_budgets`; `win_service.py` đọc `app_rules`, `category_quotas`; còn `dashboard.html` gửi `schedule_matrix`, `weekday_limit_min`, `weekend_limit_min`, `safesearch_enabled` gây lỗi HTTP `422 Unprocessable Entity` (do `PolicyUpdate` bật `extra="forbid"`). | **F1, F2, F4 (BẮT BUỘC)**: Cấu hình từ xa hạn mức ngày thường/cuối tuần, ma trận $7 \times 48$, danh sách ứng dụng/miền và ngân sách nhóm ứng dụng. |
| **BUG-03** | `agent/sync/server_client.py` | **Thiếu `import os`**: Dòng 63–66 và 318–319 gọi `os.getenv("OGK_CA_CERT")` và `os.path.exists(ca_cert)` nhưng đầu file không có `import os`, gây văng `NameError` ngay khi khởi tạo HTTP/WSS client. | **4.1, F5 (BẮT BUỘC)**: Kênh truyền HTTPS/WSS TLS 1.2+ và Certificate Pinning hoạt động ổn định. |
| **BUG-04** | `agent/ui/tray_app.py`, `agent/service/win_service.py`, `agent/ipc/pipe_protocol.py` | **Đứt luồng IPC giữa Tray UI và Windows Service**: Trong `tray_app.py`, hàm `main()` khởi tạo `TrayApplication(headless=False)` nhưng không truyền `ipc_client=IpcClient()`. Các hàm `send_tray_ready()` và `request_more_time()` gọi `self.ipc_client.send_envelope(env)` trong khi `IpcClient` chỉ có hàm `send_request(env)`. Vòng lặp `start_background_loop()` chưa gọi `GET_SESSION_STATUS` định kỳ nên đồng hồ đếm ngược, cảnh báo trước 10/5/1 phút, cửa sổ ân hạn 60s và popup báo lý do chặn ứng dụng/website chưa tự bật khi Service phát hiện vi phạm. | **4.2, F1, F2 (BẮT BUỘC)**: Tray UI hiển thị đồng hồ còn lại, cảnh báo 10/5/1 phút, ân hạn 60s, nút xin thêm giờ và cửa sổ giải thích lý do khi chặn ứng dụng/website (không im lặng). |
| **BUG-05** | `dashboard/templates/dashboard.html`, `dashboard/templates/child_view.html`, `server/routers/reports.py`, `server/routers/web.py` | **Lỗi hiển thị & thiếu chức năng trên Web Dashboard / Child View**: (1) `dashboard.html` đọc `data.pairing_code` thay vì `data.code` (hiển thị `undefined`); (2) `dashboard.html` đọc `devices[0].hostname` thay vì `devices[0].device_name`; (3) `child_view.html` đọc `report.total_used_min`, `report.top_apps`, `report.top_domains` (`d.count`) nhưng `reports.py` trả về `today_active_min`, `top_10_apps`, `top_10_domains` (`d.queries`); (4) Biểu đồ Chart.js trên `dashboard.html` đang gắn cứng mảng số liệu tĩnh thay vì dữ liệu từ `report.daily_breakdown`; (5) Thiếu mục **Duyệt yêu cầu xin thêm giờ của trẻ (`unlock_request` $\rightarrow$ `override_granted`)** và giao diện **Quản lý Ứng dụng (Allow/Block + SHA-256) / Tên miền / Ngân sách nhóm**. | **4.2, F1, F2, F3 (BẮT BUỘC)**: Dashboard phụ huynh cấu hình từ xa quota, lịch tuần, danh sách ứng dụng/miền, duyệt yêu cầu của trẻ, xem biểu đồ ngày/tuần; màn hình minh bạch cho trẻ hiển thị đúng dữ liệu thực. |
| **BUG-06** | `agent/service/win_service.py`, `agent/core/agent_db.py` | **Thiếu lưu trữ thông tin ghép đôi (Device Credentials) & CLI Enrollment**: `win_service.py` chưa có lệnh CLI `enroll` để nhập mã ghép đôi 8 ký tự và chưa tự động lưu/nạp `device_id`, `child_id`, `access_token`, `refresh_token` từ `agent.db` khi khởi động lại dịch vụ. | **4.3, M5, README (BẮT BUỘC)**: Ghép đôi bằng mã 8 ký tự hạn 10 phút; chịu lỗi khi khởi động lại; cài đặt hoàn chỉnh trong 15 phút trên máy sạch. |
| **BUG-07** | `tests/benchmark_m4.py`, `docs/THREATMODEL.md`, `docs/AI_USAGE.md`, `docs/BaoCao.docx`, `docs/BaoCaoKyThuatMang.pdf` | **Thiếu thành phần trong bộ hồ sơ nộp Mục 6 & Mục 8**: (1) `benchmark_m4.py` thiếu phép đo so sánh độ trễ phân giải DNS **có và không có agent** ($p_{50}, p_{95}$, $\ge 30$ mẫu) và độ trễ áp dụng chính sách từ Dashboard xuống Agent; (2) `THREATMODEL.md` thiếu **Checklist OWASP ASVS**; (3) `AI_USAGE.md` thiếu bảng đối chiếu chi tiết từng hạng mục; (4) Chưa tạo file `/docs/BaoCao.docx` (20–30 trang) và `/docs/BaoCaoKyThuatMang.pdf` (Phụ lục M1–M6). | **Mục 6 (M1–M6) & Mục 8 (Sản phẩm phải nộp)**: Đủ mã nguồn, test, báo cáo chính `.docx`, báo cáo kỹ thuật mạng `.pdf` và các tài liệu `.md`. |

## 2. Master Prompt Đầy Đủ Cho Claude Code (Copy & Paste Toàn Bộ Khối Này)

```markdown
# ROLE & OBJECTIVE
Bạn là Senior Systems & Network Security Architect kiêm Full-Stack Python Developer. Nhiệm vụ của bạn là rà soát, sửa toàn bộ lỗi tích hợp End-to-End (E2E), hoàn thiện các tính năng còn thiếu và sinh đầy đủ bộ tài liệu báo cáo cho đồ án môn Mạng Máy Tính: **OGK (Open Guardian for Kids) — "Công cụ đồng hành, không phải phần mềm theo dõi lén"**.

Toàn bộ yêu cầu gốc nằm trong file `DoAn01.docx` (và bộ đặc tả trong `docs/`). Dự án hiện đã có khung mã nguồn hoàn chỉnh tại `agent/`, `server/`, `dashboard/`, `demo/`, `scripts/`, `tests/` với 78 test cases cơ bản, nhưng đang tồn tại 7 nhóm lỗi đứt gãy tích hợp (Integration Gaps) giữa Frontend - Backend - Agent và thiếu một số hạng mục bắt buộc trong `DoAn01.docx`.

---

# STRICT ARCHITECTURAL & PRIVACY GUARDRAILS (BẤT KHẢ XÂM PHẠM)
Khi sửa code và viết tài liệu, bạn BẮT BUỘC tuân thủ tuyệt đối các nguyên tắc sau từ `DoAn01.docx`:
1. **Triết lý đồng hành & Không chạy ẩn (F5 - No Stealth Mode)**:
   - Không được có chế độ ẩn. Nếu `OGK-Tray` không thể hiển thị biểu tượng sau 3 lần thử, `OGK-Service` phải tự chuyển sang trạng thái `UNPROTECTED_HALT` (nhả khóa DNS, dừng chặn).
   - Tuyệt đối KHÔNG chụp ảnh màn hình, KHÔNG keylogger, KHÔNG đọc DOM/tin nhắn, KHÔNG cài tiện ích theo dõi nội dung trình duyệt.
2. **Tối thiểu hóa dữ liệu (F3 - Strict 7-Field Event Schema)**:
   - Lược đồ sự kiện nghiệp vụ chỉ gồm đúng 7 trường: `ts`, `device_id`, `child_id`, `type`, `subject`, `duration_sec`, `policy_id` (kèm `idempotency_key` để chống trùng khi đồng bộ lô).
   - `type` chỉ thuộc 9 giá trị: `{app_start, app_stop, domain_query, blocked_app, blocked_domain, quota_warning, locked, unlock_request, override_granted}`.
   - `subject` chỉ lưu tên tệp thực thi (vd: `notepad.exe`) hoặc tên miền cấp hai eTLD+1 (vd: `youtube.com`), TUYỆT ĐỐI KHÔNG chứa đường dẫn URL đầy đủ (`/`, `?`, `&`).
3. **An toàn dữ liệu kiểm thử (F2 & Phụ lục)**:
   - Bộ tên miền kiểm thử và danh mục `server/seeds/domain_catalog.json` tuyệt đối KHÔNG chứa tên miền người lớn/độc hại thật. Mọi tên miền thuộc nhóm `inappropriate` chỉ được dùng đuôi mô phỏng an toàn RFC 2606 (`.test`, `.example`).
4. **An toàn hệ thống trên máy chấm bài (Clean Rollback)**:
   - Mọi thay đổi DNS card mạng (`127.0.0.1`) hoặc Registry trình duyệt (`DnsOverHttpsMode`) phải có cơ chế lưu Snapshot vào `agent.db` và khôi phục sạch 100% khi dừng Service hoặc chạy `agent/cleanup/ogk_cleanup.py`.

---

# EXECUTION PLAN (THỰC HIỆN TUẦN TỰ 5 PHASE)

Hãy thực hiện lần lượt từng Phase dưới đây. Sau mỗi Phase, chạy `pytest -v` để đảm bảo không làm gãy bất kỳ test cũ nào và viết thêm test mới cho các luồng vừa sửa.

## PHASE 1: Đồng Bộ Hóa Schema Chính Sách, Chữ Ký HMAC & Luồng Ghép Đôi (Server <-> Agent)
1. **Sửa lỗi thiếu `import os` trong `agent/sync/server_client.py`**:
   - Thêm `import os` ở đầu file `agent/sync/server_client.py`.
2. **Chuẩn hóa hàm ký và xác minh HMAC-SHA256 giữa Server và Agent**:
   - Kiểm tra `server/services/policy_service.py` (`canonical_policy_bytes`, `sign_policy_payload`) và `agent/core/policy_verifier.py` (`canonical_policy_bytes`, `verify_policy`).
   - Định nghĩa danh sách trường chuẩn duy nhất dùng để tính chữ ký HMAC (`SIGNED_POLICY_KEYS = ("child_id", "version", "daily_limit_weekday_min", "daily_limit_weekend_min", "schedule_matrix_7x48", "category_budgets_json", "app_rules_json", "domain_rules_json", "updated_at_utc")`) ở cả `policy_service.py` và `policy_verifier.py` (bỏ qua các trường metadata như `id` hoặc các trường phụ trợ đã giải mã khi tính HMAC).
   - Trong `server/services/enrollment.py`, đảm bảo dictionary `policy` trả về trong `enroll_device()` có đầy đủ trường `"child_id": pairing.child_id` khớp 100% với `SIGNED_POLICY_KEYS`.
   - Đồng bộ khóa bí mật ký Policy (`OGK_POLICY_SECRET` / `JWT_SECRET`) giữa `server/services/policy_service.py` và `agent/sync/server_client.py` (cho phép đọc từ biến môi trường `OGK_POLICY_SECRET` hoặc `OGK_JWT_SECRET` với cùng giá trị mặc định trong môi trường lab, hoặc cấp phát `policy_hmac_secret` khi `enroll`).
3. **Thống nhất tên trường Policy trên toàn bộ hệ thống**:
   - Trong `agent/core/policy_verifier.py` và `agent/core/screen_time.py`: Hỗ trợ đọc cả tên trường chuẩn từ Server (`schedule_matrix_7x48`, `daily_limit_weekday_min`, `daily_limit_weekend_min`, `category_budgets_json`, `app_rules_json`, `domain_rules_json`) lẫn các alias cũ (`schedule_matrix`, `daily_limit_minutes_weekday`, `daily_limit_minutes_weekend`, `category_budgets`, `app_rules`, `category_quotas`) để tương thích ngược 100% với các unit test hiện có.
   - Trong `agent/sync/server_client.py` (`_apply_policy`): Khi nhận policy từ Server hoặc SQLite cache, tự động parse `app_rules_json`, `domain_rules_json`, `category_budgets_json` thành các khóa đã giải mã (`app_rules`, `domain_rules`, `category_quotas`, `category_budgets`, `schedule_matrix`) trên `self.active_policy` để `win_service.py` và `screen_time.py` sử dụng trực tiếp.
4. **Bổ sung lưu trữ thông tin định danh thiết bị (Device Credentials) & CLI Enrollment cho Agent**:
   - Trong `agent/core/agent_db.py`: Đảm bảo có bảng/hàm lưu và đọc `device_credentials` (`device_id`, `child_id`, `access_token`, `refresh_token`, `server_url`, `offline_pin_hash`).
   - Trong `agent/sync/server_client.py`: Khi `enroll()` hoặc `refresh_access_token()` thành công, tự động lưu credentials vào `self.db`. Khi `start()` khởi chạy, nếu chưa truyền `device_id`/`access_token` qua constructor thì tự nạp từ `self.db`.
   - Trong `agent/service/win_service.py`: Hỗ trợ lệnh CLI `python agent/service/win_service.py enroll --code <PAIRING_CODE> [--server https://127.0.0.1:8000]` để ghép đôi thiết bị dễ dàng khi demo trên máy sạch.

## PHASE 2: Khép Kín Luồng Giao Tiếp IPC Giữa `OGK-Service` và `OGK-Tray` (F1, F2, F3, F5)
1. **Kết nối `IpcClient` thực tế trong `agent/ui/tray_app.py`**:
   - Trong `tray_app.py`, khởi tạo mặc định `self.ipc_client = ipc_client or IpcClient()` (import `IpcClient` từ `agent.ipc.pipe_protocol`).
   - Trong `IpcClient` (`agent/ipc/pipe_protocol.py`), thêm alias method `send_envelope = send_request` để tương thích với cả `send_envelope()` và `send_request()`.
2. **Đồng bộ trạng thái thời gian thực & Cảnh báo 10m / 5m / 1m / Ân hạn 60s**:
   - Trong `TrayApplication.start_background_loop()` (`agent/ui/tray_app.py`), định kỳ mỗi 2 giây gửi `IpcEnvelope(msg_type="GET_SESSION_STATUS")` qua `self.ipc_client`.
   - Cập nhật `self.remaining_sec`, `self.used_total_sec`, `self.is_locked`, `self.is_parent_paused` và cập nhật tooltip / màu biểu tượng khay hệ thống (`active`, `warning`, `locked`, `paused`).
   - Khi `status["warning"]` trả về `"warn_10m"`, `"warn_5m"`, `"warn_1m"` (và khác `self.last_warning_shown`), tự động gọi `self.show_warning_dialog(...)` thông báo số phút còn lại và ghi sự kiện `quota_warning` vào `EventBuffer` phía Service.
   - Khi `status["warning"] == "GRACE_PERIOD_60S"` hoặc `status["lock_reason"] == "GRACE_PERIOD"`, tự động mở cửa sổ đếm ngược 60 giây `self.show_grace_countdown_dialog()` để trẻ lưu bài hoặc bấm "Xin thêm 15 phút" / "Bố mẹ mở khóa".
   - Khi `VERIFY_PARENT_PIN` thành công trên cửa sổ khóa cục bộ, `OGKServiceCore` tự động mở khóa tạm thời / cộng thêm 15 phút và ghi sự kiện `override_granted`.
3. **Hiển thị cửa sổ giải thích lý do khi chặn Ứng dụng hoặc Website (F2 BẮT BUỘC — Không chặn im lặng)**:
   - Trong `OGKServiceCore` (`agent/service/win_service.py`), lưu hàng đợi ngắn các thông báo chặn mới nhất (`recent_blocks`: `{subject, reason, ts}`) khi `AppController` kết thúc tiến trình vi phạm hoặc `DnsProxyServer` chặn tên miền.
   - Trả kèm `recent_blocks` trong phản hồi `GET_SESSION_STATUS` (và xóa khỏi hàng đợi sau khi Tray UI đã nhận).
   - Khi `TrayApplication` nhận được mục chặn mới trong `recent_blocks`, gọi ngay `self.show_block_explanation(subject, reason)` để hiển thị cửa sổ giải thích thân thiện cho trẻ.
4. **Nâng cấp màn hình "Hôm nay em đã dùng gì?" trên Tray UI**:
   - Trong `OGKServiceCore._get_session_status()`, trả thêm danh sách tóm tắt top ứng dụng và tên miền trong ngày từ `agent.db` để cửa sổ `show_transparency_screen()` trên `OGK-Tray` hiển thị trực quan cả thời gian đã dùng, thời gian còn lại, top ứng dụng và tên miền.

## PHASE 3: Hoàn Thiện Dashboard Phụ Huynh & Màn Hình Minh Bạch Cho Trẻ (F1, F2, F3, F4)
1. **Sửa toàn bộ lỗi lệch tên trường trên `dashboard/templates/dashboard.html` và `dashboard/templates/child_view.html`**:
   - Trong `dashboard.html`:
     - Đổi `policy.schedule_matrix` thành `policy.schedule_matrix_7x48`.
     - Đổi `policy.weekday_limit_min` thành `policy.daily_limit_weekday_min` và `policy.weekend_limit_min` thành `policy.daily_limit_weekend_min`.
     - Trong hàm JS `savePolicyAndSchedule()`, gửi đúng payload chuẩn của `PolicyUpdate`: `{"schedule_matrix_7x48": scheduleArray.join(""), "daily_limit_weekday_min": weekdayMin, "daily_limit_weekend_min": weekendMin, "category_budgets": ...}`.
     - Trong hàm JS `generatePairingCode()`, đọc `data.code || data.pairing_code` để hiển thị đúng mã ghép đôi 8 ký tự.
     - Đổi `devices[0].hostname` thành `devices[0].device_name`.
   - Trong `child_view.html` và `server/routers/reports.py`:
     - Chuẩn hóa dữ liệu trả về từ `get_child_report()` trong `server/routers/reports.py` để có đầy đủ: `today_active_min`, `total_used_min` (alias), `total_blocked_events`, `blocked_count` (alias), `daily_breakdown`, `category_breakdown`, `top_10_apps`, `top_apps` (alias), `top_10_domains`, `top_domains` (mỗi phần tử có cả `queries` và `count`), và danh sách `pending_requests` (các sự kiện `unlock_request` gần nhất của trẻ).
2. **Kết nối biểu đồ Chart.js với dữ liệu thật trên `dashboard.html`**:
   - Thay thế mảng dữ liệu cứng `[45, 60, 50, 40, 75, 110, 95]` trên biểu đồ cột `weeklyChart` và biểu đồ tròn `categoryChart` bằng dữ liệu động truyền từ `report.daily_breakdown` và `report.category_breakdown`.
3. **Bổ sung bảng "Yêu cầu xin thêm giờ của trẻ (`unlock_request`)" & Nút Duyệt trên Dashboard (F3, F4 BẮT BUỘC)**:
   - Hiển thị danh sách các sự kiện `unlock_request` của trẻ trên `dashboard.html`.
   - Thêm nút **"✅ Duyệt +15 phút"** (gọi API gửi lệnh `ADD_TIME_15M` xuống thiết bị, đồng thời ghi sự kiện `override_granted` vào bảng `events` và ghi `AuditLog`) và nút **"❌ Từ chối"**.
4. **Bổ sung giao diện cấu hình Ngân sách Nhóm ứng dụng (`category_budgets`), Danh sách Ứng dụng (`app_rules` kèm SHA-256) và Tên miền (`domain_rules`) trên `dashboard.html`**:
   - Cho phép phụ huynh chỉnh sửa ngân sách thời gian theo nhóm (ví dụ: Trò chơi `gaming`: 45 phút, Giải trí `entertainment`: 60 phút, Giáo dục `education`: Không giới hạn).
   - Cho phép phụ huynh xem, thêm/xóa quy tắc chặn hoặc cho phép ứng dụng (`exe_name`, `sha256`, `original_filename`, `category`, `action`) và tên miền (`domain`, `category`, `action`), bấm lưu qua `PUT /api/v1/policy/{child_id}`.

## PHASE 4: Hoàn Thiện Đo Kiểm Hiệu Năng M4 & Bộ Test Tự Động
1. **Nâng cấp `tests/benchmark_m4.py` và `docs/benchmark_m4_results.md` đáp ứng 100% yêu cầu Mục 6 (M4)**:
   - Bổ sung phép đo tối thiểu 30 mẫu liên tục cho đủ các hạng mục M4 trong `DoAn01.docx`:
     1. CPU (%) và RAM (MB) của Agent lúc rảnh (Idle) và lúc cao điểm (Stress).
     2. Độ trễ phân giải DNS ($p_{50}, p_{95}$) **KHÔNG CÓ Agent** (truy vấn trực tiếp upstream/local resolver) so với **CÓ Agent** (qua DNS Proxy `127.0.0.1:53` ở cả trường hợp Cache Miss, Cache Hit và Sinkhole Block).
     3. Độ trễ áp dụng chính sách từ Dashboard (`PUT /api/v1/policy/{child_id}`) đến khi Agent cập nhật xong, và độ trễ lệnh khẩn qua WebSocket (`< 5s`).
   - Chạy `python tests/benchmark_m4.py` để cập nhật bảng số liệu thực nghiệm kèm mô tả phương pháp đo vào `docs/benchmark_m4_results.md`.
2. **Mở rộng Test Suite (`tests/`)**:
   - Viết thêm test kiểm tra các lỗi vừa sửa ở Phase 1–3 (test chữ ký HMAC E2E khi gọi `GET /api/v1/policy` và `PUT /api/v1/policy/{child_id}`, test IPC `TrayApplication` nhận cảnh báo và block popup, test Dashboard duyệt `unlock_request` sinh `override_granted`).
   - Chạy `pytest -v` đảm bảo 100% test cases PASS.

## PHASE 5: Hoàn Thiện Bộ Tài Liệu & Sinh Báo Cáo Nộp Mục 8 (`DoAn01.docx`)
1. **Cập nhật `docs/THREATMODEL.md`**:
   - Giữ nguyên bảng phân tích 8 mối đe dọa STRIDE hiện có (bao gồm kịch bản *"chính trẻ là người tấn công"* và *"sản phẩm bị lạm dụng làm stalkerware"*).
   - Bổ sung thêm phần **Bảng đối chiếu Checklist Bảo mật OWASP ASVS (Application Security Verification Standard)** gồm các mục xác thực (V2), quản lý phiên (V3), kiểm soát truy cập chống IDOR (V4), xác thực đầu vào & chống sửa đổi chính sách (V5), mã hóa dữ liệu nghỉ/truyền (V6/V9) theo đúng yêu cầu bảng mục 8 của `DoAn01.docx`.
2. **Cập nhật `docs/AI_USAGE.md`**:
   - Bổ sung bảng chi tiết theo đúng yêu cầu mục 8: `Hạng mục / Phân hệ` ↔ `Công cụ AI sử dụng` ↔ `Mục đích sử dụng` ↔ `Phương pháp kiểm chứng & Rà soát của sinh viên`.
3. **Tạo tài liệu `/docs/BaoCao.docx` (Báo cáo chính 20–30 trang) bằng `python-docx`**:
   - Viết script Python sinh file `/docs/BaoCao.docx` trình bày chuyên nghiệp, đầy đủ các chương theo đúng đề cương đồ án:
     - Chương 1: Tổng quan đề tài, triết lý *"Công cụ đồng hành, không phải phần mềm theo dõi lén"*, tuân thủ Nghị định 13/2023/NĐ-CP và Luật Trẻ em 2016.
     - Chương 2: Kiến trúc hệ thống tổng thể (Sơ đồ 4.1, trách nhiệm thành phần 4.2, đặc tả chi tiết 5 giao thức vòng đời mục 4.3: Enrollment, Heartbeat 60s, WebSocket lệnh khẩn < 5s, Offline batch sync với `idempotency_key`, và bảo vệ quyết định **Graded Fail-Open sau N=7 ngày**).
     - Chương 3: Thiết kế & Hiện thực hóa các chức năng F1 (Quản lý thời gian, ma trận $7 \times 48$, chống chỉnh giờ 3 lớp), F2 (Kiểm soát ứng dụng SHA-256 + PE Header, DNS Proxy Suffix Trie $O(k)$, 6 nhóm phân loại 235 tên miền an toàn, SafeSearch, chống DoH & khóa DNS card mạng), F3 (Lược đồ 7 trường tối thiểu, Dashboard phụ huynh, màn hình minh bạch cho trẻ, tự động xóa sau 90 ngày & nút xóa sạch dữ liệu), F4 (Mô hình $1:n:m$, HMAC-SHA256 policy, Audit Trail NT5, gỡ cài đặt có PIN, tạm nghỉ 2 giờ), F5 (Argon2id, khóa tạm 15 phút, Cookie HttpOnly/CSRF, TLS + Certificate Pinning, AES-GCM, chống IDOR, ACL ProgramData, STRIDE).
     - Chương 4: Kiểm thử tự động (Unit tests & 5 kịch bản tích hợp E2E) và Hướng dẫn triển khai trong 15 phút.
     - Chương 5: **Bảng phân công công việc và Tự đánh giá mức độ đóng góp theo phần trăm (%) cho nhóm 3 sinh viên** (BẮT BUỘC ở mục 8).
4. **Tạo tài liệu `/docs/BaoCaoKyThuatMang.pdf` (Phụ lục Kỹ thuật Hệ thống & Mạng M1–M6)**:
   - Viết script Python sinh file `/docs/BaoCaoKyThuatMang.pdf` bao gồm đầy đủ 6 mục trọng tâm chấm điểm của Mục 6:
     - **M1 (Sơ đồ luồng gói tin)**: Sơ đồ chi tiết đường đi gói tin khi mở trang bị chặn (`Browser -> Windows Stub Resolver -> OGK DNS Proxy 127.0.0.1:53 -> Suffix Trie Lookup -> Sinkhole/NXDOMAIN Response`) kèm bảng giải phẫu bản tin DNS thực tế (Transaction ID, Flags, Question, Answer/RCode) và hướng dẫn/log chụp gói tin Wireshark trên giao diện Loopback (`Npcap Loopback Adapter`, filter `udp.port == 53`).
     - **M2 (So sánh phương án chặn)**: Bảng so sánh chi tiết 4 phương án (`Tệp hosts`, `DNS Proxy cục bộ`, `Proxy HTTP/HTTPS`, `Bộ lọc WFP`) theo đúng 5 tiêu chí bắt buộc (`Độ chính xác`, `Khả năng chặn HTTPS`, `Chi phí hiện thực`, `Khả năng bị vượt`, `Ảnh hưởng hiệu năng`) và lập luận kỹ thuật vì sao chọn DNS Proxy cục bộ kết hợp Browser Policy & Network Guard.
     - **M3 (Phân tích đường vòng — 9 kỹ thuật vượt rào)**: Phân tích đầy đủ $\ge 7$ kỹ thuật bắt buộc (`Đổi DNS thủ công sang 8.8.8.8`, `DNS-over-HTTPS (DoH)`, `DNS-over-TLS (DoT port 853)`, `VPN/Proxy công cộng`, `Truy cập trực tiếp bằng địa chỉ IP`, `Khởi động Safe Mode`, `Khởi động từ USB/Live OS`, `Tạo/đăng nhập tài khoản Windows khác`, `Kết thúc tiến trình qua Task Manager`) — mỗi kỹ thuật nêu rõ: Mô tả cơ chế, Kết quả thử nghiệm thực tế trên OGK, và Biện pháp đối phó đã cài đặt hoặc lý do chấp nhận rủi ro.
     - **M4 (Đo hiệu năng)**: Bảng số liệu thực nghiệm $\ge 30$ mẫu từ `tests/benchmark_m4.py` (CPU, RAM lúc rảnh/cao điểm; độ trễ DNS $p_{50}, p_{95}$ khi có và không có Agent; độ trễ áp dụng chính sách và lệnh khẩn WebSocket) kèm mô tả phương pháp đo.
     - **M5 (Khả năng chịu lỗi)**: Phân tích 3 kịch bản (`Mất mạng LAN/Internet`, `Máy chủ OGK-Server ngừng hoạt động`, `Tiến trình OGK-Agent / OGK-Tray bị kết thúc`) với Hành vi mong đợi, Hành vi thực tế và Thời gian phục hồi.
     - **M6 (Đồng bộ thời gian)**: Kiến trúc 3 lớp chống lệch và chống chỉnh đồng hồ hệ thống (`time.monotonic()`, dấu thời gian `last_wall_clock_utc` lưu SQLite, đối chiếu `server_utc` mỗi nhịp tim 60s với ngưỡng cảnh báo 120s).
```

## 3. Các Prompt Lẻ Theo Từng Nhiệm Vụ (Nếu Bạn Muốn Chạy Từng Bước Ngắn)

Nếu bạn muốn kiểm soát từng bước nhỏ trong Claude Code thay vì chạy một lèo 5 Phase, hãy copy từng khối dưới đây:

### Bước A — Prompt sửa dứt điểm lỗi Backend & Agent (Phase 1 + Phase 2)

```markdown
Hãy đọc các file `server/services/policy_service.py`, `server/services/enrollment.py`, `server/schemas/policy.py`, `agent/core/policy_verifier.py`, `agent/core/screen_time.py`, `agent/sync/server_client.py`, `agent/service/win_service.py`, `agent/ui/tray_app.py`, và `agent/ipc/pipe_protocol.py`.

Sửa dứt điểm các lỗi đứt gãy tích hợp sau:
1. Thêm `import os` vào đầu `agent/sync/server_client.py`.
2. Đồng bộ hóa `SIGNED_POLICY_KEYS` và secret key giữa `policy_service.py`, `enrollment.py`, `PolicyResponse` và `policy_verifier.py` để khi Agent gọi `enroll()` hoặc `GET /api/v1/policy` thì `verify_policy()` luôn xác thực chữ ký HMAC-SHA256 thành công.
3. Trong `screen_time.py` và `policy_verifier.py`, hỗ trợ đọc cả tên trường chuẩn từ Server (`schedule_matrix_7x48`, `daily_limit_weekday_min`, `daily_limit_weekend_min`, `category_budgets_json`) lẫn tên trường cũ trong unit test. Trong `server_client.py` (`_apply_policy`), parse sẵn `app_rules_json`, `domain_rules_json`, `category_budgets_json` sang list/dict trên `self.active_policy`.
4. Lưu và tự động nạp `device_id`, `child_id`, `access_token`, `refresh_token` vào `agent.db` khi `enroll()` hoặc `start()`, đồng thời thêm lệnh CLI `python agent/service/win_service.py enroll --code <CODE>`.
5. Nối `IpcClient` vào `TrayApplication` trong `tray_app.py`, thêm alias `send_envelope = send_request` trong `IpcClient`, bổ sung vòng lặp poll `GET_SESSION_STATUS` mỗi 2s trong `TrayApplication.start_background_loop()` để tự động hiển thị cảnh báo 10m/5m/1m, cửa sổ đếm ngược ân hạn 60s, và popup giải thích lý do khi `AppController` hoặc `DnsProxyServer` chặn ứng dụng/website.
6. Chạy `pytest -v` và viết thêm test tích hợp xác nhận các luồng trên hoạt động 100%.
```

### Bước B — Prompt nâng cấp Dashboard Phụ Huynh & Child View (Phase 3)

```markdown
Hãy đọc `dashboard/templates/dashboard.html`, `dashboard/templates/child_view.html`, `server/routers/web.py`, `server/routers/reports.py`, và `server/schemas/policy.py`.

Thực hiện các nâng cấp sau:
1. Sửa tên trường trên `dashboard.html` khớp với `PolicyResponse` và `PolicyUpdate` (`schedule_matrix_7x48`, `daily_limit_weekday_min`, `daily_limit_weekend_min`) để nút "Lưu Cấu Hình & Ma Trận Lịch" không bị lỗi 422.
2. Sửa lỗi hiển thị mã ghép đôi (`data.code || data.pairing_code`) và tên thiết bị (`devices[0].device_name`) trên `dashboard.html`.
3. Chuẩn hóa dữ liệu trả về của `get_child_report()` trong `server/routers/reports.py` để khớp với cả `dashboard.html` và `child_view.html`, đồng thời nối dữ liệu thật (`daily_breakdown`, `category_breakdown`) vào 2 biểu đồ Chart.js trên `dashboard.html` thay vì mảng cố định.
4. Thêm khu vực "Yêu cầu xin thêm giờ của trẻ (`unlock_request`)" trên `dashboard.html` kèm nút "Duyệt +15 phút" (gửi lệnh `ADD_TIME_15M` + lưu sự kiện `override_granted` + ghi `AuditLog`).
5. Thêm giao diện quản lý Ngân sách nhóm ứng dụng (`category_budgets`), Danh sách Ứng dụng (`app_rules` kèm SHA-256) và Danh sách Tên miền (`domain_rules`) trên `dashboard.html`.
6. Chạy `pytest -v` để kiểm chứng toàn bộ route web và API.
```

### Bước C — Prompt chạy Benchmark M4 & Sinh Báo Cáo Nộp (Phase 4 + Phase 5)

```markdown
Dựa trên yêu cầu Mục 6 (M1–M6) và Mục 8 của `DoAn01.docx`:
1. Nâng cấp `tests/benchmark_m4.py` để đo đủ >= 30 mẫu cho: (a) CPU/RAM lúc rảnh và cao điểm; (b) Độ trễ phân giải DNS (p50, p95) khi KHÔNG có Agent và khi CÓ Agent (Cache Hit, Cache Miss, Sinkhole); (c) Độ trễ áp dụng chính sách và lệnh khẩn WebSocket. Cập nhật kết quả vào `docs/benchmark_m4_results.md`.
2. Bổ sung bảng Checklist OWASP ASVS vào `docs/THREATMODEL.md` và bảng kê khai chi tiết vào `docs/AI_USAGE.md`.
3. Viết script sinh tự động file `/docs/BaoCao.docx` (20–30 trang, đầy đủ kiến trúc, giao thức, đặc tả F1–F5, kiểm thử và bảng phân công % đóng góp của 3 thành viên) và `/docs/BaoCaoKyThuatMang.pdf` (đầy đủ 6 phụ lục kỹ thuật hệ thống và mạng M1–M6).
```
