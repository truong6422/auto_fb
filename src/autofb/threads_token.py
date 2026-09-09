"""Vòng đời token Threads — tự gia hạn, vì để quên là mất hẳn.

Khác hẳn Facebook. Page token sinh từ user token dài hạn thì sống mãi; token Threads
sống **60 ngày**, và nếu để quá hạn thì KHÔNG gia hạn được nữa — phải đi xin lại từ
đầu bằng tay qua trình duyệt. Hệ thống này chạy không người trông, nên phải tự gia hạn.

Token mới lưu vào bảng `setting` chứ không ghi ngược ra .env: file .env gắn vào
container ở chế độ chỉ đọc, và một tiến trình nền tự sửa file bí mật là thứ không nên có.

.env vẫn là nơi bắt đầu. Đổi token trong .env thì lượt sau hệ thống nhận ra hạt giống
đã khác và dùng bản mới — nếu không, sửa .env sẽ chẳng có tác dụng gì vì DB cứ giữ mãi
token cũ đã gia hạn.
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from .facebook import PermanentError, TransientError
from .settings import current_value
from .threads import ThreadsClient

logger = logging.getLogger(__name__)

SEED_KEY = "threads_token_seed"          # giá trị .env mà bản trong DB sinh ra từ đó
TOKEN_KEY = "threads_token"              # token đang dùng thật
REFRESHED_KEY = "threads_token_refreshed_at"

# Gia hạn sớm hơn hạn 60 ngày rất nhiều. Gia hạn được nhiều lần không mất gì, còn để
# trễ một lần là hỏng vĩnh viễn — chọn phía an toàn.
REFRESH_EVERY_DAYS = 7
# Meta không cho gia hạn token chưa đủ 24 giờ tuổi.
MIN_AGE_HOURS = 25


def _get(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


def _set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO setting (key, value, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
        " updated_at = excluded.updated_at",
        (key, value, datetime.now(timezone.utc).isoformat()),
    )


def active_token(conn: sqlite3.Connection) -> str:
    """Token Threads đang có hiệu lực. Rỗng nghĩa là chưa cấu hình."""
    seed = current_value("THREADS_ACCESS_TOKEN")
    if not seed:
        return ""

    if seed != _get(conn, SEED_KEY):
        # .env vừa đổi (lần đầu cấu hình, hoặc người dùng dán token mới) — bắt đầu lại
        # từ giá trị đó và quên bản đã gia hạn của token cũ.
        _set(conn, SEED_KEY, seed)
        _set(conn, TOKEN_KEY, seed)
        _set(conn, REFRESHED_KEY, datetime.now(timezone.utc).isoformat())
        conn.commit()
        return seed

    return _get(conn, TOKEN_KEY) or seed


def maybe_refresh(conn: sqlite3.Connection) -> bool:
    """Gia hạn nếu tới hạn. Trả về True khi vừa gia hạn xong.

    Lỗi ở đây không được ném ra ngoài: gia hạn hỏng thì token cũ vẫn còn dùng được
    nhiều tuần nữa, không có lý do gì để làm chết lượt đăng bài.
    """
    token = active_token(conn)
    if not token:
        return False

    stamp = _get(conn, REFRESHED_KEY)
    if not stamp:
        return False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(stamp)
    except ValueError:
        age = timedelta(days=REFRESH_EVERY_DAYS)
    if age < timedelta(days=REFRESH_EVERY_DAYS) or age < timedelta(hours=MIN_AGE_HOURS):
        return False

    user_id = current_value("THREADS_USER_ID")
    try:
        fresh = ThreadsClient(user_id, token).refresh_token()
    except (TransientError, PermanentError) as exc:
        logger.warning("Chưa gia hạn được token Threads: %s", exc)
        return False

    _set(conn, TOKEN_KEY, fresh)
    _set(conn, REFRESHED_KEY, datetime.now(timezone.utc).isoformat())
    conn.commit()
    logger.info("Đã gia hạn token Threads thêm 60 ngày")
    return True
