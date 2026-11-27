# Báo Cáo Phân Tích Ứng Dụng Tham Khảo & Đối Chiếu Tính Năng (Feature Comparison)

> **Tài liệu thuộc bộ đặc tả kiến trúc dự án OGK (Open Guardian for Kids)**
> - [Kiến trúc hệ thống (architecture.md)](./architecture.md)
> - [Đặc tả chức năng (functional-specification.md)](./functional-specification.md)
> - [Đặc tả kỹ thuật (technical-specification.md)](./technical-specification.md)
> - [Đối chiếu tính năng (feature-comparison.md)](./feature-comparison.md) *(Tài liệu hiện tại)*
> - [Nhật ký thay đổi & Truy vết (architecture-change-log.md)](./architecture-change-log.md)

---

## Mục Lục

1. [Tổng Quan Khảo Sát (Discovery & Inventory Summary)](#1-tổng-quan-khảo-sát-discovery--inventory-summary)
2. [Bảng Đối Chiếu Tổng Thể (Comparative Matrix)](#2-bảng-đối-chiếu-tổng-thể-comparative-matrix)
3. [Phân Tích Chi Tiết Từng Tính Năng Tham Khảo (9 Tiêu Chí)](#3-phân-tích-chi-tiết-từng-tính-năng-tham-khảo-9-tiêu-chí)
4. [Tổng Hợp Quyết Định Phân Loại & Kiểm Soát Phạm Vi (Scope Control)](#4-tổng-hợp-quyết-định-phân-loại--kiểm-soát-phạm-vi-scope-control)

---

## 1. Tổng Quan Khảo Sát (Discovery & Inventory Summary)

### 1.1. Ba Nguồn Thông Tin Đầu Vào

| Nguồn | Tài liệu / Hiện vật trong Workspace | Trạng thái xác minh |
|---|---|---|
| **1. Teacher Requirements** | `DoAn01.docx` — Đề tài: *"Xây dựng ứng dụng hỗ trợ quản lý việc sử dụng máy tính của trẻ em ('Công cụ đồng hành, không phải phần mềm theo dõi lén')"* | **Đã xác minh 100%** (Đọc toàn văn yêu cầu kiến trúc mục 4, chức năng F1–F5 mục 5, kỹ thuật mạng M1–M6 mục 6, sản phẩm nộp mục 8 và phụ lục kiểm thử). |
| **2. Current Project** | Định hướng kiến trúc cơ sở trong `DoAn01.docx` (`OGK-Agent` + `OGK-Server` + `Dashboard`), thư mục `docs/` (chưa có mã nguồn `/agent`, `/server`, `/dashboard`). | **Đã xác minh 100%** (Dự án đang ở giai đoạn thiết kế kiến trúc & đặc tả kỹ thuật trước khi lập trình; công nghệ đã chốt: Python 3.11+, FastAPI, SQLite, SQLAlchemy, Uvicorn, `pywin32`, `psutil`). |
| **3. Reference Application** | Thư mục `Safe-Kids-Quan-Ly-Tre-Em.h - a/` gồm bộ nhị phân **Safe Kids v5.1.27** (Huy An Phát), tiện ích mở rộng `SocialExtension/`, gói lọc `Filters/Offline/`, và báo cáo dịch ngược `Bao-Cao-Phan-Tich-Du-An-Safe-Kids.docx`. | **Đã xác minh 100%** qua kiểm tra mã nguồn JS/HTML/JSON, gói chữ ký RSA và phản chiếu metadata CLR (.NET Reflection) trực tiếp trên 6 tệp thực thi/thư viện (`SafeKids.Core.dll`, `SafeKids.Platform.dll`, `SafeKidsProtectionService.exe`, `SafeKidsSessionAgent.exe`, `SafeKids.Admin.exe`, `SafeKidsCleanup.exe`). |

### 1.2. Kiến Trúc & Hiện Vật Của Ứng Dụng Tham Khảo (`Safe Kids v5.1.27`)

Qua khảo sát thực tế mã nhị phân và tài liệu phân tích, ứng dụng tham khảo **Safe Kids v5.1.27** là một phần mềm thương mại dạng **Standalone Local Endpoint** viết bằng C# / .NET (WPF + Windows Service), hoạt động cục bộ trên một máy Windows (không có máy chủ quản trị từ xa qua mạng). Hệ thống gồm 4 tầng:

1. **Tầng Dịch vụ Hệ thống (`SafeKidsProtectionService.exe` — Session 0, `NT AUTHORITY\SYSTEM`)**: Quản lý vòng đời bảo vệ (`ProtectionLifecycleCoordinator`), giám sát ứng dụng (`ApplicationRuleMonitor`), phát hiện vượt rào (`NetworkAdapterDetector`, `ProxyDohDetector`, `ProcessServiceDetector`, `EmbeddedVpnBrowserGuard`), bảo vệ tài khoản Windows (`WindowsAccountCreationGuard`), và lưu trữ bằng chứng (`EvidenceRepository`).
2. **Tầng Phiên Người dùng (`SafeKidsSessionAgent.exe` — User Session)**: Được khởi chạy tự động vào phiên của trẻ thông qua Win32 API `WTSEnumerateSessions` + `WTSQueryUserToken` + `CreateProcessAsUser` (`SessionAgentLauncher`); hiển thị cảnh báo đếm ngược (`ViolationCountdownWindow`), hộp thoại xin phép phụ huynh (`ParentPermissionWindow`), làm cầu nối Native Messaging (`NativeMessagingBridge`) và chụp màn hình (`ScreenCaptureService`).
3. **Tầng Quản trị Cục bộ (`SafeKids.Admin.exe` — WPF Admin Console)** & **Tiện ích Dọn dẹp (`SafeKidsCleanup.exe`)**: Giao diện cấu hình cục bộ cho phụ huynh, quản lý trạng thái trong tệp JSON (`JsonStateStore`) và khôi phục sạch cấu hình hệ thống khi gỡ cài đặt (`ProtectionMaintenance.CleanupProtection`).
4. **Tầng Trình duyệt (`SocialExtension/` — Manifest V3)**: Tiện ích mở rộng trên Chrome/Edge/Cốc Cốc/Brave kết nối với `SafeKidsSessionAgent.exe` qua `com.huyanphat.safekids.social` (stdio).

---

## 2. Bảng Đối Chiếu Tổng Thể (Comparative Matrix)

Bảng dưới đây đối chiếu **22 tính năng và cơ chế kỹ thuật** phát hiện từ ứng dụng tham khảo (`REF-01` đến `REF-22`) với Dự án hiện tại (`OGK`) và Yêu cầu giảng viên (`DoAn01.docx`):

| Mã | Reference Feature (Safe Kids v5.1.27) | Current Project (Baseline OGK) | Teacher Requirement (`DoAn01.docx`) | Value (Giá trị mang lại) | Compatibility (Tương thích) | Recommendation |
|---|---|---|---|---|---|---|
| **REF-01** | **Kiến trúc tách biệt Service (SYSTEM) & Session Agent (User) kèm tự động khởi chạy qua WTS API (`SessionAgentLauncher`)** | Đã định nghĩa `OGK-Agent — Service` (SYSTEM) và `Tray UI` (User) nhưng chưa đặc tả cơ chế tự khởi chạy lại Tray UI khi bị tắt. | **BẮT BUỘC (4.1, 4.2, F5, M5)**: Service chạy `LocalSystem`; chịu lỗi khi agent bị kết thúc; nếu không hiện được icon phải xử lý an toàn. | **Rất cao**: Giải quyết bài toán Session 0 Isolation trên Windows và tự phục hồi giao diện Tray UI khi trẻ kill tiến trình. | Tương thích 100% với `pywin32` (`win32ts`, `win32security`, `win32process`). | **ADOPT** |
| **REF-02** | **Giao thức IPC qua Named Pipe có Phong bì (`IpcEnvelope`), kiểm tra `CallerSid`, Challenge-Response & `FixedTimeEquals`** | Chỉ nêu khái niệm dùng Named Pipe hoặc HTTP `127.0.0.1` có token cục bộ. | **BẮT BUỘC (4.2, F5, M3)**: Giao tiếp cục bộ an toàn giữa Tray UI và Service; chống giả mạo từ tiến trình của trẻ. | **Rất cao**: Ngăn chặn trẻ viết script gửi lệnh giả mạo qua Named Pipe hoặc tấn công đo thời gian (Timing Attack). | Tương thích 100% với Python (`win32pipe`, `win32security`, `hmac.compare_digest`). | **ADOPT** |
| **REF-03** | **Nhận diện sâu ứng dụng qua SHA-256 + PE VersionInfo (`OriginalFileName`, `ProductName`, `Publisher`) + Authenticode** | Chỉ mới nêu đối chiếu tên tiến trình + mã băm SHA-256. | **BẮT BUỘC (F2)**: Kiểm soát ứng dụng theo tên tiến trình kèm SHA-256; đổi tên `notepad.exe` thành `game.exe` vẫn nhận diện đúng. | **Cao**: Bổ sung `OriginalFileName` làm lớp nhận diện phụ trợ và hiển thị tên gốc rõ ràng trên nhật ký/cảnh báo khi tệp bị đổi tên. | Tương thích cao (Python `hashlib.sha256` + `win32api.GetFileVersionInfo`). | **ADOPT** |
| **REF-04** | **Cửa sổ đếm ngược 60 giây (`ViolationCountdownWindow`) và hộp thoại xin phép (`ParentPermissionWindow`)** | Đã có yêu cầu cảnh báo 10, 5, 1 phút, ân hạn 60 giây và nút "Xin thêm giờ". | **BẮT BUỘC (F1, F2, F3)**: Cảnh báo 10/5/1 phút, ân hạn 60s lưu bài; chặn ứng dụng có cửa sổ giải thích; gửi yêu cầu `unlock_request` / `override_granted`. | **Rất cao**: Cung cấp mẫu UX nhân văn, minh bạch; cần điều chỉnh để hỗ trợ cả gửi yêu cầu từ xa qua Server lẫn nhập mã PIN/mật khẩu phụ huynh tại chỗ. | Tương thích cao với Tray UI (Python `tkinter`/`PySide6`) + WebSocket Server. | **ADAPT** |
| **REF-05** | **Hạn mức thời gian theo ngày, khung giờ, danh mục ứng dụng & Lịch đặc biệt ôn thi (`CustomLimitPeriod`)** | Có hạn mức ngày thường/cuối tuần, ma trận lịch tuần $7 \times 48$, và ngân sách theo nhóm ứng dụng. | **BẮT BUỘC & NÊN CÓ (F1)**: Quota ngày thường/cuối tuần, ma trận $7 \times 48$ (30 phút), ngân sách theo nhóm ứng dụng (NÊN CÓ). | **Cao**: Cách tổ chức `EffectiveLimit` của Reference App rất rõ ràng; ưu tiên chuẩn hóa theo đúng ma trận $7 \times 48$ và quota nhóm của giảng viên. | Tương thích 100% với mô hình chính sách JSON của `OGK-Server`. | **ADAPT** |
| **REF-06** | **Gói danh sách tên miền Offline có Manifest SHA-256 và Chữ ký số (`FilterPackageVerifier` / `manifest.sig`)** | Đã có yêu cầu chính sách có `policy_version` và chữ ký/HMAC, kèm bộ phân loại $\ge 200$ mục. | **BẮT BUỘC (F2, F4)**: Hạ tầng phân loại 6 nhóm ($\ge 200$ mục); chính sách có đánh số phiên bản và ký hiệu toàn vẹn (HMAC/chữ ký). | **Rất cao**: Đảm bảo gói phân loại tên miền/chính sách lưu trong `ProgramData` không bị trẻ chỉnh sửa trái phép khi ngoại tuyến. | Tương thích 100% với Python `hmac` / `cryptography` (RSA/Ed25519). | **ADOPT** |
| **REF-07** | **Lọc web bằng ghi tệp `hosts` nguyên tử (`AtomicHostsFileStore`) + xóa cache DNS (`DnsFlushResolverCache`)** | Dự án OGK sử dụng **DNS Proxy cục bộ tại `127.0.0.1:53`** làm phương án chính. | **BẮT BUỘC (4.1, F2, M1, M2)**: Bắt buộc lọc bằng DNS Proxy `127.0.0.1:53` và so sánh với tệp `hosts` trong mục M2. | **Trung bình**: Không dùng `hosts` làm bộ lọc chính (vì giảng viên bắt buộc DNS Proxy), nhưng **ADOPT** kỹ thuật gọi `DnsFlushResolverCache` (`dnsapi.dll`) khi cập nhật chính sách DNS! | `DnsFlushResolverCache` gọi dễ dàng qua `ctypes.windll.dnsapi` trong Python. | **ADAPT** |
| **REF-08** | **Quản lý Chính sách Trình duyệt qua Registry kèm Snapshot khôi phục (`BrowserPolicyManager` & `BrowserPolicySnapshot`)** | Đề bài nêu khuyến nghị thiết lập chính sách trình duyệt để đối phó DoH (F2 NÊN CÓ). | **NÊN CÓ (F2, M3)**: Đối phó DoH, cấu hình chính sách trình duyệt (Chrome/Edge/Cốc Cốc/Brave) tắt DoH (`DnsOverHttpsMode`) và cưỡng chế SafeSearch. | **Rất cao**: Cơ chế lưu `BrowserPolicySnapshot` trước khi sửa Registry giúp khôi phục nguyên trạng 100% khi gỡ cài đặt hoặc tắt chế độ bảo vệ. | Tương thích 100% với `winreg` trong Python. | **ADOPT** |
| **REF-09** | **Cảm biến phát hiện vượt rào: VPN Adapter, System Proxy & DoH (`NetworkAdapterDetector`, `ProxyDohDetector`)** | Đề bài yêu cầu phân tích $\ge 7$ kỹ thuật vượt rào (M3) và đối phó DoH / đổi DNS (F2). | **NÊN CÓ (F2) & BẮT BUỘC (M3)**: Phát hiện và xử lý DoH, VPN/proxy, đổi DNS thủ công; ghi nhận sự kiện và thực nghiệm trong báo cáo M3. | **Rất cao**: Giúp đồ án đạt điểm tối đa ở hạng mục trọng tâm **Kỹ thuật hệ thống và mạng (F2 NÊN CÓ & M3)**. | Tương thích 100% với `psutil.net_if_addrs()`, WMI và `winreg` trong Python. | **ADOPT** |
| **REF-10** | **Quản lý DNS Card mạng kèm Snapshot khôi phục (`WmiNetworkConfigurationAdapter` & `LegacyDnsRecoveryManager`)** | Cần trỏ DNS hệ thống về `127.0.0.1` để DNS Proxy hoạt động và chống trẻ đổi DNS sang `8.8.8.8`. | **BẮT BUỘC (M1) & NÊN CÓ (F2)**: Trình duyệt $\rightarrow$ stub resolver $\rightarrow$ DNS proxy `127.0.0.1:53`; chặn cấu hình lại DNS thủ công. | **Rất cao**: Chụp snapshot cấu hình DNS gốc (DHCP hoặc IP tĩnh) trước khi trỏ về `127.0.0.1`, tự động phát hiện nếu trẻ đổi sang `8.8.8.8` để ép lại, và hoàn trả sạch sẽ khi dừng/gỡ. | Tương thích 100% với WMI / `netsh` / PowerShell qua Python Service. | **ADOPT** |
| **REF-11** | **Công cụ Khôi phục Hệ thống Sạch (`SafeKidsCleanup.exe` / `ProtectionMaintenance`) & Quy trình gỡ cài đặt có mật khẩu** | Đề bài yêu cầu quy trình gỡ cài đặt hợp pháp có mật khẩu phụ huynh (F4 NÊN CÓ) và chạy được trên máy sạch (README). | **NÊN CÓ (F4) & BẮT BUỘC (M5)**: Quy trình gỡ cài đặt hợp pháp bằng mật khẩu phụ huynh, ghi sự kiện gỡ; khôi phục mạng sạch sẽ. | **Rất cao**: Tránh lỗi mất mạng (do DNS vẫn trỏ về `127.0.0.1`) khi Service dừng hoặc khi giảng viên gỡ thử nghiệm trên máy chấm bài. | Tương thích 100% dưới dạng mô-đun/CLI `ogk_cleanup.py` trong `/agent`. | **ADOPT** |
| **REF-12** | **Tạm dừng bảo vệ có kiểm soát (`ProtectionLifecycleCoordinator.Suspend/Resume`)** | Đề bài có mục CÓ THÌ TỐT (F4): Chế độ "tạm nghỉ của phụ huynh" trong 2 giờ, có ghi log. | **CÓ THÌ TỐT (F4)**: Tạm dừng toàn bộ kiểm soát trong 2 giờ (hoặc thời gian xác định), có ghi nhật ký kiểm toán. | **Khá cao**: Dễ tích hợp vào lệnh khẩn WebSocket / Dashboard phụ huynh và tự động bật lại khi hết hạn. | Tương thích 100% với trạng thái của `OGK-Agent` và `OGK-Server`. | **ADAPT** |
| **REF-13** | **Phát hiện gian lận đồng hồ hệ thống (`ClockTampered` / `LastSeenUtc`)** | Đề bài bắt buộc chống chỉnh đồng hồ hệ thống bằng đồng hồ đơn điệu và đối chiếu thời gian máy chủ. | **BẮT BUỘC (F1, M6)**: Lùi đồng hồ 3 giờ quota không tăng, sự kiện bị ghi nhận; kết hợp monotonic clock + đối chiếu server mỗi heartbeat 60s. | **Rất cao**: Kết hợp cơ chế lưu `last_seen_utc` cục bộ của Reference App với `time.monotonic()` và `server_utc` của OGK để chống chỉnh giờ cả khi online lẫn offline. | Tương thích 100% với Python `time.monotonic()`. | **ADAPT** |
| **REF-14** | **Bảo vệ mật khẩu phụ huynh, khóa tạm khi sai quá số lần (`LoginLockoutUntilUtc`) & Mã khôi phục (`RecoveryHash`)** | Đề bài yêu cầu Argon2id/scrypt, khóa 15 phút sau 5 lần sai, rate limit theo IP; gỡ cài đặt trên máy trẻ dùng mật khẩu/mã phụ huynh. | **BẮT BUỘC (F5) & NÊN CÓ (F4)**: Khóa tạm 15 phút sau 5 lần sai; xác thực phụ huynh trên Dashboard và khi gỡ/mở khóa khẩn trên máy trẻ. | **Cao**: Áp dụng cơ chế khóa tạm và mã khôi phục/PIN офлайн (băm Argon2id) để phụ huynh có thể mở khóa hoặc gỡ Agent ngay cả khi máy trẻ đang mất mạng. | Tương thích 100% với `passlib[argon2]`. | **ADAPT** |
| **REF-15** | **Liên kết hồ sơ trẻ với Windows SID (`WindowsUserSid`) & Phân biệt Standard User / Admin** | Đề bài yêu cầu mô hình `1 phụ huynh : n trẻ : m thiết bị` và tài khoản trẻ không thuộc nhóm Administrators. | **BẮT BUỘC (F4, F5)**: Tài khoản trẻ là Standard User; ánh xạ thiết bị/phiên đăng nhập với `child_id`. | **Cao**: Giúp `OGK-Agent` trên 1 máy tính gia đình dùng chung biết phiên đăng nhập hiện tại là của trẻ (áp dụng chính sách) hay của phụ huynh (không chặn nhầm phụ huynh). | Tương thích 100% với `win32security` / `psutil`. | **ADAPT** |
| **REF-16** | **Chống tạo tài khoản Windows mới (`WindowsAccountCreationGuard`) & Chặn trình cài đặt (`InstallerGuard`)** | Không nằm trong F1–F5 bắt buộc, nhưng liên quan trực tiếp đến mục **M3 (Phân tích đường vòng: tài khoản Windows khác)**. | **BẮT BUỘC PHÂN TÍCH (M3)**: M3 yêu cầu phân tích kỹ thuật vượt rào bằng "tài khoản Windows khác". (Lưu ý: Standard User mặc định không tạo được user mới). | **Trung bình**: Có giá trị phân tích trong báo cáo M3 và cảnh báo nếu phát hiện SID lạ, nhưng không cần tự động vô hiệu hóa tài khoản hệ thống để tránh rủi ro trên máy chấm bài. | Đưa vào nhóm tính năng mở rộng / phân tích M3. | **DEFER** |
| **REF-17** | **Tường lửa chặn trình duyệt có VPN tích hợp (`EmbeddedVpnBrowserGuard` / `FirewallRuleManager`)** | Không bắt buộc trong F1–F5, liên quan đến mục **M3 (Phân tích đường vòng: VPN/proxy)**. | **BẮT BUỘC PHÂN TÍCH (M3)**: M3 yêu cầu phân tích VPN/proxy công cộng và nêu biện pháp đối phó. | **Trung bình**: Có thể chặn Opera VPN / công cụ VPN qua danh sách chặn ứng dụng (`App Controller` theo SHA-256) thay vì can thiệp phức tạp vào Windows Firewall. | Xử lý qua `App Controller` (F2) hoặc để giai đoạn mở rộng. | **DEFER** |
| **REF-18** | **Quét và thu hồi tiện ích mở rộng trình duyệt (`CocCocExtensionScanner`, `FirefoxExtensionScanner`, `ExtensionPolicyManager`)** | Không có trong yêu cầu của giảng viên. | Không yêu cầu trong `DoAn01.docx`. | **Thấp cho đồ án**: Quá trình quét thư mục `User Data` và ép chính sách Extension rất phức tạp, tốn thời gian và nằm ngoài phạm vi 6 tuần. | Không cần thiết cho phạm vi đồ án. | **DEFER** |
| **REF-19** | **Tiện ích `SocialExtension` theo dõi URL đầy đủ, từ khóa tìm kiếm Google/YouTube/TikTok & tiêu đề video đang xem** | Không có. Dự án OGK thu thập sự kiện ở mức DNS Proxy và tiến trình. | **XUNG ĐỘT NGHIÊM TRỌNG VỚI F3**: Mục F3 quy định rõ: *"Lược đồ sự kiện chỉ gồm: `ts, device_id, child_id, type, subject, duration_sec, policy_id`... Trường `subject` là tên ứng dụng hoặc **tên miền cấp hai, không phải URL đầy đủ**."* | **Vi phạm quy định riêng tư của đề bài**: Dù `SocialExtension` có banner minh bạch, việc thu thập URL đầy đủ (`/watch?v=...`), từ khóa tìm kiếm và tiêu đề video vi phạm trực tiếp giới hạn lược đồ F3 và triết lý tối thiểu hóa dữ liệu của giảng viên. | **Xung đột với Teacher Requirement F3**. | **REJECT** |
| **REF-20** | **Chụp ảnh màn hình Desktop làm bằng chứng vi phạm (`ScreenCaptureService`, `EvidenceCrypto`, `EvidenceRepository`)** | Không có. | **XUNG ĐỘT NGHIÊM TRỌNG VỚI TRIẾT LÝ ĐỀ BÀI & F3**: Đề bài nhấn mạnh *"Công cụ đồng hành, không phải phần mềm theo dõi lén"* và mục F3 bắt buộc loại bỏ mọi trường dữ liệu ngoài 7 trường cơ bản. | **Vi phạm nguyên tắc quyền riêng tư trẻ em**: Chụp ảnh màn hình lén khi trẻ dùng máy mang tính chất giám sát xâm phạm (surveillance), trái ngược hoàn toàn với yêu cầu của giảng viên. | **Xung đột với Teacher Requirement F3 & F5**. | **REJECT** |
| **REF-21** | **Bộ dữ liệu 83.776 tên miền thực tế chứa nội dung người lớn (`adult.txt`), cờ bạc (`gambling.txt`) đính kèm mã nguồn** | Dự án yêu cầu bộ phân loại $\ge 200$ mục an toàn và bộ kiểm thử 50 tên miền trung tính. | **XUNG ĐỘT NGHIÊM TRỌNG VỚI QUY ĐỊNH KIỂM THỬ (F2)**: *"Tuyệt đối không sử dụng, truy cập hay đính kèm tên miền có nội dung người lớn để 'thử nghiệm'. Nhóm nào nộp danh sách như vậy sẽ bị trừ điểm."* | **Nguy cơ bị trừ điểm trực tiếp**: Chỉ học hỏi **cấu trúc kỹ thuật** (`manifest.json` + chữ ký số), tuyệt đối **KHÔNG** sao chép nội dung tệp `adult.txt` / `gambling.txt` vào đồ án! | **Xung đột trực tiếp với quy định F2**. | **REJECT** *(nội dung danh sách)* |
| **REF-22** | **Ẩn/Khóa ổ đĩa (`DriveProtectionManager`), Két an toàn tự phục hồi file (`VaultManager`), Quản lý bản quyền (`LicenseManager`) & Hỗ trợ Zalo (`ZaloPcLauncher`)** | Không có. | Không nằm trong yêu cầu `DoAn01.docx`. | **Không phù hợp**: Đây là các tính năng thương mại hóa hoặc bảo vệ tệp tin gia đình ngoài phạm vi môn Mạng máy tính, gây phình to dự án và rủi ro khóa nhầm phân vùng ổ đĩa khi chấm bài. | Ngoài phạm vi đồ án (Out of Scope). | **REJECT** |

---

## 3. Phân Tích Chi Tiết Từng Tính Năng Tham Khảo (9 Tiêu Chí)

Dưới đây là đánh giá chi tiết từng nhóm tính năng theo 9 câu hỏi phân tích chuẩn kiến trúc:

### 3.1. Nhóm Tính Năng Đề Xuất Áp Dụng Trực Tiếp (`ADOPT` — 7 Tính năng)

#### 1. `REF-01`: Kiến trúc tách biệt Service (`SYSTEM`) & Session Agent (`User`) kèm cơ chế tự khởi chạy (`SessionAgentLauncher`)
1. **Giải quyết vấn đề gì?** Trên Windows Vista/10/11, dịch vụ chạy ở Session 0 (`LocalSystem`) bị cô lập hoàn toàn với màn hình Desktop của người dùng (Session 1+), nên không thể trực tiếp hiển thị hộp thoại hay biểu tượng khay hệ thống (Tray Icon). Đồng thời, nếu trẻ dùng Task Manager tắt tiến trình Tray UI chạy ở quyền User, hệ thống cần tự động phát hiện và bật lại, hoặc xử lý theo quy tắc chống ẩn (F5).
2. **Đối tượng người dùng?** Trẻ em (nhìn thấy đồng hồ đếm ngược, cảnh báo, biểu tượng minh bạch) và Hệ thống (`OGK-Agent`).
3. **Cách hoạt động & luồng xử lý?** `OGK-Agent Service` (chạy quyền `SYSTEM`) định kỳ kiểm tra phiên đăng nhập đang hoạt động (Active Console Session) qua Win32 WTS API (`WTSEnumerateSessions`, `WTSQueryUserToken`). Nếu tiến trình `OGK-Tray` chưa chạy trong phiên của trẻ, Service nhân bản token (`DuplicateTokenEx`) và gọi `CreateProcessAsUser` để khởi chạy lại `OGK-Tray` trong vòng $< 3$ giây. Nếu sau $N$ lần thử liên tiếp mà `OGK-Tray` vẫn không thể khởi tạo giao diện (ví dụ lỗi môi trường đồ họa), Service ghi nhận sự kiện và tự dừng cưỡng chế theo đúng yêu cầu F5 (*"Nếu không thể hiển thị biểu tượng, agent phải tự dừng"*).
4. **Trùng lặp với chức năng hiện tại?** Bổ sung cơ chế hiện thực hóa cụ thể cho hai thành phần `OGK-Agent — Service` và `OGK-Agent — Tray UI` đã nêu ở mục 4.2 của `DoAn01.docx`.
5. **Phù hợp với yêu cầu giáo viên?** Hoàn toàn phù hợp với mục 4.2, F5 (Chống lạm dụng / Không có chế độ ẩn) và M5 (Khả năng chịu lỗi khi agent bị kết thúc).
6. **Tương thích kiến trúc & công nghệ?** Tương thích 100% với `pywin32` (`win32ts`, `win32security`, `win32process`, `win32serviceutil`) và `psutil`.
7. **Độ phức tạp triển khai?** Trung bình (khoảng 120–150 dòng code Python sử dụng `pywin32`).
8. **Tác động tiến độ & phạm vi?** Rất tích cực: giải quyết triệt để bài toán giao tiếp giữa Service và giao diện người dùng trên Windows.
9. **Phụ thuộc bên ngoài?** Không (chỉ dùng thư viện `pywin32` đã có trong stack bắt buộc).

#### 2. `REF-02`: Giao thức IPC qua Named Pipe/Localhost với Phong bì (`IpcEnvelope`), Xác thực SID & `FixedTimeEquals`
1. **Giải quyết vấn đề gì?** Bảo vệ kênh giao tiếp cục bộ giữa `OGK-Tray` và `OGK-Service`, ngăn chặn trường hợp trẻ tự viết script kết nối vào Named Pipe/Localhost để giả mạo lệnh mở khóa hoặc tắt bảo vệ.
2. **Đối tượng người dùng?** Nội bộ hệ thống (`OGK-Service` và `OGK-Tray` / CLI quản trị cục bộ).
3. **Cách hoạt động & luồng xử lý?** Mọi thông điệp IPC được đóng gói trong cấu trúc JSON chuẩn (`IpcEnvelope`) gồm: `protocol_version`, `request_id`, `type`, `payload`, `timestamp_utc`, `caller_sid` và `auth_token` (hoặc `challenge_token`). Các lệnh chỉ đọc (như lấy số phút còn lại) chỉ cho phép `caller_sid` khớp với phiên người dùng đang hoạt động; các lệnh đặc quyền (như gỡ cài đặt hợp pháp hoặc mở khóa cục bộ bằng mật khẩu phụ huynh) yêu cầu Challenge-Response token và so sánh chuỗi bằng hàm thời gian cố định `hmac.compare_digest` (tương đương `FixedTimeEquals` trong `SafeKids`).
4. **Trùng lặp với chức năng hiện tại?** Cụ thể hóa ghi chú kỹ thuật ở mục 4.2 (*"giao tiếp với service qua named pipe hoặc HTTP 127.0.0.1 có token cục bộ"*).
5. **Phù hợp với yêu cầu giáo viên?** Đáp ứng trực tiếp mục 4.2, F5 (Đặc quyền cục bộ) và M3 (Phân tích đường vòng).
6. **Tương thích kiến trúc & công nghệ?** Tương thích 100% với Python chuẩn (`hmac`, `json`, `win32pipe` / `asyncio`).
7. **Độ phức tạp triển khai?** Thấp – Trung bình.
8. **Tác động tiến độ & phạm vi?** Giúp chuẩn hóa giao diện giữa thành viên làm Service và thành viên làm Tray UI.
9. **Phụ thuộc bên ngoài?** Không.

#### 3. `REF-03`: Nhận diện ứng dụng đa lớp (Tên tiến trình + SHA-256 + PE VersionInfo `OriginalFileName`)
1. **Giải quyết vấn đề gì?** Ngăn trẻ vượt rào bằng cách đổi tên tệp thực thi (ví dụ đổi `genshin.exe` hoặc `notepad.exe` thành `word.exe`).
2. **Đối tượng người dùng?** Phụ huynh (cấu hình danh sách chặn/cho phép) và Trẻ em (nhận thông báo rõ ràng).
3. **Cách hoạt động & luồng xử lý?** Khi quét tiến trình qua `psutil.process_iter(['pid', 'name', 'exe'])`, `App Controller` tính mã băm SHA-256 của tệp thực thi (có bộ nhớ đệm LRU cache theo `(exe_path, mtime, file_size)` để không tốn CPU đọc lại đĩa) và đọc thêm `OriginalFileName` / `ProductName` trong PE Header qua `win32api.GetFileVersionInfo`. Nếu khớp SHA-256 hoặc `OriginalFileName` trong danh sách chặn, tiến trình bị kết thúc.
4. **Trùng lặp với chức năng hiện tại?** Nâng cấp trực tiếp cho yêu cầu F2 (*"đối chiếu tên tiến trình kèm mã băm SHA-256 của tệp thực thi"*).
5. **Phù hợp với yêu cầu giáo viên?** Đáp ứng 100% tiêu chí nghiệm thu F2 (*"Đổi tên notepad.exe thành game.exe vẫn bị nhận diện đúng"*) và tối ưu hiệu năng cho mục M4 (CPU/RAM thấp nhờ cache SHA-256).
6. **Tương thích kiến trúc & công nghệ?** Dùng sẵn `hashlib`, `psutil` và `pywin32` (`win32api`).
7. **Độ phức tạp triển khai?** Thấp.
8. **Tác động tiến độ & phạm vi?** Rất nhỏ (chỉ khoảng 60 dòng code Python), giúp bài demo F2 và đo hiệu năng M4 đạt kết quả xuất sắc.
9. **Phụ thuộc bên ngoài?** Không.

#### 4. `REF-06`: Cơ chế xác minh tính toàn vẹn Chính sách & Danh mục phân loại bằng chữ ký số / HMAC (`Policy & Filter Verifier`)
1. **Giải quyết vấn đề gì?** Ngăn chặn việc sửa đổi trái phép tệp chính sách hoặc cơ sở dữ liệu phân loại tên miền (200+ mục) lưu cục bộ trên máy trẻ hoặc trên đường truyền.
2. **Đối tượng người dùng?** Hệ thống (`OGK-Server` phát hành, `OGK-Agent` xác minh).
3. **Cách hoạt động & luồng xử lý?** Kế thừa ý tưởng `FilterPackageManifest` + `FilterPackageVerifier` của `SafeKids` và yêu cầu F4 của giảng viên: mỗi bản chính sách từ `OGK-Server` có `policy_version` tăng dần, `issued_at_utc`, danh sách quy tắc, kèm chữ ký toàn vẹn (`HMAC-SHA256` hoặc chữ ký bất đối xứng `Ed25519`/`RSA-PSS`). `OGK-Agent` kiểm tra chữ ký trước khi lưu vào SQLite cục bộ và trước khi nạp từ bộ nhớ đệm khi khởi động ngoại tuyến. Nếu chữ ký không hợp lệ, Agent từ chối áp dụng và ghi sự kiện cảnh báo.
4. **Trùng lặp với chức năng hiện tại?** Cụ thể hóa yêu cầu bắt buộc tại mục F4 (*"Chính sách có đánh số phiên bản và ký hiệu toàn vẹn (HMAC hoặc chữ ký) để agent từ chối chính sách bị sửa đổi"*).
5. **Phù hợp với yêu cầu giáo viên?** Bắt buộc tại F4.
6. **Tương thích kiến trúc & công nghệ?** Tương thích 100% với Python `hmac`, `hashlib` và `cryptography`.
7. **Độ phức tạp triển khai?** Thấp.
8. **Tác động tiến độ & phạm vi?** Nằm trong lộ trình cốt lõi tuần 2–3.
9. **Phụ thuộc bên ngoài?** Thư viện chuẩn Python / `cryptography`.

#### 5. `REF-08`: Quản lý Chính sách Trình duyệt qua Registry kèm Snapshot khôi phục (`BrowserPolicyManager` & `BrowserPolicySnapshot`)
1. **Giải quyết vấn đề gì?** Trình duyệt hiện đại (Chrome, Edge, Brave, Cốc Cốc) thường bật sẵn DNS-over-HTTPS (DoH), khiến truy vấn DNS đi qua cổng HTTPS (443) tới thẳng máy chủ Google/Cloudflare và bỏ qua DNS Proxy cục bộ `127.0.0.1:53` của Agent.
2. **Đối tượng người dùng?** Hệ thống (`OGK-Agent`) hỗ trợ phụ huynh thực thi lọc web nhất quán.
3. **Cách hoạt động & luồng xử lý?** Trước khi can thiệp Registry, `OGK-Agent` chụp lại trạng thái gốc của các khóa `HKLM\SOFTWARE\Policies\Google\Chrome`, `HKLM\SOFTWARE\Policies\Microsoft\Edge`, `HKLM\SOFTWARE\Policies\BraveSoftware\Brave`, `HKLM\SOFTWARE\Policies\CocCoc\Browser` vào bảng `system_snapshots` trong SQLite cục bộ. Sau đó, Agent thiết lập `DnsOverHttpsMode = "off"` (tắt DoH trên trình duyệt để ép trình duyệt dùng stub resolver hệ thống qua `127.0.0.1:53`). Khi gỡ cài đặt hoặc tắt bảo vệ, Agent đọc snapshot khôi phục lại đúng giá trị Registry ban đầu.
4. **Trùng lặp với chức năng hiện tại?** Hiện thực hóa trực tiếp yêu cầu NÊN CÓ tại F2 (*"Đối phó DNS-over-HTTPS... khuyến nghị thiết lập chính sách trình duyệt"*) và M3.
5. **Phù hợp với yêu cầu giáo viên?** Đáp ứng xuất sắc tiêu chí nghiệm thu F2 (*"Bật DoH trong Chrome: nêu rõ kết quả và cách xử lý"*) và M3.
6. **Tương thích kiến trúc & công nghệ?** Dùng mô-đun `winreg` có sẵn trong Python chuẩn.
7. **Độ phức tạp triển khai?** Thấp (khoảng 80 dòng code Python).
8. **Tác động tiến độ & phạm vi?** Giúp giải quyết triệt để vấn đề DoH trên trình duyệt mà không cần cài chứng chỉ MITM HTTPS phức tạp.
9. **Phụ thuộc bên ngoài?** Không.

#### 6. `REF-09`: Cảm biến phát hiện vượt rào: VPN Adapter, System Proxy & DoH (`Bypass Detector`)
1. **Giải quyết vấn đề gì?** Phát hiện khi trẻ bật VPN (OpenVPN, WireGuard, Cloudflare WARP), cấu hình System Proxy hoặc kết nối tới các điểm cuối DoH công cộng để vượt qua DNS Proxy `127.0.0.1:53`.
2. **Đối tượng người dùng?** Phụ huynh (nhận cảnh báo/báo cáo) và Nhóm phát triển (cung cấp số liệu thực nghiệm cho phụ lục mạng M3).
3. **Cách hoạt động & luồng xử lý?**
   - Tại tầng DNS Proxy (`127.0.0.1:53`): Chặn danh sách điểm cuối DoH phổ biến (`dns.google`, `cloudflare-dns.com`, `dns.quad9.net`, `doh.opendns.com`...) và trả về `NXDOMAIN` cho tên miền canary của Firefox (`use-application-dns.net`).
   - Tại tầng Hệ thống (`Bypass Detector`): Định kỳ kiểm tra danh sách card mạng qua `psutil.net_if_stats()` / WMI để phát hiện tunnel/TAP/WireGuard/WARP adapter, và kiểm tra Registry `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings` (`ProxyEnable`, `ProxyServer`).
4. **Trùng lặp với chức năng hiện tại?** Cụ thể hóa yêu cầu F2 (NÊN CÓ) và M3 (BẮT BUỘC).
5. **Phù hợp với yêu cầu giáo viên?** Hoàn toàn phù hợp; lưu ý khi ghi sự kiện lên Server phải tuân thủ đúng lược đồ 7 trường của F3 (`type = blocked_domain` hoặc `blocked_app`, `subject` là tên miền hoặc tên ứng dụng VPN).
6. **Tương thích kiến trúc & công nghệ?** Tương thích 100% với Python (`psutil`, `winreg`, DNS Proxy).
7. **Độ phức tạp triển khai?** Trung bình.
8. **Tác động tiến độ & phạm vi?** Trực tiếp phục vụ cả điểm chức năng F2 lẫn báo cáo kỹ thuật mạng M3.
9. **Phụ thuộc bên ngoài?** Không.

#### 7. `REF-10` & `REF-11`: Quản lý DNS Card mạng kèm Snapshot khôi phục (`LegacyDnsRecoveryManager`) & Công cụ Khôi phục Hệ thống Sạch (`OGKCleanup`)
1. **Giải quyết vấn đề gì?** Để DNS Proxy tại `127.0.0.1:53` nhận được truy vấn từ trình duyệt (M1), `OGK-Agent` cần cấu hình DNS của card mạng đang hoạt động về `127.0.0.1` và ngăn trẻ đổi DNS thủ công sang `8.8.8.8` (F2 NÊN CÓ). Tuy nhiên, nếu Service dừng đột ngột hoặc gỡ cài đặt mà không trả lại DNS gốc (DHCP hoặc IP tĩnh ban đầu), máy tính sẽ mất khả năng phân giải tên miền.
2. **Đối tượng người dùng?** Phụ huynh, Trẻ em và Giảng viên chấm bài (cài thử trên máy Windows sạch trong 15 phút theo README).
3. **Cách hoạt động & luồng xử lý?**
   - Khi `OGK-Service` khởi động: Chụp snapshot cấu hình DNS hiện tại của các card mạng vật lý/Wi-Fi (`interface_index`, `dhcp_enabled`, `dns_servers`) lưu vào SQLite cục bộ, sau đó chuyển DNS của card mạng về `127.0.0.1` và gọi `DnsFlushResolverCache()`.
   - Trong khi chạy: Định kỳ kiểm tra (hoặc lắng nghe sự kiện thay đổi mạng); nếu phát hiện DNS bị đổi thủ công sang `8.8.8.8` / `1.1.1.1` khi chưa có quyền phụ huynh, tự động ép lại về `127.0.0.1` và ghi nhận vi phạm.
   - Khi dừng hợp lệ hoặc chạy công cụ `ogk_cleanup.py`: Đọc snapshot khôi phục lại chính xác cấu hình DNS ban đầu (DHCP hoặc DNS tĩnh), khôi phục Registry Policies của trình duyệt và xóa cache DNS.
4. **Trùng lặp với chức năng hiện tại?** Bổ sung mảnh ghép kỹ thuật quan trọng nhất để vận hành an toàn DNS Proxy `127.0.0.1:53` (M1, F2, F4, M5).
5. **Phù hợp với yêu cầu giáo viên?** Đáp ứng trực tiếp M1, F2 (NÊN CÓ: chặn cấu hình lại DNS thủ công), F4 (NÊN CÓ: gỡ cài đặt hợp pháp) và yêu cầu README cài đặt/gỡ sạch trên máy chấm bài.
6. **Tương thích kiến trúc & công nghệ?** Tương thích 100% với Python (`wmi` / `netsh` / `pywin32`).
7. **Độ phức tạp triển khai?** Trung bình.
8. **Tác động tiến độ & phạm vi?** Cực kỳ cần thiết để đảm bảo an toàn khi demo và chấm đồ án.
9. **Phụ thuộc bên ngoài?** Không.

---

### 3.2. Nhóm Tính Năng Đề Xuất Điều Chỉnh Trước Khi Áp Dụng (`ADAPT` — 8 Tính năng)

1. **`REF-04` (Cửa sổ đếm ngược & Xin phép phụ huynh $\rightarrow$ Điều chỉnh sang mô hình Lai Remote + Local)**:
   - *Trong Safe Kids*: Chỉ cho phép phụ huynh nhập mật khẩu trực tiếp trên máy trẻ (`AllowOnce`, `AllowUntilRestart`, `AllowPermanent`).
   - *Cách điều chỉnh cho OGK*: Giữ trải nghiệm đếm ngược 60 giây nhân văn (`quota_warning` ở 10, 5, 1 phút + 60 giây ân hạn lưu bài) và cửa sổ giải thích rõ lý do khi chặn ứng dụng, nhưng nút **"Xin thêm giờ" / "Xin mở khóa"** mặc định gửi sự kiện `unlock_request` lên `OGK-Server` để phụ huynh duyệt từ xa trên điện thoại (nhận lệnh `override_granted` qua WebSocket dưới 5 giây), đồng thời hỗ trợ tùy chọn nhập mã PIN/mật khẩu phụ huynh tại chỗ khi mất mạng.
2. **`REF-05` (Cấu hình hạn mức thời gian $\rightarrow$ Điều chỉnh theo chuẩn Ma trận $7 \times 48$ và Quota Nhóm)**:
   - *Trong Safe Kids*: Dùng chuỗi `TimeWindows` tự do và `CustomLimitPeriod`.
   - *Cách điều chỉnh cho OGK*: Chuẩn hóa thành hạn mức ngày thường/cuối tuần, **ma trận lịch tuần $7 \times 48$ (độ phân giải 30 phút)** theo đúng F1 bắt buộc, và bộ đếm độc lập theo **6 nhóm phân loại** (F1 NÊN CÓ).
3. **`REF-07` (Cơ chế can thiệp DNS $\rightarrow$ Chuyển từ `hosts` file sang `DNS Proxy 127.0.0.1:53` + giữ lại `DnsFlushResolverCache`)**:
   - *Trong Safe Kids*: Ghi trực tiếp hàng chục nghìn dòng vào tệp `C:\Windows\System32\drivers\etc\hosts`.
   - *Cách điều chỉnh cho OGK*: Tuân thủ tuyệt đối yêu cầu của giảng viên là xây dựng **DNS Proxy cục bộ tại `127.0.0.1:53`** (hỗ trợ chặn tên miền gốc, tên miền con wildcard `*.domain`, và ánh xạ CNAME/A cho SafeSearch). Chỉ kế thừa kỹ thuật gọi hàm `DnsFlushResolverCache` của `SafeKids` để xóa bộ nhớ đệm DNS của Windows ngay khi chính sách thay đổi. Phân tích tệp `hosts` của `SafeKids` được dùng làm tư liệu thực tế cho bảng so sánh mục **M2**.
4. **`REF-12` (Tạm dừng bảo vệ $\rightarrow$ Điều chỉnh thành "Chế độ tạm nghỉ của phụ huynh" có thời hạn 2 giờ và ghi Audit Log)**:
   - *Trong Safe Kids*: `ProtectionLifecycleCoordinator.Suspend` tạm dừng không thời hạn cho tới khi Resume.
   - *Cách điều chỉnh cho OGK*: Gắn bộ hẹn giờ tự động bật lại sau 2 giờ (hoặc thời gian phụ huynh chọn), đẩy lệnh qua WebSocket xuống Agent trong $< 5$ giây, và ghi đầy đủ vào Nhật ký kiểm toán (Audit Log) mà trẻ có thể xem được theo nguyên tắc minh bạch NT5 (F4).
5. **`REF-13` (Phát hiện chỉnh giờ $\rightarrow$ Kết hợp `last_seen_utc` cục bộ với `time.monotonic()` và đối chiếu `server_utc`)**:
   - *Trong Safe Kids*: Chỉ so sánh `DateTime.UtcNow` với `LastSeenUtc` lưu trong file.
   - *Cách điều chỉnh cho OGK*: Đáp ứng mục F1 và M6 bằng cơ chế 3 lớp: (1) Đếm thời gian thực bằng đồng hồ đơn điệu `time.monotonic()` (miễn nhiễm hoàn toàn với việc chỉnh giờ Windows khi máy đang chạy); (2) Lưu `last_wall_clock_utc` định kỳ để phát hiện lùi giờ khi khởi động lại máy offline; (3) Đối chiếu độ lệch (`clock_drift_sec`) với thời gian của `OGK-Server` mỗi nhịp tim 60 giây và phát cảnh báo khi lệch quá ngưỡng (ví dụ $> 120$ giây).
6. **`REF-14` (Bảo vệ mật khẩu & Khóa đăng nhập $\rightarrow$ Chuẩn hóa sang Argon2id/scrypt + Rate Limit Server & Local)**:
   - *Trong Safe Kids*: Băm mật khẩu cục bộ và khóa trên ứng dụng Desktop.
   - *Cách điều chỉnh cho OGK*: Áp dụng băm **Argon2id** (`passlib`), tối thiểu 10 ký tự, khóa 15 phút sau 5 lần sai kèm giới hạn tần suất theo IP trên `OGK-Server` (F5), đồng thời lưu một mã băm xác thực phụ huynh (được đồng bộ trong chính sách ký số) dưới `OGK-Agent` để xác thực khi gỡ cài đặt hợp pháp hoặc mở khóa ngoại tuyến.
7. **`REF-15` (Liên kết Windows SID $\rightarrow$ Tích hợp vào mô hình Đa thiết bị `1 Parent : n Children : m Devices`)**:
   - *Trong Safe Kids*: Chỉ quản lý cục bộ trên 1 máy.
   - *Cách điều chỉnh cho OGK*: Mở rộng thành mô hình `1 phụ huynh : n trẻ : m thiết bị` trên `OGK-Server` (F4), trong đó mỗi bản ghi thiết bị/liên kết trẻ có thể lưu kèm `windows_user_sid` hoặc `windows_username` để Agent tự động nhận biết phiên đăng nhập của trẻ trên máy tính dùng chung trong gia đình.

---

### 3.3. Nhóm Tính Năng Hoãn Lại (`DEFER` — 3 Tính năng) & Từ Chối (`REJECT` — 4 Tính năng)

- **Lý do DEFER (`REF-16`, `REF-17`, `REF-18`)**:
  - Việc tự động vô hiệu hóa tài khoản Windows mới (`WindowsAccountCreationGuard`), tự động thêm quy tắc Windows Firewall chặn trình duyệt (`FirewallRuleManager`), hay quét sâu thư mục Extension của từng trình duyệt (`CocCocExtensionScanner`) làm tăng đáng kể rủi ro can thiệp hệ điều hành ngoài ý muốn khi giảng viên chạy thử nghiệm trên máy chấm bài.
  - Thay vào đó, các kịch bản này được **đưa vào tài liệu phân tích đường vòng M3** (với giải pháp kiểm soát gọn nhẹ hơn: đảm bảo tài khoản trẻ là Standard User không có quyền tạo tài khoản mới hay cài dịch vụ hệ thống, và chặn các tệp thực thi VPN/trình duyệt lạ qua `App Controller` bằng SHA-256).
- **Lý do REJECT (`REF-19`, `REF-20`, `REF-21`, `REF-22`)**:
  - **`REF-19` (`SocialExtension` thu thập URL đầy đủ, từ khóa tìm kiếm, tiêu đề video)** và **`REF-20` (Chụp ảnh màn hình Desktop làm bằng chứng)**: **Vi phạm trực tiếp yêu cầu bắt buộc F3 và F5 của giảng viên**. Giảng viên quy định rõ sản phẩm là *"Công cụ đồng hành, không phải phần mềm theo dõi lén"*, lược đồ sự kiện **chỉ gồm đúng 7 trường** (`ts, device_id, child_id, type, subject, duration_sec, policy_id`), trường `subject` chỉ là **tên ứng dụng hoặc tên miền cấp hai (không phải URL đầy đủ)**, và bất kỳ trường dữ liệu nào không giải thích được mục đích hợp pháp đều phải loại bỏ.
  - **`REF-21` (Danh sách 83.776 tên miền `adult.txt`, `gambling.txt` thực tế)**: **Vi phạm trực tiếp quy định kiểm thử tại mục F2** (*"Tuyệt đối không sử dụng, truy cập hay đính kèm tên miền có nội dung người lớn để 'thử nghiệm'. Nhóm nào nộp danh sách như vậy sẽ bị trừ điểm"*). Dự án OGK chỉ sử dụng các tên miền công khai, an toàn (trường học, thư viện số, báo điện tử) và các tên miền mô phỏng trung tính (`*.adult-sim.test`, `*.gamble-sim.example`...) theo đúng hướng dẫn ở Phụ lục của `DoAn01.docx`.
  - **`REF-22` (Khóa ổ đĩa, Két an toàn tệp tin, Quản lý bản quyền thương mại, Hỗ trợ Zalo)**: Hoàn toàn nằm ngoài phạm vi đề tài môn Mạng máy tính.

---

## 4. Tổng Hợp Quyết Định Phân Loại & Kiểm Soát Phạm Vi (Scope Control)

### 4.1. Thống Kê Quyết Định Đối Với 22 Tính Năng Tham Khảo

| Phân loại | Số lượng | Danh sách mã tính năng | Tỷ lệ |
|---|---|---|---|
| **ADOPT** (Áp dụng trực tiếp) | **7** | `REF-01`, `REF-02`, `REF-03`, `REF-06`, `REF-08`, `REF-09`, `REF-10`/`REF-11` *(cơ chế snapshot & cleanup)* | 31.8% |
| **ADAPT** (Điều chỉnh cho phù hợp) | **8** | `REF-04`, `REF-05`, `REF-07`, `REF-11` *(luồng gỡ cài đặt)*, `REF-12`, `REF-13`, `REF-14`, `REF-15` | 36.4% |
| **DEFER** (Hoãn lại / Chỉ phân tích ở M3) | **3** | `REF-16`, `REF-17`, `REF-18` | 13.6% |
| **REJECT** (Từ chối do xung đột yêu cầu/ngoài phạm vi) | **4** | `REF-19`, `REF-20`, `REF-21` *(nội dung domain người lớn)*, `REF-22` | 18.2% |
| **Tổng cộng** | **22** | `REF-01` $\rightarrow$ `REF-22` | **100%** |

### 4.2. Phân Mức Ưu Tiên Triển Khai (Scope Control: MUST / SHOULD / COULD HAVE)

Để đảm bảo nhóm **03 sinh viên** hoàn thành đúng hạn trong **06 tuần** mà không bị quá tải bởi các tính năng tham khảo, toàn bộ các hạng mục được phân bổ chặt chẽ như sau:

| Mức độ ưu tiên | Tiêu chí phân loại | Danh sách tính năng (Teacher Requirements + Adopted/Adapted Features) |
|---|---|---|
| **MUST HAVE** *(Bắt buộc hoàn thành 100% ở Tuần 1–4)* | Mọi yêu cầu `BẮT BUỘC` trong `DoAn01.docx` (Mục 4, F1–F5, M1–M6) và các cơ chế kỹ thuật từ Reference App giúp hiện thực hóa trực tiếp các yêu cầu bắt buộc đó. | - Kiến trúc `OGK-Agent` (Service + Tray UI) + `OGK-Server` (FastAPI) + `Dashboard` (Web).<br>- Ghép đôi 8 ký tự (10p), Heartbeat 60s, Lệnh khẩn WebSocket ($<5\text{s}$), Offline Queue + Idempotency Key.<br>- Hạn mức ngày thường/cuối tuần, Ma trận lịch tuần $7 \times 48$, Đếm giờ thực (trừ khóa máy / idle $>5\text{p}$), Cảnh báo 10/5/1 phút + Ân hạn 60s (`REF-04` adapted).<br>- Chống chỉnh đồng hồ bằng `time.monotonic()` + `last_seen_utc` + đối chiếu Server (`REF-13` adapted).<br>- Chặn ứng dụng theo tên + SHA-256 + `OriginalFileName` (`REF-03`), hiển thị hộp thoại giải thích.<br>- DNS Proxy `127.0.0.1:53` + xóa cache `DnsFlushResolverCache` (`REF-07` adapted), phân loại 6 nhóm ($\ge 200$ mục an toàn), cưỡng chế SafeSearch.<br>- Lược đồ sự kiện 7 trường minh bạch, Dashboard phụ huynh, Màn hình "Hôm nay em đã dùng gì" cho trẻ, Lưu trữ 90 ngày, Nút xóa toàn bộ dữ liệu, `PRIVACY.md`, `THREATMODEL.md`.<br>- Chính sách đánh số phiên bản và ký toàn vẹn HMAC/chữ ký số (`REF-06`), Nhật ký kiểm toán (Audit Log).<br>- Bảo mật Argon2id, Cookie an toàn + CSRF, TLS 1.2+ & Certificate Pinning, AES-GCM (DPAPI/env), chống IDOR, ACL `ProgramData`, IPC an toàn (`REF-01`, `REF-02`). |
| **SHOULD HAVE** *(Triển khai ở Tuần 4–5 để đạt điểm Khá/Giỏi)* | Các yêu cầu `NÊN CÓ` trong `DoAn01.docx` cùng các cơ chế chống vượt rào / khôi phục hệ thống từ Reference App. | - Ngân sách thời gian độc lập theo nhóm ứng dụng (`REF-05` adapted).<br>- Đối phó DoH: chặn điểm cuối DoH + trả `NXDOMAIN` cho canary domain + tắt DoH qua Registry trình duyệt kèm Snapshot khôi phục (`REF-08`, `REF-09`).<br>- Chặn đổi DNS thủ công + Snapshot cấu hình DNS card mạng & công cụ khôi phục sạch `ogk_cleanup.py` (`REF-10`, `REF-11`).<br>- Quy trình gỡ cài đặt hợp pháp bằng mật khẩu phụ huynh trên máy trẻ (`REF-11`, `REF-14` adapted).<br>- Liên kết phiên Windows (`WindowsUserSid`) để phân biệt tài khoản phụ huynh và tài khoản trẻ trên máy dùng chung (`REF-15` adapted).<br>- Xuất báo cáo tuần ra CSV / PDF (F3 NÊN CÓ). |
| **COULD HAVE** *(Chỉ làm ở Tuần 6 khi đã xong toàn bộ MUST & SHOULD)* | Các yêu cầu `CÓ THÌ TỐT` (điểm thưởng) có chi phí hiện thực thấp, không ảnh hưởng kiến trúc cốt lõi. | - Chế độ "tạm nghỉ của phụ huynh" trong 2 giờ, có ghi Audit Log (`REF-12` adapted / F4 CÓ THÌ TỐT).<br>- Gợi ý "thời gian nghỉ mắt" theo quy tắc 20-20-20 trên Tray UI (F3 CÓ THÌ TỐT).<br>- Cơ chế thưởng giờ khi hoàn thành nhiệm vụ do phụ huynh giao trên Dashboard (F1 CÓ THÌ TỐT).<br>- Xác thực 2 yếu tố TOTP cho tài khoản phụ huynh (F5 điểm cộng). |
