"""M3 — lọc và xếp hàng tin ứng viên.

Không có thang điểm. Đã có bước duyệt bài ở M6 thì bộ lọc máy không cần thông minh,
và mọi trọng số lúc này cũng chỉ là đoán vì chưa có dữ liệu hiệu quả thật.

4 luật: trong 24h · chưa đăng · không phải bài tiện ích · chỉ tiếng Việt.
Xếp: tin nhiều nguồn cùng đưa lên trước, rồi đến tin mới nhất. Chia suất theo môn.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from .config import PostSettings

CANDIDATE_SQL = """
SELECT c.id            AS cluster_id,
       c.representative AS representative,
       c.sport          AS sport,
       c.article_count  AS article_count,
       MAX(a.published_at) AS latest_published
  FROM topic_cluster c
  JOIN raw_article   a ON a.cluster_id = c.id
 WHERE c.posted = 0
   AND a.is_utility = 0
   AND a.lang = 'vi'
   AND a.published_at >= :cutoff
   AND NOT EXISTS (SELECT 1 FROM post p WHERE p.cluster_id = c.id)
 GROUP BY c.id
 ORDER BY c.article_count DESC, latest_published DESC
"""


_VIETNAMESE_MARKS = set("àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợ"
                        "ùúủũụưừứửữựỳýỷỹỵđ")

# Viết hoa, không dấu, nhưng là từ tiếng Việt / viết tắt — không phải tên riêng.
# Viết hoa, không dấu, nhưng không phải tên riêng. Chủ yếu là viết tắt và vài từ
# tiếng Việt hiếm hoi không mang dấu ("Tin", "Sao", "Cup").
_NOT_ENTITY = {
    "HLV", "CLB", "VDV", "BXH", "VCK", "Video", "Clip",
    "Tin", "Top", "Sao", "Cup", "Vua", "Ban", "Nam", "Hang",
}


def _entities(title: str) -> set[str]:
    """Lấy tên riêng trong tiêu đề: Arsenal, Chelsea, Havertz, Alcaraz…

    Nhận diện bằng "viết hoa VÀ không có dấu tiếng Việt". Đơn giản nhưng ăn khớp thực tế:
    tên đội bóng và cầu thủ hầu hết là chữ Latin không dấu, còn từ tiếng Việt viết hoa
    ở đầu câu (Trận, Đội, Xác, Tuyển…) gần như luôn mang dấu nên tự bị loại.

    Không bỏ từ đầu câu — đó thường chính là tên đội ("Arsenal đánh bại Chelsea").
    """
    entities = set()
    for raw in title.split():
        word = raw.strip(".,:;'\"()[]!?")
        if len(word) < 3 or not word[0].isupper():
            continue
        if word in _NOT_ENTITY:
            continue
        if any(char.lower() in _VIETNAMESE_MARKS for char in word):
            continue
        entities.add(word)
    return entities


def _apply_quota(rows: list[sqlite3.Row], settings: PostSettings) -> list[sqlite3.Row]:
    """Chia suất theo môn, và không lấy hai bài viết về cùng một sự kiện.

    Chia suất theo môn: không có thì bóng đá (78% lượng crawl thực tế) chiếm sạch.

    Khử trùng sự kiện: một trận đấu sinh ra rất nhiều bài với tiêu đề khác hẳn nhau
    ("Havertz giúp Arsenal thắng ngược Chelsea", "Arteta: trận thắng Chelsea chứng tỏ…",
    "Neville chỉ ra tử huyệt của Chelsea"). Khâu gom nhóm ở M2 so theo tiêu đề nên không
    nhận ra, dẫn tới đăng 3-4 bài về cùng một trận — nhìn y như spam.
    Ở đây so theo tên riêng: trùng dù chỉ MỘT tên đội/cầu thủ là coi như cùng sự kiện.
    Ngưỡng gắt vì trong một ngày, nhiều tin về cùng một CLB gần như luôn là cùng trận —
    và mỗi ngày chỉ đăng 5 bài nên thà bỏ sót còn hơn đăng trùng.
    """
    picked: list[sqlite3.Row] = []
    per_sport: dict[str, int] = {}
    picked_entities: list[set[str]] = []

    for row in rows:
        if len(picked) >= settings.daily_quota:
            break
        if per_sport.get(row["sport"], 0) >= settings.per_sport_quota:
            continue

        entities = _entities(row["representative"])
        if entities and any(entities & seen for seen in picked_entities):
            continue

        per_sport[row["sport"]] = per_sport.get(row["sport"], 0) + 1
        picked_entities.append(entities)
        picked.append(row)

    return picked


def select_candidates(
    conn: sqlite3.Connection, settings: PostSettings, max_age_hours: int = 24
) -> list[sqlite3.Row]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    rows = conn.execute(CANDIDATE_SQL, {"cutoff": cutoff}).fetchall()
    return _apply_quota(rows, settings)


def articles_of_cluster(conn: sqlite3.Connection, cluster_id: int) -> list[dict]:
    """Bài trong nhóm, nguồn đăng sớm nhất đứng đầu (dùng làm bài chính)."""
    rows = conn.execute(
        "SELECT title, summary, source_name, url, image_url, published_at FROM raw_article"
        " WHERE cluster_id = ? AND is_utility = 0 ORDER BY published_at ASC",
        (cluster_id,),
    ).fetchall()
    return [dict(row) for row in rows]
