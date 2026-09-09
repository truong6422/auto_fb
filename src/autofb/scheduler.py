"""Tự quyết định lúc nào đăng bài — thay cho việc người ngồi duyệt từng bài.

Thiết kế theo kiểu "tick": cron gọi vào mỗi vài phút, hàm này nhìn trạng thái hiện tại
rồi quyết định làm gì. KHÔNG chạy tiến trình nền thường trú.

Vì sao chọn kiểu này: tiến trình nền mà chết thì không ai biết, phải thêm giám sát.
Cron chết thì lần tick sau tự chạy lại. Trên mini server 2GB, không giữ tiến trình nào
sống 24/7 cũng là một cái lợi.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import Config

# Giờ Việt Nam — khung giờ đăng phải tính theo giờ người đọc, không phải UTC.
VN_TIMEZONE = timezone(timedelta(hours=7))


@dataclass(frozen=True)
class Decision:
    should_crawl: bool
    should_publish: bool
    reason: str
    posted_today: int = 0
    quota: int = 0


def now_vn() -> datetime:
    return datetime.now(VN_TIMEZONE)


def _start_of_day_utc(moment: datetime) -> str:
    """0h giờ Việt Nam của ngày đang xét, đổi sang UTC để so với dữ liệu trong DB."""
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).isoformat()


def posted_today(conn: sqlite3.Connection, moment: datetime) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM post WHERE status = 'posted' AND posted_at >= ?",
        (_start_of_day_utc(moment),),
    ).fetchone()[0]


def minutes_since_last_post(conn: sqlite3.Connection) -> float | None:
    row = conn.execute(
        "SELECT posted_at FROM post WHERE status = 'posted' ORDER BY posted_at DESC LIMIT 1"
    ).fetchone()
    if not row or not row["posted_at"]:
        return None
    last = datetime.fromisoformat(row["posted_at"])
    return (datetime.now(timezone.utc) - last).total_seconds() / 60


def hours_since_last_crawl(conn: sqlite3.Connection) -> float | None:
    row = conn.execute("SELECT MAX(fetched_at) AS t FROM raw_article").fetchone()
    if not row or not row["t"]:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(row["t"])).total_seconds() / 3600


def decide(config: Config, conn: sqlite3.Connection, moment: datetime | None = None) -> Decision:
    """Quyết định lượt tick này nên crawl / đăng gì."""
    moment = moment or now_vn()
    schedule = config.schedule
    quota = config.post.daily_quota

    last_crawl = hours_since_last_crawl(conn)
    should_crawl = last_crawl is None or last_crawl >= schedule.crawl_every_hours

    done = posted_today(conn, moment)

    if not (schedule.start_hour <= moment.hour < schedule.end_hour):
        return Decision(should_crawl, False, "ngoài khung giờ đăng", done, quota)

    if done >= quota:
        return Decision(should_crawl, False, "đã đủ số bài trong ngày", done, quota)

    gap = minutes_since_last_post(conn)
    if gap is not None and gap < schedule.min_gap_minutes:
        return Decision(
            should_crawl, False,
            f"mới đăng {gap:.0f} phút trước, chờ đủ {schedule.min_gap_minutes} phút",
            done, quota,
        )

    # Rải đều số bài còn lại trong số giờ còn lại, để không đăng dồn buổi sáng
    # rồi im lặng cả buổi tối.
    hours_left = max(schedule.end_hour - moment.hour, 1)
    expected_done = quota - (quota * hours_left // max(schedule.end_hour - schedule.start_hour, 1))
    if done > expected_done:
        return Decision(should_crawl, False, "đang đi trước lịch, chờ nhịp sau", done, quota)

    return Decision(should_crawl, True, "đến giờ đăng", done, quota)
