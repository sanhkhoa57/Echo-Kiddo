# Mô Hình Mối Đe Dọa (STRIDE Threat Model)

> **Dự án OGK (Open Guardian for Kids) — Phân tích mối đe dọa bảo mật theo chuẩn STRIDE**

---

## 1. Phương Pháp Luận STRIDE
Hệ thống OGK áp dụng mô hình phân loại STRIDE của Microsoft:
- **S**poofing (Giả mạo danh tính)
- **T**ampering (Sửa đổi dữ liệu trái phép)
- **R**epudiation (Chối bỏ trách nhiệm)
- **I**nformation Disclosure (Lộ lọt thông tin)
- **D**enial of Service (Từ chối dịch vụ)
- **E**levation of Privilege (Leo thang đặc quyền)

---

## 2. Bảng Phân Tích 8 Mối Đe Dọa Trọng Tâm

| STT | Mối Đe Dọa (Threat Scenario) | Phân Loại STRIDE | Tác Nhân (Threat Actor) | Mức Độ Rủi Ro | Biện Pháp Đối Phó Trong Kiến Trúc OGK |
|---|---|---|---|---|---|
| **TM-01** | **Chính trẻ là kẻ tấn công: Đổi tên file game thành ứng dụng được phép** (vd: đổi `game.exe` thành `notepad.exe`) | Tampering | Trẻ em (Standard User) | Cao | `AppController` kiểm tra bộ ba: Tên tiến trình + **Mã băm SHA-256** + PE Header `OriginalFileName`. |
| **TM-02** | **Chính trẻ là kẻ tấn công: Chỉnh đồng hồ hệ thống Windows** (lùi 3 giờ, hoặc tiến sang ngày mai để được quota mới) | Tampering | Trẻ em (Standard User) | Cao | Đếm bằng `time.monotonic()`; mỗi giây so bước nhảy giờ hệ thống với `GetTickCount64`, lệch > 60 s thì cộng vào `wall_offset_sec` (sang ngày và lịch 7x48 dùng giờ tin cậy) và ghi sự kiện `quota_warning/clock_tamper`; lưu `last_wall_clock_utc` cục bộ; đối chiếu `server_utc` mỗi nhịp tim 60 s. |
| **TM-03** | **Chính trẻ là kẻ tấn công: Giả mạo tin nhắn IPC Named Pipe** gửi lệnh `UNLOCK` lên Service | Spoofing / Elevation | Trẻ em (Standard User) | Nghiêm trọng | Service xác thực `actual_sid` từ nhân Windows qua `GetNamedPipeClientProcessId`, yêu cầu `ChallengeToken` và dùng `hmac.compare_digest`. |
| **TM-04** | **Chính trẻ là kẻ tấn công: Tắt tiến trình khay hệ thống (Kill Task)** qua Task Manager | Denial of Service | Trẻ em (Standard User) | Trung bình | `SessionAgentLauncher` quét mỗi 3s và tự động khởi chạy lại `OGK-Tray`; nếu không thể hiện sau 3 lần thì chuyển sang `UNPROTECTED_HALT` để minh bạch. |
| **TM-05** | **Sản phẩm bị lạm dụng làm phần mềm theo dõi lén (Stalkerware)** | Information Disclosure | Phụ huynh hoặc kẻ xấu mượn máy | Rất nghiêm trọng | **Cấm chế độ ẩn**: Khay hệ thống luôn bật; lược đồ sự kiện chỉ lưu 7 trường tối thiểu; **tuyệt đối không lưu URL/ảnh chụp màn hình/DOM**. |
| **TM-06** | **Tấn công IDOR giữa các phụ huynh**: Truy cập dữ liệu con của gia đình khác qua REST API | Information Disclosure / Elevation | Phụ huynh khác (Attacker) | Rất nghiêm trọng | RBAC chặt chẽ: Mọi truy vấn SQLAlchemy bắt buộc lọc `WHERE parent_id == current_user.id` ở tầng Database. |
| **TM-07** | **Tấn công nghe lén hoặc chèn gói tin giả giữa Agent và Server (Man-in-the-Middle)** | Spoofing / Tampering | Kẻ tấn công mạng LAN | Cao | Toàn bộ giao tiếp chạy qua HTTPS/WSS (TLS 1.2+); Agent thực hiện **Certificate Pinning** ghim dấu vân tay chứng chỉ của Server. |
| **TM-08** | **Tấn công vét cạn mật khẩu phụ huynh (Brute-force Login)** | Spoofing | Kẻ tấn công từ xa | Trung bình - Cao | Mật khẩu băm bằng **Argon2id**; Rate Limit qua `slowapi`; tự động khóa tài khoản 15 phút sau 5 lần nhập sai liên tiếp. |

---

## 3. Bảng Đối Chiếu Checklist Bảo Mật OWASP ASVS

| Nhóm ASVS | Mã / Yêu cầu | Trạng thái | Vị trí cài đặt trong mã nguồn |
|---|---|---|---|
| **V2.1 / V2.2** | Mật khẩu tối thiểu 10 ký tự, băm Argon2id, khóa tạm 15 phút sau 5 lần sai, giới hạn tần suất theo IP | Đáp ứng | `server/auth/security.py:get_password_hash`, `verify_password`; `server/routers/auth.py`; `server/routers/web.py:login_submit` |
| **V2.8** | TOTP xác thực hai yếu tố cho phụ huynh | Chưa đáp ứng (nâng cao) | Chưa triển khai TOTP; hiện sử dụng Argon2id + lockout + rate limit (`slowapi`). |
| **V3.2 / V3.4** | Phiên làm việc cookie `HttpOnly`, `SameSite=Lax`, `Secure` khi dùng HTTPS, hạn 12 giờ, đăng xuất hủy phiên phía máy chủ (`jti` vào bảng `revoked_sessions`), form đăng nhập có CSRF double-submit và giới hạn 10 lần/phút/IP | Đáp ứng | `server/routers/web.py:_session_cookie_kwargs`, `login_submit`, `logout`; `server/auth/dependencies.py:revoke_session_token` |
| **V3.5 / V4.2** | Chống CSRF cho mọi thao tác ghi qua phiên trình duyệt (`POST`/`PUT`/`PATCH`/`DELETE`) | Đáp ứng | `server/main.py:csrf_protection`; `server/auth/security.py:generate_csrf_token`, `verify_csrf_token`; `server/auth/dependencies.py:verify_csrf_header` |
| **V4.1 / V4.2** | Kiểm soát truy cập ở tầng truy vấn dữ liệu (Anti-IDOR 1 phụ huynh : n trẻ) và tách quyền `parent` / `device` | Đáp ứng | `server/auth/dependencies.py:get_child_for_parent`, `require_role`, `get_current_device` |
| **V5.1 / V5.2** | Xác thực đầu vào nghiêm ngặt (`extra="forbid"`), từ chối URL đầy đủ trong `subject`, chuẩn hóa eTLD+1 | Đáp ứng | `server/schemas/` (Pydantic v2); `agent/dns/domain_engine.py:normalize_etld_plus_one` |
| **V5.4 / V6.2** | Chữ ký toàn vẹn chính sách HMAC-SHA256 (9 trường chuẩn), từ chối chính sách bị sửa đổi | Đáp ứng | `server/services/policy_service.py:sign_policy_payload`; `agent/core/policy_verifier.py:verify_policy` |
| **V6.2 / V6.4** | Mã hóa trường nhạy cảm khi lưu trữ bằng AES-256-GCM (token và khóa HMAC trong `agent.db`); khóa lấy từ biến môi trường hoặc tệp khóa bọc DPAPI, không hardcode | Đáp ứng | `agent/core/field_crypto.py`, `agent/core/agent_db.py:save_device_credentials`; `tests/test_agent_db.py` |
| **V9.1 / V9.2** | Kênh truyền TLS 1.2+ và ghim chứng chỉ (Certificate Pinning): Agent so SHA-256 chứng chỉ máy chủ trước khi kết nối và chỉ tin đúng chứng chỉ đó cho HTTPS/WSS | Đáp ứng | `agent/sync/server_client.py:enforce_certificate_pin`; `scripts/setup_lab.py`; `tests/test_phase1_policy_sync.py` |
| **V14 (Cục bộ)** | Giao tiếp IPC Named Pipe kiểm tra `CallerSid` từ nhân Windows, Challenge Token + `hmac.compare_digest` | Đáp ứng | `agent/ipc/pipe_protocol.py:IpcPipeHandler`, `extract_client_process_sid` |

