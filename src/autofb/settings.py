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


def load_env(path: Path | None = None) -> None:
    """Nạp .env vào os.environ. Biến môi trường có sẵn được ưu tiên, không ghi đè."""
    path = path or ENV_PATH
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


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
    load_env()
    return FacebookSettings(
        page_id=os.environ.get("FB_PAGE_ID", "").strip(),
        access_token=os.environ.get("FB_PAGE_ACCESS_TOKEN", "").strip(),
        api_version=os.environ.get("FB_API_VERSION", "v21.0").strip() or "v21.0",
    )


def silence_token_leak() -> None:
    """Tắt log INFO của httpx.

    httpx ghi nguyên URL của mỗi request, mà Graph API nhận access_token qua query
    string — nghĩa là Page token nằm nguyên văn trong log Docker, ai đọc được log là
    đăng bài lên Page được. Cảnh báo và lỗi vẫn giữ, chỉ bỏ dòng "HTTP Request: GET ...".
    """
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
