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
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${PROJECT}-"; then
  bad "container tiền tố ${PROJECT}-"
else
  ok "container tiền tố ${PROJECT}-"
fi
if docker network ls --format '{{.Name}}' 2>/dev/null | grep -qx "${PROJECT}_engram"; then
  bad "mạng ${PROJECT}_engram"
else
  ok "mạng ${PROJECT}_engram"
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
echo "── Thứ CÓ SẴN trên máy này, dùng lại được ──"
for d in celestia-node sp1-blobstream orchestrator-relayer celestia_client; do
  [ -d "$HOME/$d" ] && say "$d" "có — dùng cho giai đoạn 2/3" || say "$d" "không thấy"
done

echo
if [ "$FAIL" -eq 0 ]; then
  echo "  ✓ Không xung đột. Chạy được:  make check"
else
  echo "  ✗ Có xung đột. Đổi ENGRAM_PORT_BASE hoặc COMPOSE_PROJECT_NAME rồi chạy lại."
  echo "    ví dụ:  ENGRAM_PORT_BASE=19000 bash scripts/preflight.sh"
fi
exit $FAIL
