"""Trạng thái dừng khẩn cấp (kill switch).

Ghi ra file chứ không giữ trong RAM: tiến trình đăng bài theo lịch chạy tách khỏi web,
nên hai bên phải nhìn thấy cùng một trạng thái. Web restart cũng không mất trạng thái.
"""

from pathlib import Path

from ..config import PROJECT_ROOT

PAUSE_FILE = PROJECT_ROOT / "data" / "PAUSED"


class SystemState:
    @property
    def paused(self) -> bool:
        return PAUSE_FILE.exists()

    @paused.setter
    def paused(self, value: bool) -> None:
        PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if value:
            PAUSE_FILE.touch()
        elif PAUSE_FILE.exists():
            PAUSE_FILE.unlink()
