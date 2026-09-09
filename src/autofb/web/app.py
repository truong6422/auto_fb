"""M6 — màn hình quản trị. Toàn bộ giao diện nằm ở đây.

Đã khoá bằng HTTP Basic (web/auth.py) vì màn hình này có nút đăng lên Fanpage và
đang chạy trên một subdomain công khai.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .. import db
from ..card_renderer import FontMissingError, render_card, title_of
from ..config import load_config
from ..facebook import AuthError, FacebookClient, PermanentError, TransientError
from ..autopilot import run_tick
from ..post_pipeline import build_pending_posts
from ..runtime_settings import (
    SPECS, InvalidSetting, current_values, effective_config, load_overrides,
    reset as reset_settings, save_overrides,
)
from ..scheduler import VN_TIMEZONE, decide, now_vn, posted_today
from ..publisher import publish_approved
from ..settings import load_env, load_facebook_settings, silence_token_leak
from .auth import BasicAuthMiddleware
from .state import SystemState

# Nạp .env NGAY khi import: middleware xác thực đọc AUTOFB_PASSWORD từ os.environ,
# nếu để tới lúc có request đầu tiên mới nạp thì trang bị khoá nhầm bằng 503.
load_env()
silence_token_leak()

TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="AutoFB", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(BasicAuthMiddleware)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
state = SystemState()


@app.get("/healthz")
def healthz():
    """Docker healthcheck gọi vào đây. Không qua đăng nhập, không chạm DB."""
    return {"ok": True}

SPORT_LABELS = {
    "football": "Bóng đá", "tennis": "Tennis", "pickleball": "Pickleball",
    "badminton": "Cầu lông", "running": "Chạy bộ", "cycling": "Xe đạp",
    "gym": "Gym", "other": "Khác",
}


def _humanize_age(published_at: str | None) -> str:
    """Tin thể thao mất giá rất nhanh — người duyệt cần thấy ngay bài cũ bao lâu rồi."""
    if not published_at:
        return "không rõ"
    try:
        published = datetime.fromisoformat(published_at)
    except ValueError:
        return "không rõ"
    minutes = int((datetime.now(timezone.utc) - published).total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 0)} phút trước"
    if minutes < 1440:
        return f"{minutes // 60} giờ trước"
    return f"{minutes // 1440} ngày trước"


def _format_schedule(scheduled_at: str | None) -> str:
    """Giờ hẹn hiển thị theo giờ Việt Nam, kèm trạng thái đã tới hạn hay chưa."""
    if not scheduled_at:
        return "chưa hẹn giờ"
    when = datetime.fromisoformat(scheduled_at).astimezone(VN_TIMEZONE)
    label = when.strftime("%H:%M %d/%m")
    if when <= now_vn():
        return f"{label} · đã tới hạn"
    return label


def _sources_of(conn, cluster_id: int) -> list[dict]:
    """Link bài gốc để người duyệt kiểm nguồn trước khi bấm đăng.

    Bỏ trùng theo tên báo: một tờ có thể đăng hai bài trong cùng một nhóm tin,
    hiện ra thành 'Tuổi Trẻ · Tuổi Trẻ' thì vô nghĩa với người đọc.
    """
    rows = conn.execute(
        "SELECT source_name, url, published_at FROM raw_article"
        " WHERE cluster_id = ? AND is_utility = 0 ORDER BY published_at ASC",
        (cluster_id,),
    ).fetchall()

    seen: set[str] = set()
    sources = []
    for row in rows:
        if row["source_name"] in seen:
            continue
        seen.add(row["source_name"])
        sources.append(dict(row))
    return sources


def _posts(conn, statuses: tuple[str, ...]) -> list[dict]:
    placeholders = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"SELECT * FROM post WHERE status IN ({placeholders}) ORDER BY id DESC LIMIT 100",
        statuses,
    ).fetchall()

    posts = []
    for row in rows:
        post = dict(row)
        post["sources"] = _sources_of(conn, post["cluster_id"])
        newest = max((s["published_at"] for s in post["sources"] if s["published_at"]),
                     default=None)
        post["age"] = _humanize_age(newest)
        post["char_count"] = len(post["content"])
        posts.append(post)
    return posts


def _counts(conn) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) n FROM post GROUP BY status").fetchall()
    counts = {row["status"]: row["n"] for row in rows}
    counts["articles"] = conn.execute("SELECT COUNT(*) FROM raw_article").fetchone()[0]
    counts["clusters"] = conn.execute("SELECT COUNT(*) FROM topic_cluster").fetchone()[0]
    return counts


def _facebook_status() -> dict:
    """Trạng thái kết nối Fanpage, hiện ở đầu màn hình.

    Chỉ trả về tên Page và token đã che — KHÔNG bao giờ đưa token thật ra HTML.
    """
    fb = load_facebook_settings()
    if not fb.configured:
        return {"ok": False, "text": "Chưa kết nối Fanpage — điền token vào file .env"}

    try:
        page = FacebookClient(fb.page_id, fb.access_token, fb.api_version).verify()
    except PermanentError as exc:
        return {"ok": False, "text": f"Token hỏng: {exc}"}
    except TransientError:
        return {"ok": False, "text": "Không kết nối được tới Facebook"}
    return {"ok": True, "text": f"{page.name} · token {fb.masked_token}"}


@app.get("/")
def index(request: Request, tab: str = "queue"):
    statuses = {
        "queue": ("approved",),
        "posted": ("posted",),
        "blocked": ("blocked", "failed"),
    }.get(tab, ("approved",))

    with db.session() as conn:
        config = effective_config(conn)
        plan = decide(config, conn)
        sports = conn.execute(
            "SELECT sport, COUNT(*) n FROM post WHERE status='approved' GROUP BY sport"
            " ORDER BY n DESC"
        ).fetchall()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "posts": _posts(conn, statuses),
                "counts": _counts(conn),
                "tab": tab,
                "labels": SPORT_LABELS,
                "paused": state.paused,
                "page": "posts",
                "fb": _facebook_status(),
                "plan": plan,
                "schedule": config.schedule,
                "queue_by_sport": [dict(r) for r in sports],
                "now": now_vn().strftime("%H:%M"),
                "progress": round(plan.posted_today / plan.quota * 100) if plan.quota else 0,
            },
        )


@app.get("/posts/{post_id}/card.png")
def post_card(post_id: int):
    """Xem trước đúng tấm card sẽ đăng lên Facebook.

    Render lại tại chỗ thay vì lưu file: card chỉ phụ thuộc nội dung + id bài, vẽ mất
    vài chục mili giây, mà box chạy trên USB ghi rất chậm nên tránh sinh file rác.
    """
    with db.session() as conn:
        row = conn.execute(
            "SELECT id, content, image_credit FROM post WHERE id = ?", (post_id,)
        ).fetchone()
    if row is None:
        return Response(status_code=404)

    try:
        image = render_card(
            title_of(row["content"]), load_config().card,
            seed=row["id"], source_name=row["image_credit"],
        )
    except (ValueError, FontMissingError) as exc:
        return Response(f"Không vẽ được card: {exc}", status_code=500, media_type="text/plain")

    # no-store: sửa nội dung bài xong bấm F5 phải thấy card mới, không thấy bản cũ.
    return Response(image, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.post("/tick")
def tick_now():
    """Chạy ngay một lượt tự động, thay vì đợi cron."""
    fb = load_facebook_settings()
    client = (
        FacebookClient(fb.page_id, fb.access_token, fb.api_version) if fb.configured else None
    )
    with db.session() as conn:
        run_tick(effective_config(conn), conn, client)
    return RedirectResponse("/", status_code=303)


@app.post("/posts/{post_id}/update")
def update_post(post_id: int, content: str = Form(...), affiliate_link: str = Form("")):
    with db.session() as conn:
        conn.execute(
            "UPDATE post SET content = ?, affiliate_link = ? WHERE id = ?",
            (content.strip(), affiliate_link.strip() or None, post_id),
        )
        conn.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/posts/{post_id}/approve")
def approve_post(post_id: int):
    with db.session() as conn:
        conn.execute("UPDATE post SET status = 'approved' WHERE id = ?", (post_id,))
        conn.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/posts/{post_id}/delete")
def delete_post(post_id: int):
    """Xoá bài. Với bản tin tự động, đánh dấu chủ đề đã xử lý để lượt sau khỏi dựng lại."""
    with db.session() as conn:
        row = conn.execute("SELECT cluster_id, origin FROM post WHERE id = ?",
                           (post_id,)).fetchone()
        origin = row["origin"] if row else "auto"
        if row and row["cluster_id"]:
            conn.execute("UPDATE topic_cluster SET posted = 1 WHERE id = ?", (row["cluster_id"],))
        conn.execute("DELETE FROM post WHERE id = ?", (post_id,))
        conn.commit()
    return RedirectResponse("/compose" if origin == "manual" else "/", status_code=303)


@app.post("/build")
def build_now():
    """Dựng bài từ tin đã crawl (M3 → M4 → M5)."""
    with db.session() as conn:
        build_pending_posts(effective_config(conn), conn)
    return RedirectResponse("/", status_code=303)


@app.post("/approve-all")
def approve_all():
    """Duyệt hết bài đang chờ. Duyệt từng bài là 5 lần tải lại trang cho một lượt làm việc."""
    with db.session() as conn:
        conn.execute("UPDATE post SET status = 'approved' WHERE status = 'pending'")
        conn.commit()
    return RedirectResponse("/?tab=approved", status_code=303)


@app.post("/posts/{post_id}/publish")
def publish_post_now(post_id: int):
    """Đăng ngay một bài. Người bấm nút mới đăng — hệ thống không tự đăng ở MVP."""
    fb = load_facebook_settings()
    if not fb.configured or state.paused:
        return RedirectResponse("/?tab=approved", status_code=303)

    client = FacebookClient(fb.page_id, fb.access_token, fb.api_version)
    with db.session() as conn:
        conn.execute("UPDATE post SET status = 'approved' WHERE id = ?", (post_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM post WHERE id = ?", (post_id,)).fetchone()
        if row:
            from ..publisher import PublishReport, publish_one

            try:
                publish_one(client, conn, row, PublishReport(), load_config().card)
            except AuthError:
                # Token hỏng: publish_one đã ghi lý do vào post.note và giữ nguyên
                # trạng thái 'approved'. Đưa người dùng về hàng chờ để thấy ghi chú đó.
                conn.commit()
                return RedirectResponse("/?tab=queue", status_code=303)
            conn.commit()
    return RedirectResponse("/?tab=posted", status_code=303)


@app.post("/publish-approved")
def publish_approved_now(limit: int = 1):
    fb = load_facebook_settings()
    if not fb.configured or state.paused:
        return RedirectResponse("/?tab=approved", status_code=303)

    client = FacebookClient(fb.page_id, fb.access_token, fb.api_version)
    with db.session() as conn:
        publish_approved(client, conn, limit, load_config().card)
    return RedirectResponse("/?tab=posted", status_code=303)


@app.get("/compose")
def compose_page(request: Request):
    """Bài tự soạn: review, giới thiệu sản phẩm affiliate — người dùng viết và hẹn giờ."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM post WHERE origin = 'manual' ORDER BY"
            " CASE status WHEN 'approved' THEN 0 ELSE 1 END, scheduled_at ASC, id DESC"
        ).fetchall()
        posts = []
        for row in rows:
            post = dict(row)
            post["when"] = _format_schedule(post.get("scheduled_at"))
            posts.append(post)
        counts = _counts(conn)

    return templates.TemplateResponse(
        request=request,
        name="compose.html",
        context={"posts": posts, "counts": counts, "labels": SPORT_LABELS,
                 "paused": state.paused, "page": "compose",
                 "default_when": (now_vn() + timedelta(days=1)).strftime("%Y-%m-%dT09:00")},
    )


@app.post("/compose/add")
def compose_add(content: str = Form(...), sport: str = Form("other"),
                image_url: str = Form(""), affiliate_link: str = Form(""),
                scheduled_at: str = Form("")):
    """Lưu bài tự soạn kèm giờ hẹn. Giờ nhập theo giờ Việt Nam, lưu theo UTC."""
    content = content.strip()
    if not content:
        return RedirectResponse("/compose", status_code=303)

    when = None
    if scheduled_at:
        local = datetime.fromisoformat(scheduled_at).replace(tzinfo=VN_TIMEZONE)
        when = local.astimezone(timezone.utc).isoformat()

    with db.session() as conn:
        conn.execute(
            "INSERT INTO post (cluster_id, sport, content, status, origin, scheduled_at,"
            " image_url, affiliate_link, created_at)"
            " VALUES (NULL, ?, ?, 'approved', 'manual', ?, ?, ?, ?)",
            (sport, content, when, image_url.strip() or None,
             affiliate_link.strip() or None, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    return RedirectResponse("/compose", status_code=303)


@app.get("/links")
def links_page(request: Request):
    config = load_config()
    with db.session() as conn:
        db.seed_links_from_config(
            conn, config.affiliate_links, datetime.now(timezone.utc).isoformat()
        )
        conn.commit()
        rows = [dict(row) for row in db.list_links(conn)]
        counts = _counts(conn)

    grouped: dict[str, list[dict]] = {sport: [] for sport in SPORT_LABELS}
    for row in rows:
        grouped.setdefault(row["sport"], []).append(row)

    return templates.TemplateResponse(
        request=request,
        name="links.html",
        context={
            "grouped": grouped, "labels": SPORT_LABELS,
            "counts": counts, "paused": state.paused, "page": "links",
            "total": len(rows),
            "active": sum(1 for r in rows if r["enabled"]),
        },
    )


@app.post("/links/add")
def add_link(sport: str = Form(...), url: str = Form(...), label: str = Form("")):
    url = url.strip()
    if url:
        with db.session() as conn:
            db.add_link(conn, sport, url, label.strip(), datetime.now(timezone.utc).isoformat())
    return RedirectResponse("/links", status_code=303)


@app.post("/links/{link_id}/toggle")
def toggle_link(link_id: int):
    """Tắt link thay vì xoá: giữ được số lần đã dùng, bật lại lúc nào cũng được."""
    with db.session() as conn:
        conn.execute(
            "UPDATE affiliate_link SET enabled = 1 - enabled WHERE id = ?", (link_id,)
        )
        conn.commit()
    return RedirectResponse("/links", status_code=303)


@app.post("/links/{link_id}/delete")
def delete_link(link_id: int):
    with db.session() as conn:
        conn.execute("DELETE FROM affiliate_link WHERE id = ?", (link_id,))
        conn.commit()
    return RedirectResponse("/links", status_code=303)


@app.post("/toggle-pause")
def toggle_pause():
    state.paused = not state.paused
    return RedirectResponse("/", status_code=303)


@app.get("/settings")
def settings_page(request: Request, error: str = "", saved: int = 0):
    """Chỉnh nhịp chạy: bao lâu kéo tin, ngày mấy bài, hai bài cách nhau bao lâu."""
    with db.session() as conn:
        config = effective_config(conn)
        overridden = set(load_overrides(conn))
        values = current_values(config)
        plan = decide(config, conn)
        counts = _counts(conn)

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "specs": SPECS, "values": values, "overridden": overridden,
            "error": error, "saved": bool(saved), "plan": plan, "counts": counts,
            "paused": state.paused, "page": "settings",
            # Số bài mỗi ngày chia cho số giờ hoạt động = nhịp đăng thực tế người
            # đọc cảm nhận được. Đây là con số dễ hiểu hơn mọi thông số phía trên.
            "gap_estimate": round(
                (config.schedule.end_hour - config.schedule.start_hour) * 60
                / max(config.post.daily_quota, 1)
            ),
        },
    )


@app.post("/settings")
async def settings_save(request: Request):
    """Lưu thông số. Sai một ô là không ghi ô nào — xem runtime_settings.save_overrides."""
    form = await request.form()
    raw = {key: str(value) for key, value in form.items()}

    with db.session() as conn:
        try:
            save_overrides(conn, raw, datetime.now(timezone.utc).isoformat())
        except InvalidSetting as exc:
            return RedirectResponse(f"/settings?error={exc}", status_code=303)

    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/reset")
def settings_reset():
    """Bỏ hết phần đã sửa, quay về giá trị mặc định trong config/sources.yaml."""
    with db.session() as conn:
        reset_settings(conn)
    return RedirectResponse("/settings?saved=1", status_code=303)
