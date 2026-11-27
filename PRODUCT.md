# Product

<!-- impeccable:product-schema 1 -->

> Ghi chú: file này được suy ra từ đề bài `DoAn01.docx` và mã nguồn bản demo, chưa qua phỏng vấn. Các dòng đánh dấu (giả định) cần nhóm xác nhận.

## Platform

web

## Users

- Phụ huynh hoặc người giám hộ: cấu hình từ xa và xem báo cáo, thường trên điện thoại, trong vài phút rảnh. Việc cần làm: đặt hạn mức, lịch tuần, danh sách ứng dụng và tên miền, duyệt yêu cầu xin thêm giờ, gửi lệnh khẩn.
- Trẻ 6 đến 11 tuổi: xem màn hình "Hôm nay em đã dùng gì" và nhật ký kiểm toán trên chính máy tính của mình. Cần ngôn ngữ đơn giản và hình minh họa.
- Giảng viên chấm bài: cài theo README trong 15 phút và thử trên trình duyệt điện thoại.

## Product Purpose

EC - Echo Kiddo là đồ án môn Mạng Máy Tính: agent trên Windows 10/11 quản lý thời gian dùng máy, lọc ứng dụng và website qua DNS proxy cục bộ; máy chủ FastAPI phát hành chính sách có ký HMAC; dashboard web cho phụ huynh. Thành công nghĩa là thay đổi trên dashboard có hiệu lực trên máy trẻ trong 60 giây, lệnh khẩn trong 5 giây, và trẻ luôn thấy được hệ thống ghi nhận gì.

## Positioning

"Công cụ đồng hành, không phải phần mềm theo dõi lén." Không có chế độ ẩn, không chụp màn hình, không keylogger, không đọc nội dung. Sự kiện chỉ có 7 trường. Trẻ được xem cùng dữ liệu và cùng nhật ký kiểm toán với phụ huynh.

## Operating Context

- Ghép đôi bằng mã 8 ký tự, hạn 10 phút, kèm xác nhận đồng ý của cha mẹ (Nghị định 13/2023/NĐ-CP).
- Nhịp tim 60 giây, lệnh khẩn qua WebSocket, đồng bộ ngoại tuyến theo lô có idempotency key.
- Dashboard là Jinja2 + JavaScript thuần, phục vụ bởi FastAPI. Phải dùng được trên trình duyệt điện thoại.

## Capabilities and Constraints

- F1: hạn mức ngày thường và cuối tuần, ma trận lịch 7×48, cảnh báo 10/5/1 phút, ân hạn 60 giây.
- F2: quy tắc ứng dụng (tên exe + SHA-256), quy tắc tên miền, 6 nhóm phân loại, SafeSearch.
- F3: biểu đồ ngày và tuần, top 10 ứng dụng, top 10 tên miền, số lần chặn, danh sách yêu cầu của trẻ, xuất CSV, xóa toàn bộ dữ liệu, lưu 90 ngày.
- F4: mô hình 1 phụ huynh : n trẻ : m thiết bị, nhật ký kiểm toán trẻ được xem.
- Ràng buộc dữ liệu: `subject` chỉ là tên exe hoặc eTLD+1; `type` thuộc 9 giá trị cố định; tên miền nhóm không phù hợp trong dữ liệu mẫu chỉ dùng đuôi `.test` hoặc `.example`.
- Chưa quyết định: tên và phần trăm đóng góp của 3 thành viên nhóm.

## Brand Commitments

- Tên: EC - Echo Kiddo, Open Guardian for Kids.
- Giao diện và tài liệu bằng tiếng Việt.
- Giọng: nói thẳng, bình tĩnh, không dọa nạt, không quảng cáo (giả định).

## Evidence on Hand

- `server/seeds/domain_catalog.json`: bảng phân loại tên miền.
- `demo/seed_demo.py`: dữ liệu mẫu cho demo.
- Chưa có logo, ảnh chụp sản phẩm hay video demo. Không được bịa số liệu đo, lời chứng thực hay khách hàng.

## Product Principles

1. Minh bạch trước: mọi thứ phụ huynh thấy thì trẻ cũng xem được.
2. Thu ít dữ liệu nhất có thể; trường nào không giải thích được mục đích thì bỏ.
3. Chặn luôn kèm lời giải thích, không chặn im lặng.
4. Mọi thay đổi hệ thống trên máy trẻ đều hoàn tác được.

## Accessibility & Inclusion

- Dùng được trên điện thoại ở bề rộng 390px, vùng chạm tối thiểu 44px.
- Trạng thái không chỉ phân biệt bằng màu (ô lịch cho phép/khóa cần thêm dấu hiệu khác màu).
- Màn hình cho trẻ: câu ngắn, cỡ chữ lớn, từ ngữ lớp tiểu học.
