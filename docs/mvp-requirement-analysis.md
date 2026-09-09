# Phân tích yêu cầu & Đề xuất module MVP — Fanpage thể thao tự động

> Trạng thái: bản phân tích (chốt phạm vi, chưa code).
> Cập nhật: 2026-09-07 (bản 4 — bỏ LLM khỏi MVP, chỉ tối ưu crawl + đăng bài)

---

## 0. MVP là gì

Một câu: **crawl tin thể thao → đăng lên Fanpage → gắn link affiliate theo môn vào comment.**

**Không có LLM viết bài ở MVP.** Bài đăng được dựng từ dữ liệu RSS bằng template, có trích dẫn
ngắn và dẫn nguồn rõ ràng. Việc viết lại bằng LLM là Phase 2 — và M4 được thiết kế sẵn để cắm vào
mà không phải sửa gì xung quanh (mục 3.4).

Không thống kê, không đo click, không tối ưu, không tự học.

---

## 0.1. Phạm vi đã chốt

| Hạng mục | Chốt |
|---|---|
| Stack | **Python** |
| Meta / Fanpage | Chưa có Page → tạo mới. Không cần App Review |
| Môn thể thao | 8 môn (thực tế MVP co lại — xem mục 1.5) |
| **Viết bài** | **Không dùng LLM ở MVP.** Template từ dữ liệu RSS |
| Dạng bài | **Text thuần**, không ảnh, không link trong bài |
| Affiliate | Link **cấu hình theo môn** — bài môn nào gắn link môn đó, đặt ở **comment** |
| Đo lường | Không có ở MVP |
| Hạ tầng | Mini server 2GB RAM, subdomain của `truonglb.cloud` qua Cloudflare Tunnel |

---

## 1. Ràng buộc thực tế

### 1.1. Facebook Page API — không cần App Review

- Đăng bài cần `pages_manage_posts`; comment dưới tên Page cần `pages_manage_engagement`.
- Ở chế độ công khai phải qua App Review + Business Verification (nhiều tuần, cần pháp nhân).
- **Với dự án này (1 Page tự quản trị, tự dùng): không cần.** App ở **Development Mode** cấp đủ
  quyền trên Page mà tài khoản admin/developer của app quản trị.
- Page Access Token sống ngắn → đổi sang **long-lived token** (~60 ngày), cần gia hạn + cảnh báo
  trước hạn. Token chết giữa đêm mà không ai biết = hệ thống chết âm thầm.

> Chặng 0 mất vài giờ: tạo Page → tạo Meta App → lấy long-lived token.

### 1.2. Link ở comment thay vì trong bài

Bài có link dẫn ra ngoài thường bị phân phối kém hơn bài không có link. Đặt link affiliate ở comment
đầu tiên giữ được reach cho bài mà link vẫn tới được người đọc.

Kỹ thuật rất rẻ: đăng bài xong Graph API trả `post_id` → dùng luôn `post_id` gọi lần hai tạo comment.
Hai lần gọi liên tiếp.

Chỗ dễ hỏng: **bài lên thành công nhưng comment lỗi** → bài đã public mà không có link.
→ Trạng thái bài và trạng thái comment phải **tách riêng**, retry riêng phần comment, không đăng lại bài.

### 1.3. Bỏ LLM — hệ quả phải chấp nhận

Đây là thay đổi lớn nhất so với các bản trước. Ba hệ quả thật, không né được:

**a) Không dịch được → mất phần lớn nguồn tiếng Anh.**
Các bản trước dựa vào LLM để "viết lại + dịch" trong cùng một bước. Bỏ LLM là mất luôn khả năng dịch.
Nguồn tiếng Anh vẫn crawl và lưu được, nhưng **không đăng được**.
→ Xem mục 1.5 về việc phạm vi 8 môn co lại thế nào.

**b) Nội dung không còn "viết lại theo giọng riêng".**
Yêu cầu gốc (mục 14) nói nội dung phải có giá trị riêng, không copy lại bài từ website khác.
Không có LLM thì không đạt được điều đó. Cái làm được là **trích dẫn ngắn có dẫn nguồn** —
đăng tiêu đề + 2–3 câu tóm tắt từ RSS + ghi rõ nguồn. Đây là dạng *tổng hợp tin có dẫn nguồn*,
hợp lý và phổ biến, nhưng **không phải nội dung nguyên bản**.

Ghi nhận rõ: MVP này là một **máy tổng hợp tin**, chưa phải máy sản xuất nội dung.
Bước lên máy sản xuất nội dung chính là lúc cắm LLM vào (Phase 2).

**c) Quality Gate phải đổi luật.**
Bản trước có luật "quá giống nguồn → chặn". Không có LLM thì luật đó chặn 100% bài.
→ Đổi thành: **giới hạn độ dài phần trích** (chỉ lấy tóm tắt, không lấy toàn văn) + **bắt buộc có nguồn**.

### 1.4. Bản quyền

- Không lấy toàn văn bài báo. Chỉ lấy **tiêu đề + tóm tắt (`description` của RSS)** — đây là phần
  nguồn chủ động phát hành để được trích dẫn.
- **Luôn ghi nguồn** trong bài, dạng chữ (không phải link, để tránh mục 1.2).
- Không tải ảnh của nguồn về đăng. MVP đăng **text thuần** nên không phát sinh vấn đề này.

### 1.5. Phạm vi 8 môn co lại — cần biết trước

Báo thể thao tiếng Việt gần như chỉ có bóng đá; các môn ngách (Badminton, Pickleball, Cycling, Gym)
chủ yếu có nguồn tiếng Anh. Không có LLM dịch nghĩa là:

| Nhóm | Trạng thái ở MVP |
|---|---|
| Có nguồn RSS tiếng Việt (bóng đá, tennis, chạy bộ ở mức nào đó) | **Đăng được** |
| Chỉ có nguồn tiếng Anh (pickleball, cycling, gym, badminton) | **Crawl + lưu, chưa đăng** |

→ **Vẫn cấu hình đủ 8 môn và vẫn crawl hết.** Dữ liệu tích lại sẵn, đến khi cắm LLM là đăng được ngay
mà không mất gì. Chỉ là ở MVP số môn thực sự lên bài sẽ ít hơn 8.

Con số chính xác chỉ biết sau khi khảo sát nguồn thật (chặng 0b). Đây là việc tra cứu, không phải code.

**RSS-first:** chỉ dùng RSS và API công khai. Không scrape HTML, không đụng cơ chế chống bot —
vừa đúng nguyên tắc, vừa khỏi bảo trì selector khi trang nguồn đổi giao diện.

### 1.6. Chọn tin — lọc thô, không thang điểm

Đã có bước duyệt bài thì bộ lọc máy không cần thông minh. Thang điểm có trọng số lúc này cũng chỉ là
đoán, vì chưa có dữ liệu để hiệu chỉnh.

MVP: lấy bài trong 24h · bỏ trùng · bỏ chủ đề đã đăng · tin nhiều nguồn cùng đưa lên trước ·
chia suất theo môn.

### 1.7. Bỏ đo lường — cái gì mất, cái gì không

| Bỏ | Mất vĩnh viễn? |
|---|---|
| Thu Insights bài đăng | **Không.** Miễn là **lưu `fb_post_id`**, sau này bật lên là kéo về được |
| Đếm click qua redirect nội bộ | **Mất.** Click không đi qua hệ thống mình thì không lấy lại được |

→ Chỉ cần **lưu `fb_post_id`** khi đăng (một cột, gần như miễn phí) là giữ được đường lui.
Về click: link do bạn tự tạo trên Shopee nên thống kê vẫn xem được trong dashboard của Shopee;
thứ duy nhất mất là biết *bài nào* ra click.

---

## 2. Module MVP — 7 module

| # | Module | Vai trò |
|---|---|---|
| M1 | **Cấu hình** | File YAML: nguồn RSS (URL, môn, ngôn ngữ) + link affiliate theo môn |
| M2 | **Crawler** | Kéo RSS, chuẩn hoá, chống trùng, gom nhóm cùng tin |
| M3 | **Lọc & xếp hàng tin** | 4 luật thô, không thang điểm |
| M4 | **Post Builder** | Dựng bài từ template (chỗ sau này cắm LLM) |
| M5 | **Quality Gate** | 3 luật chặn |
| M6 | **Màn hình duyệt bài** | Xem / sửa / duyệt / xoá + kill switch |
| M7 | **Publisher** | Đăng bài + comment link theo môn + retry + lưu `fb_post_id` |

Scheduler gộp vào M7.

---

## 3. Chi tiết module

### 3.1. M1 — Cấu hình (file YAML, không có UI)

Hai phần trong một file:

```yaml
sources:
  - name: VnExpress Thể thao
    url: https://...
    sport: football
    lang: vi
    enabled: true

affiliate_links:          # link theo môn — bài môn nào gắn link môn đó
  football:  ["https://shopee.vn/..."]
  running:   ["https://shopee.vn/..."]
  badminton: ["https://shopee.vn/..."]
  # ...
```

- Nhiều link cho một môn thì **xoay vòng** để không lặp lại một link mãi.
- Môn chưa có link → bài môn đó đăng không kèm comment. Không phải lỗi.
- Sửa nguồn/link là việc vài tuần một lần → **không xây màn hình CRUD**. Thêm sau lúc nào cũng được.

### 3.2. M2 — Crawler

- Chạy định kỳ, lấy bài mới, chuẩn hoá: tiêu đề, tóm tắt, thời gian, URL gốc, môn, ngôn ngữ.
- **Chống trùng 2 lớp:**
  1. Trùng tuyệt đối — theo URL / GUID của RSS.
  2. Trùng nội dung — nhiều báo cùng một tin → so tương đồng tiêu đề (so khớp chuỗi đơn giản là đủ).
- Việc gom nhóm bài trùng có tác dụng kép: chống trùng, đồng thời cho biết **tin nào nhiều nguồn đưa** —
  đầu vào duy nhất mà M3 cần.
- **Crawl cả nguồn tiếng Anh và lưu lại**, dù MVP chưa đăng được (mục 1.5).
- **Luôn lưu URL nguồn.**

### 3.3. M3 — Lọc & xếp hàng tin

1. Chỉ lấy bài trong 24h gần nhất.
2. Loại bài trùng và chủ đề đã đăng.
3. **Chỉ lấy bài `lang = vi`** (giới hạn của MVP không LLM).
4. Xếp: tin nhiều nguồn cùng đưa lên trước, rồi đến tin mới nhất.
5. Chia suất theo môn.

### 3.4. M4 — Post Builder ⭐

Dựng bài từ template. Cấu trúc bài:

```
{Tiêu đề tin}

{Tóm tắt 2–3 câu từ RSS}

{CTA cố định theo môn}

Nguồn: {tên nguồn}
{hashtag theo môn}
```

- Template lưu ở **file cấu hình, tách theo môn** — sửa được không cần đụng code.
- **Giới hạn độ dài phần trích** — chỉ tóm tắt, không lấy toàn văn (mục 1.4).

**Thiết kế quan trọng — chỗ cắm LLM sau này:**
M4 phải là một **interface một hàm**: `build_post(article) -> PostContent`.
MVP có một implementation duy nhất là `TemplateBuilder`. Phase 2 thêm `LLMBuilder` cùng interface,
đổi cấu hình là xong — **không phải sửa M3, M5, M6, M7**.

Đây là điểm đáng đầu tư 30 phút thiết kế ngay từ đầu, vì cắm LLM là bước nâng cấp chắc chắn sẽ làm.

### 3.5. M5 — Quality Gate

3 luật chặn:

1. Trùng lặp với bài đã đăng → chặn
2. Thiếu nguồn tham khảo → chặn
3. Phần trích vượt quá giới hạn độ dài → chặn

> Đã bỏ luật "quá giống nguồn" — không có LLM viết lại thì luật đó chặn mọi bài (mục 1.3c).

### 3.6. M6 — Màn hình duyệt bài

Một màn hình duy nhất, là toàn bộ giao diện MVP:

- Danh sách bài chờ + đã đăng + lỗi.
- Xem trước, **sửa nội dung trực tiếp** (quan trọng hơn hẳn khi không có LLM — bài template sẽ cần
  gọt tay nhiều hơn), duyệt, xoá.
- Hiển thị link affiliate sẽ gắn (lấy tự động theo môn), cho phép sửa/bỏ trước khi đăng.
- Nút **DỪNG TOÀN BỘ** (kill switch).
- Công tắc auto-approve, **mặc định TẮT**.

### 3.7. M7 — Publisher

- Đăng qua **Graph API chính thức**, dạng **text thuần**.
- Đăng xong → lấy `post_id` → **gọi lần hai đăng comment chứa link affiliate của môn đó**.
- **Lưu `fb_post_id`** — bắt buộc, đường lui cho Phase 2 (mục 1.7).
- **Trạng thái bài và comment tách riêng.** Comment lỗi thì retry riêng, không đăng lại bài.
- Retry có backoff với lỗi tạm thời; lỗi vĩnh viễn (token hỏng, sai quyền) thì dừng và báo.
- Lịch: khung giờ cố định (vd 7h, 12h, 19h, 21h) + nhiễu ngẫu nhiên vài phút + **hạn mức cứng/ngày**.
- Health-check token định kỳ.

---

## 3.8. Dữ liệu tối thiểu

| Bảng | Vai trò |
|---|---|
| `RawArticle` | Bài crawl thô + URL nguồn + ngôn ngữ + hash chống trùng |
| `TopicCluster` | Nhóm bài cùng một tin |
| `Post` | Nội dung, trạng thái, môn, **`fb_post_id`**, link aff, trạng thái comment |

Ba bảng, **SQLite**. Nguồn và link affiliate nằm ở file cấu hình.

---

## 4. Luồng vận hành một ngày

```
[06:00] Crawler kéo RSS (lưu cả tiếng Anh, chỉ đăng tiếng Việt)
          ↓
        Chuẩn hoá → chống trùng → gom nhóm cùng tin
          ↓
        Lọc thô: 24h · lang=vi · chưa đăng · xếp theo độ phủ nguồn · chia suất môn
          ↓
        Post Builder dựng bài từ template
          ↓
        Quality Gate → 3 luật chặn
          ↓
[07:00] Màn hình duyệt ──► Admin ~5 phút: duyệt / gọt lại câu chữ
          ↓
[7h/12h/19h/21h] Đăng bài  ──►  comment link aff theo môn
                              (lưu fb_post_id)
```

---

## 5. Hạ tầng triển khai

Mini server **2GB RAM**, expose qua subdomain của `truonglb.cloud`.

### Cách expose — đã có sẵn Cloudflare Tunnel

Máy hiện tại đang chạy `cloudflared` (tunnel `9a59ced9…`) phục vụ `truonglb.cloud`, `luxe.`,
`nhomkinh.`, `lms.`. Thêm subdomain chỉ là thêm mục `ingress` + tạo DNS route.
Không mở port, không cấu hình TLS thủ công.

| Phương án | Khi nào | Cách làm |
|---|---|---|
| **A. Tunnel riêng trên mini server** *(đề xuất)* | Mini server ở nơi khác, hoặc muốn độc lập | Cài `cloudflared` trên mini server, tạo tunnel mới |
| **B. Dùng tunnel sẵn có** | Mini server cùng LAN | Thêm ingress trỏ `http://<ip-mini>:<port>` |

Đề xuất A: app chạy 24/7 trên mini server mà phụ thuộc máy hiện tại phải bật thì mất ý nghĩa
của việc tách server.

> ⚠️ **Sửa `config.yml` của tunnel: không dùng SIGHUP để reload.** `cloudflared` thoát hẳn khi nhận
> SIGHUP, sập luôn các hostname đang chạy. Phải restart bằng service manager.
> Áp dụng cho phương án B; phương án A không đụng tunnel đang chạy nên an toàn hơn.

### Bảo mật — bắt buộc

Màn hình duyệt bài nằm trên internet công khai và **có quyền đăng lên Fanpage**.
Để trần là ai tìm thấy URL cũng đăng được lên Page của bạn.

- **Đặt sau Cloudflare Access** — đã dùng Tunnel rồi nên bật rất nhanh, đăng nhập bằng email,
  không phải tự viết auth.
- Page Access Token để trong biến môi trường, **không commit vào git**.

### Ràng buộc 2GB RAM

Rất thoải mái cho khối lượng này — nhất là khi đã bỏ LLM.

- **SQLite**, không Postgres. 3 bảng, vài nghìn bản ghi/năm.
- Crawl chạy **tuần tự**, không song song nhiều luồng — hợp RAM ít, tránh đụng rate limit nguồn.
- Khi cắm LLM ở Phase 2: **gọi qua API**, không chạy model local (2GB không đủ cho model nào đáng dùng).

---

## 6. Tiêu chí "MVP hoàn thành"

Chạy liên tục 7 ngày:

- [ ] Kéo được nguồn cho các môn đã cấu hình, không bài trùng lọt qua.
- [ ] Đăng ≥ 5 bài/ngày đúng lịch lên Page thật, tỷ lệ thành công ≥ 95%.
- [ ] Bài có môn khớp cấu hình link → comment chứa đúng link môn đó xuất hiện dưới bài.
- [ ] Comment lỗi thì retry được riêng, không đăng lại bài.
- [ ] Mọi bài đã đăng đều lưu được `fb_post_id`.
- [ ] Bài đăng luôn có ghi nguồn, phần trích không vượt giới hạn.
- [ ] Kill switch dừng toàn bộ trong 1 thao tác.
- [ ] Màn hình duyệt không truy cập được nếu chưa đăng nhập.

---

## 7. Thứ tự làm

| Chặng | Nội dung | Vì sao |
|---|---|---|
| 0 | Tạo Fanpage + Meta App + long-lived token | Vài giờ, mọi thứ sau phụ thuộc |
| 0b | Khảo sát & gom danh sách RSS (ưu tiên tiếng Việt) | Tra cứu, không phải code — làm song song |
| 1 | **Đăng thử 1 bài + 1 comment lên Page thật bằng script tay** | **Làm đầu tiên.** Chứng minh chuỗi token/quyền/API chạy được, trước khi xây gì khác |
| 2 | M1 + M2 (cấu hình + crawler) | Không có dữ liệu thì không làm gì tiếp được |
| 3 | M3 + M4 + M5 (lọc → dựng bài → kiểm) | Phần lõi |
| 4 | M6 (màn hình duyệt + auth) | Nối thành vòng lặp |
| 5 | M7 đầy đủ (lịch, retry, comment, hạn mức) | Hoàn thiện khâu đăng |
| 6 | Deploy lên mini server + Cloudflare Tunnel + Access | Đưa vào chạy thật |

---

## 8. Để sau MVP

| Giai đoạn | Nội dung |
|---|---|
| **Phase 2** | **Cắm LLM vào M4** (viết lại + dịch → mở khoá các môn chỉ có nguồn tiếng Anh) · Thu Insights (dùng `fb_post_id` đã lưu) · Link redirect + đếm click · Ảnh text-card |
| **Phase 3** | Phân tích hiệu quả (môn/chủ đề/khung giờ) · Tự điều chỉnh tỷ lệ & lịch · Import đơn hàng & commission · Bài affiliate tự viết · Multi-page (lúc này mới cần App Review) |

Đã loại bỏ hẳn (do link affiliate người dùng tự cung cấp): crawl sản phẩm từ network,
chấm điểm sản phẩm theo giá/rating/commission, tích hợp API Shopee.

---

## 9. Kết quả chặng 0b — khảo sát nguồn thật (2026-09-07)

Đã dựng M1 + M2 và chạy thật. **7/8 nguồn sống**, thu 123 bài trong 24h. Phân bố môn:

| Môn | Bài/24h | Ghi chú |
|---|---|---|
| football | 96 | 78% toàn bộ |
| other (đa môn: ASIAD, bóng chuyền…) | 16 | |
| tennis | 7 | |
| pickleball | 3 | |
| badminton | 1 | |
| **running / cycling / gym** | **0** | Không nguồn tiếng Việt nào đưa tin |

→ **Xác nhận bằng dữ liệu thật:** không có LLM dịch thì MVP thực chất là Page bóng đá.
Nếu muốn Page đa môn thật sự thì **cắm LLM phải lên sớm hơn Phase 2**, không phải việc để sau.
Đây là quyết định nên đưa ra sớm.

Ghi nhận thêm từ lần chạy thật:
- Nguồn `vnexpress/cac-mon-khac` **đã chết** (lẫn bài từ 2019, 0 bài mới) — giữ trong cấu hình,
  bộ lọc 24h tự loại.
- **21/136 bài là "bài tiện ích"** (lịch thi đấu, BXH, link xem trực tiếp) — không đáng đăng lại,
  đã lọc riêng. Đây là ~15% lượng crawl.

---

## Vấn đề chưa giải quyết
- Chưa chốt số bài/ngày mục tiêu → tạm lấy **5 bài/ngày**, chia suất theo số môn thực tế đăng được.
- Chưa chốt mini server cùng LAN hay nơi khác → tạm thiết kế theo phương án A (tunnel riêng).
- Bài template sẽ khô hơn bài LLM viết. Chấp nhận ở MVP, nhưng đây là lý do bước "sửa trực tiếp"
  ở màn hình duyệt quan trọng hơn bình thường.
