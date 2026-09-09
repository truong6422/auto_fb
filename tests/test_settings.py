"""Đọc bí mật từ .env — file phải thắng biến môi trường."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from autofb import settings  # noqa: E402


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Trỏ ENV_PATH sang file tạm để không đụng .env thật của máy."""
    path = tmp_path / ".env"
    monkeypatch.setattr(settings, "ENV_PATH", path)
    return path


class TestDocFile:
    def test_bo_qua_dong_trong_va_dong_ghi_chu(self, env_file):
        env_file.write_text("# ghi chú\n\nFB_PAGE_ID=123\n\n# nữa\nFB_API_VERSION=v22.0\n")
        assert settings.read_env_file() == {"FB_PAGE_ID": "123", "FB_API_VERSION": "v22.0"}

    def test_bo_dau_nhay_bao_quanh_gia_tri(self, env_file):
        env_file.write_text('FB_PAGE_ID="123"\nAUTOFB_USER=\'ai do\'\n')
        assert settings.read_env_file() == {"FB_PAGE_ID": "123", "AUTOFB_USER": "ai do"}

    def test_khong_co_file_thi_tra_dict_rong(self, env_file):
        assert settings.read_env_file() == {}


class TestFileThangBienMoiTruong:
    def test_doi_token_trong_file_la_co_hieu_luc_ngay(self, env_file, monkeypatch):
        """Docker nạp env_file MỘT LẦN lúc tạo container. Không đọc lại file thì đổi
        token phải tạo lại cả ba container — sót một cái là giao diện báo token hỏng
        trong khi bot vẫn đăng bài bình thường."""
        monkeypatch.setenv("FB_PAGE_ACCESS_TOKEN", "token_cu")
        env_file.write_text("FB_PAGE_ACCESS_TOKEN=token_moi\n")
        assert settings.current_value("FB_PAGE_ACCESS_TOKEN") == "token_moi"

    def test_khong_co_file_thi_dung_bien_moi_truong(self, env_file, monkeypatch):
        monkeypatch.setenv("FB_PAGE_ACCESS_TOKEN", "tu_bien_moi_truong")
        assert settings.current_value("FB_PAGE_ACCESS_TOKEN") == "tu_bien_moi_truong"

    def test_file_thieu_khoa_thi_roi_ve_bien_moi_truong(self, env_file, monkeypatch):
        monkeypatch.setenv("FB_PAGE_ID", "999")
        env_file.write_text("FB_PAGE_ACCESS_TOKEN=abc\n")
        assert settings.current_value("FB_PAGE_ID") == "999"

    def test_gia_tri_rong_trong_file_khong_che_mat_bien_moi_truong(self, env_file, monkeypatch):
        """Dòng 'FB_APP_SECRET=' bỏ trống trong .env.example không được ghi đè lên
        giá trị thật truyền qua biến môi trường."""
        monkeypatch.setenv("FB_APP_SECRET", "that")
        env_file.write_text("FB_APP_SECRET=\n")
        assert settings.current_value("FB_APP_SECRET") == "that"


class TestCheToken:
    def test_che_token_khi_hien_ra_man_hinh(self):
        fb = settings.FacebookSettings(page_id="1", access_token="EAAB" + "x" * 200)
        assert "…" in fb.masked_token and len(fb.masked_token) < 20

    def test_thieu_token_thi_coi_nhu_chua_cau_hinh(self):
        assert not settings.FacebookSettings(page_id="1", access_token="").configured


class TestFileKhongDocDuoc:
    """File .env không đọc được KHÔNG được làm sập app.

    Chuyện đã xảy ra thật: .env trên máy chủ là 600 root:root, container chạy bằng
    uid 10001 nên PermissionError thoát ra lúc import -> web sập, subdomain trả 502.
    """

    @pytest.fixture(autouse=True)
    def _quen_canh_bao_cu(self):
        settings._READ_FAILURES.clear()

    def test_khong_ném_lỗi_khi_thiếu_quyền(self, env_file, monkeypatch):
        env_file.write_text("FB_PAGE_ID=123\n")
        monkeypatch.setattr(
            settings.Path, "read_text",
            lambda self, **kw: (_ for _ in ()).throw(PermissionError(13, "Permission denied")),
        )
        assert settings.read_env_file() == {}

    def test_roi_ve_bien_moi_truong_khi_khong_doc_duoc(self, env_file, monkeypatch):
        env_file.write_text("FB_PAGE_ACCESS_TOKEN=trong_file\n")
        monkeypatch.setenv("FB_PAGE_ACCESS_TOKEN", "tu_bien_moi_truong")
        monkeypatch.setattr(
            settings.Path, "read_text",
            lambda self, **kw: (_ for _ in ()).throw(PermissionError(13, "Permission denied")),
        )
        assert settings.current_value("FB_PAGE_ACCESS_TOKEN") == "tu_bien_moi_truong"

    def test_chi_ghi_canh_bao_mot_lan(self, env_file, monkeypatch, caplog):
        """Hàm này chạy ở mỗi request; log lặp lại sẽ lấp đầy ổ USB của box."""
        env_file.write_text("x=1\n")
        monkeypatch.setattr(
            settings.Path, "read_text",
            lambda self, **kw: (_ for _ in ()).throw(PermissionError(13, "Permission denied")),
        )
        with caplog.at_level("ERROR"):
            for _ in range(5):
                settings.read_env_file()
        assert sum("Không đọc được" in r.message for r in caplog.records) == 1
