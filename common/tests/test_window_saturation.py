"""[SPEC §H.1.7] Nghẽn DA không được biến thành lợi nhuận của kẻ tấn công.

Bối cảnh. Hợp đồng trả hoa hồng 5 % của mức phạt cho ai nộp lá phạt hộ, vì lá
thưởng thì nút tự lo còn lá phạt thì không ai muốn nộp. Cơ chế đó giả định lá
phạt phản ánh gian lận THẬT.

Dưới nghẽn DA thì giả định đó sai: nút trung thực không đăng được bằng chứng và
bị phạt hàng loạt, nên kẻ gây nghẽn tự nộp lá phạt và THU hoa hồng. Khoản thu
tăng theo N, nên "chi phí tấn công > giá trị thu được" hỏng đúng lúc mạng lớn.

Cách vá KHÔNG phải hạ mức phạt — mức phạt còn phải chặn nút xoá dữ liệu, và hoa
hồng là tỉ lệ của nó. Cách vá là cắt phần THU khi có bằng cớ khách quan về nghẽn.
"""

import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "worker" / "src"))

from engram_common import constants as C
from engram_common.clock import PublicValues
from worker.coverage import prove_coverage

NS = bytes(29)


def test_cua_so_sach_thi_khong_bao_nghen():
    """Square nhỏ suốt cửa sổ nghĩa là Celestia còn rộng chỗ."""
    cov = prove_coverage(NS, [], 100, 300, square_roots=[4] * 200)
    assert cov.window_saturation == 0


def test_cua_so_bi_lap_day_thi_bao_nghen():
    """Mọi block đạt square tối đa → tín hiệu bão hoà cực đại."""
    cov = prove_coverage(NS, [], 100, 300, square_roots=[2048] * 200)
    assert cov.window_saturation == 255
    assert cov.window_saturation >= C.WINDOW_SATURATION_THRESHOLD


def test_nghen_mot_phan_duoi_nguong_thi_van_tra_hoa_hong():
    """Nửa cửa sổ đầy là tắc nghẽn tự nhiên, không phải tấn công có chủ đích.

    Ngưỡng 179/255 ≈ 70 % cố ý đặt cao: cắt hoa hồng là mất một cơ chế thật,
    nên chỉ cắt khi bằng cớ đủ mạnh.
    """
    cov = prove_coverage(NS, [], 100, 300, square_roots=[2048] * 100 + [4] * 100)
    assert cov.window_saturation < C.WINDOW_SATURATION_THRESHOLD


def test_bo_trong_thi_giu_nguyen_hanh_vi_cu():
    """Mô phỏng chưa dựng square thật thì coi như không nghẽn."""
    assert prove_coverage(NS, [], 100, 300).window_saturation == 0


def test_truong_moi_khong_lam_tang_calldata():
    """297 và 296 đều được đệm ABI lên 320, nên phí giao dịch cơ bản KHÔNG đổi.

    Đây là lý do vá này rẻ: nó không đụng tới bất kỳ số liệu calldata nào.
    """
    assert C.PUBLIC_VALUES_BYTES == 297
    assert 32 + ((C.PUBLIC_VALUES_BYTES + 31) // 32) * 32 == 352
    assert C.CALLDATA_BYTES == 868


def test_public_values_mang_duoc_tin_hieu():
    pv = PublicValues(1, b"\x01" * 32, b"\x02" * 32, 1, b"\x03" * 32, b"\x04" * 32,
                      b"\x05" * 32, b"\x06" * 32, b"\x07" * 20, b"\x08" * 32,
                      b"\x09" * 32, 5, 255)
    assert PublicValues.unpack(pv.pack()).window_saturation == 255
