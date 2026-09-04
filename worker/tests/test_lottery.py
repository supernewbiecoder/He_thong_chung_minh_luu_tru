"""
[SPEC §J.2.3] Xổ số worker — ba bộ lọc.

 ① SỐNG      [CHỐT F3] worker rời mạng bị loại, có đường quay lại
 ② XOAY VÒNG [CHỐT F2] worker còn bận chứng minh không bị giao thêm
 ③ TRẦN      [CHỐT F1-c] thích ứng theo quy mô, luôn khả thi

 ── HAI LỖI TEST NÀY BẮT ĐƯỢC KHI VIẾT ───────────────────────────────────

 ① `assigned_count or {}` LOẠI BỎ dict rỗng do người gọi truyền vào, vì dict
    rỗng là falsy. Trần im lặng ngừng hoạt động.

 ② Trần CỐ ĐỊNH 5 % chỉ ràng buộc khi có ≥ 40 worker; dưới mức đó quy tắc thoát
    kích hoạt và trần thành trang trí. Đã đổi sang trần thích ứng (F1-c).
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "common" / "src"))
sys.path.insert(0, str(_root / "worker" / "src"))

from worker.lottery import (  # noqa: E402
    DEFAULT_MISS_THRESHOLD, LotteryStats, WorkerEntry, adaptive_cap_ratio,
    cooldown_deadlines, min_workers_for_cap, record_outcome, required_workers,
    worker_lottery,
)

BEACON = b"\xbe" * 32


def _pool(n: int, rich: int = 30) -> list[WorkerEntry]:
    return [WorkerEntry(bytes([i]), (rich if i == 0 else 1) * 10**18) for i in range(n)]


# ═══════════════════════════════════════════════════════════════════════════
# ③ TRẦN THÍCH ỨNG  [CHỐT F1-c]
# ═══════════════════════════════════════════════════════════════════════════


def test_tran_thich_ung_luon_kha_thi():
    """Trần cố định 5 % cần ≥ 40 worker mới ràng buộc. Trần thích ứng nới ra ở
    mạng nhỏ, nhưng nới TƯỜNG MINH thay vì im lặng không hoạt động."""
    assert min_workers_for_cap() == 40
    assert adaptive_cap_ratio(5) == 0.4      # nới, và biết mình nới
    assert adaptive_cap_ratio(40) == 0.05
    assert adaptive_cap_ratio(200) == 0.05   # không chặt hơn sàn


def test_du_worker_thi_tran_chan_duoc_ke_giau():
    pool, cnt, got = _pool(60), {}, Counter()
    for d in range(200):
        for w in worker_lottery(BEACON, d % 4, pool, deadline=d,
                                assigned_count=cnt, total_cells=200, cooldown=0):
            got[w.worker_id[0]] += 1
    share = got[0] / sum(got.values())
    assert share < 0.06, f"kẻ giàu chiếm {share:.1%}"
    print(f"\n  60 worker: kẻ giàu nắm 33 % cọc chỉ được {share:.1%} số ô")


# ═══════════════════════════════════════════════════════════════════════════
# ② XOAY VÒNG  [CHỐT F2]
# ═══════════════════════════════════════════════════════════════════════════


def test_cooldown_suy_ra_tu_thoi_gian_chung_minh():
    """Sinh bằng chứng SP1 tốn hàng giờ, deadline chỉ 30 phút."""
    assert cooldown_deadlines(3.1 * 3600, 1800) == 6
    assert cooldown_deadlines(1800, 1800) == 0
    # Ràng buộc này CHẶT HƠN trần khe rất nhiều: 224 so với 40.
    assert required_workers(16, 2, 6) == 224


def test_worker_dang_ban_khong_bi_giao_them():
    pool, cnt = _pool(60, rich=1), {}
    seen: dict[int, int] = {}
    for d in range(20):
        for w in worker_lottery(BEACON, 0, pool, deadline=d, assigned_count=cnt,
                                total_cells=100, cooldown=6):
            prev = seen.get(w.worker_id[0])
            if prev is not None:
                assert d - prev > 6, f"worker nhận việc lại sau {d-prev} deadline, cần > 6"
            seen[w.worker_id[0]] = d
    print(f"\n  cooldown=6: không worker nào nhận hai việc cách nhau ≤ 6 deadline")


def test_thieu_worker_thi_noi_cooldown_chu_khong_bo_trong_o():
    """Bận là ràng buộc VẬT LÝ, nhưng ô không được phủ còn tệ hơn.

    Quy tắc thoát ưu tiên PHỦ. Nhưng nó phải BÁO LẠI, để vận hành biết mạng đang
    thiếu worker chứ không tưởng mọi thứ bình thường.
    """
    st = LotteryStats()
    pool, cnt = _pool(3, rich=1), {}
    worker_lottery(BEACON, 0, pool, deadline=0, assigned_count=cnt, total_cells=10, cooldown=6)
    worker_lottery(BEACON, 0, pool, deadline=1, assigned_count=cnt, total_cells=10,
                   cooldown=6, stats=st)
    assert st.relaxed_cooldown, "phải báo là đã nới cooldown"
    assert st.chosen == 2, "vẫn phải phủ đủ r=2"


# ═══════════════════════════════════════════════════════════════════════════
# ① LỌC SỐNG  [CHỐT F3]
# ═══════════════════════════════════════════════════════════════════════════


def test_worker_bo_viec_lien_tiep_thi_bi_dinh_chi():
    w = WorkerEntry(b"\x01", 10**18)
    for d in range(DEFAULT_MISS_THRESHOLD):
        assert w.is_live(d), "chưa đủ ngưỡng thì vẫn sống"
        record_outcome(w, False, d)
    assert not w.is_live(DEFAULT_MISS_THRESHOLD), "đủ ngưỡng phải bị đình chỉ"
    print(f"\n  bỏ {DEFAULT_MISS_THRESHOLD} việc liên tiếp → đình chỉ tới deadline {w.suspended_until_deadline}")


def test_dinh_chi_co_thoi_han_va_reset_bo_dem():
    """PHẢI hữu hạn. Cấm vĩnh viễn thì một sự cố mạng là mất cả khoản cọc, và
    không ai dám làm worker."""
    w = WorkerEntry(b"\x01", 10**18)
    for d in range(DEFAULT_MISS_THRESHOLD):
        record_outcome(w, False, d)
    until = w.suspended_until_deadline
    assert w.is_live(until), "hết hạn thì vào lại bể"
    assert w.consecutive_misses == 0, "bộ đếm phải reset"


def test_nop_duoc_thi_bo_dem_ve_khong():
    w = WorkerEntry(b"\x01", 10**18)
    record_outcome(w, False, 0)
    record_outcome(w, True, 1)
    assert w.consecutive_misses == 0


def test_worker_bi_dinh_chi_bi_loai_khoi_xo_so():
    st = LotteryStats()
    pool, cnt = _pool(20, rich=1), {}
    for w in pool[:5]:
        w.suspended_until_deadline = 100
    worker_lottery(BEACON, 0, pool, deadline=10, assigned_count=cnt,
                   total_cells=100, cooldown=0, stats=st)
    assert st.dropped_suspended == 5
    print(f"\n  5 worker đình chỉ bị loại khỏi bể trước khi rút thăm")


def test_dict_rong_van_duoc_cap_nhat():
    """Bắt lại lỗi ① nếu ai đó đổi về `or {}`."""
    cnt: dict[bytes, int] = {}
    worker_lottery(BEACON, 0, _pool(50, rich=1), deadline=0,
                   assigned_count=cnt, total_cells=100)
    assert sum(cnt.values()) == 2


if __name__ == "__main__":
    import inspect
    mod = sys.modules[__name__]
    for name, fn in list(vars(mod).items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            fn()
    print("\n  Tất cả đều đạt.")
