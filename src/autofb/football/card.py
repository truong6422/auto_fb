"""Vẽ card dạng bảng cho bài bóng đá: lịch thi đấu, bảng xếp hạng, đội hình.

Khác card tiêu đề ở chỗ nội dung là NHIỀU DÒNG có cấu trúc, không phải một câu.
Mỗi dòng gồm phần trái (tên đội, giờ) và phần phải (điểm, vị trí) căn về hai mép,
giữa là khoảng trống — mắt dò theo cột dễ hơn là đọc một chuỗi dài.

Kết quả trận thì KHÔNG dùng file này: "Arsenal 2-1 Chelsea" là một câu ngắn, card
tiêu đề sẵn có vẽ chữ to đẹp hơn bảng. Xem card_renderer.render_card().

Cùng nguyên tắc với card tiêu đề: trả bytes PNG, không ghi ra đĩa.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw

from ..card_renderer import LABEL_FONT, TITLE_FONT, gradient, load_font, pick_gradient
from ..config import CardSettings
from . import crest

# Tỉ lệ theo chiều rộng card, để đổi kích thước không phải chỉnh tay từng số.
_MARGIN = 0.075
_HEAD_TOP = 0.055
_MAX_ROWS = 14          # quá số này thì cắt bớt: 36 đội Champions League không vừa


@dataclass(frozen=True)
class Row:
    """Một dòng trong card. `right` để rỗng nếu dòng không có giá trị bên phải."""

    left: str
    right: str = ""
    dim: bool = False   # dòng phụ (ngày tháng, ghi chú) — chữ nhạt và nhỏ hơn
    icon: str = ""      # URL logo đội, vẽ trước phần chữ. Rỗng thì chỉ có chữ.


def render_table_card(
    heading: str, rows: list[Row], settings: CardSettings,
    seed: int = 0, subheading: str = "", footer: str = "",
) -> bytes:
    """Vẽ card gồm tiêu đề + danh sách dòng. Trả bytes PNG."""
    if not rows:
        raise ValueError("Card bảng phải có ít nhất một dòng")

    width, height = settings.width, settings.height
    top_color, bottom_color = pick_gradient(settings, seed)
    image = gradient((width, height), top_color, bottom_color)
    draw = ImageDraw.Draw(image, "RGBA")

    margin = round(width * _MARGIN)
    y = round(height * _HEAD_TOP)

    shown = _trim(rows[:_MAX_ROWS])
    y = _draw_heading(draw, heading, subheading, margin, y, width, settings)
    _draw_rows(draw, image, shown, margin, y, width, height, settings)

    if len(rows) > len(shown):
        _draw_note(draw, f"… và {len(rows) - len(shown)} dòng nữa",
                   margin, height, width, settings)
    elif footer:
        _draw_note(draw, footer, margin, height, width, settings)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def _trim(rows: list[Row]) -> list[Row]:
    """Bỏ các dòng phụ thừa ở cuối sau khi cắt bớt.

    Dòng phụ là tiêu đề ngày ("Thứ Ba 15/09"). Cắt đúng chỗ có thể để lại một tiêu
    đề ngày không còn trận nào bên dưới — nhìn như card bị lỗi.
    """
    while rows and rows[-1].dim:
        rows = rows[:-1]
    return rows


def _draw_heading(draw, heading: str, subheading: str, margin: int, y: int,
                  width: int, settings: CardSettings) -> int:
    """Tiêu đề căn trái, không căn giữa như card tiêu đề.

    Bảng bên dưới căn theo mép trái; tiêu đề căn giữa sẽ lệch khỏi trục đó và làm
    cả card trông xộc xệch.
    """
    size = round(width * 0.062)
    font = load_font(TITLE_FONT, size)

    # Tiêu đề dài thì thu nhỏ dần cho vừa một dòng — xuống dòng sẽ ăn mất chỗ của bảng.
    while font.getlength(heading) > width - margin * 2 and size > round(width * 0.032):
        size -= 3
        font = load_font(TITLE_FONT, size)

    draw.text((margin, y), heading, font=font, fill=settings.text_color)
    y += round(size * 1.28)

    if subheading:
        small = load_font(LABEL_FONT, round(width * 0.030))
        draw.text((margin, y), subheading, font=small, fill=(255, 255, 255, 190))
        y += round(width * 0.030 * 1.9)

    return y + round(width * 0.018)


def _draw_rows(draw, image, rows: list[Row], margin: int, top: int,
               width: int, height: int, settings: CardSettings) -> None:
    """Chia đều chiều cao còn lại cho các dòng, cỡ chữ theo đó mà co giãn.

    Tính theo chỗ trống thật thay vì cỡ chữ cố định: 5 trận và 12 đội dùng chung
    một hàm, cố định cỡ chữ thì một trong hai trường hợp sẽ tràn hoặc trống hoác.
    """
    bottom = height - round(height * 0.085)
    row_height = (bottom - top) / max(len(rows), 1)

    size = min(round(row_height * 0.46), round(width * 0.042))
    font = load_font(TITLE_FONT, size)
    dim_font = load_font(LABEL_FONT, round(size * 0.82))
    right_font = load_font(TITLE_FONT, size)

    for index, row in enumerate(rows):
        y = top + row_height * index
        text_y = y + (row_height - size * 1.25) / 2

        # Đường kẻ mảnh giữa các dòng, bỏ dòng đầu để không dính vào tiêu đề.
        if index:
            draw.line([(margin, y), (width - margin, y)], fill=(255, 255, 255, 38), width=2)

        left_font = dim_font if row.dim else font
        colour = (255, 255, 255, 175) if row.dim else settings.text_color

        # Logo đội vẽ trước, chữ lùi vào sau nó.
        x = margin
        if row.icon:
            logo = crest.load(row.icon, round(size * 1.15))
            if logo is not None:
                image.paste(logo, (x, round(y + (row_height - logo.height) / 2)), logo)
                x += logo.width + round(size * 0.42)

        available = width - margin - x - _right_width(row, right_font)
        draw.text((x, text_y), _fit(row.left, left_font, available),
                  font=left_font, fill=colour)

        if row.right:
            w = right_font.getlength(row.right)
            draw.text((width - margin - w, text_y), row.right,
                      font=right_font, fill=settings.text_color)


def _right_width(row: Row, font) -> float:
    return font.getlength(row.right) + 24 if row.right else 0


def _fit(text: str, font, max_width: float) -> str:
    """Cắt bớt chữ cho vừa bề ngang, thêm "…". Tên đội dài sẽ đè lên cột phải."""
    if font.getlength(text) <= max_width:
        return text
    while text and font.getlength(text + "…") > max_width:
        text = text[:-1]
    return text + "…"


def _draw_note(draw, text: str, margin: int, height: int,
               width: int, settings: CardSettings) -> None:
    font = load_font(LABEL_FONT, round(width * 0.026))
    draw.text((margin, height - round(height * 0.058)), text,
              font=font, fill=(255, 255, 255, 165))
