"""Dựng nội dung bài đăng và dữ liệu vẽ card cho từng loại bài bóng đá.

Tách khỏi planner.py: planner quyết định LÚC NÀO đăng gì, file này quyết định bài
TRÔNG NHƯ THẾ NÀO. Hai thứ đổi vì lý do khác nhau — đổi câu chữ không nên phải đụng
vào logic lịch.

card_data trả về là dict thuần để lưu JSON vào cột post.card_data. Card được vẽ LẠI
lúc đăng chứ không lưu ảnh (xem card_renderer.render_for_post) — ổ USB của box ghi
2,9 MB/s, mọi thứ tránh ghi được thì tránh.
"""

from .models import Fixture, Lineup, Standing

HASHTAGS = {
    "Ngoại hạng Anh": "#ngoaihanganh #bongda #thethao",
    "Champions League": "#championsleague #c1 #bongda",
}


def _tags(league: str) -> str:
    return HASHTAGS.get(league, "#bongda #thethao")


def _source(league: str) -> str:
    return "premierleague.com" if league == "Ngoại hạng Anh" else "uefa.com"


def fixtures_post(league: str, round_label: str, fixtures: list[Fixture]) -> dict:
    """Lịch thi đấu vòng tới. Nhóm theo ngày vì một vòng thường trải 2-3 ngày."""
    heading = f"LỊCH THI ĐẤU {round_label}".strip().upper()
    rows, lines, current_day = [], [], None

    for match in fixtures:
        day = f"{match.vn_weekday} {match.vn_date}"
        if day != current_day:
            current_day = day
            rows.append({"left": day, "right": "", "dim": True})
            lines.append(f"\n{day}")
        rows.append({"left": match.short_score_line, "right": match.vn_time,
                     "icon": match.home_crest})
        lines.append(f"{match.vn_time}  {match.home_name} – {match.away_name}")

    body = "\n".join(lines).strip()
    content = (
        f"{heading.title()} — {league}\n\n{body}\n\n"
        f"Giờ Việt Nam. Trận nào đáng xem nhất tuần này?\n\n{_tags(league)}"
    )
    return {
        "content": content,
        "card_kind": "table",
        "card_data": {
            "heading": heading, "rows": rows,
            "subheading": f"{league} · giờ Việt Nam",
            "footer": f"Nguồn: {_source(league)}",
        },
    }


def standings_post(league: str, after_round: str, table: list[Standing]) -> dict:
    """Bảng xếp hạng. Card chỉ hiện top 12, bài viết ghi đủ hơn."""
    heading = "BẢNG XẾP HẠNG"
    rows = [{"left": f"{s.position}. {s.team}", "right": str(s.points), "icon": s.crest}
            for s in table]
    lines = [
        f"{s.position}. {s.team} — {s.points} điểm ({s.played} trận"
        + (f", {s.form}" if s.form else "") + ")"
        for s in table[:10]
    ]
    content = (
        f"Bảng xếp hạng {league}{(' ' + after_round) if after_round else ''}\n\n"
        + "\n".join(lines)
        + f"\n\nĐội bạn theo dõi đang đứng thứ mấy?\n\n{_tags(league)}"
    )
    return {
        "content": content,
        "card_kind": "table",
        "card_data": {
            "heading": heading, "rows": rows,
            "subheading": f"{league}{(' · ' + after_round) if after_round else ''}",
            "footer": f"Nguồn: {_source(league)}",
        },
    }


def week_results_post(league: str, round_label: str, results: list[Fixture]) -> dict:
    """Tổng hợp kết quả cả vòng vừa qua, gộp thành một bài."""
    heading = f"KẾT QUẢ {round_label}".strip().upper()
    rows = [
        {"left": f"{f.home_name} – {f.away_name}",
         "right": f"{f.home_score}-{f.away_score}", "icon": f.home_crest}
        for f in results
    ]
    lines = [f"{f.home_name} {f.home_score} - {f.away_score} {f.away_name}" for f in results]
    content = (
        f"Kết quả {round_label} {league}\n\n" + "\n".join(lines)
        + f"\n\nKết quả nào khiến bạn bất ngờ nhất?\n\n{_tags(league)}"
    )
    return {
        "content": content,
        "card_kind": "table",
        "card_data": {
            "heading": heading, "rows": rows, "subheading": league,
            "footer": f"Nguồn: {_source(league)}",
        },
    }


def lineup_post(match: Fixture, lineups: list[Lineup]) -> dict:
    """Đội hình ra sân, một bài cho một trận.

    Card xếp hai đội thành hai cột đối nhau theo thứ tự vị trí — nhìn là so được
    ngay ai đá với ai. Nếu nguồn chỉ có đội hình một bên thì card về một cột.
    """
    home = lineups[0] if lineups else None
    away = lineups[1] if len(lineups) > 1 else None
    depth = max(len(home.starters) if home else 0, len(away.starters) if away else 0)

    rows = []
    for i in range(depth):
        rows.append({
            "left": home.starters[i] if home and i < len(home.starters) else "",
            "right": away.starters[i] if away and i < len(away.starters) else "",
            # Logo chỉ ở dòng đầu: 11 dòng cùng một logo là nhiễu, không phải thông tin.
            "icon": (home.crest if home else "") if i == 0 else "",
        })

    formations = " · ".join(
        f"{lu.team} {lu.formation}".strip() for lu in lineups if lu.formation
    )
    text = []
    for lu in lineups:
        text.append(f"{lu.team} ({lu.formation}): " + ", ".join(lu.starters))

    content = (
        f"Đội hình ra sân: {match.home_name} vs {match.away_name}\n"
        f"{match.vn_weekday} {match.vn_date}, {match.vn_time} giờ Việt Nam\n\n"
        + "\n\n".join(text)
        + f"\n\nBạn dự đoán tỉ số bao nhiêu?\n\n{_tags(match.league)}"
    )
    return {
        "content": content,
        "card_kind": "table",
        "card_data": {
            "heading": "ĐỘI HÌNH RA SÂN",
            "subheading": formations or f"{match.home_name} vs {match.away_name}",
            "rows": rows,
            "footer": f"{match.home_name} vs {match.away_name} · {match.vn_time} VN",
        },
    }


def result_post(match: Fixture) -> dict:
    """Kết quả một trận. Dùng card TIÊU ĐỀ chứ không phải card bảng.

    "Arsenal 2-1 Chelsea" là một câu ngắn — chữ to giữa card đọc rõ hơn nhiều so
    với nhét một dòng vào bảng trống hoác.
    """
    headline = f"{match.home_name} {match.home_score} - {match.away_score} {match.away_name}"
    content = (
        f"{headline}\n\n"
        f"{match.league}{(' · ' + match.round_label) if match.round_label else ''}\n\n"
        f"Bạn nghĩ sao về kết quả này?\n\n{_tags(match.league)}"
    )
    return {"content": content, "card_kind": "title", "card_data": {}}
