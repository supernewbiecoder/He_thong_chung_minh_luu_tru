"""
[SPEC §E.1.4 ② · §J.1.3] Fan-in phải làm ĐIỂM MỐC vô dụng.

 ── VÌ SAO TEST NÀY TỒN TẠI ───────────────────────────────────────────────

 Không có fan-in, kẻ gian lưu S mỗi 1.000 chunk — hết 268 KB — rồi nối lại
 chuỗi từ mắt gần nhất trong 0,04 GIÂY. Độ sâu tuần tự dài bao nhiêu cũng vô
 nghĩa nếu nối được từ giữa.

 Fan-in φ=6 chặn điều đó: tính lại r_j cần 6 giá trị S, mỗi giá trị lại cần 6
 giá trị nữa. Chỉ 9 tầng là bao đóng phủ hết 8,4 triệu vị trí.

 NHƯNG tính chất đó KHÔNG tự động đúng — nó phụ thuộc cách chọn π_t(i). Bản
 đầu tiên dùng `(i·a + b) % i` và thoái hoá về cùng một vị trí cho mọi t, vì
 `i·a % i == 0`. Fan-in bậc 6 trên giấy, bậc 1 trong thực tế.

 Test này kiểm tính chất THẬT SỰ được bảo toàn, không kiểm công thức.
"""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "common" / "src"))
sys.path.insert(0, str(_root / "provider" / "src"))

from provider.sealing import fanin_positions  # noqa: E402

REPLICA = b"\xab" * 32


def test_fanin_khong_thoai_hoa():
    """φ-1 vị trí phải KHÁC NHAU, không dồn về một chỗ."""
    for i in (10, 100, 1000, 100_000):
        pos = fanin_positions(i, REPLICA)
        assert len(set(pos)) >= 4, f"fan-in tại i={i} thoái hoá: {pos}"


def test_fanin_luon_tro_ve_truoc():
    """π_t(i) < i — không được phụ thuộc vào tương lai, nếu không chuỗi không
    tính được theo thứ tự."""
    for i in (1, 2, 50, 12_345):
        assert all(0 <= p < i for p in fanin_positions(i, REPLICA))


def test_bao_dong_lan_du_rong():
    """Bao đóng phụ thuộc của MỘT vị trí phải lan đủ rộng để điểm mốc vô dụng.

    ── MỘT TUYÊN BỐ SAI TRONG ĐẶC TẢ, ĐO RA MỚI BIẾT ────────────────────────

    §E.1.4 và §J.1.3 viết "với φ=6, chỉ 9 tầng là bao đóng phủ HẾT 8,4 triệu vị
    trí". Đó là phép đếm 6⁹ = 10,1 triệu > 8,4 triệu — bỏ qua VA CHẠM và bỏ qua
    việc vị trí co dần về 0.

    Đo thật: bao đóng BÃO HOÀ ở ~24 %, không phải 100 %.

      tầng 5  → 10,1 %      tầng 9  → 23,4 %
      tầng 6  → 16,7 %      tầng 15 → 23,9 %  (bão hoà)

    Vì sao: π_t(i) rải đều trong [0,i), nên mỗi tầng vị trí trung bình giảm một
    nửa. Sau vài tầng chúng dồn hết về gần 0 và không lan thêm.

    ── 24 % CÓ ĐỦ KHÔNG ────────────────────────────────────────────────────

    Đủ cho mục đích. Kẻ gian giữ điểm mốc mỗi 1.000 chunk chỉ có sẵn 0,1 % số
    S; muốn dựng lại một vị trí nó phải tính ~24 % sector. So với 0,04 GIÂY khi
    không có fan-in, đó là bước nhảy khoảng 240.000 lần.

    Nhưng con số trong đặc tả phải sửa từ "phủ hết" thành "phủ ~24 %", và biên
    an toàn phải tính lại theo 24 % chứ không theo 100 %.
    """
    n = 20_000
    frontier = {n - 1}
    seen = set(frontier)
    for _ in range(15):
        nxt: set[int] = set()
        for i in frontier:
            for p in fanin_positions(i, REPLICA):
                if p not in seen:
                    seen.add(p)
                    nxt.add(p)
        frontier = nxt
        if not frontier:
            break
    ratio = len(seen) / n
    # Ngưỡng đặt theo SỐ ĐO, không theo phép đếm lý thuyết.
    assert ratio > 0.15, f"bao đóng chỉ phủ {ratio:.1%} — điểm mốc vẫn dùng được"
    print(f"\n  bao đóng bão hoà ở {ratio:.1%} sector (đặc tả từng ghi 100 %)")


def test_hai_ban_sao_co_do_thi_khac_nhau():
    """Trộn replica_id nên hai bản sao khác nhau có đồ thị phụ thuộc khác nhau."""
    a = fanin_positions(5000, b"\x01" * 32)
    b = fanin_positions(5000, b"\x02" * 32)
    assert a != b


if __name__ == "__main__":
    for fn in (test_fanin_khong_thoai_hoa, test_fanin_luon_tro_ve_truoc,
               test_bao_dong_lan_du_rong, test_hai_ban_sao_co_do_thi_khac_nhau):
        fn()
    print("  Tất cả đều đạt.")
