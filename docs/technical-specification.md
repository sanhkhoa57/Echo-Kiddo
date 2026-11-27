# Đặc Tả Kỹ Thuật Hệ Thống (Technical Specification Document)

> **Tài liệu thuộc bộ đặc tả kiến trúc dự án OGK (Open Guardian for Kids)**
> - [Kiến trúc hệ thống (architecture.md)](./architecture.md)
> - [Đặc tả chức năng (functional-specification.md)](./functional-specification.md)
> - [Đặc tả kỹ thuật (technical-specification.md)](./technical-specification.md) *(Tài liệu hiện tại)*
> - [Đối chiếu tính năng (feature-comparison.md)](./feature-comparison.md)
> - [Nhật ký thay đổi & Truy vết (architecture-change-log.md)](./architecture-change-log.md)

---

## Mục Lục

1. [Ngăn Xếp Công Nghệ & Thư Viện Chi Tiết (Technology Stack)](#1-ngăn-xếp-công-nghệ--thư-viện-chi-tiết-technology-stack)
2. [Cấu Trúc Thư Mục & Đặc Tả Mô-đun (Module Specifications)](#2-cấu-trúc-thư-mục--đặc-tả-mô-đun-module-specifications)
3. [Giao Thức Tương Tác Liên Thành Phần (Component Interactions & IPC)](#3-giao-thức-tương-tác-liên-thành-phần-component-interactions--ipc)
4. [Mô Hình Dữ Liệu & Lược Đồ Cơ Sở Dữ Liệu (Data Models)](#4-mô-hình-dữ-liệu--lược-đồ-cơ-sở-dữ-liệu-data-models)
5. [Đặc Tả REST API & WebSocket (API Specifications)](#5-đặc-tả-rest-api--websocket-api-specifications)
6. [Đặc Tả Kỹ Thuật Hệ Thống & Mạng Trọng Tâm (M1 – M6)](#6-đặc-tả-kỹ-thuật-hệ-thống--mạng-trọng-tâm-m1--m6)
7. [Phụ Thuộc Bên Ngoài & Ràng Buộc Kỹ Thuật (External Dependencies & Constraints)](#7-phụ-thuộc-bên-ngoài--ràng-buộc-kỹ-thuật-external-dependencies--constraints)
8. [Xử Lý Lỗi Kỹ Thuật & Tối Ưu Hiệu Năng (Error Handling & Performance)](#8-xử-lý-lỗi-kỹ-thuật--tối-ưu-hiệu-năng-error-handling--performance)

---

## 1. Ngăn Xếp Công Nghệ & Thư Viện Chi Tiết (Technology Stack)

### 1.1. Phân hệ Máy Chủ (`OGK-Server` & `Dashboard`)
- **Runtime**: Python `3.11+` (x64).
- **Web Framework & ASGI Server**: `fastapi>=0.110.0`, `uvicorn[standard]>=0.29.0`, `websockets>=12.0`.
- **Database & ORM**: `SQLite 3.40+` (cấu hình `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=ON;`), `sqlalchemy>=2.0.28`, `alembic>=1.13.0` (quản lý migration).
- **Bảo mật & Mật mã**: `passlib[argon2]>=1.7.4`, `argon2-cffi>=23.1.0`, `cryptography>=42.0.0` (AES-256-GCM, HMAC-SHA256, RSA-PSS/Ed25519), `PyJWT>=2.8.0`, `slowapi>=0.1.9` (Rate limiting theo IP).
- **Giao diện Dashboard**: `jinja2>=3.1.3`, `python-multipart`, `HTMX 1.9`, `Chart.js 4.x` (nhúng cục bộ để chạy tốt trong mạng phòng lab không cần Internet).

### 1.2. Phân hệ Máy Trạm (`OGK-Agent` trên Windows 10/11 x64)
- **Runtime**: Python `3.11+` (x64).
- **Hệ thống Windows & Tiến trình**: `pywin32>=306` (`win32serviceutil`, `win32service`, `win32event`, `win32ts`, `win32security`, `win32process`, `win32pipe`, `win32file`, `win32api`, `win32crypt`), `psutil>=5.9.8`.
- **Mạng & DNS Proxy**: `dnslib>=0.9.24` kết hợp `asyncio.DatagramProtocol` / `asyncio.Protocol` (lắng nghe `127.0.0.1:53` UDP/TCP), `httpx>=0.27.0` (HTTPS Client hỗ trợ Certificate Pinning), `websockets>=12.0`, `tldextract>=5.1.1` (chạy chế độ offline snapshot để trích xuất chính xác tên miền cấp hai eTLD+1 cho trường `subject`).
- **Giao diện Khay hệ thống (Tray UI)**: `pystray>=0.19.5`, `Pillow>=10.2.0`, `tkinter` / `customtkinter>=5.2.2`.

---

## 2. Cấu Trúc Thư Mục & Đặc Tả Mô-đun (Module Specifications)

Cấu trúc thư mục dự án tuân thủ đúng Mục 8 (*Sản phẩm phải nộp*) trong `DoAn01.docx`:

```text
/
├── agent/                          # Mã nguồn OGK-Agent chạy trên Windows 10/11
│   ├── service/
│   │   ├── win_service.py          # OGKWindowsService (LocalSystem, SCM Recovery)
│   │   └── session_launcher.py     # SessionAgentLauncher (WTS API khởi chạy Tray UI)
│   ├── core/
│   │   ├── policy_verifier.py      # Kiểm tra chữ ký HMAC-SHA256 / RSA của Policy
│   │   ├── screen_time.py          # Monotonic Clock, Idle > 5p, Ma trận 7x48, Quota nhóm
│   │   ├── app_controller.py       # Quét tiến trình, SHA-256 LRU Cache + PE OriginalFileName
│   │   └── event_buffer.py         # Chuẩn hóa sự kiện 7 trường & hàng đợi Offline
│   ├── dns/
│   │   ├── dns_proxy.py            # Async UDP/TCP DNS Server tại 127.0.0.1:53
│   │   └── domain_engine.py        # Khớp miền gốc/con, 6 nhóm, SafeSearch, DoH Canary
│   ├── platform/
│   │   ├── network_guard.py        # Snapshot & khóa DNS card mạng, DnsFlushResolverCache
│   │   ├── browser_policy.py       # Snapshot & áp Registry tắt DoH trình duyệt
│   │   └── bypass_detector.py      # Phát hiện VPN Adapter, System Proxy, lệch đồng hồ
│   ├── ipc/
│   │   └── pipe_protocol.py        # Named Pipe Server/Client, IpcEnvelope, CallerSid
│   ├── sync/
│   │   └── server_client.py        # Enrollment, Heartbeat 60s, WSS < 5s, Cert Pinning
│   ├── ui/
│   │   └── tray_app.py             # Đồng hồ, Cảnh báo 10/5/1p, Ân hạn 60s, Minh bạch
│   ├── cleanup/
│   │   └── ogk_cleanup.py          # Khôi phục sạch DNS, Registry & gỡ Service hợp pháp
│   └── requirements.txt
├── server/                         # Mã nguồn OGK-Server (FastAPI)
│   ├── main.py                     # Khởi tạo FastAPI, TLS, Middleware, Lifespan tasks
│   ├── models/                     # SQLAlchemy ORM Models (User, Child, Device, Policy, Event, Audit)
│   ├── schemas/                    # Pydantic v2 Validation Schemas (Strict 7-field Event)
│   ├── auth/                       # Argon2id, Cookie Session, CSRF, RBAC, Anti-IDOR
│   ├── services/                   # Enrollment, PolicySigner, CommandHub, EventPurge, Reports
│   ├── routers/                    # /auth, /enroll, /heartbeat, /policy, /events, /commands, /reports, /audit
│   ├── seeds/                      # Seed tài khoản demo & >= 200 mục phân loại 6 nhóm an toàn
│   └── requirements.txt
├── dashboard/                      # Giao diện Phụ huynh & Màn hình Minh bạch cho Trẻ
│   ├── templates/                  # Jinja2 HTML Templates (Mobile-responsive)
│   └── static/                     # HTMX, Chart.js, CSS, Minh họa thân thiện cho trẻ
├── tests/                          # >= 15 Unit Tests & >= 5 Kịch bản Tích hợp tự động
├── docs/                           # Bộ tài liệu kiến trúc, đặc tả & báo cáo bắt buộc
│   ├── architecture.md
│   ├── functional-specification.md
│   ├── technical-specification.md
│   ├── feature-comparison.md
│   ├── architecture-change-log.md
│   ├── PRIVACY.md
│   ├── THREATMODEL.md
│   ├── AI_USAGE.md
│   ├── BaoCao.docx
│   └── BaoCaoKyThuatMang.pdf
├── demo/
│   └── video.mp4
└── README.md
```

---

## 3. Giao Thức Tương Tác Liên Thành Phần (Component Interactions & IPC)

### 3.1. Giao Thức IPC Cục Bộ Giữa `OGK-Service` và `OGK-Tray` (Kế thừa `REF-02`)
- **Kênh truyền**: Windows Named Pipe `\\.\pipe\OGKServicePipe` với Security Descriptor cho phép `SYSTEM`, `Administrators` và `Authenticated Users` kết nối, nhưng phân quyền thực thi theo `CallerSid`.
- **Định dạng bản tin (`IpcEnvelope`)**: Khuôn dạng độ dài tiền tố 4-byte (`uint32 little-endian`) theo sau là chuỗi UTF-8 JSON:

```json
{
  "protocol_version": 1,
  "request_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "type": "GET_SESSION_STATUS | REQUEST_MORE_TIME | VERIFY_PARENT_PIN | UNINSTALL_AUTH",
  "timestamp_utc": "2026-11-05T15:30:00Z",
  "caller_sid": "S-1-5-21-3623811015-3361044348-30300820-1013",
  "challenge_token": "8f4e2a1c9d0b...",
  "payload": {}
}
```

- **Quy tắc xác thực IPC**:
  1. `OGK-Service` gọi Win32 API `GetNamedPipeClientProcessId(pipe_handle)` và `OpenProcessToken` để lấy `actual_sid` từ nhân Windows, không tin tưởng mù quáng trường `caller_sid` trong JSON.
  2. Các lệnh đặc quyền (`VERIFY_PARENT_PIN`, `UNINSTALL_AUTH`) yêu cầu gọi `GET_CHALLENGE` trước để nhận `challenge_token` có hạn 30 giây, sau đó gửi kèm HMAC hoặc mật khẩu phụ huynh; Service kiểm tra bằng hàm thời gian cố định `hmac.compare_digest(expected, provided)` (chống Timing Attack).

### 3.2. Cơ Chế Khởi Chạy `OGK-Tray` Vượt Biên Giới Session 0 (Kế thừa `REF-01`)
Do Windows Service chạy ở Session 0 không có màn hình Desktop, `SessionAgentLauncher` thực hiện chu kỳ kiểm tra mỗi 3 giây:
1. Gọi `win32ts.WTSEnumerateSessions()` tìm phiên có trạng thái `WTSActive`.
2. Lấy SID của người dùng đang đăng nhập phiên đó qua `win32ts.WTSQueryUserToken(session_id)` + `GetTokenInformation(TokenUser)`.
3. Nếu SID thuộc hồ sơ trẻ đang được quản lý và chưa có tiến trình `ogk_tray.exe` chạy trong `session_id` đó:
   - Gọi `DuplicateTokenEx` tạo Primary Token, tạo khối môi trường `CreateEnvironmentBlock`, và gọi `CreateProcessAsUser` với `lpDesktop = "winsta0\\default"` để hiển thị `OGK-Tray` lên màn hình của trẻ.
4. **Thực thi quy tắc Chống Lạm Dụng (F5)**: Nếu sau 3 lần gọi `CreateProcessAsUser` liên tiếp mà `OGK-Tray` không kết nối vào Named Pipe để báo trạng thái hiển thị biểu tượng thành công, `OGK-Service` tự động chuyển sang trạng thái `UNPROTECTED_HALT` (dừng chặn/khóa) để tuân thủ nghiêm ngặt quy định *"Nếu không thể hiển thị biểu tượng, agent phải tự dừng"*.

---

## 4. Mô Hình Dữ Liệu & Lược Đồ Cơ Sở Dữ Liệu (Data Models)

### 4.1. Lược Đồ Cơ Sở Dữ Liệu Trên `OGK-Server` (`server.db` — SQLite WAL)

```sql
-- 1. Bảng Tài khoản Phụ huynh & Quản trị viên
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,           -- Argon2id hash (passlib)
    role TEXT NOT NULL DEFAULT 'parent',   -- 'parent' | 'admin'
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until_utc TEXT,                 -- Khóa 15 phút sau 5 lần sai
    totp_secret_enc BLOB,                  -- Mã hóa AES-256-GCM (Tùy chọn)
    created_at_utc TEXT NOT NULL
);

-- 2. Bảng Hồ sơ Trẻ em (1 Phụ huynh : n Trẻ)
CREATE TABLE children (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    birth_year INTEGER,
    age_group TEXT NOT NULL DEFAULT '6-11',
    avatar_code TEXT DEFAULT 'kid_default',
    created_at_utc TEXT NOT NULL
);
CREATE INDEX idx_children_parent ON children(parent_id);

-- 3. Bảng Thiết bị Máy trạm (1 Trẻ : m Thiết bị)
CREATE TABLE devices (
    id TEXT PRIMARY KEY,
    child_id TEXT NOT NULL REFERENCES children(id) ON DELETE CASCADE,
    device_name TEXT NOT NULL,
    fingerprint_hash TEXT NOT NULL,
    windows_user_sid TEXT,                 -- SID tài khoản Standard User của trẻ
    refresh_token_hash TEXT,               -- SHA-256 hash của Refresh Token hiện hành
    token_revoked INTEGER NOT NULL DEFAULT 0,
    applied_policy_version INTEGER NOT NULL DEFAULT 0,
    last_heartbeat_utc TEXT,
    last_clock_drift_sec INTEGER DEFAULT 0,
    created_at_utc TEXT NOT NULL
);
CREATE INDEX idx_devices_child ON devices(child_id);

-- 4. Bảng Mã Ghép Đôi (Hiệu lực 10 phút + Ghi nhận đồng ý Nghị định 13/2023)
CREATE TABLE pairing_codes (
    code TEXT PRIMARY KEY,                 -- 8 ký tự [A-Z0-9]
    parent_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    child_id TEXT NOT NULL REFERENCES children(id) ON DELETE CASCADE,
    consent_confirmed INTEGER NOT NULL CHECK (consent_confirmed = 1),
    expires_at_utc TEXT NOT NULL,
    used_at_utc TEXT
);

-- 5. Bảng Chính sách (Versioned & Signed Policy)
CREATE TABLE policies (
    id TEXT PRIMARY KEY,
    child_id TEXT UNIQUE NOT NULL REFERENCES children(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    daily_limit_weekday_min INTEGER NOT NULL DEFAULT 90,
    daily_limit_weekend_min INTEGER NOT NULL DEFAULT 120,
    schedule_matrix_7x48 TEXT NOT NULL,    -- Chuỗi 336 ký tự '0'/'1' (7 ngày x 48 khung 30p)
    category_budgets_json TEXT NOT NULL,   -- {"education": -1, "gaming": 45, ...}
    app_rules_json TEXT NOT NULL,          -- Danh sách AppRule kèm SHA-256 & OriginalFileName
    domain_rules_json TEXT NOT NULL,       -- Danh sách tên miền 6 nhóm + SafeSearch + DoH
    offline_pin_hash TEXT,                 -- Argon2id hash cho mở khóa/gỡ cài đặt offline
    updated_at_utc TEXT NOT NULL,
    signature TEXT NOT NULL                -- HMAC-SHA256 / RSA-PSS trên toàn bộ nội dung Policy
);

-- 6. Bảng Sự Kiện Hoạt Động (TUÂN THỦ TUYỆT ĐỐI LƯỢC ĐỒ 7 TRƯỜNG MỤC F3)
CREATE TABLE events (
    idempotency_key TEXT PRIMARY KEY,      -- Khóa chống trùng khi đồng bộ lô (Mục 4.3)
    ts TEXT NOT NULL,                      -- ISO-8601 UTC timestamp
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    child_id TEXT NOT NULL REFERENCES children(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN (
        'app_start', 'app_stop', 'domain_query',
        'blocked_app', 'blocked_domain', 'quota_warning',
        'locked', 'unlock_request', 'override_granted'
    )),
    subject TEXT NOT NULL,                 -- Tên ứng dụng HOẶC tên miền cấp hai (KHÔNG lưu URL đầy đủ)
    duration_sec INTEGER NOT NULL DEFAULT 0,
    policy_id TEXT NOT NULL
);
CREATE INDEX idx_events_child_ts ON events(child_id, ts);
CREATE INDEX idx_events_ts ON events(ts);  -- Phục vụ tác vụ xóa tự động sau 90 ngày

-- 7. Bảng Nhật Ký Kiểm Toán (Audit Log - Nguyên tắc NT5 Mục F4)
CREATE TABLE audit_logs (
    id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    child_id TEXT REFERENCES children(id) ON DELETE CASCADE,
    ip_address TEXT NOT NULL,
    action TEXT NOT NULL,
    old_value_json TEXT,
    new_value_json TEXT
);
CREATE INDEX idx_audit_child_ts ON audit_logs(child_id, ts_utc DESC);
```

### 4.2. Lược Đồ Bộ Nhớ Đệm Cục Bộ Trên `OGK-Agent` (`C:\ProgramData\OGK\agent.db`)
1. `cached_policy`: Lưu bản sao JSON chính sách gần nhất kèm `version`, `signature` và `fetched_at_utc`.
2. `event_queue`: Lưu các sự kiện chờ đồng bộ gồm `idempotency_key`, `ts`, `device_id`, `child_id`, `type`, `subject`, `duration_sec`, `policy_id`, `synced` (`0`/`1`).
3. `daily_usage_state`: Lưu `date_local`, `used_total_sec`, `category_used_json`, `last_monotonic_sec`, `last_wall_clock_utc` (phục vụ chống chỉnh đồng hồ hệ thống).
4. `system_snapshots` *(Kế thừa từ `SafeKids.Platform`)*: Lưu trạng thái gốc trước khi Agent can thiệp hệ thống:
   - `snapshot_type = 'NETWORK_DNS'`: Lưu JSON `[{"interface_index": 12, "name": "Wi-Fi", "dhcp_enabled": true, "dns_servers": []}]`.
   - `snapshot_type = 'BROWSER_REGISTRY'`: Lưu JSON trạng thái ban đầu của các khóa `HKLM\SOFTWARE\Policies\Google\Chrome\DnsOverHttpsMode`, `Edge`, `Brave`, `CocCoc`.

---

## 5. Đặc Tả REST API & WebSocket (API Specifications)

### 5.1. Danh Mục Điểm Cuối REST API (`HTTPS TLS 1.2+`)

| Nhóm | Phương thức & Đường dẫn | Xác thực | Mô tả xử lý |
|---|---|---|---|
| **Auth** | `POST /api/v1/auth/login` | Public (Rate-limited) | Xác thực `email` + `password` bằng Argon2id; kiểm tra khóa 15 phút nếu sai $\ge 5$ lần; cấp Cookie `HttpOnly, Secure, SameSite=Lax` + `csrf_token`. |
| **Auth** | `POST /api/v1/auth/logout` | Cookie + CSRF | Hủy phiên trên Server và xóa Cookie. |
| **Enroll** | `POST /api/v1/enroll/code` | `parent` + CSRF | Phụ huynh xác nhận đồng ý (NĐ 13/2023) và tạo mã ghép đôi 8 ký tự (TTL 10 phút) cho `child_id`. |
| **Enroll** | `POST /api/v1/enroll` | Public (Rate-limited) | Agent gửi `pairing_code`, `device_fingerprint`, `windows_user_sid`; nhận `device_id`, `access_token` (15p), `refresh_token` và `policy`. |
| **Auth** | `POST /api/v1/auth/device/refresh` | Refresh Token | Đổi `refresh_token` lấy `access_token` mới (kiểm tra cờ `token_revoked`). |
| **Agent Sync** | `POST /api/v1/heartbeat` | Device Bearer JWT | Nhịp tim 60 giây: nhận `{used_sec, local_utc, monotonic_sec, policy_version}`; kiểm tra độ lệch đồng hồ (`clock_drift`); trả `{server_utc, latest_policy_version, pending_commands}`. |
| **Agent Sync** | `GET /api/v1/policy` | Device Bearer JWT | Tải gói chính sách mới nhất kèm chữ ký toàn vẹn `signature` (`HMAC-SHA256` / `RSA`). |
| **Events** | `POST /api/v1/events/batch` | Device Bearer JWT | Nhận lô sự kiện (ràng buộc đúng 7 trường F3 + `idempotency_key`); khử trùng lặp và lưu DB. |
| **Commands** | `POST /api/v1/commands` | `parent` + CSRF | Phụ huynh phát lệnh khẩn (`LOCK_NOW`, `UNLOCK`, `ADD_TIME_15M`, `PARENT_PAUSE_2H`); kiểm tra chống IDOR; đẩy qua WebSocket tới Agent trong $< 5\text{s}$ và ghi Audit Log. |
| **Reports** | `GET /api/v1/reports/{child_id}` | `parent` / `child-view` | Trả dữ liệu thống kê ngày/tuần, Top 10 ứng dụng, Top 10 tên miền, số lần chặn (cùng nguồn dữ liệu cho cả phụ huynh và màn hình minh bạch của trẻ). |
| **Audit** | `GET /api/v1/audit/{child_id}` | `parent` / `child-view` | Trả danh sách Nhật ký kiểm toán (ai, lúc nào, IP, giá trị cũ/mới) theo nguyên tắc NT5. |
| **Privacy** | `DELETE /api/v1/privacy/children/{child_id}/events` | `parent` + CSRF | Thực thi nút **"Xóa toàn bộ dữ liệu của con tôi"**: xóa sạch bảng `events` của `child_id` trên Server và đẩy lệnh `PURGE_DATA` xuống Agent. |

### 5.2. Giao Thức WebSocket Lệnh Khẩn (`/ws/agent/{device_id}`)
- **Kết nối**: `wss://<server_host>/ws/agent/{device_id}` với Header `Authorization: Bearer <access_token>`.
- **Bản tin Lệnh Khẩn từ Server $\rightarrow$ Agent**:
```json
{
  "msg_type": "URGENT_COMMAND",
  "command_id": "cmd_01HXYZ...",
  "command": "LOCK_NOW | UNLOCK | ADD_TIME_15M | PARENT_PAUSE_2H | PURGE_DATA | POLICY_UPDATED",
  "params": {"bonus_seconds": 900},
  "issued_at_utc": "2026-11-05T15:35:00Z",
  "signature": "hmac_sha256_hex_digest"
}
```
- **Bản tin Xác nhận từ Agent $\rightarrow$ Server**:
```json
{
  "msg_type": "COMMAND_ACK",
  "command_id": "cmd_01HXYZ...",
  "status": "EXECUTED",
  "executed_at_utc": "2026-11-05T15:35:01Z"
}
```

---

## 6. Đặc Tả Kỹ Thuật Hệ Thống & Mạng Trọng Tâm (M1 – M6)

Mục này đặc tả chi tiết kỹ thuật cho **6 hạng mục bắt buộc trong Phụ lục Báo cáo Kỹ thuật Mạng (`BaoCaoKyThuatMang.pdf`)**:

### 6.1. M1 — Luồng Gói Tin Qua DNS Proxy Cục Bộ (`127.0.0.1:53`)
1. **Cấu hình Hệ thống**: Card mạng của máy trẻ có `NameServer = 127.0.0.1`.
2. **Đường đi gói tin**:
   - Bước 1: Trình duyệt gọi hàm phân giải tên miền của hệ điều hành (`getaddrinfo`).
   - Bước 2: Dịch vụ Windows DNS Client (`Dnscache` / Stub Resolver) gửi gói tin `Standard query A/AAAA` qua giao thức UDP (hoặc TCP) từ cổng nguồn ngẫu nhiên `127.0.0.1:<ephemeral_port>` tới đích `127.0.0.1:53`.
   - Bước 3: `OGK DNS Proxy` bắt gói tin trên giao diện Loopback (`\Device\NPF_Loopback` khi bắt bằng Wireshark), chuẩn hóa tên miền (`qname.lower().rstrip('.')`) và tra cứu trong `DomainPolicyEngine` (cấu trúc cây hậu tố Suffix Trie / HashSet đạt độ phức tạp $O(k)$ với $k$ là số nhãn tên miền).
   - Bước 4:
     - Nếu bị chặn: Trả bản tin DNS Response có cờ `QR=1, RA=1`, `RCODE=0` kèm `A 0.0.0.0` (hoặc `RCODE=3 NXDOMAIN`), `TTL=60`.
     - Nếu là máy chủ tìm kiếm cần SafeSearch: Trả bản ghi `CNAME forcesafesearch.google.com` kèm địa chỉ IP mục tiêu.
     - Nếu được phép: Kiểm tra Cache nội bộ; nếu chưa có thì chuyển tiếp truy vấn ra card mạng vật lý tới Upstream DNS (`1.1.1.1:53`), nhận phản hồi rồi trả về cho Stub Resolver.

### 6.2. M2 — Bảng So Sánh 4 Phương Án Chặn Website

| Tiêu chí đánh giá | 1. Tệp `hosts` *(Phương pháp của Safe Kids v5.1.27)* | 2. DNS Proxy cục bộ `127.0.0.1:53` *(Phương án chính của OGK)* | 3. HTTP/HTTPS Proxy cục bộ | 4. Bộ lọc WFP (Windows Filtering Platform) |
|---|---|---|---|---|
| **1. Độ chính xác** | **Thấp – Trung bình**: Chỉ khớp chính xác từng hostname liệt kê; **không** hỗ trợ wildcard `*.domain.com`. | **Cao**: Hỗ trợ khớp chính xác tên miền gốc và toàn bộ tên miền con (`*.domain.com`), hỗ trợ CNAME SafeSearch. | **Rất cao**: Lọc được tới mức đường dẫn URL đầy đủ nếu giải mã TLS (MITM). | **Cao**: Lọc theo địa chỉ IP, cổng, tiến trình và SNI (ở tầng gói tin). |
| **2. Khả năng chặn HTTPS** | **Có** (chặn trước khi thiết lập kết nối TCP/TLS). | **Có** (chặn ở pha phân giải tên miền trước khi bắt tay TLS, không cần cài chứng chỉ CA giả mạo trình duyệt). | Cần xem xét SNI (`CONNECT`) hoặc cài Root CA vào máy để giải mã HTTPS (gây rủi ro bảo mật). | **Có** (chặn kết nối TCP/IP hoặc kiểm tra trường TLS ClientHello SNI). |
| **3. Chi phí hiện thực** | **Rất thấp** (chỉ đọc/ghi tệp văn bản). | **Trung bình – Khá** (xây dựng UDP/TCP DNS Server bằng Python `dnslib` + `asyncio` trong 6 tuần). | **Cao** (xử lý chứng chỉ số, hiệu năng luồng TCP và tương thích ứng dụng). | **Rất cao** (đòi hỏi lập trình C/C++ Kernel Callout Driver hoặc WinDivert/WFP API phức tạp). |
| **4. Khả năng bị vượt** | Dễ bị vượt bởi DoH, đổi tên miền con (`sub1.domain.com`) hoặc truy cập IP trực tiếp. | Có thể bị vượt nếu bật DoH hoặc đổi DNS thủ công $\rightarrow$ **Khắc phục trong OGK** bằng chặn DoH Canary + Browser Registry Policy + Khóa DNS Card mạng. | Bị vượt nếu ứng dụng không tôn trọng cấu hình System Proxy. | Khó bị vượt nhất ở tầng mạng cục bộ, nhưng vẫn bị vượt bởi VPN mã hóa nếu không chặn ứng dụng VPN. |
| **5. Ảnh hưởng hiệu năng** | Khi tệp `hosts` $> 50.000$ dòng (như `SafeKids` có 83.776 dòng), dịch vụ `Dnscache` của Windows có thể tăng CPU đột biến khi nạp lại. | **Rất nhẹ**: Tra cứu trong bộ nhớ RAM ($< 1\text{ ms}$) và có bộ nhớ đệm DNS Cache; không ảnh hưởng băng thông tải dữ liệu. | **Nặng hơn**: Mọi lưu lượng tải trang/video đều phải đi qua tiến trình Proxy. | **Nhẹ** nhưng nếu xử lý ở User-mode không khéo sẽ làm tăng độ trễ mọi gói tin mạng. |

### 6.3. M3 — Phân Tích 9 Kỹ Thuật Đường Vòng (Bypass Vectors) & Biện Pháp Đối Phó

| # | Kỹ thuật vượt rào | Mô tả cơ chế vượt | Biện pháp đối phó trong kiến trúc OGK (Kết hợp từ `Safe Kids` & Yêu cầu Giảng viên) |
|---|---|---|---|
| **1** | **Đổi DNS thủ công** (vd: đổi sang `8.8.8.8`) | Trẻ mở Network Connections đổi DNS IPv4 để không đi qua `127.0.0.1:53`. | 1) Tài khoản trẻ là Standard User nên bị giới hạn quyền sửa cấu hình card mạng.<br>2) `NetworkDnsGuard` (học từ `REF-10`) định kỳ kiểm tra DNS card mạng; nếu lệch khỏi `127.0.0.1` sẽ lập tức ép lại về `127.0.0.1` và gọi `DnsFlushResolverCache()`. |
| **2** | **DNS-over-HTTPS (DoH)** | Trình duyệt gửi truy vấn DNS mã hóa qua cổng HTTPS 443. | 1) Trả `NXDOMAIN` cho tên miền canary `use-application-dns.net` (Firefox).<br>2) Chặn phân giải danh sách điểm cuối DoH phổ biến (`dns.google`, `cloudflare-dns.com`...).<br>3) Áp Registry Group Policy tắt DoH (`DnsOverHttpsMode = "off"`) trên Chrome/Edge/Brave/Cốc Cốc (`REF-08`). |
| **3** | **DNS-over-TLS (DoT)** | Truy vấn DNS qua cổng TCP/UDP 853. | Chặn các tên miền máy chủ DoT phổ biến trong DNS Proxy và kiểm tra kết nối cổng 853 trong `BypassDetector`. |
| **4** | **VPN / Proxy công cộng** | Dùng phần mềm VPN (WARP, OpenVPN, Ultrasurf) hoặc trình duyệt tích hợp VPN. | 1) `App Controller` chặn tệp thực thi của các công cụ VPN phổ biến theo SHA-256 (`REF-03`).<br>2) `BypassDetector` quét giao diện mạng ảo (TAP/TUN/WireGuard) và Registry `ProxyEnable` (`REF-09`) để cảnh báo phụ huynh. |
| **5** | **Truy cập trực tiếp bằng địa chỉ IP** | Nhập `https://1.2.3.4` vào thanh địa chỉ để bỏ qua bước phân giải DNS. | Hầu hết các trang web hiện đại dùng CDN/Virtual Hosting (Cloudflare/SNI) và chứng chỉ TLS gắn với tên miền nên truy cập trực tiếp bằng IP sẽ bị lỗi chứng chỉ TLS hoặc lỗi `403 Direct IP access not allowed`. Ghi nhận rõ giới hạn của phương pháp thuần DNS trong báo cáo M3. |
| **6** | **Kết thúc tiến trình Agent (Kill Process)** | Dùng Task Manager hoặc `taskkill` để tắt Agent. | 1) `OGK-Service` chạy dưới quyền `NT AUTHORITY\SYSTEM`, tài khoản Standard User của trẻ bị hệ điều hành từ chối quyền `TerminateProcess` (`Access Denied`).<br>2) Nếu trẻ tắt `OGK-Tray`, `SessionAgentLauncher` tự động khởi chạy lại sau $\le 3\text{ giây}$ (`REF-01`). |
| **7** | **Chỉnh lùi đồng hồ hệ thống** | Lùi giờ Windows về 3 tiếng trước để có thêm thời gian chơi. | Bộ đếm thời gian dùng đồng hồ đơn điệu `time.monotonic()` kết hợp lưu `last_wall_clock_utc` và đối chiếu `server_utc` mỗi nhịp tim 60 giây (`REF-13` / M6). |
| **8** | **Đăng nhập bằng tài khoản Windows khác** | Chuyển sang tài khoản User khác trên cùng máy tính để thoát giám sát. | Tài khoản trẻ là Standard User nên không thể tự tạo tài khoản mới; `OGK-Service` chạy toàn hệ thống (Session 0) và kiểm tra mọi phiên đăng nhập không thuộc nhóm `Administrators` (`REF-15`). |
| **9** | **Khởi động Safe Mode hoặc Boot từ USB** | Vào Safe Mode (nơi dịch vụ bên thứ ba không chạy) hoặc dùng USB Live OS. | Giải pháp chuẩn ở cấp cấu hình hệ thống: đặt mật khẩu BIOS/UEFI (chặn Boot từ USB) và vô hiệu hóa quyền khởi động lại vào Safe Mode của Standard User; đồng thời `OGK-Server` phát hiện mất nhịp tim (Heartbeat) bất thường trong khung giờ trẻ thường dùng máy. |

### 6.4. M4, M5, M6 — Đo Hiệu Năng, Chịu Lỗi & Đồng Bộ Thời Gian
- **M4 (Phương pháp đo hiệu năng — $\ge 30$ mẫu/phép đo)**:
  - Kịch bản tự động `tests/benchmark_m4.py` thu thập 30 mẫu liên tiếp cho: (1) CPU `%` và RAM `RSS (MB)` của `OGK-Service` + `OGK-Tray` ở trạng thái rảnh (Idle) và trạng thái cao điểm (gửi 50 truy vấn DNS/giây + quét 150 tiến trình); (2) Độ trễ phân giải DNS ($p_{50}, p_{95}$ tính bằng `ms`) khi không bật Agent, khi bật Agent (Cache Miss) và khi bật Agent (Cache Hit); (3) Độ trễ áp dụng chính sách và lệnh khẩn từ lúc gọi API trên Server đến lúc Agent thực thi xong (30 lần đo).
- **M5 (Khả năng chịu lỗi)**: Kiểm thử tự động và thực tế cho 3 kịch bản: ngắt card mạng (Offline queueing + Idempotent sync), dừng `OGK-Server` (Backoff reconnect), và `taskkill /F /IM ogk_tray.exe` (tự khôi phục trong $\le 3\text{ giây}$).
- **M6 (Đồng bộ thời gian & Chống chỉnh giờ)**:
  - Công thức tính thời gian hoạt động mỗi chu kỳ $\Delta t = \text{monotonic\_now} - \text{monotonic\_prev}$ (chỉ cộng vào `used_total_sec` khi `0 < \Delta t <= 10` và `idle_sec <= 300`).
  - Tại mỗi nhịp tim 60 giây: $\text{drift\_sec} = |\text{agent\_wall\_clock\_utc} - \text{server\_utc}|$. Nếu $\text{drift\_sec} > 120\text{ giây}$, hệ thống ghi nhận cảnh báo lệch đồng hồ và sử dụng `server_utc` làm mốc tham chiếu cho ma trận lịch tuần $7 \times 48$.

---

## 7. Phụ Thuộc Bên Ngoài & Ràng Buộc Kỹ Thuật (External Dependencies & Constraints)

1. **Không phụ thuộc dịch vụ đám mây trả phí**: Toàn bộ `OGK-Server`, `OGK-Agent` và `Dashboard` hoạt động độc lập 100% trong mạng LAN phòng lab hoặc máy ảo cục bộ.
2. **Tương thích Hệ điều hành**: `OGK-Agent` yêu cầu Windows 10 hoặc Windows 11 (64-bit) với quyền Administrator ở bước cài đặt ban đầu (để đăng ký Windows Service và thiết lập ACL thư mục `C:\ProgramData\OGK`).
3. **An toàn Dữ liệu Kiểm thử**: Tệp seed phân loại 200+ tên miền (`server/seeds/domain_catalog.json`) và bộ 50 tên miền kiểm thử chỉ chứa các tên miền giáo dục/tin tức hợp lệ và các tên miền mô phỏng trung tính (`.test`, `.example`), tuân thủ tuyệt đối quy định tại Mục F2.

---

## 8. Xử Lý Lỗi Kỹ Thuật & Tối Ưu Hiệu Năng (Error Handling & Performance)

1. **Tối ưu CPU khi tính SHA-256 Tiến trình (`SHA-256 LRU Cache`)**:
   - Việc băm SHA-256 một tệp thực thi lớn (ví dụ trò chơi $200\text{ MB}$) mỗi 2 giây sẽ gây tốn đĩa và CPU. Do đó, `App Controller` lưu bộ nhớ đệm `LRUCache(maxsize=512)` với khóa là bộ ba `(exe_path, st_mtime_ns, st_size)`. Chỉ khi tệp thực thi mới xuất hiện hoặc bị sửa đổi trên đĩa thì hệ thống mới tính lại SHA-256. Nhờ đó mức sử dụng CPU lúc rảnh duy trì ở mức $< 1\%$.
2. **Tối ưu Độ trễ DNS Proxy (`Async In-Memory Trie & TTL Cache`)**:
   - Toàn bộ danh sách tên miền phân loại được nạp vào cấu trúc bảng băm trong RAM (`set` cho khớp chính xác và `Suffix Trie` cho khớp tên miền con). Thời gian tra cứu một tên miền đạt $< 0.2\text{ ms}$.
3. **An toàn Giao dịch Cơ sở dữ liệu (SQLite WAL & Busy Timeout)**:
   - Cả `server.db` và `agent.db` đều bật `PRAGMA journal_mode=WAL` và `PRAGMA busy_timeout=5000` để cho phép đọc/ghi đồng thời giữa luồng DNS Proxy, luồng App Controller và luồng Đồng bộ mạng mà không bao giờ gặp lỗi `database is locked`.
