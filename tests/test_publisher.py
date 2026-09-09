"""M7 — đăng bài và comment. Dùng client giả, không gọi Facebook thật."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from autofb import db, publisher  # noqa: E402
from autofb.config import CardSettings  # noqa: E402
from autofb.facebook import PermanentError, TransientError  # noqa: E402

NOW = "2026-09-07T10:00:00+00:00"

# Phần lớn test ở đây kiểm logic đăng bài / comment, không kiểm ảnh. Tắt card để
# chúng không phụ thuộc vào file font và config trên đĩa.
NO_CARD = CardSettings(enabled=False)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Bỏ thời gian chờ giữa các lần thử lại để test chạy nhanh."""
    monkeypatch.setattr(publisher.time, "sleep", lambda _: None)


class FakeClient:
    """Client giả: đếm số lần gọi và cho phép ép lỗi."""

    def __init__(self, post_error=None, comment_error=None, upload_error=None):
        self.post_error = post_error
        self.comment_error = comment_error
        self.upload_error = upload_error
        self.post_calls = 0
        self.comment_calls = 0
        self.uploaded_bytes: list[bytes] = []
        self.uploaded_urls: list[str] = []
        self.attached: list[str] = []

    def publish_post(self, message):
        self.post_calls += 1
        if self.post_error:
            raise self.post_error
        return "page_1_post_9"

    def upload_unpublished_photo_bytes(self, image, filename="card.png"):
        if self.upload_error:
            raise self.upload_error
        self.uploaded_bytes.append(image)
        return f"photo_b{len(self.uploaded_bytes)}"

    def upload_unpublished_photo_url(self, image_url):
        if self.upload_error:
            raise self.upload_error
        self.uploaded_urls.append(image_url)
        return f"photo_u{len(self.uploaded_urls)}"

    def publish_photo_url(self, image_url, message):
        self.post_calls += 1
        if self.post_error:
            raise self.post_error
        return "page_1_photo_9"

    def publish_with_photos(self, message, photo_ids):
        self.post_calls += 1
        self.attached = list(photo_ids)
        if self.post_error:
            raise self.post_error
        return "page_1_post_9"

    def publish_comment(self, fb_post_id, message):
        self.comment_calls += 1
        if self.comment_error:
            raise self.comment_error
        return f"{fb_post_id}_c1"


@pytest.fixture
def conn(tmp_path):
    with db.session(tmp_path / "t.db") as c:
        c.execute(
            "INSERT INTO topic_cluster (id, representative, title_key, sport,"
            " first_seen_at, last_seen_at) VALUES (1, 'tin', 'tin', 'football', ?, ?)",
            (NOW, NOW),
        )
        yield c


def make_post(conn, link: str | None = "http://shopee.vn/x", status: str = "approved") -> int:
    cur = conn.execute(
        "INSERT INTO post (cluster_id, sport, content, status, affiliate_link, created_at)"
        " VALUES (1, 'football', 'Nội dung bài', ?, ?, ?)",
        (status, link, NOW),
    )
    conn.commit()
    return int(cur.lastrowid)


def fetch(conn, post_id):
    return conn.execute("SELECT * FROM post WHERE id = ?", (post_id,)).fetchone()


class TestDangBaiThanhCong:
    def test_luu_fb_post_id_va_doi_trang_thai(self, conn):
        post_id = make_post(conn)
        client = FakeClient()
        report = publisher.publish_approved(client, conn, card=NO_CARD)

        row = fetch(conn, post_id)
        assert row["status"] == "posted"
        assert row["fb_post_id"] == "page_1_post_9"   # đường lui cho Phase 2
        assert row["comment_status"] == "posted"
        assert (report.posted, report.commented) == (1, 1)

    def test_danh_dau_chu_de_da_dang(self, conn):
        """Không đánh dấu thì lượt dựng bài sau lại tạo đúng tin đó."""
        make_post(conn)
        publisher.publish_approved(FakeClient(), conn, card=NO_CARD)
        assert conn.execute("SELECT posted FROM topic_cluster WHERE id = 1").fetchone()[0] == 1

    def test_khong_co_link_thi_khong_dang_comment(self, conn):
        post_id = make_post(conn, link=None)
        client = FakeClient()
        publisher.publish_approved(client, conn, card=NO_CARD)

        assert client.comment_calls == 0
        assert fetch(conn, post_id)["comment_status"] == "none"


class TestCommentLoi:
    def test_bai_van_la_da_dang_khi_comment_hong(self, conn):
        """Bài đã public rồi — không được coi cả bài là thất bại."""
        post_id = make_post(conn)
        client = FakeClient(comment_error=PermanentError("[100] sai quyền"))
        report = publisher.publish_approved(client, conn, card=NO_CARD)

        row = fetch(conn, post_id)
        assert row["status"] == "posted"
        assert row["comment_status"] == "failed"
        assert report.posted == 1 and report.failed == 0

    def test_chay_lai_chi_dang_comment_khong_dang_lai_bai(self, conn):
        """Đăng lại bài sẽ ra hai bài trùng trên Page."""
        post_id = make_post(conn)
        publisher.publish_approved(FakeClient(comment_error=PermanentError("x")), conn, card=NO_CARD)

        client = FakeClient()
        publisher.retry_failed_comments(client, conn)

        assert client.post_calls == 0
        assert client.comment_calls == 1
        assert fetch(conn, post_id)["comment_status"] == "posted"


class TestThuLai:
    def test_loi_tam_thoi_duoc_thu_lai(self, conn):
        make_post(conn)
        client = FakeClient(post_error=TransientError("rate limit"))
        publisher.publish_approved(client, conn, card=NO_CARD)
        assert client.post_calls == publisher.MAX_ATTEMPTS

    def test_loi_vinh_vien_khong_thu_lai(self, conn):
        """Token hỏng thì thử lại vô ích, chỉ tốn lượt gọi."""
        post_id = make_post(conn)
        client = FakeClient(post_error=PermanentError("[190] token hết hạn"))
        report = publisher.publish_approved(client, conn, card=NO_CARD)

        assert client.post_calls == 1
        assert fetch(conn, post_id)["status"] == "failed"
        assert "190" in fetch(conn, post_id)["note"]
        assert report.failed == 1


class TestChonBai:
    def test_chi_dang_bai_da_duyet(self, conn):
        make_post(conn, status="pending")
        client = FakeClient()
        assert publisher.publish_approved(client, conn, card=NO_CARD).posted == 0
        assert client.post_calls == 0

    def test_dang_bai_cu_truoc_va_ton_trong_gioi_han(self, conn):
        first = make_post(conn)
        make_post(conn)
        publisher.publish_approved(FakeClient(), conn, limit=1, card=NO_CARD)

        assert fetch(conn, first)["status"] == "posted"
        assert conn.execute(
            "SELECT COUNT(*) FROM post WHERE status = 'approved'"
        ).fetchone()[0] == 1


class TestCardTieuDe:
    """Bài 2 ảnh: card tiêu đề + ảnh gốc của báo."""

    def make_post_with_image(self, conn) -> int:
        post_id = make_post(conn)
        conn.execute(
            "UPDATE post SET content = ?, image_url = ?, image_credit = ? WHERE id = ?",
            ("Công Phượng ghi bàn trong ngày trở lại\n\nTóm tắt bài.",
             "https://img.example/anh.jpg", "VnExpress", post_id),
        )
        conn.commit()
        return post_id

    def test_card_dung_truoc_anh_bao(self, conn):
        """Thứ tự sai là mất luôn lý do làm card: Facebook lấy ảnh đầu làm ảnh lớn."""
        self.make_post_with_image(conn)
        client = FakeClient()
        publisher.publish_approved(client, conn, card=CardSettings())

        assert client.attached == ["photo_b1", "photo_u1"]
        assert client.uploaded_urls == ["https://img.example/anh.jpg"]

    def test_card_la_file_png_that(self, conn):
        self.make_post_with_image(conn)
        client = FakeClient()
        publisher.publish_approved(client, conn, card=CardSettings())

        assert client.uploaded_bytes[0].startswith(b"\x89PNG")

    def test_anh_bao_chet_link_van_dang_duoc_card(self, conn):
        """Link ảnh của báo hỏng là chuyện thường — không được kéo cả bài xuống."""
        post_id = self.make_post_with_image(conn)

        class OnlyUrlFails(FakeClient):
            def upload_unpublished_photo_url(self, image_url):
                raise PermanentError("[324] ảnh không tải được")

        client = OnlyUrlFails()
        report = publisher.publish_approved(client, conn, card=CardSettings())

        assert client.attached == ["photo_b1"]
        assert fetch(conn, post_id)["status"] == "posted"
        assert report.posted == 1

    def test_tat_card_thi_quay_ve_dang_mot_anh(self, conn):
        self.make_post_with_image(conn)
        client = FakeClient()
        publisher.publish_approved(client, conn, card=NO_CARD)

        assert client.uploaded_bytes == []
        assert client.attached == ["photo_u1"]
