"""Generator for docs/BaoCao.docx, the main project report for EC - Echo Kiddo (20-30 pages).

Facts come from the code and from generated artefacts, not from memory:
  - M4 numbers are parsed from docs/benchmark_m4_results.md (tests/benchmark_m4.py);
  - the test count comes from `pytest --collect-only`.
Member names, student IDs and contribution percentages stay as placeholders for the team.

Run:  python scripts/gen_baocao.py
"""
import re
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT_DIR / "docs" / "BaoCao.docx"
BENCH_MD = ROOT_DIR / "docs" / "benchmark_m4_results.md"

GREEN = RGBColor(0x0B, 0x6B, 0x50)
GREEN_DEEP = RGBColor(0x07, 0x4A, 0x38)
INK = RGBColor(0x14, 0x21, 0x1C)


# ----------------------------------------------------------------------------- helpers
def set_cell_shading(cell, fill_hex: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    tc_pr.append(shd)


def configure_styles(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    normal.font.size = Pt(13)
    normal.paragraph_format.line_spacing = 1.2
    normal.paragraph_format.space_after = Pt(6)

    for level, size, color in [("Heading 1", 16, GREEN), ("Heading 2", 14, GREEN_DEEP), ("Heading 3", 13, INK)]:
        st = doc.styles[level]
        st.font.name = "Times New Roman"
        st.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = color
        st.paragraph_format.space_before = Pt(14 if level == "Heading 1" else 10)
        st.paragraph_format.space_after = Pt(6)
        st.paragraph_format.keep_with_next = True

    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(1.1)
        section.right_margin = Inches(0.8)


def add_page_number_footer(doc: Document) -> None:
    p = doc.sections[0].footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)


def add_toc(doc: Document) -> None:
    """Word table-of-contents field; Word fills it on open (F9 / Update field)."""
    p = doc.add_paragraph()
    run = p.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = 'TOC \\o "1-2" \\h \\z \\u'
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    txt = OxmlElement("w:t")
    txt.text = "Nhấn chuột phải vào đây và chọn Update Field để hiển thị mục lục."
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for el in (begin, instr, sep, txt, end):
        run._r.append(el)


def para(doc: Document, text: str, bold_lead: str | None = None) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if bold_lead:
        p.add_run(bold_lead).bold = True
    p.add_run(text)


def add_table(doc: Document, headers: list[str], rows: list[list[str]], widths: list[float] | None = None) -> None:
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for idx, text in enumerate(headers):
        cell = table.rows[0].cells[idx]
        cell.text = text
        set_cell_shading(cell, "0B6B50")
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
                r.font.size = Pt(10.5)
                r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for r_idx, row_data in enumerate(rows):
        for c_idx, val in enumerate(row_data):
            cell = table.rows[r_idx + 1].cells[c_idx]
            cell.text = str(val)
            set_cell_shading(cell, "EDF6F2" if r_idx % 2 == 1 else "FFFFFF")
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.line_spacing = 1.1
                for r in p.runs:
                    r.font.size = Pt(10.5)
    if widths:
        for row in table.rows:
            for idx, w in enumerate(widths):
                row.cells[idx].width = Inches(w)
    doc.add_paragraph("")


def add_caption(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text)
    r.italic = True
    r.font.size = Pt(11)


def add_code_block(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.2)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.0
    run = p.add_run(text)
    run.font.name = "Consolas"
    run.font.size = Pt(9)


def add_bullets(doc: Document, items: list[str]) -> None:
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        if ": " in item and item.index(": ") < 60:
            lead, rest = item.split(": ", 1)
            p.add_run(lead + ": ").bold = True
            p.add_run(rest)
        else:
            p.add_run(item)


def add_numbered(doc: Document, items: list[str]) -> None:
    for item in items:
        p = doc.add_paragraph(style="List Number")
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.add_run(item)


def load_benchmark_tables() -> tuple[list[str], list[tuple[str, list[list[str]]]]]:
    if not BENCH_MD.exists():
        return ["Chưa có docs/benchmark_m4_results.md: chạy python tests/benchmark_m4.py."], []
    meta, tables, title, rows = [], [], "", []
    for ln in BENCH_MD.read_text(encoding="utf-8").splitlines() + [""]:
        if ln.startswith("- "):
            meta.append(ln[2:].replace("`", ""))
        elif ln.startswith("## "):
            title = ln[3:].strip()
        elif ln.startswith("|"):
            cells = [c.strip().replace("`", "") for c in ln.strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                rows.append(cells)
        elif rows:
            tables.append((title, rows))
            rows = []
    return meta, tables


def collected_test_count() -> str:
    try:
        out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"],
                             cwd=ROOT_DIR, capture_output=True, text=True, timeout=180).stdout
        m = re.search(r"(\d+) tests? collected", out)
        return m.group(1) if m else "?"
    except Exception:
        return "?"


# ----------------------------------------------------------------------------- report
def build_report() -> Path:
    doc = Document()
    configure_styles(doc)
    add_page_number_footer(doc)
    n_tests = collected_test_count()
    bench_meta, bench_tables = load_benchmark_tables()

    # ======================= COVER =======================
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("[ĐIỀN TÊN TRƯỜNG]\n[ĐIỀN TÊN KHOA]\n")
    r.bold = True
    r.font.size = Pt(14)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("\nĐỒ ÁN MÔN HỌC MẠNG MÁY TÍNH\n")
    r.bold = True
    r.font.size = Pt(15)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("\nXÂY DỰNG ỨNG DỤNG HỖ TRỢ QUẢN LÝ\nVIỆC SỬ DỤNG MÁY TÍNH CỦA TRẺ EM\n")
    r.bold = True
    r.font.size = Pt(20)
    r.font.color.rgb = GREEN
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run('EC - Echo Kiddo\n"Công cụ đồng hành, không phải phần mềm theo dõi lén"\n\n')
    r.italic = True
    r.font.size = Pt(14)
    add_table(doc, ["Vai trò", "Họ và tên", "MSSV"], [
        ["Sinh viên 1", "[ĐIỀN HỌ TÊN THÀNH VIÊN 1]", "[ĐIỀN MSSV 1]"],
        ["Sinh viên 2", "[ĐIỀN HỌ TÊN THÀNH VIÊN 2]", "[ĐIỀN MSSV 2]"],
        ["Sinh viên 3", "[ĐIỀN HỌ TÊN THÀNH VIÊN 3]", "[ĐIỀN MSSV 3]"],
        ["Giảng viên hướng dẫn", "[ĐIỀN TÊN GIẢNG VIÊN]", "-"],
    ], [2.0, 3.0, 1.5])
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("\nThành phố Hồ Chí Minh, tháng 11 năm 2026")
    doc.add_page_break()

    # ======================= FRONT MATTER =======================
    doc.add_heading("LỜI MỞ ĐẦU", level=1)
    para(doc,
         "Máy tính đã trở thành công cụ học tập quen thuộc của học sinh tiểu học: làm bài tập trực tuyến, tra cứu, học lập trình "
         "kéo thả, xem bài giảng. Cùng với lợi ích đó là những lo lắng rất cụ thể của cha mẹ: con ngồi máy quá lâu, chơi game "
         "vào giờ ngủ, vô tình vào những trang không phù hợp lứa tuổi. Phần lớn công cụ trên thị trường giải quyết lo lắng này "
         "bằng cách giám sát: chụp màn hình định kỳ, ghi lại phím gõ, đọc lịch sử duyệt web đầy đủ, chạy ẩn để trẻ không biết.")
    para(doc,
         "Nhóm chọn một hướng khác, đúng với tinh thần đề bài: một công cụ đồng hành. EC - Echo Kiddo giới hạn thời gian và chặn nội dung "
         "không phù hợp ở tầng hệ thống và mạng, nhưng không bao giờ chạy ẩn, không đọc nội dung, chỉ ghi đúng bảy trường dữ liệu "
         "và cho trẻ xem chính xác những gì cha mẹ xem. Báo cáo này trình bày kiến trúc, giao thức, cách hiện thực từng chức năng, "
         "kết quả kiểm thử và đo đạc, cùng những giới hạn mà nhóm chấp nhận một cách có chủ đích.")
    para(doc,
         "Phần kỹ thuật mạng chi tiết (M1 đến M6: luồng gói tin, so sánh phương án chặn, phân tích đường vòng, đo hiệu năng, "
         "chịu lỗi, đồng bộ thời gian) được trình bày đầy đủ trong phụ lục docs/BaoCaoKyThuatMang.pdf; Chương 5 của báo cáo này "
         "tóm tắt các kết quả chính.")

    doc.add_heading("MỤC LỤC", level=1)
    add_toc(doc)
    doc.add_page_break()

    doc.add_heading("DANH MỤC TỪ VIẾT TẮT", level=1)
    add_table(doc, ["Viết tắt", "Ý nghĩa"], [
        ["EC", "Echo Kiddo, tên hệ thống"],
        ["DNS", "Domain Name System, hệ thống phân giải tên miền"],
        ["DoH / DoT", "DNS-over-HTTPS / DNS-over-TLS"],
        ["eTLD+1", "Tên miền cấp hai tính theo danh sách hậu tố công khai (vd. school.edu.vn)"],
        ["HMAC", "Hash-based Message Authentication Code, mã xác thực thông điệp dựa trên hàm băm"],
        ["IPC", "Inter-Process Communication, giao tiếp liên tiến trình"],
        ["JWT", "JSON Web Token"],
        ["WAL", "Write-Ahead Logging, chế độ ghi nhật ký trước của SQLite"],
        ["WTS", "Windows Terminal Services API, dùng để mở tiến trình trong phiên người dùng"],
        ["IDOR", "Insecure Direct Object Reference, truy cập trực tiếp đối tượng không được phép"],
        ["CSRF", "Cross-Site Request Forgery, giả mạo yêu cầu liên trang"],
        ["STRIDE", "Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege"],
        ["ASVS", "OWASP Application Security Verification Standard"],
        ["ADR", "Architecture Decision Record, bản ghi quyết định kiến trúc"],
        ["TTL", "Time To Live, thời gian sống của bản ghi DNS trong bộ đệm"],
    ], [1.6, 4.9])
    doc.add_page_break()

    # ======================= CHAPTER 1 =======================
    doc.add_heading("CHƯƠNG 1. TỔNG QUAN ĐỀ TÀI", level=1)

    doc.add_heading("1.1. Bối cảnh và đặt vấn đề", level=2)
    para(doc,
         "Trẻ 6 đến 11 tuổi dùng máy tính chủ yếu cho việc học, nhưng chưa tự điều chỉnh được thời lượng và chưa nhận diện được "
         "nội dung không phù hợp. Cha mẹ thường không ở cạnh con suốt thời gian con dùng máy. Nhu cầu vì vậy rất rõ: đặt giới hạn "
         "thời gian, khung giờ được dùng, chặn ứng dụng và trang web không phù hợp, và nhận được báo cáo ngắn gọn.")
    para(doc,
         "Vấn đề nằm ở cách đáp ứng nhu cầu đó. Một hệ thống chạy ẩn, chụp màn hình và đọc tin nhắn sẽ làm tổn hại lòng tin trong "
         "gia đình, vi phạm quyền riêng tư của trẻ được Luật Trẻ em 2016 bảo vệ, và có thể bị lạm dụng để theo dõi người lớn. "
         "Nghị định 13/2023/NĐ-CP còn yêu cầu dữ liệu cá nhân của trẻ chỉ được xử lý khi có sự đồng ý của cha mẹ, đúng mục đích "
         "và ở mức tối thiểu. Đề bài đặt ra yêu cầu kép: kiểm soát phải có hiệu lực thật ở tầng hệ thống và mạng, đồng thời "
         "phải minh bạch tuyệt đối với trẻ.")

    doc.add_heading("1.2. Mục tiêu của đồ án", level=2)
    add_bullets(doc, [
        "Kiểm soát thời gian: hạn mức riêng ngày thường và cuối tuần, lịch tuần độ phân giải 30 phút, đếm thời gian dùng thực, cảnh báo trước và chống chỉnh đồng hồ.",
        "Lọc nội dung: chặn ứng dụng theo tên kèm mã băm SHA-256, lọc tên miền bằng DNS proxy cục bộ 127.0.0.1:53, phân loại 6 nhóm, cưỡng chế SafeSearch.",
        "Quản trị từ xa: thay đổi trên dashboard có hiệu lực trên máy trẻ trong 60 giây, lệnh khẩn trong 5 giây, chính sách có phiên bản và chữ ký HMAC.",
        "Minh bạch: lược đồ sự kiện 7 trường, màn hình cho trẻ và nhật ký kiểm toán trẻ xem được, xóa dữ liệu theo yêu cầu, tự xóa sau 90 ngày.",
        "Bảo mật: Argon2id, phiên an toàn, chống CSRF và IDOR, TLS kèm ghim chứng chỉ, mã hóa trường nhạy cảm, mô hình mối đe dọa STRIDE.",
        "Kỹ thuật mạng: phân tích đường đi gói tin, so sánh phương án chặn, phân tích 9 kỹ thuật vượt rào, đo hiệu năng tối thiểu 30 mẫu, chịu lỗi và đồng bộ thời gian.",
    ])

    doc.add_heading("1.3. Triết lý thiết kế và tuân thủ pháp lý", level=2)
    para(doc, 'Toàn bộ thiết kế bám theo câu "Công cụ đồng hành, không phải phần mềm theo dõi lén", cụ thể hóa thành bốn nguyên tắc sản phẩm:')
    add_numbered(doc, [
        "Minh bạch trước: mọi thứ phụ huynh thấy thì trẻ cũng xem được, trên màn hình /child-view và nhật ký /audit/view.",
        "Thu ít dữ liệu nhất có thể: chỉ 7 trường, trường nào không giải thích được mục đích thì bỏ (bảng ánh xạ trong docs/PRIVACY.md).",
        "Chặn luôn kèm lời giải thích: khi chặn ứng dụng hay tên miền, khay hệ thống hiện cửa sổ nêu lý do, không chặn im lặng.",
        "Mọi thay đổi trên máy trẻ đều hoàn tác được: DNS card mạng và registry trình duyệt được chụp snapshot và khôi phục sạch khi dừng dịch vụ hoặc gỡ cài đặt.",
    ])
    add_table(doc, ["Căn cứ pháp lý", "Yêu cầu liên quan", "Cách EC - Echo Kiddo đáp ứng"], [
        ["Nghị định 13/2023/NĐ-CP", "Có sự đồng ý của cha mẹ khi xử lý dữ liệu trẻ em; tối thiểu hóa; quyền xóa", "Hộp xác nhận đồng ý bắt buộc trước khi tạo mã ghép đôi, ghi vào audit log; 7 trường; nút xóa toàn bộ dữ liệu; tự xóa sau 90 ngày"],
        ["Luật Trẻ em 2016", "Quyền bí mật đời sống riêng tư của trẻ", "Không chụp màn hình, không keylogger, không đọc DOM/tin nhắn; subject chỉ là tên exe hoặc eTLD+1"],
        ["Yêu cầu chống lạm dụng của đề bài", "Không có chế độ ẩn; không hiện được biểu tượng thì tự dừng", "SessionAgentLauncher thử bật khay 3 lần, thất bại thì Service chuyển UNPROTECTED_HALT: nhả DNS, dừng chặn"],
    ], [1.6, 2.2, 2.7])

    doc.add_heading("1.4. Khảo sát các cách tiếp cận hiện có", level=2)
    para(doc,
         "Nhóm khảo sát các nhóm giải pháp thường gặp theo cách chúng vận hành, không đánh giá sản phẩm thương mại cụ thể. "
         "Mục tiêu là xác định chỗ EC - Echo Kiddo cần khác biệt.")
    add_table(doc, ["Cách tiếp cận", "Ưu điểm", "Nhược điểm so với yêu cầu đề bài"], [
        ["Sửa tệp hosts bằng tay", "Không cần phần mềm, không tốn tài nguyên", "Không chặn tên miền con theo wildcard, không có thời gian, không báo cáo, trẻ có quyền admin là sửa được"],
        ["Bộ lọc DNS trên router hoặc dịch vụ DNS công cộng có lọc", "Áp dụng cho cả mạng gia đình", "Không phân biệt từng trẻ, không biết ứng dụng nào đang chạy, mang máy ra quán cà phê là mất tác dụng"],
        ["Phần mềm giám sát chạy ẩn", "Thu thập rất nhiều thông tin", "Vi phạm quyền riêng tư, dễ thành stalkerware, đúng loại sản phẩm đề bài cấm"],
        ["Tính năng gia đình của hệ điều hành", "Tích hợp sẵn, ổn định", "Phụ thuộc tài khoản đám mây của nhà cung cấp, khó tùy biến phân loại và khó làm minh bạch cho trẻ theo yêu cầu đồ án"],
        ["EC - Echo Kiddo (đồ án này)", "Agent cục bộ + DNS proxy + máy chủ tự host, minh bạch hai chiều", "Không lọc theo đường dẫn URL, chưa có bộ lọc WFP (trình bày ở mục 5.2)"],
    ], [1.7, 2.0, 2.8])

    doc.add_heading("1.5. Phạm vi và ngăn xếp công nghệ", level=2)
    add_table(doc, ["Thành phần", "Công nghệ", "Vai trò"], [
        ["EC Agent, Service", "Python 3.11+, pywin32, psutil, dnslib, asyncio, SQLite", "Đếm thời gian, kiểm soát tiến trình, DNS proxy 127.0.0.1:53, đồng bộ với máy chủ"],
        ["EC Agent, Tray UI", "pystray, Tkinter, Named Pipe", "Đồng hồ còn lại, cảnh báo 10/5/1 phút, ân hạn 60 giây, xin thêm giờ, giải thích lý do chặn"],
        ["EC Server", "FastAPI, Uvicorn, SQLAlchemy 2.0, SQLite WAL, Argon2id, websockets", "Xác thực, ghép đôi, ký chính sách HMAC, nhận sự kiện, phát lệnh khẩn"],
        ["Web Dashboard", "Jinja2, HTML/CSS/JavaScript thuần, không thư viện ngoài", "Cấu hình từ xa trên máy tính và điện thoại, biểu đồ, duyệt yêu cầu"],
        ["Kiểm thử", "pytest, pytest-asyncio, httpx ASGITransport, TestClient", f"{n_tests} ca kiểm thử tự động (unit + tích hợp đầu-cuối)"],
    ], [1.6, 2.4, 2.5])
    para(doc,
         "Ngoài phạm vi: lọc theo đường dẫn URL (cần proxy HTTPS và cài chứng chỉ gốc vào máy trẻ, mâu thuẫn với nguyên tắc tối thiểu "
         "can thiệp), macOS/Linux, và phân loại nội dung bằng học máy.")

    doc.add_heading("1.6. Ánh xạ yêu cầu đề bài", level=2)
    add_table(doc, ["Mã", "Yêu cầu (mức)", "Hiện thực chính", "Kiểm chứng"], [
        ["F1", "Hạn mức ngày thường/cuối tuần (BẮT BUỘC)", "screen_time.py, policy daily_limit_*", "test_agent_core, kịch bản tích hợp 3"],
        ["F1", "Lịch 7x48 (BẮT BUỘC)", "schedule_matrix_7x48, is_slot_allowed_by_matrix", "test_agent_core"],
        ["F1", "Đếm thời gian thực, idle > 5 phút (BẮT BUỘC)", "GetLastInputInfo, WTS session lock", "test_agent_core"],
        ["F1", "Cảnh báo 10/5/1 phút, ân hạn 60 giây (BẮT BUỘC)", "evaluate_lock_status, tray_app", "test_phase1_policy_sync, demo"],
        ["F1", "Chống chỉnh đồng hồ (BẮT BUỘC)", "monotonic + last_wall_clock_utc + server_utc", "test_agent_core"],
        ["F1", "Ngân sách theo nhóm (NÊN CÓ)", "category_budgets_json", "test_agent_core"],
        ["F2", "Danh sách ứng dụng + SHA-256 (BẮT BUỘC)", "app_controller.py, PE OriginalFileName", "test_agent_core (đổi tên exe)"],
        ["F2", "Chặn kèm giải thích (BẮT BUỘC)", "recent_blocks -> show_block_explanation", "test_phase1_policy_sync"],
        ["F2", "DNS proxy 127.0.0.1:53, tên miền con (BẮT BUỘC)", "dns_proxy.py, SuffixTrie", "test_dns_proxy (50 chặn, 20 giáo dục)"],
        ["F2", "6 nhóm, >= 200 mục (BẮT BUỘC)", "seeds/domain_catalog.json (235 mục)", "test_seed_catalog"],
        ["F2", "SafeSearch bằng DNS (BẮT BUỘC)", "SAFESEARCH_MAP, CNAME", "test_dns_proxy, nslookup"],
        ["F2", "Đối phó DoH, khóa DNS card (NÊN CÓ)", "DoH canary/endpoint, BrowserPolicyGuard, NetworkDnsGuard", "test_dns_proxy, M3"],
        ["F3", "Lược đồ 7 trường, 9 loại (BẮT BUỘC)", "schemas/event.py, event_buffer.py", "test_schemas"],
        ["F3", "Dashboard, màn hình trẻ (BẮT BUỘC)", "dashboard.html, child_view.html, reports.py", "test_web_dashboard"],
        ["F3", "90 ngày, nút xóa (BẮT BUỘC)", "retention worker, PURGE_DATA", "kịch bản tích hợp 5"],
        ["F3", "Xuất CSV (NÊN CÓ)", "/api/v1/reports/export/csv", "test_server_api"],
        ["F4", "1:n:m, 60 giây / 5 giây (BẮT BUỘC)", "models, heartbeat, WebSocket", "benchmark M4 đầu-cuối"],
        ["F4", "Phiên bản + HMAC (BẮT BUỘC)", "policy_service.py, policy_verifier.py", "test_phase1_policy_sync"],
        ["F4", "Nhật ký kiểm toán trẻ xem được (BẮT BUỘC)", "audit_logs, /audit/view", "test_web_dashboard"],
        ["F4", "Gỡ cài có PIN, tạm nghỉ 2 giờ (NÊN CÓ / CÓ THÌ TỐT)", "ogk_cleanup.py, PARENT_PAUSE_2H", "test_agent_lifecycle"],
        ["F5", "Bảo mật (BẮT BUỘC)", "Xem Chương 6", "test_server_api, test_agent_db, test_phase1"],
    ], [0.5, 2.2, 2.1, 1.7])
    doc.add_page_break()

    # ======================= CHAPTER 2 =======================
    doc.add_heading("CHƯƠNG 2. KIẾN TRÚC HỆ THỐNG", level=1)

    doc.add_heading("2.1. Sơ đồ tổng thể", level=2)
    para(doc,
         "EC - Echo Kiddo theo mô hình client-server. Trên máy trẻ chạy EC Agent; máy chủ EC Server đặt trong mạng LAN hoặc một VPS phòng lab. "
         "Phụ huynh dùng trình duyệt (máy tính hoặc điện thoại) truy cập dashboard do chính EC Server phục vụ.")
    add_code_block(doc,
        "MÁY CỦA TRẺ (Windows 10/11)                           MÁY CHỦ (LAN / VPS lab)\n"
        "+--------------------------------------+   HTTPS     +--------------------------------+\n"
        "| EC Service (Session 0, LocalSystem) |  TLS 1.2+   | EC Server (FastAPI + Uvicorn) |\n"
        "|  ScreenTimeManager (monotonic)       |<----------->|  /auth /enroll /policy         |\n"
        "|  AppController (SHA-256 + PE header) | heartbeat   |  /events /commands /heartbeat  |\n"
        "|  DnsProxyServer 127.0.0.1:53 UDP/TCP |   60 s      |  /reports /audit /ws/agent     |\n"
        "|  NetworkDnsGuard, BrowserPolicyGuard |             |  CommandHub (WebSocket)        |\n"
        "|  AgentServerClient (pinning)         |  WSS lệnh   +---------------+----------------+\n"
        "|  agent.db (ProgramData, AES-GCM)     |  khẩn < 5 s | SQLite WAL + SQLAlchemy 2.0    |\n"
        "+------------------^-------------------+             +---------------^----------------+\n"
        "                   | Named Pipe \\\\.\\pipe\\OGKServicePipe                | HTTPS\n"
        "+------------------v-------------------+             +---------------+----------------+\n"
        "| EC Tray (phiên người dùng)          |             | Web Dashboard (Jinja2 + JS)    |\n"
        "|  đồng hồ, cảnh báo, xin thêm giờ,    |             |  phụ huynh / màn hình của trẻ  |\n"
        "|  cửa sổ giải thích lý do chặn        |             |  / nhật ký kiểm toán           |\n"
        "+--------------------------------------+             +--------------------------------+")
    add_caption(doc, "Hình 2.1. Kiến trúc tổng thể của EC - Echo Kiddo")

    doc.add_heading("2.2. Tách hai tiến trình trên máy trẻ", level=2)
    para(doc,
         "Windows cô lập dịch vụ trong Session 0 (Session 0 Isolation): một dịch vụ chạy LocalSystem không thể vẽ cửa sổ lên màn hình "
         "của người dùng. Vì vậy agent tách thành hai tiến trình. EC Service giữ toàn bộ quyền và logic thực thi; EC Tray chạy "
         "với quyền của trẻ, chỉ hiển thị và gửi yêu cầu. Service dùng WTSEnumerateSessions để tìm phiên đang hoạt động, lấy token "
         "người dùng và gọi CreateProcessAsUser để bật Tray trong đúng phiên đó (agent/service/session_launcher.py).")
    para(doc,
         "Cách tách này cũng là một ranh giới bảo mật: Tray không có quyền gì đáng kể, nên dù trẻ tắt hay sửa Tray thì luật vẫn do "
         "Service quyết định. Ngược lại, vì không được chạy ẩn, Service theo dõi Tray: Tray bị tắt thì bật lại; thử 3 lần không hiện "
         "được thì Service tự chuyển UNPROTECTED_HALT, nhả DNS và dừng chặn, thay vì tiếp tục kiểm soát mà trẻ không nhìn thấy.")

    doc.add_heading("2.3. Trách nhiệm các thành phần", level=2)
    add_table(doc, ["Thành phần", "Mã nguồn", "Trách nhiệm"], [
        ["Windows Service", "agent/service/win_service.py", "Vòng lặp thực thi: đánh giá khóa, quét tiến trình, nạp chính sách, trả trạng thái cho Tray; lệnh CLI run và enroll"],
        ["Session Launcher", "agent/service/session_launcher.py", "Bật Tray trong phiên người dùng, giám sát và áp dụng guardrail UNPROTECTED_HALT"],
        ["Bộ đếm giờ", "agent/core/screen_time.py", "Hạn mức, lịch 7x48, idle, cảnh báo, ân hạn, ngân sách nhóm, chống chỉnh giờ, Graded Fail-Open"],
        ["Kiểm soát ứng dụng", "agent/core/app_controller.py", "Quét psutil, đối chiếu tên + SHA-256 + OriginalFileName, kết thúc tiến trình vi phạm"],
        ["DNS proxy", "agent/dns/dns_proxy.py, domain_engine.py", "Phân giải có lọc trên 127.0.0.1:53, Suffix Trie, SafeSearch, chặn DoH, cache TTL, failover upstream"],
        ["Bảo vệ cấu hình", "agent/platform/network_guard.py, browser_policy.py", "Khóa DNS card mạng về 127.0.0.1, tắt DoH trình duyệt qua registry, snapshot và khôi phục"],
        ["IPC", "agent/ipc/pipe_protocol.py", "Named Pipe, gói tin có tiền tố độ dài 4 byte, kiểm tra SID người gọi và challenge token"],
        ["Đồng bộ", "agent/sync/server_client.py", "Ghép đôi, nhịp tim, tải sự kiện theo lô, kéo chính sách, WebSocket lệnh khẩn, ghim chứng chỉ"],
        ["Kho cục bộ", "agent/core/agent_db.py, field_crypto.py", "Chính sách đệm, hàng đợi sự kiện, trạng thái ngày, snapshot, định danh thiết bị (mã hóa AES-GCM)"],
        ["Máy chủ", "server/main.py, routers/*, services/*", "Xác thực, mô hình 1:n:m, ký chính sách, nhận sự kiện, báo cáo, audit, CommandHub"],
        ["Dashboard", "dashboard/templates/*, static/app.js", "Giao diện phụ huynh, màn hình của trẻ, nhật ký kiểm toán, đăng nhập"],
    ], [1.4, 2.2, 2.9])

    doc.add_heading("2.4. Mô hình dữ liệu", level=2)
    para(doc, "Máy chủ dùng SQLite ở chế độ WAL (đọc đồng thời trong khi ghi) với 7 bảng, quan hệ 1 phụ huynh : n trẻ : m thiết bị:")
    add_table(doc, ["Bảng", "Trường chính", "Ghi chú"], [
        ["users", "id, email, password_hash, role, failed_login_count, locked_until_utc", "Ba vai trò parent, child-view, admin; Argon2id; khóa 15 phút sau 5 lần sai"],
        ["children", "id, parent_id, display_name, age_group", "Một phụ huynh nhiều trẻ"],
        ["devices", "id, child_id, device_name, fingerprint_hash, refresh_token_hash, token_revoked, applied_policy_version, last_heartbeat_utc, last_clock_drift_sec", "Một trẻ nhiều máy; chỉ lưu băm SHA-256 của refresh token; danh sách thu hồi"],
        ["pairing_codes", "code, parent_id, child_id, consent_confirmed, expires_at_utc, used_at_utc", "Mã 8 ký tự, hạn 10 phút, dùng một lần"],
        ["policies", "child_id, version, daily_limit_*, schedule_matrix_7x48, *_json, updated_at_utc, signature, offline_pin_hash", "Mỗi lần sửa tăng version và ký lại"],
        ["events", "idempotency_key, ts, device_id, child_id, type, subject, duration_sec, policy_id", "Đúng 7 trường nghiệp vụ + khóa chống trùng"],
        ["audit_logs", "actor_id, actor_role, child_id, ip_address, action, old_value_json, new_value_json, ts_utc", "Nhật ký kiểm toán NT5"],
    ], [1.2, 3.0, 2.3])
    para(doc, "Trên máy trẻ, agent.db đặt trong C:\\ProgramData\\OGK (ACL chỉ SYSTEM và Administrators được ghi) gồm 5 bảng:")
    add_table(doc, ["Bảng", "Mục đích"], [
        ["cached_policy", "Bản chính sách đã ký gần nhất, được xác minh lại HMAC mỗi lần khởi động để chạy ngoại tuyến"],
        ["event_queue", "Hàng đợi sự kiện chờ đồng bộ, mỗi sự kiện có idempotency_key (UUID)"],
        ["daily_usage_state", "Số giây đã dùng trong ngày, last_wall_clock_utc, mốc monotonic để phát hiện chỉnh giờ"],
        ["system_snapshots", "Cấu hình DNS card mạng và registry trình duyệt trước khi EC - Echo Kiddo sửa, để khôi phục sạch"],
        ["device_credentials", "device_id, child_id, token truy cập và làm mới, khóa HMAC chính sách (ba trường bí mật mã hóa AES-256-GCM)"],
    ], [1.6, 4.9])

    doc.add_heading("2.5. Giao diện lập trình (REST API và WebSocket)", level=2)
    add_table(doc, ["Phương thức và đường dẫn", "Người gọi", "Chức năng"], [
        ["POST /api/v1/auth/register, /login, /logout", "Phụ huynh", "Đăng ký, đăng nhập (Argon2id, rate limit), hủy phiên"],
        ["POST /api/v1/auth/device/refresh", "Agent", "Đổi refresh token lấy access token 15 phút"],
        ["POST /api/v1/children", "Phụ huynh", "Tạo hồ sơ trẻ"],
        ["POST /api/v1/enroll/code", "Phụ huynh", "Tạo mã ghép đôi (bắt buộc consent_confirmed)"],
        ["POST /api/v1/enroll", "Agent", "Ghép đôi bằng mã, nhận device_id, token và chính sách đã ký"],
        ["POST /api/v1/heartbeat", "Agent", "Nhịp tim 60 giây, nhận server_utc, phiên bản chính sách mới nhất, lệnh chờ"],
        ["GET /api/v1/policy", "Agent", "Lấy chính sách đã ký của trẻ gắn với thiết bị"],
        ["GET, PUT /api/v1/policy/{child_id}", "Phụ huynh", "Xem, sửa chính sách (tăng version, ký lại, đẩy POLICY_UPDATED)"],
        ["POST /api/v1/events/batch", "Agent", "Tải sự kiện theo lô, bỏ qua bản ghi trùng idempotency_key"],
        ["DELETE /api/v1/privacy/children/{id}/events", "Phụ huynh", "Xóa toàn bộ dữ liệu của trẻ trên máy chủ và gửi PURGE_DATA"],
        ["POST /api/v1/commands", "Phụ huynh", "LOCK_NOW, UNLOCK, ADD_TIME_15M, PARENT_PAUSE_2H, PURGE_DATA"],
        ["GET /api/v1/requests/{id}, POST .../approve, .../deny", "Phụ huynh", "Duyệt hoặc từ chối yêu cầu xin thêm giờ"],
        ["POST /api/v1/devices/{id}/revoke", "Phụ huynh", "Gỡ thiết bị, thu hồi token"],
        ["GET /api/v1/reports/{id}, /export/csv", "Phụ huynh", "Báo cáo 7 ngày, xuất CSV"],
        ["GET /api/v1/audit/{child_id}", "Phụ huynh", "Nhật ký kiểm toán dạng JSON"],
        ["WS /ws/agent/{device_id}", "Agent", "Kênh lệnh khẩn, xác thực bằng access token của thiết bị"],
        ["GET /dashboard, /child-view, /audit/view, /login", "Trình duyệt", "Các trang web"],
    ], [2.6, 1.0, 2.9])
    doc.add_page_break()

    # ======================= CHAPTER 3 =======================
    doc.add_heading("CHƯƠNG 3. VÒNG ĐỜI VÀ GIAO THỨC", level=1)
    para(doc, "Mục 4.3 của đề bài yêu cầu đặc tả năm giao thức vòng đời. Mỗi giao thức dưới đây ghi rõ thông điệp, điều kiện và cách xử lý lỗi.")

    doc.add_heading("3.1. Ghép đôi (enrollment)", level=2)
    add_code_block(doc,
        "Phụ huynh (Dashboard)          EC Server                       EC Agent (máy trẻ)\n"
        "  | tick 'Tôi đồng ý...'           |                                  |\n"
        "  | POST /enroll/code ------------>| tạo mã 8 ký tự, hạn 10 phút      |\n"
        "  |   {child_id, consent:true}     | ghi audit CREATE_PAIRING_CODE    |\n"
        "  |<------------- {code} ----------|                                  |\n"
        "  | (đọc mã cho máy trẻ)           |                                  |\n"
        "  |                                |<--- POST /enroll ----------------| win_service.py enroll --code\n"
        "  |                                |  {pairing_code, device_name,     |\n"
        "  |                                |   device_fingerprint SHA-256}    |\n"
        "  |                                | kiểm tra hạn, đánh dấu đã dùng   |\n"
        "  |                                |---- {device_id, child_id, ------>| lưu agent.db (AES-GCM)\n"
        "  |                                |  access 15', refresh, policy     | verify HMAC rồi áp dụng\n"
        "  |                                |  đã ký, policy_hmac_secret}      |")
    add_caption(doc, "Hình 3.1. Trình tự ghép đôi")
    para(doc,
         "Bảng chữ của mã bỏ các ký tự dễ nhầm (0, O, 1, I), còn 32 ký tự, nên có 32^8 ≈ 1,1 × 10^12 tổ hợp; cùng hạn 10 phút, dùng "
         "một lần và rate limit, việc đoán mã là không khả thi. Bước tick đồng ý là điểm ghi nhận sự đồng ý của cha mẹ theo Nghị định "
         "13/2023 và được lưu vào nhật ký kiểm toán. Máy chủ chỉ lưu băm SHA-256 của refresh token, nên lộ CSDL máy chủ không lộ token.")

    doc.add_heading("3.2. Nhịp tim 60 giây", level=2)
    para(doc,
         "Mỗi 60 giây agent gửi POST /api/v1/heartbeat với số giây đã dùng, giờ UTC cục bộ, mốc monotonic và phiên bản chính sách "
         "đang áp dụng. Máy chủ trả server_utc, latest_policy_version và danh sách lệnh chờ. Agent dùng server_utc để đo độ lệch "
         "đồng hồ (mục 4.1.4); nếu latest_policy_version lớn hơn bản đang có, agent gọi GET /api/v1/policy ngay. Lệnh chờ trong "
         "nhịp tim là đường dự phòng cho lệnh khẩn khi WebSocket rớt; mỗi command_id chỉ thực thi một lần.")
    para(doc,
         "Khi access token hết hạn (HTTP 401), agent tự đổi refresh token rồi gửi lại. Thân yêu cầu khớp đúng lược đồ Pydantic với "
         "extra=forbid; định danh thiết bị lấy từ token, không lấy từ thân yêu cầu, nên một thiết bị không thể gửi nhịp tim thay thiết bị khác.")

    doc.add_heading("3.3. Lệnh khẩn qua WebSocket (dưới 5 giây)", level=2)
    para(doc,
         "Agent giữ kết nối WSS tới /ws/agent/{device_id}, xác thực bằng access token có sub trùng device_id. Khi phụ huynh bấm một "
         "lệnh, CommandHub tạo phong bì {command_id, command, params, issued_at_utc, signature} với chữ ký HMAC-SHA256 trên chuỗi "
         "command_id:command:issued_at:params, đẩy xuống agent và chờ COMMAND_ACK. Agent từ chối lệnh không có chữ ký hoặc sai "
         "chữ ký, nên kẻ chen giữa đường không thể tự phát lệnh UNLOCK. Mất kết nối thì agent kết nối lại theo exponential backoff "
         "(1, 2, 4... tối đa 60 giây) cộng jitter ngẫu nhiên để tránh dồn tải khi máy chủ khởi động lại.")

    doc.add_heading("3.4. Chế độ ngoại tuyến và đồng bộ theo lô", level=2)
    para(doc,
         "Khi mất mạng, agent vẫn áp dụng chính sách trong cached_policy (đã xác minh HMAC), vẫn đếm giờ và vẫn chặn. Sự kiện được "
         "ghi vào event_queue với idempotency_key là UUID sinh tại agent. Khi có mạng trở lại, agent gửi tối đa 200 sự kiện mỗi lô "
         "lên POST /api/v1/events/batch. Máy chủ có ràng buộc duy nhất trên idempotency_key: lô bị gửi lại do mất phản hồi giữa "
         "chừng sẽ không làm sự kiện bị đếm hai lần. Agent chỉ đánh dấu đã đồng bộ khi nhận HTTP 200.")

    doc.add_heading("3.5. Chính sách hết hạn: ADR-01 Graded Fail-Open sau N = 7 ngày", level=2)
    add_table(doc, ["Phương án", "Hậu quả khi mất kết nối kéo dài", "Đánh giá"], [
        ["Fail-closed (khóa máy)", "Máy chủ bảo trì hay đổi mạng là máy học của trẻ bị khóa, kể cả giờ làm bài", "Gây hại cho việc học, gia đình sẽ gỡ phần mềm"],
        ["Fail-open hoàn toàn", "Rút dây mạng 7 ngày là mất cả lọc nội dung", "Biến thành cách vượt rào dễ nhất"],
        ["Graded Fail-Open (chọn)", "Sau 7 ngày không liên lạc: nới hạn mức thời gian, giữ nguyên lọc DNS nhóm không phù hợp và SafeSearch", "Giữ lớp bảo vệ quan trọng nhất, không khóa nhầm việc học"],
    ], [1.6, 2.8, 2.1])
    para(doc,
         "Lý do chọn N = 7: đủ dài để phủ một kỳ nghỉ hay sự cố máy chủ cuối tuần, đủ ngắn để phụ huynh nhận ra máy mất liên lạc qua "
         "trạng thái \"Mất kết nối\" trên dashboard. Mốc thời gian dùng đồng hồ monotonic và lần đồng bộ thành công cuối cùng, nên "
         "chỉnh đồng hồ hệ thống không kích hoạt được fail-open sớm.")
    doc.add_page_break()

    # ======================= CHAPTER 4 =======================
    doc.add_heading("CHƯƠNG 4. THIẾT KẾ VÀ HIỆN THỰC CHỨC NĂNG", level=1)

    doc.add_heading("4.1. F1: Quản lý thời gian sử dụng", level=2)
    doc.add_heading("4.1.1. Hạn mức và lịch tuần 7x48", level=3)
    para(doc,
         "Chính sách có daily_limit_weekday_min và daily_limit_weekend_min (0 đến 1440 phút) và schedule_matrix_7x48, chuỗi 336 ký tự "
         "'0'/'1'. Ô thứ i ứng với ngày i // 48 (0 = thứ Hai) và khung 30 phút (i % 48). Ví dụ ô 2*48 + 44 = 140 là thứ Tư 22:00 đến 22:30. "
         "Cách mã hóa này gọn (336 byte), dễ ký HMAC vì là một chuỗi, và kiểm tra O(1) khi biết thời điểm. Ngoài khung cho phép, "
         "vòng lặp Service đánh giá lại mỗi giây nên máy khóa trong vòng 5 giây theo tiêu chí nghiệm thu.")
    doc.add_heading("4.1.2. Đếm thời gian dùng thực", level=3)
    para(doc,
         "Bộ đếm chỉ cộng khi phiên không bị khóa (WTS_SESSION_LOCK) và thời gian không thao tác (GetLastInputInfo) không quá 300 giây. "
         "Mỗi bước cộng là hiệu hai mốc time.monotonic(), chỉ chấp nhận bước từ 0 đến 10 giây: máy ngủ rồi thức dậy hay tiến trình bị "
         "treo không làm nhảy bộ đếm. Trạng thái được ghi xuống daily_usage_state để khởi động lại không mất số phút đã dùng.")
    doc.add_heading("4.1.3. Cảnh báo và ân hạn", level=3)
    para(doc,
         "Khi thời gian còn lại chạm 10, 5 và 1 phút, Service trả warning tương ứng (warn_10m, warn_5m, warn_1m) trong phản hồi "
         "GET_SESSION_STATUS; Tray hiển thị hộp thoại một lần cho mỗi mốc và Service ghi sự kiện quota_warning. Hết hạn mức thì "
         "trạng thái chuyển GRACE_PERIOD_60S: Tray mở cửa sổ đếm ngược 60 giây với hai nút \"Xin thêm 15 phút\" (gửi unlock_request "
         "lên dashboard) và \"Bố mẹ mở khóa\" (nhập PIN phụ huynh cục bộ, đối chiếu băm Argon2id nhận từ máy chủ; thành công thì ghi "
         "override_granted). Hết 60 giây thì khóa (sự kiện locked).")
    doc.add_heading("4.1.4. Chống chỉnh đồng hồ ba lớp", level=3)
    add_table(doc, ["Lớp", "Cơ chế", "Chặn được"], [
        ["1", "Bộ đếm dùng time.monotonic(), không phụ thuộc giờ hệ thống. Mỗi giây so bước nhảy của giờ hệ thống với GetTickCount64 (vẫn chạy khi máy ngủ); lệch quá 60 giây là chỉnh tay: độ lệch được cộng vào wall_offset_sec, nên sang ngày, ngày thường/cuối tuần và lịch 7x48 vẫn theo giờ thật, và ghi sự kiện quota_warning (subject clock_tamper)", "Lùi hoặc tiến giờ khi agent đang chạy, kể cả chỉnh sang ngày mai để được quota mới"],
        ["2", "Lưu last_wall_clock_utc; khi khởi động, giờ hiện tại nhỏ hơn mốc đã lưu là có lùi giờ", "Lùi giờ trong lúc tắt máy hoặc tắt agent"],
        ["3", "So server_utc trong mỗi nhịp tim, lệch quá 120 giây thì ghi cảnh báo, hiện trên dashboard và lấy giờ máy chủ làm giờ tin cậy", "Lệch giờ kéo dài, đổi múi giờ để qua ngày mới"],
    ], [0.5, 3.6, 2.4])
    para(doc, "Tiêu chí nghiệm thu \"lùi đồng hồ 3 giờ: quota không tăng, sự kiện bị ghi nhận\" được kiểm bằng test trong tests/test_agent_core.py và tests/test_enforcement_hardening.py (chỉnh giờ qua nửa đêm, lịch theo giờ tin cậy).")
    doc.add_heading("4.1.5. Ngân sách theo nhóm ứng dụng", level=3)
    para(doc,
         "category_budgets_json cho mỗi nhóm một trong ba chế độ: không giới hạn, giới hạn N phút, hoặc chặn hẳn. Bộ đếm theo nhóm chạy "
         "song song và độc lập với hạn mức ngày: trẻ có thể còn 30 phút trong ngày nhưng đã hết 45 phút trò chơi, khi đó chỉ ứng dụng "
         "nhóm gaming bị chặn còn ứng dụng học tập vẫn dùng được.")

    doc.add_heading("4.2. F2: Kiểm soát ứng dụng và website", level=2)
    doc.add_heading("4.2.1. Nhận diện ứng dụng", level=3)
    para(doc,
         "AppController quét tiến trình qua psutil, bỏ qua danh sách tiến trình hệ thống trọng yếu. Mỗi tiến trình được đối chiếu với "
         "quy tắc theo ba dấu hiệu: tên tệp, mã băm SHA-256 của tệp thực thi và trường OriginalFileName trong tài nguyên phiên bản của "
         "PE header. Đổi tên game.exe thành notepad.exe không qua được vì mã băm và OriginalFileName không đổi. Băm cả tệp tốn I/O nên "
         "có Sha256LruCache khóa theo (đường dẫn, kích thước, thời điểm sửa). Tiến trình vi phạm bị kết thúc, sự kiện blocked_app được "
         "ghi, và mục {subject, reason, ts} được đẩy vào hàng đợi recent_blocks để Tray hiện cửa sổ giải thích.")
    doc.add_heading("4.2.2. DNS proxy cục bộ và Suffix Trie", level=3)
    para(doc,
         "DnsProxyServer lắng nghe UDP và TCP tại 127.0.0.1:53 (asyncio + dnslib). Với mỗi truy vấn, DomainPolicyEngine quyết định theo "
         "thứ tự: tên miền canary DoH, điểm cuối DoH, SafeSearch, allowlist, blocklist. Quy tắc lưu trong Suffix Trie theo nhãn đảo ngược "
         "(test → example → bad), nên tra một tên có k nhãn tốn O(k) và một quy tắc cho example.test áp dụng luôn cho mọi tên miền con. "
         "Allowlist thắng blocklist để tránh dương tính giả với trang giáo dục. Bị chặn thì trả bản ghi A 0.0.0.0 (sinkhole); được phép "
         "thì tra cache TTL rồi chuyển tiếp upstream, upstream chính không trả lời trong 2 giây thì chuyển sang upstream phụ.")
    add_code_block(doc,
        "evaluate(qname):\n"
        "  if qname == 'use-application-dns.net'      -> NXDOMAIN   (tắt DoH tự động của Firefox)\n"
        "  if qname in DOH_ENDPOINTS                   -> NXDOMAIN   (dns.google, cloudflare-dns.com, ...)\n"
        "  if qname in SAFESEARCH_MAP                  -> CNAME forcesafesearch.google.com / restrict.youtube.com ...\n"
        "  rule = trie.longest_suffix_match(reverse(labels(qname)))       # O(k)\n"
        "  if rule.action == 'allow'                   -> forward upstream (cache TTL)\n"
        "  if rule.action == 'block'                   -> A 0.0.0.0, ghi blocked_domain, báo Tray\n"
        "  else                                        -> forward upstream")
    add_caption(doc, "Hình 4.1. Thứ tự quyết định của DomainPolicyEngine")
    doc.add_heading("4.2.3. Phân loại 6 nhóm và dữ liệu kiểm thử an toàn", level=3)
    para(doc,
         "server/seeds/domain_catalog.json có 235 tên miền thuộc 6 nhóm: education, entertainment, social, gaming, inappropriate, "
         "unclassified, kèm chính sách mặc định cho trẻ 6 đến 11 tuổi. Theo quy định của đề bài, nhóm inappropriate chỉ dùng tên miền "
         "dự trữ theo RFC 2606 (.test, .example); test_seed_catalog.py kiểm tra tự động điều này. Kiểm thử DNS kiểm tra tỷ lệ chặn "
         "≥ 95% trên bộ 50 tên miền và 0 dương tính giả trên 20 tên miền giáo dục, đúng tiêu chí nghiệm thu.")
    doc.add_heading("4.2.4. SafeSearch, DoH và khóa DNS card mạng", level=3)
    para(doc,
         "SafeSearch được cưỡng chế bằng CNAME: google.com trỏ tới forcesafesearch.google.com, youtube.com tới restrict.youtube.com, "
         "bing.com tới strict.bing.com, duckduckgo.com tới safe.duckduckgo.com; kiểm chứng được bằng nslookup qua 127.0.0.1. Để trình "
         "duyệt không đi vòng qua DoH, proxy trả NXDOMAIN cho tên canary và 10 điểm cuối DoH phổ biến, BrowserPolicyGuard đặt "
         "DnsOverHttpsMode=off trong registry chính sách của Chrome và Edge, và NetworkDnsGuard đặt DNS của mọi card mạng về 127.0.0.1. "
         "Mọi thay đổi đều có snapshot trong agent.db và được khôi phục bởi ogk_cleanup.py.")

    doc.add_heading("4.3. F3: Ghi nhận, báo cáo và minh bạch", level=2)
    add_table(doc, ["type", "Khi nào phát sinh", "subject"], [
        ["app_start / app_stop", "Ứng dụng mở hoặc đóng (kèm duration_sec)", "tên exe, vd. code.exe"],
        ["domain_query", "Truy vấn DNS được phép", "eTLD+1, vd. wikipedia.org"],
        ["blocked_app", "Ứng dụng bị kết thúc do quy tắc", "tên exe"],
        ["blocked_domain", "Truy vấn bị sinkhole", "eTLD+1"],
        ["quota_warning", "Còn 10, 5, 1 phút", "system"],
        ["locked", "Máy bị khóa do hết giờ, ngoài lịch hoặc lệnh", "system"],
        ["unlock_request", "Trẻ bấm Xin thêm giờ", "system"],
        ["override_granted", "Phụ huynh duyệt hoặc nhập PIN mở khóa", "system"],
    ], [1.6, 3.0, 1.9])
    para(doc,
         "Lược đồ được ép ở ba nơi: EventBuffer phía agent, Pydantic schema phía máy chủ (extra=forbid, type thuộc tập 9 giá trị) và "
         "validator subject. normalize_etld_plus_one() dùng tldextract với danh sách hậu tố đóng gói sẵn (không cần mạng); tên miền có "
         "TLD ngoài danh sách như .test được rút về hai nhãn cuối. Mọi subject chứa '/', '?', '&', '#' hoặc '\\' đều bị từ chối, nên "
         "URL đầy đủ hay đường dẫn tệp không thể lọt vào CSDL.")
    para(doc,
         "Dashboard phụ huynh (tab Hôm nay) hiển thị tờ lịch ngày với số phút đã dùng so với hạn mức, biểu đồ 7 ngày, phân bổ theo "
         "nhóm, top 10 ứng dụng, top 10 tên miền, số lần chặn và danh sách yêu cầu xin thêm giờ với nút Duyệt +15 phút / Từ chối. Duyệt "
         "sẽ gửi lệnh ADD_TIME_15M, ghi sự kiện override_granted gắn với yêu cầu và ghi audit log. Có nút xuất CSV và nút xóa toàn bộ "
         "dữ liệu (xóa trên máy chủ và gửi PURGE_DATA xóa bộ đệm của agent). Tác vụ nền trên máy chủ xóa sự kiện cũ hơn 90 ngày.")
    para(doc,
         "Màn hình \"Hôm nay em đã dùng gì?\" dùng cùng dữ liệu và cùng bố cục với dashboard phụ huynh nhưng viết bằng câu ngắn cho học "
         "sinh tiểu học: thời gian còn lại hôm nay kèm thanh tiến độ, dải 48 ô giờ được dùng (ô khóa có thêm vân sọc, không chỉ khác màu), "
         "biểu đồ 7 ngày, ứng dụng và trang web đã dùng, những lần bị chặn, ba cam kết \"Những điều EC - Echo Kiddo không làm\" "
         "và đường dẫn tới nhật ký thay đổi. docs/PRIVACY.md có bảng trường dữ liệu, mục đích, thời hạn, người xem và một phiên bản cho trẻ.")

    doc.add_heading("4.4. F4: Quản trị từ xa, toàn vẹn chính sách, kiểm toán", level=2)
    para(doc,
         "Chữ ký chính sách là HMAC-SHA256 trên JSON chuẩn hóa (sort_keys, không khoảng trắng) của đúng 9 trường SIGNED_POLICY_KEYS: "
         "child_id, version, daily_limit_weekday_min, daily_limit_weekend_min, schedule_matrix_7x48, category_budgets_json, app_rules_json, "
         "domain_rules_json, updated_at_utc. Danh sách này giống hệt nhau ở server/services/policy_service.py và agent/core/policy_verifier.py "
         "(có test so sánh). Các trường siêu dữ liệu như id không được ký và bị loại khi agent dựng bản chạy, nên không trường chưa ký nào "
         "ảnh hưởng được tới việc thực thi. Agent còn kiểm tra child_id trong chính sách trùng với trẻ của thiết bị.")
    add_code_block(doc,
        '{ "child_id": "e0742125-...", "version": 7,\n'
        '  "daily_limit_weekday_min": 120, "daily_limit_weekend_min": 180,\n'
        '  "schedule_matrix_7x48": "000000000000111111...111100",\n'
        '  "category_budgets_json": "{\\"gaming\\": 45, \\"education\\": -1}",\n'
        '  "app_rules_json": "[{\\"exe_name\\": \\"game.exe\\", \\"sha256\\": null, ...}]",\n'
        '  "domain_rules_json": "[{\\"domain\\": \\"bad-simulated-site.test\\", \\"action\\": \\"block\\"}]",\n'
        '  "updated_at_utc": "2026-11-19T07:12:31+00:00",\n'
        '  "signature": "9f2c...e41a"        # HMAC-SHA256(policy_secret, canonical_json(9 trường)) }')
    add_caption(doc, "Hình 4.2. Chính sách đã ký trên đường truyền")
    para(doc,
         "Khóa ký là policy_secret dẫn xuất từ bí mật máy chủ bằng HMAC với nhãn \"ogk-policy-signing-v1\", cấp cho agent lúc ghép đôi; "
         "bản thân JWT secret không bao giờ rời máy chủ. Sửa một ký tự trong agent.db hay chen giữa đường đều làm chữ ký sai và agent "
         "giữ nguyên chính sách cũ. Đo đầu-cuối (mục 5.4) cho thấy thay đổi từ dashboard có hiệu lực trên agent trong khoảng 50 ms khi "
         "WebSocket đang mở, và tối đa khoảng 60 giây qua nhịp tim nếu WebSocket rớt.")
    para(doc,
         "Mọi thao tác ghi đều vào audit_logs: tạo mã ghép đôi, ghép thiết bị, sửa chính sách (kèm giá trị cũ và mới), gửi lệnh khẩn, "
         "duyệt hoặc từ chối yêu cầu, gỡ thiết bị, xóa dữ liệu. Trang /audit/view hiển thị cho cả phụ huynh và trẻ (nguyên tắc NT5), chỉ "
         "các mục thuộc gia đình đang đăng nhập. Gỡ cài đặt hợp pháp dùng ogk_cleanup.py với PIN phụ huynh, khôi phục DNS và registry từ "
         "snapshot; lệnh PARENT_PAUSE_2H tạm dừng kiểm soát 2 giờ rồi tự bật lại, có ghi log.")

    doc.add_heading("4.5. F5: Bảo mật và quyền riêng tư (tóm tắt)", level=2)
    para(doc, "Chi tiết biện pháp, mô hình mối đe dọa và checklist ASVS ở Chương 6. Bảng dưới đối chiếu với yêu cầu tối thiểu của đề bài:")
    add_table(doc, ["Hạng mục", "Hiện thực"], [
        ["Xác thực phụ huynh", "Argon2id (64 MiB, time_cost 3, parallelism 4); mật khẩu tối thiểu 10 ký tự; khóa 15 phút sau 5 lần sai; rate limit theo IP (slowapi)"],
        ["Phiên làm việc", "Cookie ogk_session HttpOnly, SameSite=Lax, Secure khi chạy HTTPS, hạn 12 giờ; token CSRF cho mọi thao tác ghi"],
        ["Kênh truyền", "TLS 1.2+ (CA tự ký trong lab, scripts/setup_lab.py); agent ghim SHA-256 chứng chỉ máy chủ và từ chối kết nối khi không khớp"],
        ["Định danh thiết bị", "Access token 15 phút + refresh token gắn device_id; máy chủ lưu băm refresh token; thu hồi khi gỡ thiết bị"],
        ["Dữ liệu lưu trữ", "Token và khóa HMAC trong agent.db mã hóa AES-256-GCM; khóa lấy từ biến môi trường hoặc tệp khóa bọc DPAPI, không hardcode"],
        ["Phân quyền", "parent, child-view, admin; kiểm tra quyền sở hữu ở tầng truy vấn (get_child_for_parent) để chống IDOR"],
        ["Đặc quyền cục bộ", "Tài khoản trẻ là Standard User; thư mục ProgramData\\OGK chỉ SYSTEM và Administrators được ghi"],
        ["Chống lạm dụng", "Không có chế độ ẩn; không hiện được khay thì UNPROTECTED_HALT; phạm vi sử dụng hợp pháp ghi ở chân mọi trang web"],
    ], [1.6, 4.9])
    doc.add_page_break()

    # ======================= CHAPTER 5 =======================
    doc.add_heading("CHƯƠNG 5. KỸ THUẬT MẠNG VÀ HIỆU NĂNG (TÓM TẮT M1-M6)", level=1)
    para(doc, "Chương này tóm tắt phụ lục docs/BaoCaoKyThuatMang.pdf; phụ lục có bảng giải phẫu gói tin, sơ đồ và hướng dẫn chụp Wireshark đầy đủ.")

    doc.add_heading("5.1. M1: Đường đi gói tin khi mở một trang bị chặn", level=2)
    add_numbered(doc, [
        "Trình duyệt cần địa chỉ của www.bad-simulated-site.test và gọi stub resolver của Windows (dịch vụ Dnscache).",
        "Card mạng đã bị NetworkDnsGuard đặt DNS là 127.0.0.1, nên stub resolver gửi gói UDP tới 127.0.0.1:53.",
        "EC - Echo Kiddo DNS proxy nhận gói, dnslib giải mã phần Question, chuẩn hóa tên và tra Suffix Trie: khớp quy tắc block của bad-simulated-site.test.",
        "Proxy dựng phản hồi cùng Transaction ID, cờ QR=1, RCODE=NOERROR, một bản ghi A 0.0.0.0 TTL ngắn; ghi blocked_domain (subject bad-simulated-site.test) và báo Tray.",
        "Trình duyệt kết nối tới 0.0.0.0, thất bại ngay, không có gói nào ra Internet; Tray hiện cửa sổ giải thích cho trẻ.",
    ])
    para(doc, "Trên Wireshark, chụp giao diện Npcap Loopback Adapter với bộ lọc udp.port == 53 sẽ thấy đúng một cặp truy vấn và phản hồi cho mỗi lần tra.")

    doc.add_heading("5.2. M2: So sánh phương án chặn", level=2)
    add_table(doc, ["Tiêu chí", "Tệp hosts", "DNS proxy cục bộ", "Proxy HTTP(S)", "Bộ lọc WFP"], [
        ["Độ chính xác", "Từng tên, không wildcard", "Tên miền và mọi tên miền con", "Đến đường dẫn URL", "Theo IP/cổng, không biết tên miền"],
        ["Chặn HTTPS", "Có (trước khi bắt tay TLS)", "Có (trước khi bắt tay TLS)", "Cần giải mã TLS, cài CA vào máy trẻ", "Có, theo IP"],
        ["Chi phí hiện thực", "Rất thấp", "Trung bình", "Cao", "Cao (driver/API nhân)"],
        ["Khả năng bị vượt", "Cao", "Trung bình, cần khóa DNS và DoH", "Trung bình", "Thấp"],
        ["Ảnh hưởng hiệu năng", "Không đáng kể", "Dưới 1 ms khi cache hit", "Đáng kể", "Thấp"],
    ], [1.2, 1.2, 1.5, 1.4, 1.2])
    para(doc,
         "Nhóm chọn DNS proxy cục bộ làm phương án chính vì cân bằng tốt nhất: chặn được HTTPS mà không cần giải mã nội dung (đúng "
         "nguyên tắc không đọc nội dung), chặn theo wildcard, chi phí hiện thực vừa sức đồ án, và điểm yếu (DoH, đổi DNS) có biện pháp "
         "bù cụ thể. Proxy HTTPS bị loại vì buộc phải cài chứng chỉ gốc và đọc nội dung trang.")

    doc.add_heading("5.3. M3: Phân tích đường vòng", level=2)
    add_table(doc, ["Kỹ thuật vượt rào", "Kết quả trên EC - Echo Kiddo", "Đối phó hoặc lý do chấp nhận"], [
        ["Đổi DNS thủ công sang 8.8.8.8", "Standard User không đổi được; admin đổi thì NetworkDnsGuard đặt lại và ghi bypass", "Khóa thiết lập card mạng, giám sát định kỳ"],
        ["DNS-over-HTTPS", "Bị chặn: NXDOMAIN canary và điểm cuối DoH, registry tắt DoH", "Danh sách điểm cuối cần cập nhật; DoH tới IP lạ là rủi ro còn lại"],
        ["DNS-over-TLS (cổng 853)", "Hệ điều hành không dùng DoT mặc định", "Chấp nhận rủi ro; hướng mở rộng: chặn cổng 853 bằng tường lửa"],
        ["VPN / proxy công cộng", "Cài VPN cần quyền admin; ứng dụng VPN có thể đưa vào blocklist", "Tài khoản trẻ không phải admin"],
        ["Truy cập bằng địa chỉ IP", "Không qua DNS nên không bị chặn", "Chấp nhận: giới hạn vốn có của lọc DNS; HTTPS theo IP thường lỗi chứng chỉ"],
        ["Khởi động Safe Mode", "Dịch vụ không chạy trong Safe Mode", "Đặt mật khẩu BIOS/UEFI, trẻ không có quyền admin"],
        ["Khởi động từ USB / Live OS", "Không áp dụng được chính sách", "Đặt mật khẩu UEFI, tắt boot USB; ngoài phạm vi phần mềm"],
        ["Tài khoản Windows khác", "Service chạy toàn máy, mỗi phiên đều bật Tray", "Thời gian gắn theo hồ sơ trẻ, không theo tài khoản"],
        ["Kết thúc tiến trình", "Không tắt được Service LocalSystem; tắt Tray thì bật lại sau 3 giây", "Nếu 3 lần không bật được: UNPROTECTED_HALT (minh bạch)"],
    ], [1.7, 2.6, 2.2])

    doc.add_heading("5.4. M4: Kết quả đo hiệu năng", level=2)
    for line in bench_meta:
        add_bullets(doc, [line])
    for title, rows in bench_tables:
        doc.add_heading(title, level=3)
        add_table(doc, rows[0], rows[1:])
    para(doc,
         "Số liệu trên được sinh tự động bởi tests/benchmark_m4.py và đọc từ docs/benchmark_m4_results.md tại thời điểm tạo báo cáo. "
         "Độ trễ DNS qua Internet dao động mạnh theo mạng, nên tiêu chí \"có Agent\" được chấm trên chi phí xử lý riêng của agent; phép "
         "so sánh có/không có agent qua mạng thật được giữ làm tham chiếu.")

    doc.add_heading("5.5. M5: Khả năng chịu lỗi", level=2)
    add_table(doc, ["Kịch bản", "Hành vi mong đợi", "Hành vi thực tế", "Phục hồi"], [
        ["Mất mạng LAN/Internet", "Vẫn đếm giờ và chặn theo chính sách đệm, đệm sự kiện", "Đúng như mong đợi; sự kiện nằm trong event_queue", "Đồng bộ theo lô ở nhịp tim đầu tiên sau khi có mạng (≤ 60 s)"],
        ["Máy chủ ngừng hoạt động", "Như mất mạng; WebSocket kết nối lại theo backoff", "Agent tiếp tục thực thi; dashboard không truy cập được", "Kết nối lại trong ≤ 60 s + jitter sau khi máy chủ lên"],
        ["EC Tray bị tắt", "Service bật lại Tray", "Tray xuất hiện lại", "Khoảng 3 giây"],
        ["EC Service bị dừng", "SCM khởi động lại theo Recovery Options", "Trạng thái ngày nạp lại từ agent.db", "Theo cấu hình SCM (vài giây)"],
    ], [1.4, 1.8, 1.8, 1.5])

    doc.add_heading("5.6. M6: Đồng bộ thời gian", level=2)
    para(doc,
         "Kiến trúc ba lớp ở mục 4.1.4: đồng hồ đơn điệu cho bộ đếm, mốc last_wall_clock_utc trong SQLite cho lần khởi động sau, và đối "
         "chiếu server_utc mỗi nhịp tim với ngưỡng cảnh báo 120 giây. Máy chủ là nguồn thời gian tin cậy; dashboard hiển thị huy hiệu "
         "\"Đồng hồ lệch N giây\" bên cạnh thiết bị khi vượt ngưỡng.")

    # ======================= CHAPTER 6 =======================
    doc.add_heading("CHƯƠNG 6. BẢO MẬT, MÔ HÌNH MỐI ĐE DỌA VÀ QUYỀN RIÊNG TƯ", level=1)

    doc.add_heading("6.1. Mô hình mối đe dọa STRIDE", level=2)
    add_table(doc, ["Mã", "Mối đe dọa", "STRIDE", "Biện pháp"], [
        ["TM-01", "Trẻ đổi tên game.exe thành notepad.exe", "Tampering", "Đối chiếu SHA-256 và OriginalFileName"],
        ["TM-02", "Trẻ lùi đồng hồ hệ thống", "Tampering", "Monotonic, last_wall_clock_utc, server_utc"],
        ["TM-03", "Trẻ giả mạo tin nhắn IPC để mở khóa", "Spoofing, EoP", "Kiểm tra SID người gọi từ nhân Windows, challenge token, compare_digest"],
        ["TM-04", "Trẻ tắt khay hệ thống", "DoS", "Bật lại sau 3 giây, quá 3 lần thì UNPROTECTED_HALT"],
        ["TM-05", "Sản phẩm bị lạm dụng làm stalkerware theo dõi người lớn", "Information disclosure", "Không chế độ ẩn, 7 trường, không URL, không ảnh màn hình"],
        ["TM-06", "Phụ huynh khác truy cập dữ liệu gia đình mình (IDOR)", "Information disclosure", "Lọc parent_id ở tầng truy vấn"],
        ["TM-07", "Chen giữa đường giữa agent và máy chủ (MITM)", "Spoofing, Tampering", "TLS 1.2+, ghim chứng chỉ, HMAC chính sách và lệnh"],
        ["TM-08", "Vét cạn mật khẩu phụ huynh", "Spoofing", "Argon2id, rate limit, khóa 15 phút sau 5 lần sai"],
    ], [0.6, 2.4, 1.2, 2.3])
    para(doc,
         "Hai kịch bản bắt buộc của đề bài đều có mặt: \"chính trẻ là người tấn công\" (TM-01 đến TM-04) và \"sản phẩm bị lạm dụng để "
         "theo dõi người lớn\" (TM-05). Với TM-05, biện pháp quan trọng nhất nằm ở thiết kế: hệ thống không có khả năng thu thập nội dung, "
         "nên kẻ lạm dụng cũng không có gì để lấy ngoài tên ứng dụng và tên miền, và người dùng máy luôn thấy biểu tượng EC - Echo Kiddo.")

    doc.add_heading("6.2. Ghim chứng chỉ (certificate pinning)", level=2)
    para(doc,
         "scripts/setup_lab.py sinh chứng chỉ tự ký có SAN cho localhost, 127.0.0.1 và IP LAN, rồi in SHA-256 của chứng chỉ dạng DER "
         "vào biến OGK_PINNED_CERT_FINGERPRINT. Trước khi tạo kết nối HTTPS hay WSS, AgentServerClient mở một kết nối TLS, lấy chứng chỉ "
         "lá của máy chủ và so SHA-256 với giá trị đã ghim; không khớp thì ném CertificatePinError và không gửi bất kỳ dữ liệu nào. "
         "Nhóm đã thử với máy chủ TLS thật: đúng dấu vân tay thì kết nối được, sai thì bị từ chối (test trong test_phase1_policy_sync.py).")

    doc.add_heading("6.3. Mã hóa dữ liệu lưu trữ", level=2)
    para(doc,
         "agent/core/field_crypto.py mã hóa access_token, refresh_token và policy_hmac_secret trong agent.db bằng AES-256-GCM (nonce 12 "
         "byte ngẫu nhiên mỗi lần, tag 16 byte, dữ liệu liên kết cố định). Khóa 32 byte lấy từ biến môi trường OGK_AGENT_DATA_KEY, hoặc "
         "được sinh ngẫu nhiên lần đầu và lưu trong tệp agent.key bọc bằng DPAPI (CryptProtectData, phạm vi máy), nên sao chép agent.db và "
         "agent.key sang máy khác cũng không giải mã được. Phía máy chủ, mật khẩu băm Argon2id, refresh token chỉ lưu băm SHA-256, khóa AES "
         "của máy chủ lấy từ biến môi trường hoặc tệp sinh ngẫu nhiên lần đầu, không có giá trị mặc định trong mã nguồn.")

    doc.add_heading("6.4. Checklist OWASP ASVS", level=2)
    add_table(doc, ["Nhóm ASVS", "Yêu cầu", "Trạng thái"], [
        ["V2 Xác thực", "Băm mật khẩu bằng hàm chậm, chống vét cạn, độ dài tối thiểu", "Đạt (Argon2id, khóa 15 phút, ≥ 10 ký tự)"],
        ["V3 Quản lý phiên", "Cookie HttpOnly/SameSite/Secure, hết hạn 12 giờ, đăng xuất đưa jti của phiên vào bảng revoked_sessions (hủy phía máy chủ)", "Đạt"],
        ["V4 Kiểm soát truy cập", "Kiểm tra quyền sở hữu phía máy chủ cho mọi đối tượng", "Đạt (get_child_for_parent, test IDOR)"],
        ["V5 Xác thực đầu vào", "Lược đồ chặt, từ chối trường lạ, chống sửa chính sách", "Đạt (Pydantic extra=forbid, HMAC)"],
        ["V6 Mật mã lưu trữ", "Thuật toán chuẩn, khóa không hardcode", "Đạt (AES-256-GCM, DPAPI/env)"],
        ["V9 Truyền thông", "TLS cho mọi kết nối, xác minh chứng chỉ", "Đạt (TLS 1.2+, ghim chứng chỉ)"],
        ["V13 API", "Xác thực từng endpoint, rate limit", "Đạt"],
    ], [1.6, 3.0, 1.9])

    doc.add_heading("6.5. Quyền riêng tư theo thiết kế", level=2)
    add_table(doc, ["Trường", "Mục đích", "Thời hạn", "Ai xem được"], [
        ["ts", "Báo cáo theo ngày", "90 ngày", "Phụ huynh, trẻ"],
        ["device_id", "Phân biệt máy trong gia đình", "Theo vòng đời thiết bị", "Phụ huynh, hệ thống"],
        ["child_id", "Gắn sự kiện với hồ sơ trẻ", "Đến khi phụ huynh xóa", "Phụ huynh, trẻ"],
        ["type", "Một trong 9 loại sự kiện", "90 ngày", "Phụ huynh, trẻ"],
        ["subject", "Tên exe hoặc eTLD+1, không URL", "90 ngày", "Phụ huynh, trẻ"],
        ["duration_sec", "Thời lượng dùng thực", "90 ngày", "Phụ huynh, trẻ"],
        ["policy_id", "Truy vết quy tắc đang áp dụng", "90 ngày", "Phụ huynh, trẻ"],
    ], [1.3, 2.4, 1.5, 1.3])

    # ======================= CHAPTER 7 =======================
    doc.add_heading("CHƯƠNG 7. KIỂM THỬ", level=1)
    doc.add_heading("7.1. Chiến lược kiểm thử", level=2)
    para(doc,
         f"Bộ kiểm thử gồm {n_tests} ca, chạy bằng pytest trong khoảng 15 giây, không cần quyền admin và không chạm vào cấu hình thật "
         "của máy: mọi CSDL nằm trong thư mục tạm, agent nói chuyện với ứng dụng FastAPI qua httpx.ASGITransport, các thành phần sửa DNS "
         "và registry được thay bằng mock. Nhờ vậy giảng viên chạy được ngay sau khi cài theo README.")
    add_table(doc, ["Tệp kiểm thử", "Phạm vi"], [
        ["test_agent_core.py", "Bộ đếm monotonic, idle, lịch 7x48, Graded Fail-Open, chống lùi giờ, ngân sách nhóm, AppController đổi tên exe, EventBuffer"],
        ["test_agent_db.py", "Chính sách đệm, hàng đợi sự kiện, snapshot, mã hóa AES-GCM định danh thiết bị"],
        ["test_dns_proxy.py", "Suffix Trie, allowlist thắng blocklist, SafeSearch, DoH, 50 miền chặn, 20 miền giáo dục, failover, cache TTL"],
        ["test_agent_lifecycle.py", "IpcEnvelope, challenge, guardrail UNPROTECTED_HALT, Tray headless, ogk_cleanup"],
        ["test_server_db.py, test_schemas.py", "PRAGMA WAL, cascade, ràng buộc 7 trường, từ chối URL"],
        ["test_server_api.py", "Đăng ký, đăng nhập, khóa sau 5 lần sai, IDOR, ghép đôi, đồng bộ lô, WebSocket"],
        ["test_web_dashboard.py", "Trang đăng nhập (CSRF), dashboard, màn hình của trẻ, nhật ký, đăng xuất hủy phiên phía máy chủ, vai trò child-view chỉ đọc"],
        ["test_enforcement_hardening.py", "Ngân sách -1 = không giới hạn, hai bộ đếm độc lập, chỉnh giờ qua nửa đêm, không đụng tiến trình Session 0, Tray báo idle/khóa phiên, khóa Windows khi hết giờ, ACL ProgramData, sự kiện gỡ cài đặt"],
        ["test_phase1_policy_sync.py", "Hợp đồng HMAC 9 trường giữa máy chủ và agent, enroll và lưu định danh, IPC Tray, duyệt yêu cầu, ghim chứng chỉ"],
        ["test_integration_scenarios.py", "5 kịch bản tích hợp đầu-cuối"],
        ["benchmark_m4.py", "Bài đo M4 chạy ở chế độ ngoại tuyến như một ca kiểm thử"],
    ], [2.2, 4.3])
    doc.add_heading("7.2. Năm kịch bản tích hợp đầu-cuối", level=2)
    add_numbered(doc, [
        "Ghép đôi: phụ huynh xác nhận đồng ý, tạo mã, agent ghép đôi, nhận và xác minh chính sách, audit log có mục tương ứng.",
        "Lệnh khẩn: phụ huynh gửi LOCK_NOW, UNLOCK, ADD_TIME_15M; agent nhận qua WebSocket, kiểm chữ ký, thực thi và ACK.",
        "Hết hạn mức: cảnh báo 10/5/1 phút, ân hạn 60 giây, trẻ gửi yêu cầu, phụ huynh duyệt, agent được cộng 15 phút.",
        "Lọc DNS: chặn tên miền và tên miền con, SafeSearch, phát hiện đổi DNS thủ công.",
        "Xóa dữ liệu và khôi phục: xóa sự kiện trên máy chủ, PURGE_DATA xóa bộ đệm agent, cleanup trả DNS và registry về như cũ.",
    ])
    doc.add_heading("7.3. Kết quả", level=2)
    para(doc,
         f"Lần chạy cuối cùng trước khi nộp: {n_tests} ca đạt, 0 lỗi (pytest -v). Nhóm đính kèm ảnh chụp kết quả trong thư mục nộp bài theo "
         "yêu cầu mục 8 của đề bài. Ngoài kiểm thử tự động, dashboard được kiểm tra bằng trình duyệt ở bề rộng 1440 px và 390 px.")

    # ======================= CHAPTER 8 =======================
    doc.add_heading("CHƯƠNG 8. TRIỂN KHAI VÀ HƯỚNG DẪN CHẠY DEMO", level=1)
    doc.add_heading("8.1. Cài đặt trong 15 phút", level=2)
    add_numbered(doc, [
        "Cài Python 3.11+ x64. Mở PowerShell với quyền Administrator tại thư mục dự án.",
        "python -m venv .venv; .\\.venv\\Scripts\\Activate.ps1; pip install -r server/requirements.txt -r agent/requirements.txt (khoảng 3 phút).",
        ".\\scripts\\run_dev.ps1 setup: sinh chứng chỉ TLS tự ký, in dấu vân tay để ghim, nạp dữ liệu mẫu (demo/seed_demo.py).",
        ".\\scripts\\run_dev.ps1 server: chạy EC Server qua HTTPS trên cổng 8000.",
        "Mở https://<IP máy chủ>:8000/login trên máy tính hoặc điện thoại, đăng nhập parent@ogk.local / AdminPassword123!.",
        "Trên máy trẻ: tạo mã ghép đôi ở tab Thiết bị, chạy python agent/service/win_service.py enroll --code <MÃ> --server https://<IP>:8000, rồi win_service.py run.",
        "Gỡ sạch: python agent/cleanup/ogk_cleanup.py --pin <PIN> trả DNS và registry về trạng thái ban đầu.",
    ])
    doc.add_heading("8.2. Kịch bản demo gợi ý (5 đến 7 phút)", level=2)
    add_table(doc, ["Phút", "Nội dung", "Yêu cầu được chứng minh"], [
        ["0:00", "Đăng nhập, giới thiệu dashboard và màn hình của trẻ", "F3, NT5"],
        ["1:00", "Đặt hạn mức 3 phút, chờ cảnh báo 1 phút và cửa sổ ân hạn 60 giây", "F1"],
        ["2:30", "Trẻ bấm Xin thêm giờ, phụ huynh duyệt trên điện thoại", "F1, F4 (dưới 5 giây)"],
        ["3:30", "Mở game.exe đã đổi tên thành notepad.exe: bị chặn kèm cửa sổ giải thích", "F2"],
        ["4:30", "nslookup tên miền bị chặn và google.com qua 127.0.0.1; Wireshark loopback", "F2, M1"],
        ["5:30", "Lùi đồng hồ 3 giờ: quota không tăng, dashboard báo lệch giờ", "F1, M6"],
        ["6:15", "Mở nhật ký kiểm toán với tư cách trẻ, xóa dữ liệu, chạy cleanup", "F3, F4"],
    ], [0.7, 4.0, 1.8])
    doc.add_heading("8.3. Xử lý sự cố thường gặp", level=2)
    add_table(doc, ["Hiện tượng", "Nguyên nhân", "Cách xử lý"], [
        ["Proxy DNS không khởi động", "Cổng 53 đã bị dịch vụ khác chiếm (vd. Internet Connection Sharing)", "check_port_53_conflict in tên tiến trình chiếm cổng; tắt dịch vụ đó"],
        ["Agent báo CertificatePinError", "Đã sinh lại chứng chỉ máy chủ", "Chạy lại setup_lab.py và cập nhật OGK_PINNED_CERT_FINGERPRINT"],
        ["Dashboard trống dữ liệu", "Dữ liệu mẫu cũ hơn 7 ngày", "Chạy lại demo/seed_demo.py (tự làm mới sự kiện cũ)"],
        ["Tray không hiện", "Không có phiên người dùng hoạt động", "Service chuyển UNPROTECTED_HALT theo thiết kế; đăng nhập rồi khởi động lại dịch vụ"],
    ], [1.7, 2.3, 2.5])

    # ======================= CHAPTER 9 =======================
    doc.add_heading("CHƯƠNG 9. KẾT LUẬN VÀ HƯỚNG PHÁT TRIỂN", level=1)
    doc.add_heading("9.1. Kết quả đạt được", level=2)
    add_bullets(doc, [
        "Hiện thực đủ các yêu cầu BẮT BUỘC của F1 đến F5 và phần lớn yêu cầu NÊN CÓ (ngân sách nhóm, đối phó DoH, khóa DNS card mạng, xuất CSV, gỡ cài có PIN, tạm nghỉ 2 giờ).",
        "Đặc tả và hiện thực năm giao thức vòng đời, có quyết định ADR-01 cho trường hợp mất kết nối kéo dài.",
        "Đo hiệu năng với ít nhất 30 mẫu mỗi phép đo, gồm so sánh DNS có và không có agent qua mạng thật và độ trễ áp dụng chính sách đầu-cuối.",
        f"Bộ {n_tests} kiểm thử tự động chạy được trên máy sạch, không cần quyền admin.",
        "Giữ đúng triết lý đồng hành: không chế độ ẩn, 7 trường dữ liệu, trẻ xem được mọi thứ phụ huynh xem.",
    ])
    doc.add_heading("9.2. Hạn chế", level=2)
    add_bullets(doc, [
        "Lọc DNS không chặn được truy cập trực tiếp bằng địa chỉ IP và DoH tới máy chủ lạ chưa có trong danh sách.",
        "Chưa có bộ lọc WFP hay proxy theo đường dẫn; không phân biệt được từng trang trong cùng một tên miền.",
        "Agent chỉ hỗ trợ Windows 10/11 x64; Safe Mode và khởi động từ USB phải dựa vào thiết lập UEFI của gia đình.",
        "Phân loại tên miền dựa trên danh mục tĩnh 235 mục; tên miền mới mặc định thuộc nhóm chưa phân loại.",
        "Chưa có xác thực hai yếu tố TOTP cho phụ huynh (điểm cộng của đề bài).",
    ])
    doc.add_heading("9.3. Hướng phát triển", level=2)
    add_bullets(doc, [
        "Thêm bộ lọc WFP chặn cổng 853 (DoT) và các dải IP của dịch vụ DoH/VPN phổ biến.",
        "TOTP cho phụ huynh, thông báo đẩy khi trẻ gửi yêu cầu.",
        "Cơ chế thưởng giờ khi hoàn thành nhiệm vụ do phụ huynh giao, nhắc nghỉ mắt 20-20-20 trên Tray.",
        "Cập nhật danh mục tên miền định kỳ có chữ ký, để agent nhận danh mục mới mà vẫn kiểm được toàn vẹn.",
    ])

    doc.add_heading("TÀI LIỆU THAM KHẢO", level=1)
    add_numbered(doc, [
        "Chính phủ Việt Nam, Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân, 2023.",
        "Quốc hội Việt Nam, Luật Trẻ em số 102/2016/QH13, 2016.",
        "P. Mockapetris, RFC 1034 và RFC 1035: Domain Names, IETF, 1987.",
        "D. Eastlake, A. Panitz, RFC 2606: Reserved Top Level DNS Names, IETF, 1999.",
        "P. Hoffman, P. McManus, RFC 8484: DNS Queries over HTTPS (DoH), IETF, 2018.",
        "H. Krawczyk, M. Bellare, R. Canetti, RFC 2104: HMAC, IETF, 1997.",
        "A. Biryukov, D. Dinu, D. Khovratovich, S. Josefsson, RFC 9106: Argon2, IRTF, 2021.",
        "OWASP Foundation, Application Security Verification Standard 4.0.3.",
        "Microsoft, tài liệu Windows Services, Session 0 Isolation, WTS API, DPAPI (learn.microsoft.com).",
        "Tài liệu FastAPI, SQLAlchemy 2.0, dnslib, psutil, pywin32.",
    ])

    # ======================= CHAPTER 10: CONTRIBUTION =======================
    doc.add_heading("PHÂN CÔNG CÔNG VIỆC VÀ TỰ ĐÁNH GIÁ ĐÓNG GÓP", level=1)
    para(doc,
         "Theo mục 8 của đề bài, nhóm tự điền họ tên, MSSV và tỷ lệ phần trăm đóng góp (tổng 100%) trước khi nộp. Cột nhiệm vụ dưới đây "
         "là phân chia theo phân hệ; nhóm sửa lại cho đúng thực tế.")
    add_table(doc, ["Thành viên", "MSSV", "Nhiệm vụ phụ trách chính", "Đóng góp (%)"], [
        ["[ĐIỀN HỌ TÊN 1]", "[ĐIỀN MSSV 1]", "EC Agent: Service, ScreenTime, AppController, IPC Named Pipe, Tray UI", "[ĐIỀN %]"],
        ["[ĐIỀN HỌ TÊN 2]", "[ĐIỀN MSSV 2]", "DNS proxy, Suffix Trie, SafeSearch, NetworkGuard, BrowserPolicy, phụ lục M1-M6, đo hiệu năng", "[ĐIỀN %]"],
        ["[ĐIỀN HỌ TÊN 3]", "[ĐIỀN MSSV 3]", "EC Server (FastAPI, SQLite WAL, Argon2id, HMAC, WebSocket), Web Dashboard, báo cáo", "[ĐIỀN %]"],
    ], [1.6, 1.0, 3.0, 0.9])
    para(doc, "Tự đánh giá mức độ hoàn thành theo từng hạng mục (nhóm điều chỉnh nếu cần):")
    add_table(doc, ["Hạng mục", "Mức độ hoàn thành", "Ghi chú"], [
        ["F1 Quản lý thời gian", "Đủ BẮT BUỘC + NÊN CÓ", "Chưa có thưởng giờ theo nhiệm vụ"],
        ["F2 Lọc ứng dụng/website", "Đủ BẮT BUỘC + NÊN CÓ", "Chưa có WFP / proxy theo đường dẫn"],
        ["F3 Báo cáo và minh bạch", "Đủ BẮT BUỘC + NÊN CÓ", "Xuất CSV; in hoặc lưu PDF từ trình duyệt"],
        ["F4 Quản trị từ xa", "Đủ BẮT BUỘC + NÊN CÓ + CÓ THÌ TỐT", "Tạm nghỉ 2 giờ"],
        ["F5 Bảo mật", "Đủ yêu cầu tối thiểu", "Chưa có TOTP"],
        ["M1-M6", "Đủ 6 mục", "Ảnh Wireshark chụp trên máy demo"],
        ["Sản phẩm nộp (mục 8)", "[NHÓM TỰ ĐÁNH GIÁ]", "Video demo do nhóm quay"],
    ], [2.0, 2.3, 2.2])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT_PATH))
    return OUT_PATH


if __name__ == "__main__":
    print(f"Generated: {build_report()}")
