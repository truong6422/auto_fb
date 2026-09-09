"""Chuẩn hoá tiêu đề và so khớp — nơi từng có lỗi chữ 'đ' và lỗi gom nhầm."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autofb.text_utils import (  # noqa: E402
    normalize_title,
    strip_accents,
    strip_html,
    title_similarity,
    truncate_words,
)

SIMILARITY_THRESHOLD = 0.72


class TestStripAccents:
    def test_d_gach_ngang_thanh_d_thuong(self):
        """NFD không tách 'đ' (U+0111). Không thay thủ công thì mọi từ khoá có 'đ' đều trượt."""
        assert strip_accents("bóng đá") == "bong da"
        assert strip_accents("xe đạp") == "xe dap"
        assert strip_accents("điền kinh") == "dien kinh"
        assert strip_accents("Đội tuyển") == "Doi tuyen"

    def test_giu_nguyen_chu_khong_dau(self):
        assert strip_accents("pickleball 2026") == "pickleball 2026"


class TestNormalizeTitle:
    def test_bo_dau_va_ky_tu_dac_biet(self):
        assert normalize_title("Lịch thi đấu bóng đá hôm nay 7/9") == (
            "lich thi dau bong da hom nay 7 9"
        )

    def test_u_cham_20_va_u20_cho_ra_cung_tu_khoa(self):
        """Báo viết cả 'U20' lẫn 'U.20' — hai dạng phải quy về so khớp được."""
        assert "u 20" in normalize_title("U.20 Việt Nam")
        assert "u20" in normalize_title("U20 Việt Nam")

    def test_bo_hu_tu(self):
        assert "cua" not in normalize_title("Đội bóng của HLV Park Hang Seo").split()


class TestTitleSimilarity:
    def test_cung_mot_tin_khac_cach_dat_tieu_de_thi_khop(self):
        pairs = [
            (
                "Đội trưởng U20 Việt Nam xin lỗi người hâm mộ sau 3 trận thua",
                "Thủ quân U20 Việt Nam xin lỗi người hâm mộ",
            ),
            (
                "Xác định 16 đội dự VCK U20 châu Á 2027",
                "Xác định 16 đội dự giải U20 châu Á: Thái Lan, Indonesia, Malaysia có tên",
            ),
        ]
        for left, right in pairs:
            score = title_similarity(normalize_title(left), normalize_title(right))
            assert score >= SIMILARITY_THRESHOLD, f"{score:.2f} — {left} | {right}"

    def test_hai_tin_khac_nhau_thi_khong_khop(self):
        score = title_similarity(
            normalize_title("Tottenham và bước khởi đầu thảm họa"),
            normalize_title("Đội bóng của HLV Park Hang Seo thắng ở giải Thái Lan"),
        )
        assert score < SIMILARITY_THRESHOLD, f"{score:.2f}"

    def test_tieu_de_rap_khuon_van_khop_cao_nen_can_loc_o_noi_khac(self):
        """Giới hạn đã biết của cách so khớp này, ghi lại để không quên.

        Hai bài lịch thi đấu khác giải vẫn khớp trên ngưỡng, vì phần lớn tiêu đề trùng mẫu.
        Sửa bằng cách hạ ngưỡng hay bỏ thêm stopword đều làm hỏng các cặp đúng ở test trên.
        Nhóm bài này được chặn bằng content_filter.is_utility_article() trước khi gom nhóm —
        xem test_khong_gom_nhom_bai_tien_ich ở tests/test_crawler_pipeline.py.
        """
        score = title_similarity(
            normalize_title("Lịch thi đấu vòng 3 Ngoại hạng Anh 2026/27 mới nhất"),
            normalize_title("Lịch thi đấu vòng 1 V-League mùa giải 2026/27 mới nhất"),
        )
        assert score >= SIMILARITY_THRESHOLD

    def test_it_tu_chung_thi_khong_tinh_la_trung(self):
        assert title_similarity(normalize_title("Messi ghi bàn"),
                                normalize_title("Ronaldo ghi bàn")) == 0.0

    def test_chuoi_rong(self):
        assert title_similarity("", "abc") == 0.0


class TestStripHtmlVaTruncate:
    def test_go_the_va_giai_ma_entity(self):
        assert strip_html("<p>Tuy&#7875;n Vi&#7879;t Nam</p>") == "Tuyển Việt Nam"

    def test_cat_bot_tu(self):
        assert truncate_words("một hai ba bốn năm", 3) == "một hai ba…"

    def test_khong_cat_khi_du_ngan(self):
        assert truncate_words("một hai", 5) == "một hai"
