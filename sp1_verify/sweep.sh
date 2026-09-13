#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# SWEEP — chiến lược đo cho Modular-PoSt, tối ưu giờ server.
#
# Nguyên tắc thiết kế:
#   1. PREFLIGHT   — kiểm quyền ghi + toolchain TRƯỚC, không để chết ở phút 30.
#   2. FAIL FAST   — smoke test 5 phút trước, đừng đốt 3 giờ rồi mới biết hỏng.
#   3. RẺ TRƯỚC    — execute (đếm cycles) rẻ, chạy hết trước; prove đắt, chạy sau.
#   4. CACHE       — bundle.bin sinh 1 lần/(challenge, tree_height), tái dùng mọi batch.
#   5. RESUMABLE   — append JSONL ngay + bỏ qua điểm đã đo (SKIP_DONE=1).
#   6. TRUY NGUYÊN — mỗi dòng kết quả mang run_id + phase + config đã sinh ra nó.
#
# Dùng:
#   ./sweep.sh smoke     — kiểm pipeline (~5 phút). LÀM ĐẦU TIÊN.
#   ./sweep.sh execute   — quét cycles (rẻ, ~30-60 phút). Trả lời RQ2 + RQ3.
#   ./sweep.sh prepare   — chỉ sinh/cache bundle, KHÔNG execute (tách RAM bundle-gen).
#   ./sweep.sh point     — chạy ĐÚNG MỘT điểm POINT_BATCH × POINT_CHALLENGES.
#   ./sweep.sh distinct  — điểm ĐỐI CHỨNG cho ghi chú đo đạc (bundle phân biệt).
#   ./sweep.sh prove     — quét Groth16 (ĐẮT, nhiều giờ). Trả lời RQ1 + RQ2.
#   ./sweep.sh all       — smoke → execute → distinct → prove.
#
# ── SỬA SO VỚI BẢN TRƯỚC ──
#   * Preflight: bắt lỗi quyền ghi /results và $HOME/.sp1 ngay từ giây đầu, kèm lệnh sửa.
#   * Bỏ `|| log LỖI` sai: dùng PIPESTATUS thay vì exit status của grep (grep không
#     match là chuyện bình thường, trước đây bị báo "LỖI" oan).
#   * RUN_ID + dòng run_meta: hai lượt sweep không còn lẫn dòng vào nhau.
#   * TREE_HEIGHT là biến quét thật (trước đây bị hardcode 4 trong bundle_gen).
#   * bundle_gen tự ghi dòng JSONL của nó (có RAM + config), sweep không echo tay nữa.
#   * SKIP_DONE: chạy lại sau khi đứt chỉ đo phần còn thiếu.
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

if [ "${SP1_PROVER:-local}" = "network" ]; then
    echo "❌ SP1_PROVER=network bị khóa trong bản simulation-only; dùng local." >&2
    exit 2
fi

RESULTS="${RESULTS_DIR:-/results}"
ART="${ART_DIR:-$RESULTS/artifacts}"   # trong $RESULTS để tương thích --read-only rootfs
SCRATCH="${SCRATCH_DIR:-$ART}"          # nơi ghi sector tạm (xoá ngay sau khi seal)
BG="${BG_DIR:-/work}"                   # bundle-gen binary
HOST="${HOST_DIR:-/work}"               # engram-host binary

# ── Tham số quét ──────────────────────────────────────────────────────────────
# CHALLENGES: số challenge/proof — ảnh hưởng chi phí prover phía node (RQ3).
CHALLENGES_SWEEP="${CHALLENGES_SWEEP:-1 3 10}"
# BATCH: số bundle/batch — TRỤC CHÍNH của RQ2 (chi phí EVM có gần như hằng số không).
BATCH_EXECUTE="${BATCH_EXECUTE:-1 2 5 10 25 50}"
# Prove đắt hơn nhiều → chỉ vài điểm đủ vẽ đường cong.
BATCH_PROVE="${BATCH_PROVE:-1 5 25}"
# Mức challenge cố định khi quét batch (giữ 1 biến thay đổi tại một thời điểm).
CHALLENGES_FIXED="${CHALLENGES_FIXED:-3}"
# TREE_HEIGHT: num_chunks = 2^h, sector = 4KiB·2^h.
#   4  → 64 KiB  (smoke, rẻ)
#   18 → 1 GiB
#   23 → 32 GiB  (config production — CẦN 32GB trống ở SCRATCH_DIR)
TREE_HEIGHT="${TREE_HEIGHT:-4}"
# Số bundle phân biệt cho phase đối chứng.
DISTINCT_N="${DISTINCT_N:-5}"
# Chế độ `point`: mỗi container chỉ đo đúng một cấu hình, giúp memory.peak của
# cgroup thuộc chính điểm đó thay vì là max tích lũy của cả sweep.
POINT_BATCH="${POINT_BATCH:-1}"
POINT_CHALLENGES="${POINT_CHALLENGES:-$CHALLENGES_FIXED}"
# 1 = bỏ qua điểm đã có trong results.jsonl (mọi run_id). 0 = đo lại tất cả.
SKIP_DONE="${SKIP_DONE:-1}"

# ── PREFLIGHT ─────────────────────────────────────────────────────────────────
# Mục đích: mọi lỗi môi trường phải lộ ra trong 5 giây đầu, kèm lệnh sửa cụ thể.
die() { echo "❌ $*" >&2; exit 1; }

[ -x "$BG/bundle-gen" ]    || die "Không thấy $BG/bundle-gen (image build lỗi?)"
[ -x "$HOST/engram-host" ] || die "Không thấy $HOST/engram-host (image build lỗi?)"

mkdir -p "$RESULTS" 2>/dev/null
if ! ( : > "$RESULTS/.wtest" ) 2>/dev/null; then
    die "KHÔNG ghi được vào $RESULTS.
   Nguyên nhân gần như chắc chắn: container chạy uid $(id -u), nhưng thư mục
   results/ trên host thuộc user khác → bind mount giữ nguyên ownership của host.
   SỬA (chạy trên host, TRƯỚC docker run):
       mkdir -p results && chmod 777 results"
fi
rm -f "$RESULTS/.wtest"
mkdir -p "$ART" "$SCRATCH" || die "Không tạo được $ART / $SCRATCH"

# $HOME/.sp1 — sp1-sdk ghi cache/artifact vào đây. Với --read-only thì rootfs (nơi
# /home/runner nằm) KHÔNG ghi được → phải mount riêng.
if ! ( mkdir -p "$HOME/.sp1" && : > "$HOME/.sp1/.wtest" ) 2>/dev/null; then
    die "KHÔNG ghi được vào \$HOME/.sp1 ($HOME/.sp1).
   Nguyên nhân: --read-only làm rootfs chỉ đọc, mà \$HOME nằm trên rootfs.
   SỬA — thêm vào lệnh docker run:
       execute:  --tmpfs /home/runner/.sp1:exec,size=2g
       prove:    -v \"\$(pwd)/sp1cache:/home/runner/.sp1\"   (cần ~30GB cho circuit gnark)"
fi
rm -f "$HOME/.sp1/.wtest"

RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)_$$}"
LOG="$RESULTS/sweep_${RUN_ID}.log"
JSON="$RESULTS/results.jsonl"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

# Giới hạn RAM của container + peak (để chẩn đoán OOM-kill về sau).
cg_read() { [ -r "$1" ] && cat "$1" 2>/dev/null || echo 0; }
mem_limit() {
    local v; v=$(cg_read /sys/fs/cgroup/memory.max)
    [ "$v" = "0" ] && v=$(cg_read /sys/fs/cgroup/memory/memory.limit_in_bytes)
    echo "${v:-0}"
}
mem_peak() {
    local v; v=$(cg_read /sys/fs/cgroup/memory.peak)
    [ "$v" = "0" ] && v=$(cg_read /sys/fs/cgroup/memory/memory.max_usage_in_bytes)
    echo "${v:-0}"
}

# Ghi 1 dòng run_meta — neo mọi kết quả của lượt này vào môi trường sinh ra nó.
write_run_meta() {
    local disk_kb; disk_kb=$(df -Pk "$SCRATCH" 2>/dev/null | awk 'NR==2{print $4}')
    printf '{"mode":"run_meta","run_id":"%s","ts":%s,"phase_arg":"%s","host":"%s","uid":%s,"nproc":%s,"mem_limit_bytes":"%s","scratch_free_kib":"%s","tree_height":%s,"challenges_fixed":%s,"point_batch":%s,"point_challenges":%s,"batch_execute":"%s","batch_prove":"%s","challenges_sweep":"%s","distinct_n":%s,"sp1_prover":"%s","sp1_version":"%s","git_sha":"%s"}\n' \
        "$RUN_ID" "$(date +%s)" "${1:-na}" "$(hostname 2>/dev/null || echo na)" "$(id -u)" \
        "$(nproc 2>/dev/null || echo 0)" "$(mem_limit)" "${disk_kb:-0}" \
        "$TREE_HEIGHT" "$CHALLENGES_FIXED" "$POINT_BATCH" "$POINT_CHALLENGES" \
        "$BATCH_EXECUTE" "$BATCH_PROVE" \
        "$CHALLENGES_SWEEP" "$DISTINCT_N" "${SP1_PROVER:-local}" \
        "${SP1_VERSION:-6.3.1}" "${GIT_SHA:-unknown}" >> "$JSON"
    sync 2>/dev/null || true
}

# ── Resumability: điểm này đã đo chưa? ───────────────────────────────────────
# So theo (mode, batch, challenges, tree_height, distinct) trên MỌI run_id.
already_done() { # $1=mode $2=batch $3=challenges $4=distinct(true|false)
    [ "$SKIP_DONE" = "1" ] || return 1
    [ -f "$JSON" ] || return 1
    command -v jq >/dev/null 2>&1 || return 1
    local n
    n=$(jq -c --arg m "$1" --argjson b "$2" --argjson c "$3" --argjson h "$TREE_HEIGHT" \
           --argjson d "$4" \
        'select(.mode==$m and .batch==$b and .challenges==$c
                and ((.cfg.tree_height // -1)==$h)
                and ((.distinct // false)==$d)
                and (($m=="execute" and .ok==true and .num_verified==$b)
                     or ($m=="prove" and .ok==true and .num_verified==$b
                         and (.groth16_bytes // 0)>0
                         and (.pv_bytes // 0)==256)))' \
        "$JSON" 2>/dev/null | wc -l)
    [ "${n:-0}" -gt 0 ]
}

# ── Helper: sinh bundle, có cache ─────────────────────────────────────────────
# Cache theo (challenges, tree_height) — KHÔNG phụ thuộc batch size.
gen_bundle() { # $1=challenges
    local c=$1
    local cache="$ART/h${TREE_HEIGHT}_c${c}"
    if [ -f "$cache/bundle.bin" ] && [ -f "$cache/vk.bin" ] && [ -f "$cache/meta.json" ]; then
        log "  ↩️  Dùng lại bundle cache (h=$TREE_HEIGHT, challenges=$c)"
    else
        log "  ⏳ Sinh bundle h=$TREE_HEIGHT challenges=$c (Nova fold + Spartan compress)..."
        mkdir -p "$cache"
        local t0=$SECONDS
        "$BG/bundle-gen" --challenges "$c" --tree-height "$TREE_HEIGHT" \
            --out "$cache" --scratch "$SCRATCH" \
            --json "$JSON" --run-id "$RUN_ID" >>"$LOG" 2>&1
        local rc=$?
        if [ $rc -ne 0 ]; then
            log "  ❌ bundle-gen THẤT BẠI rc=$rc (h=$TREE_HEIGHT, challenges=$c) — xem $LOG"
            return 1
        fi
        log "  ✅ Bundle xong sau $((SECONDS-t0))s, size=$(stat -c%s "$cache/bundle.bin" 2>/dev/null || echo 0)B"
    fi
    # Trỏ artifact "hiện hành" vào cache (host đọc $ART/bundle.bin + vk.bin + meta.json).
    ln -sfn "$cache/bundle.bin" "$ART/bundle.bin"
    ln -sfn "$cache/vk.bin"     "$ART/vk.bin"
    ln -sfn "$cache/meta.json"  "$ART/meta.json"
}

# Chạy engram-host, lọc dòng đáng xem ra console, GIỮ full output trong log.
# PIPESTATUS[0] = exit status của engram-host (không phải của grep).
run_host() { # $@ = args cho engram-host
    "$HOST/engram-host" "$@" 2>&1 \
        | tee -a "$LOG" \
        | grep --line-buffered -E "TỔNG CYCLES|CYCLES /|PROVER GAS|GAS / bundle|Execute time|Throughput|Peak RSS|Cgroup memory|num_verified|📦|🔀|Groth16 proof|EVM calldata|Prove time|vkey|💾"
    return "${PIPESTATUS[0]}"
}

run_execute() { # $1=batch $2=challenges $3=phase
    if already_done execute "$1" "$2" false; then
        log "  ⏭️  bỏ qua execute batch=$1 ch=$2 h=$TREE_HEIGHT (đã có trong results.jsonl)"
        return 0
    fi
    log "  ▶️  execute batch=$1 ch=$2 h=$TREE_HEIGHT"
    if run_host --execute --batch "$1" --artifacts "$ART" --json "$JSON" \
                --run-id "$RUN_ID" --phase "$3"; then
        return 0
    else
        log "  ⚠️  execute batch=$1 LỖI (xem $LOG) — bỏ qua, chạy tiếp"
        return 1
    fi
}

run_prove() { # $1=batch $2=challenges $3=phase
    if already_done prove "$1" "$2" false; then
        log "  ⏭️  bỏ qua prove batch=$1 ch=$2 h=$TREE_HEIGHT (đã có)"
        return 0
    fi
    log "  ▶️  prove batch=$1 (đắt — có thể nhiều phút/giờ)"
    if run_host --prove --batch "$1" --artifacts "$ART" --json "$JSON" \
                --run-id "$RUN_ID" --phase "$3"; then
        return 0
    else
        log "  ⚠️  prove batch=$1 LỖI (nhiều khả năng OOM; peak=$(mem_peak)B / limit=$(mem_limit)B)"
        return 1
    fi
}

# ── PHASE 0: SMOKE — kiểm pipeline trước khi đốt giờ ──────────────────────────
phase_smoke() {
    log "═══ PHASE 0: SMOKE TEST (mục tiêu: ~5 phút) ═══"
    log "run_id=$RUN_ID | tree_height=$TREE_HEIGHT | results=$JSON"
    log "Kiểm pipeline chạy được ở kích thước nhỏ nhất TRƯỚC KHI quét dài."
    gen_bundle 1 || { log "❌ SMOKE FAIL ở bundle_gen. DỪNG."; return 1; }
    # Smoke luôn đo lại, không skip (nó là cổng chặn, không phải điểm dữ liệu).
    if ! SKIP_DONE=0 run_execute 1 1 smoke; then
        log "❌ SMOKE FAIL ở execute (host trả exit khác 0). DỪNG — sửa trước khi quét."
        return 1
    fi
    if jq -e --arg r "$RUN_ID" \
        'select(.mode=="execute" and .run_id==$r and .ok==true
                and .batch==1 and .num_verified==1)' "$JSON" >/dev/null 2>&1; then
        log "✅ SMOKE PASS — pipeline hoạt động. An toàn để quét."
        log "   👉 Xem cycles ở trên. Nếu >1 tỷ, cân nhắc giảm quy mô trước khi prove."
    else
        log "❌ SMOKE FAIL ở execute. DỪNG — sửa trước khi quét."
        return 1
    fi
}

# ── PHASE 1: EXECUTE SWEEP — rẻ, thu nhiều dữ liệu nhất ───────────────────────
phase_execute() {
    log ""
    log "═══ PHASE 1: EXECUTE SWEEP (rẻ — không sinh proof) ═══"

    log "── 1a. Quét BATCH (challenges=$CHALLENGES_FIXED cố định) → RQ2 ──"
    log "   Kỳ vọng: cycles tăng ~tuyến tính theo batch, nhưng EVM cost sẽ HẰNG SỐ."
    local failures=0
    gen_bundle "$CHALLENGES_FIXED" || return 1
    for b in $BATCH_EXECUTE; do
        run_execute "$b" "$CHALLENGES_FIXED" 1a || failures=$((failures+1))
    done

    log ""
    log "── 1b. Quét CHALLENGES (batch=1 cố định) → RQ3 ──"
    log "   Kỳ vọng: cycles/proof tăng theo số challenge (nhiều bước fold hơn)."
    for c in $CHALLENGES_SWEEP; do
        gen_bundle "$c" || continue
        run_execute 1 "$c" 1b || failures=$((failures+1))
    done
    if [ "$failures" -gt 0 ]; then
        log "❌ PHASE 1 có $failures điểm execute lỗi; dữ liệu hợp lệ đã được giữ, nhưng sweep chưa hoàn chỉnh."
        return 1
    fi
    log "✅ PHASE 1 xong. Dữ liệu cycles/prover-gas đủ cho phần off-chain của RQ3; RQ2 EVM vẫn cần lớp EVM/proof."
}

# ── PREPARE: sinh cache trước, tách bundle-gen khỏi cgroup peak của execute ─────
phase_prepare() {
    log ""
    log "═══ PREPARE — sinh/cache bundle, KHÔNG chạy SP1 execute ═══"
    local seen=" " c
    for c in $CHALLENGES_FIXED $CHALLENGES_SWEEP $POINT_CHALLENGES; do
        case "$seen" in *" $c "*) continue ;; esac
        seen="$seen$c "
        gen_bundle "$c" || return 1
    done
    log "✅ PREPARE xong. Chạy mode=point trong container mới để memory.peak chỉ thuộc execute."
}

# ── POINT: đúng một cấu hình, dùng cho replicate và peak RAM sạch ──────────────
phase_point() {
    case "$POINT_BATCH" in ''|*[!0-9]*) die "POINT_BATCH phải là số nguyên dương" ;; esac
    case "$POINT_CHALLENGES" in ''|*[!0-9]*) die "POINT_CHALLENGES phải là số nguyên dương" ;; esac
    [ "$POINT_BATCH" -ge 1 ] || die "POINT_BATCH phải ≥1"
    [ "$POINT_CHALLENGES" -ge 1 ] || die "POINT_CHALLENGES phải ≥1"
    log ""
    log "═══ POINT — batch=$POINT_BATCH challenges=$POINT_CHALLENGES h=$TREE_HEIGHT ═══"
    gen_bundle "$POINT_CHALLENGES" || return 1
    SKIP_DONE=0 run_execute "$POINT_BATCH" "$POINT_CHALLENGES" point
}

# ── PHASE 1c: ĐỐI CHỨNG bundle phân biệt ──────────────────────────────────────
# Ghi chú đo đạc của paper nói "N bản sao ≈ N proof phân biệt". Phase này SINH RA
# bằng chứng cho câu đó thay vì để nó là lời khẳng định suông.
phase_distinct() {
    log ""
    log "═══ PHASE 1c: ĐỐI CHỨNG — $DISTINCT_N bundle PHÂN BIỆT vs $DISTINCT_N bản sao ═══"
    local ddir="$ART/distinct_h${TREE_HEIGHT}_c${CHALLENGES_FIXED}_n${DISTINCT_N}"
    local count=0 valid=0
    [ -d "$ddir" ] && count=$(find "$ddir" -maxdepth 1 -type f -name 'bundle_*.bin' | wc -l)
    if [ "$count" -eq "$DISTINCT_N" ] && [ -s "$ddir/vk.bin" ] && \
       jq -e --argjson n "$DISTINCT_N" \
          '.shared_vk==true and .num_bundles==$n' "$ddir/meta.json" >/dev/null 2>&1; then
        valid=1
        log "  ↩️  dùng lại cache distinct hợp lệ: $ddir"
    fi
    if [ "$valid" -ne 1 ]; then
        # Không xóa cache cũ/không rõ nguồn gốc. Sinh vào thư mục mới để tránh
        # bundle thừa hoặc VK bị ghi đè làm sai đối chứng.
        ddir="${ddir}_${RUN_ID}"
        mkdir -p "$ddir"
        log "  ⏳ sinh $DISTINCT_N bundle trong MỘT tiến trình, dùng CHUNG một VK..."
        "$BG/bundle-gen" --challenges "$CHALLENGES_FIXED" --tree-height "$TREE_HEIGHT" \
            --seed 0 --num-bundles "$DISTINCT_N" --out "$ddir" --scratch "$SCRATCH" \
            --json "$JSON" --run-id "$RUN_ID" >>"$LOG" 2>&1 \
            || { log "  ❌ sinh distinct batch thất bại"; return 1; }
    fi

    log "  ▶️  đo bundle PHÂN BIỆT (n=$DISTINCT_N)"
    if ! run_host --execute --artifacts "$ddir" --distinct-dir "$ddir" --json "$JSON" \
             --run-id "$RUN_ID" --phase distinct; then
        log "  ❌ đối chứng bundle phân biệt LỖI — xem $LOG"
        return 1
    fi

    log "  ▶️  đo $DISTINCT_N BẢN SAO để so sánh"
    gen_bundle "$CHALLENGES_FIXED" || return 1
    SKIP_DONE=0 run_execute "$DISTINCT_N" "$CHALLENGES_FIXED" distinct_clone || return 1
    log "✅ PHASE 1c xong. So hai dòng distinct=true / distinct=false ở cùng batch."
}

# ── PHASE 2+3: PROVE — đắt, chạy sau cùng ─────────────────────────────────────
phase_prove() {
    log ""
    log "═══ PHASE 2: LOCAL PROVE ĐƠN LẺ (validate Groth16) ═══"
    log "⚠️  Local Groth16 cần nhiều RAM/disk. Không dùng public prover network."
    gen_bundle "$CHALLENGES_FIXED" || return 1
    if ! run_prove 1 "$CHALLENGES_FIXED" 2; then
        log "❌ Prove đơn lẻ THẤT BẠI — dừng sweep prove để khỏi phí giờ server."
        log "   👉 Giữ execute/cycle results; thử lại trên máy local RAM lớn hơn."
        return 1
    fi
    log "✅ Groth16 chạy được. Tiếp tục sweep."

    log ""
    log "═══ PHASE 3: PROVE SWEEP → RQ1 + RQ2 ═══"
    log "   Kỳ vọng CỐT LÕI: groth16_bytes + evm_calldata HẰNG SỐ bất kể batch."
    for b in $BATCH_PROVE; do
        [ "$b" = "1" ] && continue  # đã đo ở Phase 2
        run_prove "$b" "$CHALLENGES_FIXED" 3
    done
    log "✅ PHASE 3 xong."
}

summary() {
    log ""
    log "═══ TÓM TẮT (run_id=$RUN_ID) ═══"
    log "Kết quả JSONL: $JSON"
    log "Log đầy đủ:    $LOG"
    log "RAM peak container: $(mem_peak) B / limit $(mem_limit) B"
    if command -v jq >/dev/null 2>&1 && [ -f "$JSON" ]; then
        echo "" | tee -a "$LOG"
        echo "── execute (lượt này) ──" | tee -a "$LOG"
        jq -r --arg r "$RUN_ID" 'select(.mode=="execute" and .run_id==$r)
            | "ok=\(.ok) h=\(.cfg.tree_height // "?") ch=\(.challenges) batch=\(.batch) distinct=\(.distinct) cycles=\(.cycles) gas=\(.prover_gas) time=\(.execute_s)s cgroup_peak=\(.cgroup_memory_peak_bytes)B payload=\(.da_payload_bytes)B"' \
            "$JSON" 2>/dev/null | tee -a "$LOG"
        echo "── prove (lượt này) — calldata kỳ vọng HẰNG SỐ ──" | tee -a "$LOG"
        jq -r --arg r "$RUN_ID" 'select(.mode=="prove" and .run_id==$r)
            | "ok=\(.ok) batch=\(.batch) verified=\(.num_verified) pv=\(.pv_bytes)B groth16=\(.groth16_bytes)B calldata=\(.evm_calldata_bytes)B prove=\(.prove_s)s cgroup_peak=\(.cgroup_memory_peak_bytes)B payload_DA=\(.da_payload_bytes)B"' \
            "$JSON" 2>/dev/null | tee -a "$LOG"
    else
        log "(jq không có — bỏ qua bảng tóm tắt, dữ liệu vẫn nằm đủ trong $JSON)"
    fi
    log ""
    log "👉 Mang cả thư mục $RESULTS về máy: scp -r user@server:~/engram/results ./"
    log "   rồi: python3 analyze.py results/results.jsonl --outdir analysis"
}

ARG="${1:-smoke}"
write_run_meta "$ARG"
rc=0
case "$ARG" in
    prepare)  phase_prepare || rc=$? ;;
    point)    phase_point || rc=$? ;;
    smoke)    phase_smoke || rc=$? ;;
    execute)  phase_smoke && phase_execute || rc=$? ;;
    distinct) phase_distinct || rc=$? ;;
    prove)    phase_prove || rc=$? ;;
    all)      phase_smoke && phase_execute && phase_distinct && phase_prove || rc=$? ;;
    *) echo "Dùng: $0 {prepare|point|smoke|execute|distinct|prove|all}"; exit 1 ;;
esac
summary
exit "$rc"
