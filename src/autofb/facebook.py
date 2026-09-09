"""Gọi Facebook Graph API — đăng bài và đăng comment.

Dùng API chính thức, không giả lập trình duyệt.

Phân biệt hai loại lỗi vì cách xử lý khác hẳn nhau:
  TransientError  — mạng chập chờn, rate limit, lỗi 5xx  -> thử lại được
  PermanentError  — token hỏng, sai quyền, sai Page ID    -> thử lại vô ích, phải báo người
Không phân biệt thì hệ thống sẽ retry vô hạn một token đã chết.
"""

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

GRAPH_HOST = "https://graph.facebook.com"
REQUEST_TIMEOUT = 20
UPLOAD_TIMEOUT = 90

# Mã lỗi Graph API nên thử lại. Ngoài danh sách này thì coi là lỗi vĩnh viễn.
_TRANSIENT_CODES = {1, 2, 4, 17, 32, 341, 613}

# Lỗi thuộc về TOKEN/QUYỀN, không thuộc về nội dung bài:
#   190 token hết hạn hoặc bị thu hồi   102 phiên không hợp lệ
#   10 / 200–299 thiếu quyền            2500 OAuth sai
#   458–467 người dùng phải đăng nhập lại
_AUTH_CODES = {10, 102, 190, 2500, 458, 459, 460, 463, 464, 467}


class TransientError(Exception):
    """Lỗi tạm thời — nên thử lại sau."""


class PermanentError(Exception):
    """Lỗi không tự khỏi — dừng và báo người, đừng thử lại."""


class AuthError(PermanentError):
    """Token hỏng / thiếu quyền — hỏng ở TÀI KHOẢN, không phải ở bài đang đăng.

    Phải tách khỏi PermanentError vì cách xử lý ngược nhau: bài sai nội dung thì đánh
    dấu bài đó hỏng rồi đăng bài kế tiếp; token hỏng thì mọi bài đều sẽ hỏng như nhau,
    đánh dấu tiếp là xoá sạch hàng chờ trong một tiếng dù bài chẳng có lỗi gì.
    """


def classify_meta_error(body: dict, status_code: int) -> Exception:
    """Đổi lỗi Graph API thành đúng một trong ba loại ngoại lệ ở trên.

    Để ở mức module chứ không nằm trong FacebookClient vì Threads (graph.threads.net)
    trả lỗi y hệt khuôn này — cùng nhà Meta, cùng cấu trúc {"error": {...}}.
    """
    error = body.get("error", {})
    code = error.get("code")
    message = error.get("message", f"HTTP {status_code}")

    if code in _TRANSIENT_CODES or status_code >= 500:
        return TransientError(f"[{code}] {message}")
    # Dải 200–299 là nhóm lỗi quyền của Graph API, không liệt kê hết từng mã được.
    if code in _AUTH_CODES or (isinstance(code, int) and 200 <= code <= 299):
        return AuthError(f"[{code}] {message}")
    return PermanentError(f"[{code}] {message}")


@dataclass(frozen=True)
class PageInfo:
    id: str
    name: str


@dataclass(frozen=True)
class PagePost:
    """Một bài ĐANG NẰM TRÊN Fanpage, kèm số tương tác thật."""

    id: str
    message: str
    created_time: str                # ISO 8601 do Facebook trả về
    permalink: str
    picture: str = ""
    reactions: int = 0
    comments: int = 0
    shares: int = 0


class FacebookClient:
    def __init__(self, page_id: str, access_token: str, api_version: str = "v21.0"):
        self.page_id = page_id
        self.access_token = access_token
        self.base = f"{GRAPH_HOST}/{api_version}"

    # ---------- gọi API ----------

    def _request(
        self, method: str, path: str, data: dict | None = None,
        files: dict | None = None,
    ) -> dict:
        url = f"{self.base}/{path}"
        payload = {**(data or {}), "access_token": self.access_token}

        # GET phải đưa tham số vào query string. Nhét vào body thì Facebook không thấy
        # access_token và trả lỗi khó hiểu "(#200) Provide valid app ID".
        timeout = REQUEST_TIMEOUT
        if method.upper() == "GET":
            kwargs = {"params": payload}
        else:
            kwargs = {"data": payload}
            if files:
                # Upload ảnh từ RAM: timeout dài hơn vì mạng nhà upload chỉ ~23 Mbit/s.
                kwargs["files"] = files
                timeout = UPLOAD_TIMEOUT

        try:
            response = httpx.request(method, url, timeout=timeout, **kwargs)
        except httpx.HTTPError as exc:
            raise TransientError(f"Lỗi mạng: {exc}") from exc

        try:
            body = response.json()
        except ValueError:
            raise TransientError(f"Phản hồi không phải JSON (HTTP {response.status_code})")

        if response.is_success:
            return body

        raise classify_meta_error(body, response.status_code)

    _classify = staticmethod(classify_meta_error)

    # ---------- thao tác ----------

    def verify(self) -> PageInfo:
        """Kiểm tra token còn dùng được không và trỏ đúng Page nào.

        Chỉ đọc, không đăng gì — an toàn để chạy định kỳ làm health-check.
        """
        body = self._request("GET", f"{self.page_id}?fields=id,name")
        return PageInfo(id=str(body.get("id", "")), name=body.get("name", ""))

    def recent_posts(self, limit: int = 25) -> list[PagePost]:
        """Các bài mới nhất trên Fanpage.

        Đây là nguồn sự thật cho mục "Đã đăng". DB chỉ biết mình đã GỬI ĐI cái gì;
        Facebook biết bài hiện ra sao và có bao nhiêu tương tác — mà tương tác mới là
        thứ cần nhìn để biết nên đăng tiếp kiểu nào.

        `summary(true).limit(0)` lấy đúng con số đếm mà không kéo về từng lượt thả tim
        hay từng bình luận.
        """
        body = self._request("GET", f"{self.page_id}/posts", {
            "fields": "id,created_time,message,permalink_url,full_picture,"
                      "reactions.summary(true).limit(0),"
                      "comments.summary(true).limit(0),shares",
            "limit": limit,
        })
        return [self._page_post(item) for item in body.get("data", [])]

    @staticmethod
    def _page_post(item: dict) -> PagePost:
        def counted(field: str) -> int:
            summary = (item.get(field) or {}).get("summary") or {}
            return int(summary.get("total_count") or 0)

        return PagePost(
            id=str(item.get("id", "")),
            message=item.get("message") or "",
            created_time=item.get("created_time") or "",
            permalink=item.get("permalink_url") or "",
            picture=item.get("full_picture") or "",
            reactions=counted("reactions"),
            comments=counted("comments"),
            # Bài không ai chia sẻ thì Facebook bỏ hẳn trường `shares`, không trả 0.
            shares=int((item.get("shares") or {}).get("count") or 0),
        )

    def publish_post(self, message: str) -> str:
        """Đăng bài text lên Page. Trả về fb_post_id."""
        body = self._request("POST", f"{self.page_id}/feed", {"message": message})
        post_id = body.get("id")
        if not post_id:
            raise PermanentError(f"Facebook không trả về id bài đăng: {body}")
        return str(post_id)

    def publish_photo_url(self, image_url: str, message: str) -> str:
        """Đăng ảnh bằng CÁCH ĐƯA URL cho Facebook tự tải.

        Không tải ảnh về máy mình: không tốn băng thông, RAM hay đĩa của mini server.
        Vẫn trả về post_id (id bài trên feed), không phải id của ảnh.
        """
        body = self._request(
            "POST", f"{self.page_id}/photos", {"url": image_url, "caption": message}
        )
        post_id = body.get("post_id") or body.get("id")
        if not post_id:
            raise PermanentError(f"Facebook không trả về id bài đăng: {body}")
        return str(post_id)

    # ---------- bài nhiều ảnh ----------
    #
    # Quy trình 2 bước bắt buộc của Graph API: mỗi ảnh phải upload trước ở chế độ
    # published=false (Facebook giữ ảnh nhưng KHÔNG hiện lên feed), lấy về photo_id,
    # rồi mới tạo một bài /feed gắn tất cả photo_id đó. Đăng thẳng nhiều ảnh vào
    # /photos sẽ ra nhiều bài riêng lẻ chứ không phải một bài.

    def upload_unpublished_photo_bytes(self, image: bytes, filename: str = "card.png") -> str:
        """Đưa ảnh từ RAM lên Facebook, chưa hiện lên feed. Trả về photo_id."""
        body = self._request(
            "POST", f"{self.page_id}/photos",
            {"published": "false"},
            files={"source": (filename, image, "image/png")},
        )
        return self._photo_id(body)

    def upload_unpublished_photo_url(self, image_url: str) -> str:
        """Như trên nhưng để Facebook tự đi tải ảnh — không tốn băng thông của mình."""
        body = self._request(
            "POST", f"{self.page_id}/photos", {"url": image_url, "published": "false"}
        )
        return self._photo_id(body)

    @staticmethod
    def _photo_id(body: dict) -> str:
        photo_id = body.get("id")
        if not photo_id:
            raise PermanentError(f"Facebook không trả về id ảnh: {body}")
        return str(photo_id)

    def publish_with_photos(self, message: str, photo_ids: list[str]) -> str:
        """Tạo bài feed gắn sẵn các ảnh đã upload. Trả về fb_post_id."""
        if not photo_ids:
            raise ValueError("publish_with_photos cần ít nhất một ảnh")

        data: dict[str, str] = {"message": message}
        for index, photo_id in enumerate(photo_ids):
            # Graph API nhận mảng qua cú pháp attached_media[0], attached_media[1]...
            data[f"attached_media[{index}]"] = f'{{"media_fbid":"{photo_id}"}}'

        body = self._request("POST", f"{self.page_id}/feed", data)
        post_id = body.get("id")
        if not post_id:
            raise PermanentError(f"Facebook không trả về id bài đăng: {body}")
        return str(post_id)

    def post_picture(self, fb_post_id: str) -> str:
        """URL ảnh Facebook đang hiển thị cho bài này.

        Dùng để đăng lại sang Threads: Threads đòi ảnh phải nằm ở một URL công khai
        tải được. Card của mình vẽ trong RAM và không lưu ra đĩa, nên mượn luôn bản
        Facebook vừa nhận — vừa khỏi mở thêm đường công khai vào máy, vừa chắc chắn
        hai nơi hiện đúng một tấm ảnh.
        """
        body = self._request("GET", f"{fb_post_id}?fields=full_picture")
        return body.get("full_picture") or ""

    def publish_comment(self, fb_post_id: str, message: str) -> str:
        """Đăng comment dưới bài đã đăng — nơi đặt link affiliate."""
        body = self._request("POST", f"{fb_post_id}/comments", {"message": message})
        comment_id = body.get("id")
        if not comment_id:
            raise PermanentError(f"Facebook không trả về id comment: {body}")
        return str(comment_id)
