"""Hai lượt chạy tự động, TÁCH RỜI nhau:

    run_crawl_tick()    — dọn dữ liệu → kéo RSS → dựng bài vào hàng chờ
    run_publish_tick()  — nhìn lịch → đăng bài trong hàng chờ lên Fanpage

Vì sao tách: hai việc này có nhịp và rủi ro hoàn toàn khác nhau. Crawl chạy 2 tiếng
một lần, hỏng thì chỉ là thiếu tin mới. Đăng bài chạy vài phút một lần, hỏng thì Page
im lặng cả ngày. Gộp chung một tiến trình thì RSS của một tờ báo treo 15 giây là kéo
theo cả việc đăng bài trễ, và token Facebook chết cũng làm dừng luôn việc crawl.

Chúng chỉ gặp nhau qua bảng `post` trong SQLite — không gọi hàm của nhau, không chia
sẻ bộ nhớ. Nhờ vậy chạy được ở hai container riêng, khởi động lại cái này không đụng
cái kia.
"""

import logging
import sqlite3
from dataclasses import dataclass, field

from . import cleanup, scheduler
from .config import Config
from .crawler.pipeline import run_crawl
from .facebook import FacebookClient
from .post_pipeline import build_pending_posts
from .publisher import publish_approved
from .web.state import SystemState

logger = logging.getLogger(__name__)

# Hàng chờ đầy hơn ngần này thì thôi dựng thêm — bài dựng thừa sẽ bị cleanup xoá phí công,
# mà tin thể thao để lâu cũng mất giá.
QUEUE_HIGH_WATER = 20


@dataclass
class TickReport:
    paused: bool = False
    crawled: int = 0
    built: int = 0
    published: int = 0
    reason: str = ""
    posted_today: int = 0
    quota: int = 0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.paused:
            return "HỆ THỐNG ĐANG TẠM DỪNG — không làm gì"
        parts = [f"crawl {self.crawled} tin", f"dựng {self.built} bài",
                 f"đăng {self.published} bài", f"hôm nay {self.posted_today}/{self.quota}"]
        return " | ".join(parts) + (f"\n  {self.reason}" if self.reason else "")


def run_crawl_tick(config: Config, conn: sqlite3.Connection) -> TickReport:
    """Lượt của container crawler. KHÔNG đụng tới Facebook — chạy được cả khi token chết."""
    report = TickReport()

    if SystemState().paused:
        report.paused = True
        return report

    cleanup.run_cleanup(conn, config.retention_days)

    decision = scheduler.decide(config, conn)
    report.reason = decision.reason

    if not decision.should_crawl:
        report.reason = "chưa tới nhịp kéo RSS"
        return report

    report.crawled = run_crawl(config, conn).inserted

    waiting = conn.execute(
        "SELECT COUNT(*) FROM post WHERE status = 'approved'"
    ).fetchone()[0]
    if waiting >= QUEUE_HIGH_WATER:
        report.reason = f"hàng chờ đã có {waiting} bài — không dựng thêm"
        return report

    report.built = build_pending_posts(config, conn).created
    report.reason = f"đã kéo tin và dựng bài (hàng chờ {waiting + report.built})"
    return report


def run_publish_tick(config: Config, conn: sqlite3.Connection,
                     client: FacebookClient | None = None) -> TickReport:
    """Lượt của container publisher. KHÔNG crawl — mạng báo chậm không làm trễ giờ đăng."""
    report = TickReport()

    # Kill switch kiểm TRƯỚC MỌI THỨ. Bấm dừng là dừng ngay lượt sau.
    if SystemState().paused:
        report.paused = True
        return report

    decision = scheduler.decide(config, conn)
    report.reason = decision.reason
    report.posted_today = decision.posted_today
    report.quota = decision.quota

    if not decision.should_publish:
        return report

    if client is None:
        report.notes.append("chưa cấu hình Facebook — không đăng")
        return report

    result = publish_approved(client, conn, limit=1, card=config.card)
    report.published = result.posted
    report.notes.extend(result.errors)
    return report


def run_tick(config: Config, conn: sqlite3.Connection,
             client: FacebookClient | None = None) -> TickReport:
    """Chạy cả hai lượt liền nhau — dùng cho nút 'Chạy ngay' và lệnh `cli.py tick`.

    Đây là đường tay, không phải đường chạy 24/7. Trên box, hai lượt do hai container
    gọi riêng.
    """
    crawl_report = run_crawl_tick(config, conn)
    if crawl_report.paused:
        return crawl_report

    publish_report = run_publish_tick(config, conn, client)
    publish_report.crawled = crawl_report.crawled
    publish_report.built = crawl_report.built
    return publish_report
