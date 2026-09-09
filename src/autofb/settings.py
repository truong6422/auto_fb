"""Đọc bí mật từ file .env.

Token KHÔNG nằm trong config/sources.yaml (file đó có thể commit) và KHÔNG nhập qua web
(màn hình web chưa có auth). Chỉ nằm trong .env, đã bị .gitignore chặn.

Tự đọc .env bằng vài dòng thay vì thêm phụ thuộc python-dotenv — nhu cầu chỉ có 3 biến.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .config import PROJECT_ROOT

ENV_PATH = PROJECT_ROOT / ".env"

# Đường dẫn đã cảnh báo là đọc hỏng — để không lặp log ở mỗi request.
_READ_FAILURES: set[Path] = set()


def read_env_file(path: Path | None = None) -> dict[str, str]:
    """Đọc .env thành dict. Không đụng os.environ.

    KHÔNG BAO GIỜ ném lỗi. File .env được gắn vào container, và nếu quyền trên máy chủ
    sai (chủ file là root, container chạy bằng uid 10001) thì đọc sẽ báo PermissionError.
    Để lỗi đó thoát ra là cả web sập ngay lúc import — trang trả 502 chỉ vì một cái
    chmod, trong khi biến môi trường vẫn có đủ thông tin để chạy tiếp.

    Đọc hỏng -> trả dict rỗng và ghi cảnh báo; current_value() rơi về os.environ.
    """
    path = path or ENV_PATH
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        # Chỉ cảnh báo MỘT LẦN cho mỗi đường dẫn: hàm này gọi ở mỗi request và mỗi
        # lượt chạy, log lặp lại sẽ lấp đầy ổ USB của box.
        if path not in _READ_FAILURES:
            _READ_FAILURES.add(path)
            logging.getLogger(__name__).error(
                "Không đọc được %s (%s) — dùng biến môi trường thay thế. "
                "Trong Docker, sửa bằng: chown 10001:10001 .env && chmod 640 .env",
                path, exc,
            )
        return {}

    values: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def load_env(path: Path | None = None) -> None:
    """Nạp .env vào os.environ. Biến môi trường có sẵn được ưu tiên, không ghi đè."""
    for key, value in read_env_file(path).items():
        os.environ.setdefault(key, value)


def current_value(key: str, default: str = "") -> str:
    """Giá trị đang có hiệu lực của một biến bí mật, ĐỌC LẠI FILE mỗi lần gọi.

    FILE THẮNG BIẾN MÔI TRƯỜNG — cố ý ngược với thông lệ. Lý do: ba container đọc
    biến môi trường từ `env_file`, mà Docker chỉ nạp nó MỘT LẦN lúc tạo container.
    Đổi token trong .env rồi chỉ tạo lại một container là hai container còn lại vẫn
    ôm token cũ, và giao diện báo "token hỏng" trong khi bot vẫn đăng bài bình thường.

    Đọc lại file ở mỗi lần gọi thì sửa .env là mọi tiến trình thấy ngay lượt sau.
    File .env được gắn vào container ở chế độ chỉ đọc (xem docker-compose.yml).
    Không có file thì rơi về biến môi trường như cũ.
    """
    return (read_env_file().get(key) or os.environ.get(key, default)).strip()


@dataclass(frozen=True)
class FacebookSettings:
    page_id: str
    access_token: str
    api_version: str = "v21.0"

    @property
    def configured(self) -> bool:
        return bool(self.page_id and self.access_token)

    @property
    def masked_token(self) -> str:
        """Che token khi hiển thị ra màn hình hay ghi log."""
        if not self.access_token:
            return "(chưa có)"
        return f"{self.access_token[:6]}…{self.access_token[-4:]}"


def load_facebook_settings() -> FacebookSettings:
    """Đọc cấu hình Facebook. Gọi lại ở mỗi lượt chạy — token đổi là có hiệu lực ngay."""
    return FacebookSettings(
        page_id=current_value("FB_PAGE_ID"),
        access_token=current_value("FB_PAGE_ACCESS_TOKEN"),
        api_version=current_value("FB_API_VERSION", "v21.0") or "v21.0",
    )


def silence_token_leak() -> None:
    """Tắt log INFO của httpx.

    httpx ghi nguyên URL của mỗi request, mà Graph API nhận access_token qua query
    string — nghĩa là Page token nằm nguyên văn trong log Docker, ai đọc được log là
    đăng bài lên Page được. Cảnh báo và lỗi vẫn giữ, chỉ bỏ dòng "HTTP Request: GET ...".
    """
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
