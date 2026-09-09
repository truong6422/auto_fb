"""Xoá dữ liệu cũ. Mini server ổ nhỏ, mà MVP chỉ cần đăng bài chứ không cần lịch sử.

Giữ lại `fb_post_id` của bài đã đăng lâu hơn phần còn lại: đó là đường lui để sau này
bật thu Insights (Phase 2). Xoá mất thì không lấy lại được số liệu của bài cũ.
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


@dataclass
class CleanupReport:
    articles: int = 0
    clusters: int = 0
    posts: int = 0
    trimmed: int = 0

    def summary(self) -> str:
        base = f"dọn {self.articles} tin, {self.clusters} chủ đề, {self.posts} bài"
        return base + (f", rút gọn {self.trimmed} bài đã đăng" if self.trimmed else "")


def run_cleanup(conn: sqlite3.Connection, retention_days: int) -> CleanupReport:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    report = CleanupReport()

    # Bài chưa đăng và đã quá hạn: tin thể thao cũ vài ngày thì không còn giá trị đăng.
    # Chỉ dọn bản tin tự động. Bài tự soạn là công sức của người dùng và có thể hẹn
    # đăng xa trong tương lai — xoá là mất trắng.
    report.posts = conn.execute(
        "DELETE FROM post WHERE status != 'posted' AND origin = 'auto' AND created_at < ?",
        (cutoff,),
    ).rowcount

    # Bài ĐÃ ĐĂNG: Facebook giữ bản chính, mục "Đã đăng" đọc thẳng từ Graph API. Ở đây
    # chỉ cần phần sổ sách, và phải giữ NGUYÊN dòng chứ không xoá:
    #   ref        — khoá chống trùng; mất nó là planner dựng lại bài bóng đá đã đăng
    #   fb_post_id — đường lui để thu Insights sau này
    #   posted_at  — hạn ngạch ngày và giãn cách giữa hai bài đọc từ đây
    # Bỏ đi nội dung và dữ liệu card: chúng chiếm gần hết dung lượng một dòng mà không
    # còn ai đọc tới. Dòng còn lại vài chục byte, nghìn bài cũng chưa tới 100KB.
    report.trimmed = conn.execute(
        "UPDATE post SET content = '', card_data = NULL, image_url = NULL"
        " WHERE status = 'posted' AND posted_at < ? AND content != ''",
        (cutoff,),
    ).rowcount

    # Tin thô: chỉ xoá tin không còn bài nào tham chiếu tới.
    # Phải viết rõ "cluster_id IS NULL OR ..." — trong SQL, `NULL NOT IN (...)` cho ra NULL
    # chứ không phải TRUE, nên tin chưa gắn nhóm sẽ không bao giờ bị xoá và rác tích mãi.
    report.articles = conn.execute(
        "DELETE FROM raw_article WHERE fetched_at < ? AND ("
        "  cluster_id IS NULL"
        "  OR cluster_id NOT IN (SELECT cluster_id FROM post WHERE cluster_id IS NOT NULL)"
        ")",
        (cutoff,),
    ).rowcount

    # Chủ đề mồ côi — không còn tin nào và không còn bài nào.
    # Lại phải lọc NULL trong subquery: bài tự soạn có cluster_id rỗng, để lọt vào thì
    # `NOT IN` trả NULL và không xoá được chủ đề nào — chúng tích tụ mãi.
    report.clusters = conn.execute(
        "DELETE FROM topic_cluster WHERE last_seen_at < ?"
        " AND id NOT IN (SELECT cluster_id FROM post WHERE cluster_id IS NOT NULL)"
        " AND id NOT IN (SELECT cluster_id FROM raw_article WHERE cluster_id IS NOT NULL)",
        (cutoff,),
    ).rowcount

    conn.commit()

    # VACUUM trả dung lượng đã xoá về hệ điều hành. Không chạy thì file DB chỉ phình,
    # không bao giờ nhỏ lại — đúng thứ cần tránh trên ổ nhỏ.
    conn.execute("VACUUM")

    logger.info("Dọn dữ liệu: %s", report.summary())
    return report
