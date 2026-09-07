"""
[SPEC §D.3 / §J.2.6] Sổ thành viên chặn bỏ sót có chọn lọc.

 Test này kiểm tính chất, không kiểm công thức: BỚT MỘT MỤC PHẢI RA GIÁ TRỊ
 KHÁC. Đó là toàn bộ cơ chế, và mọi thứ khác chỉ là chi tiết hiện thực.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engram_common.membership import (  # noqa: E402
    DealRecord, MembershipEntry, MembershipKind, MembershipRegistry,
    SnapshotMismatch, replay, verify_registry,
)

P = b"\x9f" * 20


def _registry(n: int = 12) -> MembershipRegistry:
    entries = [
        MembershipEntry(MembershipKind.DEAL_ACTIVE, bytes([i]) * 32, bytes(32)) for i in range(n)
    ]
    deals = [
        DealRecord(P, bytes([i]) * 32, bytes([i + 100]) * 32, i % 4, i % 2) for i in range(n)
    ]
    return MembershipRegistry(epoch=7, cut_height=1_595_500, entries=entries, deals=deals)


def test_bot_mot_muc_bi_chan():
    """Đây là lỗ hổng §J.2.6, và đây là bản sửa."""
    r = _registry()
    sid = r.snapshot_id()

    thieu = MembershipRegistry(r.epoch, r.cut_height, r.entries[:-1], r.deals[:-1])
    try:
        verify_registry(thieu, sid, r.epoch)
        raise AssertionError("bỏ sót phải bị chặn")
    except SnapshotMismatch:
        pass
    print("\n  bớt một mục → snapshot_id khác → guest dừng")


def test_bot_muc_o_giua_cung_bi_chan():
    """Không chỉ mục cuối — bớt ở giữa cũng đổi toàn bộ chuỗi về sau."""
    r = _registry()
    sid = r.snapshot_id()
    giua = MembershipRegistry(r.epoch, r.cut_height, r.entries[:5] + r.entries[6:], r.deals)
    try:
        verify_registry(giua, sid, r.epoch)
        raise AssertionError("bỏ sót giữa chừng phải bị chặn")
    except SnapshotMismatch:
        pass


def test_doi_thu_tu_bi_chan():
    """Sổ là CHUỖI, không phải TẬP HỢP. Đổi thứ tự là giá trị khác."""
    r = _registry()
    sid = r.snapshot_id()
    dao = list(r.entries)
    dao[2], dao[3] = dao[3], dao[2]
    assert replay(dao) != sid


def test_sai_epoch_bi_chan():
    """Sổ của epoch khác không dùng lại được — chặn phát lại bằng chứng cũ."""
    r = _registry()
    try:
        verify_registry(r, r.snapshot_id(), r.epoch + 1)
        raise AssertionError("sai epoch phải bị chặn")
    except SnapshotMismatch:
        pass


def test_so_dung_thi_qua():
    r = _registry()
    verify_registry(r, r.snapshot_id(), r.epoch)


def test_danh_sach_ky_vong_tat_dinh_va_sap_xep():
    """Guest lặp trên danh sách này, nên thứ tự phải tất định — nếu không thì
    results_root của hai worker trung thực cũng khác nhau."""
    r = _registry()
    a = r.expected_for(1, 1)
    b = r.expected_for(1, 1)
    assert [d.deal_id for d in a] == [d.deal_id for d in b]
    assert a == sorted(a, key=lambda d: (d.provider_id, d.deal_id))


def test_kind_dem_phai_32_byte():
    """Phải khớp byte-để-byte với `bytes32 constant` trong Solidity — chuỗi ở
    ĐẦU, đệm số 0 ở SAU. Đệm sai đầu là giá trị khác, im lặng."""
    for k in MembershipKind:
        b = k.as_bytes32()
        assert len(b) == 32
        assert b.startswith(k.value)
        assert b[len(k.value):] == bytes(32 - len(k.value))


if __name__ == "__main__":
    import inspect
    mod = sys.modules[__name__]
    n = 0
    for name, fn in list(vars(mod).items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            fn(); n += 1
    print(f"  {n} test sổ thành viên: tất cả đều đạt.")
