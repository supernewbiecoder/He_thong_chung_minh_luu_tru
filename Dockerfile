# ═══════════════════════════════════════════════════════════════════════════
#  Dockerfile chung cho MỌI dịch vụ Python của Engram
#
#  VÌ SAO MỘT TỆP CHO TẤT CẢ: mỗi thư mục là một hệ thống độc lập, nhưng chúng
#  cùng nền Python và cùng phụ thuộc engram-common. Một Dockerfile tham số hoá
#  bằng build arg tránh phải đồng bộ bảy tệp gần giống nhau — mà lệch phiên bản
#  giữa các tệp đó chính là loại lỗi Docker sinh ra để tránh.
#
#  Xây:   docker build --build-arg SERVICE=provider -t engram/provider .
#  Chạy:  docker run engram/provider
# ═══════════════════════════════════════════════════════════════════════════

FROM python:3.11-slim AS base

# Ghim phiên bản pip để hai lần xây cách nhau vài tháng vẫn ra cùng kết quả.
ARG PIP_VERSION=24.0
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir "pip==${PIP_VERSION}"

WORKDIR /app

# ── Lớp 1: thư viện dùng chung ────────────────────────────────────────────
# Cài trước và tách lớp, nên sửa mã dịch vụ không phải cài lại phụ thuộc.
COPY common/pyproject.toml /app/common/
COPY common/src /app/common/src
RUN pip install --no-cache-dir -e /app/common

# ── Lớp 2: dịch vụ cụ thể ─────────────────────────────────────────────────
ARG SERVICE
RUN test -n "$SERVICE" || (echo "THIEU build-arg SERVICE" && exit 1)

COPY ${SERVICE}/pyproject.toml /app/${SERVICE}/
RUN pip install --no-cache-dir -e /app/${SERVICE} || true

COPY ${SERVICE}/ /app/${SERVICE}/
RUN pip install --no-cache-dir -e /app/${SERVICE}

# Ghi tên dịch vụ vào ảnh để entrypoint biết chạy gì mà không cần truyền lại.
ENV ENGRAM_SERVICE=${SERVICE}
ENV PYTHONPATH=/app/common/src:/app/${SERVICE}/src

# Không chạy bằng root.
RUN useradd --create-home --uid 10001 engram && chown -R engram:engram /app
USER engram

# [SPEC §C.2.1] Mọi dịch vụ mở cổng HTTP 8080 bên trong mạng nội bộ.
# docker-compose ánh xạ ra cổng khác nhau ở ngoài.
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,os,sys; \
        urllib.request.urlopen('http://127.0.0.1:8080/v1/health', timeout=2)" || exit 1

ENTRYPOINT ["sh", "-c", "python -m ${ENGRAM_SERVICE}"]
