"""
[SPEC §H.1.6 / CHỐT C1-b] Cầu dao chỉ bật khi mạng đủ worker.

 Test quan trọng nhất ở đây là `test_mang_nho_thi_khong_nha`: nó kiểm rằng cầu
 dao TỪ CHỐI hoạt động khi mạng nhỏ. Nghe ngược, nhưng đó chính là điểm — dưới
 ngưỡng thì kẻ xấu DoS vài máy là VOID cả epoch, biến cơ chế bảo vệ thành công
 cụ tấn công rẻ tiền.
"""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "common" / "src"))
sys.path.insert(0, str(_root / "aggregator" / "src"))
sys.path.insert(0, str(_root / "worker" / "src"))

from aggregator.circuit_breaker import evaluate  # noqa: E402
from worker.lottery import cooldown_deadlines  # noqa: E402

CD = cooldown_deadlines(3.1 * 3600, 300 * 6.0)  # = 6


def _ev(n_workers: int, coverage: float):
    return evaluate(
        covered_cells=int(768 * coverage), expected_cells=768,
        n_workers=n_workers, n_shards=16, cooldown=CD,
    )


def test_mang_du_lon_va_phu_thap_thi_nha():
    r = _ev(224, 0.30)
    assert r.tripped and r.threshold_met
    print(f"\n  224 worker · phủ 30 % → VOID")


def test_phu_cao_thi_khong_nha_du_mang_lon():
    assert not _ev(224, 0.80).tripped


def test_mang_nho_thi_khong_nha():
    """ĐÂY LÀ TEST QUAN TRỌNG NHẤT.

    Phủ thấp NHƯNG mạng nhỏ → KHÔNG nhả. Vì dưới ngưỡng, tín hiệu "phủ thấp"
    không phân biệt được sự cố hạ tầng với một cuộc DoS vài máy.
    """
    r = _ev(20, 0.30)
    assert not r.tripped, "mạng nhỏ mà nhả là mở đường cho DoS"
    assert not r.threshold_met
    assert "công cụ tấn công" in r.reason
    print(f"  20 worker · phủ 30 % → KHÔNG nhả · {r.required_workers} worker mới đủ")


def test_nguong_dung_bang_cong_thuc():
    r = _ev(100, 0.9)
    assert r.required_workers == 16 * 2 * (CD + 1) == 224


def test_ly_do_luon_giai_thich_duoc():
    """Vận hành phải biết VÌ SAO, không chỉ biết CÓ hay KHÔNG."""
    for n, c in ((224, 0.3), (224, 0.8), (20, 0.3)):
        assert len(_ev(n, c).reason) > 20


if __name__ == "__main__":
    import inspect
    mod = sys.modules[__name__]
    n = 0
    for name, fn in list(vars(mod).items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            fn(); n += 1
    print(f"\n  {n} test cầu dao: tất cả đều đạt.")
