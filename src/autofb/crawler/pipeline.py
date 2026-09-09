"""Điều phối một lượt crawl: kéo tất cả nguồn → chống trùng → gom nhóm → lưu."""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .. import db
from ..config import Config
from ..text_utils import normalize_title, title_similarity
from . import fetcher

logger = logging.getLogger(__name__)

# Trên ngưỡng này thì coi là cùng một tin. Đặt cao vì gom nhầm hai tin khác nhau
# gây hậu quả nặng hơn (mất một tin) so với tách nhầm một tin thành hai nhóm.
SIMILARITY_THRESHOLD = 0.72


@dataclass
class CrawlReport:
    fetched: int = 0
    inserted: int = 0
    duplicate_guid: int = 0
    utility: int = 0
    clustered_into_existing: int = 0
    new_clusters: int = 0
    failed_sources: list[str] = field(default_factory=list)
    by_sport: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        sports = ", ".join(f"{k}={v}" for k, v in sorted(self.by_sport.items())) or "-"
        return (
            f"lấy {self.fetched} bài | mới {self.inserted} | trùng guid {self.duplicate_guid} | "
            f"nhóm mới {self.new_clusters} | gộp vào nhóm cũ {self.clustered_into_existing} | "
            f"bài tiện ích {self.utility} | "
            f"nguồn lỗi {len(self.failed_sources)}\n  môn: {sports}"
        )


def _find_matching_cluster(
    clusters: list[sqlite3.Row], title_key: str, sport: str
) -> int | None:
    """Tìm nhóm tin cùng chủ đề. Chỉ so trong cùng môn để giảm gom nhầm."""
    best_id, best_score = None, 0.0
    for cluster in clusters:
        if cluster["sport"] != sport:
            continue
        score = title_similarity(title_key, cluster["title_key"])
        if score > best_score:
            best_id, best_score = cluster["id"], score
    return best_id if best_score >= SIMILARITY_THRESHOLD else None


def _store(conn: sqlite3.Connection, article: dict, report: CrawlReport, now_iso: str) -> None:
    """Chống trùng 2 lớp rồi lưu bài + gắn vào nhóm tin."""
    # Lớp 1: guid/URL trùng tuyệt đối — rẻ nhất, chặn trước.
    if db.guid_exists(conn, article["guid"]):
        report.duplicate_guid += 1
        return

    # Lớp 2: tương đồng tiêu đề với các nhóm còn sống.
    title_key = normalize_title(article["title"])
    lookback = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    clusters = db.recent_clusters(conn, lookback)

    # Bài tiện ích không gom nhóm: tiêu đề theo mẫu cố định nên khớp bừa với nhau.
    if article["is_utility"]:
        cluster_id = None
        report.utility += 1
    else:
        cluster_id = _find_matching_cluster(clusters, title_key, article["sport"])
    if cluster_id is None:
        cluster_id = db.create_cluster(
            conn, article["title"], title_key, article["sport"], now_iso
        )
        report.new_clusters += 1
    else:
        report.clustered_into_existing += 1

    if db.insert_article(conn, article, cluster_id) is None:
        report.duplicate_guid += 1
        return

    db.touch_cluster(conn, cluster_id, now_iso)
    report.inserted += 1
    report.by_sport[article["sport"]] = report.by_sport.get(article["sport"], 0) + 1


def run_crawl(config: Config, conn: sqlite3.Connection) -> CrawlReport:
    report = CrawlReport()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    for source in config.enabled_sources:
        try:
            articles = fetcher.collect(source, config.crawl, now)
        except fetcher.FeedError as exc:
            logger.warning("Nguồn lỗi — %s", exc)
            report.failed_sources.append(source.name)
            continue

        logger.info("%-28s %3d bài trong %dh", source.name, len(articles),
                    config.crawl.max_age_hours)
        report.fetched += len(articles)
        for article in articles:
            _store(conn, article, report, now_iso)
        conn.commit()

    return report
