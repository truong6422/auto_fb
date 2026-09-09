"""Vẽ ảnh "card tiêu đề": nền gradient + tiêu đề chữ to, để người lướt feed đọc được ngay.

VÌ SAO PHẢI TỰ VẼ: bài nền màu (cái bảng chọn màu trong trình soạn thảo Facebook) là
tính năng của giao diện web, Graph API KHÔNG có tham số tương ứng. Cách duy nhất làm
được bằng bot là tự render một ảnh trông y như vậy rồi đăng như ảnh thường.

Card này đăng kèm ảnh gốc của báo thành bài 2 ảnh — xem publisher.publish_one().

Trả về bytes PNG, KHÔNG ghi ra đĩa: box chạy trên USB ghi chỉ 2,9 MB/s, mọi thứ ghi
được thì tránh. Ảnh sống trong RAM đúng lúc upload rồi bị thu hồi.
"""

from __future__ import annotations

import io
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import PROJECT_ROOT, CardSettings

FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"
TITLE_FONT = FONTS_DIR / "BeVietnamPro-ExtraBold.ttf"
LABEL_FONT = FONTS_DIR / "BeVietnamPro-Bold.ttf"

# Lề trái/phải tính theo phần trăm chiều rộng để đổi kích thước card không phải chỉnh tay.
_SIDE_MARGIN_RATIO = 0.09
_TOP_BAND_RATIO = 0.10      # chỗ dành cho dòng thương hiệu
_BOTTOM_BAND_RATIO = 0.10   # chỗ dành cho dòng nguồn


class FontMissingError(RuntimeError):
    """Thiếu file font — không tự ý rơi về font mặc định của Pillow.

    Font mặc định là bitmap, không có dấu tiếng Việt: 'Công Phượng' sẽ ra 'C ng Ph ng'.
    Thà hỏng to và báo lỗi còn hơn đăng lên Page một tấm ảnh mất dấu.
    """


def _load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FontMissingError(f"Không tìm thấy font: {path}")
    return ImageFont.truetype(str(path), size)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _gradient(size: tuple[int, int], top: str, bottom: str) -> Image.Image:
    """Nền chuyển màu dọc.

    Dựng trên dải 1 pixel bề ngang rồi phóng to: CPU A53 của box rất yếu, vẽ từng pixel
    trên 1080x1350 (1,4 triệu pixel) bằng Python mất vài giây, cách này mất vài mili giây.
    """
    width, height = size
    start, end = _hex_to_rgb(top), _hex_to_rgb(bottom)
    strip = Image.new("RGB", (1, height))
    pixels = strip.load()
    for y in range(height):
        ratio = y / max(height - 1, 1)
        pixels[0, y] = tuple(
            round(start[i] + (end[i] - start[i]) * ratio) for i in range(3)
        )
    return strip.resize(size, Image.BILINEAR)


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    """Xuống dòng theo từ. textwrap không dùng được vì nó đếm ký tự, còn ở đây phải đếm
    chiều rộng thật: chữ 'i' và chữ 'M' rộng khác nhau rất xa."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_title(
    text: str, max_width: float, max_height: float, max_lines: int,
    size_range: tuple[int, int],
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Chọn cỡ chữ lớn nhất mà tiêu đề vẫn nằm gọn trong khung.

    Dò từ to xuống nhỏ thay vì tính công thức: chiều rộng chữ phụ thuộc từng ký tự,
    không có công thức đóng. Vòng lặp chạy tối đa vài chục lần, không đáng kể.
    """
    largest, smallest = size_range
    font = _load_font(TITLE_FONT, smallest)
    lines = _wrap(text, font, max_width)
    # Giãn dòng 1.32 chứ không phải 1.2 như chữ Latin: tiếng Việt chồng hai tầng dấu
    # ("tuyển", "ướ"), để sát là dấu mũ dòng dưới đâm vào dấu nặng dòng trên.
    line_gap = 1.32

    for size in range(largest, smallest - 1, -4):
        candidate = _load_font(TITLE_FONT, size)
        wrapped = _wrap(text, candidate, max_width)
        block_height = len(wrapped) * size * line_gap
        if len(wrapped) <= max_lines and block_height <= max_height:
            return candidate, wrapped, round(size * line_gap)

    # Không cỡ nào vừa: dùng cỡ nhỏ nhất và cắt bớt dòng thừa, thêm dấu "…".
    lines = _wrap(text, font, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(",;:") + "…"
    return font, lines, round(smallest * line_gap)


def _draw_centered(
    draw: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.FreeTypeFont,
    line_height: int, box: tuple[int, int, int, int], color: str,
) -> None:
    left, top, right, bottom = box
    block_height = len(lines) * line_height
    y = top + (bottom - top - block_height) / 2
    centre_x = (left + right) / 2

    for line in lines:
        width = font.getlength(line)
        x = centre_x - width / 2
        # Bóng đổ mờ: gradient sáng (vàng, cam) làm chữ trắng bị chìm nếu để trần.
        draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0, 70))
        draw.text((x, y), line, font=font, fill=color)
        y += line_height


def pick_gradient(settings: CardSettings, seed: int) -> tuple[str, str]:
    """Chọn gradient theo số thứ tự bài — xoay vòng đều, không dùng ngẫu nhiên.

    Ngẫu nhiên có thể ra hai bài liền nhau cùng màu, nhìn như đăng trùng. Xoay vòng
    thì hai bài cạnh nhau chắc chắn khác màu, và vẽ lại bài cũ vẫn ra đúng màu cũ.
    """
    palette = settings.gradients
    return tuple(palette[seed % len(palette)])  # type: ignore[return-value]


def render_card(
    title: str, settings: CardSettings, seed: int = 0,
    source_name: str | None = None,
) -> bytes:
    """Vẽ card và trả về PNG dạng bytes."""
    title = " ".join(title.split())
    if not title:
        raise ValueError("Card phải có tiêu đề")

    width, height = settings.width, settings.height
    top_color, bottom_color = pick_gradient(settings, seed)

    image = _gradient((width, height), top_color, bottom_color)
    draw = ImageDraw.Draw(image, "RGBA")

    margin = round(width * _SIDE_MARGIN_RATIO)
    top_band = round(height * _TOP_BAND_RATIO)
    bottom_band = round(height * _BOTTOM_BAND_RATIO)

    font, lines, line_height = _fit_title(
        title,
        max_width=width - margin * 2,
        max_height=height - top_band - bottom_band,
        max_lines=settings.max_lines,
        size_range=(settings.max_font_size, settings.min_font_size),
    )
    _draw_centered(
        draw, lines, font, line_height,
        (margin, top_band, width - margin, height - bottom_band),
        settings.text_color,
    )

    small = _load_font(LABEL_FONT, round(width * 0.028))
    if settings.brand:
        draw.text((margin, round(top_band * 0.45)), settings.brand.upper(),
                  font=small, fill=(255, 255, 255, 190))
    if source_name:
        label = f"Nguồn: {source_name}"
        draw.text((margin, height - round(bottom_band * 0.72)), label,
                  font=small, fill=(255, 255, 255, 175))

    buffer = io.BytesIO()
    # PNG optimize=True tốn nhiều CPU mà card chỉ có màu phẳng + chữ nên đã rất nhẹ sẵn.
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def title_of(content: str) -> str:
    """Tiêu đề của bài = dòng đầu tiên có chữ.

    Không thêm cột `title` vào bảng post: bài tự động đã dựng tiêu đề ở dòng đầu
    (post_builder), bài tự soạn thì dòng đầu cũng chính là câu người viết muốn nhấn.
    Thêm cột là thêm một chỗ nữa có thể lệch với nội dung thật.
    """
    for line in content.splitlines():
        line = line.strip()
        if line:
            return textwrap.shorten(line, width=220, placeholder="…")
    return ""
