"""Thông số nhịp chạy sửa từ web, đè lên config/sources.yaml."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from autofb import db, runtime_settings as rs  # noqa: E402
from autofb.config import Config, CrawlSettings, PostSettings, ScheduleSettings, Source  # noqa: E402

NOW = "2026-09-09T03:00:00+00:00"

BASE = Config(
    crawl=CrawlSettings(max_age_hours=24),
    sources=[Source(name="x", url="http://x", sport="mixed", lang="vi")],
    post=PostSettings(daily_quota=10, per_sport_quota=6, max_summary_words=55),
    schedule=ScheduleSettings(active_hours=[7, 22], min_gap_minutes=45, crawl_every_hours=2),
    retention_days=3,
)


@pytest.fixture
def conn(tmp_path):
    with db.session(tmp_path / "t.db") as c:
        yield c


class TestApDung:
    def test_khong_co_gi_de_sua_thi_giu_nguyen(self):
        assert rs.apply_overrides(BASE, {}) is BASE

    def test_de_len_dung_tung_truong(self):
        result = rs.apply_overrides(BASE, {"daily_quota": 20, "crawl_every_hours": 1})
        assert result.post.daily_quota == 20
        assert result.schedule.crawl_every_hours == 1
        # Những trường không sửa phải giữ nguyên giá trị của file cấu hình.
        assert result.schedule.min_gap_minutes == 45
        assert result.crawl.max_age_hours == 24

    def test_khong_lam_thay_doi_cau_hinh_goc(self):
        """Config là frozen dataclass; nếu apply lỡ sửa tại chỗ thì lượt chạy đang
        dùng bản cũ sẽ bị đổi thông số giữa chừng."""
        rs.apply_overrides(BASE, {"daily_quota": 99})
        assert BASE.post.daily_quota == 10

    def test_sua_gio_hoat_dong(self):
        result = rs.apply_overrides(BASE, {"active_start_hour": 9, "active_end_hour": 20})
        assert (result.schedule.start_hour, result.schedule.end_hour) == (9, 20)


class TestKiemTraGiaTri:
    def test_ngoai_khoang_bi_tu_choi(self):
        with pytest.raises(rs.InvalidSetting):
            rs.validate("daily_quota", 999)

    def test_khong_phai_so_bi_tu_choi(self):
        with pytest.raises(rs.InvalidSetting):
            rs.validate("daily_quota", "nhiều")

    def test_khoa_la_bi_tu_choi(self):
        with pytest.raises(rs.InvalidSetting):
            rs.validate("khong_ton_tai", 1)

    def test_gio_ngung_phai_sau_gio_bat_dau(self, conn):
        with pytest.raises(rs.InvalidSetting):
            rs.save_overrides(
                conn, {"active_start_hour": "20", "active_end_hour": "8"}, NOW)


class TestLuuVaDoc:
    def test_luu_roi_doc_lai(self, conn):
        rs.save_overrides(conn, {"daily_quota": "12", "min_gap_minutes": "60"}, NOW)
        assert rs.load_overrides(conn) == {"daily_quota": 12, "min_gap_minutes": 60}

    def test_mot_gia_tri_sai_thi_khong_ghi_gia_tri_nao(self, conn):
        """Ghi được một nửa sẽ để lại cấu hình nửa cũ nửa mới, rất khó truy."""
        with pytest.raises(rs.InvalidSetting):
            rs.save_overrides(conn, {"daily_quota": "12", "min_gap_minutes": "0"}, NOW)
        assert rs.load_overrides(conn) == {}

    def test_bo_qua_truong_la_trong_form(self, conn):
        rs.save_overrides(conn, {"daily_quota": "12", "csrf": "abc"}, NOW)
        assert rs.load_overrides(conn) == {"daily_quota": 12}

    def test_khoi_phuc_mac_dinh_xoa_het(self, conn):
        rs.save_overrides(conn, {"daily_quota": "12"}, NOW)
        rs.reset(conn)
        assert rs.load_overrides(conn) == {}

    def test_khoa_con_sot_tu_ban_cu_khong_lam_hong_app(self, conn):
        conn.execute("INSERT INTO setting (key, value, updated_at) VALUES (?,?,?)",
                     ("thong_so_da_bo", "5", NOW))
        conn.commit()
        assert rs.load_overrides(conn) == {}
