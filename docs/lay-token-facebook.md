# Lấy Page token không hết hạn

Token hết hạn là lý do phổ biến nhất khiến Page im lặng cả ngày. Facebook có ba loại,
và chỉ loại thứ ba mới dùng được cho bot chạy 24/7:

| Loại | Sống được | Lấy từ đâu |
|---|---|---|
| User token ngắn hạn | 1–2 giờ | Graph API Explorer, nút "Generate Access Token" |
| User token dài hạn | ~60 ngày | đổi từ token ngắn hạn, cần App ID + App Secret |
| **Page token sinh từ user token dài hạn** | **không có hạn** | `/me/accounts` gọi bằng user token dài hạn |

**Thứ tự bắt buộc:** đổi user token sang dài hạn **trước**, rồi mới rút Page token ra.
Rút Page token từ user token ngắn hạn thì Page token cũng chết theo trong vài giờ —
đây là cái bẫy dễ mắc nhất, vì hai cách làm cho ra token trông y hệt nhau.

## Các bước

### 1. App ID và App Secret

`developers.facebook.com/apps/<app-id>/settings/basic/` — ô **Mã ứng dụng** và
**Khóa bí mật của ứng dụng** (bấm *Hiển thị*, nhập lại mật khẩu Facebook).

```
FB_APP_ID=...
FB_APP_SECRET=...
```

App để ở chế độ **Development** là đủ khi bạn là admin của cả App lẫn Page.
Không cần qua App Review.

### 2. User token ngắn hạn

`developers.facebook.com/tools/explorer`

- Ô **Meta App**: chọn đúng App của bạn. Mặc định nó chọn "Graph API Explorer" —
  **phải đổi**, nếu không bước 3 báo lỗi App Secret không khớp.
- Ô **User or Page**: để **User Token**
- **Permissions**: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`,
  `pages_manage_engagement`

  Thiếu `pages_manage_posts` là không đăng bài được. Thiếu `pages_manage_engagement`
  thì đăng được bài nhưng **không đăng được comment** — mất chỗ đặt link affiliate.
- **Generate Access Token** → chọn Page trong cửa sổ quyền → Continue

Dán token vào `FB_PAGE_ACCESS_TOKEN` trong `.env` (đúng, lúc này biến đó đang chứa
user token — hai lệnh dưới sẽ thay bằng Page token thật).

### 3. Đổi và rút

```bash
./.venv/bin/python cli.py fb-longlive              # user token -> dài hạn 60 ngày
./.venv/bin/python cli.py fb-info --save <page_id> # rút Page token vĩnh viễn
./.venv/bin/python cli.py check-token              # xác nhận
```

### 4. Kiểm chứng token thật sự vô hạn

`check-token` chỉ nói token dùng được, không nói nó sống được bao lâu. Kiểm bằng
`debug_token`:

```bash
./.venv/bin/python - <<'PY'
import sys, datetime, httpx; sys.path.insert(0, "src")
from autofb.settings import load_facebook_settings, silence_token_leak
silence_token_leak()
fb = load_facebook_settings()
d = httpx.get(f"https://graph.facebook.com/{fb.api_version}/debug_token",
              params={"input_token": fb.access_token,
                      "access_token": fb.access_token}, timeout=20).json()["data"]
print("loại:", d["type"], "| hợp lệ:", d["is_valid"])
print("hết hạn:", datetime.datetime.fromtimestamp(d["expires_at"]) if d.get("expires_at")
      else "KHÔNG CÓ HẠN")
PY
```

Phải ra `loại: PAGE` và `hết hạn: KHÔNG CÓ HẠN`. Ra `USER` là quên bước rút Page token;
ra một mốc thời gian là đã làm sai thứ tự ở bước 3.

### 5. Đưa lên box

```bash
scp .env tvbox:/opt/autofb/.env
ssh tvbox 'chmod 600 /opt/autofb/.env && cd /opt/autofb && docker rm -f autofb-publisher
           && docker compose up -d --no-deps publisher'
```

Phải tạo lại container: biến môi trường nạp từ `env_file` lúc tạo, khởi động lại không
đọc lại file.

## Khi nào token vẫn chết

Page token không có hạn, nhưng vẫn mất hiệu lực nếu: đổi mật khẩu Facebook, gỡ App khỏi
tài khoản, Facebook khoá vì lý do bảo mật, hoặc bạn thôi làm admin của Page.
Màn hình quản trị hiện dải đỏ báo `Token hỏng: [190] ...` khi việc đó xảy ra, và
publisher **giữ nguyên hàng chờ** thay vì đánh dấu từng bài hỏng.
