#!/usr/bin/env bash
# Ai đang giữ một cổng? Chạy: bash scripts/whoholds.sh 18201
PORT="${1:?dùng: bash scripts/whoholds.sh <cổng>}"
echo "═══ Ai giữ cổng $PORT ═══"
echo
echo "── Container Docker công bố cổng này ──"
docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null \
  | grep ":${PORT}->" || echo "  (không có)"
echo
echo "── Socket đang lắng nghe ──"
ss -ltnp 2>/dev/null | grep ":${PORT} " || echo "  (không có — hoặc cần sudo để thấy tên tiến trình)"
echo
echo "── Nếu là container cũ của mình ──"
echo "    make down     # dừng và dọn project engram-sim"
echo "    make reset    # dọn rồi chạy lại"
