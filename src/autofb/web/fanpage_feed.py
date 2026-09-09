"""Mục "Đã đăng" đọc thẳng từ Fanpage thay vì đọc lại bản sao trong SQLite.

Trước đây màn hình này hiện lại chính những dòng mình đã ghi vào DB — một bản sao mờ
hơn bản gốc. Facebook biết bài thực sự hiện ra sao và đã có bao nhiêu cảm xúc, bình
luận, chia sẻ; DB chỉ biết mình đã gửi đi cái gì. Lấy từ Graph API vừa đúng hơn, vừa
cho phép dọn nội dung bài cũ khỏi DB mà không mất gì (xem cleanup.py).

Nhớ tạm 60 giây. Mỗi lần mở trang mà gọi lại Graph API thì màn hình đợi cả giây và
tốn hạn ngạch API vô ích — số lượt thả tim không đổi từng giây.
"""

import logging
import time

from ..facebook import FacebookClient, PagePost, PermanentError, TransientError
from ..settings import load_facebook_settings

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60

# Số bài kéo về mỗi lần. Đủ để lướt lại vài ngày gần nhất — muốn xem xa hơn thì mở
# thẳng Fanpage, ở đó cuộn thoải mái hơn màn hình này.
LIMIT = 25

# (thời điểm hết hạn, danh sách bài). Chỉ có một Fanpage nên một ô nhớ là đủ.
_cache: tuple[float, list[PagePost]] = (0.0, [])


def recent_posts(limit: int = LIMIT) -> tuple[list[PagePost], str]:
    """Trả về (danh sách bài, lời báo lỗi). Lỗi rỗng nghĩa là lấy được.

    Không ném lỗi ra ngoài: Facebook hỏng thì màn hình quản trị vẫn phải mở được để
    người dùng còn thấy hàng chờ và bấm tạm dừng.
    """
    global _cache

    expires, cached = _cache
    if cached and time.monotonic() < expires:
        return cached, ""

    fb = load_facebook_settings()
    if not fb.configured:
        return [], "Chưa kết nối Fanpage — điền token vào file .env"

    client = FacebookClient(fb.page_id, fb.access_token, fb.api_version)
    try:
        posts = client.recent_posts(limit)
    except PermanentError as exc:
        return cached, f"Không đọc được bài trên Fanpage: {exc}"
    except TransientError as exc:
        logger.warning("Tạm thời không lấy được feed Fanpage: %s", exc)
        return cached, "Không kết nối được tới Facebook"

    _cache = (time.monotonic() + CACHE_SECONDS, posts)
    return posts, ""


def forget() -> None:
    """Bỏ nhớ tạm — gọi sau khi vừa đăng bài để bài mới hiện ra ngay."""
    global _cache
    _cache = (0.0, [])
