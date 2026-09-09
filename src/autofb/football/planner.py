"""Quyết định lúc nào đăng bài bóng đá nào.

Lịch đăng theo yêu cầu:
  đầu tuần   — 3 bài: kết quả vòng vừa qua, bảng xếp hạng, lịch thi đấu vòng tới
  trước trận — 1 bài đội hình ra sân cho MỖI trận
  sau trận   — 1 bài kết quả cho MỖI trận

Chống trùng bằng khoá `ref` ghi vào cột post.ref (có UNIQUE index). Vòng lặp chạy
5 phút một lần nên nếu không chặn, mỗi trận sẽ sinh ra hàng chục bài đội hình.

Nguồn hỏng KHÔNG được làm chết lượt chạy: hai API đều là backend nội bộ của
premierleague.com và uefa.com. Mọi SourceUnavailable bị nuốt tại đây, lượt sau thử lại.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import content, premier_league, uefa
from .models import VN_TIMEZONE, Fixture, SourceUnavailable

logger = logging.getLogger(__name__)

# Cửa sổ bắt trận sắp đá. Rộng hơn khoảng cách giữa hai lượt chạy (5 phút) để không
# bỏ sót trận nào, và dedupe theo ref lo phần không đăng trùng.
LINEUP_WINDOW_MINUTES = 75
# Chờ sau giờ bóng lăn trước khi đăng kết quả. 140 phút = 90 phút thi đấu + bù giờ +
# nghỉ giữa hiệp + vài phút để API kịp cập nhật tỉ số cuối.
RESULT_AFTER_MINUTES = 140
# Chỉ đăng trận vừa xong trong ngần này phút. Không có cận trên thì mọi trận đã đá
# từ đầu mùa đều thoả, lần chạy đầu sẽ đăng một tràng tin cũ. 8 tiếng đủ rộng để hệ
# thống chết nửa buổi vẫn đăng bù được.
RESULT_WITHIN_MINUTES = 480


@dataclass(frozen=True)
class League:
    key: str            # tiền tố khoá chống trùng
    name: str
    module: object      # premier_league hoặc uefa
    enabled: bool = True

    def season(self, now: datetime):
        if self.module is premier_league:
            return premier_league.current_season_id()
        return uefa.season_year(now)


LEAGUES = (
    League("pl", "Ngoại hạng Anh", premier_league),
    League("cl", "Champions League", uefa),
)


def _round_of(fixtures: list[Fixture]) -> tuple[str, list[Fixture]]:
    """Nhóm trận của vòng đấu ĐẦU TIÊN trong danh sách.

    Lấy nguyên một vòng chứ không phải N trận đầu: một vòng Ngoại hạng Anh có 10
    trận nhưng trải từ thứ Bảy tới thứ Ba, cắt theo số lượng sẽ đứt giữa vòng.
    """
    if not fixtures:
        return "", []
    label = fixtures[0].round_label
    return label, [f for f in fixtures if f.round_label == label]


def _weekly_posts(league: League, season, now: datetime) -> list[dict]:
    """Ba bài đầu tuần. Khoá chống trùng theo tuần ISO nên mỗi tuần chỉ ra một lần."""
    week = now.astimezone(VN_TIMEZONE).strftime("%G-W%V")
    module = league.module
    posts = []

    done_label, done = _round_of(module.recent_results(season, 30))
    if done:
        posts.append(_wrap(league, f"{league.key}:results:{week}",
                           content.week_results_post(league.name, done_label, done)))

    table = module.standings(season)
    if table:
        posts.append(_wrap(league, f"{league.key}:standings:{week}",
                           content.standings_post(league.name, f"sau {done_label}" if done_label else "", table)))

    next_label, upcoming = _round_of(module.upcoming_fixtures(season, 30))
    if upcoming:
        posts.append(_wrap(league, f"{league.key}:fixtures:{week}",
                           content.fixtures_post(league.name, next_label, upcoming)))

    return posts


def _lineup_posts(league: League, season, now: datetime) -> list[dict]:
    """Đội hình các trận sắp đá. Trận nào nguồn chưa công bố thì bỏ qua, lượt sau thử lại."""
    posts = []
    for match in league.module.upcoming_fixtures(season, 30):
        if not match.starts_within(now, LINEUP_WINDOW_MINUTES):
            continue
        lineups = league.module.lineups(match.id)
        if not lineups:
            continue
        posts.append(_wrap(league, f"{league.key}:lineup:{match.id}",
                           content.lineup_post(match, lineups)))
    return posts


def _result_posts(league: League, season, now: datetime) -> list[dict]:
    """Kết quả từng trận vừa đá xong."""
    posts = []
    for match in league.module.recent_results(season, 20):
        if not match.just_ended(now, RESULT_AFTER_MINUTES, RESULT_WITHIN_MINUTES):
            continue
        posts.append(_wrap(league, f"{league.key}:result:{match.id}",
                           content.result_post(match)))
    return posts


def _wrap(league: League, ref: str, built: dict) -> dict:
    return {"ref": ref, "sport": "football", "league": league.name, **built}


def plan(conn: sqlite3.Connection, now: datetime, weekly_day: int = 0) -> list[dict]:
    """Danh sách bài bóng đá cần tạo lúc này, đã loại những bài đã tạo trước đó.

    weekly_day theo quy ước của datetime.weekday(): 0 = thứ Hai.
    """
    is_weekly_day = now.astimezone(VN_TIMEZONE).weekday() == weekly_day
    wanted: list[dict] = []

    for league in LEAGUES:
        if not league.enabled:
            continue
        try:
            season = league.season(now)
            if is_weekly_day:
                wanted += _weekly_posts(league, season, now)
            wanted += _lineup_posts(league, season, now)
            wanted += _result_posts(league, season, now)
        except SourceUnavailable as exc:
            logger.warning("Bỏ qua %s lượt này: %s", league.name, exc)
        except Exception:  # noqa: BLE001 - nguồn ngoài, không được kéo sập lượt chạy
            logger.exception("Lỗi ngoài dự tính khi lấy dữ liệu %s", league.name)

    return [post for post in wanted if not _already_made(conn, post["ref"])]


def _already_made(conn: sqlite3.Connection, ref: str) -> bool:
    row = conn.execute("SELECT 1 FROM post WHERE ref = ? LIMIT 1", (ref,)).fetchone()
    return row is not None


def create_posts(conn: sqlite3.Connection, now: datetime) -> int:
    """Tạo bài bóng đá đến hạn, trả về số bài đã tạo.

    Bài vào thẳng trạng thái 'approved' và mang scheduled_at = bây giờ: chúng gắn
    với một mốc thời gian thật (1 tiếng trước bóng lăn, ngay sau trận) nên để nằm
    xếp hàng sau bản tin là mất luôn ý nghĩa.
    """
    created = 0
    stamp = now.isoformat()

    for post in plan(conn, now):
        try:
            conn.execute(
                "INSERT INTO post (cluster_id, sport, content, status, origin, ref,"
                " card_kind, card_data, scheduled_at, created_at)"
                " VALUES (NULL, ?, ?, 'approved', 'football', ?, ?, ?, ?, ?)",
                (post["sport"], post["content"], post["ref"], post["card_kind"],
                 json.dumps(post["card_data"], ensure_ascii=False), stamp, stamp),
            )
            created += 1
        except sqlite3.IntegrityError:
            # Index UNIQUE trên ref đã chặn: hai tiến trình cùng lúc thấy một trận.
            # Không phải lỗi, chỉ nghĩa là bài đã có.
            logger.debug("Bài %s đã tồn tại", post["ref"])

    if created:
        conn.commit()
    return created
