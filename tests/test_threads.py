"""Đăng lại sang Threads: cắt chữ, hai bước tạo–đăng, và cách hỏng cho đúng.

Nguyên tắc lớn nhất được kiểm ở đây: Threads hỏng KHÔNG được làm bài Facebook thành
'failed'. Bài đã lên Fanpage rồi — đánh dấu hỏng là lượt sau đăng lại thành bài trùng.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from autofb import db  # noqa: E402
from autofb.facebook import PermanentError, TransientError  # noqa: E402
from autofb.publisher import PublishReport, _publish_threads  # noqa: E402
from autofb.threads import ThreadsClient, shorten  # noqa: E402


class TestCatChu:
    """Threads chặn ở 500 ký tự và từ chối CẢ BÀI nếu vượt, không tự cắt hộ."""

    def test_bai_ngan_giu_nguyen(self):
        assert shorten("Arsenal 2 - 1 Chelsea") == "Arsenal 2 - 1 Chelsea"

    def test_cat_o_cuoi_dong_cho_bai_van_doc_duoc(self):
        text = "dòng một\n" + "x" * 40 + "\ndòng ba"
        assert shorten(text, 55).endswith("…") and "dòng ba" not in shorten(text, 55)

    def test_cat_o_ranh_gioi_tu_khi_khong_co_xuong_dong(self):
        assert shorten("alpha bravo charlie delta", 18) == "alpha bravo…"

    def test_khong_cat_qua_ngan_du_phai_cat_giua_tu(self):
        """Dấu cách nằm ngay đầu chuỗi thì cắt theo nó là mất gần hết bài."""
        assert len(shorten("a " + "x" * 100, 20)) >= 15


class FakeThreads(ThreadsClient):
    """Ghi lại từng lời gọi thay vì ra mạng."""

    def __init__(self, statuses=("FINISHED",), fail_image=False):
        super().__init__("u1", "tok")
        self.calls: list[tuple[str, str, dict]] = []
        self._statuses = list(statuses)
        self._fail_image = fail_image

    def _request(self, method, path, params, base=None):
        self.calls.append((method, path, params))
        if path.endswith("/threads"):
            if self._fail_image and params.get("media_type") == "IMAGE":
                raise PermanentError("ảnh tải không được")
            return {"id": "c1"}
        if path.endswith("/threads_publish"):
            return {"id": "t9"}
        status = self._statuses.pop(0) if self._statuses else "FINISHED"
        return {"status": status, "error_message": "hỏng ảnh"}


class TestHaiBuoc:
    def test_bai_anh_dung_media_type_image(self):
        client = FakeThreads()
        assert client.post("nội dung", image_url="https://x/a.png").with_image
        create = client.calls[0][2]
        assert create["media_type"] == "IMAGE" and create["image_url"] == "https://x/a.png"

    def test_bai_chu_gan_link_ve_fanpage(self):
        """Không có ảnh thì thẻ xem trước là thứ duy nhất kéo người về Page."""
        client = FakeThreads()
        client.post("nội dung", link="https://facebook.com/1_2")
        create = client.calls[0][2]
        assert create["media_type"] == "TEXT"
        assert create["link_attachment"] == "https://facebook.com/1_2"

    def test_phai_dang_dung_container_vua_tao(self):
        client = FakeThreads()
        client.post("nội dung")
        publish = next(c for c in client.calls if c[1].endswith("threads_publish"))
        assert publish[2]["creation_id"] == "c1"

    def test_cho_den_khi_threads_tai_xong_anh(self):
        client = FakeThreads(statuses=("IN_PROGRESS", "FINISHED"))
        client.wait_ready("c1", timeout=5)
        assert sum(1 for c in client.calls if c[0] == "GET") == 2

    def test_threads_bao_loi_thi_dung_ngay_khong_cho_het_gio(self):
        client = FakeThreads(statuses=("ERROR",))
        with pytest.raises(PermanentError):
            client.wait_ready("c1", timeout=5)

    def test_qua_gio_cho_thi_la_loi_tam_thoi(self):
        client = FakeThreads(statuses=("IN_PROGRESS",) * 20)
        with pytest.raises(TransientError):
            client.wait_ready("c1", timeout=0)

    def test_anh_hong_thi_van_dang_duoc_bai_chu(self):
        """Mất một tấm ảnh không đáng để mất cả bài."""
        client = FakeThreads(fail_image=True)
        result = client.post("nội dung", image_url="https://x/a.png", link="https://fb/1")
        assert result.id == "t9" and not result.with_image


class TestKhongLamHongBaiFacebook:
    @pytest.fixture
    def post_row(self, tmp_path):
        with db.session(tmp_path / "t.db") as conn:
            conn.execute("INSERT INTO post (sport, content, status, fb_post_id, created_at)"
                         " VALUES ('football', 'nội dung', 'posted', '1_2', '2026-09-09')")
            conn.commit()
            yield conn, conn.execute("SELECT * FROM post").fetchone()

    def test_chua_cau_hinh_thi_bo_qua_lang_le(self, post_row, monkeypatch):
        conn, post = post_row
        monkeypatch.setattr("autofb.publisher.load_threads_settings",
                            lambda: type("S", (), {"configured": False})())
        report = PublishReport()
        _publish_threads(None, conn, post, "1_2", report)
        assert report.errors == []
        assert conn.execute("SELECT threads_status FROM post").fetchone()[0] == "none"

    def test_threads_hong_thi_bai_van_la_posted(self, post_row, monkeypatch):
        conn, post = post_row
        monkeypatch.setattr("autofb.publisher.load_threads_settings",
                            lambda: type("S", (), {"configured": True, "user_id": "u",
                                                   "access_token": "t"})())
        monkeypatch.setattr("autofb.publisher.ThreadsClient",
                            lambda *a: type("C", (), {
                                "post": lambda self, *a, **k: (_ for _ in ()).throw(
                                    PermanentError("sập"))})())

        class FakeFB:
            def post_picture(self, _):
                return "https://x/a.png"

        report = PublishReport()
        _publish_threads(FakeFB(), conn, post, "1_2", report)
        conn.commit()

        row = conn.execute("SELECT status, threads_status FROM post").fetchone()
        # Bài đã nằm trên Fanpage — đổi thành 'failed' là lượt sau đăng lại thành bài trùng.
        assert row["status"] == "posted"
        assert row["threads_status"] == "failed"


class TestGiaHanToken:
    """Token Threads sống 60 ngày; quá hạn là hỏng vĩnh viễn, phải xin lại bằng tay."""

    @pytest.fixture
    def conn(self, tmp_path, monkeypatch):
        monkeypatch.setattr("autofb.threads_token.current_value",
                            lambda key, default="": {"THREADS_ACCESS_TOKEN": "seed1",
                                                     "THREADS_USER_ID": "u1"}.get(key, default))
        with db.session(tmp_path / "t.db") as c:
            yield c

    def test_lan_dau_lay_thang_tu_env(self, conn):
        from autofb import threads_token
        assert threads_token.active_token(conn) == "seed1"

    def test_doi_token_trong_env_thi_bo_ban_da_gia_han(self, conn, monkeypatch):
        """Không có bước này thì sửa .env chẳng có tác dụng — DB cứ giữ token cũ."""
        from autofb import threads_token
        threads_token.active_token(conn)
        threads_token._set(conn, threads_token.TOKEN_KEY, "da-gia-han")
        conn.commit()
        assert threads_token.active_token(conn) == "da-gia-han"

        monkeypatch.setattr("autofb.threads_token.current_value",
                            lambda key, default="": {"THREADS_ACCESS_TOKEN": "seed2",
                                                     "THREADS_USER_ID": "u1"}.get(key, default))
        assert threads_token.active_token(conn) == "seed2"

    def test_token_con_moi_thi_khong_goi_gia_han(self, conn, monkeypatch):
        from autofb import threads_token
        monkeypatch.setattr(ThreadsClient, "refresh_token",
                            lambda self: pytest.fail("không được gọi khi token còn mới"))
        assert threads_token.maybe_refresh(conn) is False

    def test_qua_han_thi_gia_han_va_luu_token_moi(self, conn, monkeypatch):
        from datetime import datetime, timedelta, timezone

        from autofb import threads_token
        threads_token.active_token(conn)
        cu = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        threads_token._set(conn, threads_token.REFRESHED_KEY, cu)
        conn.commit()

        monkeypatch.setattr(ThreadsClient, "refresh_token", lambda self: "token-moi")
        assert threads_token.maybe_refresh(conn) is True
        assert threads_token.active_token(conn) == "token-moi"

    def test_gia_han_hong_khong_lam_chet_luot_dang(self, conn, monkeypatch):
        """Token cũ còn dùng được nhiều tuần — không có lý do gì để ném lỗi ra ngoài."""
        from datetime import datetime, timedelta, timezone

        from autofb import threads_token
        threads_token.active_token(conn)
        threads_token._set(conn, threads_token.REFRESHED_KEY,
                           (datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
        conn.commit()

        monkeypatch.setattr(ThreadsClient, "refresh_token",
                            lambda self: (_ for _ in ()).throw(TransientError("mạng")))
        assert threads_token.maybe_refresh(conn) is False
        assert threads_token.active_token(conn) == "seed1"
