"""
[SỬA — nhận xét phản biện P0.3] Mắt xích thứ tư: guest đã xét HẾT chưa.

 Nhận xét chỉ ra rằng `num_verified == expectedDealCount` KHÔNG đủ, vì
 num_verified lấy từ `len(leaves)` — số lá mà guest tự sinh ra. Ba đường
 vòng mà phép kiểm cũ không chặn:

   ① một ô xét 3 trong 13 hợp đồng rồi trả về
        → ô vẫn tính là "đã phủ", tổng vẫn có thể khớp nếu ô khác bù

   ② một ô nhồi thêm hợp đồng ngoài phạm vi để bù cho ô trả thiếu
        → TỔNG khớp, nhưng nghĩa vụ thật không được xét

   ③ hai ChildProof của cùng một ô dựng từ hai sổ khác nhau
        → ít nhất một bên dùng sổ sai, không ai phát hiện

 Bản vá kiểm theo TỪNG Ô, và so với |E_cell| lấy từ sổ thành viên.
"""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
for sub in ("common", "worker", "aggregator"):
    sys.path.insert(0, str(_root / sub / "src"))

from engram_common.verdict import Verdict  # noqa: E402
from aggregator.reconcile import (  # noqa: E402
    CardinalityMismatch,
    reconcile_shard_results,
)
from worker.verify import ShardResult  # noqa: E402


def _cell(deadline: int, shard: int, n_expected: int, n_returned: int | None = None):
    """Một ChildProof khai `n_expected` hợp đồng, trả về `n_returned` phán quyết."""
    if n_returned is None:
        n_returned = n_expected
    verdicts = {
        (bytes([shard]) * 20, bytes([deadline, i]) * 16): Verdict.PASS
        for i in range(n_returned)
    }
    return ShardResult(
        deadline=deadline,
        shard=shard,
        expected_count=n_expected,
        verdicts=verdicts,
        results_root=bytes(32),
    )


def test_o_trung_thuc_thi_qua():
    ev = reconcile_shard_results([_cell(1, 0, 13), _cell(1, 1, 13)])
    assert sum(ev.cell_expected.values()) == 26
    assert len(ev.verdicts) == 26


def test_o_xet_thieu_bi_chan():
    """① Khai 13 hợp đồng nhưng chỉ trả về 3 phán quyết."""
    try:
        reconcile_shard_results([_cell(1, 0, 13, n_returned=3)])
        raise AssertionError("xét thiếu phải bị chặn")
    except CardinalityMismatch as e:
        assert "3" in str(e) and "13" in str(e)
    print("\n  ô xét 3/13 rồi trả về → BỊ CHẶN")


def test_o_nhoi_thua_bi_chan():
    """② Nhồi thêm hợp đồng ngoài phạm vi để bù cho ô khác."""
    try:
        reconcile_shard_results([_cell(1, 0, 13, n_returned=20)])
        raise AssertionError("nhồi thừa phải bị chặn")
    except CardinalityMismatch:
        pass
    print("  ô nhồi 20 phán quyết cho 13 kỳ vọng → BỊ CHẶN")


def test_bu_tru_giua_hai_o_bi_chan():
    """② dạng nguy hiểm hơn: ô này thiếu, ô kia thừa, TỔNG vẫn khớp.

    Đây là đường mà phép kiểm theo tổng KHÔNG BAO GIỜ bắt được — và là lý do
    phải kiểm theo từng ô.
    """
    thieu = _cell(1, 0, 13, n_returned=8)
    thua = _cell(1, 1, 13, n_returned=18)
    assert len(thieu.verdicts) + len(thua.verdicts) == 26  # tổng vẫn khớp
    try:
        reconcile_shard_results([thieu, thua])
        raise AssertionError("bù trừ giữa hai ô phải bị chặn")
    except CardinalityMismatch:
        pass
    print("  ô A thiếu 5, ô B thừa 5, TỔNG khớp → VẪN BỊ CHẶN")


def test_hai_ban_cung_o_khai_lech_bi_chan():
    """③ Hai ChildProof của cùng một ô khai |E_cell| khác nhau."""
    a = _cell(1, 0, 13)
    b = _cell(1, 0, 11)
    try:
        reconcile_shard_results([a, b])
        raise AssertionError("hai bản khai lệch phải bị chặn")
    except CardinalityMismatch as e:
        assert "13" in str(e) and "11" in str(e)
    print("  hai bản cùng ô khai 13 và 11 → BỊ CHẶN")


def test_du_thua_dung_van_qua():
    """Hai worker trung thực cho cùng một ô thì phải QUA — dư thừa là tính năng."""
    ev = reconcile_shard_results([_cell(1, 0, 13), _cell(1, 0, 13)])
    assert ev.cell_expected[(1, 0)] == 13
    assert len(ev.verdicts) == 13          # hoà giải, không nhân đôi
    assert ev.stats.childproofs_seen == 2
    print("  hai worker trung thực cùng ô → QUA, hoà giải đúng")


if __name__ == "__main__":
    import inspect

    mod = sys.modules[__name__]
    n = 0
    for name, fn in list(vars(mod).items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            fn()
            n += 1
    print(f"\n  {n} test mắt xích thứ tư: tất cả đều đạt.")
