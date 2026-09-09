"""Đoán môn thể thao cho bài từ feed tổng hợp (sport: mixed).

Vì sao cần: tiêu đề báo Việt gần như không bao giờ chứa tên môn. Khảo sát 1214 tiêu đề
từ 4 nguồn chỉ thấy 8 tiêu đề có chữ "bóng đá", 0 tiêu đề có "tennis" hay "cầu lông".
Cái thực sự xuất hiện là tên giải và tên người: "V-League", "U20 Việt Nam", "Alcaraz",
"US Open". Nên bảng từ khoá dưới đây bám vào giải đấu và thực thể, không bám tên môn.

Feed đã khai báo sport cụ thể trong config thì KHÔNG chạy qua đây.
Không khớp gì -> "other". Thà để "other" còn hơn gán bừa.
"""

import re

from .text_utils import normalize_title

# Từ khoá đã bỏ dấu, vì so khớp trên chuỗi đã chuẩn hoá.
# Thứ tự trong dict quyết định độ ưu tiên khi một bài khớp nhiều môn.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "pickleball": ("pickleball",),
    "badminton": ("cau long", "badminton", "thomas uber", "all england", "bwf"),
    "tennis": (
        "tennis", "quan vot", "us open", "wimbledon", "roland garros", "australian open",
        "atp", "wta", "djokovic", "alcaraz", "sinner", "nadal", "federer",
    ),
    "cycling": ("xe dap", "cycling", "tour de france", "duong dua xanh", "cuoc dua"),
    "running": (
        "chay bo", "marathon", "running", "dien kinh", "duong chay", "half marathon",
        "ultra trail", "vdv chay", "giai chay", "buoc chay", "run for", "duong dua",
    ),
    "gym": ("gym", "the hinh", "fitness", "tap luyen", "cu ta", "thap hinh"),
    "basketball": (
        "bong ro", "basketball", "nba", "vba", "fiba", "euroleague",
        "lakers", "celtics", "warriors", "lebron", "curry", "saigon heat",
    ),
    "football": (
        # Tên môn và giải
        "bong da", "v league", "vleague", "world cup", "premier league", "ngoai hang anh",
        "la liga", "serie a", "bundesliga", "champions league", "cup c1", "asean cup",
        "aff cup", "euro", "copa america", "fifa", "afc", "vong loai",
        # Đội tuyển trẻ. Tiêu đề viết cả "U20" lẫn "U.20" -> sau chuẩn hoá thành "u 20".
        "u23", "u20", "u19", "u17", "u 23", "u 20", "u 19", "u 17",
        # Vai trò và thuật ngữ trong bài bóng đá
        "hlv", "clb", "tuyen viet nam", "doi tuyen", "cau thu", "thu quan", "thu mon",
        "hau ve", "tien dao", "tien ve", "ban thang", "ghi ban", "chuyen nhuong",
        # Tên riêng xuất hiện dày trong tin tiếng Việt
        "man city", "arsenal", "real madrid", "barca", "barcelona", "liverpool", "chelsea",
        "tottenham", "mu", "man utd", "man united", "messi", "ronaldo", "kim sang sik", "park hang seo",
    ),
}

# Môn không nằm trong 8 môn mục tiêu nhưng hay xuất hiện -> nhận diện để KHÔNG gán nhầm
# vào football (nhiều tin ASIAD/SEA Games lẫn đủ môn trong một bài).
_NOT_TARGET_SPORTS = (
    "bong chuyen", "bong ban", "co vua", "boxing", "vo thuat", "esports",
    "billiards", "bi a", "the duc dung cu", "bơi", "boi loi", "judo", "karate", "taekwondo",
)


def _matches(keyword: str, haystack: str) -> bool:
    """So khớp theo RANH GIỚI TỪ, không phải chuỗi con.

    Khớp chuỗi con gây lỗi thật: "bi a" (bi-a) nằm lọt trong "Xa-bi A-lonso",
    làm tin Arsenal - Chelsea bị xếp vào môn khác.
    """
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", haystack) is not None


def classify_sport(title: str, summary: str = "") -> str:
    """Trả về mã môn, hoặc 'other' nếu không đủ tự tin."""
    haystack = normalize_title(f"{title} {summary}")
    if not haystack:
        return "other"

    # Môn ngoài phạm vi CHỈ xét trên tiêu đề. Xét cả tóm tắt thì quá rộng: bài
    # "Pickleball là môn gây chấn thương tệ nhất nhóm cầm vợt" có nhắc "bóng bàn"
    # trong phần so sánh, và bị loại oan dù tiêu đề nói rõ là pickleball.
    headline = normalize_title(title)
    if any(_matches(kw, headline) for kw in _NOT_TARGET_SPORTS):
        return "other"

    for sport, keywords in _KEYWORDS.items():
        if any(_matches(kw, haystack) for kw in keywords):
            return sport
    return "other"


def resolve_sport(declared_sport: str, title: str, summary: str = "") -> str:
    """Feed khai báo môn cụ thể thì tin theo feed; chỉ 'mixed' mới đoán."""
    if declared_sport and declared_sport != "mixed":
        return declared_sport
    return classify_sport(title, summary)
