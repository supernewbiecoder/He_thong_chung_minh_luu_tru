"""
═══════════════════════════════════════════════════════════════════════════════
 [SPEC §E.1.2]  Chi phí niêm phong  ·  [SPEC §I.1.6]  Chi phí zkVM
 [SPEC §G.2.3]  Chi phí phủ đầy đủ  ·  [SPEC §I.1.7]  Kinh tế dựng lại
═══════════════════════════════════════════════════════════════════════════════

 [CHỐT — quyết định D3] MÔ HÌNH CHI PHÍ, không chạy mật mã thật.

 Niêm phong 32 GiB thật mất 1,28 giờ. Với 20 hợp đồng thì là 25,6 giờ — không
 mô phỏng nổi. Nên ta TÍNH chi phí thay vì TRẢ chi phí.

 ── ĐIỀU GÌ VẪN THẬT ──────────────────────────────────────────────────────

   kích thước bằng chứng   13.776 B · 356 B · 296 B   → phí DA và calldata THẬT
   số share Celestia       29                          → phí DA THẬT
   gas EVM                 487.109                     → THẬT, Anvil chạy đúng EVM
   cấu trúc cây, chỉ số thách thức, phán quyết          → THẬT

 ── ĐIỀU GÌ LÀ MÔ HÌNH ────────────────────────────────────────────────────

   nội dung mật mã của bằng chứng, và THỜI GIAN sinh ra nó.

 Mọi hằng số dưới đây mang nhãn [ĐO] kèm nguồn, hoặc [MỞ] nếu chưa đo. Không
 có số nào là ước lượng không nguồn — đó chính là lỗi làm hỏng đặc tả v1, khi
 "27 phút" được giả định rồi chép lại như số đo suốt nhiều vòng.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    CHUNKS_PER_SECTOR,
    COVERAGE_SHA256_PER_WINDOW,
    CPU_COST_USD_PER_HOUR,
    LIMBS_PER_CHUNK,
    POSEIDON2_T3_PERM_US,
    POSEIDON2_T8_PERM_US,
    SEALING_FEE_MULTIPLIER,
    SEAL_FANIN_PHI,
    SEAL_K_DELAY,
    SEAL_RATE,
    ZKVM_FIXED_COST_F,
    ZKVM_MARGINAL_COST_M,
)

# ═══════════════════════════════════════════════════════════════════════════
# 1. NIÊM PHONG — Thuật toán 1d SeqWide  ·  [SPEC §E.1.4]
# ═══════════════════════════════════════════════════════════════════════════


def perms_per_chunk(rate: int = SEAL_RATE) -> int:
    """Số lần hoán vị Poseidon2 t=8 cho MỘT chunk.

    1 lần gieo trạng thái bằng S_{i-1} và các giá trị fan-in, cộng
    ceil(133/rate) lần hấp thụ limb.

        rate 7 → 20 hoán vị  → sàn kẻ gian 22,1 phút
        rate 4 → 35 hoán vị  → sàn 38,4 phút   ← ĐÃ CHỐT
        rate 1 → 134 hoán vị → sàn 2,38 giờ
    """
    return 1 + -(-LIMBS_PER_CHUNK // rate)


TARGET_GHZ = 3.8
"""[CHỐT] Xung nhịp máy đích — Xeon E-2276G. MỌI con số kinh tế trong đặc tả
§E.1.6 và §I.1.7 quy chiếu về mức này, không phải về container 2,1 GHz nơi
`sealbench` chạy. Lẫn hai mức là lệch 1,8 lần trên mọi bảng kinh tế."""

BENCH_GHZ = 2.1
"""[ĐO] Xung nhịp container nơi sealbench đo. Dùng để đối chiếu số đo gốc."""


def seal_seconds(n_chunks: int = CHUNKS_PER_SECTOR, ghz: float = TARGET_GHZ) -> float:
    """[ĐO] Thời gian niêm phong, quy đổi theo xung nhịp.

    Số nền đo trên container Xeon 2,1 GHz bằng `sealbench`:
        Poseidon2 t=8 = 27,72 µs · t=3 = 11,89 µs

    ── ĐIỀU QUAN TRỌNG NHẤT VỀ HÀM NÀY ──────────────────────────────────────

    KHÔNG có tham số `threads`. Đó không phải thiếu sót — Thuật toán 1d có
    0 % công việc song song hoá được, nên máy 64 nhân niêm phong MỘT sector
    không nhanh hơn máy 1 nhân.

    Nhiều nhân vẫn hữu ích, nhưng theo chiều khác: seal NHIỀU SECTOR cùng lúc,
    mỗi nhân một sector. Đó là cách Filecoin vận hành, và là lý do onboard 100 TB
    mất 2,7 ngày trên máy 64 nhân thay vì 171 ngày tuần tự.
    """
    scale = BENCH_GHZ / ghz
    t8 = POSEIDON2_T8_PERM_US * scale
    t3 = POSEIDON2_T3_PERM_US * scale
    per_chunk_us = perms_per_chunk() * t8 + SEAL_K_DELAY * t3
    return n_chunks * per_chunk_us * 1e-6


def attacker_floor_seconds(n_chunks: int = CHUNKS_PER_SECTOR, ghz: float = TARGET_GHZ, speedup: float = 2.0) -> float:
    """Sàn cứng của kẻ gian — thời gian TỐI THIỂU để dựng lại dạng niêm phong.

    Bằng đúng thời gian niêm phong chia cho hệ số phần cứng, vì fan-in φ=6 làm
    ĐIỂM MỐC VÔ DỤNG: muốn tính lại r_j phải có 6 giá trị S, mỗi giá trị lại cần
    6 giá trị nữa, và chỉ 9 tầng là bao đóng phủ hết 8,4 triệu vị trí. Dựng lại
    MỘT vị trí = dựng lại CẢ sector.

    Không có fan-in thì kẻ gian lưu S mỗi 1.000 chunk (268 KB) rồi nối lại chuỗi
    từ giữa trong 0,04 GIÂY — độ sâu tuần tự dài bao nhiêu cũng vô nghĩa.

    `speedup` = giả định kẻ gian có Poseidon2 nhanh hơn bao nhiêu lần. Mặc định 2.
    Nếu ai đó tối ưu được 5 lần thì sàn tụt còn 15 phút. PHẢI viết kèm giả định
    này trong bài, đừng viết như hằng số.
    """
    return seal_seconds(n_chunks, ghz) / speedup


def sealing_fee_wei(n_chunks: int = CHUNKS_PER_SECTOR, eth_usd: float = 3000.0) -> int:
    """[CHỐT B1-a] [SPEC §J.2.4] Phí niêm phong KHÔNG HOÀN LẠI.

    Bằng chi phí CPU của t_seal nhân hệ số an toàn 2.

    VÌ SAO TỒN TẠI: nút bỏ 1,28 giờ CPU niêm phong TRƯỚC khi kiếm được đồng nào,
    còn FR-12 nói ký quỹ chưa kiếm được luôn quay về khách. Không có khoản này
    thì khách mở 1.000 hợp đồng rồi bỏ: nút đốt 1.280 giờ CPU ≈ 12,80 $, khách
    tốn ~1 $ phí giao dịch và lấy lại toàn bộ.
    """
    usd = seal_seconds(n_chunks) / 3600.0 * CPU_COST_USD_PER_HOUR * SEALING_FEE_MULTIPLIER
    return int(usd / eth_usd * 1e18)


# ═══════════════════════════════════════════════════════════════════════════
# 2. CHI PHÍ zkVM  ·  [SPEC §I.1.6]
# ═══════════════════════════════════════════════════════════════════════════


def shard_cycles(n_bundles: int, sha_cycles: int, coverage: bool = True) -> int:
    """Chu kỳ zkVM cho MỘT ô (deadline, mảnh).

    [ĐO] cycles = f + m·N,  R²=1,0000, sai số ngoài mẫu 2,6e-7

    `f` là chi phí nạp và tiền xử lý tệp khoá xác minh 4,7 MB — trả MỘT LẦN cho
    cả ô. Đây là lý do NFR-05 tồn tại: chia nhỏ quá thì trả f nhiều lần cho
    những mảnh gần rỗng. Ở N=1.000 với D·S=768 thì f chiếm 75,6 % tổng.

    `coverage` = chi phí chứng minh phủ đầy đủ (§G.2). Nó là MỘT LẦN cho cả ô,
    không phải một lần mỗi hợp đồng — nên với ô 625 hợp đồng nó chỉ chiếm
    0,006–0,12 %, tức nhiễu.
    """
    total = ZKVM_FIXED_COST_F + ZKVM_MARGINAL_COST_M * n_bundles
    if coverage:
        total += COVERAGE_SHA256_PER_WINDOW * sha_cycles
    return int(total)


def coverage_cost_ratio(sha_cycles: int) -> float:
    """Chi phí phủ đầy đủ so với chi phí xác minh MỘT bundle.

    [MỞ C2-b] c_sha chưa đo, nên quét ba giá trị:
        1.000  →  3,65 %   không đáng kể
        5.000  → 18,27 %   chấp nhận được
       20.000  → 73,07 %   bắt đầu đau

    Và spam KHÔNG làm nó bùng nổ: bội số tối đa là 171 lần (block đầy so với
    block rỗng) rồi dừng ở 411.200 sha256 — đúng như sự thật nền thứ ba dự đoán,
    trần block Celestia là trần cứng.
    """
    return COVERAGE_SHA256_PER_WINDOW * sha_cycles / ZKVM_MARGINAL_COST_M


def network_daily_cycles(n_deals: int, deadlines: int, shards: int, sha_cycles: int) -> int:
    """Tổng chu kỳ toàn mạng mỗi ngày: D·S·f + m·N (cộng phủ đầy đủ mỗi ô).

    [SPEC NFR-05] Chọn D·S_ns ≤ N/20 để phần f ≤ 20 %.

    NGƯỢC TRỰC GIÁC: mạng NHỎ phải chia ÍT. Chia nhỏ ở mạng nhỏ nghĩa là trả f
    nhiều lần cho những mảnh gần rỗng.
    """
    cells = deadlines * shards
    per_cell = max(1, n_deals // max(1, cells))
    return cells * shard_cycles(per_cell, sha_cycles)


# ═══════════════════════════════════════════════════════════════════════════
# 3. KINH TẾ DỰNG LẠI  ·  [SPEC §I.1.7]
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RegenEconomics:
    """So CHI PHÍ GIỮ với CHI PHÍ DỰNG LẠI.

    Phân tích v1 so THỜI GIAN dựng lại với CỬA SỔ NỘP và ra kết luận sai. Bảng
    này so CHI PHÍ với CHI PHÍ, và kết luận không phụ thuộc kẻ tấn công có bao
    nhiêu lõi.
    """

    keep_usd_per_month: float
    regen_usd_per_month: float

    @property
    def margin(self) -> float:
        return self.regen_usd_per_month / max(1e-12, self.keep_usd_per_month)


def regen_economics(
    n_chunks: int = CHUNKS_PER_SECTOR,
    disk_usd_per_gb_month: float = 0.00024,
    cpu_usd_per_hour: float = CPU_COST_USD_PER_HOUR,
    regens_per_day: int = 1,
) -> RegenEconomics:
    """[SPEC §I.1.6] Biên 1.600×–12.800× tuỳ giá CPU.

    Giữ {R,S}: 64 byte mỗi chunk = 512 MiB cho một sector = 1,6 % dữ liệu.
    Dựng lại: t_seal giờ CPU mỗi lần, mỗi epoch một lần.

    Kết luận: xoá dạng niêm phong rồi dựng lại ĐẮT HƠN giữ nó ít nhất 1.600 lần.
    Tấn công "nén và dựng lại" KHÔNG CÓ ĐỘNG CƠ KINH TẾ.
    """
    keep_gb = n_chunks * 64 / 1024**3
    keep = keep_gb * disk_usd_per_gb_month
    regen = seal_seconds(n_chunks) / 3600.0 * cpu_usd_per_hour * regens_per_day * 30
    return RegenEconomics(keep, regen)


def capacity_bound_cores(n_deals: int, epoch_hours: float = 24.0) -> float:
    """[SPEC §E.1.6] Chặn cứng về NĂNG LỰC — điều kinh tế không nói được.

    Gian lận trên n hợp đồng đòi bao nhiêu nhân CPU chạy 24/24 chỉ để dựng lại.
    Gian trên 1.000 hợp đồng cần 53 nhân — đó là một trang trại CPU, không phải
    một thủ thuật lưu trữ.
    """
    return n_deals * (seal_seconds() / 3600.0) / epoch_hours
