"""Dò thông tin từ token đang có: token loại gì, Page ID là bao nhiêu, Page token ở đâu.

Có một mã truy cập là đủ để lấy nốt phần còn lại — không phải vào Graph API Explorer mò tay.

Hai loại token dễ nhầm:
  User Token — của tài khoản cá nhân. KHÔNG đăng bài lên Page được.
               Nhưng gọi /me/accounts được, và đó là nơi lấy Page Token.
  Page Token — của chính Fanpage. Đây mới là thứ hệ thống cần.
"""

from dataclasses import dataclass, field

import httpx

from .facebook import GRAPH_HOST, REQUEST_TIMEOUT, PermanentError, TransientError


@dataclass
class TokenInfo:
    kind: str                      # "page" | "user" | "unknown"
    id: str = ""
    name: str = ""
    pages: list[dict] = field(default_factory=list)   # chỉ có khi là User Token


def _get(path: str, params: dict, api_version: str) -> dict:
    url = f"{GRAPH_HOST}/{api_version}/{path}"
    try:
        response = httpx.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except httpx.HTTPError as exc:
        raise TransientError(f"Lỗi mạng: {exc}") from exc

    body = response.json()
    if response.is_success:
        return body

    error = body.get("error", {})
    raise PermanentError(f"[{error.get('code')}] {error.get('message', 'lỗi không rõ')}")


def inspect_token(token: str, api_version: str = "v21.0") -> TokenInfo:
    """Xác định token thuộc loại nào và trả về thông tin kèm theo."""
    me = _get("me", {"fields": "id,name", "access_token": token}, api_version)
    info = TokenInfo(kind="unknown", id=str(me.get("id", "")), name=me.get("name", ""))

    # Chỉ User Token mới liệt kê được danh sách Page. Page Token gọi vào đây sẽ lỗi.
    try:
        accounts = _get(
            "me/accounts",
            {"fields": "id,name,access_token,tasks", "access_token": token},
            api_version,
        )
    except (PermanentError, TransientError):
        info.kind = "page"
        return info

    pages = accounts.get("data") or []
    if pages:
        info.kind = "user"
        info.pages = pages
    else:
        # Gọi được /me/accounts nhưng không quản trị Page nào.
        info.kind = "user"
    return info


def exchange_for_long_lived(
    token: str, app_id: str, app_secret: str, api_version: str = "v21.0"
) -> str:
    """Đổi token ngắn hạn sang token dài hạn (~60 ngày).

    Cần App ID và App Secret lấy ở developers.facebook.com > App > Settings > Basic.
    """
    body = _get(
        "oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": token,
        },
        api_version,
    )
    new_token = body.get("access_token")
    if not new_token:
        raise PermanentError(f"Facebook không trả về token mới: {body}")
    return str(new_token)


def upsert_env(path, values: dict[str, str]) -> None:
    """Ghi/cập nhật các biến trong .env, giữ nguyên phần còn lại của file."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)

    updated = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            updated.append(f"{key}={remaining.pop(key)}")
        else:
            updated.append(line)

    for key, value in remaining.items():
        updated.append(f"{key}={value}")

    path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    path.chmod(0o600)   # chứa token — không để người dùng khác trên máy đọc được
