"""Nối M3 → M4 → M5: chọn tin, dựng bài, kiểm chất lượng, đưa vào hàng đợi duyệt."""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import db, quality_gate, selector
from .config import Config
from .post_builder import TemplateBuilder

logger = logging.getLogger(__name__)


@dataclass
class BuildReport:
    candidates: int = 0
    created: int = 0
    blocked: int = 0
    reasons: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"ứng viên {self.candidates} | tạo bài {self.created} | bị chặn {self.blocked}"
        )


def pick_affiliate_link(conn: sqlite3.Connection, sport: str) -> str | None:
    """Lấy link affiliate của môn, xoay vòng đều giữa các link đang bật.

    Nguồn sự thật là bảng affiliate_link (sửa ở màn hình web), không phải file YAML.
    Môn chưa có link -> None, bài vẫn đăng nhưng không kèm comment. Không phải lỗi.
    """
    link = db.next_link_for_sport(conn, sport)
    if link is None:
        return None
    db.mark_link_used(conn, link["id"])
    return link["url"]


def build_pending_posts(config: Config, conn: sqlite3.Connection) -> BuildReport:
    report = BuildReport()
    builder = TemplateBuilder(config.post)
    now_iso = datetime.now(timezone.utc).isoformat()

    candidates = selector.select_candidates(conn, config.post, config.crawl.max_age_hours)
    report.candidates = len(candidates)

    for cluster in candidates:
        articles = selector.articles_of_cluster(conn, cluster["cluster_id"])
        if not articles:
            continue

        content = builder.build(dict(cluster), articles)
        result = quality_gate.check(
            conn, content, config.post.max_summary_words, config.blocked_keywords
        )

        cursor = conn.execute(
            "INSERT INTO post (cluster_id, sport, content, status, affiliate_link, note,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                cluster["cluster_id"],
                cluster["sport"],
                content,
                "approved" if result.passed else "blocked",
                pick_affiliate_link(conn, cluster["sport"]) if result.passed else None,
                result.reason or None,
                now_iso,
            ),
        )

        if result.passed:
            # Ảnh lấy từ chính bài gốc, chỉ lưu URL — Facebook sẽ tự tải khi đăng.
            primary = articles[0]
            conn.execute(
                "UPDATE post SET image_url = ?, image_credit = ?, source_url = ? WHERE id = ?",
                (primary.get("image_url"), primary["source_name"],
                 primary.get("url"), cursor.lastrowid),
            )
            report.created += 1
        else:
            report.blocked += 1
            report.reasons.append(result.reason)
            logger.info("Chặn bài: %s", result.reason)

    conn.commit()
    return report
