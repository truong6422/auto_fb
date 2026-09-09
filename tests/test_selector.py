"""M3 — chọn tin: chia suất theo môn và khử trùng sự kiện."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autofb.config import PostSettings  # noqa: E402
from autofb.selector import _apply_quota, _entities  # noqa: E402


def row(title: str, sport: str = "football", count: int = 1) -> dict:
    return {"cluster_id": abs(hash(title)) % 10000, "representative": title,
            "sport": sport, "article_count": count, "latest_published": "2026-09-07"}


class TestEntities:
    def test_lay_ten_doi_ke_ca_o_dau_cau(self):
        """'Arsenal' đứng đầu câu vẫn là tên đội, không được bỏ."""
        assert _entities("Arsenal đánh bại Chelsea") == {"Arsenal", "Chelsea"}

    def test_bo_tu_tieng_viet_viet_hoa(self):
        """Từ tiếng Việt viết hoa đầu câu mang dấu nên tự bị loại; U20 thì giữ vì là đội."""
        assert _entities("Xác định 16 đội dự giải U20 châu Á") == {"U20"}

    def test_bo_viet_tat_khong_phai_ten_rieng(self):
        assert "HLV" not in _entities("HLV Arteta phát biểu")


class TestKhuTrungSuKien:
    def test_nhieu_bai_cung_tran_chi_lay_mot(self):
        """Một trận sinh ra rất nhiều bài với tiêu đề khác hẳn nhau."""
        titles = [
            "Neville chỉ ra tử huyệt của Chelsea dưới thời Alonso",
            "Arteta: 'Trận thắng Chelsea chứng tỏ Arsenal ở đẳng cấp cao hơn'",
            "Havertz giúp Arsenal thắng ngược Chelsea",
            "Arsenal đánh bại Chelsea, giữ mạch toàn thắng ở Premier League",
        ]
        picked = _apply_quota([row(t) for t in titles],
                              PostSettings(daily_quota=8, per_sport_quota=8))
        assert len(picked) == 1

    def test_hai_tran_khac_nhau_thi_giu_ca_hai(self):
        picked = _apply_quota(
            [row("Arsenal đánh bại Chelsea"), row("Man Utd hòa Everton")],
            PostSettings(daily_quota=8, per_sport_quota=8),
        )
        assert len(picked) == 2

    def test_tin_khong_co_ten_rieng_khong_bi_khu_lan_nhau(self):
        picked = _apply_quota(
            [row("Đội tuyển giành huy chương vàng"), row("Thưởng nóng cho vận động viên")],
            PostSettings(daily_quota=8, per_sport_quota=8),
        )
        assert len(picked) == 2


class TestHanNgach:
    def test_chia_suat_theo_mon(self):
        rows = [row(f"Arsenal thắng trận {i}", "football") for i in range(5)]
        rows += [row("Alcaraz vào tứ kết", "tennis")]
        picked = _apply_quota(rows, PostSettings(daily_quota=5, per_sport_quota=2))
        assert [p["sport"] for p in picked].count("tennis") == 1

    def test_ton_trong_han_muc_ngay(self):
        rows = [row(f"Đội thứ {i} thắng trận", f"sport{i}") for i in range(10)]
        assert len(_apply_quota(rows, PostSettings(daily_quota=3, per_sport_quota=9))) == 3
