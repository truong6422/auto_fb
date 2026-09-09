"""Chia sẻ bài vào nhóm Facebook — phần ghi nhớ đã chia sẻ đâu rồi.

Không có test nào cho việc ĐĂNG vào nhóm, vì không có code nào làm việc đó: Meta gỡ
Groups API ngày 22/04/2024.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from autofb import db  # noqa: E402
from autofb.web import share  # noqa: E402


@pytest.fixture
def conn(tmp_path):
    with db.session(tmp_path / "t.db") as c:
        c.execute("INSERT INTO fb_group (name, url, created_at)"
                  " VALUES ('Hội bóng đá', 'https://facebook.com/groups/a', '2026-09-09')")
        c.execute("INSERT INTO fb_group (name, url, created_at)"
                  " VALUES ('Cầu lông HN', 'https://facebook.com/groups/b', '2026-09-09')")
        c.commit()
        yield c


def feed(*ids):
    return [{"id": i, "headline": f"bài {i}", "age": "1 giờ trước",
             "permalink": f"https://facebook.com/{i}", "picture": "",
             "reactions": 0, "comments": 0, "shares": 0} for i in ids]


class TestChonBai:
    def test_khong_chon_gi_thi_lay_bai_moi_nhat(self, conn):
        assert share.build_context(conn, feed("1_9", "1_8"), "")["chosen"]["id"] == "1_9"

    def test_bai_da_bien_mat_khoi_fanpage_thi_quay_ve_bai_moi_nhat(self, conn):
        """Bài bị xoá trên Page mà link cũ còn trong lịch sử trình duyệt — không được
        để trang trắng."""
        assert share.build_context(conn, feed("1_9"), "1_khong_co")["chosen"]["id"] == "1_9"

    def test_fanpage_trong_thi_khong_no(self, conn):
        assert share.build_context(conn, [], "")["chosen"] is None


class TestGhiNhoDaChiaSe:
    def _mark(self, conn, post_id, group_id):
        conn.execute("INSERT OR REPLACE INTO group_share (fb_post_id, group_id, shared_at)"
                     " VALUES (?, ?, '2026-09-09')", (post_id, group_id))
        conn.commit()

    def test_danh_dau_theo_tung_bai_rieng(self, conn):
        """Chia sẻ bài A vào nhóm 1 không được làm bài B trông như đã chia sẻ."""
        self._mark(conn, "1_9", 1)
        a = share.build_context(conn, feed("1_9", "1_8"), "1_9")
        b = share.build_context(conn, feed("1_9", "1_8"), "1_8")
        assert a["done_count"] == 1 and b["done_count"] == 0

    def test_nhom_chua_chia_se_xep_len_truoc(self, conn):
        """Việc còn phải làm nằm trên, việc đã xong nằm dưới."""
        self._mark(conn, "1_9", 1)
        groups = share.build_context(conn, feed("1_9"), "1_9")["groups"]
        assert groups[0]["shared"] is False

    def test_dem_so_nhom_cho_tung_bai_trong_o_chon(self, conn):
        self._mark(conn, "1_9", 1)
        self._mark(conn, "1_9", 2)
        counts = share.build_context(conn, feed("1_9", "1_8"), "1_9")["counts_by_post"]
        assert counts == {"1_9": 2}

    def test_nhom_tat_khong_tinh_vao_tong(self, conn):
        """Tắt nhóm rồi thì '2/3 nhóm' phải thành '2/2', không thì tiến độ không bao
        giờ đầy."""
        conn.execute("UPDATE fb_group SET enabled = 0 WHERE id = 2")
        conn.commit()
        assert share.build_context(conn, feed("1_9"), "1_9")["active_count"] == 1

    def test_xoa_nhom_thi_xoa_luon_lich_su_cua_no(self, conn):
        """Còn dòng group_share mồ côi thì số đếm cao hơn số nhóm đang có."""
        self._mark(conn, "1_9", 1)
        conn.execute("DELETE FROM group_share WHERE group_id = 1")
        conn.execute("DELETE FROM fb_group WHERE id = 1")
        conn.commit()
        assert share.build_context(conn, feed("1_9"), "1_9")["done_count"] == 0
