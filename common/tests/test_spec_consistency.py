"""
═══════════════════════════════════════════════════════════════════════════════
 ĐỐI CHIẾU MÃ ↔ ĐẶC TẢ
═══════════════════════════════════════════════════════════════════════════════

 Bài báo tuyên bố những con số cụ thể. Mã tính ra những con số cụ thể. Test này
 kiểm hai bên khớp nhau.

 ── VÌ SAO CẦN ─────────────────────────────────────────────────────────────

 Trong quá trình làm, BỐN lần mã và đặc tả lệch nhau mà không ai phát hiện cho
 tới khi ngồi đo:

   ① fan-in `(i·a+b) % i` luôn trả cùng một vị trí — bậc 6 trên giấy, bậc 1
     trong thực tế
   ② bao đóng phụ thuộc: đặc tả ghi "phủ hết", đo được 23,9 %
   ③ bảng kinh tế dùng xung nhịp container 2,1 GHz thay vì máy đích 3,8 GHz —
     lệch 1,8 lần trên mọi biên
   ④ `assigned_count or {}` loại bỏ dict rỗng, trần khe im lặng ngừng hoạt động

 Cả bốn đều thuộc loại "đúng trên giấy, sai khi chạy". Test này bắt loại ③ ngay
 lập tức, và làm hai loại kia khó lọt hơn.

 Khi một con số ở đây đổi, PHẢI sửa cả đặc tả — hoặc ngược lại. Không được sửa
 một bên rồi nới ngưỡng test cho khớp.
"""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
for sub in ("common", "worker", "provider"):
    sys.path.insert(0, str(_root / sub / "src"))

from engram_common import blob as B  # noqa: E402
from engram_common import constants as C  # noqa: E402
from engram_common import costs as CO  # noqa: E402
from engram_common.clock import PublicValues  # noqa: E402


def _close(actual: float, spec: float, tol: float = 0.03) -> bool:
    return abs(actual - spec) / spec <= tol


# ═══════════════════════════════════════════════════════════════════════════
# 1. BỀ MẶT ON-CHAIN  ·  [SPEC §K.1 / §I.1.1]
# ═══════════════════════════════════════════════════════════════════════════


def test_public_values_296_byte():
    """[SPEC §D.2.1] Bố cục PHẢI khớp bit-để-bit với _decodePublicValues
    trong EngramManager.sol. Lệch là bằng chứng hợp lệ bị từ chối im lặng."""
    pv = PublicValues(1, b"\x01" * 32, b"\x02" * 32, 1, b"\x03" * 32, b"\x04" * 32,
                      b"\x05" * 32, b"\x06" * 32, b"\x07" * 20, b"\x08" * 32, b"\x09" * 32, 1)
    assert len(pv.pack()) == 296
    assert PublicValues.unpack(pv.pack()) == pv


def test_calldata_844_byte():
    """[SPEC §K.1] 356 Groth16 + 296 public values + mào đầu ABI."""
    assert C.GROTH16_PROOF_BYTES + C.PUBLIC_VALUES_BYTES == 652
    assert C.CALLDATA_BYTES == 844


# ═══════════════════════════════════════════════════════════════════════════
# 2. LỚP DA  ·  [SPEC §G.1.3]
# ═══════════════════════════════════════════════════════════════════════════


def test_bundle_van_la_29_share():
    """Chuyển sang share v1 và bỏ provider_sig KHÔNG đổi số share, nên kinh tế
    DA giữ nguyên. Nếu đổi thì mọi con số phí trong §G.1 sai theo."""
    total = C.BUNDLE_SIZE_BYTES + B.HEADER_SIZE
    assert B.shares_for(total) == 29
    assert B.pfb_gas(total) == 183_784
    assert abs(B.pfb_fee_usd(total) - 0.00024) < 1e-5


def test_share_v1_signer_20_byte():
    """[ext] Celestia SignerSize = 20. ĐÂY LÀ NEO CHỐNG MẠO DANH BLOB (§J.2.1).
    Đổi số này là đổi nền của cả bản sửa."""
    assert C.SIGNER_SIZE == 20
    assert C.FIRST_SHARE_PAYLOAD_V1 == 458
    assert C.CONT_SHARE_PAYLOAD == 482


# ═══════════════════════════════════════════════════════════════════════════
# 3. NIÊM PHONG  ·  [SPEC §E.1.4]
# ═══════════════════════════════════════════════════════════════════════════


def test_seal_khop_dac_ta():
    """§E.1.4 ghi 1,28 giờ và sàn kẻ gian 38,4 phút, ở máy đích 3,8 GHz.

    Lỗi ③: bảng kinh tế từng dùng xung nhịp container 2,1 GHz, lệch 1,8 lần.
    """
    assert CO.TARGET_GHZ == 3.8, "mọi con số kinh tế quy chiếu về máy đích"
    assert _close(CO.seal_seconds() / 3600, 1.28), f"{CO.seal_seconds()/3600:.2f} vs 1,28 giờ"
    assert _close(CO.attacker_floor_seconds() / 60, 38.4), \
        f"{CO.attacker_floor_seconds()/60:.1f} vs 38,4 phút"


def test_seqwide_35_hoan_vi_moi_chunk():
    """rate=4 → 1 gieo + ⌈133/4⌉ = 35 hoán vị."""
    assert C.SEAL_RATE == 4
    assert C.SEAL_FANIN_PHI == 6
    assert CO.perms_per_chunk() == 35


def test_kinh_te_dung_lai():
    """[SPEC §E.1.6] Biên 1.600×–12.800× tuỳ giá CPU."""
    assert _close(CO.regen_economics(cpu_usd_per_hour=0.005).margin, 1600, 0.05)
    assert _close(CO.regen_economics(cpu_usd_per_hour=0.04).margin, 12800, 0.05)
    assert _close(CO.capacity_bound_cores(1000), 53.3, 0.05)


# ═══════════════════════════════════════════════════════════════════════════
# 4. CHI PHÍ zkVM  ·  [SPEC §I.1.6]
# ═══════════════════════════════════════════════════════════════════════════


def test_hoi_quy_chi_phi_zkvm():
    """cycles = f + m·N, R²=1,0000."""
    assert C.ZKVM_FIXED_COST_F == 45.385e9
    assert C.ZKVM_MARGINAL_COST_M == 11.255e9
    assert CO.shard_cycles(13, 0, coverage=False) == int(45.385e9 + 13 * 11.255e9)


def test_phu_day_du_co_tran_cung():
    """[SPEC §G.2.3] Spam nhân tối đa 171 lần rồi DỪNG, vì trần block Celestia
    là trần cứng. Đây là điều khiến chi phí phủ đầy đủ chặn trên được."""
    assert C.COVERAGE_SHA256_PER_WINDOW == 411_200
    assert _close(CO.coverage_cost_ratio(1_000) * 100, 3.65)
    assert _close(CO.coverage_cost_ratio(5_000) * 100, 18.27)
    assert _close(CO.coverage_cost_ratio(20_000) * 100, 73.07)


def test_nfr05_chia_it_khi_mang_nho():
    """[SPEC §I.1.6] NGƯỢC TRỰC GIÁC: mạng NHỎ phải chia ÍT, vì chia nhỏ nghĩa
    là trả f nhiều lần cho những mảnh gần rỗng."""
    assert C.recommended_shard_count(10_000, 48) == 10
    assert C.recommended_shard_count(1_000, 48) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 5. QUY MÔ MẠNG  ·  [SPEC §I.1.7 / §A.4.3]
# ═══════════════════════════════════════════════════════════════════════════


def test_worker_toi_thieu_224_khong_phai_40():
    """[SPEC §I.1.7] Xoay vòng chặt hơn trần khe 5,6 lần.

    Định cỡ mạng theo 40 là định cỡ theo ràng buộc YẾU NHẤT, và mạng sẽ nghẽn ở
    tầng worker trước khi ai kịp lo về tập trung cọc.
    """
    from worker.lottery import cooldown_deadlines, min_workers_for_cap, required_workers

    cooldown = cooldown_deadlines(3.1 * 3600, 300 * 6.0)
    assert cooldown == 6, "t_worker ~3,1 giờ / deadline 30 phút"
    assert required_workers(16, 2, cooldown) == 224
    assert min_workers_for_cap() == 40
    assert required_workers(16, 2, cooldown) > 5 * min_workers_for_cap()


def test_tran_thich_ung_luon_kha_thi():
    """[SPEC §A.4.3] Trần cố định 5 % im lặng không hoạt động dưới 40 worker."""
    from worker.lottery import adaptive_cap_ratio

    assert adaptive_cap_ratio(5) == 0.4
    assert adaptive_cap_ratio(40) == 0.05
    assert adaptive_cap_ratio(1000) == 0.05


# ═══════════════════════════════════════════════════════════════════════════
# 6. FAN-IN  ·  [SPEC §J.1.3]
# ═══════════════════════════════════════════════════════════════════════════


def test_bao_dong_fan_in_khong_phai_100_phan_tram():
    """[SPEC §J.1.3] Đặc tả TỪNG ghi "phủ hết 8,4 triệu vị trí" — phép đếm
    6⁹ > 8,4 triệu bỏ qua va chạm. Đo được: bão hoà ở ~24 %.

    24 % vẫn đủ dùng, nhưng biên an toàn phải tính theo 24 %, không theo 100 %.
    """
    from provider.sealing import fanin_positions

    n, replica = 20_000, b"\xab" * 32
    frontier, seen = {n - 1}, {n - 1}
    for _ in range(15):
        nxt = set()
        for i in frontier:
            for p in fanin_positions(i, replica):
                if p not in seen:
                    seen.add(p)
                    nxt.add(p)
        frontier = nxt
        if not frontier:
            break
    ratio = len(seen) / n
    assert 0.15 < ratio < 0.40, f"bao đóng {ratio:.1%} — đặc tả ghi ~24 %"


if __name__ == "__main__":
    import inspect

    mod = sys.modules[__name__]
    n = 0
    for name, fn in list(vars(mod).items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            fn()
            n += 1
    print(f"  {n} phép đối chiếu mã ↔ đặc tả: tất cả đều khớp.")
