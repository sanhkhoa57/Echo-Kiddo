# Chính Sách & Minh Bạch Quyền Riêng Tư (Privacy Specification)

> **Dự án OGK (Open Guardian for Kids) — Tuân thủ Nghị định 13/2023/NĐ-CP về Bảo vệ Dữ liệu Cá nhân**

---

## 1. Tuyên Ngôn Quyền Riêng Tư Dành Cho Trẻ Em (Phiên Bản Dễ Hiểu)

Chào em! Phần mềm **OGK** trên máy tính này là một người bạn đồng hành giúp em và bố mẹ cùng nhau sắp xếp thời gian học tập và vui chơi hợp lý:
- **Biết rõ giờ giấc**: Biểu tượng OGK ở góc màn hình cho em biết hôm nay em còn bao nhiêu thời gian sử dụng máy tính.
- **Không bao giờ lén lút**: OGK không bao giờ chạy ẩn. Nếu biểu tượng biến mất, phần mềm sẽ tự động dừng lại.
- **Bảo vệ sự riêng tư**: OGK **KHÔNG** chụp ảnh màn hình, **KHÔNG** đọc tin nhắn, **KHÔNG** ghi lại mật khẩu hay những gì em gõ trên bàn phím, và **KHÔNG** lưu lại đường link chi tiết hay video cụ thể em xem. OGK chỉ ghi nhận tên trang web chính (như `youtube.com` hay `wikipedia.org`) để giúp em và bố mẹ theo dõi tổng thời gian.
- **Minh bạch 100%**: Em có thể bấm vào *"Hôm nay em đã dùng gì"* để xem chính xác những gì bố mẹ nhìn thấy, và xem cả lịch sử bố mẹ đã thay đổi quy định như thế nào.

---

## 2. Bảng Đối Chiếu Thu Thập Dữ Liệu (Data Mapping Matrix)

Tuân thủ nghiêm ngặt nguyên tắc **Tối thiểu hóa dữ liệu (Data Minimization)**:

| Trường Dữ Liệu | Mục Đích Thu Thập | Thời Hạn Lưu Trữ | Quyền Tiếp Cận | Ghi Chú Bảo Vệ |
|---|---|---|---|---|
| `ts` | Thời điểm UTC xảy ra sự kiện | Tối đa 90 ngày (Tự xóa) | Phụ huynh & Trẻ | Dùng cho báo cáo theo ngày |
| `device_id` | Định danh máy trạm trong gia đình | Theo vòng đời thiết bị | Phụ huynh & Hệ thống | Băm ngẫu nhiên UUIDv4 |
| `child_id` | Định danh hồ sơ trẻ trong gia đình | Cho đến khi phụ huynh xóa | Phụ huynh & Trẻ | Phân quyền RBAC, chống IDOR |
| `type` | 1 trong 9 loại sự kiện nghiệp vụ chuẩn | Tối đa 90 ngày | Phụ huynh & Trẻ | Ràng buộc CHECK Constraint |
| `subject` | Tên ứng dụng (vd: `notepad.exe`) hoặc eTLD+1 (vd: `google.com`) | Tối đa 90 ngày | Phụ huynh & Trẻ | **Từ chối nếu chứa `/` hoặc `?`** (Tuyệt đối không lưu URL đầy đủ) |
| `duration_sec` | Thời lượng hoạt động thực tế (giây) | Tối đa 90 ngày | Phụ huynh & Trẻ | Chỉ tính khi Active & Idle $\le 300\text{s}$ |
| `policy_id` | Phiên bản chính sách áp dụng tại thời điểm đó | Tối đa 90 ngày | Phụ huynh & Trẻ | Truy vết quy tắc |

---

## 3. Quyền Của Chủ Thể Dữ Liệu (Data Subject Rights)

1. **Quyền được biết**: Trẻ và Phụ huynh được xem cùng một nguồn dữ liệu tại Dashboard và màn hình *"Hôm nay em đã dùng gì"*.
2. **Quyền được xóa**: Phụ huynh có nút *"Xóa toàn bộ dữ liệu của con tôi"*, lập tức xóa toàn bộ bảng `events` trên Server và đẩy lệnh `PURGE_DATA` xóa sạch hàng đợi trên Agent.
3. **Quyền kiểm toán (Audit Trail - NT5)**: Mọi thao tác thay đổi thời gian, quy tắc hay xem dữ liệu đều được ghi vào bảng `audit_logs` có thể tra cứu minh bạch.
