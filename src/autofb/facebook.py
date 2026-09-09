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


class TransientError(Exception):
    """Lỗi tạm thời — nên thử lại sau."""


class PermanentError(Exception):
    """Lỗi không tự khỏi — dừng và báo người, đừng thử lại."""


@dataclass(frozen=True)
class PageInfo:
    id: str
    name: str


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

        raise self._classify(body, response.status_code)

    @staticmethod
    def _classify(body: dict, status_code: int) -> Exception:
        error = body.get("error", {})
        code = error.get("code")
        message = error.get("message", f"HTTP {status_code}")

        if code in _TRANSIENT_CODES or status_code >= 500:
            return TransientError(f"[{code}] {message}")
        return PermanentError(f"[{code}] {message}")

    # ---------- thao tác ----------

    def verify(self) -> PageInfo:
        """Kiểm tra token còn dùng được không và trỏ đúng Page nào.

        Chỉ đọc, không đăng gì — an toàn để chạy định kỳ làm health-check.
        """
        body = self._request("GET", f"{self.page_id}?fields=id,name")
        return PageInfo(id=str(body.get("id", "")), name=body.get("name", ""))

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

    def publish_comment(self, fb_post_id: str, message: str) -> str:
        """Đăng comment dưới bài đã đăng — nơi đặt link affiliate."""
        body = self._request("POST", f"{fb_post_id}/comments", {"message": message})
        comment_id = body.get("id")
        if not comment_id:
            raise PermanentError(f"Facebook không trả về id comment: {body}")
        return str(comment_id)
