#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  Kiểm tra trước khi chạy — máy chủ này đang chạy nhiều thứ khác
#
#  node-blockchain đang có: celestia-node, sp1-blobstream, orchestrator-relayer,
#  nitro/orbit, các stack dal-*. Chạy đè lên chúng là hỏng việc của người khác.
#
#      bash scripts/preflight.sh
# ═══════════════════════════════════════════════════════════════════════════
set -uo pipefail

BASE="${ENGRAM_PORT_BASE:-18000}"
PROJECT="${COMPOSE_PROJECT_NAME:-engram-sim}"
FAIL=0
LEFTOVER=0

say()  { printf "  %-52s %s\n" "$1" "$2"; }
ok()   { say "$1" "OK"; }
bad()  { say "$1" "XUNG ĐỘT"; FAIL=1; }

echo "═══ Kiểm tra trước khi chạy ═══"
echo
echo "── Cổng ──"
for spec in \
  "$((BASE+545)):anvil" \
  "$((BASE+658)):da-mock" \
  "$((BASE+101)):provider-a" \
  "$((BASE+102)):provider-b" \
  "$((BASE+201)):worker-1" \
  "$((BASE+202)):worker-2" \
  "$((BASE+301)):aggregator" \
  "$((BASE+401)):client" \
  "$((BASE+501)):watchtower"
do
  port="${spec%%:*}"; name="${spec##*:}"
  if ss -ltn 2>/dev/null | grep -q ":${port} " || netstat -ltn 2>/dev/null | grep -q ":${port} "; then
    bad "$name (cổng $port)"
  else
    ok "$name (cổng $port)"
  fi
done

echo
echo "── Cổng của dịch vụ NGƯỜI KHÁC, không được đụng ──"
for spec in "26658:celestia-node RPC" "26659:celestia gateway" "8545:EVM/anvil khác" \
            "8547:nitro http" "9944:avail"; do
  port="${spec%%:*}"; name="${spec##*:}"
  if ss -ltn 2>/dev/null | grep -q ":${port} "; then
    say "$name (cổng $port)" "đang chạy — ĐÃ TRÁNH"
  else
    say "$name (cổng $port)" "trống"
  fi
done

echo
echo "── Tên container và mạng Docker ──"
#
# PHẢI phân biệt CỦA MÌNH TỪ LẦN TRƯỚC với CỦA NGƯỜI KHÁC.
#
# Bản trước gộp làm một và báo XUNG ĐỘT cho chính container của mình, nên sau
# lần chạy đầu là preflight chặn vĩnh viễn — mà `make sim` gọi preflight trước,
# thành ra chạy được đúng một lần rồi tắc. Dương tính giả còn tệ hơn không kiểm:
# nó dạy người dùng bỏ qua cảnh báo.
#
# Cách phân biệt: container do docker compose tạo mang nhãn
# com.docker.compose.project. Trùng nhãn nghĩa là của mình.
MINE=$(docker ps -aq --filter "label=com.docker.compose.project=${PROJECT}" 2>/dev/null | wc -l)
OTHERS=$(docker ps -a --format '{{.Names}}\t{{.Label "com.docker.compose.project"}}' 2>/dev/null \
         | awk -F'\t' -v p="${PROJECT}" '$1 ~ "^"p"-" && $2 != p' | wc -l)

if [ "${OTHERS:-0}" -gt 0 ]; then
  bad "container tên ${PROJECT}-* nhưng KHÔNG phải của project này"
elif [ "${MINE:-0}" -gt 0 ]; then
  say "container ${PROJECT}-* ($MINE cái)" "của lần chạy trước"
  LEFTOVER=1
else
  ok "container tiền tố ${PROJECT}-"
fi

NET_OWNER=$(docker network inspect "${PROJECT}_engram" \
            --format '{{index .Labels "com.docker.compose.project"}}' 2>/dev/null)
if [ -z "$NET_OWNER" ]; then
  ok "mạng ${PROJECT}_engram"
elif [ "$NET_OWNER" = "${PROJECT}" ]; then
  say "mạng ${PROJECT}_engram" "của lần chạy trước"
  LEFTOVER=1
else
  bad "mạng ${PROJECT}_engram thuộc project khác ($NET_OWNER)"
fi

echo
echo "── Thư mục ──"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
say "cài tại" "$HERE"
if [ "$(basename "$HERE")" = "engram" ] && [ -d "$HERE/../engram/.git" ]; then
  bad "trùng tên với repo engram đã có"
else
  ok "không trùng ~/engram (repo cũ)"
fi

echo
echo "── Tài nguyên ──"
FREE_G=$(df -BG --output=avail "$HERE" 2>/dev/null | tail -1 | tr -dc '0-9')
say "đĩa trống" "${FREE_G:-?} GiB (cần ~3 GiB cho ảnh Docker)"
[ "${FREE_G:-0}" -lt 3 ] && FAIL=1
MEM_G=$(free -g 2>/dev/null | awk '/^Mem:/{print $7}')
say "RAM khả dụng" "${MEM_G:-?} GiB (cần ~2 GiB)"

echo
echo "── Việc của NGƯỜI KHÁC trên máy này — KHÔNG ĐỤNG ──"
FOUND=0
for d in celestia-node sp1-blobstream orchestrator-relayer celestia_client engram; do
  if [ -e "$HOME/$d" ]; then say "~/$d" "có — KHÔNG dùng lại"; FOUND=1; fi
done
if [ "$FOUND" -eq 1 ]; then
  echo
  echo "    Số đo phụ thuộc cấu hình của người khác thì KHÔNG mô tả lại được"
  echo "    trong bài báo, và chạy đè lên là phá việc họ. Dựng riêng mọi thứ."
  echo "    Xem docs/HUONG_DAN.md — nguyên tắc cô lập hoàn toàn."
fi

echo
if [ "$FAIL" -ne 0 ]; then
  echo "  ✗ XUNG ĐỘT THẬT — thứ của người khác đang chiếm chỗ."
  echo
  echo "    Đổi cổng:"
  echo "      ENGRAM_PORT_ANVIL=19545 ENGRAM_PORT_DAMOCK=19658 \\"
  echo "      ENGRAM_PORT_PROV_A=19101 ENGRAM_PORT_PROV_B=19102 \\"
  echo "      ENGRAM_PORT_WORK_1=19201 ENGRAM_PORT_WORK_2=19202 \\"
  echo "      ENGRAM_PORT_AGG=19301 ENGRAM_PORT_CLIENT=19401 \\"
  echo "      ENGRAM_PORT_WATCH=19501 make sim"
  echo
  echo "    Hoặc đổi tên project:"
  echo "      COMPOSE_PROJECT_NAME=engram-sim2 make sim"
  exit 1
fi

if [ "${LEFTOVER:-0}" -ne 0 ]; then
  echo "  ✓ Không xung đột với ai. Còn dấu vết lần chạy trước của CHÍNH MÌNH."
  echo "    Không sao — docker compose sẽ dựng lại. Muốn sạch hẳn thì:  make down"
else
  echo "  ✓ Không xung đột. Chạy được:  make check"
fi
exit 0
