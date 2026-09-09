"""Tải logo đội bóng để vẽ lên card.

Logo lấy thẳng từ máy chủ ảnh của premierleague.com và uefa.com — đúng thứ hai
trang đó dùng, nền trong suốt, không vướng bản quyền như ảnh chụp của báo.

NHỚ TRONG RAM, KHÔNG GHI ĐĨA. Logo không bao giờ đổi nên nhớ lại là an toàn tuyệt
đối; một card bảng xếp hạng cần 12-20 logo, vẽ lại mỗi lần mở trang mà lần nào cũng
tải là quá chậm. 20 logo cỡ 60px chỉ tốn khoảng 300KB bộ nhớ.

Tải hỏng KHÔNG được làm hỏng card: thiếu logo thì card vẫn đọc được, còn ném lỗi ra
là mất cả bài. Mọi hàm ở đây trả None khi có sự cố.
"""

import io
import logging
from functools import lru_cache

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

TIMEOUT = 12
PREMIER_LEAGUE_BADGE = "https://resources.premierleague.com/premierleague/badges/100/{code}.png"
UEFA_LOGO = "https://img.uefa.com/imgml/TP/teams/logos/240x240/{code}.png"


def premier_league_url(opta_id: str | None) -> str:
    """opta_id có dạng "t43". Rỗng thì trả chuỗi rỗng — card sẽ vẽ không logo."""
    return PREMIER_LEAGUE_BADGE.format(code=opta_id) if opta_id else ""


def uefa_url(team_id: str | None) -> str:
    return UEFA_LOGO.format(code=team_id) if team_id else ""


@lru_cache(maxsize=128)
def _download(url: str) -> bytes | None:
    try:
        response = httpx.get(url, timeout=TIMEOUT,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; AutoFB/1.0)"})
        response.raise_for_status()
        return response.content
    except httpx.HTTPError as exc:
        logger.warning("Không tải được logo %s: %s", url, exc)
        return None


@lru_cache(maxsize=256)
def load(url: str, size: int) -> Image.Image | None:
    """Logo đã thu về đúng cỡ, nền trong suốt. None nếu không lấy được.

    Nhớ theo cặp (url, size) vì cùng một logo dùng ở hai cỡ khác nhau: dòng trong
    bảng thì nhỏ, card kết quả thì to.
    """
    if not url:
        return None

    raw = _download(url)
    if raw is None:
        return None

    try:
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
    except OSError as exc:
        logger.warning("Logo hỏng %s: %s", url, exc)
        return None

    # thumbnail giữ nguyên tỉ lệ — logo tròn và logo vuông không bị bóp méo.
    image.thumbnail((size, size), Image.LANCZOS)
    return image


def prefetch(urls: list[str], size: int) -> None:
    """Tải trước một loạt logo. Gọi trước khi vẽ card để lỗi mạng lộ ra sớm."""
    for url in urls:
        load(url, size)
