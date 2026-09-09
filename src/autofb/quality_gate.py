"""M5 — kiểm tra bài trước khi vào hàng đợi duyệt.

3 luật CHẶN. Bài bị chặn không hiện ở hàng chờ duyệt.

Đã bỏ luật "quá giống nguồn": MVP không viết lại bằng LLM nên bài luôn giống nguồn,
luật đó sẽ chặn 100% bài. Thay bằng giới hạn độ dài phần trích — cùng mục đích
(không lấy quá nhiều nội dung của người ta) nhưng đúng với cách bài đang được dựng.
"""

import sqlite3
from dataclasses import dataclass

from .text_utils import normalize_title, strip_accents, title_similarity

# Trên ngưỡng này so với một bài đã đăng thì coi là đăng lại chuyện cũ.
DUPLICATE_THRESHOLD = 0.75


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reason: str = ""

    @property
    def status(self) -> str:
        return "pending" if self.passed else "blocked"


def _exceeds_quote_limit(content: str, max_words: int) -> bool:
    """Toàn bài (trừ hashtag) không được dài hơn nhiều lần giới hạn trích.

    Nhân 3 để chừa chỗ cho tiêu đề, CTA và dòng nguồn.
    """
    body = " ".join(line for line in content.splitlines() if not line.startswith("#"))
    return len(body.split()) > max_words * 3


def _duplicates_posted(conn: sqlite3.Connection, title: str) -> str | None:
    """So tiêu đề với các bài đã đăng. Trả về tiêu đề trùng, hoặc None."""
    key = normalize_title(title)
    rows = conn.execute(
        "SELECT p.content FROM post p WHERE p.status IN ('posted', 'approved') LIMIT 200"
    ).fetchall()
    for row in rows:
        posted_title = row["content"].splitlines()[0] if row["content"] else ""
        if title_similarity(key, normalize_title(posted_title)) >= DUPLICATE_THRESHOLD:
            return posted_title
    return None


def _blocked_by_keyword(content: str, blocked: list[str]) -> str | None:
    """Chặn tin nhạy cảm — thay cho việc người ngồi duyệt từng bài.

    Không có bước duyệt tay nữa nên đây là hàng rào duy nhất giữa nguồn tin và Fanpage.
    Cố ý chặn rộng: tin tang lễ / doping / khởi tố lên Page thể thao giải trí là hỏng.
    """
    haystack = strip_accents(content.lower())
    for keyword in blocked:
        if strip_accents(keyword.lower()) in haystack:
            return keyword
    return None


def check(
    conn: sqlite3.Connection,
    content: str,
    max_summary_words: int,
    blocked_keywords: list[str] | None = None,
) -> GateResult:
    keyword = _blocked_by_keyword(content, blocked_keywords or [])
    if keyword:
        return GateResult(False, f"Chứa từ khoá bị chặn: {keyword}")

    if "Nguồn:" not in content:
        return GateResult(False, "Thiếu dòng ghi nguồn")

    if _exceeds_quote_limit(content, max_summary_words):
        return GateResult(False, "Phần trích dài quá giới hạn cho phép")

    title = content.splitlines()[0] if content else ""
    duplicate = _duplicates_posted(conn, title)
    if duplicate:
        return GateResult(False, f"Trùng bài đã đăng: {duplicate[:60]}")

    return GateResult(True)
