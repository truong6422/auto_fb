"""Nhận diện bài không đáng đăng lại lên Fanpage.

Nhóm "bài tiện ích": lịch thi đấu, bảng xếp hạng, kết quả, link xem trực tiếp.
Đây là bảng dữ liệu chứ không phải tin — giá trị nằm ở trang nguồn, đăng lại lên Page
thì vừa không có nội dung, vừa lỗi thời sau vài giờ.

Chúng còn phá khâu gom nhóm: tiêu đề rập khuôn theo mẫu cố định nên hai tin hoàn toàn
khác nhau vẫn khớp rất cao ("Lịch thi đấu vòng 3 Ngoại hạng Anh" vs "BXH vòng 3 Ngoại
hạng Anh" khớp 1.00). Tách riêng từ đầu thì khỏi phải chỉnh ngưỡng so khớp cho vừa cả hai.

Vẫn LƯU vào raw_article (bài thô là nguồn sự thật), chỉ đánh dấu để khâu chọn tin bỏ qua.
"""

from .text_utils import strip_accents, strip_html

_UTILITY_PATTERNS = (
    "lich thi dau",
    "lich truc tiep",
    "bang xep hang",
    "bxh",
    "ket qua bong da",
    "ket qua thi dau",
    "truc tiep",
    "link xem",
    "xem truc tiep",
    "nhan dinh ty le",
    "ty le keo",
    "doi hinh ra san",
)


def is_utility_article(title: str, summary: str = "") -> bool:
    """True nếu bài chỉ là bảng dữ liệu/lịch, không phải tin để đăng lại."""
    haystack = strip_accents(strip_html(f"{title} {summary}").lower())
    return any(pattern in haystack for pattern in _UTILITY_PATTERNS)
