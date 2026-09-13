"""[T3.2] Eq. (1) ở tham số hiện tại: chưa kết luận được, và phải nói ra.

Đặc tả §F.2.1 tính sàn kẻ gian 38,4 phút theo giả định dựng lại TOÀN BỘ sector.
Bao đóng fan-in ĐO ĐƯỢC chỉ 23,9 %, nên sàn thật khoảng 18,1 phút. Cửa sổ nộp là
20 phút. Bất đẳng thức chỉ còn đúng nếu t_prove > 1,9 phút, mà t_prove chưa đo.
"""

import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from engram_common import constants as C
from engram_common.clock import window_safety_report, window_safety_ok


def test_chua_do_t_prove_thi_khong_ket_luan():
    r = window_safety_report(w_blocks=200, t_prove_s=None)
    assert r["left_ok"] is None and r["right_ok"] is None
    assert "CHƯA KẾT LUẬN" in r["verdict"]


def test_nguong_t_prove_toi_thieu_o_W_200():
    """20 phút cửa sổ − 18,1 phút dựng lại = 1,9 phút."""
    r = window_safety_report(w_blocks=200, t_prove_s=None)
    assert 100 < r["t_prove_min_required_s"] < 130


def test_t_prove_mot_phut_thi_KHONG_thoa():
    r = window_safety_report(w_blocks=200, t_prove_s=60)
    assert r["right_ok"] is False and r["verdict"] == "KHÔNG THOẢ"


def test_giam_W_xuong_90_block_thi_thoa():
    """Một trong ba đường sửa: giảm W xuống dưới 90 block."""
    assert window_safety_report(w_blocks=90, t_prove_s=60)["verdict"] == "THOẢ"


def test_mac_dinh_dung_san_DA_DINH_CHINH_khong_dung_san_dac_ta():
    """Dùng 38,4 phút là tự cho mình một biên an toàn không có thật."""
    r = window_safety_report(w_blocks=200, t_prove_s=60)
    assert r["t_regen_s"] == C.ADVERSARY_FLOOR_MINUTES_MEASURED * 60
    assert C.ADVERSARY_FLOOR_MINUTES_MEASURED < C.ADVERSARY_FLOOR_MINUTES_SPEC


def test_ham_bool_cu_van_chay():
    assert window_safety_ok(w_blocks=90, t_prove_s=60, t_regen_s=18.1 * 60)
