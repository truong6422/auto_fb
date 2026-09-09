"""Quản lý link affiliate và cách gắn link vào bài theo môn."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from autofb import db  # noqa: E402
from autofb.post_pipeline import pick_affiliate_link  # noqa: E402

NOW = "2026-09-07T10:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    with db.session(tmp_path / "test.db") as connection:
        yield connection


class TestPickAffiliateLink:
    def test_lay_dung_link_cua_mon(self, conn):
        db.add_link(conn, "football", "http://x/bong-da", "", NOW)
        db.add_link(conn, "tennis", "http://x/tennis", "", NOW)
        assert pick_affiliate_link(conn, "tennis") == "http://x/tennis"

    def test_mon_chua_co_link_thi_khong_gan(self, conn):
        """Không phải lỗi — bài vẫn đăng, chỉ là không kèm comment."""
        assert pick_affiliate_link(conn, "gym") is None

    def test_xoay_vong_deu_giua_cac_link(self, conn):
        db.add_link(conn, "football", "http://x/a", "", NOW)
        db.add_link(conn, "football", "http://x/b", "", NOW)
        picked = [pick_affiliate_link(conn, "football") for _ in range(4)]
        assert picked == ["http://x/a", "http://x/b", "http://x/a", "http://x/b"]

    def test_link_bi_tat_thi_khong_duoc_chon(self, conn):
        off = db.add_link(conn, "football", "http://x/tat", "", NOW)
        db.add_link(conn, "football", "http://x/bat", "", NOW)
        conn.execute("UPDATE affiliate_link SET enabled = 0 WHERE id = ?", (off,))
        assert pick_affiliate_link(conn, "football") == "http://x/bat"
        assert pick_affiliate_link(conn, "football") == "http://x/bat"

    def test_them_link_moi_van_xoay_vong_dung(self, conn):
        """Link thêm sau có use_count = 0 nên được ưu tiên — không nhảy lung tung
        như cách lấy modulo trên danh sách đổi độ dài."""
        db.add_link(conn, "football", "http://x/cu", "", NOW)
        pick_affiliate_link(conn, "football")
        pick_affiliate_link(conn, "football")
        db.add_link(conn, "football", "http://x/moi", "", NOW)
        assert pick_affiliate_link(conn, "football") == "http://x/moi"


class TestSeedFromConfig:
    def test_nap_link_tu_file_cau_hinh_khi_bang_trong(self, conn):
        added = db.seed_links_from_config(
            conn, {"football": ["http://x/1", "http://x/2"], "gym": []}, NOW
        )
        assert added == 2
        assert len(db.list_links(conn)) == 2

    def test_khong_nap_de_khong_tao_ban_trung(self, conn):
        db.add_link(conn, "football", "http://x/da-co", "", NOW)
        assert db.seed_links_from_config(conn, {"football": ["http://x/1"]}, NOW) == 0
        assert len(db.list_links(conn)) == 1
