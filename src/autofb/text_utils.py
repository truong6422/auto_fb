"""Chuẩn hoá văn bản và so khớp tiêu đề (dùng cho chống trùng lớp 2)."""

import html
import re
import unicodedata
from difflib import SequenceMatcher

_TAG_RE = re.compile(r"<[^>]+>")
_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

# Từ không giúp phân biệt tin -> bỏ khi so khớp. Viết dạng ĐÃ bỏ dấu vì lọc chạy sau
# bước strip_accents.
_STOPWORDS = {
    # Chỉ hư từ. KHÔNG bỏ các từ như "lịch thi đấu" / "BXH" ở đây: chúng trông rập khuôn
    # nhưng lại là thứ phân biệt "Lịch thi đấu vòng 3" với "BXH vòng 3" — bỏ đi là gộp
    # nhầm hai tin khác nhau. Nhóm bài đó xử lý bằng content_filter.is_utility_article().
    # KHÔNG thêm "da"/"la"/"co"/"va": sau khi bỏ dấu chúng đụng "đá", "lá", "cỏ", "vá".
    # Mất chữ "đá" là hỏng luôn từ khoá "bong da" của bộ phân loại môn.
    "cua", "cho", "voi", "trong", "khi", "duoc", "se", "cac", "nhung",
    "the", "a", "an", "of", "in", "for", "to", "and",
}

# Số từ mang thông tin tối thiểu phải trùng nhau mới coi là cùng tin.
# Chặn trường hợp hai tiêu đề rất ngắn khớp nhau chỉ vì có 1-2 từ chung.
_MIN_SHARED_WORDS = 3


def strip_html(text: str) -> str:
    """Gỡ thẻ HTML và giải mã entity. RSS description thường lẫn cả hai."""
    if not text:
        return ""
    return _SPACE_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", text))).strip()


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt về ASCII.

    Phải thay 'đ' -> 'd' THỦ CÔNG trước khi chạy NFD: 'đ' (U+0111) là một ký tự độc lập,
    không phải 'd' + dấu, nên NFD không tách nó ra. Bỏ bước này thì 'bóng đá' cho ra
    'bong đa' và mọi từ khoá viết bằng 'd' đều không khớp.
    """
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_title(title: str) -> str:
    """Đưa tiêu đề về dạng so khớp được: bỏ dấu, bỏ ký tự đặc biệt, bỏ stopword.

    Bỏ dấu để hai bản 'HLV Kim Sang-sik' / 'HLV Kim Sang Sik' khớp nhau.
    """
    text = strip_accents(strip_html(title).lower())
    text = _NON_WORD_RE.sub(" ", text)
    words = [w for w in text.split() if w not in _STOPWORDS]
    return " ".join(words)


def title_similarity(a: str, b: str) -> float:
    """Độ giống giữa hai tiêu đề ĐÃ chuẩn hoá, 0.0 → 1.0.

    Kết hợp hai tín hiệu vì mỗi cái hụt một kiểu:
      - tỷ lệ từ chung: bắt được cùng tin dù báo đảo thứ tự câu chữ
      - SequenceMatcher: bắt được khác biệt nhỏ mà tỷ lệ từ chung bỏ qua

    Mẫu số dùng min(len) chứ không phải hợp: hai báo tả cùng một tin thường đặt tiêu đề
    dài ngắn rất khác nhau, dùng hợp sẽ tách nhầm. Đổi lại phải chặn bằng _MIN_SHARED_WORDS
    và danh sách stopword rập khuôn ở trên.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    words_a, words_b = set(a.split()), set(b.split())
    shared = words_a & words_b
    if len(shared) < _MIN_SHARED_WORDS:
        return 0.0

    overlap = len(shared) / min(len(words_a), len(words_b))
    ratio = SequenceMatcher(None, a, b).ratio()
    return max(overlap, ratio)


# Báo Việt hay chèn tên toà soạn vào đầu phần tóm tắt: "(Dân trí) - ", "TPO - "...
# Bê nguyên lên Page mình thì lộ ngay là copy. Cắt ở đây, nguồn vẫn được ghi ở cuối bài.
_SOURCE_PREFIX_RE = re.compile(
    r"^\s*(?:\([^)]{2,30}\)|[A-ZĐÀ-Ỹ][A-ZĐÀ-Ỹ0-9.\s]{1,18})\s*[-–—:]\s*",
)


def clean_summary(text: str) -> str:
    """Bỏ tiền tố tên toà soạn ở đầu tóm tắt RSS."""
    return _SOURCE_PREFIX_RE.sub("", strip_html(text), count=1).strip()


def truncate_words(text: str, max_words: int) -> str:
    """Cắt bớt phần trích để không lấy quá nhiều nội dung của nguồn."""
    words = strip_html(text).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",;:") + "…"
