"""Kéo và chuẩn hoá một feed RSS.

Chạy tuần tự, một feed một lần — hợp với mini server 2GB và tránh đụng rate limit nguồn.
"""

import logging
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser
import httpx

from ..config import CrawlSettings, Source
from ..content_filter import is_utility_article
from ..rss_image import extract_image_url
from ..sport_classifier import resolve_sport
from ..text_utils import strip_html

logger = logging.getLogger(__name__)


class FeedError(Exception):
    """Không lấy được feed. Gọi ở tầng trên để ghi nhận nguồn lỗi, không làm chết cả lượt chạy."""


def fetch_feed(source: Source, settings: CrawlSettings) -> bytes:
    headers = {"User-Agent": settings.user_agent}
    try:
        response = httpx.get(
            source.url,
            headers=headers,
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise FeedError(f"{source.name}: {exc}") from exc
    return response.content


# Múi giờ mặc định cho nguồn Việt Nam không ghi timezone trong pubDate.
VN_TIMEZONE = timezone(timedelta(hours=7))

# Định dạng pubDate không chuẩn RFC-822 mà feedparser bỏ qua.
# Tuổi Trẻ trả "9/7/2026 12:16:00 PM" -> không có timezone, tháng/ngày kiểu Mỹ.
# Không xử lý thì mất trắng toàn bộ bài của nguồn đó (đã gặp thật khi chạy).
_FALLBACK_DATE_FORMATS = (
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)


def _parse_fallback_date(raw: str) -> datetime | None:
    raw = raw.strip()
    for fmt in _FALLBACK_DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=VN_TIMEZONE).astimezone(timezone.utc)
    return None


def _parse_published(entry) -> datetime | None:
    """Lấy thời điểm đăng. feedparser lo phần chuẩn, phần lệch chuẩn tự xử."""
    for key in ("published_parsed", "updated_parsed"):
        value = getattr(entry, key, None)
        if value:
            return datetime.fromtimestamp(mktime(value), tz=timezone.utc)

    for key in ("published", "updated", "pubDate"):
        value = getattr(entry, key, None)
        if value:
            parsed = _parse_fallback_date(value)
            if parsed:
                return parsed

    logger.debug("Không đọc được ngày đăng: %s", getattr(entry, "title", "")[:60])
    return None


def _entry_guid(entry) -> str | None:
    """Khoá chống trùng lớp 1. Ưu tiên guid của feed, không có thì dùng link."""
    return getattr(entry, "id", None) or getattr(entry, "link", None)


def parse_entries(
    raw: bytes, source: Source, settings: CrawlSettings, now: datetime
) -> list[dict]:
    """Chuẩn hoá entry của feed về cấu trúc chung, đã lọc theo tuổi bài."""
    parsed = feedparser.parse(raw)
    cutoff = now - timedelta(hours=settings.max_age_hours)

    articles: list[dict] = []
    skipped_old = 0

    for entry in parsed.entries[: settings.max_items_per_feed]:
        guid = _entry_guid(entry)
        title = strip_html(getattr(entry, "title", ""))
        if not guid or not title:
            continue

        published = _parse_published(entry)
        # Không rõ ngày đăng thì bỏ — an toàn hơn là đăng lại tin cũ.
        # Feed vnexpress/cac-mon-khac lẫn bài từ 2019, đây là chỗ chặn.
        if published is None or published < cutoff:
            skipped_old += 1
            continue

        summary = strip_html(getattr(entry, "summary", ""))
        articles.append(
            {
                "guid": guid,
                "url": getattr(entry, "link", "") or guid,
                "title": title,
                "summary": summary,
                "source_name": source.name,
                "sport": resolve_sport(source.sport, title, summary),
                "lang": source.lang,
                "published_at": published.isoformat(),
                "fetched_at": now.isoformat(),
                "is_utility": int(is_utility_article(title, summary)),
                "image_url": extract_image_url(entry),
            }
        )

    if skipped_old:
        logger.debug("%s: bỏ %d bài quá cũ/không rõ ngày", source.name, skipped_old)
    return articles


def collect(source: Source, settings: CrawlSettings, now: datetime) -> list[dict]:
    return parse_entries(fetch_feed(source, settings), source, settings, now)
