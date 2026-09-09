"""Điểm vào dòng lệnh cho AutoFB."""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from autofb import db  # noqa: E402
from autofb.config import load_config  # noqa: E402
from autofb.crawler.pipeline import run_crawl  # noqa: E402
from autofb.facebook import FacebookClient, PermanentError, TransientError  # noqa: E402
from autofb.post_pipeline import build_pending_posts  # noqa: E402
from autofb.autopilot import run_tick  # noqa: E402
from autofb.publisher import publish_approved, retry_failed_comments  # noqa: E402
from autofb.fb_setup import exchange_for_long_lived, inspect_token, upsert_env  # noqa: E402
from autofb.settings import ENV_PATH, load_facebook_settings, silence_token_leak  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="autofb")
    parser.add_argument(
        "command",
        choices=["crawl", "build", "stats", "serve", "check-token", "fb-info", "fb-longlive", "publish", "retry-comments",
         "tick", "cleanup", "crawl-loop", "publish-loop"],
    )
    parser.add_argument("--limit", type=int, default=1, help="số bài đăng mỗi lượt")
    parser.add_argument("--every", type=int, default=0,
                        help="crawl-loop/publish-loop: số phút giữa hai lượt "
                             "(mặc định: crawler 30, publisher 5)")
    parser.add_argument("--reload", action="store_true",
                        help="serve: tự nạp lại khi sửa code")
    parser.add_argument("--save", metavar="PAGE_ID",
                        help="fb-info: lưu Page ID + Page token của Page này vào .env")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )
    silence_token_leak()

    config = load_config()

    if args.command == "check-token":
        return check_token()

    if args.command == "fb-info":
        return fb_info(save=args.save)

    if args.command == "fb-longlive":
        return fb_longlive()

    # Hai lệnh dưới đây là điểm vào của hai container chạy nền. Chúng KHÔNG mở
    # kết nối DB ở đây: vòng lặp tự mở/đóng theo từng lượt, giữ một kết nối sống
    # nhiều ngày trên SQLite dùng chung là cách chắc chắn gặp "database is locked".
    if args.command == "crawl-loop":
        from autofb.worker import crawl_worker

        return crawl_worker(args.every or 30)

    if args.command == "publish-loop":
        from autofb.worker import publish_worker

        return publish_worker(args.every or 5)

    if args.command == "serve":
        import uvicorn

        # --reload: nạp lại khi sửa code. Không có nó thì server giữ bản cũ trong bộ nhớ,
        # sửa bug xong vẫn thấy lỗi cũ trên giao diện.
        uvicorn.run(
            "autofb.web.app:app", host="0.0.0.0", port=args.port,
            reload=args.reload, reload_dirs=[str(Path(__file__).parent / "src")],
        )
        return 0

    with db.session() as conn:
        if args.command == "crawl":
            report = run_crawl(config, conn)
            print("\n" + report.summary())
            if report.failed_sources:
                print("  nguồn lỗi: " + ", ".join(report.failed_sources))
        elif args.command == "build":
            report = build_pending_posts(config, conn)
            print(report.summary())
        elif args.command == "tick":
            client = None
            fb = load_facebook_settings()
            if fb.configured:
                client = FacebookClient(fb.page_id, fb.access_token, fb.api_version)
            report = run_tick(config, conn, client)
            print(report.summary())
            for note in report.notes:
                print("  " + note)
        elif args.command == "cleanup":
            from autofb.cleanup import run_cleanup

            print(run_cleanup(conn, config.retention_days).summary())
        elif args.command in ("publish", "retry-comments"):
            client = _facebook_client()
            if client is None:
                return 1
            report = (
                publish_approved(client, conn, args.limit)
                if args.command == "publish"
                else retry_failed_comments(client, conn)
            )
            print(report.summary())
            for err in report.errors:
                print("  " + err)
        else:
            print_stats(conn)
    return 0


def _facebook_client() -> FacebookClient | None:
    fb = load_facebook_settings()
    if not fb.configured:
        print("Chưa cấu hình Facebook. Tạo file .env từ .env.example rồi điền")
        print("FB_PAGE_ID và FB_PAGE_ACCESS_TOKEN.")
        return None
    return FacebookClient(fb.page_id, fb.access_token, fb.api_version)


def _mask(token: str) -> str:
    return f"{token[:6]}…{token[-4:]}" if len(token) > 12 else "(quá ngắn)"


def fb_info(save: str | None = None) -> int:
    """Dò xem token đang có là loại gì và lấy nốt Page ID / Page token."""
    fb = load_facebook_settings()
    if not fb.access_token:
        print("Chưa có FB_PAGE_ACCESS_TOKEN trong .env")
        return 1

    try:
        info = inspect_token(fb.access_token, fb.api_version)
    except (PermanentError, TransientError) as exc:
        print(f"Không dùng được token: {exc}")
        return 1

    if info.kind == "page":
        print("Loại token : PAGE TOKEN (đúng loại cần dùng)")
        print(f"Page       : {info.name} (id {info.id})")
        if save or not fb.page_id:
            upsert_env(ENV_PATH, {"FB_PAGE_ID": info.id})
            print(f"\nĐã ghi FB_PAGE_ID={info.id} vào .env")
        return 0

    print("Loại token : USER TOKEN — KHÔNG đăng bài lên Page được.")
    print(f"Tài khoản  : {info.name} (id {info.id})")
    if not info.pages:
        print("\nTài khoản này không quản trị Fanpage nào.")
        return 1

    print("\nCác Page quản trị được:")
    for page in info.pages:
        print(f"  - {page['name']}  (id {page['id']})  token {_mask(page.get('access_token',''))}")

    target = None
    if save:
        target = next((p for p in info.pages if str(p["id"]) == str(save)), None)
        if target is None:
            print(f"\nKhông thấy Page id {save} trong danh sách trên.")
            return 1
    elif len(info.pages) == 1:
        target = info.pages[0]

    if target is None:
        print("\nChạy lại với: cli.py fb-info --save <page_id>")
        return 0

    upsert_env(ENV_PATH, {
        "FB_PAGE_ID": str(target["id"]),
        "FB_PAGE_ACCESS_TOKEN": target["access_token"],
    })
    print(f"\nĐã ghi Page ID + PAGE TOKEN của '{target['name']}' vào .env")
    print("Chạy: cli.py check-token để xác nhận.")
    return 0


def fb_longlive() -> int:
    """Đổi token ngắn hạn sang token dài hạn (~60 ngày)."""
    import os

    fb = load_facebook_settings()
    app_id = os.environ.get("FB_APP_ID", "").strip()
    app_secret = os.environ.get("FB_APP_SECRET", "").strip()

    if not (app_id and app_secret):
        print("Cần FB_APP_ID và FB_APP_SECRET trong .env.")
        print("Lấy ở developers.facebook.com > App của bạn > Settings > Basic.")
        return 1

    try:
        new_token = exchange_for_long_lived(fb.access_token, app_id, app_secret, fb.api_version)
    except (PermanentError, TransientError) as exc:
        print(f"Đổi token thất bại: {exc}")
        return 1

    upsert_env(ENV_PATH, {"FB_PAGE_ACCESS_TOKEN": new_token})
    print(f"Đã đổi sang token dài hạn: {_mask(new_token)} (đã ghi vào .env)")
    print("Nếu token vừa đổi là USER token, chạy tiếp: cli.py fb-info --save <page_id>")
    return 0


def check_token() -> int:
    """Kiểm tra token — chỉ đọc, không đăng gì lên Page."""
    fb = load_facebook_settings()
    print(f"Page ID     : {fb.page_id or '(chưa có)'}")
    print(f"Token       : {fb.masked_token}")
    print(f"API version : {fb.api_version}")

    client = _facebook_client()
    if client is None:
        return 1

    try:
        page = client.verify()
    except PermanentError as exc:
        print(f"\nTOKEN KHÔNG DÙNG ĐƯỢC: {exc}")
        print("Thường do: token hết hạn, dùng User Token thay vì Page Token,")
        print("hoặc thiếu quyền pages_manage_posts / pages_manage_engagement.")
        return 1
    except TransientError as exc:
        print(f"\nKhông kết nối được tới Facebook: {exc}")
        return 1

    print(f"\nOK — token hợp lệ, trỏ tới Page: {page.name} (id {page.id})")
    return 0


def print_stats(conn) -> None:
    total = conn.execute("SELECT COUNT(*) FROM raw_article").fetchone()[0]
    clusters = conn.execute("SELECT COUNT(*) FROM topic_cluster").fetchone()[0]
    print(f"raw_article: {total} | topic_cluster: {clusters}")

    print("\nBài theo môn:")
    for row in conn.execute(
        "SELECT sport, COUNT(*) n FROM raw_article GROUP BY sport ORDER BY n DESC"
    ):
        print(f"  {row['n']:4d}  {row['sport']}")

    print("\nTin nhiều nguồn cùng đưa (top 10):")
    rows = conn.execute(
        "SELECT representative, article_count, sport FROM topic_cluster"
        " WHERE article_count > 1 ORDER BY article_count DESC LIMIT 10"
    ).fetchall()
    for row in rows:
        print(f"  [{row['article_count']}] ({row['sport']}) {row['representative'][:80]}")
    if not rows:
        print("  (chưa có — cần chạy crawl vài lần)")


if __name__ == "__main__":
    raise SystemExit(main())
