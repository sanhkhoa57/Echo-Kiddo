# Nhật Ký Thay Đổi Kiến Trúc, Truy Vết Yêu Cầu & Kiểm Toán Nhất Quán (Architecture Change Log & Traceability)

> **Tài liệu thuộc bộ đặc tả kiến trúc dự án EC - Echo Kiddo**
> - [Kiến trúc hệ thống (architecture.md)](./architecture.md)
> - [Đặc tả chức năng (functional-specification.md)](./functional-specification.md)
> - [Đặc tả kỹ thuật (technical-specification.md)](./technical-specification.md)
> - [Đối chiếu tính năng (feature-comparison.md)](./feature-comparison.md)
> - [Nhật ký thay đổi & Truy vết (architecture-change-log.md)](./architecture-change-log.md) *(Tài liệu hiện tại)*

---

## Mục Lục

1. [Tóm Tắt Thay Đổi So Với Phiên Bản Cơ Sở (Executive Change Summary)](#1-tóm-tắt-thay-đổi-so-với-phiên-bản-cơ-sở-executive-change-summary)
2. [Các Quyết Định & Yêu Cầu Được Giữ Nguyên (Preserved Baseline)](#2-các-quyết-định--yêu-cầu-được-giữ-nguyên-preserved-baseline)
3. [Các Thành Phần Được Điều Chỉnh & Tinh Chỉnh (Modified & Adapted)](#3-các-thành-phần-được-điều-chỉnh--tinh-chỉnh-modified--adapted)
4. [Các Cơ Chế Kỹ Thuật Được Bổ Sung Từ Ứng Dụng Tham Khảo (Added Features)](#4-các-cơ-chế-kỹ-thuật-được-bổ-sung-từ-ứng-dụng-tham-khảo-added-features)
5. [Các Tính Năng Tham Khảo Bị Loại Bỏ / Từ Chối (Rejected / Excluded)](#5-các-tính-năng-tham-khảo-bị-loại-bỏ--từ-chối-rejected--excluded)
6. [Đánh Giá Tác Động Đến Các Mô-đun & Tài Liệu Liên Quan (Impact Analysis)](#6-đánh-giá-tác-động-đến-các-mô-đun--tài-liệu-liên-quan-impact-analysis)
7. [Ma Trận Truy Vết Yêu Cầu (Requirements Traceability Matrix - RTM)](#7-ma-trận-truy-vết-yêu-cầu-requirements-traceability-matrix---rtm)
8. [Kiểm Toán Tính Nhất Quán (Consistency Audit)](#8-kiểm-toán-tính-nhất-quán-consistency-audit)
9. [Kiểm Soát Phạm Vi & Đánh Giá Khả Thi (Scope Control & Feasibility)](#9-kiểm-soát-phạm-vi--đánh-giá-khả-thi-scope-control--feasibility)

---

## 1. Tóm Tắt Thay Đổi So Với Phiên Bản Cơ Sở (Executive Change Summary)

Quá trình phân tích và tổng hợp kiến trúc đã đối chiếu **Đề bài của Giảng viên (`DoAn01.docx`)**, **Định hướng dự án hiện tại (`EC Agent` + `EC Server`)** và **Ứng dụng tham khảo (`Safe Kids v5.1.27` — Huy An Phát)**. Phiên bản kiến trúc mới bảo toàn **100% yêu cầu bắt buộc và ngăn xếp công nghệ Python/FastAPI**, đồng thời tích hợp có chọn lọc các cơ chế bảo vệ hệ thống và khôi phục an toàn từ ứng dụng tham khảo để lấp đầy các khoảng trống kỹ thuật khi triển khai thực tế trên Windows 10/11.

---

## 2. Các Quyết Định & Yêu Cầu Được Giữ Nguyên (Preserved Baseline)

| Hạng mục giữ nguyên | Nội dung chi tiết | Lý do bảo toàn |
|---|---|---|
| **1. Triết lý cốt lõi & Quyền riêng tư** | *"Công cụ đồng hành, không phải phần mềm theo dõi lén"*; không có chế độ ẩn; lược đồ sự kiện chỉ gồm đúng 7 trường (`ts, device_id, child_id, type, subject, duration_sec, policy_id`), trong đó `subject` không lưu URL đầy đủ. | Yêu cầu bắt buộc của giảng viên (Mục F3, F5). |
| **2. Ngăn xếp công nghệ (Technology Stack)** | Python 3.11+ (x64), FastAPI, Uvicorn, SQLite (WAL mode), SQLAlchemy, `pywin32`, `psutil`, giao diện Web Dashboard dùng được trên điện thoại. | Quyết định công nghệ đã được xác nhận trong `DoAn01.docx` (không chuyển sang C#/.NET của ứng dụng tham khảo). |
| **3. Mô hình kiến trúc Phân tán** | `EC Agent` (Service `LocalSystem` + `Tray UI` quyền User) giao tiếp với `EC Server` qua HTTPS (TLS 1.2+ kèm Certificate Pinning) và WebSocket (lệnh khẩn $< 5\text{s}$). | Yêu cầu bắt buộc tại Mục 4.1, 4.2, 4.3 (ứng dụng tham khảo chỉ chạy cục bộ, không có Server từ xa). |
| **4. Cơ chế lọc tên miền chính** | Sử dụng **DNS Proxy cục bộ tại `127.0.0.1:53`** hỗ trợ chặn tên miền gốc, tên miền con (`*.domain`), phân loại 6 nhóm ($\ge 200$ mục) và cưỡng chế SafeSearch. | Yêu cầu bắt buộc tại Mục 4.1, F2 và M1. |
| **5. Toàn bộ yêu cầu chức năng F1–F5 & báo cáo M1–M6** | Giữ nguyên mọi tiêu chí nghiệm thu của F1–F5, 6 chuyên đề mạng M1–M6 và danh mục sản phẩm phải nộp ở Mục 8. | Quy định chấm điểm bắt buộc của giảng viên. |

---

## 3. Các Thành Phần Được Điều Chỉnh & Tinh Chỉnh (Modified & Adapted)

| Thành phần điều chỉnh | Trạng thái ban đầu (`DoAn01.docx`) | Trạng thái sau khi điều chỉnh | Lý do & Giá trị mang lại |
|---|---|---|---|
| **1. Giao thức IPC giữa `Service` và `Tray UI`** | Chỉ nêu khái niệm *"giao tiếp với service qua named pipe hoặc HTTP 127.0.0.1 có token cục bộ"*. | Chuẩn hóa thành giao thức phong bì **`IpcEnvelope`** qua Named Pipe `\\.\pipe\OGKServicePipe`, xác thực `CallerSid` từ nhân Windows và đối chiếu token bằng `hmac.compare_digest` (`REF-02`). | Chống giả mạo lệnh từ tiến trình của trẻ và chống tấn công Timing Attack. |
| **2. Nhận diện ứng dụng bị đổi tên** | Nêu đối chiếu tên tiến trình kèm mã băm SHA-256. | Kết hợp **Tên tiến trình + SHA-256 (có LRU Cache) + PE Header `OriginalFileName`** (`REF-03`). | Vừa giảm tải CPU nhờ LRU Cache, vừa hiển thị được tên gốc của ứng dụng trên cửa sổ thông báo khi trẻ đổi tên tệp `.exe`. |
| **3. Luồng cảnh báo hết giờ & Xin phép phụ huynh** | Nêu cảnh báo 10, 5, 1 phút, ân hạn 60 giây và nút "Xin thêm giờ". | Thiết kế chi tiết máy trạng thái giao diện (kế thừa UX `ViolationCountdownWindow` `REF-04`) hỗ trợ **cả 2 kênh**: gửi yêu cầu từ xa lên Dashboard phụ huynh (duyệt qua WebSocket $< 5\text{s}$) VÀ nhập mã PIN phụ huynh tại chỗ khi mất mạng. | Đảm bảo tính khả dụng ngay cả khi máy tính của trẻ đang ngoại tuyến. |
| **4. Cơ chế chống chỉnh đồng hồ hệ thống** | Nêu sử dụng đồng hồ đơn điệu và đối chiếu thời gian máy chủ mỗi nhịp tim. | Kết hợp **3 lớp** (`REF-13`): (1) `time.monotonic()` khi máy đang chạy; (2) Lưu `last_wall_clock_utc` trong SQLite cục bộ để phát hiện lùi giờ khi reboot offline; (3) Đối chiếu `server_utc` mỗi nhịp tim 60 giây. | Chống gian lận thời gian triệt để trong cả trường hợp online lẫn offline. |
| **5. Quyết định hành vi khi chính sách hết hạn (Mục 4.3)** | Đề bài yêu cầu nhóm tự quyết định `fail-open` hay `fail-closed` sau $N$ ngày mất kết nối. | Chốt thiết kế **Graded Fail-Open sau $N = 7\text{ ngày}$** (`ADR-01` trong `architecture.md`): giữ nguyên lọc DNS độc hại/chặn game nhưng mở khóa thời gian cơ bản cho ứng dụng học tập. | Có lập luận vững chắc khi bảo vệ đồ án: không biến máy trẻ thành "cục gạch" khi lỗi máy chủ dài ngày nhưng vẫn giữ lớp lọc nội dung an toàn. |

---

## 4. Các Cơ Chế Kỹ Thuật Được Bổ Sung Từ Ứng Dụng Tham Khảo (Added Features)

| Cơ chế bổ sung | Nguồn tham khảo | Mô-đun tiếp nhận trong `EC - Echo Kiddo` | Lý do bổ sung |
|---|---|---|---|
| **1. Tự động khởi chạy & giám sát `Tray UI` qua WTS API (`WTSEnumerateSessions` + `CreateProcessAsUser`)** | `SafeKids.Service.Sessions.SessionAgentLauncher` (`REF-01`) | `/agent/service/session_launcher.py` | Giải quyết bài toán Session 0 Isolation của Windows Service, tự bật lại `Tray UI` trong $\le 3\text{s}$ nếu bị tắt, và dừng cưỡng chế nếu không thể hiển thị biểu tượng (tuân thủ F5). |
| **2. Snapshot & Khôi phục cấu hình DNS Card mạng + `DnsFlushResolverCache()`** | `SafeKids.Platform.Network.LegacyDnsRecoveryManager` & `WindowsDnsCache` (`REF-07`, `REF-10`) | `/agent/platform/network_guard.py` | Đảm bảo khi trỏ DNS về `127.0.0.1` có hiệu lực ngay lập tức, chống trẻ đổi DNS sang `8.8.8.8`, và khôi phục lại đúng DHCP/IP tĩnh ban đầu khi dừng dịch vụ. |
| **3. Snapshot & Áp chính sách Registry trình duyệt tắt DoH (`DnsOverHttpsMode = "off"`)** | `SafeKids.Platform.Browser.BrowserPolicyManager` (`REF-08`) | `/agent/platform/browser_policy.py` | Ngăn trình duyệt Chrome/Edge/Brave/Cốc Cốc tự động vượt qua DNS Proxy bằng DoH, đồng thời hoàn trả nguyên trạng Registry từ Snapshot khi gỡ. |
| **4. Cảm biến phát hiện VPN Adapter & System Proxy** | `NetworkAdapterDetector` & `ProxyDohDetector` (`REF-09`) | `/agent/platform/bypass_detector.py` | Phục vụ trực tiếp yêu cầu chống vượt rào (F2 NÊN CÓ) và cung cấp dữ liệu thực nghiệm cho báo cáo kỹ thuật mạng M3. |
| **5. Công cụ Khôi phục Sạch (`ogk_cleanup.py`)** | `SafeKidsCleanup.exe` (`REF-11`) | `/agent/cleanup/ogk_cleanup.py` | Đảm bảo quá trình gỡ cài đặt hoặc kiểm thử trên máy chấm bài của giảng viên luôn khôi phục sạch sẽ 100% cài đặt mạng và Registry. |

---

## 5. Các Tính Năng Tham Khảo Bị Loại Bỏ / Từ Chối (Rejected / Excluded)

| Tính năng bị từ chối | Nguồn trong `Safe Kids v5.1.27` | Lý do từ chối (Căn cứ theo Nguyên tắc ưu tiên) |
|---|---|---|
| **1. Chụp ảnh màn hình Desktop làm bằng chứng vi phạm** | `ScreenCaptureService`, `EvidenceCrypto`, `EvidenceRepository` (`REF-20`) | **Xung đột trực tiếp với Teacher Requirements (Triết lý đề bài & F3)**: Mang tính chất theo dõi lén (surveillance), vi phạm nguyên tắc chỉ lưu 7 trường sự kiện cơ bản. |
| **2. Tiện ích mở rộng trình duyệt (`SocialExtension`) thu thập URL đầy đủ, từ khóa tìm kiếm & tiêu đề video** | `SocialExtension/content.js`, `background.js` (`REF-19`) | **Xung đột trực tiếp với Teacher Requirements (Mục F3)**: Mục F3 quy định rõ `subject` chỉ là tên ứng dụng hoặc **tên miền cấp hai, không phải URL đầy đủ**. |
| **3. Bộ dữ liệu 83.776 tên miền người lớn/cờ bạc thực tế (`adult.txt`, `gambling.txt`)** | `Filters/Offline/adult.txt`, `gambling.txt` (`REF-21`) | **Xung đột trực tiếp với Quy định kiểm thử (Mục F2)**: Giảng viên nghiêm cấm sử dụng hay đính kèm tên miền người lớn thật trong đồ án (sẽ bị trừ điểm). |
| **4. Khóa/Ẩn phân vùng ổ đĩa, Két an toàn tệp tin, Quản lý bản quyền & Hỗ trợ Zalo** | `DriveProtectionManager`, `VaultManager`, `LicenseManager`, `ZaloPcLauncher` (`REF-22`) | Nằm ngoài phạm vi đồ án môn Mạng máy tính và gây rủi ro can thiệp ổ đĩa trên máy chấm bài. |

---

## 6. Đánh Giá Tác Động Đến Các Mô-đun & Tài Liệu Liên Quan (Impact Analysis)

| Mô-đun / Tài liệu | Mức độ tác động | Nội dung cập nhật tương ứng |
|---|---|---|
| **`docs/architecture.md`** | Tạo mới toàn diện | Hợp nhất sơ đồ tổng thể `EC Agent` + `EC Server` + `Dashboard` với kiến trúc 5 tầng, luồng dữ liệu, mô hình ER và 3 quyết định kiến trúc (ADR-01 $\rightarrow$ ADR-03). |
| **`docs/functional-specification.md`** | Tạo mới toàn diện | Đặc tả 39 yêu cầu chức năng có mã định danh (`FR-LC-01` $\rightarrow$ `FR-F5-09`), 6 Use Cases cốt lõi, 12 User Stories, quy tắc nghiệp vụ và tiêu chí nghiệm thu. |
| **`docs/technical-specification.md`** | Tạo mới toàn diện | Đặc tả chi tiết cấu trúc thư mục, giao thức `IpcEnvelope`, lược đồ SQLite (`server.db` & `agent.db`), REST API, WebSocket và giải pháp kỹ thuật cho M1–M6. |
| **`docs/feature-comparison.md`** | Tạo mới toàn diện | Phân tích 22 tính năng của `Safe Kids v5.1.27` theo 9 tiêu chí và phân loại `ADOPT` / `ADAPT` / `DEFER` / `REJECT`. |
| **Mô-đun `/agent` (Sắp triển khai)** | Định hình cấu trúc | Tách rõ `service/`, `core/`, `dns/`, `platform/`, `ipc/`, `sync/`, `ui/`, `cleanup/` giúp dễ dàng viết Unit Test và phân chia công việc cho nhóm 3 sinh viên. |

---

## 7. Ma Trận Truy Vết Yêu Cầu (Requirements Traceability Matrix - RTM)

Bảng dưới đây chứng minh **100% yêu cầu bắt buộc và mở rộng trong `DoAn01.docx`** đều đã được ánh xạ đầy đủ vào Đặc tả chức năng và Kiến trúc hệ thống mới:

| Requirement ID | Original Requirement (`DoAn01.docx`) | Updated Specification (`functional-specification.md` & `technical-specification.md`) | Architecture Component (`architecture.md`) | Status |
|---|---|---|---|---|
| **REQ-ARCH-01** | **4.1 & 4.2**: Kiến trúc `EC Agent` (Service `LocalSystem` + `Tray UI` quyền user), `EC Server` (FastAPI + SQLite WAL), `Dashboard` (Web di động), kho cục bộ `ProgramData` (ACL SYSTEM/Admins). | Mục 3, 4, 5 trong `architecture.md`; `FR-F5-07`, `FR-F5-09`; Mục 2 & 4.2 trong `technical-specification.md`. | `OGKWindowsService`, `SessionAgentLauncher`, `TrayUI`, `FastAPIServer`, `LocalSQLiteStore`, `WebDashboard` | **Preserved & Enhanced** |
| **REQ-LC-01** | **4.3**: Ghép đôi (enrollment) bằng mã 8 ký tự có hạn 10 phút; gửi kèm device fingerprint; trả `device_id` và cặp token; ghi nhận đồng ý theo NĐ 13/2023. | `FR-LC-01`, `UC-01`, `POST /api/v1/enroll/code` & `POST /api/v1/enroll`. | `EnrollmentMod` (`Server`), `SyncClient` (`Agent`), Bảng `pairing_codes` & `devices` | **Preserved** |
| **REQ-LC-02** | **4.3**: Nhịp tim (heartbeat) 60 giây: gửi trạng thái, quota đã dùng, `policy_version`; lệch phiên bản thì gọi `GET /policy`. | `FR-LC-02`, `POST /api/v1/heartbeat`, `GET /api/v1/policy`. | `SyncClient` (`Agent`), `CommandMod` & `PolicyMod` (`Server`) | **Preserved** |
| **REQ-LC-03** | **4.3**: Lệnh khẩn qua WebSocket: khóa ngay, mở khóa, cộng thêm 15 phút — độ trễ $< 5\text{ giây}$. | `FR-LC-03`, `FR-F4-02`, `UC-02`, `WS /ws/agent/{device_id}`. | `CommandMod` (`Server`), `SyncClient` & `ScreenTimer` (`Agent`) | **Preserved** |
| **REQ-LC-04** | **4.3**: Chế độ ngoại tuyến: áp chính sách trong bộ nhớ đệm, đếm giờ, đệm sự kiện; đồng bộ theo lô có `idempotency_key`. | `FR-LC-04`, `POST /api/v1/events/batch`, Bảng `event_queue` & `events`. | `EventBuffer` (`Agent`), `EventMod` (`Server`) | **Preserved** |
| **REQ-LC-05** | **4.3**: Chính sách hết hạn: quyết định `fail-open` hay `fail-closed` sau $N$ ngày mất kết nối và bảo vệ lựa chọn. | `FR-LC-05`, `ADR-01` (Chế độ **Graded Fail-Open** sau $N = 7\text{ ngày}$ mất kết nối). | `PolicyEnforcer` & `ScreenTimer` (`Agent`) | **Preserved & Defined** |
| **REQ-F1-01** | **F1 (BẮT BUỘC)**: Hạn mức theo ngày, cấu hình riêng cho ngày thường và cuối tuần (đặt 3 phút khóa đúng hạn). | `FR-F1-01`, `BR-02`, Bảng `policies` (`daily_limit_weekday_min`, `daily_limit_weekend_min`). | `ScreenTimer` (`Agent`), `PolicyMod` (`Server`) | **Preserved** |
| **REQ-F1-02** | **F1 (BẮT BUỘC)**: Lịch tuần cho phép/khóa với độ phân giải 30 phút (ma trận $7 \times 48$), ngoài khung giờ khóa trong 5 giây. | `FR-F1-02`, `BR-02`, Bảng `policies` (`schedule_matrix_7x48`). | `ScreenTimer` (`Agent`), `WebDashboard` (`Server`) | **Preserved** |
| **REQ-F1-03** | **F1 (BẮT BUỘC)**: Đếm thời gian sử dụng thực: không tính khi máy khóa hoặc không thao tác quá 5 phút (sai số $\le \pm 30\text{s/giờ}$). | `FR-F1-03`, `BR-01`, `GetLastInputInfo` + `WTS_SESSION_LOCK`. | `ScreenTimer` (`Agent`) | **Preserved** |
| **REQ-F1-04** | **F1 (BẮT BUỘC)**: Cảnh báo trước 10, 5 và 1 phút; có khoảng ân hạn 60 giây để trẻ lưu bài. | `FR-F1-04`, `UC-02`, `BR-03` (Tích hợp UX đếm ngược từ `REF-04`). | `ScreenTimer` & `TrayUI` (`Agent`) | **Preserved & Enhanced** |
| **REQ-F1-05** | **F1 (BẮT BUỘC)**: Chống chỉnh đồng hồ hệ thống để kéo dài thời gian (lùi 3 giờ quota không tăng, ghi nhận sự kiện). | `FR-F1-05`, `BR-04`, Mục 6.4 (`time.monotonic()` + `last_wall_clock_utc` + `server_utc`). | `ScreenTimer` & `BypassGuard` (`Agent`), `CommandMod` (`Server`) | **Preserved & Enhanced** |
| **REQ-F1-06** | **F1 (NÊN CÓ & CÓ THÌ TỐT)**: Ngân sách theo nhóm ứng dụng (`FR-F1-06`) & Cơ chế thưởng giờ khi hoàn thành nhiệm vụ (`FR-F1-07`). | `FR-F1-06`, `FR-F1-07`, `category_budgets_json`. | `ScreenTimer`, `AppCtrl`, `PolicyMod` | **Preserved** |
| **REQ-F2-01** | **F2 (BẮT BUỘC)**: Kiểm soát ứng dụng theo danh sách cho phép/chặn, đối chiếu tên tiến trình kèm mã băm SHA-256 (đổi tên `notepad.exe` thành `game.exe` vẫn nhận diện đúng). | `FR-F2-01`, `UC-03`, `BR-05` (Bổ sung SHA-256 LRU Cache + PE `OriginalFileName` từ `REF-03`). | `AppCtrl` (`Agent`) | **Preserved & Enhanced** |
| **REQ-F2-02** | **F2 (BẮT BUỘC)**: Khi chặn: kết thúc tiến trình và hiển thị cửa sổ giải thích lý do, không im lặng. | `FR-F2-02`, `UC-03`. | `AppCtrl` & `TrayUI` (`Agent`) | **Preserved** |
| **REQ-F2-03** | **F2 (BẮT BUỘC)**: Lọc website bằng DNS proxy cục bộ tại `127.0.0.1:53`, hỗ trợ chặn theo tên miền và toàn bộ tên miền con ($\ge 95\%$ trên 50 miền kiểm thử, 0 dương tính giả trên 20 miền giáo dục). | `FR-F2-03`, `UC-04`, `BR-06`, Mục 6.1 (Kết hợp `DnsFlushResolverCache` từ `REF-07`). | `DnsProxy` & `DomainPolicyEngine` (`Agent`) | **Preserved & Enhanced** |
| **REQ-F2-04** | **F2 (BẮT BUỘC)**: Hạ tầng phân loại 6 nhóm (`education`, `entertainment`, `social`, `gaming`, `inappropriate`, `unclassified`) — chính sách mặc định 6–11 tuổi, tối thiểu 200 mục an toàn. | `FR-F2-04`, `/server/seeds/domain_catalog.json` (Tuân thủ nghiêm quy định không dùng tên miền người lớn thật). | `PolicyMod` (`Server`), `DomainPolicyEngine` (`Agent`) | **Preserved** |
| **REQ-F2-05** | **F2 (BẮT BUỘC)**: Cưỡng chế SafeSearch của công cụ tìm kiếm bằng bản ghi DNS (`forcesafesearch`, `strict.bing`, v.v.). | `FR-F2-05`, `UC-04`, Mục 6.1 trong `technical-specification.md`. | `DnsProxy` (`Agent`) | **Preserved** |
| **REQ-F2-06** | **F2 (NÊN CÓ)**: Đối phó DoH (chặn điểm cuối DoH, trả `NXDOMAIN` cho canary, chính sách trình duyệt) & Chặn cấu hình lại DNS thủ công. | `FR-F2-06`, `FR-F2-07`, `FR-F2-08` (Bổ sung `BrowserPolicySnapshot` `REF-08` và `NetworkDnsGuard` `REF-10`). | `DnsProxy`, `BypassGuard` (`Agent`) | **Preserved & Enhanced** |
| **REQ-F3-01** | **F3 (BẮT BUỘC)**: Lược đồ sự kiện chỉ gồm: `ts, device_id, child_id, type, subject, duration_sec, policy_id` (9 loại `type`, `subject` không phải URL đầy đủ). | `FR-F3-01`, `BR-07`, Bảng `events` trong `technical-specification.md`. | `EventBuffer` (`Agent`), `EventMod` (`Server`) | **Preserved (100% Strict)** |
| **REQ-F3-02** | **F3 (BẮT BUỘC)**: Dashboard phụ huynh (biểu đồ ngày/tuần, top 10 ứng dụng, top 10 tên miền, số lần chặn, danh sách yêu cầu) & Màn hình *"Hôm nay em đã dùng gì"* cho trẻ. | `FR-F3-02`, `FR-F3-03`, `UC-05`, `GET /api/v1/reports/{child_id}`. | `ReportAuditMod` (`Server`), `WebDashboard`, `TrayUI` | **Preserved** |
| **REQ-F3-03** | **F3 (BẮT BUỘC)**: Lưu trữ 90 ngày có tác vụ tự động xóa; nút *"Xóa toàn bộ dữ liệu của con tôi"* xóa đồng thời trên server và agent; tệp `PRIVACY.md`. | `FR-F3-04`, `FR-F3-05`, `UC-05`, `DELETE /api/v1/privacy/children/{child_id}/events`. | `EventMod` (`Server`), `SyncClient` (`Agent`), `docs/PRIVACY.md` | **Preserved** |
| **REQ-F3-04** | **F3 (NÊN CÓ & CÓ THÌ TỐT)**: Xuất báo cáo tuần ra PDF/CSV (`FR-F3-06`) & Gợi ý nghỉ mắt 20-20-20 (`FR-F3-07`). | `FR-F3-06`, `FR-F3-07`. | `ReportAuditMod` (`Server`), `TrayUI` (`Agent`) | **Preserved** |
| **REQ-F4-01** | **F4 (BẮT BUỘC)**: Mô hình `1 phụ huynh : n trẻ : m thiết bị`; thay đổi chính sách hiệu lực $\le 60\text{s}$, lệnh khẩn $< 5\text{s}$; chính sách có đánh số phiên bản và ký toàn vẹn (HMAC/chữ ký); Nhật ký kiểm toán (Audit Log) trẻ xem được (NT5). | `FR-F4-01`, `FR-F4-02`, `FR-F4-03`, `FR-F4-04`, Bảng `policies` & `audit_logs`. | `PolicyMod`, `ReportAuditMod` (`Server`), `PolicyEnforcer` (`Agent`) | **Preserved & Enhanced** |
| **REQ-F4-02** | **F4 (NÊN CÓ & CÓ THÌ TỐT)**: Quy trình gỡ cài đặt hợp pháp bằng mật khẩu phụ huynh (`FR-F4-05`) & Chế độ tạm nghỉ 2 giờ (`FR-F4-06`). | `FR-F4-05`, `FR-F4-06`, `UC-06` (Tích hợp `ogk_cleanup.py` từ `REF-11` và `REF-12`). | `CleanupCLI`, `OGKService` (`Agent`), `CommandMod` (`Server`) | **Preserved & Enhanced** |
| **REQ-F5-01** | **F5 (BẮT BUỘC)**: Bảo mật xác thực Argon2id ($\ge 10$ ký tự, khóa 15p sau 5 lần sai, rate limit IP), Cookie an toàn + CSRF, TLS 1.2+ & Certificate Pinning, Token thiết bị 15p + Refresh + Thu hồi, AES-GCM (env/DPAPI), RBAC 3 vai trò chống IDOR, ACL `ProgramData`, STRIDE $\ge 8$ mối đe dọa, Cấm chế độ ẩn. | `FR-F5-01` $\rightarrow$ `FR-F5-09`, Mục 11 trong `architecture.md`, Mục 3 & 4 trong `technical-specification.md`. | `AuthMod` (`Server`), `SyncClient`, `SessionAgentLauncher`, `PipeProtocol` (`Agent`) | **Preserved & Enhanced** |
| **REQ-NET-M1_M6** | **Mục 6 (M1–M6)**: Sơ đồ luồng gói tin + Wireshark (M1), So sánh 4 phương án chặn (M2), Phân tích $\ge 7$ đường vòng (M3), Đo hiệu năng $\ge 30$ mẫu (M4), Chịu lỗi 3 kịch bản (M5), Đồng bộ thời gian monotonic (M6). | Mục 6.1 $\rightarrow$ 6.4 trong `technical-specification.md`. | `DnsProxy`, `BypassGuard`, `ScreenTimer`, `tests/benchmark_m4.py`, `docs/BaoCaoKyThuatMang.pdf` | **Preserved** |

---

## 8. Kiểm Toán Tính Nhất Quán (Consistency Audit)

| # | Câu hỏi kiểm toán (Audit Question) | Kết quả kiểm tra | Bằng chứng & Đối chiếu giữa các tài liệu |
|---|---|---|---|
| **1** | **Có yêu cầu chức năng nào của giảng viên bị bỏ sót không?** | **KHÔNG (Đạt 100%)** | Toàn bộ các mục 4.1, 4.2, 4.3, F1, F2, F3, F4, F5 (cả mức BẮT BUỘC, NÊN CÓ, CÓ THÌ TỐT) và M1–M6 trong `DoAn01.docx` đều có mặt trong `functional-specification.md` và bảng RTM ở Mục 7. |
| **2** | **Có tính năng nào được thêm nhưng không có lý do không?** | **KHÔNG** | Mọi tính năng `ADOPT` (7 mục) và `ADAPT` (8 mục) từ `Safe Kids v5.1.27` đều được giải trình rõ theo 9 tiêu chí trong `feature-comparison.md` và gắn trực tiếp với một yêu cầu trong `DoAn01.docx`. Các tính năng không phù hợp (`REF-19` $\rightarrow$ `REF-22`) đã bị `REJECT` dứt khoát. |
| **3** | **Có mô-đun nào không có trách nhiệm rõ ràng không?** | **KHÔNG** | Mục 5 của `architecture.md` và Mục 2 của `technical-specification.md` định nghĩa rõ trách nhiệm, đường dẫn tệp và giao diện đầu vào/đầu ra cho từng mô-đun trong `/agent`, `/server` và `/dashboard`. |
| **4** | **Có thành phần nào được mô tả khác nhau giữa các tài liệu không?** | **KHÔNG (Nhất quán 100%)** | Tên gọi thành phần (`EC Agent`, `EC Service`, `EC Tray`, `EC Server`, `Web Dashboard`, `IpcEnvelope`, `system_snapshots`), các thông số thời gian (Heartbeat `60s`, WebSocket `< 5s`, Idle `> 5p`, Cảnh báo `10/5/1p`, Ân hạn `60s`, Chính sách hết hạn `N = 7 ngày`, Lưu trữ `90 ngày`, Khóa đăng nhập `15p sau 5 lần sai`) và lược đồ 7 trường sự kiện hoàn toàn khớp nhau trên cả 5 tệp tài liệu. |
| **5** | **Có xung đột giữa kiến trúc và ngăn xếp công nghệ (Technology Stack) không?** | **KHÔNG** | Dù ứng dụng tham khảo viết bằng C#/.NET (WPF), kiến trúc tổng hợp đã ánh xạ toàn bộ các cơ chế hệ thống sang các thư viện chuẩn của **Python 3.11+** (`pywin32`, `psutil`, `winreg`, `ctypes.windll.dnsapi`, `dnslib`, `asyncio`, `FastAPI`, `SQLite WAL`, `SQLAlchemy`). |
| **6** | **Có chức năng nào vượt quá phạm vi đồ án không?** | **KHÔNG** | Các tính năng ngoài phạm vi hoặc vi phạm quyền riêng tư của ứng dụng tham khảo (chụp màn hình, tiện ích mở rộng trình duyệt đọc DOM, khóa ổ đĩa, két dữ liệu, bản quyền thương mại) đã bị loại bỏ hoàn toàn. |
| **7** | **Có yêu cầu nào không khả thi với nguồn lực hiện tại (03 sinh viên / 06 tuần) không?** | **KHÔNG (Hoàn toàn khả thi)** | Các thành phần phức tạp ở mức Kernel (như WFP Driver C/C++) không bắt buộc; phương án chính là User-mode DNS Proxy (`127.0.0.1:53`) bằng `dnslib` + `asyncio` kết hợp Registry Policy và `psutil`/`pywin32`, hoàn toàn nằm trong tầm tay của 3 sinh viên đại học trong 6 tuần. |
| **8** | **Có giả định nào chưa được xác minh không?** | **Đã phân biệt rõ ràng** | Tất cả thông tin về `DoAn01.docx` và `Safe Kids v5.1.27` đều được xác minh trực tiếp từ tệp gốc và nhị phân trong workspace. Các quyết định thiết kế của nhóm (như ngưỡng hết hạn chính sách $N=7\text{ ngày}$ theo yêu cầu mở của mục 4.3) được ghi chú rõ tại `ADR-01`. |

---

## 9. Kiểm Soát Phạm Vi & Đánh Giá Khả Thi (Scope Control & Feasibility)

### 9.1. Kế Hoạch Phân Bổ Lộ Trình 6 Tuần Cho Nhóm 03 Sinh Viên

| Tuần | Mục tiêu trọng tâm (Ưu tiên tuyệt đối `MUST HAVE` trước) | Phân công (3 Thành viên: SV1 - Server/Web, SV2 - Agent Core/UI, SV3 - DNS/Network/Test) |
|---|---|---|
| **Tuần 1** | Khởi tạo dự án, CSDL SQLite WAL, Xác thực Argon2id, Ghép đôi 8 ký tự, Khung Windows Service + Named Pipe `IpcEnvelope`. | - **SV1**: Khung FastAPI, Auth Argon2id, Enrollment API.<br>- **SV2**: `OGKWindowsService`, `SessionAgentLauncher`, `PipeProtocol`.<br>- **SV3**: Thiết kế bộ 200+ tên miền phân loại an toàn & 50 tên miền kiểm thử. |
| **Tuần 2** | Đếm thời gian thực (`time.monotonic()` + Idle $>5\text{p}$), Ma trận lịch tuần $7 \times 48$, DNS Proxy `127.0.0.1:53` + SafeSearch. | - **SV1**: API `/policy` (kèm chữ ký HMAC) & `/heartbeat`.<br>- **SV2**: `ScreenTimeEngine`, `AppController` (SHA-256 + `OriginalFileName`).<br>- **SV3**: `DnsProxyServer` (`127.0.0.1:53`), `DomainPolicyEngine`, SafeSearch. |
| **Tuần 3** | Lệnh khẩn WebSocket ($< 5\text{s}$), Hàng đợi sự kiện Offline + Idempotent Batch Sync, Giao diện `EC Tray` (cảnh báo 10/5/1p + ân hạn 60s). | - **SV1**: WebSocket Hub, API `/events/batch`, `/commands`, Audit Log.<br>- **SV2**: `TrayUI` (đồng hồ, cảnh báo, xin thêm giờ, màn hình minh bạch).<br>- **SV3**: Tích hợp `SyncClient` (HTTPS Cert Pinning + WSS). |
| **Tuần 4** | Hoàn thiện 100% `MUST HAVE`: Dashboard Phụ huynh & Màn hình minh bạch cho trẻ, Lưu trữ 90 ngày, Nút xóa toàn bộ dữ liệu. | - **SV1**: Giao diện Dashboard (Jinja2 + HTMX + Chart.js), Nút xóa dữ liệu.<br>- **SV2**: Hoàn thiện luồng khóa máy & mở khóa từ xa / PIN cục bộ.<br>- **SV3**: Viết $\ge 15$ Unit Tests & $\ge 5$ kịch bản tích hợp. |
| **Tuần 5** | Triển khai nhóm `SHOULD HAVE`: Chống DoH (`BrowserPolicySnapshot`), Khóa DNS Card mạng (`NetworkDnsGuard`), Công cụ `ogk_cleanup.py`, Ngân sách nhóm ứng dụng, Xuất CSV/PDF. | - **SV1**: Xuất báo cáo CSV/PDF, Ngân sách theo nhóm ứng dụng.<br>- **SV2**: Quy trình gỡ cài đặt hợp pháp + `ogk_cleanup.py`.<br>- **SV3**: `NetworkDnsGuard`, `BrowserPolicyGuard`, `BypassDetector` & Đo đạc thực nghiệm M1–M6 (Wireshark, 30 mẫu hiệu năng). |
| **Tuần 6** | Triển khai `COULD HAVE` (Tạm nghỉ 2h, Nhắc nghỉ mắt 20-20-20), Kiểm thử cài đặt sạch 15 phút theo `README.md`, Hoàn thiện báo cáo & Video demo. | - **Cả nhóm**: Hoàn thiện `BaoCao.docx`, `BaoCaoKyThuatMang.pdf`, `PRIVACY.md`, `THREATMODEL.md`, `AI_USAGE.md`, `README.md` và quay `demo/video.mp4`. |
