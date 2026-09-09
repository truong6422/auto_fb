"""Mục "Đã đăng" đọc từ Fanpage, và phần sổ sách còn lại trong DB.

Hai thứ phải đi kèm nhau: chỉ khi màn hình không còn đọc nội dung bài đã đăng từ DB
thì cleanup mới được phép rút gọn chúng.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autofb import cleanup, db  # noqa: E402
from autofb.facebook import FacebookClient  # noqa: E402
from autofb.web import fanpage_feed  # noqa: E402


class TestDocFeed:
    def test_lay_du_so_tuong_tac(self):
        item = {
            "id": "1_2", "created_time": "2026-09-09T09:35:02+0000",
            "message": "Kết quả Vòng 3\n\nArsenal 2 - 1 Chelsea",
            "permalink_url": "https://facebook.com/1/posts/2",
            "full_picture": "https://scontent/x.jpg",
            "reactions": {"summary": {"total_count": 12}},
            "comments": {"summary": {"total_count": 3}},
            "shares": {"count": 2},
        }
        post = FacebookClient._page_post(item)
        assert (post.reactions, post.comments, post.shares) == (12, 3, 2)
        assert post.picture.endswith("x.jpg")

    def test_bai_khong_ai_chia_se_thi_dem_bang_khong(self):
        """Facebook BỎ HẲN trường `shares` khi chưa ai chia sẻ, không trả 0."""
        post = FacebookClient._page_post({"id": "1_2", "message": "x"})
        assert post.shares == 0 and post.reactions == 0

    def test_gio_facebook_doc_duoc_thanh_tuoi_bai(self):
        """created_time có dạng '+0000' — fromisoformat phải nuốt được, không thì
        mọi bài đều hiện 'không rõ'."""
        from autofb.web.app import _humanize_age

        when = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S+0000")
        assert _humanize_age(when) == "3 giờ trước"

    def test_facebook_hong_thi_khong_lam_sap_trang(self, monkeypatch):
        from autofb.facebook import TransientError

        fanpage_feed.forget()
        monkeypatch.setattr(fanpage_feed, "load_facebook_settings",
                            lambda: type("S", (), {"configured": True, "page_id": "1",
                                                   "access_token": "t", "api_version": "v21.0"})())
        monkeypatch.setattr(FacebookClient, "recent_posts",
                            lambda self, limit=25: (_ for _ in ()).throw(TransientError("sập")))
        items, error = fanpage_feed.recent_posts()
        assert items == [] and error


class TestRutGonBaiDaDang:
    """Bản chính nằm trên Facebook; DB chỉ giữ phần đủ để không đăng trùng."""

    def _post(self, conn, posted_at: str, ref: str):
        conn.execute(
            "INSERT INTO post (sport, content, status, origin, ref, card_data, posted_at,"
            " created_at) VALUES ('football', 'nội dung dài', 'posted', 'football', ?,"
            " '{\"rows\":[]}', ?, ?)", (ref, posted_at, posted_at))
        conn.commit()

    def test_bai_cu_bi_rut_gon_nhung_giu_khoa_chong_trung(self, tmp_path):
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        with db.session(tmp_path / "t.db") as conn:
            self._post(conn, old, "pl:results:2026-W30")
            assert cleanup.run_cleanup(conn, 3).trimmed == 1

            row = conn.execute("SELECT * FROM post").fetchone()
            assert row["content"] == "" and row["card_data"] is None
            # Mất ref là planner dựng lại đúng bài đã đăng -> Fanpage có hai bài giống nhau.
            assert row["ref"] == "pl:results:2026-W30"
            assert row["posted_at"] == old      # hạn ngạch ngày đọc từ đây

    def test_bai_moi_dang_van_giu_nguyen_noi_dung(self, tmp_path):
        """Facebook chưa kịp index hoặc mạng hỏng thì màn hình còn cái để hiện."""
        now = datetime.now(timezone.utc).isoformat()
        with db.session(tmp_path / "t.db") as conn:
            self._post(conn, now, "pl:results:2026-W37")
            cleanup.run_cleanup(conn, 3)
            assert conn.execute("SELECT content FROM post").fetchone()[0] == "nội dung dài"

    def test_chay_lai_khong_dem_lai_bai_da_rut_gon(self, tmp_path):
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        with db.session(tmp_path / "t.db") as conn:
            self._post(conn, old, "pl:results:2026-W30")
            cleanup.run_cleanup(conn, 3)
            assert cleanup.run_cleanup(conn, 3).trimmed == 0
