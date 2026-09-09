"""Thông số chạy sửa được từ màn hình web, đè lên config/sources.yaml.

VÌ SAO KHÔNG GHI THẲNG VÀO sources.yaml: file đó nằm trong ảnh Docker và được gắn vào
container ở chế độ chỉ đọc. Cho web ghi đè file cấu hình còn kéo theo hai rắc rối nữa:
ba container đọc cùng lúc dễ vớ phải file ghi dở, và mọi sửa đổi bị mất khi cập nhật ảnh.

Nên chỗ này lưu trong SQLite — cùng nơi với dữ liệu, cùng vòng đời sao lưu, ba container
đều thấy ngay lượt chạy sau mà không phải khởi động lại.

sources.yaml vẫn là GIÁ TRỊ MẶC ĐỊNH: xoá một dòng trong bảng setting là quay về đúng
giá trị trong file, không cần nhớ số cũ là bao nhiêu.
"""

import sqlite3
from dataclasses import dataclass, replace

from .config import Config, load_config


@dataclass(frozen=True)
class Spec:
    """Mô tả một thông số: đủ để dựng ô nhập trên web và để kiểm tra giá trị nhập vào."""

    key: str
    label: str
    unit: str
    minimum: int
    maximum: int
    hint: str


# Chỉ mở ra những thông số ảnh hưởng tới NHỊP chạy. Danh sách nguồn RSS, từ khoá chặn,
# hashtag... vẫn nằm ở sources.yaml: sửa chúng cần đọc cả ngữ cảnh, không hợp với
# một ô nhập số trên web.
SPECS: tuple[Spec, ...] = (
    Spec("crawl_every_hours", "Kéo RSS mỗi", "giờ", 1, 24,
         "Bao lâu đi lấy tin mới một lần. Đặt dày quá thì báo chưa kịp ra tin mới."),
    Spec("daily_quota", "Số bài mỗi ngày", "bài", 1, 40,
         "Tổng số bài đăng trong một ngày, rải đều trong khung giờ hoạt động."),
    Spec("min_gap_minutes", "Cách nhau tối thiểu", "phút", 5, 720,
         "Hai bài liên tiếp phải cách nhau ít nhất ngần này. Đăng dồn dễ bị coi là spam."),
    Spec("per_sport_quota", "Tối đa mỗi môn", "bài", 1, 20,
         "Để bóng đá không chiếm hết suất trong ngày."),
    Spec("active_start_hour", "Bắt đầu đăng lúc", "giờ", 0, 23,
         "Giờ Việt Nam. Trước giờ này hệ thống không đăng gì."),
    Spec("active_end_hour", "Ngừng đăng lúc", "giờ", 1, 24,
         "Giờ Việt Nam. Phải lớn hơn giờ bắt đầu."),
    Spec("max_age_hours", "Chỉ nhận tin mới hơn", "giờ", 1, 168,
         "Tin cũ hơn ngần này bị bỏ ngay lúc crawl. Tin thể thao mất giá rất nhanh."),
    Spec("max_summary_words", "Độ dài phần trích", "từ", 10, 200,
         "Số từ tối đa trích từ bài gốc. Trích nhiều quá là chép nội dung của báo."),
    Spec("retention_days", "Giữ dữ liệu", "ngày", 1, 60,
         "Xoá tin cũ hơn ngần này. Ổ đĩa của box nhỏ, đừng để quá dài."),
)

_BY_KEY = {spec.key: spec for spec in SPECS}


class InvalidSetting(ValueError):
    """Giá trị nhập không hợp lệ — trả về cho người dùng, không ghi vào DB."""


def load_overrides(conn: sqlite3.Connection) -> dict[str, int]:
    """Đọc các thông số đã sửa. Khoá lạ (còn sót từ bản cũ) bị bỏ qua, không làm hỏng app."""
    rows = conn.execute("SELECT key, value FROM setting").fetchall()
    values: dict[str, int] = {}
    for row in rows:
        if row["key"] not in _BY_KEY:
            continue
        try:
            values[row["key"]] = int(row["value"])
        except (TypeError, ValueError):
            continue
    return values


def validate(key: str, raw: str | int) -> int:
    spec = _BY_KEY.get(key)
    if spec is None:
        raise InvalidSetting(f"Không có thông số '{key}'")
    try:
        value = int(str(raw).strip())
    except ValueError:
        raise InvalidSetting(f"{spec.label}: phải là số nguyên") from None
    if not (spec.minimum <= value <= spec.maximum):
        raise InvalidSetting(
            f"{spec.label}: phải trong khoảng {spec.minimum}–{spec.maximum} {spec.unit}"
        )
    return value


def save_overrides(conn: sqlite3.Connection, raw: dict[str, str], now_iso: str) -> None:
    """Kiểm TẤT CẢ giá trị trước khi ghi bất kỳ giá trị nào.

    Ghi từng cái một rồi mới phát hiện cái cuối sai sẽ để lại cấu hình nửa cũ nửa mới —
    kiểu lỗi rất khó truy vì mỗi thông số nhìn riêng đều hợp lệ.
    """
    checked = {key: validate(key, value) for key, value in raw.items() if key in _BY_KEY}

    start = checked.get("active_start_hour")
    end = checked.get("active_end_hour")
    if start is not None and end is not None and end <= start:
        raise InvalidSetting("Giờ ngừng đăng phải lớn hơn giờ bắt đầu")

    for key, value in checked.items():
        conn.execute(
            "INSERT INTO setting (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_at = excluded.updated_at",
            (key, str(value), now_iso),
        )
    conn.commit()


def reset(conn: sqlite3.Connection) -> None:
    """Xoá hết phần đè, quay về đúng giá trị trong config/sources.yaml."""
    conn.execute("DELETE FROM setting")
    conn.commit()


def apply_overrides(config: Config, overrides: dict[str, int]) -> Config:
    """Trả về một Config MỚI đã áp thông số sửa. Không đụng vào bản gốc.

    Config là frozen dataclass nên phải dựng lại bằng replace() — cố ý như vậy để
    không có chỗ nào lén sửa cấu hình đang dùng giữa chừng một lượt chạy.
    """
    if not overrides:
        return config

    schedule = replace(
        config.schedule,
        crawl_every_hours=overrides.get(
            "crawl_every_hours", config.schedule.crawl_every_hours),
        min_gap_minutes=overrides.get(
            "min_gap_minutes", config.schedule.min_gap_minutes),
        active_hours=[
            overrides.get("active_start_hour", config.schedule.start_hour),
            overrides.get("active_end_hour", config.schedule.end_hour),
        ],
    )
    post = replace(
        config.post,
        daily_quota=overrides.get("daily_quota", config.post.daily_quota),
        per_sport_quota=overrides.get("per_sport_quota", config.post.per_sport_quota),
        max_summary_words=overrides.get(
            "max_summary_words", config.post.max_summary_words),
    )
    crawl = replace(
        config.crawl,
        max_age_hours=overrides.get("max_age_hours", config.crawl.max_age_hours),
    )
    return replace(
        config, schedule=schedule, post=post, crawl=crawl,
        retention_days=overrides.get("retention_days", config.retention_days),
    )


def current_values(config: Config) -> dict[str, int]:
    """Giá trị đang thực sự có hiệu lực, để đổ vào form trên web."""
    return {
        "crawl_every_hours": config.schedule.crawl_every_hours,
        "daily_quota": config.post.daily_quota,
        "min_gap_minutes": config.schedule.min_gap_minutes,
        "per_sport_quota": config.post.per_sport_quota,
        "active_start_hour": config.schedule.start_hour,
        "active_end_hour": config.schedule.end_hour,
        "max_age_hours": config.crawl.max_age_hours,
        "max_summary_words": config.post.max_summary_words,
        "retention_days": config.retention_days,
    }


def effective_config(conn: sqlite3.Connection) -> Config:
    """Cấu hình dùng cho một lượt chạy: sources.yaml + phần đè từ DB.

    Đọc lại ở MỖI lượt chứ không nhớ sẵn: sửa thông số trên web xong phải có hiệu lực
    ngay lượt sau, không phải khởi động lại ba container.
    """
    return apply_overrides(load_config(), load_overrides(conn))
