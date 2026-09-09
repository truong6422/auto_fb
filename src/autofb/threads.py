"""Đăng lại bài sang Threads — kênh tự động hợp lệ duy nhất còn lại cùng hệ Meta.

Nhóm Facebook thì không đăng bằng API được nữa (Meta gỡ Groups API 22/04/2024), còn
Threads có API chính thức, miễn phí, 250 bài/ngày. Khán giả cũng là người dùng Meta
nên nội dung thể thao tiếng Việt đăng sang đó không lạc chỗ.

Quy trình BẮT BUỘC hai bước, không có đường tắt đăng thẳng:
    POST /{user}/threads          -> tạo "container", trả về creation_id
    POST /{user}/threads_publish  -> đăng container đó

Với ảnh, Threads phải đi tải ảnh về trước nên container chưa sẵn sàng ngay. Tài liệu
khuyên chờ trung bình 30 giây; ở đây hỏi trạng thái container thay vì ngủ mù 30 giây —
xong sớm thì đi tiếp luôn, mà hỏng thì biết ngay lý do thay vì đăng lỗi.
"""

import logging
import time
from dataclasses import dataclass

import httpx

from .facebook import PermanentError, TransientError, classify_meta_error

logger = logging.getLogger(__name__)

THREADS_HOST = "https://graph.threads.net/v1.0"
# Gia hạn token nằm ở gốc tên miền, KHÔNG có /v1.0 — ghép nhầm là 404.
THREADS_ROOT = "https://graph.threads.net"
REQUEST_TIMEOUT = 20

# Giới hạn cứng của Threads là 500 ký tự, và emoji tính theo số byte UTF-8 chứ không
# phải một ký tự. Cắt ở 460 để phần đếm theo byte còn chỗ thở — vượt hạn là API từ
# chối cả bài, mất trắng chứ không phải bị cắt bớt.
MAX_TEXT = 460

# Chờ Threads tải xong ảnh. 45 giây là quá đủ cho một tấm PNG ~200KB; quá đó thì coi
# như nguồn ảnh có vấn đề và quay về đăng bài chữ.
READY_TIMEOUT = 45
POLL_SECONDS = 3


@dataclass(frozen=True)
class ThreadsPost:
    id: str
    with_image: bool


def shorten(text: str, limit: int = MAX_TEXT) -> str:
    """Cắt cho vừa Threads, ưu tiên cắt ở ranh giới dòng rồi tới ranh giới từ.

    Cắt giữa từ trông như bài bị lỗi; cắt ở cuối dòng thì vẫn đọc ra một bài hoàn chỉnh.
    """
    if len(text) <= limit:
        return text

    head = text[:limit]
    for sep in ("\n", " "):
        cut = head.rfind(sep)
        # Cắt quá ngắn thì thà cắt giữa từ còn hơn mất nội dung: 60% là ngưỡng chấp nhận.
        if cut > limit * 0.6:
            return head[:cut].rstrip() + "…"
    return head.rstrip() + "…"


class ThreadsClient:
    def __init__(self, user_id: str, access_token: str):
        self.user_id = user_id
        self.access_token = access_token

    def _request(self, method: str, path: str, params: dict,
                 base: str = THREADS_HOST) -> dict:
        payload = {**params, "access_token": self.access_token}
        kwargs = {"params": payload} if method == "GET" else {"data": payload}
        try:
            response = httpx.request(method, f"{base}/{path}",
                                     timeout=REQUEST_TIMEOUT, **kwargs)
        except httpx.HTTPError as exc:
            raise TransientError(f"Lỗi mạng: {exc}") from exc

        try:
            body = response.json()
        except ValueError:
            raise TransientError(f"Phản hồi không phải JSON (HTTP {response.status_code})")

        if response.is_success:
            return body
        raise classify_meta_error(body, response.status_code)

    # ---------- hai bước ----------

    def create_container(self, text: str, image_url: str = "", link: str = "") -> str:
        data: dict[str, str] = {"text": shorten(text)}
        if image_url:
            data.update(media_type="IMAGE", image_url=image_url)
        else:
            data["media_type"] = "TEXT"
            # link_attachment chỉ dùng được cho bài chữ. Có nó thì Threads dựng thẻ
            # xem trước dẫn về Fanpage — đó mới là chỗ cần kéo người theo dõi.
            if link:
                data["link_attachment"] = link

        container_id = self._request("POST", f"{self.user_id}/threads", data).get("id")
        if not container_id:
            raise PermanentError("Threads không trả về id container")
        return str(container_id)

    def wait_ready(self, container_id: str, timeout: int = READY_TIMEOUT) -> None:
        """Chờ Threads tải xong ảnh. Bài chữ thì FINISHED ngay từ lần hỏi đầu."""
        deadline = time.monotonic() + timeout
        while True:
            body = self._request("GET", container_id,
                                 {"fields": "status,error_message"})
            status = body.get("status")
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise PermanentError(
                    f"Threads không dựng được bài: {body.get('error_message') or 'không rõ'}")
            if time.monotonic() >= deadline:
                raise TransientError(f"Threads xử lý quá {timeout}s (trạng thái {status})")
            time.sleep(POLL_SECONDS)

    def publish(self, container_id: str) -> str:
        body = self._request("POST", f"{self.user_id}/threads_publish",
                             {"creation_id": container_id})
        post_id = body.get("id")
        if not post_id:
            raise PermanentError("Threads không trả về id bài đăng")
        return str(post_id)

    def refresh_token(self) -> str:
        """Gia hạn token thêm 60 ngày, trả về token MỚI (token cũ vẫn còn hiệu lực).

        Khác hẳn Facebook: Page token sinh từ user token dài hạn thì sống mãi, còn
        token Threads CHẾT sau 60 ngày và quá hạn thì không gia hạn được nữa — phải
        đi xin lại từ đầu bằng tay. Nên việc gia hạn phải tự chạy, không thể trông chờ
        người dùng nhớ.
        """
        body = self._request("GET", "refresh_access_token",
                             {"grant_type": "th_refresh_token"}, base=THREADS_ROOT)
        token = body.get("access_token")
        if not token:
            raise PermanentError("Threads không trả về token mới")
        return str(token)

    # ---------- dùng ở ngoài ----------

    def post(self, text: str, image_url: str = "", link: str = "") -> ThreadsPost:
        """Đăng một bài. Có ảnh thì đăng kèm ảnh, hỏng ảnh thì vẫn đăng bài chữ.

        Quay về bài chữ thay vì bỏ luôn: ảnh hỏng là chuyện của một tấm ảnh, không
        đáng để mất cả bài — mà bài chữ kèm link vẫn dẫn người đọc về Fanpage.
        """
        if image_url:
            try:
                container = self.create_container(text, image_url=image_url)
                self.wait_ready(container)
                return ThreadsPost(self.publish(container), with_image=True)
            except (TransientError, PermanentError) as exc:
                logger.warning("Threads bỏ ảnh (%s), đăng bài chữ thay thế", exc)

        container = self.create_container(text, link=link)
        self.wait_ready(container)
        return ThreadsPost(self.publish(container), with_image=False)
