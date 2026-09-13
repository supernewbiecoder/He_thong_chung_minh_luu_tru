#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# ⑥ export_locks.sh — lấy Cargo.lock của guest và host ra khỏi ảnh Docker.
#
# VÌ SAO CẦN: verifier key phụ thuộc byte-với-byte vào tệp ELF của guest. Không
# có Cargo.lock thì cây phụ thuộc có thể giải khác đi ở lần build sau → ELF khác
# → programVKey khác → mọi giao dịch bị hợp đồng từ chối. Chính công cụ đo của
# dự án đã tự phát cảnh báo này ở mỗi lần chạy lớp 4:
#
#     ⚠ SP1 version NOT found in Cargo.lock — version drift risk HIGH
#
# Chạy:  ./sp1_verify/export_locks.sh
# Sau đó: git add sp1_verify/host/Cargo.lock sp1_verify/guest/Cargo.lock
# ═══════════════════════════════════════════════════════════════════════════
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

USER_TAG="${USER:-$(id -un)}"; USER_TAG="${USER_TAG//[^a-zA-Z0-9_.-]/_}"
IMAGE="${IMAGE:-engram-sp1-${USER_TAG}}"

die() { echo "❌ $*" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || die "không thấy docker"
docker image inspect "$IMAGE" >/dev/null 2>&1 \
    || die "chưa có ảnh $IMAGE — build trước bằng ./sp1_verify/run_sp1.sh build"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cid="$(docker create "$IMAGE")" || die "docker create thất bại"
found=0
for pair in "host" "guest"; do
    for src in "/build/sp1_verify/${pair}/Cargo.lock" \
               "/build/sp1_verify/${pair}/target/Cargo.lock"; do
        if docker cp "$cid:$src" "$tmp/${pair}.lock" 2>/dev/null; then
            cp "$tmp/${pair}.lock" "sp1_verify/${pair}/Cargo.lock"
            echo "  ✓ sp1_verify/${pair}/Cargo.lock  ($(wc -l < "sp1_verify/${pair}/Cargo.lock") dòng)"
            found=$((found + 1))
            break
        fi
    done
done
docker rm "$cid" >/dev/null

if [ "$found" -lt 2 ]; then
    echo
    echo "⚠ Chỉ lấy được $found/2. Ảnh có thể build với --locked hoặc đã dọn lock."
    echo "  Cách khác — sinh trực tiếp trong container:"
    echo
    echo "    docker run --rm -v \"\$PWD/sp1_verify:/out\" --entrypoint sh '$IMAGE' -c \\"
    echo "      'cd /build/sp1_verify/host  && cargo generate-lockfile && cp Cargo.lock /out/host/  ; \\"
    echo "       cd /build/sp1_verify/guest && cargo generate-lockfile && cp Cargo.lock /out/guest/'"
    exit 1
fi

echo
echo "── kiểm phiên bản SP1 đã bị ghim ──"
for pair in host guest; do
    v="$(grep -A1 '^name = "sp1-sdk"' "sp1_verify/${pair}/Cargo.lock" 2>/dev/null | grep version || true)"
    z="$(grep -A1 '^name = "sp1-zkvm"' "sp1_verify/${pair}/Cargo.lock" 2>/dev/null | grep version || true)"
    echo "  ${pair}: ${v:-–} ${z:-–}"
done
echo
echo "👉 git add sp1_verify/host/Cargo.lock sp1_verify/guest/Cargo.lock"
echo "   Sau đó chạy lại lớp 4; cảnh báo 'version drift risk HIGH' phải biến mất."
