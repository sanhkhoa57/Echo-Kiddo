# OGK (Open Guardian for Kids)

> **"Công cụ đồng hành, không phải phần mềm theo dõi lén"**  
> *A Transparent Companion, Not Stalkerware*  
> Nền tảng: **Windows 10 / 11 (x64)** kết hợp máy chủ quản trị tập trung **FastAPI + SQLite WAL**.

---

## 1. Giới Thiệu Dự Án

**OGK (Open Guardian for Kids)** là giải pháp toàn diện giúp phụ huynh và trẻ em cùng đồng hành, thiết lập thói quen sử dụng máy tính cân bằng, lành mạnh và an toàn:
- **Minh bạch theo thiết kế (No Stealth Mode)**: Khay hệ thống `OGK-Tray` luôn hiển thị thời gian còn lại. Nếu khay hệ thống không hiển thị được sau 3 lần thử, `OGK-Service` tự động chuyển sang chế độ an toàn `UNPROTECTED_HALT` để không bao giờ hoạt động như phần mềm theo dõi lén.
- **Tối thiểu hóa dữ liệu (Lược đồ sự kiện 7 trường F3)**: Chỉ lưu đúng 7 trường nghiệp vụ (`ts, device_id, child_id, type, subject, duration_sec, policy_id`). Trường `subject` chỉ lưu tên file thực thi hoặc tên miền cấp hai eTLD+1 (từ chối hoàn toàn đường dẫn URL chi tiết).
- **Tuyệt đối không chụp màn hình / không DOM extension**: Tôn trọng quyền riêng tư của trẻ theo **Nghị định 13/2023/NĐ-CP** và **Luật Trẻ em 2016**.
- **An toàn hệ thống (Snapshot & Clean Rollback)**: Toàn bộ can thiệp mạng (`127.0.0.1:53`) và Registry trình duyệt (`DnsOverHttpsMode=off`) đều chụp Snapshot vào `agent.db` và được hoàn trả sạch 100% khi dừng hoặc gỡ cài đặt.

---

## 2. Cấu Trúc Mã Nguồn

Tuân thủ nghiêm ngặt Mục 2 của `docs/technical-specification.md`:

```text
ogk/
├── agent/                       # OGK-Agent trên Windows 10/11 x64
│   ├── cleanup/                 # Công cụ khôi phục sạch 100% (ogk_cleanup.py)
│   ├── core/                    # Bộ đếm giờ, App Controller, Event Buffer, SQLite
│   ├── dns/                     # DNS Proxy Server (UDP/TCP), Domain Engine, Suffix Trie
│   ├── ipc/                     # Named Pipe (\\.\pipe\OGKServicePipe), IpcEnvelope
│   ├── platform/                # Network Guard (netsh), Browser Policy (DoH), Bypass Detector
│   ├── service/                 # Windows Service (LocalSystem), SessionAgentLauncher (WTS)
│   ├── sync/                    # Server Client (HTTPS Cert Pinning, WebSocket Command Hub)
│   └── ui/                      # Khay hệ thống pystray + Tkinter UI
├── server/                      # OGK-Server (FastAPI + SQLite WAL)
│   ├── auth/                    # Argon2id, JWT, Anti-IDOR, CSRF Token
│   ├── models/                  # SQLAlchemy 2.0 ORM (8 bảng CSDL)
│   ├── migrations/              # Alembic (0001_initial_schema) + alembic.ini
│   ├── routers/                 # REST API v1 (Auth, Enroll, Policy, Events, Commands, Reports)
│   ├── schemas/                 # Pydantic v2 schemas với validator eTLD+1 nghiêm ngặt
│   ├── seeds/                   # Danh mục 235 tên miền an toàn mẫu (domain_catalog.json)
│   └── services/                # Policy Signer (HMAC), Realtime WebSocket Command Hub
├── dashboard/                   # Web Dashboard (Jinja2 + HTMX + Chart.js)
│   └── templates/               # Giao diện Phụ huynh, "Hôm nay em đã dùng gì", Audit Trail
├── demo/                        # Kịch bản Demo & Seeder dữ liệu mẫu (seed_demo.py)
├── docs/                        # Tài liệu đặc tả: Kiến trúc, Chức năng, Kỹ thuật, Privacy, Threat Model
└── tests/                       # 143 automated test cases (Unit & E2E Integration)
```

---

## 3. Hướng Dẫn Cài Đặt Hoàn Chỉnh Trong $\le 15$ Phút

### 3.1. Yêu Cầu Môi Trường
- **Hệ điều hành**: Windows 10 hoặc Windows 11 (64-bit).
- **Ngôn ngữ**: Python 3.11+ x64.
- **Quyền**: Administrator (khi đăng ký Windows Service hoặc cấu hình card mạng).

### 3.2. Cài Đặt Môi Trường Ảo & Thư Viện (3 phút)
Mở PowerShell (Run as Administrator):

```powershell
# 1. Điều hướng vào thư mục dự án
cd "d:\Trong\1. Đại học\Hk 1 2026-2027\2. Mạng máy tính\1. Đồ án"

# 2. Tạo và kích hoạt môi trường ảo Python
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Nâng cấp pip và cài đặt toàn bộ thư viện
pip install --upgrade pip
pip install -r server/requirements.txt
pip install -r agent/requirements.txt
```

### 3.3. Khởi Tạo Dữ Liệu Mẫu Demo (1 phút)
Chạy script seeder để tự động tạo tài khoản Phụ huynh, hồ sơ Bé Minh, thiết bị Windows 11, ma trận lịch tuần 7x48 và khoảng 100 sự kiện hoạt động trong 7 ngày gần nhất (chạy lại script sẽ tự làm mới dữ liệu cũ hơn 12 giờ):

```powershell
python demo/seed_demo.py
```

*Thông tin đăng nhập demo:*
- **URL Dashboard**: `http://127.0.0.1:8000/login`
- **Email**: `parent@ogk.local`
- **Mật khẩu**: `AdminPassword123!`

### 3.3b. Migration CSDL (Alembic)
Tạo/nâng cấp schema chính thức của server (chạy từ thư mục gốc dự án):

```powershell
$env:PYTHONPATH = "."
alembic -c server/alembic.ini upgrade head     # tạo/nâng cấp bảng
alembic -c server/alembic.ini downgrade base   # hoàn tác (chỉ dùng khi thử nghiệm)
```

Khi đổi model: `alembic -c server/alembic.ini revision --autogenerate -m "mô tả"`. Server vẫn tự `create_all` khi khởi động để demo chạy ngay; migration là đường nâng cấp có đánh phiên bản.

### 3.4. Khởi Chạy Nhanh Cho Phòng Lab & Đánh Giá (All-in-One Lab Hub)
Để thiết lập chứng chỉ bảo mật TLS tự ký (Self-Signed Cert với SAN `localhost`, `127.0.0.1`, LAN IP), trích xuất SHA-256 Fingerprint phục vụ Certificate Pinning và khởi chạy nhanh mọi dịch vụ:

```powershell
# Cách 1: Sử dụng PowerShell Launcher
.\scripts\run_dev.ps1 setup       # Sinh chứng chỉ TLS + nạp CSDL mẫu
.\scripts\run_dev.ps1 server      # Khởi động Server qua HTTPS trên 0.0.0.0:8000
.\scripts\run_dev.ps1 agent       # Khởi động Agent có Certificate Pinning
.\scripts\run_dev.ps1 tray        # Khởi động Tray UI hiển thị trực quan
.\scripts\run_dev.ps1 all         # Tự động setup + chạy toàn bộ 143 tests + benchmark M4

# Cách 2: Sử dụng Python trực tiếp
python scripts/setup_lab.py
```

---

## 4. Vận Hành Hệ Thống

### 4.1. Khởi Động Máy Chủ OGK-Server (Terminal 1)
```powershell
.\.venv\Scripts\Activate.ps1
uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```
Truy cập trình duyệt:
- Bảng điều khiển phụ huynh: `http://127.0.0.1:8000/dashboard`
- Màn hình minh bạch của trẻ ("Hôm nay em đã dùng gì"): `http://127.0.0.1:8000/child-view`. Phụ huynh bấm **"Giao máy cho con xem"** để chuyển trình duyệt sang vai trò `child-view` (chỉ đọc báo cáo và nhật ký của đúng một bé; phiên phụ huynh bị đăng xuất).
- Nhật ký kiểm toán minh bạch (Audit Trail): `http://127.0.0.1:8000/audit/view`
- Tài liệu tương tác API Swagger: `http://127.0.0.1:8000/docs`

### 4.2. Khởi Động OGK-Agent (Terminal 2)
```powershell
.\.venv\Scripts\Activate.ps1
python agent/service/win_service.py run
```
*Hoặc khởi chạy riêng lẻ giao diện Khay hệ thống:*
```powershell
python agent/ui/tray_app.py
```

### 4.3. Gỡ Cài Đặt & Khôi Phục Sạch 100% (Clean Rollback)
Để hoàn trả lại cấu hình mạng và Registry của hệ thống 100% nguyên vẹn như ban đầu:
```powershell
python agent/cleanup/ogk_cleanup.py --pin 1234
```
*(Hoặc dùng tham số `--force` trong kịch bản kiểm thử tự động).*

---

## 5. Chạy Kiểm Thử & Đo Lường Hiệu Năng (M4)

### 5.1. Chạy Toàn Bộ Test Suite (143 Tests)
```powershell
pytest -v
```
Toàn bộ 143 kiểm thử bao gồm:
- **Unit Tests**: Mã hóa Argon2id, chống IDOR, xác thực chữ ký HMAC-SHA256, kiểm tra ma trận 7x48, đồng hồ đơn điệu `time.monotonic()`, phát hiện chỉnh lùi giờ, Suffix Trie $O(k)$, cache DNS TTL.
- **5 Kịch bản Tích hợp End-to-End**:
  1. Quy trình Ghép đôi thiết bị (Nghị định 13/2023).
  2. Lệnh khẩn tức thời qua WebSocket (`LOCK_NOW`, `UNLOCK`, `ADD_TIME_15M`).
  3. Hết hạn mức, cửa sổ ân hạn 60 giây và xin thêm giờ.
  4. Lọc DNS, cưỡng chế SafeSearch và chống đổi DNS thủ công.
  5. Xóa sạch dữ liệu của trẻ và khôi phục hệ thống sạch 100%.

### 5.2. Đo Lường Hiệu Năng M4 (>= 30 Mẫu Liên Tục)
```powershell
python tests/benchmark_m4.py
```
Kết quả đo lường tự động lưu tại `docs/benchmark_m4_results.md` (số liệu thay đổi theo máy, xem file để có số mới nhất):
- CPU và RAM lúc rảnh và lúc cao điểm.
- Độ trễ DNS p50/p95 **không có Agent** (UDP thẳng tới 1.1.1.1) so với **có Agent** (qua DNS Proxy: cache miss, cache hit, sinkhole), đo trên mạng thật. Đặt `OGK_BENCH_OFFLINE=1` nếu máy không có Internet.
- Độ trễ đầu-cuối Dashboard → Server → WebSocket → Agent cho chính sách mới (ngưỡng 60 s) và lệnh khẩn `LOCK_NOW` (ngưỡng 5 s).

Sau khi chạy benchmark, sinh lại tài liệu nộp bài:
```powershell
python scripts/gen_baocao_mang.py   # docs/BaoCaoKyThuatMang.pdf (bảng M4 đọc từ benchmark_m4_results.md)
python scripts/gen_baocao.py        # docs/BaoCao.docx (mở bằng Word, chuột phải vào mục lục > Update Field)
```

### 5.3. Ghim Chứng Chỉ & Mã Hóa Dữ Liệu Agent
- `scripts/setup_lab.py` in ra `OGK_PINNED_CERT_FINGERPRINT`. Đặt biến này trước khi chạy Agent; Agent từ chối kết nối HTTPS/WSS nếu chứng chỉ máy chủ không khớp.
- Token và khóa HMAC trong `agent.db` được mã hóa AES-256-GCM. Khóa lấy từ `OGK_AGENT_DATA_KEY` (base64 của 32 byte) hoặc tự sinh lần đầu trong `agent.key` bọc bằng DPAPI.

---

## 6. Tài Liệu Kèm Theo
- [Chính sách & Minh bạch Quyền Riêng tư](docs/PRIVACY.md) (kèm phiên bản dành riêng cho trẻ em).
- [Mô hình Mối đe dọa STRIDE](docs/THREATMODEL.md) (phân tích chi tiết 8 mối đe dọa trọng tâm).
- [Báo cáo Hiệu năng M4](docs/benchmark_m4_results.md).
- [Tuyên bố Sử dụng Trợ lý AI](docs/AI_USAGE.md).
