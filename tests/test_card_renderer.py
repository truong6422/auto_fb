"""Card tiêu đề — ảnh nền gradient + chữ to, thứ người lướt feed nhìn thấy đầu tiên."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from autofb.card_renderer import pick_gradient, render_card, title_of  # noqa: E402
from autofb.config import CardSettings  # noqa: E402

CARD = CardSettings(width=540, height=675, max_font_size=60, min_font_size=22)


def open_card(**kwargs) -> Image.Image:
    return Image.open(io.BytesIO(render_card(**kwargs)))


class TestKichThuoc:
    def test_dung_kich_thuoc_cau_hinh(self):
        image = open_card(title="Tin thể thao", settings=CARD)
        assert image.size == (540, 675)

    def test_tra_ve_png(self):
        assert render_card("Tin thể thao", CARD).startswith(b"\x89PNG")


class TestChuTiengViet:
    def test_ve_duoc_chu_co_dau(self):
        """Font mặc định của Pillow không có dấu — lỗi này chỉ lộ ra khi nhìn ảnh thật,
        nên kiểm bằng cách so số pixel chữ giữa bản có dấu và bản không dấu."""
        có_dấu = open_card(title="ĐỘI TUYỂN VIỆT NAM", settings=CARD).convert("L")
        không_dấu = open_card(title="DOI TUYEN VIET NAM", settings=CARD).convert("L")

        # Dấu là pixel sáng thêm. Hai ảnh cùng cỡ chữ, bản có dấu phải sáng hơn.
        assert sum(có_dấu.get_flattened_data()) > sum(không_dấu.get_flattened_data())

    def test_tieu_de_rong_thi_bao_loi(self):
        with pytest.raises(ValueError):
            render_card("   ", CARD)


class TestTuThuNhoChu:
    def test_tieu_de_dai_khong_tran_ra_ngoai(self):
        """Tiêu đề dài phải tự thu nhỏ chữ. Tràn ra ngoài là chữ bị cắt cụt trên feed."""
        dài = " ".join(["Đội tuyển Việt Nam thi đấu rất hay"] * 6)
        image = open_card(title=dài, settings=CARD).convert("L")

        # Cột ngoài cùng bên trái/phải phải còn nguyên nền, không dính chữ trắng.
        pixels = image.load()
        biên = [pixels[x, y] for y in range(image.height) for x in (0, image.width - 1)]
        assert max(biên) < 200

    def test_tieu_de_qua_dai_bi_cat_bang_dau_ba_cham(self):
        chật = CardSettings(width=400, height=400, max_lines=2,
                            max_font_size=48, min_font_size=40)
        # Không kiểm được chữ trong ảnh, nhưng render phải chạy trót lọt chứ không treo.
        assert render_card("từ " * 200, chật).startswith(b"\x89PNG")


class TestChonMau:
    def test_xoay_vong_theo_id_bai(self):
        """Hai bài liền nhau phải khác màu, và vẽ lại bài cũ ra đúng màu cũ."""
        assert pick_gradient(CARD, 0) != pick_gradient(CARD, 1)
        assert pick_gradient(CARD, 0) == pick_gradient(CARD, len(CARD.gradients))


class TestLayTieuDe:
    def test_lay_dong_dau_tien_co_chu(self):
        assert title_of("\n\nCông Phượng ghi bàn\n\nTóm tắt") == "Công Phượng ghi bàn"

    def test_bai_rong_tra_ve_chuoi_rong(self):
        assert title_of("\n \n") == ""
