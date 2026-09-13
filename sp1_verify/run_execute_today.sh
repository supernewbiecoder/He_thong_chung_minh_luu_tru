#!/usr/bin/env bash
# Host-side runner cho server còn khoảng 27 GiB RAM khả dụng.
# Chỉ gọi SP1 execute; KHÔNG có nhánh prove/Groth16.
set -uo pipefail

IMAGE="${IMAGE:-engram-sp1-${USER:-$(id -un)}}"
RESULTS_HOST="${RESULTS_HOST:-$(pwd)/results}"
DOCKER_MEM="${DOCKER_MEM:-22g}"
DOCKER_SHM="${DOCKER_SHM:-8g}"
DOCKER_CPUS="${DOCKER_CPUS:-4}"
MIN_AVAILABLE_GIB="${MIN_AVAILABLE_GIB:-24}"
REPLICATES="${REPLICATES:-3}"
TREE_HEIGHT="${TREE_HEIGHT:-4}"
FIXED_CHALLENGES="${FIXED_CHALLENGES:-1}"
BATCH_POINTS="${BATCH_POINTS:-1 2}"
CHALLENGE_POINTS="${CHALLENGE_POINTS:-4 16}"
EXTRA_BATCH_POINTS="${EXTRA_BATCH_POINTS:-}"
RUN_DISTINCT="${RUN_DISTINCT:-1}"
DISTINCT_N="${DISTINCT_N:-2}"

die() { echo "❌ $*" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || die "Không thấy docker"
docker image inspect "$IMAGE" >/dev/null 2>&1 || die "Không thấy image $IMAGE — build image trước"
case "$REPLICATES" in ''|*[!0-9]*) die "REPLICATES phải là số nguyên" ;; esac
[ "$REPLICATES" -ge 1 ] || die "REPLICATES phải ≥1"

mkdir -p "$RESULTS_HOST" || die "Không tạo được $RESULTS_HOST"
chmod 777 "$RESULTS_HOST" 2>/dev/null || true
RESULTS_HOST="$(cd "$RESULTS_HOST" && pwd)"

available_gib() {
    awk '/MemAvailable:/ {printf "%d", $2/1024/1024}' /proc/meminfo
}

ram_gate() {
    local avail
    avail=$(available_gib)
    echo "🧠 MemAvailable trước điểm đo: ${avail} GiB (cần ≥${MIN_AVAILABLE_GIB} GiB)"
    if [ "$avail" -lt "$MIN_AVAILABLE_GIB" ]; then
        echo "⏸️  Dừng an toàn: RAM khả dụng thấp hơn ngưỡng. Kết quả đã fsync trong results.jsonl." >&2
        return 1
    fi
}

docker_point() { # mode run_id [extra docker -e args...]
    local mode="$1" run_id="$2"
    shift 2
    docker run --rm \
        --network none --read-only --cap-drop=ALL --security-opt=no-new-privileges \
        --pids-limit=4096 --shm-size="$DOCKER_SHM" \
        --memory="$DOCKER_MEM" --memory-swap="$DOCKER_MEM" --cpus="$DOCKER_CPUS" \
        --tmpfs /tmp:rw,nosuid,nodev,exec,size=1g \
        --tmpfs /home/runner/.sp1:rw,nosuid,nodev,exec,size=2g,uid=10001,gid=10001,mode=0700 \
        -e RUN_ID="$run_id" -e TREE_HEIGHT="$TREE_HEIGHT" \
        -e CHALLENGES_FIXED="$FIXED_CHALLENGES" -e SKIP_DONE=0 \
        -e SP1_PROVER=cpu \
        "$@" \
        -v "$RESULTS_HOST:/results" \
        "$IMAGE" "$mode"
}

stamp="$(date +%Y%m%d_%H%M%S)"
echo "═══ ENGRAM SP1 EXECUTE — run $stamp ═══"
echo "image=$IMAGE | results=$RESULTS_HOST | RAM cap=$DOCKER_MEM | shm=$DOCKER_SHM | CPUs=$DOCKER_CPUS"
echo "matrix: batch={$BATCH_POINTS} @ challenges=$FIXED_CHALLENGES; batch=1 @ challenges={$CHALLENGE_POINTS}; reps=$REPLICATES"

# Sinh/cache bundle ở container riêng. Nhờ vậy cgroup memory.peak trong từng
# container `point` không bị peak của Nova/bundle-gen làm nhiễu.
prepare_challenges="$FIXED_CHALLENGES $CHALLENGE_POINTS"
ram_gate || exit 3
docker_point prepare "${stamp}_prepare" \
    -e CHALLENGES_SWEEP="$prepare_challenges" \
    -e POINT_CHALLENGES="$FIXED_CHALLENGES" \
    || die "PREPARE thất bại — xem results/sweep_${stamp}_prepare.log"

failures=0
batch_blocked=0

# Trục 1: batch tăng, giữ challenges cố định.
for b in $BATCH_POINTS $EXTRA_BATCH_POINTS; do
    [ "$batch_blocked" -eq 1 ] && { echo "⏭️  bỏ batch=$b vì batch trước đã lỗi/OOM"; continue; }
    for rep in $(seq 1 "$REPLICATES"); do
        ram_gate || { failures=$((failures+1)); batch_blocked=1; break; }
        run_id="${stamp}_b${b}_c${FIXED_CHALLENGES}_r${rep}"
        echo "▶ batch=$b challenges=$FIXED_CHALLENGES replicate=$rep/$REPLICATES"
        if ! docker_point point "$run_id" \
            -e POINT_BATCH="$b" -e POINT_CHALLENGES="$FIXED_CHALLENGES"; then
            echo "⚠️  điểm $run_id lỗi/OOM; không thử batch lớn hơn" >&2
            failures=$((failures+1))
            batch_blocked=1
            break
        fi
    done
done

# Trục 2: challenges tăng, giữ batch=1.
for c in $CHALLENGE_POINTS; do
    for rep in $(seq 1 "$REPLICATES"); do
        ram_gate || { failures=$((failures+1)); break; }
        run_id="${stamp}_b1_c${c}_r${rep}"
        echo "▶ batch=1 challenges=$c replicate=$rep/$REPLICATES"
        if ! docker_point point "$run_id" -e POINT_BATCH=1 -e POINT_CHALLENGES="$c"; then
            echo "⚠️  điểm $run_id lỗi/OOM; chuyển sang cấu hình tiếp theo" >&2
            failures=$((failures+1))
            break
        fi
    done
done

# Một điểm đối chứng N proof phân biệt và N bản sao, dùng chung circuit shape.
if [ "$RUN_DISTINCT" = "1" ]; then
    ram_gate || failures=$((failures+1))
    if [ "$(available_gib)" -ge "$MIN_AVAILABLE_GIB" ]; then
        run_id="${stamp}_distinct_n${DISTINCT_N}"
        echo "▶ distinct control N=$DISTINCT_N"
        docker_point distinct "$run_id" \
            -e DISTINCT_N="$DISTINCT_N" -e CHALLENGES_FIXED="$FIXED_CHALLENGES" \
            || failures=$((failures+1))
    fi
fi

echo ""
echo "═══ HOÀN TẤT ═══"
echo "JSONL: $RESULTS_HOST/results.jsonl"
echo "Phân tích: python3 sp1_verify/analyze.py '$RESULTS_HOST/results.jsonl' --outdir '$RESULTS_HOST/analysis'"
if [ "$failures" -gt 0 ]; then
    echo "⚠️  Có $failures điểm lỗi/không chạy; các điểm ok=true vẫn hợp lệ và đã được giữ." >&2
    exit 2
fi
