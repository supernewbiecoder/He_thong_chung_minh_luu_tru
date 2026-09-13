"""Tầng DA: một giao diện, hai backend.

`MemoryDA` một mình thì mọi kết luận chỉ nói về một danh sách trong RAM. Ba thứ
mà thiết kế dựa vào đều thuộc về Celestia chứ không thuộc Engram, và chỉ backend
thật mới kiểm được: trường signer có được đồng thuận áp đặt không, namespace có
thật sự mở cho mọi người ghi không, và blob có lên được block trong cửa sổ không.
"""

import sys, pathlib, os

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest

from engram_common.blob import BlobHeader, BlobKind, build_namespace
from engram_common.da import CelestiaDA, DAError, MemoryDA, make_da

NS = build_namespace(BlobKind.BUNDLE, 1, 3)
HDR = BlobHeader(BlobKind.BUNDLE, 1_000_000, 3, b"\x01" * 20, b"\x02" * 32, 10)


def test_namespace_mo_ai_cung_ghi_duoc():
    """Không phải thiếu sót — đây là hành vi của Celestia, và là lý do worker
    phải lọc theo người ký."""
    da = MemoryDA()
    da.submit(NS, HDR, b"that", b"\x01" * 20)
    da.submit(NS, HDR, b"rac", b"\xbb" * 20)   # kẻ lạ, chữ ký của chính nó
    assert len(da.read(NS, da.height, da.height + 1)) == 2


def test_namespace_sai_do_dai_bi_tu_choi():
    with pytest.raises(DAError):
        MemoryDA().submit(b"\x00" * 5, HDR, b"x", b"\x01" * 20)


def test_signer_phai_20_byte():
    with pytest.raises(DAError):
        MemoryDA().submit(NS, HDR, b"x", b"\x01" * 3)


def test_doc_theo_khoang_chieu_cao_nua_mo():
    da = MemoryDA()
    h0 = da.height
    da.submit(NS, HDR, b"a", b"\x01" * 20)
    da.advance()
    da.submit(NS, HDR, b"b", b"\x01" * 20)
    assert len(da.read(NS, h0, h0 + 1)) == 1
    assert len(da.read(NS, h0, h0 + 2)) == 2


def test_khong_cong_bo_len_mang_chinh(monkeypatch):
    """Một lần chạy thử không được phép tiêu TIA thật."""
    monkeypatch.setenv("CELESTIA_NETWORK", "mainnet")
    with pytest.raises(DAError, match="mạng chính"):
        CelestiaDA()._guard_submit()


def test_mac_dinh_tat_cong_bo(monkeypatch):
    monkeypatch.delenv("CELESTIA_LOCAL_DEVNET", raising=False)
    monkeypatch.setenv("CELESTIA_NETWORK", "")
    with pytest.raises(DAError, match="đang tắt"):
        CelestiaDA()._guard_submit()


def test_devnet_loopback_thi_mo(monkeypatch):
    monkeypatch.setenv("CELESTIA_LOCAL_DEVNET", "1")
    CelestiaDA()._guard_submit()      # không ném


def test_chon_backend_theo_bien_moi_truong(monkeypatch):
    monkeypatch.setenv("ENGRAM_DA", "memory")
    assert isinstance(make_da(), MemoryDA)
    monkeypatch.setenv("ENGRAM_DA", "celestia")
    assert isinstance(make_da(), CelestiaDA)
    monkeypatch.setenv("ENGRAM_DA", "linh tinh")
    with pytest.raises(DAError):
        make_da()
