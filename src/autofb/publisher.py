"""M7 — đăng bài đã duyệt lên Fanpage, rồi đăng link affiliate xuống comment.

Nguyên tắc quan trọng: TRẠNG THÁI BÀI VÀ TRẠNG THÁI COMMENT TÁCH RIÊNG.
Bài lên thành công mà comment lỗi thì bài đã public rồi — đăng lại bài là ra hai bài trùng.
Chỉ retry riêng phần comment.
"""

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .card_renderer import FontMissingError, render_card, title_of
from .config import CardSettings, load_config
from .facebook import AuthError, FacebookClient, PermanentError, TransientError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (2, 6)


@dataclass
class PublishReport:
    posted: int = 0
    commented: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    # Khác None nghĩa là lượt bị dừng vì token/quyền, KHÔNG phải vì bài hỏng.
    auth_broken: str | None = None

    def summary(self) -> str:
        base = f"đăng {self.posted} bài | {self.commented} comment | lỗi {self.failed}"
        return base + (f" | DỪNG: {self.auth_broken}" if self.auth_broken else "")


def _with_retry(action, what: str):
    """Thử lại lỗi tạm thời; lỗi vĩnh viễn thì ném ra ngay, không phí lượt."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return action()
        except TransientError as exc:
            if attempt == MAX_ATTEMPTS:
                raise
            delay = BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)]
            logger.warning("%s lỗi tạm thời (lần %d): %s — thử lại sau %ds",
                           what, attempt, exc, delay)
            time.sleep(delay)


def build_comment(post: sqlite3.Row) -> str:
    """Nội dung comment đầu tiên dưới bài.

    Link bài gốc đặt ở đây chứ không đặt trong bài: bài có link ra ngoài bị phân phối kém,
    mà người muốn đọc đầy đủ vẫn bấm được, và nguồn vẫn được dẫn đàng hoàng.
    """
    keys = post.keys()
    parts = []

    source_url = post["source_url"] if "source_url" in keys else None
    if source_url:
        parts.append(f"Đọc bài gốc: {source_url}")

    if post["affiliate_link"]:
        parts.append(post["affiliate_link"])

    return "\n\n".join(parts)


def _publish_comment(
    client: FacebookClient, conn: sqlite3.Connection, post: sqlite3.Row, report: PublishReport
) -> None:
    """Đăng comment: link bài gốc + link affiliate. Lỗi ở đây KHÔNG làm bài thành thất bại."""
    message = build_comment(post)
    if not message:
        conn.execute("UPDATE post SET comment_status = 'none' WHERE id = ?", (post["id"],))
        return

    fb_post_id = conn.execute(
        "SELECT fb_post_id FROM post WHERE id = ?", (post["id"],)
    ).fetchone()["fb_post_id"]

    try:
        _with_retry(lambda: client.publish_comment(fb_post_id, message), "Đăng comment")
        conn.execute("UPDATE post SET comment_status = 'posted' WHERE id = ?", (post["id"],))
        report.commented += 1
    except (TransientError, PermanentError) as exc:
        # Bài đã lên rồi, chỉ comment hỏng -> đánh dấu để chạy lại riêng phần comment.
        conn.execute(
            "UPDATE post SET comment_status = 'failed', note = ? WHERE id = ?",
            (f"Comment lỗi: {exc}", post["id"]),
        )
        report.errors.append(f"#{post['id']} comment: {exc}")
        logger.error("Bài #%s đã đăng nhưng comment lỗi: %s", post["id"], exc)


def _field(post: sqlite3.Row, name: str):
    """Đọc cột có thể chưa tồn tại trên DB cũ. sqlite3.Row ném KeyError chứ không trả None."""
    return post[name] if name in post.keys() else None


def build_media(
    client: FacebookClient, post: sqlite3.Row, card: CardSettings, report: PublishReport
) -> list[str]:
    """Upload trước các ảnh của bài, trả về danh sách photo_id theo đúng thứ tự hiển thị.

    Thứ tự có ý nghĩa: card tiêu đề PHẢI đứng đầu. Facebook lấy ảnh đầu tiên làm ảnh
    lớn nhất trên feed — để ảnh báo lên trước thì người lướt vẫn không đọc được tiêu đề,
    tức là mất đúng cái lý do làm card.

    Lỗi ở đây không làm hỏng bài: thiếu ảnh nào thì đăng không có ảnh đó.
    """
    photo_ids: list[str] = []

    if card.enabled:
        try:
            image = render_card(
                title_of(post["content"]), card,
                seed=post["id"], source_name=_field(post, "image_credit"),
            )
            photo_ids.append(
                _with_retry(lambda: client.upload_unpublished_photo_bytes(image), "Upload card")
            )
        except (ValueError, FontMissingError, OSError) as exc:
            report.errors.append(f"#{post['id']} card: {exc}")
            logger.error("Bài #%s không vẽ được card: %s", post["id"], exc)
        except AuthError:
            raise
        except (TransientError, PermanentError) as exc:
            report.errors.append(f"#{post['id']} upload card: {exc}")
            logger.error("Bài #%s upload card lỗi: %s", post["id"], exc)

    image_url = _field(post, "image_url")
    if image_url:
        try:
            photo_ids.append(
                _with_retry(lambda: client.upload_unpublished_photo_url(image_url), "Upload ảnh")
            )
        except AuthError:
            raise
        except (TransientError, PermanentError) as exc:
            # Link ảnh của báo chết là chuyện thường. Bài vẫn lên với card tiêu đề.
            logger.warning("Bài #%s bỏ ảnh nguồn (%s): %s", post["id"], image_url, exc)

    return photo_ids


def publish_one(
    client: FacebookClient, conn: sqlite3.Connection, post: sqlite3.Row,
    report: PublishReport, card: CardSettings | None = None,
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    card = card if card is not None else load_config().card
    image_url = _field(post, "image_url")
    photo_ids = build_media(client, post, card, report)

    def send():
        # Bài 2 ảnh: card tiêu đề + ảnh gốc của báo. Đây là cách gần nhất với bài
        # "nền màu" của Facebook — Graph API không có tham số tạo bài nền màu thật.
        if photo_ids:
            return client.publish_with_photos(post["content"], photo_ids)
        # Không dựng được card thì quay về cách cũ, đừng để bài không đăng được.
        if image_url:
            return client.publish_photo_url(image_url, post["content"])
        return client.publish_post(post["content"])

    try:
        fb_post_id = _with_retry(send, "Đăng bài")
    except AuthError as exc:
        # Token/quyền hỏng: bài này không có lỗi gì, giữ nguyên 'approved' để đăng lại
        # sau khi cấp token mới. Ném tiếp để publish_approved dừng cả lượt.
        conn.execute("UPDATE post SET note = ? WHERE id = ?",
                     (f"Chưa đăng được — {exc}", post["id"]))
        report.errors.append(f"#{post['id']} bài: {exc}")
        raise
    except (TransientError, PermanentError) as exc:
        conn.execute(
            "UPDATE post SET status = 'failed', note = ? WHERE id = ?",
            (f"Đăng bài lỗi: {exc}", post["id"]),
        )
        report.failed += 1
        report.errors.append(f"#{post['id']} bài: {exc}")
        return

    conn.execute(
        "UPDATE post SET status = 'posted', fb_post_id = ?, posted_at = ?, note = NULL"
        " WHERE id = ?",
        (fb_post_id, now_iso, post["id"]),
    )
    conn.execute(
        "UPDATE topic_cluster SET posted = 1 WHERE id = ?", (post["cluster_id"],)
    )
    report.posted += 1

    _publish_comment(client, conn, post, report)


def due_manual_posts(conn: sqlite3.Connection, limit: int = 1) -> list[sqlite3.Row]:
    """Bài tự soạn đã tới giờ hẹn. Ưu tiên hơn bản tin tự động.

    Người dùng chọn ngày giờ cho bài review/affiliate thì phải đăng đúng lúc đó,
    không thể để bản tin thời sự chen vào chiếm suất."""
    now = datetime.now(timezone.utc).isoformat()
    return conn.execute(
        "SELECT * FROM post WHERE status = 'approved' AND origin = 'manual'"
        " AND scheduled_at IS NOT NULL AND scheduled_at <= ?"
        " ORDER BY scheduled_at ASC LIMIT ?",
        (now, limit),
    ).fetchall()


def publish_approved(
    client: FacebookClient, conn: sqlite3.Connection, limit: int = 1,
    card: CardSettings | None = None,
) -> PublishReport:
    """Đăng bài chờ. Bài tự soạn đến hạn đi trước, sau đó mới tới bản tin tự động."""
    report = PublishReport()
    card = card if card is not None else load_config().card

    rows = due_manual_posts(conn, limit)
    if len(rows) < limit:
        rows = list(rows) + list(conn.execute(
            "SELECT * FROM post WHERE status = 'approved' AND origin = 'auto'"
            " ORDER BY id ASC LIMIT ?", (limit - len(rows),)
        ).fetchall())

    for post in rows:
        try:
            publish_one(client, conn, post, report, card)
        except AuthError as exc:
            # Mọi bài còn lại cũng sẽ hỏng y hệt. Dừng ở đây, hàng chờ giữ nguyên
            # cho tới khi người dùng cấp token mới.
            conn.commit()
            report.auth_broken = str(exc)
            logger.error("Dừng lượt đăng — token/quyền hỏng: %s", exc)
            return report
        conn.commit()

    return report


def retry_failed_comments(client: FacebookClient, conn: sqlite3.Connection) -> PublishReport:
    """Chạy lại riêng phần comment cho bài đã lên nhưng comment hỏng. KHÔNG đăng lại bài."""
    report = PublishReport()
    rows = conn.execute(
        "SELECT * FROM post WHERE status = 'posted' AND comment_status = 'failed'"
    ).fetchall()

    for post in rows:
        _publish_comment(client, conn, post, report)
        conn.commit()

    return report
