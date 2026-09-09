"""Kiểu dữ liệu chung cho mọi nguồn bóng đá.

Premier League và UEFA trả JSON hoàn toàn khác nhau. Quy về mấy kiểu dưới đây ngay
tại lớp client, để phần dựng bài và vẽ card không phải biết dữ liệu đến từ đâu —
thêm giải mới sau này chỉ là viết thêm một client.

Mọi mốc thời gian giữ ở UTC. Đổi sang giờ Việt Nam chỉ làm ở lúc hiển thị
(vn_time), không lưu giờ địa phương vào đâu cả — lưu rồi thì không biết nó đã đổi
múi giờ hay chưa.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

VN_TIMEZONE = timezone(timedelta(hours=7))


@dataclass(frozen=True)
class Fixture:
    """Một trận đấu, dùng cho cả lịch thi đấu lẫn kết quả."""

    id: str
    league: str                      # tên hiển thị: "Ngoại hạng Anh"
    kickoff: datetime                # UTC
    home: str
    away: str
    home_score: int | None = None
    away_score: int | None = None
    finished: bool = False
    round_label: str = ""            # "Vòng 5" / "Lượt 1"
    # Tên rút gọn do nguồn cung cấp ("Man Utd" thay vì "Manchester United").
    # Card bảng rất hẹp: để tên đầy đủ thì "Brighton & Hove Albion" bị cắt thành
    # "Brighton & Ho…" — mất luôn thông tin. Rỗng thì rơi về tên đầy đủ.
    home_short: str = ""
    away_short: str = ""
    home_crest: str = ""             # URL logo, rỗng thì card vẽ không logo
    away_crest: str = ""

    @property
    def home_name(self) -> str:
        return self.home_short or self.home

    @property
    def away_name(self) -> str:
        return self.away_short or self.away

    @property
    def vn_weekday(self) -> str:
        thu = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
        return thu[self.kickoff.astimezone(VN_TIMEZONE).weekday()]

    @property
    def vn_time(self) -> str:
        return self.kickoff.astimezone(VN_TIMEZONE).strftime("%H:%M")

    @property
    def vn_date(self) -> str:
        return self.kickoff.astimezone(VN_TIMEZONE).strftime("%d/%m")

    @property
    def score_line(self) -> str:
        if not self.finished or self.home_score is None:
            return f"{self.home} vs {self.away}"
        return f"{self.home} {self.home_score} - {self.away_score} {self.away}"

    @property
    def short_score_line(self) -> str:
        if not self.finished or self.home_score is None:
            return f"{self.home_name} – {self.away_name}"
        return f"{self.home_name} {self.home_score}-{self.away_score} {self.away_name}"

    def starts_within(self, now: datetime, minutes: int) -> bool:
        """Còn đúng ngần này phút nữa là đá — mốc để đăng bài đội hình."""
        left = (self.kickoff - now).total_seconds() / 60
        return 0 <= left <= minutes

    def just_ended(self, now: datetime, after: int, within: int) -> bool:
        """Trận VỪA kết thúc: đã qua `after` phút nhưng chưa quá `within` phút.

        Cận dưới: API cập nhật tỉ số trễ vài phút, đăng ngay tiếng còi mãn cuộc là ra
        bài thiếu bàn thắng phút bù giờ.

        Cận TRÊN mới là chỗ quan trọng. Thiếu nó thì mọi trận đã đá trong lịch sử đều
        thoả điều kiện — lần chạy đầu tiên sinh ra 20 bài kết quả của các vòng trước,
        đăng lên Fanpage thành một tràng tin cũ.
        """
        gone = (now - self.kickoff).total_seconds() / 60
        return self.finished and after <= gone <= within


@dataclass(frozen=True)
class Standing:
    """Một dòng trong bảng xếp hạng."""

    position: int
    team: str
    played: int
    points: int
    goal_diff: int = 0
    form: str = ""                   # "WWDLW", rỗng nếu nguồn không có
    crest: str = ""                  # URL logo đội


@dataclass(frozen=True)
class Lineup:
    """Đội hình ra sân của một đội."""

    team: str
    formation: str                   # "4-2-3-1", rỗng nếu nguồn không có
    crest: str = ""
    starters: list[str] = field(default_factory=list)


class SourceUnavailable(RuntimeError):
    """Nguồn không gọi được lúc này.

    Cả hai nguồn đều là API nội bộ của premierleague.com và uefa.com — không phải
    API công bố chính thức, có thể đổi hoặc chặn bất kỳ lúc nào mà không báo.
    Mọi client phải gói lỗi mạng và lỗi phân tích dữ liệu vào đây, để lượt chạy chỉ
    bỏ qua bài bóng đá chứ không làm chết cả tiến trình đăng bài.
    """
