"""Đọc ngày đăng lệch chuẩn, chống trùng và gom nhóm — chạy trên SQLite tạm, không ra mạng."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from autofb import db  # noqa: E402
from autofb.config import CrawlSettings, Config, Source  # noqa: E402
from autofb.crawler.fetcher import _parse_fallback_date, parse_entries  # noqa: E402
from autofb.crawler.pipeline import _store, CrawlReport  # noqa: E402

NOW = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
SETTINGS = CrawlSettings()
SOURCE = Source(name="Test", url="http://x", sport="mixed", lang="vi")


def rss(items: str) -> bytes:
    return f"<rss version='2.0'><channel>{items}</channel></rss>".encode()


def item(title: str, pub_date: str, guid: str) -> str:
    return f"<item><title>{title}</title><link>http://x/{guid}</link>" \
           f"<guid>{guid}</guid><pubDate>{pub_date}</pubDate></item>"


class TestParseFallbackDate:
    def test_dinh_dang_tuoi_tre(self):
        """Tuổi Trẻ trả '9/7/2026 12:16:00 PM' — feedparser bỏ qua, từng mất trắng 50 bài."""
        parsed = _parse_fallback_date("9/7/2026 12:16:00 PM")
        assert parsed is not None
        assert (parsed.year, parsed.month, parsed.day) == (2026, 9, 7)

    def test_coi_la_gio_viet_nam_khi_thieu_timezone(self):
        parsed = _parse_fallback_date("9/7/2026 12:00:00 PM")
        assert parsed.hour == 5  # 12h giờ VN = 05h UTC

    def test_dinh_dang_la_thi_tra_none(self):
        assert _parse_fallback_date("hôm qua") is None


class TestParseEntries:
    def test_lay_duoc_bai_dung_dinh_dang_le_chuan(self):
        raw = rss(item("Tin mới", "9/7/2026 10:30:00 AM", "g1"))
        assert len(parse_entries(raw, SOURCE, SETTINGS, NOW)) == 1

    def test_bo_bai_qua_cu(self):
        old = (NOW - timedelta(days=5)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        raw = rss(item("Tin cũ", old, "g2"))
        assert parse_entries(raw, SOURCE, SETTINGS, NOW) == []

    def test_bo_bai_khong_ro_ngay_dang(self):
        raw = rss("<item><title>Không ngày</title><guid>g3</guid></item>")
        assert parse_entries(raw, SOURCE, SETTINGS, NOW) == []

    def test_gan_mon_va_co_bai_tien_ich(self):
        raw = rss(item("Lịch thi đấu vòng 3 Ngoại hạng Anh", "9/7/2026 10:30:00 AM", "g4"))
        article = parse_entries(raw, SOURCE, SETTINGS, NOW)[0]
        assert article["sport"] == "football"
        assert article["is_utility"] == 1


@pytest.fixture
def conn(tmp_path):
    with db.session(tmp_path / "test.db") as connection:
        yield connection


def make_article(title: str, guid: str, sport: str = "football", utility: int = 0) -> dict:
    return {
        "guid": guid, "url": f"http://x/{guid}", "title": title, "summary": "",
        "source_name": "Test", "sport": sport, "lang": "vi",
        "published_at": NOW.isoformat(), "fetched_at": NOW.isoformat(),
        "is_utility": utility, "image_url": None,
    }


class TestStore:
    def test_bai_moi_tao_nhom_moi(self, conn):
        report = CrawlReport()
        _store(conn, make_article("Tottenham thua trận", "a1"), report, NOW.isoformat())
        assert (report.inserted, report.new_clusters) == (1, 1)

    def test_trung_guid_bi_chan(self, conn):
        report = CrawlReport()
        article = make_article("Tottenham thua trận", "a1")
        _store(conn, article, report, NOW.isoformat())
        _store(conn, dict(article), report, NOW.isoformat())
        assert (report.inserted, report.duplicate_guid) == (1, 1)

    def test_cung_tin_khac_bao_thi_gop_nhom(self, conn):
        report = CrawlReport()
        _store(conn, make_article(
            "Đội trưởng U20 Việt Nam xin lỗi người hâm mộ sau 3 trận thua", "a1"),
            report, NOW.isoformat())
        _store(conn, make_article(
            "Thủ quân U20 Việt Nam xin lỗi người hâm mộ", "a2"),
            report, NOW.isoformat())
        assert report.clustered_into_existing == 1
        assert conn.execute("SELECT COUNT(*) FROM topic_cluster").fetchone()[0] == 1

    def test_khac_mon_thi_khong_gop(self, conn):
        report = CrawlReport()
        _store(conn, make_article("Việt Nam thắng Thái Lan", "a1", "football"),
               report, NOW.isoformat())
        _store(conn, make_article("Việt Nam thắng Thái Lan", "a2", "tennis"),
               report, NOW.isoformat())
        assert conn.execute("SELECT COUNT(*) FROM topic_cluster").fetchone()[0] == 2

    def test_bai_tien_ich_moi_bai_mot_nhom_rieng(self, conn):
        report = CrawlReport()
        _store(conn, make_article("Lịch thi đấu vòng 3 Ngoại hạng Anh", "a1", utility=1),
               report, NOW.isoformat())
        _store(conn, make_article("Lịch thi đấu vòng 3 Ngoại hạng Anh mới nhất", "a2",
                                  utility=1), report, NOW.isoformat())
        assert report.utility == 2
        assert conn.execute("SELECT COUNT(*) FROM topic_cluster").fetchone()[0] == 2
