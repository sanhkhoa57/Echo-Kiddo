"""Generator for docs/BaoCaoKyThuatMang.pdf (Network Engineering Appendix M1-M6).

Uses ReportLab with the bundled Be Vietnam Pro TrueType fonts in dashboard/static/fonts
so Vietnamese diacritics render cleanly.
"""
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT_DIR / "dashboard" / "static" / "fonts"
OUT_PATH = ROOT_DIR / "docs" / "BaoCaoKyThuatMang.pdf"


BENCH_MD = ROOT_DIR / "docs" / "benchmark_m4_results.md"


def load_benchmark_tables() -> dict:
    """Parses the Markdown tables written by tests/benchmark_m4.py (no hardcoded numbers)."""
    text = BENCH_MD.read_text(encoding="utf-8")
    meta = [ln[2:] for ln in text.splitlines() if ln.startswith("- ")]
    tables, title, rows = [], "", []
    for ln in text.splitlines() + [""]:
        if ln.startswith("## "):
            title = ln[3:].strip()
        elif ln.startswith("|"):
            cells = [escape(c.strip().replace("`", "")) for c in ln.strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                rows.append(cells)
        elif rows:
            tables.append((title, rows))
            rows = []
    return {"meta": escape(" ".join(m.replace("`", "") for m in meta)), "tables": tables}


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("VietRegular", str(FONTS_DIR / "BeVietnamPro-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("VietBold", str(FONTS_DIR / "BeVietnamPro-Bold.ttf")))


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle(
            "OGKTitle",
            parent=base["Title"],
            fontName="VietBold",
            fontSize=18,
            leading=24,
            textColor=colors.HexColor("#0B6B50"),
            alignment=1,
            spaceAfter=8,
        ),
        "Subtitle": ParagraphStyle(
            "OGKSubtitle",
            parent=base["Normal"],
            fontName="VietRegular",
            fontSize=11,
            leading=16,
            textColor=colors.HexColor("#44554E"),
            alignment=1,
            spaceAfter=18,
        ),
        "H1": ParagraphStyle(
            "OGKH1",
            parent=base["Heading1"],
            fontName="VietBold",
            fontSize=13.5,
            leading=18,
            textColor=colors.HexColor("#074A38"),
            spaceBefore=14,
            spaceAfter=6,
        ),
        "H2": ParagraphStyle(
            "OGKH2",
            parent=base["Heading2"],
            fontName="VietBold",
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#14211C"),
            spaceBefore=8,
            spaceAfter=4,
        ),
        "Body": ParagraphStyle(
            "OGKBody",
            parent=base["Normal"],
            fontName="VietRegular",
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#14211C"),
            spaceAfter=6,
        ),
        "Code": ParagraphStyle(
            "OGKCode",
            parent=base["Code"],
            fontName="Courier",
            fontSize=8.5,
            leading=11.5,
            leftIndent=8,
            backColor=colors.HexColor("#F4F7F5"),
            spaceAfter=8,
        ),
        "Cell": ParagraphStyle(
            "OGKCell",
            parent=base["Normal"],
            fontName="VietRegular",
            fontSize=8.5,
            leading=12,
        ),
        "CellHdr": ParagraphStyle(
            "OGKCellHdr",
            parent=base["Normal"],
            fontName="VietBold",
            fontSize=8.5,
            leading=12,
            textColor=colors.white,
        ),
    }


def make_table(data: list[list[str]], col_widths: list[float], styles: dict[str, ParagraphStyle]) -> Table:
    rows = []
    for r_idx, row in enumerate(data):
        st = styles["CellHdr"] if r_idx == 0 else styles["Cell"]
        rows.append([Paragraph(str(cell).replace("\n", "<br/>"), st) for cell in row])

    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B6B50")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EDF6F2")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9FB1AA")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return t


def build_pdf() -> Path:
    register_fonts()
    styles = make_styles()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(OUT_PATH),
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=2.0 * cm,
        bottomMargin=2.0 * cm,
        title="Báo Cáo Kỹ Thuật Hệ Thống và Mạng (M1-M6) - OGK",
    )

    story = []
    story.append(Paragraph("PHỤ LỤC KỸ THUẬT HỆ THỐNG VÀ MẠNG (M1–M6)", styles["Title"]))
    story.append(Paragraph("Đề tài: OGK (Open Guardian for Kids) — Môn Mạng Máy Tính", styles["Subtitle"]))

    # ==================== M1 ====================
    story.append(Paragraph("M1. Sơ Đồ Luồng Gói Tin Khi Trẻ Mở Một Trang Bị Chặn", styles["H1"]))
    story.append(
        Paragraph(
            "Khi OGK-Service hoạt động, NetworkDnsGuard (agent/platform/network_guard.py) cấu hình DNS của card mạng đang hoạt động về 127.0.0.1 "
            "và gọi DnsFlushResolverCache() để xóa bộ nhớ đệm DNS của Windows. Khi trình duyệt truy cập một tên miền bị chặn (ví dụ blocked.test), "
            "luồng gói tin đi qua các bước sau:",
            styles["Body"],
        )
    )
    story.append(
        Preformatted(
            "1. Browser (Chrome/Edge)  --[DoH tắt qua BrowserPolicyGuard]-->  Windows Stub Resolver (dnscache)\n"
            "2. Windows Stub Resolver  --[UDP/53 Query: blocked.test A]-->  OGK DnsProxyServer (127.0.0.1:53)\n"
            "3. DnsProxyServer         --[evaluate('blocked.test')]-------->  DomainPolicyEngine (HashSet + Suffix Trie)\n"
            "4. DomainPolicyEngine     --[Match: ACTION_BLOCK]------------->  DnsProxyServer\n"
            "5. DnsProxyServer         --[UDP/53 Resp: NOERROR, A 0.0.0.0]->  Browser (Kết nối thất bại tức thì)\n"
            "6. DnsProxyServer         --[blocked_domain (eTLD+1)]--------->  EventBuffer & recent_blocks -> Tray UI",
            styles["Code"],
        )
    )
    story.append(Paragraph("Giải phẫu gói tin và cách kiểm chứng bằng Wireshark:", styles["H2"]))
    story.append(
        Paragraph(
            "Trên Windows, lưu lượng loopback đi qua giao diện Npcap Loopback Adapter với bộ lọc Wireshark: udp.port == 53 || tcp.port == 53. "
            "Gói truy vấn (QR=0, RD=1, QTYPE=A) gửi tới 127.0.0.1:53 nhận về gói phản hồi có cùng Transaction ID (QR=1, AA=1, RCODE=0 NOERROR), "
            "Answer RR chứa địa chỉ sinkhole 0.0.0.0 (TTL=60). Với tên miền canary DoH (use-application-dns.net), phản hồi trả RCODE=3 (NXDOMAIN). "
            "Với SafeSearch (google.com, youtube.com), phản hồi trả bản ghi CNAME tương ứng (forcesafesearch.google.com, restrict.youtube.com). "
            "(Ghi chú: ảnh chụp Wireshark thực tế trên máy lab do nhóm đính kèm khi nộp bài).",
            styles["Body"],
        )
    )

    # ==================== M2 ====================
    story.append(Paragraph("M2. So Sánh 4 Phương Án Chặn Website Theo 5 Tiêu Chí", styles["H1"]))
    m2_table = [
        ["Phương án", "Độ chính xác", "Chặn HTTPS", "Chi phí hiện thực", "Khả năng bị vượt", "Ảnh hưởng hiệu năng"],
        ["1. Tệp hosts (Windows)", "Thấp: chỉ khớp tên miền chính xác, không hỗ trợ wildcard *.domain.", "Có (chặn ở tầng phân giải tên trước TLS).", "Rất thấp (ghi tệp văn bản).", "Cao: dễ vượt bằng đổi tên miền con hoặc DoH.", "Không đáng kể."],
        ["2. DNS Proxy cục bộ (127.0.0.1:53) [ĐƯỢC CHỌN]", "Cao theo tên miền & wildcard (*.domain) qua Suffix Trie O(k); không lọc theo URL path.", "Có (chặn trước khi bắt tay TLS; hỗ trợ SafeSearch CNAME).", "Trung bình (Python asyncio + dnslib).", "Trung bình: vượt được qua DoH/VPN nếu không khóa DNS & Registry.", "Rất thấp (< 1 ms với TTL Cache hit)."],
        ["3. Proxy HTTP/HTTPS cục bộ (MITM)", "Rất cao: lọc được cả đường dẫn URL chi tiết.", "Phức tạp: phải cài CA gốc giả mạo để giải mã TLS.", "Cao (dễ lỗi chứng chỉ, HSTS, certificate pinning).", "Trung bình (ứng dụng không dùng system proxy sẽ lọt).", "Cao (tăng độ trễ mọi luồng TLS)."],
        ["4. Bộ lọc WFP (Windows Filtering Platform)", "Cao ở tầng IP/Port và ALE.", "Khó theo tên miền (phải trích xuất SNI hoặc kết hợp DNS).", "Rất cao (cần driver C/C++ ký số WHQL ở Kernel-mode).", "Thấp (khó tắt từ User-mode).", "Thấp nhưng rủi ro BSOD nếu lỗi driver."],
    ]
    story.append(make_table(m2_table, [2.8 * cm, 2.9 * cm, 2.8 * cm, 2.8 * cm, 3.0 * cm, 3.0 * cm], styles))
    story.append(Spacer(1, 0.25 * cm))
    story.append(
        Paragraph(
            "Lý do chọn DNS Proxy cục bộ làm phương án chính: Phù hợp với yêu cầu đồ án không đọc nội dung/URL chi tiết (F3), "
            "cài đặt 100% bằng Python ở User/Service-mode không cần driver kernel, chặn được HTTPS ngay trước bước TLS handshake và hỗ trợ "
            "cưỡng chế SafeSearch bằng bản ghi CNAME.",
            styles["Body"],
        )
    )

    # ==================== M3 ====================
    story.append(PageBreak())
    story.append(Paragraph("M3. Phân Tích Đường Vòng (9 Kỹ Thuật Vượt Rào)", styles["H1"]))
    m3_table = [
        ["Kỹ thuật vượt rào", "Mô tả cơ chế", "Biện pháp đối phó trong OGK", "Trạng thái kiểm thử"],
        ["1. Đổi DNS thủ công sang 8.8.8.8", "Trẻ mở Network Connections đổi DNS card mạng khỏi 127.0.0.1.", "NetworkDnsGuard định kỳ kiểm tra phát hiện sai lệch so với 127.0.0.1 và tự động đặt lại + flush DNS cache.", "Cài đặt trong network_guard.py (cần chạy quyền Admin trên máy thật để nghiệm thu)."],
        ["2. DNS-over-HTTPS (DoH)", "Trình duyệt mã hóa truy vấn DNS qua HTTPS port 443.", "DNS Proxy trả NXDOMAIN cho use-application-dns.net và các endpoint DoH phổ biến; BrowserPolicyGuard ghi Registry tắt DoH.", "Đã test đơn vị trong test_dns_proxy.py; cần thử trên Chrome thực tế."],
        ["3. DNS-over-TLS (DoT port 853)", "Ứng dụng kết nối DNS mã hóa qua TCP/853.", "BypassDetector giám sát; có thể bổ sung rule Windows Firewall chặn outbound TCP/853.", "Đã ghi nhận trong phân tích kiến trúc; chưa chặn tự động port 853."],
        ["4. VPN / Proxy công cộng", "Cài phần mềm VPN hoặc bật System Proxy để đi vòng.", "BypassDetector (bypass_detector.py) quét adapter VPN ảo và khóa Registry ProxyEnable để phát hiện và ghi sự kiện.", "Đã kiểm thử phát hiện trong test_agent_core.py."],
        ["5. Truy cập trực tiếp bằng IP", "Gõ thẳng địa chỉ IP thay vì tên miền để bỏ qua DNS.", "Giới hạn thiết kế của DNS Proxy (chấp nhận rủi ro ở mức cơ bản; kết hợp AppController chặn công cụ quét IP).", "Chấp nhận rủi ro theo phạm vi đồ án."],
        ["6. Khởi động Windows Safe Mode", "Vào Safe Mode không nạp Windows Service bên thứ ba.", "Yêu cầu tài khoản trẻ không thuộc nhóm Administrators (F5); BIOS/BitLocker nằm ngoài phạm vi ứng dụng.", "Chấp nhận rủi ro ở tầng hệ điều hành."],
        ["7. Khởi động từ USB / Live OS", "Boot hệ điều hành khác từ USB để bỏ qua Windows.", "Nằm ngoài phạm vi phần mềm trên Windows; cần khóa thứ tự boot trong UEFI/BIOS.", "Chấp nhận rủi ro ở tầng phần cứng."],
        ["8. Tài khoản Windows khác", "Đăng nhập bằng user Windows khác trên cùng máy.", "OGK-Service chạy dưới LocalSystem cho toàn máy; SessionAgentLauncher dùng WTSEnumerateSessions gắn Tray UI vào phiên đang hoạt động.", "Đã cài đặt trong session_launcher.py."],
        ["9. Kết thúc tiến trình (Task Manager)", "Dùng Task Manager / taskkill tắt OGK-Tray hoặc OGK-Service.", "Trẻ dùng Standard User không tắt được Service LocalSystem. Nếu tắt Tray UI, SessionAgentLauncher tự bật lại trong 3 giây; lỗi 3 lần sẽ về UNPROTECTED_HALT.", "Đã kiểm thử guardrail trong test_agent_lifecycle.py."],
    ]
    story.append(make_table(m3_table, [3.2 * cm, 4.2 * cm, 5.8 * cm, 4.1 * cm], styles))

    # ==================== M4 ====================
    story.append(Paragraph("M4. Đo Hiệu Năng (Tối Thiểu 30 Mẫu Mỗi Phép Đo)", styles["H1"]))
    story.append(
        Paragraph(
            "Phương pháp đo: Sử dụng tests/benchmark_m4.py chạy 30 mẫu liên tục cho mỗi hạng mục. CPU (%) và RAM RSS (MB) đo bằng psutil.Process(); "
            "độ trễ DNS đo thời gian phản hồi từ lúc gửi truy vấn đến khi nhận gói DNS trả về; độ trễ lệnh khẩn đo thời gian xử lý LOCK_NOW.",
            styles["Body"],
        )
    )
    m4 = load_benchmark_tables()
    story.append(Paragraph(m4["meta"], styles["Body"]))
    for title, rows in m4["tables"]:
        story.append(Paragraph(title, styles["Body"]))
        story.append(make_table(rows, [5.4 * cm, 1.6 * cm, 1.6 * cm, 1.6 * cm, 1.6 * cm, 1.6 * cm, 2.4 * cm, 1.6 * cm], styles))
    story.append(
        Paragraph(
            "Ghi chú: bảng được đọc trực tiếp từ docs/benchmark_m4_results.md do tests/benchmark_m4.py sinh ra. "
            "Chạy lại benchmark rồi chạy lại script này để cập nhật số liệu.",
            styles["Body"],
        )
    )

    # ==================== M5 & M6 ====================
    story.append(Paragraph("M5. Khả Năng Chịu Lỗi (3 Kịch Bản)", styles["H1"]))
    m5_table = [
        ["Kịch bản sự cố", "Hành vi mong đợi & cài đặt thực tế", "Thời gian phục hồi"],
        ["1. Mất mạng LAN / Internet", "Agent chuyển chế độ ngoại tuyến, tiếp tục áp dụng chính sách từ agent.db, đếm giờ bằng monotonic clock và đệm sự kiện vào event_queue với idempotency_key.", "Tức thì (0s); đồng bộ lô ngay khi có mạng."],
        ["2. Máy chủ OGK-Server ngừng hoạt động", "Agent tiếp tục bảo vệ cục bộ; nếu mất kết nối quá N = 7 ngày, áp dụng Graded Fail-Open (ADR-01): mở giới hạn giờ học tập nhưng giữ lọc DNS độc hại.", "Tự động đồng bộ lại ở nhịp tim 60s tiếp theo khi server bật lại."],
        ["3. OGK-Agent / OGK-Tray bị kết thúc", "OGK-Service được Windows SCM phục hồi tự động; nếu OGK-Tray bị tắt, SessionAgentLauncher khởi chạy lại; thất bại 3 lần chuyển UNPROTECTED_HALT và nhả DNS.", "<= 3 giây đối với Tray UI."],
    ]
    story.append(make_table(m5_table, [4.2 * cm, 9.1 * cm, 4.0 * cm], styles))

    story.append(Paragraph("M6. Đồng Bộ Thời Gian & Chống Chỉnh Đồng Hồ (3 Lớp)", styles["H1"]))
    story.append(
        Paragraph(
            "1. Lớp 1 (Khi máy đang chạy): ScreenTimeManager tính thời gian trôi qua bằng time.monotonic(), miễn nhiễm với việc chỉnh giờ hệ thống. Mỗi giây Agent so bước nhảy của giờ hệ thống với GetTickCount64 (đồng hồ khởi động, vẫn chạy khi máy ngủ nên không báo nhầm khi laptop thức dậy); lệch quá 60 giây (tiến hoặc lùi) được coi là chỉnh tay: độ lệch cộng vào wall_offset_sec để việc sang ngày mới, ngày thường/cuối tuần và lịch 7x48 vẫn dùng giờ thật, đồng thời ghi sự kiện quota_warning với subject clock_tamper.\n"
            "2. Lớp 2 (Khi khởi động lại ngoại tuyến): Lưu dấu thời gian last_wall_clock_utc vào agent.db; nếu phát hiện thời gian hiện tại nhỏ hơn mốc đã lưu, Agent ghi nhận hành vi chỉnh đồng hồ và không giảm quota đã dùng.\n"
            "3. Lớp 3 (Đối chiếu máy chủ): Mỗi nhịp tim 60 giây, máy chủ trả về server_utc; nếu độ lệch |server_utc - agent_utc| > 120 giây (CLOCK_DRIFT_WARN_SEC), Dashboard hiển thị cảnh báo lệch đồng hồ trên thẻ thiết bị và Agent lấy giờ máy chủ làm giờ tin cậy.",
            styles["Body"],
        )
    )

    doc.build(story)
    return OUT_PATH


if __name__ == "__main__":
    path = build_pdf()
    print(f"Generated: {path}")
