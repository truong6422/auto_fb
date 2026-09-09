# Triển khai AutoFB lên box homelab

Chạy 24/7 trên TV box Tanix TX3 Mini-A (Armbian, aarch64, 1,8GB RAM, boot từ USB).

## Kiến trúc chạy

Bốn container, dùng chung **một ảnh** và **một file SQLite**:

| Container | Việc | Nhịp | Cần token FB |
|---|---|---|---|
| `autofb-web` | màn hình quản trị, cổng `127.0.0.1:3100` | — | không (chỉ để hiện trạng thái) |
| `autofb-crawler` | kéo RSS → dựng bài vào hàng chờ | tỉnh mỗi 10 phút, kéo theo nhịp ở trang Cài đặt | không |
| `autofb-publisher` | đăng bài lên Fanpage | 5 phút một lượt | có |
| `autofb-watchtower` | tự kéo ảnh mới từ GHCR | 30 phút | — |

Crawler và publisher **không gọi hàm của nhau**, chỉ gặp nhau qua bảng `post`. Một tờ báo
treo 15 giây không làm trễ giờ đăng; token Facebook chết không làm dừng việc kéo tin.

SQLite bật `journal_mode=WAL` và `busy_timeout=15000` — bắt buộc, vì ba tiến trình
cùng ghi một file.

## Vì sao ảnh build trên GitHub Actions

CPU Cortex-A53 của box build một ảnh Python mất hàng chục phút và làm treo AdGuard đang
chạy cùng máy. Actions build chéo sang `linux/arm64` bằng QEMU rồi đẩy lên GHCR; box chỉ
kéo về. Ảnh pin Python 3.12 (box đang 3.14) để chắc chắn có sẵn wheel Pillow cho aarch64 —
không có wheel thì pip build từ nguồn, trên A53 là hàng tiếng.

## Cài lần đầu trên box

```bash
ssh tvbox
mkdir -p /opt/autofb && cd /opt/autofb
# chép docker-compose.yml, config/sources.yaml và .env từ máy làm việc sang
docker compose up -d
```

`.env` phải có:

```
FB_PAGE_ID=...
FB_PAGE_ACCESS_TOKEN=...        # PAGE token, không phải USER token
AUTOFB_USER=admin
AUTOFB_PASSWORD=...             # bắt buộc, thiếu là mọi trang trả 503
```

## Mở ra internet

Thêm hostname vào tunnel `shop3d-box` đang chạy sẵn trên box
(`/etc/cloudflared/config.yml`), trỏ về `http://localhost:3100`, rồi:

```bash
cloudflared tunnel route dns <tunnel-id> autofb.truonglb.cloud
systemctl restart cloudflared      # KHÔNG dùng SIGHUP: cloudflared thoát hẳn
```

Màn hình quản trị có nút đăng lên Fanpage nên **luôn phải qua HTTP Basic**
(`web/auth.py`). Không đặt `AUTOFB_PASSWORD` thì app tự khoá bằng 503 — cố ý hỏng to
thay vì ghi một dòng cảnh báo rồi vẫn để trần.

## Ràng buộc của box — nhớ trước khi đổi gì

- **RAM 1,8GB hàn chết.** Ba container Python ≈ 210MB. Đừng thêm Postgres/Redis.
- **Ổ USB ghi 2,9 MB/s**, ghi 500MB một lần là treo cả box. Vì vậy: card render trong RAM
  không lưu file, log Docker giới hạn 5MB×3, `retention_days` mặc định 3.
- **Không build ảnh trên box.**

## Vận hành

```bash
docker compose logs -f publisher        # xem lượt đăng
docker compose restart crawler          # khởi động lại riêng crawler
docker compose exec web python cli.py stats
```

Đổi nhịp chạy (bao lâu kéo RSS, ngày mấy bài, hai bài cách nhau bao lâu) làm ở trang
**Cài đặt** trên web — lưu vào SQLite, cả ba tiến trình đọc lại ở lượt sau, không phải
khởi động lại gì.
