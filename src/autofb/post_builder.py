"""M4 — dựng nội dung bài đăng từ một nhóm tin.

THIẾT KẾ QUAN TRỌNG: đây là interface một hàm `build(cluster, articles) -> str`.
MVP chỉ có TemplateBuilder (ghép theo mẫu, không dùng LLM). Phase 2 thêm LLMBuilder
cùng interface là xong — M3, M5, M6, M7 không phải sửa gì.

Đừng để logic dựng bài rò ra chỗ khác, nếu không việc cắm LLM sau này thành refactor lớn.
"""

from typing import Protocol

from .config import PostSettings
from .text_utils import clean_summary, truncate_words


class PostBuilder(Protocol):
    def build(self, cluster: dict, articles: list[dict]) -> str: ...


class TemplateBuilder:
    """Ghép bài theo khuôn cố định từ dữ liệu RSS.

    Không viết lại nội dung — chỉ trích tóm tắt có giới hạn độ dài và dẫn nguồn rõ ràng.
    Bài sẽ khô hơn bài do người (hoặc LLM) viết; đó là lý do màn hình duyệt cho sửa trực tiếp.
    """

    def __init__(self, settings: PostSettings):
        self.settings = settings

    def build(self, cluster: dict, articles: list[dict]) -> str:
        primary = articles[0]
        style = self.settings.style_for(cluster["sport"])

        blocks = [primary["title"].strip()]

        summary = truncate_words(
            clean_summary(primary.get("summary", "")), self.settings.max_summary_words
        )
        if summary:
            blocks.append(summary)

        cta = style.get("cta")
        if cta:
            blocks.append(cta)

        # Một dòng nguồn là đủ: ảnh và chữ đều lấy từ cùng bài gốc, ghi thêm "Ảnh: ..."
        # chỉ lặp lại đúng cái tên vừa ghi.
        blocks.append(self._source_line(articles))

        hashtags = style.get("hashtags") or []
        if hashtags:
            blocks.append(" ".join(f"#{tag}" for tag in hashtags))

        return "\n\n".join(blocks)

    @staticmethod
    def _source_line(articles: list[dict]) -> str:
        """Ghi ĐÚNG một nguồn: tờ báo mà bài này lấy chữ ra.

        Trước đây liệt kê mọi báo trong nhóm tin, nhưng nội dung đăng chỉ trích từ bài
        chính — ghi thêm hai tờ không đóng góp chữ nào là ghi sai công trạng.
        Việc nhiều báo cùng đưa tin vẫn dùng được, nhưng chỉ để xếp thứ tự ưu tiên ở M3.

        Ghi dạng chữ chứ không phải link: bài có link ra ngoài bị bóp phân phối.
        """
        return f"Nguồn: {articles[0]['source_name']}"
