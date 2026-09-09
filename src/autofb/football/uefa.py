"""Lấy dữ liệu Champions League từ API nội bộ của uefa.com.

Cùng lý do và cùng rủi ro với premier_league.py: đây là backend chạy website
uefa.com, miễn phí và không cần key, nhưng không phải API công bố chính thức.

Khác biệt so với Ngoại hạng Anh cần nhớ:
  - Thể thức mới của Champions League là MỘT bảng 36 đội ("league phase"), không
    còn 8 bảng nhỏ. Bảng xếp hạng vì vậy dài 36 dòng — card phải cắt bớt.
  - Bảng xếp hạng không trả sẵn thứ hạng, phải tự đánh số theo thứ tự trả về.
  - Đội hình có endpoint riêng và thường chỉ có dữ liệu quanh giờ thi đấu.
"""

import logging
from datetime import datetime

import httpx

from . import crest
from .models import Fixture, Lineup, Standing, SourceUnavailable

logger = logging.getLogger(__name__)

MATCH_BASE = "https://match.uefa.com/v5"
STANDINGS_BASE = "https://standings.uefa.com/v1"
COMPETITION_ID = 1
LEAGUE_NAME = "Champions League"
TIMEOUT = 20

HEADERS = {
    "Referer": "https://www.uefa.com/",
    "User-Agent": "Mozilla/5.0 (compatible; AutoFB/1.0)",
    "Accept": "application/json",
}


def _get(url: str, params: dict | None = None):
    try:
        response = httpx.get(url, params=params or {}, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceUnavailable(f"uefa.com: {exc}") from exc


def season_year(now: datetime) -> int:
    """Mùa giải UEFA gọi theo năm KẾT THÚC: mùa 2026-27 là seasonYear=2027.

    Mùa mới bắt đầu từ tháng 7, nên trước tháng 7 vẫn thuộc mùa của năm hiện tại.
    """
    return now.year + 1 if now.month >= 7 else now.year


def _to_fixture(raw: dict) -> Fixture:
    status = str(raw.get("status", "")).upper()
    score = raw.get("score") or {}
    total = score.get("total") or {}
    matchday = (raw.get("matchday") or {}).get("longName") or ""

    def side(key: str) -> str:
        team = raw.get(key) or {}
        return team.get("internationalName") or team.get("displayName") or "?"

    return Fixture(
        id=str(raw["id"]),
        league=LEAGUE_NAME,
        # dateTime luôn ở UTC (đuôi Z). fromisoformat của Python 3.12 đọc được "Z".
        kickoff=datetime.fromisoformat(raw["kickOffTime"]["dateTime"]),
        home=side("homeTeam"),
        away=side("awayTeam"),
        home_crest=crest.uefa_url((raw.get("homeTeam") or {}).get("id")),
        away_crest=crest.uefa_url((raw.get("awayTeam") or {}).get("id")),
        home_score=total.get("home"),
        away_score=total.get("away"),
        finished=status == "FINISHED",
        round_label=matchday,
    )


def _matches(year: int, limit: int, order: str) -> list[dict]:
    # offset là tham số BẮT BUỘC — thiếu nó máy chủ trả 404 kèm thông báo khó hiểu
    # "null is not valid for offset" chứ không phải lỗi 400 như thường thấy.
    body = _get(f"{MATCH_BASE}/matches", {
        "competitionId": COMPETITION_ID, "seasonYear": year,
        "limit": limit, "offset": 0, "order": order,
    })
    return body if isinstance(body, list) else []


def upcoming_fixtures(year: int, limit: int = 20) -> list[Fixture]:
    fixtures = [_to_fixture(m) for m in _matches(year, 120, "ASC")]
    return [f for f in fixtures if not f.finished][:limit]


def recent_results(year: int, limit: int = 20) -> list[Fixture]:
    fixtures = [_to_fixture(m) for m in _matches(year, 120, "DESC")]
    return [f for f in fixtures if f.finished][:limit]


def standings(year: int) -> list[Standing]:
    body = _get(f"{STANDINGS_BASE}/standings", {
        "competitionId": COMPETITION_ID, "seasonYear": year, "phase": "TOURNAMENT",
    })
    groups = body if isinstance(body, list) else []
    if not groups:
        raise SourceUnavailable("uefa.com: không có bảng xếp hạng")

    rows = []
    for index, item in enumerate(groups[0].get("items") or [], start=1):
        team = item.get("team") or {}
        rows.append(Standing(
            # Nguồn để trống thứ hạng ở thể thức league phase — tự đánh số theo
            # thứ tự trả về, vốn đã là thứ tự xếp hạng.
            position=int(item.get("position") or index),
            team=team.get("internationalName") or team.get("displayName") or "?",
            played=int(item.get("played") or 0),
            points=int(item.get("points") or 0),
            goal_diff=int(item.get("goalDifference") or 0),
            crest=crest.uefa_url(team.get("id")),
        ))
    return rows


def lineups(match_id: str) -> list[Lineup]:
    """Đội hình ra sân. Rỗng khi UEFA chưa công bố (lineupStatus != AVAILABLE)."""
    body = _get(f"{MATCH_BASE}/matches/{match_id}/lineups")
    if not isinstance(body, dict) or body.get("lineupStatus") != "AVAILABLE":
        return []

    result = []
    for key in ("homeTeam", "awayTeam"):
        team_data = body.get(key) or {}
        starters = [
            _player_name(p) for p in team_data.get("players") or []
            if p.get("fieldPosition") or p.get("started")
        ]
        if not starters:
            continue
        result.append(Lineup(
            team=(team_data.get("team") or {}).get("internationalName", ""),
            formation=team_data.get("formation") or "",
            starters=starters[:11],
        ))
    return result


def _player_name(player: dict) -> str:
    person = player.get("player") or player
    return (person.get("internationalName") or person.get("shortName")
            or person.get("translationName") or "?")
