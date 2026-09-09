# Lấy token Threads

Threads là kênh **tự động hợp lệ duy nhất** còn lại cùng hệ Meta. Nhóm Facebook thì
Meta gỡ API từ 22/04/2024, không có đường vòng.

Token Threads **không liên quan gì** tới Page token Facebook — app khác, tên miền khác
(`graph.threads.net`), quyền khác. Có Page token rồi vẫn phải làm lại từ đầu ở đây.

## Khác biệt quan trọng nhất so với Facebook

| | Page token Facebook | Token Threads |
|---|---|---|
| Sống được | **không có hạn** | **60 ngày** |
| Quá hạn | — | **hỏng vĩnh viễn**, phải xin lại bằng tay |
| Gia hạn | không cần | được, nhưng phải làm **trước** khi hết hạn |

AutoFB tự gia hạn 7 ngày một lần (`threads_token.py`) nên bình thường không phải đụng
tới. Nhưng nếu tắt máy hơn 60 ngày thì token chết hẳn và phải làm lại toàn bộ hướng
dẫn này — đó là lý do phần gia hạn được viết tự động ngay từ đầu.

## Các bước

### 1. Thêm Threads vào app trên Meta

`developers.facebook.com` → app đang dùng cho Fanpage → **Thêm trường hợp sử dụng** →
chọn **Threads API**.

Trong phần Threads, bật hai quyền:

- `threads_basic` — bắt buộc cho mọi endpoint
- `threads_content_publish` — để đăng bài

Lấy **Threads App ID** và **Threads App Secret** ở mục cài đặt của trường hợp sử dụng
này. Chúng **khác** App ID/Secret của Facebook.

### 2. Thêm địa chỉ chuyển hướng

Cùng màn hình đó, mục **Redirect Callback URLs**, thêm:

```
https://autofb.truonglb.cloud/threads/callback
```

Địa chỉ này không cần chạy được — chỉ cần Meta chấp nhận và bạn đọc được phần `code=`
trên thanh địa chỉ sau khi bấm đồng ý.

### 3. Lấy mã uỷ quyền

Mở địa chỉ sau trong trình duyệt (thay `<APP_ID>`):

```
https://threads.net/oauth/authorize
  ?client_id=<APP_ID>
  &redirect_uri=https://autofb.truonglb.cloud/threads/callback
  &scope=threads_basic,threads_content_publish
  &response_type=code
```

Đăng nhập, bấm đồng ý. Trình duyệt nhảy sang địa chỉ chuyển hướng kèm `?code=AQB...`.
**Chép phần sau `code=`**, bỏ dấu `#_` ở cuối nếu có.

Mã này sống rất ngắn — làm luôn bước 4.

### 4. Đổi mã lấy token

```bash
curl -X POST https://graph.threads.net/oauth/access_token \
  -d client_id=<APP_ID> \
  -d client_secret=<APP_SECRET> \
  -d grant_type=authorization_code \
  -d redirect_uri=https://autofb.truonglb.cloud/threads/callback \
  -d code=<CODE>
```

Trả về `{"access_token": "TH...", "user_id": 1784...}`. Token này **sống 1 giờ** — chưa
dùng được, phải đổi tiếp.

### 5. Đổi sang token 60 ngày

```bash
curl "https://graph.threads.net/access_token\
?grant_type=th_exchange_token\
&client_secret=<APP_SECRET>\
&access_token=<TOKEN_1_GIO>"
```

Trả về token mới kèm `expires_in` khoảng 5.184.000 giây (60 ngày). **Đây mới là token
cần dùng.** Bỏ qua bước này là hôm sau Threads im lặng.

### 6. Điền vào .env

```
THREADS_USER_ID=1784...
THREADS_ACCESS_TOKEN=TH...
```

Trên box:

```bash
ssh tvbox
nano /opt/autofb/.env          # dán hai dòng trên
docker restart autofb-publisher
```

Không cần tạo lại container — `.env` được gắn vào và đọc lại ở mỗi lượt chạy.

### 7. Kiểm chứng

Mở `https://autofb.truonglb.cloud` — ô **Threads** ở hàng thông tin trên cùng phải
chuyển từ *chưa nối* sang *đang đăng kèm*. Bài tiếp theo lên Fanpage sẽ tự lên Threads.

Xem log:

```bash
docker logs autofb-publisher | grep -i threads
```

## Bài trên Threads trông thế nào

- **Ảnh**: mượn lại đúng tấm Facebook vừa nhận (`full_picture`). Card không lưu ra đĩa
  nên không có file nào để đưa cho Threads tải — mượn bản Facebook vừa tránh phải mở
  một đường công khai vào máy, vừa chắc chắn hai nơi hiện cùng một ảnh.
- **Chữ**: giới hạn 500 ký tự, hệ thống cắt ở 460 cho chắc (emoji tính theo byte).
  Cắt ở cuối dòng, không cắt giữa từ.
- **Ảnh hỏng**: vẫn đăng bài chữ kèm thẻ xem trước dẫn về bài trên Fanpage.

## Khi nào Threads im lặng

| Dấu hiệu | Nguyên nhân | Cách sửa |
|---|---|---|
| Ô Threads ghi *chưa nối* | thiếu `THREADS_USER_ID` hoặc `THREADS_ACCESS_TOKEN` | điền vào `.env` |
| Log báo lỗi quyền | thiếu `threads_content_publish` | bật quyền rồi lấy lại token |
| Bài đăng lỗi sau 60 ngày tắt máy | token hết hạn, không gia hạn được nữa | làm lại từ bước 3 |
| `threads_status = failed` trong DB | lỗi lẻ một bài | xem log, bài Facebook **không** bị ảnh hưởng |
