"""Đọc cấu hình từ config/sources.yaml."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "sources.yaml"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    sport: str
    lang: str
    enabled: bool = True


@dataclass(frozen=True)
class CrawlSettings:
    max_age_hours: int = 24
    max_items_per_feed: int = 120
    request_timeout_seconds: int = 15
    user_agent: str = "AutoFB/0.1"


@dataclass(frozen=True)
class PostSettings:
    max_summary_words: int = 55
    daily_quota: int = 5
    per_sport_quota: int = 2
    default: dict = field(default_factory=dict)
    by_sport: dict[str, dict] = field(default_factory=dict)

    def style_for(self, sport: str) -> dict:
        """Giọng bài theo môn, thiếu thì lấy mặc định."""
        return self.by_sport.get(sport) or self.default


@dataclass(frozen=True)
class CardSettings:
    """Ảnh card tiêu đề đăng kèm mỗi bài.

    Kích thước mặc định 1080x1350 (tỉ lệ 4:5) — khổ dọc cao nhất Facebook hiển thị
    trên feed điện thoại mà không cắt ảnh. Để 1:1 thì bài chiếm ít chiều cao hơn,
    người lướt dễ trôi qua.
    """

    enabled: bool = True
    width: int = 1080
    height: int = 1350
    max_lines: int = 7
    max_font_size: int = 96
    min_font_size: int = 44
    text_color: str = "#FFFFFF"
    brand: str = ""
    gradients: list[list[str]] = field(default_factory=lambda: list(DEFAULT_GRADIENTS))


# Bộ gradient mặc định. Đều là màu đậm để chữ trắng luôn đọc được — đừng thêm màu
# nhạt (vàng chanh, xanh mint) nếu không đổi luôn text_color.
DEFAULT_GRADIENTS = [
    ["#E8365D", "#B0175F"],   # hồng đỏ
    ["#1E3C72", "#2A5298"],   # xanh dương đậm
    ["#134E5E", "#12805C"],   # xanh lá rừng
    ["#42275A", "#734B6D"],   # tím khói
    ["#C31432", "#240B36"],   # đỏ rượu
    ["#0F2027", "#2C5364"],   # xám xanh đêm
    ["#F12711", "#C6410A"],   # cam lửa
    ["#141E30", "#243B55"],   # navy
]


@dataclass(frozen=True)
class ScheduleSettings:
    active_hours: list[int] = field(default_factory=lambda: [7, 22])
    min_gap_minutes: int = 45
    crawl_every_hours: int = 2

    @property
    def start_hour(self) -> int:
        return self.active_hours[0]

    @property
    def end_hour(self) -> int:
        return self.active_hours[1]


@dataclass(frozen=True)
class Config:
    crawl: CrawlSettings
    sources: list[Source]
    post: PostSettings = field(default_factory=PostSettings)
    schedule: ScheduleSettings = field(default_factory=ScheduleSettings)
    card: CardSettings = field(default_factory=CardSettings)
    retention_days: int = 3
    blocked_keywords: list[str] = field(default_factory=list)
    affiliate_links: dict[str, list[str]] = field(default_factory=dict)

    @property
    def enabled_sources(self) -> list[Source]:
        return [s for s in self.sources if s.enabled]

    def links_for_sport(self, sport: str) -> list[str]:
        return self.affiliate_links.get(sport, [])


def load_config(path: Path | str | None = None) -> Config:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file cấu hình: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    crawl = CrawlSettings(**(raw.get("crawl") or {}))

    sources = []
    for index, item in enumerate(raw.get("sources") or []):
        missing = {"name", "url", "sport", "lang"} - item.keys()
        if missing:
            raise ValueError(f"sources[{index}] thiếu trường: {', '.join(sorted(missing))}")
        sources.append(Source(**item))

    if not sources:
        raise ValueError("Cấu hình không có nguồn nào")

    return Config(
        crawl=crawl,
        sources=sources,
        post=PostSettings(**(raw.get("post") or {})),
        schedule=ScheduleSettings(**(raw.get("schedule") or {})),
        card=CardSettings(**(raw.get("card") or {})),
        retention_days=int(raw.get("retention_days", 3)),
        blocked_keywords=raw.get("blocked_keywords") or [],
        affiliate_links=raw.get("affiliate_links") or {},
    )
