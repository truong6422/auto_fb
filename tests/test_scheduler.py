"""Bộ lịch tự động — quyết định lúc nào crawl, lúc nào đăng."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from autofb import db  # noqa: E402
from autofb.cleanup import run_cleanup  # noqa: E402
from autofb.config import (  # noqa: E402
    Config, CrawlSettings, PostSettings, ScheduleSettings, Source,
)
from autofb.scheduler import VN_TIMEZONE, decide  # noqa: E402


def make_config(**post_kw) -> Config:
    return Config(
        crawl=CrawlSettings(), sources=[Source("s", "u", "mixed", "vi")],
        post=PostSettings(daily_quota=10, **post_kw),
        schedule=ScheduleSettings(active_hours=[7, 22], min_gap_minutes=45),
    )


@pytest.fixture
def conn(tmp_path):
    with db.session(tmp_path / "t.db") as c:
        c.execute("INSERT INTO topic_cluster (id, representative, title_key, sport,"
                  " first_seen_at, last_seen_at) VALUES (1,'t','t','football','x','x')")
        yield c


def add_posted(conn, minutes_ago: float, count: int = 1):
    for i in range(count):
        when = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago + i)).isoformat()
        conn.execute(
            "INSERT INTO post (cluster_id, sport, content, status, posted_at, created_at)"
            " VALUES (1,'football','x','posted',?,?)", (when, when))
    conn.commit()


AT_NOON = datetime(2026, 9, 7, 12, 0, tzinfo=VN_TIMEZONE)


class TestKhungGio:
    def test_ngoai_khung_gio_thi_khong_dang(self, conn):
        at_night = AT_NOON.replace(hour=3)
        assert decide(make_config(), conn, at_night).should_publish is False

    def test_trong_khung_gio_va_chua_dang_gi_thi_dang(self, conn):
        assert decide(make_config(), conn, AT_NOON).should_publish is True


class TestGianCach:
    def test_moi_dang_xong_thi_cho(self, conn):
        """Đăng dồn liên tiếp trông bất thường với Facebook lẫn người đọc."""
        add_posted(conn, minutes_ago=5)
        plan = decide(make_config(), conn, AT_NOON)
        assert plan.should_publish is False
        assert "45 phút" in plan.reason

    def test_du_gian_cach_thi_dang_tiep(self, conn):
        add_posted(conn, minutes_ago=60)
        assert decide(make_config(), conn, AT_NOON).should_publish is True


class TestHanMucNgay:
    def test_du_so_bai_thi_dung(self, conn):
        add_posted(conn, minutes_ago=200, count=10)
        plan = decide(make_config(), conn, AT_NOON)
        assert plan.should_publish is False
        assert plan.posted_today == 10

    def test_di_truoc_lich_thi_cho_nhip_sau(self, conn):
        """Rải đều cả ngày, không đăng hết 10 bài trong buổi sáng."""
        add_posted(conn, minutes_ago=200, count=8)
        assert decide(make_config(), conn, AT_NOON.replace(hour=8)).should_publish is False


class TestCrawl:
    def test_chua_co_du_lieu_thi_crawl(self, conn):
        assert decide(make_config(), conn, AT_NOON).should_crawl is True


class TestDonDuLieu:
    def test_xoa_tin_cu_giu_bai_da_dang(self, conn):
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        conn.execute("INSERT INTO raw_article (guid,url,title,source_name,sport,lang,"
                     "fetched_at,cluster_id) VALUES ('g','u','t','s','football','vi',?,NULL)",
                     (old,))
        conn.execute("INSERT INTO post (cluster_id,sport,content,status,fb_post_id,created_at)"
                     " VALUES (1,'football','x','posted','fb_1',?)", (old,))
        conn.commit()

        run_cleanup(conn, retention_days=3)

        assert conn.execute("SELECT COUNT(*) FROM raw_article").fetchone()[0] == 0
        # Bài đã đăng phải còn — fb_post_id là đường lui để sau này lấy Insights.
        assert conn.execute("SELECT COUNT(*) FROM post WHERE status='posted'").fetchone()[0] == 1

    def test_xoa_chu_de_mo_coi_du_co_bai_tu_soan(self, conn):
        """Bài tự soạn có cluster_id rỗng — nếu để lọt vào subquery thì `NOT IN` trả NULL
        và không chủ đề nào bị xoá, rác tích mãi trên ổ nhỏ."""
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        conn.execute("UPDATE topic_cluster SET last_seen_at = ?", (old,))
        conn.execute("INSERT INTO post (cluster_id,sport,content,status,origin,created_at)"
                     " VALUES (NULL,'running','tu soan','approved','manual',?)", (old,))
        conn.commit()

        run_cleanup(conn, retention_days=3)

        assert conn.execute("SELECT COUNT(*) FROM topic_cluster").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM post WHERE origin='manual'").fetchone()[0] == 1
