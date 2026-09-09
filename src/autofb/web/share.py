"""Chia sẻ bài lên nhóm Facebook — BÁN tự động, và không thể hơn thế.

Meta gỡ toàn bộ Groups API ngày 22/04/2024: permission `publish_to_groups` và các
endpoint đăng vào nhóm bị xoá khỏi MỌI phiên bản Graph API. Buffer, Hootsuite, kể cả
Meta Business Suite cũng chỉ còn đăng được lên Page. Không có đường vòng hợp lệ.

Đường vòng KHÔNG hợp lệ là giả lập trình duyệt trong phiên đăng nhập của người dùng.
Nó vi phạm điều khoản Facebook, và ở đây rủi ro cụ thể hơn thế: cả hệ thống chạy từ
đúng một IP nhà, cùng IP đang gọi Graph API bằng Page token thật — bị gắn cờ là mất
luôn Fanpage lẫn token, tức là mất phần đang chạy tốt. Nên module này không tự bấm
thay người dùng; nó chỉ làm việc bấm tay nhanh hơn và không sót nhóm.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import db

router = APIRouter()

# Bao nhiêu bài gần nhất cho chọn để chia sẻ. Bài quá cũ mang vào nhóm thì vô duyên,
# mà danh sách dài cũng không ai cuộn.
RECENT_POSTS = 8

CTA_KEY = "share_cta"
CTA_NOLINK_KEY = "share_cta_nolink"

# Câu chốt mặc định. Dán nguyên văn bài trên Page vào nhóm thì người đọc xong là đi,
# không có lý do gì để bấm theo dõi — câu này là chỗ duy nhất biến người đọc thành
# người theo dõi, nên nó phải sửa được mà không cần đụng vào code.
DEFAULT_CTA = ("Mình tổng hợp kết quả, lịch thi đấu và bảng xếp hạng mỗi tuần ở đây,"
               " ai cần thì ghé nhé: {link}")
# Nhóm cấm link thì câu trên bị xoá bài. Nhắc tên Page để người quan tâm tự tìm.
DEFAULT_CTA_NOLINK = ("Mình tổng hợp kết quả, lịch thi đấu và bảng xếp hạng mỗi tuần"
                      " trên trang {name}, ai cần thì tìm tên đó trên Facebook nhé.")


def _setting(conn, key: str, fallback: str) -> str:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return row["value"] if row and row["value"] else fallback


def share_text(message: str, cta: str, page_name: str, page_link: str) -> str:
    """Nội dung dán vào nhóm: nguyên bài trên Page + câu chốt kéo người theo dõi.

    Giữ nguyên bài chứ không rút gọn: trong nhóm, bài đọc trọn vẹn ngay tại chỗ thì
    người ta dừng lại đọc, còn một dòng tiêu đề kèm link thì đa số lướt qua — mà nhiều
    nhóm cũng dìm bài có link.
    """
    body = (message or "").strip()
    tail = cta.replace("{link}", page_link).replace("{name}", page_name).strip()
    return f"{body}\n\n{tail}" if tail else body


def list_groups(conn) -> list[dict]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM fb_group ORDER BY enabled DESC, name COLLATE NOCASE"
    )]


def shared_group_ids(conn, fb_post_id: str) -> set[int]:
    if not fb_post_id:
        return set()
    return {row["group_id"] for row in conn.execute(
        "SELECT group_id FROM group_share WHERE fb_post_id = ?", (fb_post_id,)
    )}


def share_counts(conn, fb_post_ids: list[str]) -> dict[str, int]:
    """Mỗi bài đã vào bao nhiêu nhóm — hiện ngay ở ô chọn bài để biết bài nào còn dở."""
    if not fb_post_ids:
        return {}
    marks = ",".join("?" * len(fb_post_ids))
    return {row["fb_post_id"]: row["n"] for row in conn.execute(
        f"SELECT fb_post_id, COUNT(*) n FROM group_share"
        f" WHERE fb_post_id IN ({marks}) GROUP BY fb_post_id", fb_post_ids
    )}


def build_context(conn, feed: list[dict], chosen_id: str,
                  page_name: str = "", page_link: str = "") -> dict:
    """Dữ liệu cho màn hình chia sẻ. `feed` là bài lấy từ Fanpage (fanpage_feed.py)."""
    posts = feed[:RECENT_POSTS]
    chosen = next((p for p in posts if p["id"] == chosen_id), posts[0] if posts else None)

    groups = list_groups(conn)
    done = shared_group_ids(conn, chosen["id"]) if chosen else set()
    for group in groups:
        group["shared"] = group["id"] in done

    cta = _setting(conn, CTA_KEY, DEFAULT_CTA)
    cta_nolink = _setting(conn, CTA_NOLINK_KEY, DEFAULT_CTA_NOLINK)
    message = chosen["message"] if chosen else ""

    return {
        "posts": posts,
        "counts_by_post": share_counts(conn, [p["id"] for p in posts]),
        "chosen": chosen,
        # Nhóm chưa chia sẻ lên trước: đó là việc còn phải làm, không phải việc đã xong.
        "groups": sorted(groups, key=lambda g: (g["shared"], not g["enabled"])),
        "done_count": sum(1 for g in groups if g["shared"] and g["enabled"]),
        "active_count": sum(1 for g in groups if g["enabled"]),
        "cta": cta,
        "cta_nolink": cta_nolink,
        # Dựng sẵn hai bản: nhóm cho phép link và nhóm cấm link. Bấm nút là có ngay,
        # không phải chờ gọi thêm gì.
        "text_link": share_text(message, cta, page_name, page_link),
        "text_nolink": share_text(message, cta_nolink, page_name, page_link),
    }


def unshared_count(conn, feed: list[dict]) -> int:
    """Bao nhiêu bài gần đây chưa vào nhóm nào — con số nhắc việc trên bảng điều khiển."""
    posts = feed[:RECENT_POSTS]
    counts = share_counts(conn, [p["id"] for p in posts])
    return sum(1 for p in posts if not counts.get(p["id"]))


@router.post("/share/groups/add")
def add_group(name: str = Form(...), url: str = Form(...), note: str = Form("")):
    name, url = name.strip(), url.strip()
    if name and url:
        with db.session() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO fb_group (name, url, note, created_at)"
                " VALUES (?, ?, ?, ?)",
                (name, url, note.strip(), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
    return RedirectResponse("/share", status_code=303)


@router.post("/share/cta")
def save_cta(cta: str = Form(""), cta_nolink: str = Form("")):
    now = datetime.now(timezone.utc).isoformat()
    with db.session() as conn:
        for key, value in ((CTA_KEY, cta), (CTA_NOLINK_KEY, cta_nolink)):
            conn.execute(
                "INSERT INTO setting (key, value, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                " updated_at = excluded.updated_at",
                (key, value.strip(), now),
            )
        conn.commit()
    return RedirectResponse("/share", status_code=303)


@router.post("/share/groups/{group_id}/nolink")
def toggle_nolink(group_id: int):
    with db.session() as conn:
        conn.execute("UPDATE fb_group SET no_link = 1 - no_link WHERE id = ?", (group_id,))
        conn.commit()
    return RedirectResponse("/share", status_code=303)


@router.post("/share/groups/{group_id}/toggle")
def toggle_group(group_id: int):
    """Tắt nhóm thay vì xoá — giữ lại lịch sử đã chia sẻ bài nào vào đó."""
    with db.session() as conn:
        conn.execute("UPDATE fb_group SET enabled = 1 - enabled WHERE id = ?", (group_id,))
        conn.commit()
    return RedirectResponse("/share", status_code=303)


@router.post("/share/groups/{group_id}/delete")
def delete_group(group_id: int):
    with db.session() as conn:
        conn.execute("DELETE FROM group_share WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM fb_group WHERE id = ?", (group_id,))
        conn.commit()
    return RedirectResponse("/share", status_code=303)


@router.post("/share/mark")
async def mark_shared(request: Request):
    """Đánh dấu / bỏ đánh dấu đã chia sẻ. Gọi bằng fetch nên trả JSON, không chuyển trang.

    Chuyển trang ở đây là hỏng thao tác: người dùng vừa bấm mở nhóm ở tab mới, tab cũ
    mà nhảy đi thì quay lại phải dò từ đầu xem đang ở bài nào.
    """
    body = await request.json()
    fb_post_id = str(body.get("fb_post_id") or "")
    group_id = int(body.get("group_id") or 0)
    if not fb_post_id or not group_id:
        return {"ok": False}

    with db.session() as conn:
        if body.get("undo"):
            conn.execute("DELETE FROM group_share WHERE fb_post_id = ? AND group_id = ?",
                         (fb_post_id, group_id))
            shared = False
        else:
            conn.execute(
                "INSERT OR REPLACE INTO group_share (fb_post_id, group_id, shared_at)"
                " VALUES (?, ?, ?)",
                (fb_post_id, group_id, datetime.now(timezone.utc).isoformat()),
            )
            shared = True
        conn.commit()
        done = len(shared_group_ids(conn, fb_post_id))

    return {"ok": True, "shared": shared, "done": done}
