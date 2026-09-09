"""Phân loại lỗi Graph API. Ba nhóm, ba cách xử lý khác hẳn nhau."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from autofb.facebook import (  # noqa: E402
    AuthError, FacebookClient, PermanentError, TransientError,
)


def classify(code, status=400):
    return FacebookClient._classify({"error": {"code": code, "message": "x"}}, status)


class TestPhanLoai:
    @pytest.mark.parametrize("code", [1, 2, 4, 17, 32, 341, 613])
    def test_loi_tam_thoi_thi_thu_lai(self, code):
        assert isinstance(classify(code), TransientError)

    def test_loi_5xx_luon_la_tam_thoi(self):
        assert isinstance(classify(999, status=503), TransientError)

    @pytest.mark.parametrize("code", [10, 102, 190, 200, 230, 299, 2500, 467])
    def test_loi_token_va_quyen_la_authError(self, code):
        """AuthError phải là nhóm riêng: publisher dừng cả lượt thay vì đánh dấu
        từng bài hỏng — nếu không, token hết hạn sẽ xoá sạch hàng chờ."""
        assert isinstance(classify(code), AuthError)

    def test_authError_van_la_permanentError(self):
        """Chỗ nào bắt PermanentError sẵn thì vẫn bắt được, không sót lỗi."""
        assert isinstance(classify(190), PermanentError)

    def test_loi_noi_dung_la_permanentError_thuong(self):
        error = classify(1500)
        assert isinstance(error, PermanentError) and not isinstance(error, AuthError)

    def test_ngoai_dai_quyen_khong_bi_gan_nham(self):
        """300 nằm ngoài dải 200–299, không được coi là lỗi quyền."""
        assert not isinstance(classify(300), AuthError)
