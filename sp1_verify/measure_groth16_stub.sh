#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# measure_groth16_stub.sh — sinh MỘT Groth16 proof THẬT bằng pv-stub guest.
#
#   ./sp1_verify/measure_groth16_stub.sh build     # build image (1 lần)
#   ./sp1_verify/measure_groth16_stub.sh execute   # đếm cycle stub, trong container
#   ./sp1_verify/measure_groth16_stub.sh fetch     # tải circuit gnark vào cache (1 lần)
#   ./sp1_verify/measure_groth16_stub.sh export    # lấy binary + cache ra host
#   ./sp1_verify/measure_groth16_stub.sh native    # PROVE — chạy TRÊN HOST
#
# ══════════════════════════════════════════════════════════════════════════
# ⚠ VÌ SAO PROVE PHẢI CHẠY TRÊN HOST, KHÔNG TRONG CONTAINER
# ══════════════════════════════════════════════════════════════════════════
# SP1 6.3.1 chạy gnark bằng cách TỰ SPAWN MỘT CONTAINER DOCKER khác
# (sp1_recursion_gnark_ffi::ffi::docker::assert_docker). Đặt prover bên trong
# một container thì:
#   - không có docker CLI  → panic "Failed to run `docker info`"
#   - mount /var/run/docker.sock cũng KHÔNG cứu được: SP1 truyền đường dẫn
#     /home/runner/.sp1/circuits/... cho daemon, daemon resolve trên filesystem
#     HOST, nên container gnark anh em không thấy artifact.
#
# Nên: `fetch` chạy trong container (chỉ để tải circuit vào volume, an toàn),
# rồi `export` mang binary + cache ra host, rồi `native` prove trên host.
#
# Bản trước của script này chỉ có `prove` chạy trong container — SAI, đã bỏ.
# ═══════════════════════════════════════════════════════════════════════════
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

USER_TAG="${USER:-$(id -un)}"; USER_TAG="${USER_TAG//[^a-zA-Z0-9_.-]/_}"
IMAGE="${IMAGE:-engram-pvstub-${USER_TAG}}"
CACHE_VOLUME="${SP1_CACHE_VOLUME:-engram-sp1-cache-${USER_TAG}}"
RESULTS_HOST="${RESULTS_HOST:-$PROJECT_DIR/results}"
BIN_HOST="${BIN_HOST:-$PROJECT_DIR/.pvstub-bin/engram-pvstub-host}"
SP1_HOME="${SP1_HOME:-$HOME/.sp1}"

SUBMITTER="${SUBMITTER:-f39fd6e51aad88f6f4ce6ab8827279cfffb92266}"

die() { echo "❌ $*" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || die "Không thấy docker"

prep() {
    mkdir -p "$RESULTS_HOST/pvstub" || die "Không tạo được $RESULTS_HOST/pvstub"
    chmod 777 "$RESULTS_HOST" "$RESULTS_HOST/pvstub" 2>/dev/null || true
    RESULTS_HOST="$(cd "$RESULTS_HOST" && pwd)"
    docker volume inspect "$CACHE_VOLUME" >/dev/null 2>&1 \
        || docker volume create "$CACHE_VOLUME" >/dev/null \
        || die "Không tạo được volume $CACHE_VOLUME"

    # Lượt chạy trong container dùng uid 10001 (runner), lượt native dùng
    # uid $(id -u). Bên nào ghi trước thì bên kia không mở được file đó với
    # O_TRUNC. `chmod 777` ở trên chỉ tác động lên THƯ MỤC, không lên file đã
    # tồn tại; thư mục 777 nên unlink được mà không cần sudo.
    for f in pv_expected.bin vkey.txt proof.bin public_values.bin \
             result.json pvstub.jsonl; do
        p="$RESULTS_HOST/pvstub/$f"
        if [ -e "$p" ] && [ ! -w "$p" ]; then
            rm -f "$p" && echo "🧹 dọn artifact thuộc uid khác: $f"
        fi
    done
}

avail_gib() { awk '/MemAvailable:/ {printf "%d", $2/1024/1024}' /proc/meminfo; }

cache_size() {
    docker run --rm --user 0:0 -v "$CACHE_VOLUME:/c" --entrypoint sh "$IMAGE" \
        -c 'du -sh /c 2>/dev/null | cut -f1' 2>/dev/null || echo "?"
}

case "${1:-help}" in

build)
    docker build -f Dockerfile.pvstub -t "$IMAGE" .
    ;;

execute)
    prep
    docker image inspect "$IMAGE" >/dev/null 2>&1 || die "Chưa có image $IMAGE — chạy 'build' trước"

    # ⚠ HẠN MỨC BỘ NHỚ: 4g KHÔNG ĐỦ, dù chương trình guest chỉ vài nghìn chu kỳ.
    #
    #   `ProverClient::from_env()` dựng toàn bộ SP1Prover — core, compress,
    #   shrink, wrap machine cùng dữ liệu tiền xử lý — và được gọi TRƯỚC khi rẽ
    #   nhánh execute/prove. Chi phí đó KHÔNG phụ thuộc chương trình.
    #
    #   Bằng chứng từ chính bộ đo: RAM pha execute của guest thật phẳng ở
    #   10,60–10,66 GiB khi cycles tăng từ 56,6·10⁹ lên 90,4·10⁹ (N=1..4).
    #   Phẳng nghĩa là phần cố định chi phối. Với 4g, container bị OOM killer
    #   kết thúc — SIGKILL không để lại thông điệp nào, nên log chỉ có ba dòng
    #   đầu và trông như "chạy xong rồi dừng".
    #
    #   `run_sp1.sh execute` dùng DOCKER_MEM=22g cho cùng lý do.
    DOCKER_MEM_EXEC="${DOCKER_MEM_EXEC:-16g}"
    a="$(avail_gib)"
    if [ "$a" -lt 18 ]; then
        die "MemAvailable ${a} GiB. Pha execute cần ~11 GiB cho SP1Prover; để ít nhất 18 GiB.
   Giải phóng bằng cách dừng tạm các container khác, hoặc đặt DOCKER_MEM_EXEC thấp hơn nếu bạn biết mình đang làm gì."
    fi

    stamp="$(date +%Y%m%d_%H%M%S)_pvstub_exec"
    echo "═══ PV-STUB EXECUTE — $stamp ═══"
    echo "🧠 MemAvailable ${a} GiB | hạn mức container ${DOCKER_MEM_EXEC}"

    # ⚠ ĐÃ BỎ `--tmpfs /home/runner/.sp1`: nó CHE MẤT thư mục .sp1 mà Dockerfile
    #   đã copy vào image lúc build, đồng thời cgroup v2 tính tmpfs vào
    #   memory.max nên nó ăn thêm phần của hạn mức.
    docker run --rm \
        --network none --read-only --cap-drop=ALL --security-opt=no-new-privileges \
        --pids-limit=4096 --shm-size=1g \
        --memory="$DOCKER_MEM_EXEC" --memory-swap="$DOCKER_MEM_EXEC" --cpus=4 \
        --tmpfs /tmp:rw,nosuid,nodev,exec,size=1g \
        -e SP1_PROVER=cpu \
        -v "$RESULTS_HOST:/results" \
        "$IMAGE" \
        --execute --run-id "$stamp" \
        --submitter "$SUBMITTER" \
        --out /results/pvstub \
        --json /results/pvstub/pvstub.jsonl \
        2>&1 | tee "$RESULTS_HOST/pvstub/host_${stamp}.log"
    rc="${PIPESTATUS[0]}"
    if [ "$rc" = "137" ]; then
        echo
        echo "❌ Mã thoát 137 = SIGKILL = OOM killer. Tăng DOCKER_MEM_EXEC rồi chạy lại:"
        echo "     DOCKER_MEM_EXEC=24g $0 execute"
    elif [ "$rc" != "0" ]; then
        echo
        echo "❌ Mã thoát $rc. 101 = panic Rust (đọc log để biết chỗ); 137 = OOM."
    fi
    exit "$rc"
    ;;

fetch)
    prep
    echo "═══ NẠP CIRCUIT GNARK VÀO CACHE (mở mạng đúng bước này) ═══"
    echo "Cache trước: $(cache_size)"
    echo "ℹ️  Lệnh này SẼ panic ở bước gnark với 'Failed to run docker info' —"
    echo "    ĐÓ LÀ BÌNH THƯỜNG. Mục đích duy nhất là tải circuit vào volume."
    echo "    Prove thật chạy ở bước 'native'."
    stamp="$(date +%Y%m%d_%H%M%S)_pvstub_fetch"
    docker run --rm \
        --cap-drop=ALL --security-opt=no-new-privileges \
        --pids-limit=8192 --shm-size=2g \
        --memory=32g --memory-swap=32g --cpus=8 \
        --tmpfs /tmp:rw,nosuid,nodev,exec,size=4g \
        -v "$CACHE_VOLUME:/home/runner/.sp1" \
        -v "$RESULTS_HOST:/results" \
        -e SP1_PROVER=cpu \
        "$IMAGE" \
        --prove --run-id "$stamp" \
        --submitter "$SUBMITTER" \
        --out /results/pvstub \
        2>&1 | tee "$RESULTS_HOST/pvstub/host_${stamp}.log"
    echo "Cache sau: $(cache_size)"
    echo "👉 Bước tiếp: $0 export"
    ;;

export)
    prep
    docker image inspect "$IMAGE" >/dev/null 2>&1 || die "Chưa có image $IMAGE"
    mkdir -p "$(dirname "$BIN_HOST")"

    echo "── 1/2 lấy binary ra host ──"
    cid="$(docker create "$IMAGE")" || die "docker create thất bại"
    docker cp "$cid:/work/engram-pvstub-host" "$BIN_HOST" \
        || { docker rm "$cid" >/dev/null 2>&1; die "docker cp thất bại"; }
    docker rm "$cid" >/dev/null
    chmod +x "$BIN_HOST"
    echo "   $BIN_HOST"

    echo "── 2/2 copy cache circuit ra $SP1_HOME ──"
    mkdir -p "$SP1_HOME"
    docker run --rm --user 0:0 \
        -v "$CACHE_VOLUME:/from" \
        -v "$SP1_HOME:/to" \
        --entrypoint sh "$IMAGE" \
        -c "cp -a /from/. /to/ && chown -R $(id -u):$(id -g) /to" \
        || die "copy cache thất bại"
    du -sh "$SP1_HOME"

    echo
    echo "── kiểm binary chạy được trên host (glibc) ──"
    if "$BIN_HOST" --help >/dev/null 2>&1; then
        echo "   ✅ chạy được"
    else
        echo "   ❌ KHÔNG chạy được. Nhiều khả năng lệch glibc (image bookworm 2.36"
        echo "      vs Ubuntu 24.04 2.39 — thường tương thích xuôi, nhưng không chắc)."
        echo "      Kiểm: ldd '$BIN_HOST'"
        echo "      Cách khác: cài Rust + SP1 toolchain trên host rồi"
        echo "      cd sp1_verify/pv_stub/host && cargo build --release"
        exit 1
    fi
    echo "👉 Bước tiếp: $0 native"
    ;;

native)
    prep
    [ -x "$BIN_HOST" ] || die "Chưa có $BIN_HOST — chạy '$0 export' trước"
    [ -d "$SP1_HOME/circuits" ] || die "Chưa có $SP1_HOME/circuits — chạy '$0 export' trước"
    docker info >/dev/null 2>&1 \
        || die "Không gọi được 'docker info'. SP1 cần nó để spawn container gnark."

    echo "═══ PV-STUB GROTH16 — CHẠY TRÊN HOST ═══"
    echo "🧠 MemAvailable: $(avail_gib) GiB (không cgroup limit — SP1 tự spawn container gnark)"
    echo "📦 $SP1_HOME: $(du -sh "$SP1_HOME" 2>/dev/null | cut -f1)"
    stamp="$(date +%Y%m%d_%H%M%S)_pvstub_native"

    SP1_PROVER=cpu \
    RUST_BACKTRACE=1 \
    "$BIN_HOST" \
        --prove --run-id "$stamp" \
        --submitter "$SUBMITTER" \
        --out "$RESULTS_HOST/pvstub" \
        --json "$RESULTS_HOST/pvstub/pvstub.jsonl" \
        2>&1 | tee "$RESULTS_HOST/pvstub/host_${stamp}.log"
    rc="${PIPESTATUS[0]}"

    if [ "$rc" = "0" ]; then
        echo
        echo "✅ Xong. Artifact: $RESULTS_HOST/pvstub/"
        echo "   Dòng '🔎 4-byte selector' phía trên dùng để chọn đúng version"
        echo "   verifier trong sp1-contracts."
        echo "👉 python3 experiments/l4_evm/bench_real_verifier.py --artifacts '$RESULTS_HOST/pvstub'"
    else
        echo
        echo "❌ prove thất bại (rc=$rc). Phân loại theo MÃ THOÁT trước, rồi mới đọc log:"
        echo "   • 137  → SIGKILL = OOM killer. Log KHÔNG có thông điệp nào; đừng"
        echo "            tìm panic trong đó. Giải phóng RAM hoặc dùng máy lớn hơn."
        echo "   • 101  → panic Rust; thông điệp nằm ở cuối log."
        echo "   • 2    → lỗi tham số dòng lệnh."
        echo "   Phân loại theo log:"
        echo "   • 'Killed' / OOM        → RAM không đủ cho cả stub 1 shard. ĐÓ LÀ KẾT QUẢ:"
        echo "                             ghi RSS peak vào Limitations rồi dừng P1."
        echo "   • 'docker info'         → sudo usermod -aG docker \$USER; đăng nhập lại"
        echo "   • 'artifact not found'  → cache thiếu: chạy lại '$0 fetch' rồi '$0 export'"
    fi
    exit "$rc"
    ;;

prove)
    echo "❌ Mode 'prove' (trong container) đã BỎ: SP1 6.3.1 spawn container gnark"
    echo "   nên prover không chạy được bên trong container."
    echo "   Dùng: $0 fetch → $0 export → $0 native"
    exit 2
    ;;

*)
    sed -n '2,28p' "$0" | sed 's/^# \?//'
    ;;
esac