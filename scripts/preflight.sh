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
#
# ── PHẢI CHỈ ĐÍCH DANH AI GIỮ CỔNG ────────────────────────────────────────
#
# Bản trước chỉ hỏi "cổng có bận không" rồi kết luận "của người khác". Sai, vì
# thủ phạm thường gặp nhất là CONTAINER CŨ CỦA CHÍNH MÌNH từ lần chạy hỏng —
# nó vẫn đang giữ cổng. Kết luận không có bằng chứng thì vô dụng, và tệ hơn là
# nó gửi người dùng đi đổi cổng trong khi chỉ cần `make down`.
#
# Ba nguồn có thể giữ cổng, phân biệt được cả ba:
#   ① container của project này  → dấu vết lần trước, compose sẽ dựng lại
#   ② container của project khác → xung đột thật
#   ③ tiến trình thường          → xung đột thật, in luôn tên tiến trình

port_owner() {
  local port="$1" c pr
  c=$(docker ps --filter "label=com.docker.compose.project=${PROJECT}" \
        --format '{{.Names}}|{{.Ports}}' 2>/dev/null | grep ":${port}->" | cut -d'|' -f1 | head -1)
  [ -n "$c" ] && { echo "mine:$c"; return; }
  c=$(docker ps --format '{{.Names}}|{{.Ports}}' 2>/dev/null | grep ":${port}->" | cut -d'|' -f1 | head -1)
  [ -n "$c" ] && { echo "container:$c"; return; }
  pr=$(ss -ltnp 2>/dev/null | grep ":${port} " | sed -n 's/.*users:((\"\([^\"]*\)\".*/\1/p' | head -1)
  [ -n "$pr" ] && { echo "process:$pr"; return; }
  echo "unknown:"
}

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
    owner="$(port_owner "$port")"
    who="${owner#*:}"
    case "${owner%%:*}" in
      mine)      say "$name (cổng $port)" "container cũ của mình: $who"; LEFTOVER=1 ;;
      container) bad "$name (cổng $port) ← container khác: $who" ;;
      process)   bad "$name (cổng $port) ← tiến trình: $who" ;;
      *)         bad "$name (cổng $port) ← không xác định được, chạy: sudo ss -ltnp | grep $port" ;;
    esac
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
echo "── Dấu vết Docker (chỉ báo, KHÔNG chặn) ──"
#
# ── VÌ SAO PHẦN NÀY KHÔNG BAO GIỜ ĐẶT FAIL=1 ──────────────────────────────
#
# `docker compose` TỰ XỬ LÝ container cũ của chính nó: nó dựng lại, không báo
# lỗi. Nên chặn `make sim` vì có container cũ là chặn một thứ không hỏng.
#
# Bản trước chặn, và sai hai lần liên tiếp:
#   ① so tên trần → tưởng container của chính mình là của người khác
#   ② `{{index .Labels "..."}}` trả "<no value>" khi nhãn thiếu, mà chuỗi đó
#      không rỗng và không bằng tên project → lại rơi vào nhánh "người khác"
#
# Thứ THẬT SỰ chặn được là CỔNG bị chiếm. Cái đó ở trên, và cái đó mới đặt FAIL.
# Phần này chỉ báo để biết mà dọn.

NAMED=$(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -c "^${PROJECT}-" || true)
MINE=$(docker ps -aq --filter "label=com.docker.compose.project=${PROJECT}" 2>/dev/null | wc -l)

if [ "${NAMED:-0}" -eq 0 ]; then
  ok "container ${PROJECT}-*"
elif [ "${NAMED:-0}" -eq "${MINE:-0}" ]; then
  say "container ${PROJECT}-* (${NAMED} cái)" "của lần chạy trước"
  LEFTOVER=1
else
  say "container ${PROJECT}-* (${NAMED} cái, ${MINE} của mình)" "kiểm bằng: docker ps -a"
  LEFTOVER=1
fi

if docker network ls --format '{{.Name}}' 2>/dev/null | grep -qx "${PROJECT}_engram"; then
  say "mạng ${PROJECT}_engram" "đã có, compose dùng lại"
  LEFTOVER=1
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
echo "── Thư mục kết quả ──"
#
# Lần chạy Docker trước khi có bản vá `user:` tạo ./results bằng ROOT. Sau đó
# người dùng không chmod được (không sở hữu), và mô phỏng hỏng ở bước ghi tệp.
# Bắt ở đây thì thấy trước khi chạy, thay vì sau khi đã chạy xong.
RES="$HERE/results"
if [ ! -e "$RES" ]; then
  ok "results/ (sẽ tạo khi chạy)"
elif [ -w "$RES" ]; then
  ok "results/ ghi được"
else
  OWNER=$(stat -c '%U' "$RES" 2>/dev/null || echo '?')
  bad "results/ KHÔNG ghi được — thuộc '$OWNER', bạn là '$(id -un)'"
  echo "        sudo chown -R \$(id -u):\$(id -g) $RES"
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
  echo "  ✗ CỔNG BỊ CHIẾM bởi thứ KHÔNG phải của project này — xem dòng có mũi tên ←"
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
  echo "  ✓ Không xung đột với ai khác. Container của lần chạy trước vẫn còn."
  echo "    compose sẽ dựng lại chúng. Muốn sạch hẳn:  make reset"
else
  echo "  ✓ Không xung đột. Chạy được:  make check"
fi
exit 0
