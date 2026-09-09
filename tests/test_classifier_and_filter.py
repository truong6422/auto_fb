"""Phân loại môn và lọc bài tiện ích.

Các tiêu đề dưới đây lấy từ dữ liệu crawl thật, không phải bịa ra.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from autofb.content_filter import is_utility_article  # noqa: E402
from autofb.sport_classifier import classify_sport, resolve_sport  # noqa: E402


class TestClassifySport:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Lịch thi đấu bóng đá hôm nay 7/9", "football"),
            ("Xác định 16 đội dự U.20 châu Á 2027", "football"),
            ("Tottenham và bước khởi đầu thảm họa", "football"),
            ("Đội bóng của HLV Park Hang Seo thắng tưng bừng ở giải Thái Lan", "football"),
            ("Alcaraz tiếp tục bùng nổ, giành vé vào tứ kết US Open", "tennis"),
            ("Việt Nam tại Pickleball World Cup 2026", "pickleball"),
            ("Điền kinh Việt Nam đoạt 16 HC vàng ở SEA Games", "running"),
            ("Giải xe đạp xuyên Việt khởi tranh", "cycling"),
        ],
    )
    def test_nhan_dien_dung_mon(self, title, expected):
        assert classify_sport(title) == expected

    def test_mon_ngoai_pham_vi_tra_ve_other(self):
        """Tin bóng chuyền dễ khớp nhầm 'đội tuyển' của bảng football."""
        assert classify_sport("Tuyển thủ bóng chuyền Lưu Thị Huệ dự ASIAD 20") == "other"

    def test_khong_ro_thi_tra_other_chu_khong_doan_bua(self):
        assert classify_sport("Thưởng nóng 100 triệu đồng cho VĐV giành HCV") == "other"

    def test_tieu_de_rong(self):
        assert classify_sport("") == "other"


class TestResolveSport:
    def test_feed_khai_bao_mon_thi_tin_theo_feed(self):
        assert resolve_sport("badminton", "Alcaraz vào tứ kết US Open") == "badminton"

    def test_feed_mixed_thi_moi_doan(self):
        assert resolve_sport("mixed", "Alcaraz vào tứ kết US Open") == "tennis"


class TestUtilityFilter:
    @pytest.mark.parametrize(
        "title",
        [
            "Lịch thi đấu vòng 3 Ngoại hạng Anh 2026/27 mới nhất",
            "Nóng BXH vòng 3 Ngoại hạng Anh 2026/27 mới nhất",
            "Bảng xếp hạng V-League 2026/27 - Vòng 1 mới nhất",
            "Link xem trực tiếp U20 Việt Nam vs Thái Lan",
        ],
    )
    def test_nhan_dien_bai_bang_bieu(self, title):
        assert is_utility_article(title) is True

    @pytest.mark.parametrize(
        "title",
        [
            "Đội trưởng U20 Việt Nam xin lỗi người hâm mộ",
            "Tottenham và bước khởi đầu thảm họa",
            "Việt Nam không thể tạo bất ngờ trước Mỹ ở chung kết Pickleball World Cup",
        ],
    )
    def test_tin_that_khong_bi_danh_dau(self, title):
        assert is_utility_article(title) is False
