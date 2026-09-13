#!/usr/bin/env bash
# Unified host-side entrypoint for the same Engram Guest ELF and Host binary.
#
#   ./sp1_verify/run_sp1.sh build
#   ./sp1_verify/run_sp1.sh execute
#   ENABLE_PROVE=1 ./sp1_verify/run_sp1.sh prove
#   ./sp1_verify/run_sp1.sh pipeline       # execute; prove only when explicitly enabled
#   ./sp1_verify/run_sp1.sh analyze
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

USER_TAG="${USER:-$(id -un)}"
USER_TAG="${USER_TAG//[^a-zA-Z0-9_.-]/_}"
IMAGE="${IMAGE:-engram-sp1-${USER_TAG}}"
RESULTS_HOST="${RESULTS_HOST:-$PROJECT_DIR/results}"

die() { echo "❌ $*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Engram SP1 unified runner

Usage:
  ./sp1_verify/run_sp1.sh build
  ./sp1_verify/run_sp1.sh execute
  ENABLE_PROVE=1 ./sp1_verify/run_sp1.sh prove
  ./sp1_verify/run_sp1.sh pipeline
  ./sp1_verify/run_sp1.sh analyze

Modes share one Docker image, one engram-host binary, one Guest ELF, one input
format, one artifact cache, and one results.jsonl. `execute` never generates a
proof. `prove` is local Groth16 and is opt-in because it needs substantially
more RAM, disk, and time.

Important variables:
  IMAGE, RESULTS_HOST
  DOCKER_MEM, DOCKER_SHM, DOCKER_CPUS, MIN_AVAILABLE_GIB, REPLICATES
  BATCH_POINTS, CHALLENGE_POINTS, RUN_DISTINCT
  ENABLE_PROVE=1
  DOCKER_MEM_PROVE, DOCKER_SHM_PROVE, DOCKER_CPUS_PROVE
  MIN_PROVE_AVAILABLE_GIB, PROVE_BATCH_POINTS, PROVE_CHALLENGES
  SP1_CACHE_VOLUME
EOF
}

need_docker() {
    command -v docker >/dev/null 2>&1 || die "Không thấy docker"
}

prepare_results() {
    mkdir -p "$RESULTS_HOST" || die "Không tạo được $RESULTS_HOST"
    chmod 777 "$RESULTS_HOST" 2>/dev/null || true
    RESULTS_HOST="$(cd "$RESULTS_HOST" && pwd)"
}

available_gib() {
    awk '/MemAvailable:/ {printf "%d", $2/1024/1024}' /proc/meminfo
}

build_image() {
    need_docker
    docker build --pull -t "$IMAGE" .
}

run_execute_profile() {
    need_docker
    docker image inspect "$IMAGE" >/dev/null 2>&1 \
        || die "Không thấy image $IMAGE — chạy '$0 build' trước"
    prepare_results

    IMAGE="$IMAGE" \
    RESULTS_HOST="$RESULTS_HOST" \
    DOCKER_MEM="${DOCKER_MEM:-22g}" \
    DOCKER_SHM="${DOCKER_SHM:-8g}" \
    DOCKER_CPUS="${DOCKER_CPUS:-4}" \
    MIN_AVAILABLE_GIB="${MIN_AVAILABLE_GIB:-24}" \
    REPLICATES="${REPLICATES:-3}" \
    TREE_HEIGHT="${TREE_HEIGHT:-4}" \
    FIXED_CHALLENGES="${FIXED_CHALLENGES:-1}" \
    BATCH_POINTS="${BATCH_POINTS:-1 2}" \
    CHALLENGE_POINTS="${CHALLENGE_POINTS:-4 16}" \
    EXTRA_BATCH_POINTS="${EXTRA_BATCH_POINTS:-}" \
    RUN_DISTINCT="${RUN_DISTINCT:-1}" \
    DISTINCT_N="${DISTINCT_N:-2}" \
    "$SCRIPT_DIR/run_execute_today.sh"
}

run_prove_profile() {
    [ "${ENABLE_PROVE:-0}" = "1" ] \
        || die "Prove đang khóa an toàn. Chỉ bật bằng: ENABLE_PROVE=1 $0 prove"
    need_docker
    docker image inspect "$IMAGE" >/dev/null 2>&1 \
        || die "Không thấy image $IMAGE — chạy '$0 build' trước"
    prepare_results

    local min_available="${MIN_PROVE_AVAILABLE_GIB:-32}"
    local avail
    avail="$(available_gib)"
    echo "🧠 MemAvailable trước prove: ${avail} GiB (ngưỡng mặc định ${min_available} GiB)"
    if [ "$avail" -lt "$min_available" ] && [ "${ALLOW_LOW_MEMORY_PROVE:-0}" != "1" ]; then
        die "Không đủ ngưỡng RAM cho profile prove. Giữ execute benchmark; hoặc chỉ override khi chấp nhận rủi ro OOM bằng ALLOW_LOW_MEMORY_PROVE=1."
    fi

    local cache_volume="${SP1_CACHE_VOLUME:-engram-sp1-cache-${USER_TAG}}"
    docker volume inspect "$cache_volume" >/dev/null 2>&1 \
        || docker volume create "$cache_volume" >/dev/null \
        || die "Không tạo được Docker volume $cache_volume"

    local stamp
    stamp="$(date +%Y%m%d_%H%M%S)_prove"
    echo "═══ ENGRAM SP1 LOCAL GROTH16 — run $stamp ═══"
    echo "image=$IMAGE | results=$RESULTS_HOST | cache-volume=$cache_volume"
    echo "batch={${PROVE_BATCH_POINTS:-1}} | challenges=${PROVE_CHALLENGES:-1} | tree_height=${PROVE_TREE_HEIGHT:-4}"

    docker run --rm \
        --network none --read-only --cap-drop=ALL --security-opt=no-new-privileges \
        --pids-limit=8192 --shm-size="${DOCKER_SHM_PROVE:-8g}" \
        --memory="${DOCKER_MEM_PROVE:-28g}" \
        --memory-swap="${DOCKER_MEM_PROVE:-28g}" \
        --cpus="${DOCKER_CPUS_PROVE:-8}" \
        --tmpfs /tmp:rw,nosuid,nodev,exec,size=2g \
        -v "$cache_volume:/home/runner/.sp1" \
        -v "$RESULTS_HOST:/results" \
        -e RUN_ID="$stamp" \
        -e TREE_HEIGHT="${PROVE_TREE_HEIGHT:-4}" \
        -e CHALLENGES_FIXED="${PROVE_CHALLENGES:-1}" \
        -e BATCH_PROVE="${PROVE_BATCH_POINTS:-1}" \
        -e SKIP_DONE="${SKIP_DONE:-1}" \
        -e SP1_PROVER=cpu \
        "$IMAGE" prove
}

analyze_results() {
    prepare_results
    command -v python3 >/dev/null 2>&1 || die "Không thấy python3"
    [ -f "$RESULTS_HOST/results.jsonl" ] \
        || die "Chưa có $RESULTS_HOST/results.jsonl"
    python3 "$SCRIPT_DIR/analyze.py" \
        "$RESULTS_HOST/results.jsonl" \
        --outdir "$RESULTS_HOST/analysis"
}

MODE="${1:-help}"
case "$MODE" in
    build)
        build_image
        ;;
    execute)
        run_execute_profile
        ;;
    prove)
        run_prove_profile
        ;;
    pipeline)
        run_execute_profile
        if [ "${ENABLE_PROVE:-0}" = "1" ]; then
            run_prove_profile
        else
            echo "ℹ️  Execute đã xong; prove được bỏ qua vì ENABLE_PROVE chưa bằng 1."
        fi
        ;;
    analyze)
        analyze_results
        ;;
    help|-h|--help)
        usage
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
