"""Lấy dữ liệu Ngoại hạng Anh từ API nội bộ của premierleague.com.

VÌ SAO DÙNG NGUỒN NÀY: đây là backend chạy chính website premierleague.com, trả đủ
lịch thi đấu, bảng xếp hạng, ĐỘI HÌNH RA SÂN và kết quả — miễn phí, không cần key.
Mọi API có giấy phép đàng hoàng đều bắt trả tiền cho phần đội hình
(football-data.org: add-on; API-Football: khoá mùa hiện tại ở gói miễn phí).

ĐÁNH ĐỔI PHẢI BIẾT: đây KHÔNG phải API công bố chính thức. Không có cam kết nào về
việc nó không đổi đường dẫn hay không chặn. Vì vậy mọi lỗi đều quy về
SourceUnavailable để lượt chạy chỉ bỏ qua bài bóng đá, không làm chết tiến trình.
"""

import logging
from datetime import datetime, timezone

import httpx

from . import crest
from .models import Fixture, Lineup, Standing, SourceUnavailable

logger = logging.getLogger(__name__)

BASE = "https://footballapi.pulselive.com/football"
COMPETITION_ID = 1
LEAGUE_NAME = "Ngoại hạng Anh"
TIMEOUT = 20

# Không có Origin/Referer thì máy chủ trả 403. Đây là kiểm tra CORS phía họ chứ
# không phải xác thực — gửi kèm là đủ, không cần token gì.
HEADERS = {
    "Origin": "https://www.premierleague.com",
    "Referer": "https://www.premierleague.com/",
    "User-Agent": "Mozilla/5.0 (compatible; AutoFB/1.0)",
    "Accept": "application/json",
}


def _get(path: str, params: dict | None = None) -> dict | list:
    try:
        response = httpx.get(f"{BASE}/{path}", params=params or {},
                             headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceUnavailable(f"premierleague.com: {exc}") from exc


def _millis_to_utc(millis) -> datetime:
    return datetime.fromtimestamp(int(millis) / 1000, tz=timezone.utc)


def current_season_id() -> int:
    """Id mùa giải đang diễn ra.

    API trả danh sách mùa theo thứ tự mới nhất trước, nên lấy phần tử đầu. Không
    ghim cứng số: mỗi mùa nó lại đổi, ghim cứng là hè sang năm hệ thống chết câm.
    """
    body = _get(f"competitions/{COMPETITION_ID}/compseasons", {"pageSize": 1})
    seasons = (body or {}).get("content") or []
    if not seasons:
        raise SourceUnavailable("premierleague.com: không đọc được mùa giải")
    return int(seasons[0]["id"])


def _fixtures(season_id: int, status: str, limit: int, order: str) -> list[dict]:
    body = _get("fixtures", {
        "comps": COMPETITION_ID, "compSeasons": season_id,
        "page": 0, "pageSize": limit, "sort": order, "statuses": status,
        # altIds để lấy mã opta ("t43") — mã này dựng ra URL logo đội.
        "altIds": "true",
    })
    return (body or {}).get("content") or []


def _to_fixture(raw: dict) -> Fixture:
    teams = raw.get("teams") or []
    if len(teams) < 2:
        raise SourceUnavailable("premierleague.com: trận thiếu đội")
    home, away = teams[0], teams[1]
    week = raw.get("gameweek", {}).get("gameweek")
    finished = str(raw.get("status", "")).upper() == "C"

    def score(side):
        value = side.get("score")
        return int(value) if value is not None else None

    return Fixture(
        # id trả về dạng số thực (128953.0) — ép về int trước khi thành chuỗi,
        # nếu không mọi khoá chống trùng đều dính đuôi ".0".
        id=str(int(float(raw["id"]))),
        league=LEAGUE_NAME,
        kickoff=_millis_to_utc(raw["kickoff"]["millis"]),
        home=home["team"]["name"],
        away=away["team"]["name"],
        home_short=_short(home), away_short=_short(away),
        home_crest=_crest(home), away_crest=_crest(away),
        home_score=score(home) if finished else None,
        away_score=score(away) if finished else None,
        finished=finished,
        round_label=f"Vòng {int(week)}" if week else "",
    )


def _short(side: dict) -> str:
    club = (side.get("team") or {}).get("club") or {}
    return club.get("shortName") or ""


def _crest(side: dict) -> str:
    return crest.premier_league_url(_opta_id(side.get("team") or {}))


def _opta_id(team: dict) -> str:
    return ((team.get("altIds") or {}).get("opta")) or ""


def upcoming_fixtures(season_id: int, limit: int = 20) -> list[Fixture]:
    """Các trận chưa đá, gần nhất trước."""
    return [_to_fixture(r) for r in _fixtures(season_id, "U", limit, "asc")]


def recent_results(season_id: int, limit: int = 20) -> list[Fixture]:
    """Các trận đã đá xong, mới nhất trước."""
    return [_to_fixture(r) for r in _fixtures(season_id, "C", limit, "desc")]


def standings(season_id: int) -> list[Standing]:
    body = _get("standings", {"compSeasons": season_id, "altIds": "true", "detail": 2})
    tables = (body or {}).get("tables") or []
    if not tables:
        raise SourceUnavailable("premierleague.com: không có bảng xếp hạng")

    rows = []
    for entry in tables[0].get("entries") or []:
        overall = entry.get("overall") or {}
        rows.append(Standing(
            position=int(entry.get("position", 0)),
            team=entry["team"]["name"],
            played=int(overall.get("played", 0)),
            points=int(overall.get("points", 0)),
            goal_diff=int(overall.get("goalsDifference", 0)),
            form=_form_of(entry),
            crest=crest.premier_league_url(_opta_id(entry.get("team") or {})),
        ))
    return rows


def _form_of(entry: dict) -> str:
    """Phong độ gần đây dạng "WWDLW".

    Nguồn KHÔNG trả sẵn chữ W/D/L: trường `form` là danh sách trận đầy đủ, phải tự
    so tỉ số của đội này với đối thủ. Vì vậy phải biết trong hai đội của trận thì
    đội nào là đội đang xét — so theo tên.
    """
    me = (entry.get("team") or {}).get("name")
    letters = []

    for match in (entry.get("form") or [])[-5:]:
        sides = match.get("teams") or []
        mine = next((s for s in sides if (s.get("team") or {}).get("name") == me), None)
        theirs = next((s for s in sides if s is not mine), None)
        if mine is None or theirs is None:
            continue

        ours, others = mine.get("score"), theirs.get("score")
        if ours is None or others is None:
            continue
        letters.append("W" if ours > others else "L" if ours < others else "D")

    return "".join(letters)


def lineups(fixture_id: str) -> list[Lineup]:
    """Đội hình ra sân. Rỗng nếu chưa công bố (thường trước giờ bóng lăn ~1 tiếng).

    Đội hình nằm trong chi tiết trận chứ không phải endpoint /teamlists riêng —
    endpoint đó trả 404.
    """
    body = _get(f"fixtures/{fixture_id}")
    result = []
    for team_list in (body or {}).get("teamLists") or []:
        starters = [_player_name(p) for p in team_list.get("lineup") or []]
        if not starters:
            continue
        team_id = team_list.get("teamId")
        result.append(Lineup(
            team=_team_name(body, team_id),
            crest=crest.premier_league_url(_opta_of(body, team_id)),
            formation=(team_list.get("formation") or {}).get("label", ""),
            starters=starters,
        ))
    return result


def _player_name(player: dict) -> str:
    name = player.get("name") or {}
    return name.get("display") or f"{name.get('first', '')} {name.get('last', '')}".strip()


def _opta_of(fixture: dict, team_id) -> str:
    for side in fixture.get("teams") or []:
        if (side.get("team") or {}).get("id") == team_id:
            return _opta_id(side.get("team") or {})
    return ""


def _team_name(fixture: dict, team_id) -> str:
    for side in fixture.get("teams") or []:
        team = side.get("team") or {}
        if team.get("id") == team_id:
            return team.get("name", "")
    return ""
