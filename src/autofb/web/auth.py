"""Khoá màn hình quản trị bằng HTTP Basic.

BẮT BUỘC PHẢI CÓ: màn hình này có nút đăng bài lên Fanpage. Đưa nó ra subdomain công
khai mà không khoá thì bất kỳ ai đoán được URL đều đăng bài lên Page của bạn được,
và con bot dò subdomain thì lúc nào cũng có.

Không đặt mật khẩu -> app trả 503 cho mọi trang. Cố ý làm hỏng to: nếu chỉ ghi cảnh
báo vào log rồi vẫn chạy thì sẽ không ai đọc cái log đó, và trang vẫn để trần.
"""

import hmac
import os
import secrets
from base64 import b64decode

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, Response

# Đường không cần đăng nhập: Docker healthcheck gọi vào đây, nó không có mật khẩu.
PUBLIC_PATHS = frozenset({"/healthz"})

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": 'Basic realm="AutoFB", charset="UTF-8"'}


def _credentials() -> tuple[str, str] | None:
    user = os.environ.get("AUTOFB_USER", "admin").strip()
    password = os.environ.get("AUTOFB_PASSWORD", "").strip()
    return (user, password) if password else None


def _matches(header: str, expected: tuple[str, str]) -> bool:
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        user, _, password = b64decode(encoded).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False

    # compare_digest cho CẢ HAI trường: so bằng "==" sẽ thoát sớm ở ký tự sai đầu tiên,
    # đủ để đo thời gian mà dò dần mật khẩu.
    return (
        hmac.compare_digest(user, expected[0])
        and hmac.compare_digest(password, expected[1])
    )


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next) -> Response:
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        expected = _credentials()
        if expected is None:
            return PlainTextResponse(
                "Chưa đặt AUTOFB_PASSWORD — màn hình quản trị bị khoá.\n"
                "Đặt biến môi trường AUTOFB_PASSWORD rồi khởi động lại.",
                status_code=503,
            )

        header = request.headers.get("authorization", "")
        if not header or not _matches(header, expected):
            return PlainTextResponse("Sai tài khoản hoặc mật khẩu", status_code=401,
                                     headers=_UNAUTHORIZED_HEADERS)

        return await call_next(request)


def suggest_password() -> str:
    """Sinh mật khẩu ngẫu nhiên để in ra cho người cài đặt chép vào .env."""
    return secrets.token_urlsafe(18)
