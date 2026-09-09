"""Bài bóng đá: mốc thời gian, chống trùng, dựng nội dung, vẽ card.

Không gọi mạng: dùng nguồn giả thay cho premierleague.com và uefa.com.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from autofb import db  # noqa: E402
from autofb.config import CardSettings  # noqa: E402
from autofb.football import content, planner  # noqa: E402
from autofb.football.card import Row, render_table_card  # noqa: E402
from autofb.football.models import Fixture, Lineup, Standing  # noqa: E402

NOW = datetime(2026, 9, 14, 2, 0, tzinfo=timezone.utc)      # 9h sáng thứ Hai giờ VN
CARD = CardSettings(width=540, height=675, max_font_size=60, min_font_size=20)


def make_fixture(**kwargs) -> Fixture:
    base = dict(id="1", league="Ngoại hạng Anh", kickoff=NOW,
                home="Arsenal", away="Chelsea",
                home_short="Arsenal", away_short="Chelsea")
    return Fixture(**{**base, **kwargs})


class TestMocThoiGian:
    def test_gio_viet_nam_va_thu(self):
        # 20:00 UTC thứ Bảy 12/09 = 03:00 Chủ Nhật 13/09 giờ VN
        match = make_fixture(kickoff=datetime(2026, 9, 12, 20, 0, tzinfo=timezone.utc))
        assert match.vn_time == "03:00"
        assert match.vn_date == "13/09"
        assert match.vn_weekday == "Chủ Nhật"

    def test_sap_da_thi_lot_cua_so_dang_doi_hinh(self):
        match = make_fixture(kickoff=NOW + timedelta(minutes=50))
        assert match.starts_within(NOW, 75)

    def test_con_qua_lau_thi_chua_dang_doi_hinh(self):
        match = make_fixture(kickoff=NOW + timedelta(hours=5))
        assert not match.starts_within(NOW, 75)

    def test_da_da_roi_thi_khong_dang_doi_hinh_nua(self):
        match = make_fixture(kickoff=NOW - timedelta(minutes=10))
        assert not match.starts_within(NOW, 75)


class TestKetQuaVuaXong:
    """Cận TRÊN là chỗ dễ sai nhất: thiếu nó thì mọi trận cũ đều bị đăng lại."""

    def test_vua_xong_thi_dang(self):
        match = make_fixture(kickoff=NOW - timedelta(minutes=150), finished=True,
                             home_score=2, away_score=1)
        assert match.just_ended(NOW, 140, 480)

    def test_moi_da_duoc_nua_hiep_thi_chua_dang(self):
        match = make_fixture(kickoff=NOW - timedelta(minutes=60), finished=True)
        assert not match.just_ended(NOW, 140, 480)

    def test_tran_tu_tuan_truoc_khong_bi_dao_lai(self):
        """Chuyện đã xảy ra thật: lần chạy đầu sinh 20 bài kết quả của các vòng cũ."""
        match = make_fixture(kickoff=NOW - timedelta(days=6), finished=True,
                             home_score=2, away_score=1)
        assert not match.just_ended(NOW, 140, 480)

    def test_chua_da_xong_thi_khong_tinh(self):
        match = make_fixture(kickoff=NOW - timedelta(minutes=200), finished=False)
        assert not match.just_ended(NOW, 140, 480)


class TestTenDoiRutGon:
    def test_dung_ten_rut_gon_cho_card(self):
        match = make_fixture(home="Brighton and Hove Albion", home_short="Brighton")
        assert match.home_name == "Brighton"

    def test_khong_co_ten_rut_gon_thi_dung_ten_day_du(self):
        match = make_fixture(home="Fulham", home_short="")
        assert match.home_name == "Fulham"


class TestDungNoiDung:
    def test_lich_thi_dau_nhom_theo_ngay(self):
        fixtures = [
            make_fixture(id="1", kickoff=datetime(2026, 9, 12, 14, 0, tzinfo=timezone.utc)),
            make_fixture(id="2", kickoff=datetime(2026, 9, 13, 14, 0, tzinfo=timezone.utc)),
        ]
        post = content.fixtures_post("Ngoại hạng Anh", "Vòng 4", fixtures)
        dims = [r for r in post["card_data"]["rows"] if r.get("dim")]
        assert len(dims) == 2                      # hai tiêu đề ngày
        assert post["card_kind"] == "table"

    def test_ket_qua_mot_tran_dung_card_tieu_de(self):
        """Một câu ngắn thì chữ to giữa card đọc rõ hơn là nhét vào bảng trống hoác."""
        match = make_fixture(finished=True, home_score=2, away_score=1)
        post = content.result_post(match)
        assert post["card_kind"] == "title"
        assert post["content"].splitlines()[0] == "Arsenal 2 - 1 Chelsea"

    def test_doi_hinh_xep_hai_cot_doi_nhau(self):
        match = make_fixture()
        lineups = [
            Lineup(team="Arsenal", formation="4-3-3", starters=["Raya", "White"]),
            Lineup(team="Chelsea", formation="4-2-3-1", starters=["Sánchez", "James"]),
        ]
        rows = content.lineup_post(match, lineups)["card_data"]["rows"]
        assert rows[0]["left"] == "Raya" and rows[0]["right"] == "Sánchez"

    def test_doi_hinh_mot_ben_van_dung_duoc(self):
        """Nguồn hay chỉ có đội hình đội nhà lúc gần giờ bóng lăn."""
        rows = content.lineup_post(
            make_fixture(), [Lineup(team="Arsenal", formation="", starters=["Raya"])]
        )["card_data"]["rows"]
        assert rows[0]["left"] == "Raya" and rows[0]["right"] == ""


class TestVeCard:
    def test_ve_duoc_card_bang(self):
        rows = [Row("1. Man City", "9"), Row("2. Arsenal", "9")]
        assert render_table_card("BẢNG XẾP HẠNG", rows, CARD).startswith(b"\x89PNG")

    def test_khong_co_dong_nao_thi_bao_loi(self):
        with pytest.raises(ValueError):
            render_table_card("TRỐNG", [], CARD)

    def test_bo_tieu_de_ngay_khong_con_tran_nao_ben_duoi(self):
        """Cắt bớt dòng có thể để lại một tiêu đề ngày trơ trọi — nhìn như card lỗi."""
        rows = [Row(f"trận {i}") for i in range(20)] + [Row("Thứ Ba 15/09", dim=True)]
        assert render_table_card("LỊCH", rows, CARD).startswith(b"\x89PNG")


class FakeSource:
    """Nguồn giả: cùng giao diện với premier_league và uefa, không gọi mạng."""

    LEAGUE_NAME = "Giải giả"

    def __init__(self, upcoming=(), results=(), table=(), lineup=()):
        self._upcoming, self._results = list(upcoming), list(results)
        self._table, self._lineup = list(table), list(lineup)

    def upcoming_fixtures(self, season, limit=20):
        return self._upcoming

    def recent_results(self, season, limit=20):
        return self._results

    def standings(self, season):
        return self._table

    def lineups(self, fixture_id):
        return self._lineup


@pytest.fixture
def conn(tmp_path):
    with db.session(tmp_path / "t.db") as c:
        yield c


@pytest.fixture
def one_league(monkeypatch):
    """Thay hai giải thật bằng đúng một giải giả."""
    def install(source):
        league = planner.League("gg", "Giải giả", source)
        monkeypatch.setattr(planner, "LEAGUES", (league,))
        monkeypatch.setattr(planner.League, "season", lambda self, now: 1)
    return install


class TestLenLich:
    def test_dau_tuan_ra_ba_bai(self, conn, one_league):
        done = make_fixture(id="9", finished=True, home_score=1, away_score=0,
                            round_label="Vòng 3", kickoff=NOW - timedelta(days=2))
        one_league(FakeSource(
            upcoming=[make_fixture(id="10", round_label="Vòng 4",
                                   kickoff=NOW + timedelta(days=5))],
            results=[done], table=[Standing(1, "Arsenal", 3, 9)]))

        assert planner.create_posts(conn, NOW) == 3
        refs = {r["ref"].split(":")[1] for r in conn.execute("SELECT ref FROM post")}
        assert refs == {"results", "standings", "fixtures"}

    def test_giua_tuan_khong_ra_bai_dau_tuan(self, conn, one_league):
        one_league(FakeSource(
            upcoming=[make_fixture(id="10", kickoff=NOW + timedelta(days=2))],
            results=[], table=[Standing(1, "Arsenal", 3, 9)]))
        thu_tu = NOW + timedelta(days=2)
        assert planner.create_posts(conn, thu_tu) == 0

    def test_chay_lai_khong_tao_bai_trung(self, conn, one_league):
        """Vòng lặp chạy 5 phút một lần — không chặn là mỗi trận ra hàng chục bài."""
        one_league(FakeSource(table=[Standing(1, "Arsenal", 3, 9)]))
        first = planner.create_posts(conn, NOW)
        assert first == 1
        assert planner.create_posts(conn, NOW) == 0

    def test_doi_hinh_chua_cong_bo_thi_bo_qua(self, conn, one_league):
        """Nguồn chỉ có đội hình quanh giờ bóng lăn — chưa có thì lượt sau thử lại."""
        one_league(FakeSource(
            upcoming=[make_fixture(id="10", kickoff=NOW + timedelta(minutes=50))],
            lineup=[]))
        assert planner.create_posts(conn, NOW + timedelta(days=1)) == 0

    def test_nguon_hong_khong_lam_chet_luot_chay(self, conn, one_league):
        class Broken(FakeSource):
            def standings(self, season):
                raise RuntimeError("máy chủ sập")

        one_league(Broken())
        assert planner.create_posts(conn, NOW) == 0   # không ném lỗi ra ngoài


class TestBoCucTranDau:
    """Dòng trận đấu: [logo] đội nhà — TỈ SỐ — đội khách [logo]."""

    def test_ket_qua_dat_ti_so_o_giua(self):
        match = make_fixture(finished=True, home_score=2, away_score=1)
        row = content.week_results_post("Ngoại hạng Anh", "Vòng 3", [match])["card_data"]["rows"][0]
        assert row["left"] == "Arsenal"
        assert row["center"] == "2 - 1"
        assert row["right"] == "Chelsea"

    def test_lich_thi_dau_dat_gio_o_giua(self):
        rows = content.fixtures_post("Ngoại hạng Anh", "Vòng 4", [make_fixture()])["card_data"]["rows"]
        match_row = next(r for r in rows if r.get("center"))
        assert match_row["center"] == make_fixture().vn_time

    def test_co_logo_ca_hai_doi(self):
        """Chỉ một logo thì dòng lệch hẳn về một bên, mà đội khách cũng cần nhận ra."""
        match = make_fixture(finished=True, home_score=1, away_score=0,
                             home_crest="http://x/home.png", away_crest="http://x/away.png")
        row = content.week_results_post("Ngoại hạng Anh", "Vòng 3", [match])["card_data"]["rows"][0]
        assert row["icon"] == "http://x/home.png"
        assert row["right_icon"] == "http://x/away.png"

    def test_ten_doi_dai_lam_ca_card_nho_chu_lai(self):
        """Thà cả card chữ nhỏ hơn còn hơn cắt "Crystal Palace" thành "Crystal Pal…"."""
        from autofb.football.card import _fit_match_size

        ngan = [Row("Hull", center="1 - 0", right="Spurs")]
        dai = [Row("Crystal Palace", center="1 - 0", right="Bournemouth")]
        assert _fit_match_size(dai, 45, 81, 1080) < _fit_match_size(ngan, 45, 81, 1080)

    def test_dong_thuong_khong_bi_anh_huong(self):
        """Bảng xếp hạng không có center — cỡ chữ giữ nguyên."""
        from autofb.football.card import _fit_match_size

        assert _fit_match_size([Row("1. Manchester City", "9")], 45, 81, 1080) == 45
