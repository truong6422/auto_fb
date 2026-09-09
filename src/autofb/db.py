"""SQLite: schema và truy cập dữ liệu.

Ba bảng theo spec MVP:
  raw_article   — bài crawl thô (nguồn sự thật, không bao giờ sửa)
  topic_cluster — nhóm các bài cùng một tin (cho biết tin nào nhiều nguồn đưa)
  post          — bài đã dựng để đăng (M4 trở đi mới ghi vào)
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import PROJECT_ROOT

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "autofb.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS topic_cluster (
    id                INTEGER PRIMARY KEY,
    representative    TEXT    NOT NULL,          -- tiêu đề đại diện, dùng để so khớp bài mới
    title_key         TEXT    NOT NULL,          -- representative đã chuẩn hoá
    sport             TEXT    NOT NULL,
    article_count     INTEGER NOT NULL DEFAULT 0,-- bao nhiêu nguồn cùng đưa tin này
    first_seen_at     TEXT    NOT NULL,
    last_seen_at      TEXT    NOT NULL,
    posted            INTEGER NOT NULL DEFAULT 0 -- đã đăng chủ đề này chưa
);
CREATE INDEX IF NOT EXISTS idx_cluster_last_seen ON topic_cluster(last_seen_at);

CREATE TABLE IF NOT EXISTS raw_article (
    id              INTEGER PRIMARY KEY,
    guid            TEXT    NOT NULL UNIQUE,     -- chống trùng lớp 1
    url             TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    summary         TEXT    NOT NULL DEFAULT '',
    source_name     TEXT    NOT NULL,
    sport           TEXT    NOT NULL,
    lang            TEXT    NOT NULL,
    published_at    TEXT,
    fetched_at      TEXT    NOT NULL,
    is_utility      INTEGER NOT NULL DEFAULT 0,  -- bài lịch thi đấu/BXH: lưu nhưng không đăng
    image_url       TEXT,                        -- ảnh do RSS của nguồn cung cấp
    cluster_id      INTEGER REFERENCES topic_cluster(id)
);
CREATE INDEX IF NOT EXISTS idx_article_cluster ON raw_article(cluster_id);
CREATE INDEX IF NOT EXISTS idx_article_published ON raw_article(published_at);

CREATE TABLE IF NOT EXISTS post (
    id                 INTEGER PRIMARY KEY,
    cluster_id         INTEGER REFERENCES topic_cluster(id),  -- NULL với bài tự soạn
    sport              TEXT    NOT NULL,
    content            TEXT    NOT NULL,
    status             TEXT    NOT NULL DEFAULT 'pending',  -- pending|approved|posted|failed|blocked
    affiliate_link     TEXT,
    comment_status     TEXT    NOT NULL DEFAULT 'none',     -- none|pending|posted|failed
    fb_post_id         TEXT,                                -- đường lui cho Phase 2 (thu Insights)
    note               TEXT,                                -- lý do bị chặn / ghi chú lỗi đăng
    origin             TEXT    NOT NULL DEFAULT 'auto',     -- auto=bản tin | manual=tự soạn | football
    ref                TEXT,                                -- khoá chống trùng bài bóng đá
    card_kind          TEXT    NOT NULL DEFAULT 'title',    -- title | table
    card_data          TEXT,                                -- JSON dựng card bảng
    threads_id         TEXT,                                -- id bài đăng lại trên Threads
    threads_status     TEXT    NOT NULL DEFAULT 'none',     -- none|posted|failed
    scheduled_at       TEXT,                                -- bài tự soạn: hẹn giờ đăng
    image_url          TEXT,                                -- ảnh minh hoạ (URL của nguồn)
    image_credit       TEXT,                                -- tên báo sở hữu ảnh
    source_url         TEXT,                                -- link bài gốc, đăng ở comment
    created_at         TEXT    NOT NULL,
    posted_at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_post_status ON post(status);
-- UNIQUE cho phép nhiều NULL trong SQLite, nên bài crawl (ref rỗng) không bị chặn,
-- còn bài bóng đá thì không thể tạo trùng dù vòng lặp chạy 5 phút một lần.


CREATE TABLE IF NOT EXISTS affiliate_link (
    id          INTEGER PRIMARY KEY,
    sport       TEXT    NOT NULL,
    url         TEXT    NOT NULL,
    label       TEXT    NOT NULL DEFAULT '',
    enabled     INTEGER NOT NULL DEFAULT 1,
    use_count   INTEGER NOT NULL DEFAULT 0,   -- dùng để xoay vòng link trong cùng môn
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_link_sport ON affiliate_link(sport, enabled);

-- Nhóm Facebook để chia sẻ bài vào.
--
-- KHÔNG có chỗ nào trong code đăng bài vào nhóm, và sẽ không có: Meta gỡ toàn bộ
-- Groups API ngày 22/04/2024 (xoá permission publish_to_groups trên mọi phiên bản).
-- Cách duy nhất còn lại là bấm tay. Bảng này chỉ để việc bấm tay đó nhanh và không
-- sót nhóm — nhớ giúp người dùng đã chia sẻ bài nào vào đâu rồi.
CREATE TABLE IF NOT EXISTS fb_group (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    url         TEXT    NOT NULL UNIQUE,
    note        TEXT    NOT NULL DEFAULT '',
    enabled     INTEGER NOT NULL DEFAULT 1,
    -- Nhiều nhóm xoá thẳng bài có link ra ngoài. Với nhóm đó, nội dung sao chép ra
    -- không kèm link — người quan tâm tự tìm tên Page.
    no_link     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

-- Bài nào đã chia sẻ vào nhóm nào.
-- Khoá theo fb_post_id chứ không theo post.id: danh sách bài trên màn hình lấy từ
-- Fanpage, mà Fanpage có cả bài không do AutoFB đăng.
CREATE TABLE IF NOT EXISTS group_share (
    fb_post_id  TEXT    NOT NULL,
    group_id    INTEGER NOT NULL REFERENCES fb_group(id) ON DELETE CASCADE,
    shared_at   TEXT    NOT NULL,
    PRIMARY KEY (fb_post_id, group_id)
);

-- Thông số nhịp chạy sửa được từ màn hình web (runtime_settings.py).
-- Chỉ chứa phần ĐÈ LÊN config/sources.yaml: không có dòng nào thì dùng giá trị trong file.
CREATE TABLE IF NOT EXISTS setting (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # Ba tiến trình (web, crawler, publisher) dùng chung một file DB. WAL cho phép đọc
    # song song nhưng CHỈ MỘT tiến trình được ghi tại một thời điểm — không có dòng này
    # thì tiến trình thứ hai ném "database is locked" ngay lập tức thay vì chờ.
    # 15s: crawler ghi cả trăm bài một lượt, publisher không được bỏ cuộc giữa chừng.
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


# Cột thêm sau khi DB đã tồn tại. CREATE TABLE IF NOT EXISTS không đụng tới bảng cũ,
# nên phải ALTER thủ công — không thể xoá DB mỗi lần đổi schema trên máy đang chạy.
_ADDED_COLUMNS = (
    ("raw_article", "is_utility", "INTEGER NOT NULL DEFAULT 0"),
    ("post", "note", "TEXT"),
    ("post", "origin", "TEXT NOT NULL DEFAULT 'auto'"),
    ("post", "scheduled_at", "TEXT"),
    ("post", "image_url", "TEXT"),
    ("post", "source_url", "TEXT"),
    ("post", "image_credit", "TEXT"),
    ("raw_article", "image_url", "TEXT"),
    # Bài bóng đá: ref là khoá chống trùng ("pl:lineup:128953"), card_kind chọn kiểu
    # card, card_data là JSON để vẽ lại card lúc đăng thay vì lưu sẵn ảnh.
    ("post", "ref", "TEXT"),
    ("post", "card_kind", "TEXT NOT NULL DEFAULT 'title'"),
    ("post", "card_data", "TEXT"),
    # Đăng lại sang Threads: trạng thái TÁCH RIÊNG khỏi status của bài, y như comment.
    # Bài đã lên Facebook rồi mà Threads hỏng thì không được coi là bài hỏng — đăng
    # lại là ra hai bài trùng trên Fanpage.
    ("post", "threads_id", "TEXT"),
    ("post", "threads_status", "TEXT NOT NULL DEFAULT 'none'"),  # none|posted|failed
    ("fb_group", "no_link", "INTEGER NOT NULL DEFAULT 0"),
)


def _apply_migrations(conn: sqlite3.Connection) -> None:
    for table, column, definition in _ADDED_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if existing and column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    # Tạo SAU khi ALTER: trên DB cũ chưa có cột `ref`, đặt index trong SCHEMA sẽ
    # lỗi "no such column" ngay lúc khởi động.
    # UNIQUE cho phép nhiều NULL trong SQLite, nên bài crawl (ref rỗng) không bị chặn.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_post_ref ON post(ref)")


def _relax_post_cluster_id(conn: sqlite3.Connection) -> None:
    """Bỏ ràng buộc NOT NULL trên post.cluster_id.

    Bài tự soạn không gắn với tin crawl nào nên cluster_id phải để trống được.
    SQLite không có ALTER COLUMN — cách duy nhất là dựng bảng mới rồi chép dữ liệu sang.
    """
    columns = conn.execute("PRAGMA table_info(post)").fetchall()
    if not columns:
        return
    cluster = next((c for c in columns if c["name"] == "cluster_id"), None)
    if cluster is None or not cluster["notnull"]:
        return

    names = ", ".join(c["name"] for c in columns)
    conn.execute("ALTER TABLE post RENAME TO post_old")
    conn.executescript(SCHEMA)
    conn.execute(f"INSERT INTO post ({names}) SELECT {names} FROM post_old")
    conn.execute("DROP TABLE post_old")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _apply_migrations(conn)
    _relax_post_cluster_id(conn)
    conn.commit()


@contextmanager
def session(db_path: Path | str | None = None):
    """Mở kết nối, tạo schema nếu chưa có, đóng khi xong."""
    conn = connect(db_path)
    try:
        init_schema(conn)
        yield conn
    finally:
        conn.close()


def guid_exists(conn: sqlite3.Connection, guid: str) -> bool:
    row = conn.execute("SELECT 1 FROM raw_article WHERE guid = ? LIMIT 1", (guid,)).fetchone()
    return row is not None


def recent_clusters(conn: sqlite3.Connection, since_iso: str) -> list[sqlite3.Row]:
    """Cluster còn 'sống' — chỉ so khớp bài mới với nhóm này, không quét cả bảng."""
    return conn.execute(
        "SELECT id, representative, title_key, sport FROM topic_cluster"
        " WHERE last_seen_at >= ? ORDER BY id DESC",
        (since_iso,),
    ).fetchall()


def create_cluster(
    conn: sqlite3.Connection, representative: str, title_key: str, sport: str, now_iso: str
) -> int:
    cursor = conn.execute(
        "INSERT INTO topic_cluster"
        " (representative, title_key, sport, article_count, first_seen_at, last_seen_at)"
        " VALUES (?, ?, ?, 0, ?, ?)",
        (representative, title_key, sport, now_iso, now_iso),
    )
    return int(cursor.lastrowid)


def touch_cluster(conn: sqlite3.Connection, cluster_id: int, now_iso: str) -> None:
    conn.execute(
        "UPDATE topic_cluster SET article_count = article_count + 1, last_seen_at = ?"
        " WHERE id = ?",
        (now_iso, cluster_id),
    )


def insert_article(conn: sqlite3.Connection, article: dict, cluster_id: int) -> int | None:
    """Trả về id bài mới, hoặc None nếu guid đã tồn tại (chống trùng lớp 1)."""
    try:
        cursor = conn.execute(
            "INSERT INTO raw_article"
            " (guid, url, title, summary, source_name, sport, lang, published_at,"
            "  fetched_at, is_utility, image_url, cluster_id)"
            " VALUES (:guid, :url, :title, :summary, :source_name, :sport, :lang,"
            "         :published_at, :fetched_at, :is_utility, :image_url, :cluster_id)",
            {**article, "cluster_id": cluster_id},
        )
    except sqlite3.IntegrityError:
        return None
    return int(cursor.lastrowid)


# ---------- link affiliate (M12) ----------

def list_links(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM affiliate_link ORDER BY sport, id"
    ).fetchall()


def add_link(
    conn: sqlite3.Connection, sport: str, url: str, label: str, now_iso: str
) -> int:
    cursor = conn.execute(
        "INSERT INTO affiliate_link (sport, url, label, created_at) VALUES (?, ?, ?, ?)",
        (sport, url, label, now_iso),
    )
    conn.commit()
    return int(cursor.lastrowid)


def next_link_for_sport(conn: sqlite3.Connection, sport: str) -> sqlite3.Row | None:
    """Link ít được dùng nhất của môn đó, để xoay vòng đều thay vì lặp mãi một link.

    Sắp theo use_count chứ không lấy modulo: link có thể bị thêm/xoá/tắt bất cứ lúc nào,
    modulo trên danh sách đổi độ dài sẽ nhảy lung tung.
    """
    return conn.execute(
        "SELECT * FROM affiliate_link WHERE sport = ? AND enabled = 1"
        " ORDER BY use_count ASC, id ASC LIMIT 1",
        (sport,),
    ).fetchone()


def mark_link_used(conn: sqlite3.Connection, link_id: int) -> None:
    conn.execute("UPDATE affiliate_link SET use_count = use_count + 1 WHERE id = ?", (link_id,))


def seed_links_from_config(conn: sqlite3.Connection, links_by_sport: dict, now_iso: str) -> int:
    """Nạp link từ file cấu hình vào DB, chỉ khi bảng còn trống.

    Từ lúc đó DB là nguồn sự thật — sửa link ở màn hình web, không sửa YAML nữa.
    """
    if conn.execute("SELECT 1 FROM affiliate_link LIMIT 1").fetchone():
        return 0
    added = 0
    for sport, urls in (links_by_sport or {}).items():
        for url in urls or []:
            add_link(conn, sport, url, "", now_iso)
            added += 1
    return added
