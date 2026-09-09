"""Vòng lặp thường trú cho hai container chạy nền (crawler và publisher).

Trước đây scheduler thiết kế theo kiểu cron gọi vào từng lượt. Chạy trong Docker thì
container PHẢI có một tiến trình sống mãi, nên chỗ này thay cron: ngủ — chạy một lượt —
ngủ tiếp. Toàn bộ quyết định "có nên làm gì không" vẫn nằm ở scheduler.decide(),
vòng lặp này chỉ giữ nhịp.

Bắt mọi lỗi trong từng lượt: một lượt hỏng (mạng rớt, RSS trả rác) KHÔNG được phép
giết container, vì lượt sau có thể chạy bình thường. Chỉ SIGTERM mới dừng vòng lặp.
"""

import logging
import signal
import sqlite3
import time
from collections.abc import Callable

from . import db
from .autopilot import TickReport, run_crawl_tick, run_publish_tick
from .facebook import FacebookClient
from .runtime_settings import effective_config
from .settings import load_facebook_settings

logger = logging.getLogger(__name__)


class _StopSignal:
    """Nhận SIGTERM/SIGINT để dừng GIỮA hai lượt, không cắt ngang một lượt đang chạy.

    Cắt ngang lúc đang đăng bài là nguy hiểm nhất: bài đã lên Facebook nhưng DB chưa
    kịp ghi 'posted', lần chạy sau sẽ đăng lại thành bài trùng.
    """

    def __init__(self) -> None:
        self.stopped = False
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._handle)

    def _handle(self, signum, frame) -> None:  # noqa: ARG002
        logger.info("Nhận tín hiệu dừng — kết thúc sau lượt hiện tại")
        self.stopped = True

    def sleep(self, seconds: float) -> None:
        """Ngủ nhưng tỉnh ngay khi có tín hiệu dừng, thay vì để Docker chờ hết timeout."""
        deadline = time.monotonic() + seconds
        while not self.stopped and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))


def run_loop(name: str, interval_seconds: int,
             tick: Callable[[sqlite3.Connection], TickReport]) -> int:
    """Chạy `tick` mãi mãi, cách nhau `interval_seconds` giây."""
    stop = _StopSignal()
    logger.info("[%s] khởi động, chạy mỗi %d giây", name, interval_seconds)

    while not stop.stopped:
        try:
            with db.session() as conn:
                report = tick(conn)
            logger.info("[%s] %s", name, report.summary().replace("\n", " "))
            for note in report.notes:
                logger.warning("[%s] %s", name, note)
        except Exception:  # noqa: BLE001 - cố ý nuốt: một lượt hỏng không được giết container
            logger.exception("[%s] lượt chạy lỗi — bỏ qua, thử lại lượt sau", name)

        stop.sleep(interval_seconds)

    logger.info("[%s] đã dừng", name)
    return 0


def crawl_worker(interval_minutes: int) -> int:
    """Container 1: chỉ kéo RSS và dựng bài. Không cần token Facebook."""
    return run_loop(
        "crawler", interval_minutes * 60,
        lambda conn: run_crawl_tick(effective_config(conn), conn),
    )


def publish_worker(interval_minutes: int) -> int:
    """Container 2: chỉ đăng bài đã có trong hàng chờ.

    Đọc lại token ở MỖI lượt chứ không giữ một client dùng mãi: đổi token trong .env
    xong chỉ cần đợi lượt sau, không phải khởi động lại container.
    """

    def tick(conn: sqlite3.Connection) -> TickReport:
        fb = load_facebook_settings()
        client = (
            FacebookClient(fb.page_id, fb.access_token, fb.api_version)
            if fb.configured else None
        )
        return run_publish_tick(effective_config(conn), conn, client)

    return run_loop("publisher", interval_minutes * 60, tick)
