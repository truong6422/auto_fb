"""Trích URL ảnh minh hoạ từ một entry RSS.

Mỗi báo nhét ảnh vào một chỗ khác nhau, không có chuẩn chung:
  media:content / media:thumbnail  — VnExpress, Thanh Niên
  enclosure                        — một số nguồn quốc tế
  thẻ <img> trong description      — Dân Trí, Tuổi Trẻ, VietnamNet
Nên phải dò lần lượt cả bốn chỗ.

Chỉ lấy URL, KHÔNG tải ảnh về. Facebook nhận tham số `url` ở endpoint /photos và tự đi
tải — server mình không tốn băng thông, RAM hay dung lượng đĩa.
"""

import re
from urllib.parse import urlparse

_IMG_TAG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)

# Ảnh nhỏ thường là logo, icon chia sẻ, ảnh tracking — không dùng làm ảnh bài.
_SKIP_PATTERNS = ("logo", "icon", "avatar", "1x1", "pixel", "spacer", "blank")


def _looks_usable(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    path = urlparse(url).path.lower()
    if any(bad in path for bad in _SKIP_PATTERNS):
        return False
    return True


def _from_html(value) -> str | None:
    """Bóc thẻ <img> đầu tiên trong đoạn HTML của description."""
    if isinstance(value, list):
        value = value[0].get("value", "") if value else ""
    match = _IMG_TAG_RE.search(value or "")
    return match.group(1) if match else None


# CDN báo Việt nhét kích thước thu nhỏ vào đường dẫn. Bỏ đoạn đó ra thì lấy được ảnh gốc.
# Không xử lý thì Thể thao & Văn hoá chỉ cho ảnh 245x163 — đăng lên Facebook là mờ tịt.
_RESIZE_SEGMENTS = (
    re.compile(r"/zoom/\d+_\d+/"),      # thethaovanhoa, thanhnien
    re.compile(r"/thumb_w/\d+/"),       # tuoitre
    re.compile(r"/resize_\d+x\d+/"),
    re.compile(r"/crop/\d+x\d+/"),
)


def upgrade_to_full_size(url: str) -> str:
    """Đổi URL ảnh thu nhỏ về bản kích thước gốc."""
    for pattern in _RESIZE_SEGMENTS:
        url = pattern.sub("/", url)
    return url


def extract_image_url(entry) -> str | None:
    """Trả về URL ảnh của bài, hoặc None nếu nguồn không kèm ảnh."""
    for media in (entry.get("media_content") or []) + (entry.get("media_thumbnail") or []):
        url = media.get("url")
        if _looks_usable(url):
            return upgrade_to_full_size(url)

    for enclosure in entry.get("enclosures") or []:
        url = enclosure.get("href")
        if _looks_usable(url) and enclosure.get("type", "").startswith("image"):
            return upgrade_to_full_size(url)

    for field in ("summary", "description", "content"):
        url = _from_html(entry.get(field))
        if _looks_usable(url):
            return upgrade_to_full_size(url)

    return None
