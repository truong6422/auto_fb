# Ảnh dùng chung cho cả ba container (web, crawler, publisher). Chỉ khác lệnh chạy.
# Gộp một ảnh vì cả ba dùng chung y hệt bộ code và thư viện — tách ra là phải build
# ba lần, kéo ba lần, mà box chỉ có 1,8GB RAM và ổ USB ghi 2,9 MB/s.
#
# Pin đúng 3.12: box đang chạy Python 3.14, Pillow chưa chắc có sẵn wheel aarch64 cho
# bản đó. Không có wheel thì pip build từ mã nguồn, trên CPU A53 mất hàng tiếng.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Ho_Chi_Minh

WORKDIR /app

# Cài thư viện trước, chép code sau: sửa code không làm mất lớp cache đã cài pip.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cli.py ./
COPY src/ ./src/
COPY config/ ./config/
COPY assets/ ./assets/

# Ổ chứa DB. Khai VOLUME để `docker run` không có -v cũng không ghi vào lớp ảnh
# (ghi vào lớp ảnh là mất sạch dữ liệu mỗi lần cập nhật phiên bản).
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# Chạy dưới người dùng thường: container này mở ra internet qua Cloudflare Tunnel.
RUN useradd --system --uid 10001 --home /app autofb && chown -R autofb:autofb /app
USER autofb

EXPOSE 8080

# Healthcheck bằng Python chứ không phải curl — bản slim không có curl, thêm vào
# chỉ để healthcheck là tốn thêm mấy MB ảnh phải kéo qua đường truyền chậm.
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5).status == 200 else 1)"

CMD ["python", "cli.py", "serve", "--port", "8080"]
